# -*- coding: utf-8 -*-
"""3D Align - the results window, the settings window, and their chrome.

Both windows are modal. The chrome (drag, close, theme chip, version, logo,
full screen, resize grips) is the house chrome from the theme reference.
"""
import a3d_clr  # noqa: F401  - assemblies first, always

import inspect
import io
import os
import traceback

from System.Diagnostics import Process
from System.IO import File, MemoryStream
from System.Windows import (GridLength, GridUnitType,
                            PresentationSource, SystemParameters, TextWrapping,
                            Thickness, CornerRadius, HorizontalAlignment,
                            VerticalAlignment, FontWeights)
from System.Windows.Controls import Border, ColumnDefinition, Grid, TextBlock
from System.Windows.Forms import Screen
from System.Windows.Input import Key
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import Color, SolidColorBrush
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage

import a3d_settings as cfg
import theme

HERE = os.path.dirname(os.path.abspath(__file__))

KINDS = {
    'ok': (u'ALIGNED', 'Green', 'RowOk'),
    'already': (u'ALREADY', 'TextMuted', 'RowQuiet'),
    'warn': (u'CHECK', 'Orange', 'RowWarn'),
    'refused': (u'REFUSED', 'Red', 'RowBad'),
    'failed': (u'FAILED', 'Red', 'RowBad'),
}

# (heading, star weight, minimum px)
COLUMNS = (
    (u'', 0, 84),
    (u'First (align to)', 2, 150),
    (u'Moved', 2, 150),
    (u'How', 2, 160),
    (u'Distance', 0, 76),
    (u'Result', 3, 200),
)


# ==========================================================================
# plumbing
# ==========================================================================

def log_ui_error(text):
    try:
        folder = cfg.data_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with io.open(cfg.error_path(), 'w', encoding='utf-8') as handle:
            handle.write(u'{0}'.format(text))
    except Exception:
        pass


def guard(function):
    """WPF swallows exceptions raised in a handler; this writes them down."""
    def handler(sender, args):
        try:
            function(sender, args)
        except Exception:
            log_ui_error(traceback.format_exc())
    return handler


def read_text(name):
    with io.open(os.path.join(HERE, name), 'r', encoding='utf-8') as handle:
        return handle.read()


def load_window(name):
    window = XamlReader.Parse(read_text(name))
    try:
        window.Resources.MergedDictionaries.Add(XamlReader.Parse(read_text('Theme.xaml')))
    except Exception:
        log_ui_error(traceback.format_exc())
    return window


def brush(hex_value):
    value = hex_value.lstrip('#')
    result = SolidColorBrush(Color.FromRgb(int(value[0:2], 16), int(value[2:4], 16),
                                           int(value[4:6], 16)))
    try:
        result.Freeze()
    except Exception:
        pass
    return result


def set_owner(window):
    """Owned by Revit's main window so it floats above Revit, not behind it."""
    try:
        WindowInteropHelper(window).Owner = Process.GetCurrentProcess().MainWindowHandle
    except Exception:
        pass


def load_image(path):
    """From bytes, never a Uri: System.Uri moved assembly in Revit 2025."""
    image = BitmapImage()
    image.BeginInit()
    image.StreamSource = MemoryStream(File.ReadAllBytes(path))
    image.CacheOption = BitmapCacheOption.OnLoad
    image.EndInit()
    return image


def _argument_names(function):
    for name in ('getfullargspec', 'getargspec'):
        reader = getattr(inspect, name, None)
        if reader is None:
            continue
        try:
            return list(reader(function).args)
        except Exception:
            continue
    return []


def attach_egg(window, logo, mode):
    """The easter egg, armed on the logo of the main window only. A soft
    dependency: anything going wrong here is swallowed."""
    try:
        if logo is None:
            return False
        egg_hook = None
        for name in ('revobim.egg.egg_hook', 'egg_hook'):
            try:
                egg_hook = __import__(name, fromlist=['egg_hook'])
                break
            except Exception:
                continue
        attach = getattr(egg_hook, 'attach', None) if egg_hook is not None else None
        if attach is None:
            return False
        values = []
        for argument in _argument_names(attach):
            low = argument.lower()
            if low == 'self':
                continue
            if any(word in low for word in ('logo', 'element', 'target', 'control', 'image')):
                values.append(logo)
            elif any(word in low for word in ('window', 'host', 'owner')):
                values.append(window)
            elif 'theme' in low:
                values.append(mode)
            else:
                break
        attach(*values)
        return True
    except Exception:
        return False


# ==========================================================================
# chrome
# ==========================================================================

class Chrome(object):
    """Drag, close, theme chip, version, logo, full screen and grips."""

    def __init__(self, window, settings, allow_full=True, on_theme=None, egg=False):
        self.window = window
        self.settings = settings
        self.allow_full = allow_full
        self.on_theme = on_theme
        self.full = False
        self.saved_bounds = None
        self.find = window.FindName
        self.mode = 'dark'
        self.apply_theme()
        self.wire(egg)

    # ---- theme -------------------------------------------------------
    def apply_theme(self):
        self.mode = theme.resolve(self.settings.get('theme', 'follow'))
        for key, value in theme.palette(self.mode).items():
            self.window.Resources[key] = brush(value)
        label = self.find('ThemeLabel')
        if label is not None:
            label.Text = theme.chip_label(self.settings.get('theme'), self.mode)
        chip = self.find('ThemeChip')
        if chip is not None:
            chip.ToolTip = theme.chip_tooltip(self.settings.get('theme'), self.mode)
        if self.on_theme is not None:
            self.on_theme(self.mode)

    def set_theme(self, choice):
        self.settings['theme'] = choice
        cfg.save_theme(choice)
        self.apply_theme()

    def on_chip(self, sender, args):
        self.set_theme(cfg.next_theme(self.settings.get('theme', 'follow')))

    # ---- wiring ------------------------------------------------------
    def wire(self, egg):
        version = self.find('VersionText')
        if version is not None:
            version.Text = u'v{0}'.format(cfg.__version__)
        logo = self.find('Logo')
        try:
            logo.Source = load_image(os.path.join(HERE, 'icon.png'))
        except Exception:
            pass
        chip = self.find('ThemeChip')
        if chip is not None:
            chip.Click += guard(self.on_chip)
        close = self.find('CloseBtn')
        if close is not None:
            close.Click += guard(lambda s, a: self.window.Close())
        header = self.find('Header')
        if header is not None:
            header.MouseLeftButtonDown += guard(self.on_header_down)
        full = self.find('FullBtn')
        if full is not None:
            full.Click += guard(lambda s, a: self.toggle_full())
        self.window.PreviewKeyDown += guard(self.on_key)
        self.wire_grips()
        if egg:
            attach_egg(self.window, logo, self.mode)

    def on_header_down(self, sender, args):
        if args.ClickCount == 2 and self.allow_full:
            self.toggle_full()
            return
        if self.full:
            self.leave_full()
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_key(self, sender, args):
        if args.Key == Key.Escape:
            args.Handled = True
            if self.full:
                self.leave_full()
            else:
                self.window.Close()
        elif args.Key == Key.F11 and self.allow_full:
            args.Handled = True
            self.toggle_full()

    # ---- full screen, by bounds --------------------------------------
    def work_area(self):
        try:
            area = Screen.FromHandle(WindowInteropHelper(self.window).Handle).WorkingArea
            matrix = PresentationSource.FromVisual(self.window).CompositionTarget.TransformToDevice
            sx = matrix.M11 or 1.0
            sy = matrix.M22 or 1.0
            return area.X / sx, area.Y / sy, area.Width / sx, area.Height / sy
        except Exception:
            area = SystemParameters.WorkArea
            return area.X, area.Y, area.Width, area.Height

    def toggle_full(self):
        if self.full:
            self.leave_full()
            return
        w = self.window
        self.saved_bounds = (w.Left, w.Top, w.Width, w.Height)
        left, top, width, height = self.work_area()
        w.Left, w.Top, w.Width, w.Height = left, top, width, height
        self.full = True

    def leave_full(self):
        if self.full and self.saved_bounds is not None:
            w = self.window
            w.Left, w.Top, w.Width, w.Height = self.saved_bounds
        self.full = False

    # ---- grips: a borderless transparent window has no frame to grab --
    def wire_grips(self):
        sides = {'GripL': (1, 0, 0, 0), 'GripR': (0, 0, 1, 0), 'GripT': (0, 1, 0, 0),
                 'GripB': (0, 0, 0, 1), 'GripTL': (1, 1, 0, 0), 'GripTR': (0, 1, 1, 0),
                 'GripBL': (1, 0, 0, 1), 'GripBR': (0, 0, 1, 1)}
        for name, edges in sides.items():
            grip = self.find(name)
            if grip is not None:
                grip.DragDelta += guard(self.make_grip_handler(edges))

    def make_grip_handler(self, edges):
        left, top, right, bottom = edges

        def on_drag(sender, args):
            w = self.window
            self.full = False
            dx = args.HorizontalChange
            dy = args.VerticalChange
            if right:
                w.Width = max(w.MinWidth, w.Width + dx)
            if bottom:
                w.Height = max(w.MinHeight, w.Height + dy)
            if left:
                width = max(w.MinWidth, w.Width - dx)
                w.Left = w.Left + (w.Width - width)
                w.Width = width
            if top:
                height = max(w.MinHeight, w.Height - dy)
                w.Top = w.Top + (w.Height - height)
                w.Height = height
        return on_drag


# ==========================================================================
# results
# ==========================================================================

def themed_text(text, key='Text', bold=False, wrap=True):
    block = TextBlock()
    block.Text = text
    block.VerticalAlignment = VerticalAlignment.Center
    block.Margin = Thickness(0, 0, 10, 0)
    if wrap:
        block.TextWrapping = TextWrapping.Wrap
    if bold:
        block.FontWeight = FontWeights.SemiBold
    block.SetResourceReference(TextBlock.ForegroundProperty, key)
    return block


def column_grid():
    grid = Grid()
    for _heading, weight, minimum in COLUMNS:
        column = ColumnDefinition()
        if weight:
            column.Width = GridLength(weight, GridUnitType.Star)
        else:
            column.Width = GridLength(minimum)
        column.MinWidth = minimum
        grid.ColumnDefinitions.Add(column)
    return grid


def place(grid, element, index):
    Grid.SetColumn(element, index)
    grid.Children.Add(element)


def pill(kind):
    label, colour, _row = KINDS.get(kind, KINDS['failed'])
    border = Border()
    border.CornerRadius = CornerRadius(3)
    border.Padding = Thickness(6, 1, 6, 1)
    border.Margin = Thickness(0, 0, 10, 0)
    border.HorizontalAlignment = HorizontalAlignment.Left
    border.VerticalAlignment = VerticalAlignment.Center
    border.SetResourceReference(Border.BackgroundProperty, colour)
    text = themed_text(label, 'OnAccent', bold=True, wrap=False)
    text.Margin = Thickness(0)
    text.FontSize = 10.5
    border.Child = text
    return border


def build_rows(window, rows):
    heading = column_grid()
    for index, column in enumerate(COLUMNS):
        place(heading, themed_text(column[0], 'TextMuted', bold=True, wrap=False), index)
    window.FindName('HeadingRow').Child = heading

    panel = window.FindName('Rows')
    for row in rows:
        _label, _colour, tint = KINDS.get(row['kind'], KINDS['failed'])
        grid = column_grid()
        place(grid, pill(row['kind']), 0)
        place(grid, themed_text(row['first']), 1)
        place(grid, themed_text(row['second']), 2)
        place(grid, themed_text(row['mode'] or u'-', 'TextMuted'), 3)
        moved = u'-' if row['moved_mm'] is None else u'{0:.1f} mm'.format(row['moved_mm'])
        place(grid, themed_text(moved, wrap=False), 4)
        place(grid, themed_text(row['note']), 5)
        border = Border()
        border.Padding = Thickness(8, 6, 8, 6)
        border.BorderThickness = Thickness(0, 0, 0, 1)
        border.SetResourceReference(Border.BackgroundProperty, tint)
        border.SetResourceReference(Border.BorderBrushProperty, 'Edge')
        border.Child = grid
        panel.Children.Add(border)


def summary(rows):
    counts = {}
    for row in rows:
        counts[row['kind']] = counts.get(row['kind'], 0) + 1
    parts = []
    for kind, words in (('ok', u'aligned'), ('warn', u'aligned - check'),
                        ('already', u'already aligned'), ('refused', u'refused'),
                        ('failed', u'failed')):
        if counts.get(kind):
            parts.append(u'{0} {1}'.format(counts[kind], words))
    return u', '.join(parts) or u'Nothing aligned'


def show_results(rows, settings):
    window = load_window('Align3DResults.xaml')
    chrome = Chrome(window, settings, allow_full=True, egg=True)
    build_rows(window, rows)
    window.FindName('StatusText').Text = summary(rows) + u'. Debug log: ' + cfg.debug_path()
    window.FindName('OkBtn').Click += guard(lambda s, a: window.Close())

    def on_settings(sender, args):
        show_settings()
        chrome.settings['theme'] = cfg.load().get('theme', 'follow')
        chrome.apply_theme()
    window.FindName('SettingsChip').Click += guard(on_settings)
    set_owner(window)
    window.ShowDialog()


# ==========================================================================
# settings
# ==========================================================================

RADIOS = (
    ('keep_running', (('on', 'KeepOn'), ('off', 'KeepOff'))),
    ('show_results', (('needs_look', 'ShowLook'), ('always', 'ShowAlways'), ('never', 'ShowNever'))),
    ('on_refusal', (('detach', 'RefDetach'), ('leave', 'RefLeave'))),
    ('theme', (('follow', 'ThemeFollow'), ('dark', 'ThemeDark'), ('light', 'ThemeLight'))),
)


def show_settings(settings=None):
    """Modal. True if Apply saved them."""
    settings = dict(settings or cfg.load())
    window = load_window('Align3DSettings.xaml')
    find = window.FindName
    state = {'loading': True, 'saved': False}

    def push_radios(key=None):
        for setting, options in RADIOS:
            if key is not None and setting != key:
                continue
            for value, name in options:
                find(name).IsChecked = settings.get(setting) == value

    def on_theme(mode):
        if not state['loading']:
            state['loading'] = True
            try:
                push_radios('theme')
            finally:
                state['loading'] = False

    chrome = Chrome(window, settings, allow_full=False, on_theme=on_theme)
    push_radios()
    find('MaxMove').Text = settings.get('max_move_mm', cfg.DEFAULTS['max_move_mm'])
    find('DebugTick').IsChecked = cfg.is_on(settings, 'debug')
    state['loading'] = False

    def make_theme_handler(value):
        def handler(sender, args):
            if not state['loading'] and settings.get('theme') != value:
                chrome.set_theme(value)
        return handler
    for value, name in dict(RADIOS)['theme']:
        find(name).Checked += guard(make_theme_handler(value))

    def on_apply(sender, args):
        chosen = dict(settings)
        for setting, options in RADIOS:
            for value, name in options:
                if find(name).IsChecked:
                    chosen[setting] = value
        limit = cfg.clean_value('max_move_mm', find('MaxMove').Text)
        if limit is None:
            status = find('StatusText')
            status.Text = u'The largest move has to be a number of millimetres, 0 or more.'
            status.SetResourceReference(TextBlock.ForegroundProperty, 'Red')
            return
        chosen['max_move_mm'] = limit
        chosen['debug'] = 'on' if find('DebugTick').IsChecked else 'off'
        if cfg.save(chosen):
            state['saved'] = True
            window.Close()
        else:
            status = find('StatusText')
            status.Text = u'Could not write ' + cfg.settings_path()
            status.SetResourceReference(TextBlock.ForegroundProperty, 'Red')

    find('ApplyBtn').Click += guard(on_apply)
    find('CancelBtn').Click += guard(lambda s, a: window.Close())
    set_owner(window)
    window.ShowDialog()
    return state['saved']
