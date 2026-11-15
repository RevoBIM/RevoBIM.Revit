# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM System Offset - the direction prompt
#
# Opens after the second click, carrying the calculated
# distance in an editable box and the four directions as
# buttons. Pressing one closes the window and the offset
# runs; the pick loop then goes straight back to waiting for
# the next first click.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

import so_core
import so_ui
import theme as theme_module


DIRECTION_BUTTONS = (
    (u'up', 'UpButton'),
    (u'down', 'DownButton'),
    (u'left', 'LeftButton'),
    (u'right', 'RightButton'),
)


class OffsetPrompt(object):
    """Returns (distance_mm, direction), or None if cancelled."""

    def __init__(self, analysis, settings, tool_name=u'System Offset'):
        self.analysis = analysis
        self.tool_name = tool_name
        self.settings = settings
        self.answer = None
        self.theme_setting = so_core.to_text(settings.get('theme', 'revit'))

        self.window, self.applied = so_ui.load_window(
            'OffsetPrompt.xaml', self.theme_setting)

        so_ui.set_version(self.window)
        so_ui.load_icon(self.window)
        so_ui.attach_egg(self.window)
        so_ui.wire_theme_chip(self.window, self.theme_setting,
                              self._theme_changed)

        self._fill()
        self._wire()

    def find(self, name):
        return self.window.FindName(name)

    def _theme_changed(self, setting):
        """The chip is the only place the theme is set, so it
        writes straight through rather than waiting for an
        Apply this window does not have."""
        self.theme_setting = setting
        values = so_core.load_settings()
        values['theme'] = setting
        so_core.save_settings(values)

    def status(self, text):
        block = self.find('StatusText')
        if block is not None:
            block.Text = so_core.to_text(text)

    # -- opening state ----------------------------------------
    def _fill(self):
        analysis = self.analysis

        name = self.find('ToolNameText')
        if name is not None:
            name.Text = self.tool_name

        which = self.find('WhichWayText')
        if which is not None:
            which.Text = (u'Which way to step it'
                          if analysis.get('mode') == u'break'
                          else u'Which way')

        runs = len(analysis.get('bank') or [])
        if runs > 1 and which is not None:
            which.Text = which.Text + u'  ({0} runs)'.format(runs)

        box = self.find('DistanceBox')
        default_mm = analysis.get('default_distance_mm', 0.0)
        if box is not None:
            box.Text = u'{0:.0f}'.format(default_mm)
            try:
                box.SelectAll()
                box.Focus()
            except Exception:
                pass

        width = analysis.get('width_mm', 0.0)
        factor = so_core.as_float(self.settings.get('width_factor'), 1.0)
        note = self.find('DefaultNote')
        if note is not None:
            if width > 0:
                note.Text = (u'{0:g} x the {1:.0f}mm {2}, rounded up to {3:.0f}mm.'
                             .format(factor, width, analysis.get('kind') or u'service',
                                     so_core.ROUND_MM))
            else:
                note.Text = (u'That {0} carries no size to work from, so the '
                             u'minimum was used.'
                             .format(analysis.get('kind') or u'service'))

        room = self.find('RoomNote')
        if room is not None:
            largest = analysis.get('max_distance_mm')
            if largest is None:
                room.Text = (u'{0:.0f}mm between the clicks, square bends - '
                             u'any distance fits.'
                             .format(analysis.get('span_mm', 0.0)))
            else:
                room.Text = (u'{0:.0f}mm between the clicks at {1:.0f} degrees, '
                             u'so up to {2:.0f}mm fits.'
                             .format(analysis.get('span_mm', 0.0),
                                     analysis.get('angle_deg', 45.0),
                                     largest))
            if analysis.get('mode') == u'break':
                room.Text = room.Text + (
                    u' The run is cut at the second click and what lies '
                    u'beyond it stays put.')

        available = analysis.get('directions') or []
        for key, name in DIRECTION_BUTTONS:
            button = self.find(name)
            if button is None:
                continue
            allowed = key in available
            button.IsEnabled = allowed
            if not allowed:
                try:
                    button.ToolTip = (u'A vertical run has no {0}. '
                                      u'Use left or right.'.format(key))
                except Exception:
                    pass

        self.status(u'Pick a direction, or Escape to cancel this one.')

    # -- wiring ------------------------------------------------
    def _wire(self):
        for key, name in DIRECTION_BUTTONS:
            button = self.find(name)
            if button is None:
                continue
            button.Click += so_ui.ui_safe(
                lambda s, a, chosen=key: self._chose(chosen))

        for name in ('CancelButton', 'CloseButton'):
            button = self.find(name)
            if button is not None:
                button.Click += so_ui.ui_safe(lambda s, a: self._cancel())

        bar = self.find('HeaderBar')
        if bar is not None:
            @so_ui.ui_safe
            def on_drag(sender, args):
                try:
                    self.window.DragMove()
                except Exception:
                    pass
            bar.MouseLeftButtonDown += on_drag

        from System.Windows.Input import Key

        @so_ui.ui_safe
        def on_key(sender, args):
            if args.Key == Key.Escape:
                self._cancel()

        self.window.KeyDown += on_key

    # -- answering ---------------------------------------------
    def _distance(self):
        box = self.find('DistanceBox')
        text = so_core.to_text(box.Text).strip() if box is not None else u''
        try:
            value = float(text)
        except Exception:
            self.status(u'"{0}" is not a number.'.format(text))
            return None
        if value <= 0:
            self.status(u'The offset has to be more than nothing.')
            return None

        largest = self.analysis.get('max_distance_mm')
        if largest is not None and value > largest + 1.0e-6:
            self.status(u'{0:.0f}mm will not fit between the clicks - '
                        u'{1:.0f}mm is the most, or use 90 degree bends.'
                        .format(value, largest))
            return None
        return value

    def _chose(self, direction):
        value = self._distance()
        if value is None:
            return
        self.answer = (value, direction)
        self.window.Close()

    def _cancel(self):
        self.answer = None
        self.window.Close()

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception as error:
            so_ui.report_error(u'The offset prompt would not open', error)
            return None
        return self.answer


def ask(analysis, settings, tool_name=u'System Offset'):
    return OffsetPrompt(analysis, settings, tool_name).show()
