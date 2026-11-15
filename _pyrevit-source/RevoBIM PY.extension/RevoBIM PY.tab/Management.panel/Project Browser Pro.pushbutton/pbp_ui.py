# -*- coding: utf-8 -*-
u"""Project Browser Pro - WPF helpers shared by the browser and its dialogs.

XAML loading, named-element lookup, the logo, owners for dialogs, opening
files, the clipboard, and the themed Prompt window (message, question,
name box). Every event handler goes through safe(): an exception inside a
WPF event closure is otherwise swallowed and the button just does nothing.
"""
import os

import pbp_clr  # noqa: F401
from System.IO import File, MemoryStream
from System.Diagnostics import Process, ProcessStartInfo
from System.Windows import FrameworkElement, Clipboard, Visibility
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Input import Key

import pbp_log
import pbp_theme
from pbp_compat import to_text, on_path
from pbp_version import __version__

HERE = os.path.dirname(os.path.abspath(__file__))


def load_xaml(name):
    u"""Load a layout from bytes; a parse failure names the file."""
    path = os.path.join(HERE, name)
    stream = MemoryStream(File.ReadAllBytes(path))
    try:
        return XamlReader.Load(stream)
    finally:
        stream.Close()


def find(root, name):
    element = root.FindName(name)
    if element is None:
        pbp_log.log(u'ui: no element named ' + name)
    return element


def safe(handler, where=u''):
    u"""Wrap an event handler so a failure is logged, never silent."""
    label = where or getattr(handler, u'__name__', u'handler')

    def wrapped(*args):
        try:
            # an event can import a module the first time it fires; the
            # folder may be off sys.path by then (pyRevit resets it)
            on_path()
            return handler(*args)
        except Exception:
            pbp_log.exc(u'event ' + to_text(label))
    return wrapped


def set_style(element, key):
    u"""Never element.Style = TryFindResource(key): a null result becomes a
    local value that also blocks the implicit style, and the control drops
    to OS chrome. A resource reference re-resolves with the palette too."""
    element.SetResourceReference(FrameworkElement.StyleProperty, key)


def show(element, visible):
    element.Visibility = Visibility.Visible if visible else Visibility.Collapsed


def logo_image(path=None):
    u"""icon.png as an ImageSource, loaded from bytes (no System.Uri - it
    moved assembly in Revit 2025 and kills a script at import)."""
    try:
        path = path or os.path.join(HERE, u'icon.png')
        image = BitmapImage()
        image.BeginInit()
        image.CacheOption = BitmapCacheOption.OnLoad
        image.StreamSource = MemoryStream(File.ReadAllBytes(path))
        image.EndInit()
        image.Freeze()
        return image
    except Exception:
        pbp_log.exc(u'logo')
        return None


def revit_handle():
    try:
        return Process.GetCurrentProcess().MainWindowHandle
    except Exception:
        return None


def own(window, handle=None):
    u"""Own a window to Revit, so it never slips behind Revit's main window."""
    try:
        handle = handle or revit_handle()
        if handle:
            WindowInteropHelper(window).Owner = handle
    except Exception:
        pbp_log.exc(u'own window')


def shell_open(path):
    u"""Open a file or folder the way Explorer would.

    On .NET 8 (Revit 2025+) Process.Start(path) no longer goes through the
    shell, so a .txt or a folder will not open without UseShellExecute.
    """
    try:
        info = ProcessStartInfo(path)
        info.UseShellExecute = True
        Process.Start(info)
        return True
    except Exception:
        pbp_log.exc(u'shell_open ' + to_text(path))
        return False


def copy_text(text):
    for attempt in range(3):
        try:
            Clipboard.SetText(text)
            return True
        except Exception:
            pass
    pbp_log.log(u'clipboard busy')
    return False


def attach_egg(logo, window=None):
    u"""Arm the RevoBIM easter egg on the logo if the shared module is there.

    Decorative, so every failure is swallowed: cosmetics never take a tool
    down, and this tool is one more anchor rather than a dependency.
    """
    try:
        from revobim.egg import egg_hook
    except Exception:
        return False
    attach = getattr(egg_hook, u'attach', None)
    if attach is None:
        return False
    for args in ((logo, window), (logo,)):
        try:
            attach(*args)
            return True
        except TypeError:
            continue
        except Exception:
            return False
    return False


# ============================================================
# themed prompt
# ============================================================

class Prompt(object):

    def __init__(self, title, message, theme_name, ask_text=False, initial=u'',
                 ok_text=u'OK', cancel_text=u'Cancel'):
        self.window = load_xaml(u'Prompt.xaml')
        pbp_theme.apply(self.window, theme_name)
        self.answer = None
        find(self.window, u'TitleText').Text = title
        find(self.window, u'MessageText').Text = message
        find(self.window, u'VersionText').Text = u'v' + __version__
        logo = logo_image()
        if logo is not None:
            find(self.window, u'LogoImage').Source = logo
        self.input = find(self.window, u'InputBox')
        ok = find(self.window, u'OkButton')
        cancel = find(self.window, u'CancelButton')
        ok.Content = ok_text
        if cancel_text:
            cancel.Content = cancel_text
        else:
            show(cancel, False)
        if ask_text:
            show(self.input, True)
            self.input.Text = initial
        self.ask_text = ask_text
        ok.Click += safe(self._ok, u'prompt ok')
        cancel.Click += safe(self._cancel, u'prompt cancel')
        find(self.window, u'CloseButton').Click += safe(self._cancel, u'prompt close')
        find(self.window, u'Header').MouseLeftButtonDown += safe(self._drag, u'prompt drag')
        self.window.PreviewKeyDown += safe(self._key, u'prompt key')
        self.window.Loaded += safe(self._loaded, u'prompt loaded')

    def _loaded(self, sender, args):
        if self.ask_text:
            self.input.Focus()
            self.input.SelectAll()

    def _drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    def _key(self, sender, args):
        if args.Key == Key.Enter:
            args.Handled = True
            self._ok(None, None)
        elif args.Key == Key.Escape:
            args.Handled = True
            self._cancel(None, None)

    def _ok(self, sender, args):
        self.answer = to_text(self.input.Text) if self.ask_text else True
        self.window.Close()

    def _cancel(self, sender, args):
        self.answer = None
        self.window.Close()

    def run(self):
        own(self.window)
        self.window.ShowDialog()
        return self.answer


def message(title, text, theme_name):
    Prompt(title, text, theme_name, cancel_text=u'').run()


def confirm(title, text, theme_name, ok_text=u'Yes'):
    return bool(Prompt(title, text, theme_name, ok_text=ok_text).run())


def ask_text(title, text, initial, theme_name):
    return Prompt(title, text, theme_name, ask_text=True, initial=initial).run()
