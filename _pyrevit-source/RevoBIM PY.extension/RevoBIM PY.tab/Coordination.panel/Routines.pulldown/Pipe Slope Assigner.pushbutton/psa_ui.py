# -*- coding: utf-8 -*-
"""RevoBIM Pipe Slope Assigner - the windows.

XAML loading, theming, the borderless chrome, the easter egg on the logo, the
prompt and the results report. Every handler goes through ui_safe(), so a
button that throws says so in the status line and the error file rather than
doing nothing - a silent handler is indistinguishable from a dead button.
"""

import psa_clr  # noqa: F401  (assemblies before any System.* name)

import io
import os
import traceback

from System.IO import MemoryStream, File
from System.Windows import Visibility, Thickness, TextWrapping
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Controls import Border, TextBlock, DockPanel, Dock

import psa_core as core
import psa_theme as theme

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(HERE, 'icon.png')


# ====================== errors ======================

def write_error(text):
    try:
        folder = core.settings_folder()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = io.open(os.path.join(folder, core.ERROR_FILE), 'w', encoding='utf-8')
        try:
            handle.write(core.text_type(text))
        finally:
            handle.close()
    except Exception:
        pass


# ====================== is the engine still alive? ======================
#
# A modeless window outlives the command that opened it. If pyRevit does not
# keep the engine alive, the window stays on screen with every handler in it
# dead - indistinguishable from a broken tool, and nothing inside it can say
# so. So a note is written when a modeless window opens, the first handler that
# runs deletes it, and the next launch finds the note still there and offers
# the fixed (modal) window instead.

ALIVE = [True]


def _alive_path():
    return os.path.join(core.settings_folder(), core.ALIVE_FILE)


def arm_alive_check():
    ALIVE[0] = False
    try:
        folder = core.settings_folder()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = io.open(_alive_path(), 'w', encoding='utf-8')
        try:
            handle.write(u'The Pipe Slope Assigner window was opened and no handler '
                         u'has run in it yet.\n')
        finally:
            handle.close()
    except Exception:
        pass


def mark_alive():
    if ALIVE[0]:
        return
    ALIVE[0] = True
    try:
        if os.path.isfile(_alive_path()):
            os.remove(_alive_path())
    except Exception:
        pass


def alive_check_failed():
    try:
        return os.path.isfile(_alive_path())
    except Exception:
        return False


def clear_alive_check():
    ALIVE[0] = True
    try:
        if os.path.isfile(_alive_path()):
            os.remove(_alive_path())
    except Exception:
        pass


def ui_safe(fn, status=None):
    """Wrap a WPF handler so an exception is reported, never swallowed.
    Also proves the engine is alive the first time any handler runs."""
    def handler(sender, args):
        mark_alive()
        try:
            return fn(sender, args)
        except Exception:
            text = traceback.format_exc()
            write_error(text)
            if status is not None:
                try:
                    status(u'Something went wrong - details in {0}'.format(
                        core.ERROR_FILE), 'Red')
                except Exception:
                    pass
    return handler


# ====================== loading ======================

def _read(name):
    handle = io.open(os.path.join(HERE, name), 'r', encoding='utf-8')
    try:
        return handle.read()
    finally:
        handle.close()


def load_window(layout_name, mode):
    """Parse a layout, then merge Theme.xaml, then write the palette on top.

    Theme.xaml is merged after the layout is parsed, which is why the layouts
    may only use DynamicResource.
    """
    window = XamlReader.Parse(_read(layout_name))
    dictionary = XamlReader.Parse(_read('Theme.xaml'))
    window.Resources.MergedDictionaries.Add(dictionary)
    theme.apply(window, mode)
    return window


def load_icon(image):
    """From bytes, not UriSource - System.Uri moved assemblies in 2025."""
    try:
        if image is None or not os.path.isfile(ICON_PATH):
            return
        bitmap = BitmapImage()
        bitmap.BeginInit()
        bitmap.CacheOption = BitmapCacheOption.OnLoad
        bitmap.StreamSource = MemoryStream(File.ReadAllBytes(ICON_PATH))
        bitmap.EndInit()
        bitmap.Freeze()
        image.Source = bitmap
    except Exception:
        pass


def own_to_revit(window, uiapp):
    """Owned by Revit's main window, so it floats above Revit."""
    try:
        from System.Windows.Interop import WindowInteropHelper
        helper = WindowInteropHelper(window)
        helper.Owner = uiapp.MainWindowHandle
    except Exception:
        pass


def attach_egg(window, mode_getter, logo_host=None):
    """Three slow clicks on the RevoBIM logo.

    The egg lives in the extension's shared lib\\revobim\\egg package and is not
    shipped with this tool. attach_to_window finds the logo itself; attach is
    the older form kept as a fallback. Decorative, so it can never take the
    tool down.
    """
    try:
        from revobim.egg import egg_hook
    except Exception:
        return False

    def palette():
        return theme.palette(theme.resolve(mode_getter()))

    attach_to_window = getattr(egg_hook, 'attach_to_window', None)
    if attach_to_window is not None:
        try:
            attach_to_window(window, theme=palette, tool=core.TOOL_NAME)
            return True
        except TypeError:
            try:
                attach_to_window(window, theme=palette)
                return True
            except Exception:
                pass
        except Exception:
            pass
    attach = getattr(egg_hook, 'attach', None)
    if attach is None or logo_host is None:
        return False
    try:
        attach(logo_host, host_window=window, theme=palette)
        return True
    except Exception:
        return False


class Chrome(object):
    """Header, version, theme chip, close, drag - shared by both windows."""

    def __init__(self, window, settings, on_close):
        self.window = window
        self.settings = settings
        find = window.FindName
        self.status_block = find('StatusText')
        find('VersionText').Text = u'v' + core.__version__
        load_icon(find('HeaderIcon'))
        self.theme_text = find('ThemeText')
        self.theme_text.Text = theme.chip_text(self.mode())
        find('ThemeButton').Click += ui_safe(self.on_theme, self.status)
        find('CloseButton').Click += ui_safe(lambda s, a: on_close(), self.status)
        find('HeaderBar').MouseLeftButtonDown += ui_safe(self.on_drag, self.status)
        attach_egg(window, self.mode, find('RevoLogo'))

    def mode(self):
        return self.settings.get('theme', 'auto')

    def on_theme(self, sender, args):
        self.settings['theme'] = theme.next_mode(self.mode())
        theme.apply(self.window, self.mode())
        self.theme_text.Text = theme.chip_text(self.mode())
        core.save_settings(self.settings)

    def on_drag(self, sender, args):
        try:
            if args.ClickCount == 1:
                self.window.DragMove()
        except Exception:
            pass

    def status(self, text, brush='TextMuted'):
        if self.status_block is None:
            return
        self.status_block.Text = text
        self.status_block.SetResourceReference(TextBlock.ForegroundProperty, brush)


# ====================== the prompt ======================

class SlopeDialog(object):
    """The prompt.

    Modal: show() blocks and returns the chosen settings, or None.
    Modeless: show() returns at once and Revit stays fully usable - zoom, pan,
    select a different run - while the window floats above it. Apply hands the
    settings to on_apply, which queues the work through an ExternalEvent; the
    window stays open for the next run until it is closed.
    """

    def __init__(self, uiapp, settings, selection_text, preview, modeless=False,
                 on_apply=None, on_closed=None):
        self.settings = dict(settings)
        self.preview = preview
        self.result = None
        self.modeless = modeless
        self.on_apply_cb = on_apply
        self.on_closed_cb = on_closed
        self.busy = False
        self.window = load_window('PipeSlopeAssigner.xaml', self.settings.get('theme'))
        own_to_revit(self.window, uiapp)
        self.place()
        self.chrome = Chrome(self.window, self.settings, self.cancel)
        find = self.window.FindName
        self.slope_buttons = {}
        for n in core.SLOPES:
            button = find('Slope{0}'.format(n))
            self.slope_buttons[n] = button
            button.Checked += ui_safe(self.on_changed, self.chrome.status)
        self.scope_run = find('ScopeRun')
        self.scope_network = find('ScopeNetwork')
        self.scope_system = find('ScopeSystem')
        self.upright_buttons = {}
        for deg in core.UPRIGHT_CHOICES:
            self.upright_buttons[deg] = find('Upright{0}'.format(deg))
        self.dir_auto = find('DirAuto')
        self.dir_pick = find('DirPick')
        self.anchor_low = find('AnchorLow')
        self.anchor_high = find('AnchorHigh')
        self.debug_check = find('DebugCheck')
        self.apply_button = find('ApplyButton')
        self.apply_text = find('ApplyText')
        self.scope_text = find('ScopeText')
        self.dir_auto_hint = find('DirAutoHint')
        self.selection_block = find('SelectionText')
        self.body = find('BodyPanel')
        self.selection_block.Text = selection_text
        self.cancel_button = find('CancelButton')
        if modeless:
            self.cancel_button.Content = u'Close'

        slope = int(self.settings.get('slope', '100'))
        self.slope_buttons.get(slope, self.slope_buttons[100]).IsChecked = True
        {'network': self.scope_network, 'selection': self.scope_system}.get(
            self.settings.get('scope'), self.scope_run).IsChecked = True
        upright = int(core.to_number(self.settings.get('upright')) or 15)
        self.upright_buttons.get(upright, self.upright_buttons[15]).IsChecked = True
        (self.dir_pick if self.settings.get('direction') == 'pick'
         else self.dir_auto).IsChecked = True
        (self.anchor_high if self.settings.get('anchor') == 'high'
         else self.anchor_low).IsChecked = True
        self.debug_check.IsChecked = self.settings.get('debug') == '1'

        for control in ([self.scope_run, self.scope_network, self.scope_system,
                         self.dir_auto, self.dir_pick, self.anchor_low, self.anchor_high]
                        + list(self.upright_buttons.values())):
            control.Checked += ui_safe(self.on_changed, self.chrome.status)
        self.apply_button.Click += ui_safe(self.on_apply, self.chrome.status)
        self.cancel_button.Click += ui_safe(lambda s, a: self.cancel(), self.chrome.status)
        self.window.PreviewKeyDown += ui_safe(self.on_key, self.chrome.status)
        self.window.Closed += ui_safe(self.on_closed, None)
        self.window.ContentRendered += ui_safe(lambda s, a: None, None)
        self.refresh()

    # ---------- where it sits ----------

    def place(self):
        """Back where it was last left, if that is still on a screen."""
        try:
            from System.Windows import SystemParameters, WindowStartupLocation
            left = core.to_number(self.settings.get('left'))
            top = core.to_number(self.settings.get('top'))
            if left is None or top is None:
                return
            x0, y0 = SystemParameters.VirtualScreenLeft, SystemParameters.VirtualScreenTop
            x1 = x0 + SystemParameters.VirtualScreenWidth - 120
            y1 = y0 + SystemParameters.VirtualScreenHeight - 80
            if not (x0 <= left <= x1 and y0 <= top <= y1):
                return
            self.window.WindowStartupLocation = WindowStartupLocation.Manual
            self.window.Left = left
            self.window.Top = top
        except Exception:
            pass

    def remember_place(self):
        try:
            self.settings['left'] = u'{0:.0f}'.format(self.window.Left)
            self.settings['top'] = u'{0:.0f}'.format(self.window.Top)
        except Exception:
            pass

    # ---------- what is chosen ----------

    def chosen_slope(self):
        for n, button in self.slope_buttons.items():
            if button.IsChecked:
                return n
        return 100

    def chosen_scope(self):
        if self.scope_system.IsChecked:
            return 'selection'
        return 'network' if self.scope_network.IsChecked else 'run'

    def chosen_upright(self):
        for deg, button in self.upright_buttons.items():
            if button.IsChecked:
                return deg
        return 15

    def chosen(self):
        values = dict(self.settings)
        values['slope'] = core.text_type(self.chosen_slope())
        values['scope'] = self.chosen_scope()
        values['upright'] = core.text_type(self.chosen_upright())
        values['direction'] = 'pick' if self.dir_pick.IsChecked else 'auto'
        values['anchor'] = 'high' if self.anchor_high.IsChecked else 'low'
        values['debug'] = '1' if self.debug_check.IsChecked else '0'
        values['theme'] = self.chrome.mode()
        return values

    def refresh(self):
        n = self.chosen_slope()
        self.apply_text.Text = u'Apply ' + core.slope_label(n)
        scope = self.chosen_scope()
        try:
            text, hint = self.preview(scope, self.chosen_upright())
        except Exception:
            write_error(traceback.format_exc())
            text, hint = u'', None
        self.scope_text.Text = text
        if hint:
            self.dir_auto_hint.Text = hint

    def set_selection(self, text, preview):
        """Revit's selection changed - show it and re-run the preview."""
        if self.busy:
            return
        self.selection_block.Text = text
        self.preview = preview
        self.refresh()

    def set_busy(self, busy, text=None, brush='Orange'):
        """While a run is working the window takes no input - the picks happen
        in Revit, and a second Apply must not queue behind the first."""
        self.busy = busy
        try:
            self.body.IsEnabled = not busy
            self.apply_button.IsEnabled = not busy
        except Exception:
            pass
        if text is not None:
            self.chrome.status(text, brush)

    # ---------- handlers ----------

    def on_changed(self, sender, args):
        self.refresh()

    def on_key(self, sender, args):
        if self.busy:
            return
        key = str(args.Key)
        for index, n in enumerate(core.SLOPES):
            if key in ('D{0}'.format(index + 1), 'NumPad{0}'.format(index + 1)):
                self.slope_buttons[n].IsChecked = True
                args.Handled = True
                return
        if key in ('Return', 'Enter'):
            args.Handled = True
            self.on_apply(sender, args)
        elif key == 'Escape':
            args.Handled = True
            self.cancel()

    def on_apply(self, sender, args):
        if self.busy:
            return
        values = self.chosen()
        self.settings.update(values)
        if self.modeless:
            self.remember_place()
            values = dict(self.settings)
            if self.on_apply_cb is not None:
                self.on_apply_cb(values)
            return
        self.result = values
        self.window.Close()

    def cancel(self):
        if self.busy:
            return
        self.result = None
        self.window.Close()

    def on_closed(self, sender, args):
        self.remember_place()
        try:
            saved = core.load_settings()
            saved['left'], saved['top'] = self.settings.get('left'), self.settings.get('top')
            saved['theme'] = self.chrome.mode()
            core.save_settings(saved)
        except Exception:
            pass
        if self.on_closed_cb is not None:
            self.on_closed_cb()

    def show(self):
        if self.modeless:
            self.window.Show()
            return None
        self.window.ShowDialog()
        return self.result


# ====================== the results ======================

ROW_BRUSH = {'ok': 'Green', 'warn': 'Orange', 'bad': 'Red', 'info': 'TextMuted'}


class ResultsWindow(object):
    def __init__(self, uiapp, settings, summary, rows, report, report_path, show_debug):
        self.settings = settings
        self.report = report
        self.report_path = report_path
        self.window = load_window('PipeSlopeResults.xaml', settings.get('theme'))
        own_to_revit(self.window, uiapp)
        self.chrome = Chrome(self.window, settings, self.close)
        find = self.window.FindName
        find('SummaryText').Text = summary
        panel = find('RowsPanel')
        for state, text in rows[:400]:
            panel.Children.Add(self.make_row(state, text))
        if len(rows) > 400:
            panel.Children.Add(self.make_row('info', u'... and {0} more in the report.'.format(
                len(rows) - 400)))
        if show_debug:
            find('DebugPanel').Visibility = Visibility.Visible
            find('DebugBox').Text = report
        find('CopyButton').Click += ui_safe(self.on_copy, self.chrome.status)
        find('FolderButton').Click += ui_safe(self.on_folder, self.chrome.status)
        find('OkButton').Click += ui_safe(lambda s, a: self.close(), self.chrome.status)
        self.window.PreviewKeyDown += ui_safe(self.on_key, self.chrome.status)
        if report_path:
            self.chrome.status(u'Report written to ' + report_path)

    def make_row(self, state, text):
        row = DockPanel()
        row.Margin = Thickness(8, 3, 8, 3)
        bar = Border()
        bar.Width = 4
        bar.Margin = Thickness(0, 1, 8, 1)
        bar.SetResourceReference(Border.BackgroundProperty, ROW_BRUSH.get(state, 'TextMuted'))
        DockPanel.SetDock(bar, Dock.Left)
        row.Children.Add(bar)
        label = TextBlock()
        label.Text = text
        label.TextWrapping = TextWrapping.Wrap
        label.SetResourceReference(TextBlock.ForegroundProperty, 'Text')
        row.Children.Add(label)
        return row

    def on_copy(self, sender, args):
        from System.Windows import Clipboard
        Clipboard.SetText(self.report or u'(empty report)')
        self.chrome.status(u'Report copied - paste it to Claude.', 'Green')

    def on_folder(self, sender, args):
        from System.Diagnostics import Process
        Process.Start('explorer.exe', core.settings_folder())

    def on_key(self, sender, args):
        if str(args.Key) == 'Escape':
            args.Handled = True
            self.close()

    def close(self):
        self.window.Close()

    def show(self, modal=True):
        if modal:
            self.window.ShowDialog()
        else:
            self.window.Show()
