# -*- coding: utf-8 -*-
"""The themed prompt (Partial / Full) and the themed results window.

One layout, two modes. Modal, owned by Revit's main window.
"""
import io
import os
import traceback

import eim_clr  # noqa: F401  (assembly references first)
from System.IO import File, MemoryStream
from System.Windows import Visibility, WindowStartupLocation
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Input import Key
from System.Windows.Interop import WindowInteropHelper

import eim_core
import eim_theme
from eim_version import __version__

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(name):
    with io.open(os.path.join(HERE, name), 'r', encoding='utf-8') as fh:
        return fh.read()


def load_bitmap(name):
    """PNG from bytes - System.Uri moved assembly in Revit 2025, so never a
    UriSource. Cosmetic, so it can never take the tool down."""
    try:
        path = os.path.join(HERE, name)
        if not os.path.isfile(path):
            return None
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.StreamSource = MemoryStream(File.ReadAllBytes(path))
        bmp.EndInit()
        bmp.Freeze()
        return bmp
    except Exception:
        return None


class ExplodeWindow(object):
    """mode 'prompt' returns 'partial' / 'full' / None from show();
    mode 'result' just shows a report."""

    def __init__(self, settings, owner_handle, canvas_dark, log=None):
        self.settings = settings
        self.canvas_dark = canvas_dark
        self.log = log or (lambda m: None)
        self.choice = None
        self.mode = u'prompt'

        self.win = XamlReader.Parse(_read('ExplodePrompt.xaml'))
        self.win.Resources.MergedDictionaries.Add(XamlReader.Parse(_read('Theme.xaml')))
        self._apply_theme()

        names = ['HeaderBar', 'HeaderIcon', 'ThemeChip', 'ThemeChipText', 'VersionText',
                 'CloseButton', 'PromptPanel', 'SummaryText', 'SkipText', 'PartialButton',
                 'FullButton', 'PartialIcon', 'FullIcon', 'SelectResultsCheck', 'DebugCheck',
                 'ResultPanel', 'ResultTitle', 'ResultText', 'CancelButton', 'CancelText',
                 'StatusText']
        for n in names:
            setattr(self, n, self.win.FindName(n))

        self.VersionText.Text = u'v' + __version__
        for img, png in ((self.HeaderIcon, 'icon.png'), (self.PartialIcon, 'partial.png'),
                         (self.FullIcon, 'full.png')):
            bmp = load_bitmap(png)
            if bmp is not None:
                img.Source = bmp

        self.SelectResultsCheck.IsChecked = settings.get(u'select_results') == u'1'
        self.DebugCheck.IsChecked = settings.get(u'debug') == u'1'
        last = settings.get(u'last_mode')
        self.PartialButton.Tag = u'last' if last == u'partial' else None
        self.FullButton.Tag = u'last' if last == u'full' else None

        self.HeaderBar.MouseLeftButtonDown += self._guard(self._on_drag)
        self.ThemeChip.MouseLeftButtonDown += self._guard(self._on_theme_chip)
        self.CloseButton.MouseLeftButtonDown += self._guard(self._on_close)
        self.CancelButton.Click += self._guard(self._on_close)
        self.PartialButton.Click += self._guard(lambda s, e: self._pick(u'partial'))
        self.FullButton.Click += self._guard(lambda s, e: self._pick(u'full'))
        self.win.PreviewKeyDown += self._guard(self._on_key)

        try:
            if owner_handle:
                WindowInteropHelper(self.win).Owner = owner_handle
                self.win.WindowStartupLocation = WindowStartupLocation.CenterOwner
        except Exception:
            pass

    # ======================================================================
    # Plumbing
    # ======================================================================

    def _guard(self, fn):
        """WPF swallows exceptions raised in handlers - report them instead."""
        def handler(sender, args):
            try:
                fn(sender, args)
            except Exception:
                text = traceback.format_exc()
                self.log(u'ui: ' + text)
                try:
                    self.StatusText.Text = u'Error: ' + text.strip().splitlines()[-1]
                except Exception:
                    pass
        return handler

    def _apply_theme(self):
        name = eim_core.resolve_theme(self.settings.get(u'theme'), self.canvas_dark)
        eim_theme.apply_palette(self.win, name)
        try:
            self.ThemeChipText.Text = eim_core.theme_chip_label(self.settings.get(u'theme'))
        except Exception:
            pass

    def _on_drag(self, sender, args):
        try:
            self.win.DragMove()
        except Exception:
            pass

    def _on_theme_chip(self, sender, args):
        args.Handled = True
        self.settings[u'theme'] = eim_core.next_theme_setting(self.settings.get(u'theme'))
        self._apply_theme()
        label = eim_core.theme_chip_label(self.settings[u'theme'])
        if self.settings[u'theme'] == u'follow':
            canvas = u'unknown' if self.canvas_dark is None else (u'dark' if self.canvas_dark else u'light')
            self.StatusText.Text = u'Theme follows Revit\'s canvas ({0})'.format(canvas)
        else:
            self.StatusText.Text = u'Theme: ' + label

    def _on_close(self, sender, args):
        try:
            args.Handled = True
        except Exception:
            pass
        self.choice = None
        self.win.Close()

    def _on_key(self, sender, args):
        if args.Key == Key.Escape:
            args.Handled = True
            self.choice = None
            self.win.Close()
        elif self.mode == u'prompt' and args.Key == Key.P and self.PartialButton.IsEnabled:
            args.Handled = True
            self._pick(u'partial')
        elif self.mode == u'prompt' and args.Key == Key.F and self.FullButton.IsEnabled:
            args.Handled = True
            self._pick(u'full')
        elif self.mode == u'result' and args.Key == Key.Enter:
            args.Handled = True
            self.win.Close()

    def _pick(self, mode):
        self.choice = mode
        self.settings[u'last_mode'] = mode
        self.win.Close()

    def _store_ticks(self):
        self.settings[u'select_results'] = u'1' if self.SelectResultsCheck.IsChecked else u'0'
        self.settings[u'debug'] = u'1' if self.DebugCheck.IsChecked else u'0'

    # ======================================================================
    # Modes
    # ======================================================================

    def prompt(self, headline, detail, can_run):
        self.mode = u'prompt'
        self.SummaryText.Text = headline
        self.SkipText.Text = detail
        self.SkipText.Visibility = Visibility.Visible if detail else Visibility.Collapsed
        self.PartialButton.IsEnabled = can_run
        self.FullButton.IsEnabled = can_run
        self.StatusText.Text = (u'Pick one - it runs on every selected import symbol'
                                if can_run else u'Nothing to explode')
        self.win.ShowDialog()
        self._store_ticks()
        return self.choice

    def result(self, title, lines):
        self.mode = u'result'
        self.PromptPanel.Visibility = Visibility.Collapsed
        self.ResultPanel.Visibility = Visibility.Visible
        self.ResultTitle.Text = title
        self.ResultText.Text = u'\n'.join(lines)
        self.CancelText.Text = u'Close'
        self.StatusText.Text = u'The ones not exploded are left selected'
        self.win.ShowDialog()
