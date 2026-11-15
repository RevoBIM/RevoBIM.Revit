# -*- coding: utf-8 -*-
u"""Project Browser Pro - the settings window.

Heading colours (Colour / Greyscale / Custom - the same three the colour
button cycles), highlighted rows (fill and text for each theme, bold or
not) and the user's own colours (offered wherever a colour is picked).

Modal; nothing is saved until Save, which hands back only the settings
this window owns. The browser saves them and tells the other browsers.
"""
import pbp_clr  # noqa: F401
from System.Windows.Input import Key
from System.Windows.Controls import Button
from System.Windows import Thickness

import pbp_ui
import pbp_theme
import pbp_settings
from pbp_ui import find, safe
from pbp_version import __version__

OWNED = (u'colour', u'custom_colours', u'highlight_bold') + pbp_settings.HIGHLIGHT_KEYS


class SettingsWindow(object):

    def __init__(self, settings, theme_name):
        self.values = dict((key, settings.get(key, pbp_settings.DEFAULTS[key])) for key in OWNED)
        self.values[u'colour'] = pbp_settings.colour_mode(self.values[u'colour'])
        self.custom = pbp_settings.custom_colours(self.values)
        self.result = None
        self.window = pbp_ui.load_xaml(u'Settings.xaml')
        pbp_theme.apply(self.window, theme_name)
        w = self.window
        find(w, u'VersionText').Text = u'v' + __version__
        logo = pbp_ui.logo_image()
        if logo is not None:
            find(w, u'LogoImage').Source = logo
        self.modes = {u'colour': find(w, u'ModeColour'), u'grey': find(w, u'ModeGrey'),
                      u'custom': find(w, u'ModeCustom')}
        self.bold = find(w, u'BoldTick')
        self.swatches = find(w, u'CustomSwatches')
        self.samples = {u'dark': (find(w, u'DarkSample'), find(w, u'DarkSampleText')),
                        u'light': (find(w, u'LightSample'), find(w, u'LightSampleText'))}
        for mode, radio in self.modes.items():
            radio.Checked += safe(self._mode(mode), u'settings mode')
        self.bold.Checked += safe(self._bold, u'settings bold')
        self.bold.Unchecked += safe(self._bold, u'settings bold')
        for name, key in ((u'DarkFill', u'highlight_dark'), (u'DarkText', u'highlight_dark_text'),
                          (u'LightFill', u'highlight_light'), (u'LightText', u'highlight_light_text')):
            find(w, name).Click += safe(self._picker(key), u'settings ' + name)
        find(w, u'AddCustom').Click += safe(self._add_custom, u'settings add colour')
        find(w, u'ResetButton').Click += safe(self._reset, u'settings reset')
        find(w, u'SaveButton').Click += safe(self._save, u'settings save')
        find(w, u'CancelButton').Click += safe(self._cancel, u'settings cancel')
        find(w, u'CloseButton').Click += safe(self._cancel, u'settings close')
        find(w, u'Header').MouseLeftButtonDown += safe(self._drag, u'settings drag')
        w.PreviewKeyDown += safe(self._key, u'settings key')
        self._load()

    # ---- state to screen ----
    def _load(self):
        self.modes[self.values[u'colour']].IsChecked = True
        self.bold.IsChecked = pbp_settings.as_bool(self.values[u'highlight_bold'])
        self._paint_samples()
        self._paint_custom()

    def _paint_samples(self):
        from System.Windows import FontWeights
        bold = pbp_settings.as_bool(self.values[u'highlight_bold'])
        for theme, (border, text) in self.samples.items():
            border.Background = pbp_theme.brush(self.values[u'highlight_' + theme])
            text.Foreground = pbp_theme.brush(self.values[u'highlight_{0}_text'.format(theme)])
            text.FontWeight = FontWeights.Bold if bold else FontWeights.Normal

    def _paint_custom(self):
        self.swatches.Children.Clear()
        for colour in self.custom:
            swatch = Button()
            pbp_ui.set_style(swatch, u'SwatchButton')
            swatch.Background = pbp_theme.brush(colour)
            swatch.Margin = Thickness(0, 0, 4, 4)
            swatch.ToolTip = colour + u' - right click to remove'
            swatch.MouseRightButtonUp += safe(self._dropper(colour), u'settings drop colour')
            self.swatches.Children.Add(swatch)

    # ---- handlers ----
    def _mode(self, mode):
        def checked(sender, args):
            self.values[u'colour'] = mode
        return checked

    def _bold(self, sender, args):
        self.values[u'highlight_bold'] = u'1' if self.bold.IsChecked else u'0'
        self._paint_samples()

    def _picker(self, key):
        def pick(sender, args):
            import pbp_orgwin
            colour = pbp_orgwin.pick_colour(self.values[key])
            if colour:
                self.set_colour(key, colour)
        return pick

    def set_colour(self, key, colour):
        colour = pbp_settings.hex_colour(colour)
        if colour and key in pbp_settings.HIGHLIGHT_KEYS:
            self.values[key] = colour
            self._paint_samples()

    def _add_custom(self, sender, args):
        import pbp_orgwin
        self.add_custom(pbp_orgwin.pick_colour())

    def add_custom(self, colour):
        colour = pbp_settings.hex_colour(colour)
        if colour and colour not in self.custom:
            self.custom.append(colour)
            self._paint_custom()

    def _dropper(self, colour):
        def drop(sender, args):
            args.Handled = True
            if colour in self.custom:
                self.custom.remove(colour)
                self._paint_custom()
        return drop

    def _reset(self, sender, args):
        for key in pbp_settings.HIGHLIGHT_KEYS + (u'highlight_bold',):
            self.values[key] = pbp_settings.DEFAULTS[key]
        self.bold.IsChecked = pbp_settings.as_bool(self.values[u'highlight_bold'])
        self._paint_samples()

    def _save(self, sender, args):
        pbp_settings.set_custom_colours(self.values, self.custom)
        self.result = dict(self.values)
        self.window.Close()

    def _cancel(self, sender, args):
        self.result = None
        self.window.Close()

    def _drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    def _key(self, sender, args):
        if args.Key == Key.Escape:
            args.Handled = True
            self._cancel(None, None)

    def run(self):
        pbp_ui.own(self.window)
        self.window.ShowDialog()
        return self.result


def ask(settings, theme_name):
    u"""The changed settings this window owns, or None when cancelled."""
    return SettingsWindow(settings, theme_name).run()
