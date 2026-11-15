# -*- coding: utf-8 -*-
# ==========================================================
# RevoBIM Click System - the bend angle prompt
#
# Opens after the run is chosen and before the click that
# places the next corner, so every bend can have its own
# angle. Ticking "use this angle for the rest of the run"
# keeps it and the prompt stops appearing, which is what
# makes drawing a square route four clicks rather than eight.
# ==========================================================

import so_clr  # noqa: F401  assembly references first

import so_core
import so_ui


STANDARD = ((u'Angle90', 90.0), (u'Angle45', 45.0),
            (u'Angle30', 30.0), (u'Angle225', 22.5))

MIN_ANGLE = 5.0
MAX_ANGLE = 90.0
MIN_LENGTH_MM = 10.0


class AnglePrompt(object):
    """What to do next. One of:

        ('horizontal', angle, length_mm)   go and click corners
        ('vertical', way, mm, deg, lead)   go and click, then rise
        None                               finish

    plus the "keep these" tick, which is returned alongside.

    length_mm is None where the box was left blank, meaning the
    new piece runs to wherever the next click lands.

    A tile SELECTS an angle rather than committing it, and the
    green button is what goes back to Revit. That matters
    because this window is reached mid-route by pressing
    Escape: a tile that committed the moment it was pressed
    would leave no way to set an angle and a length in the same
    visit, and no room for a second thing to press at all.
    """

    def __init__(self, settings, angle=90.0, keep=True, bank=0,
                 length_mm=None, height_mm=500.0, rise_angle=45.0,
                 lead_mm=500.0):
        self.settings = settings
        self.answer = None
        self.theme_setting = so_core.to_text(settings.get('theme', 'revit'))
        self.window, self.applied = so_ui.load_window(
            'AnglePrompt.xaml', self.theme_setting)

        so_ui.set_version(self.window)
        so_ui.load_icon(self.window)
        so_ui.attach_egg(self.window)
        so_ui.wire_theme_chip(self.window, self.theme_setting)

        box = self.find('ManualBox')
        if box is not None:
            box.Text = u'{0:g}'.format(angle)

        length_box = self.find('LengthBox')
        if length_box is not None:
            length_box.Text = (u'' if not length_mm
                               else u'{0:g}'.format(length_mm))

        height_box = self.find('HeightBox')
        if height_box is not None:
            height_box.Text = u'{0:g}'.format(height_mm or 500.0)

        rise_box = self.find('RiseAngleBox')
        if rise_box is not None:
            rise_box.Text = u'{0:g}'.format(rise_angle or 45.0)

        lead_box = self.find('LeadBox')
        if lead_box is not None:
            lead_box.Text = u'{0:g}'.format(lead_mm or 0.0)


        self._mark(angle)

        keep_check = self.find('KeepCheck')
        if keep_check is not None:
            keep_check.IsChecked = bool(keep)

        note = self.find('BankNote')
        if note is not None:
            if bank > 1:
                note.Text = (u'{0} runs are being routed together. They stay '
                             u'parallel and keep their spacing round every '
                             u'corner.'.format(bank))
            else:
                note.Text = u'Applies to the corner your next click places.'

        self.status(u'Place bends, or take the run up or down. Finish to stop.')
        self._wire()

    def find(self, name):
        return self.window.FindName(name)

    def status(self, text):
        block = self.find('StatusText')
        if block is not None:
            block.Text = so_core.to_text(text)

    def _mark(self, angle):
        """Show which of the standard angles is in play."""
        for name, value in STANDARD:
            button = self.find(name)
            if button is None:
                continue
            chosen = abs(value - float(angle)) < 1.0e-6
            try:
                button.Style = self.window.Resources[
                    'DirTileOn' if chosen else 'DirTile']
            except Exception:
                pass

    def _keep(self):
        check = self.find('KeepCheck')
        try:
            return bool(check.IsChecked) if check is not None else True
        except Exception:
            return True

    def _wire(self):
        for name, value in STANDARD:
            button = self.find(name)
            if button is None:
                continue
            button.Click += so_ui.ui_safe(
                lambda s, a, chosen=value: self._pick(chosen))

        place = self.find('PlaceHorizontalButton')
        if place is not None:
            place.Click += so_ui.ui_safe(lambda s, a: self._horizontal())

        for name, way in (('SetUpButton', u'up'), ('SetDownButton', u'down')):
            button = self.find(name)
            if button is not None:
                button.Click += so_ui.ui_safe(
                    lambda s, a, chosen=way: self._vertical(chosen))

        for name in ('CancelButton', 'CloseButton'):
            button = self.find(name)
            if button is not None:
                button.Click += so_ui.ui_safe(lambda s, a: self._finish())

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
                self._finish()
            elif args.Key == Key.Enter:
                self._horizontal()

        self.window.KeyDown += on_key

    def _pick(self, angle):
        """A tile fills the angle in and lights up. It does not
        commit - Apply does."""
        box = self.find('ManualBox')
        if box is not None:
            box.Text = u'{0:g}'.format(angle)
        self._mark(angle)
        self.status(u'{0:g} degrees. Place Horizontal Bends to carry on.'
                    .format(angle))

    def _read_angle(self):
        box = self.find('ManualBox')
        text = so_core.to_text(box.Text).strip() if box is not None else u''
        try:
            value = float(text)
        except Exception:
            self.status(u'"{0}" is not an angle.'.format(text))
            return None
        if value < MIN_ANGLE or value > MAX_ANGLE:
            self.status(u'The angle has to be between {0:g} and {1:g} degrees.'
                        .format(MIN_ANGLE, MAX_ANGLE))
            return None
        return value

    def _read_length(self):
        """Blank means "run to the click", which is not an error."""
        box = self.find('LengthBox')
        text = so_core.to_text(box.Text).strip() if box is not None else u''
        if not text:
            return True, None
        try:
            value = float(text)
        except Exception:
            self.status(u'"{0}" is not a length. Leave it blank to run to '
                        u'the click.'.format(text))
            return False, None
        if value < MIN_LENGTH_MM:
            self.status(u'A length under {0:g}mm has nothing to bend from.'
                        .format(MIN_LENGTH_MM))
            return False, None
        return True, value

    def _read_height(self):
        box = self.find('HeightBox')
        text = so_core.to_text(box.Text).strip() if box is not None else u''
        try:
            value = float(text)
        except Exception:
            self.status(u'"{0}" is not a height.'.format(text))
            return None
        if abs(value) < MIN_LENGTH_MM:
            self.status(u'A height under {0:g}mm has nothing to bend into.'
                        .format(MIN_LENGTH_MM))
            return None
        return abs(value)

    def _horizontal(self):
        angle = self._read_angle()
        if angle is None:
            return
        ok, length = self._read_length()
        if not ok:
            return
        self.answer = ((u'horizontal', angle, length), self._keep())
        self.window.Close()

    def _read_rise_angle(self):
        box = self.find('RiseAngleBox')
        text = so_core.to_text(box.Text).strip() if box is not None else u''
        try:
            value = float(text)
        except Exception:
            self.status(u'"{0}" is not an angle.'.format(text))
            return None
        if value < MIN_ANGLE or value > MAX_ANGLE:
            self.status(u'The rise angle has to be between {0:g} and {1:g} '
                        u'degrees.'.format(MIN_ANGLE, MAX_ANGLE))
            return None
        return value

    def _read_lead(self):
        box = self.find('LeadBox')
        text = so_core.to_text(box.Text).strip() if box is not None else u''
        if not text:
            return True, 0.0
        try:
            value = float(text)
        except Exception:
            self.status(u'"{0}" is not a distance.'.format(text))
            return False, None
        if value < 0:
            self.status(u'The run on cannot be negative.')
            return False, None
        return True, value

    def _vertical(self, way):
        height = self._read_height()
        if height is None:
            return
        angle = self._read_rise_angle()
        if angle is None:
            return
        ok, lead = self._read_lead()
        if not ok:
            return
        self.answer = ((u'vertical', way, height, angle, lead), self._keep())
        self.window.Close()

    def _finish(self):
        self.answer = None
        self.window.Close()

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception as error:
            so_ui.report_error(u'The angle prompt would not open', error)
            return None
        return self.answer


def ask(settings, angle=90.0, keep=True, bank=0, length_mm=None,
        height_mm=500.0, rise_angle=45.0, lead_mm=500.0):
    return AnglePrompt(settings, angle, keep, bank, length_mm, height_mm,
                       rise_angle, lead_mm).show()
