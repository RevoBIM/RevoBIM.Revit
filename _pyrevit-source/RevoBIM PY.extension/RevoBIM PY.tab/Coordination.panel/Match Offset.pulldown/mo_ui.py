# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - XAML loading, window chrome and the easter egg.

Every window in the tool is built the same way: parse the layout, merge
Theme.xaml into it afterwards, write the palette onto window.Resources, wire
the header, and arm the logo for the easter egg.

Images are loaded from bytes through a MemoryStream and never through
System.Uri, which moved assemblies in Revit 2025 and throws ImportError at
module load on 2025 and later - killing the script before any of it runs.
"""

import mo_clr  # noqa: F401

import os

from System.IO import MemoryStream, File
from System.Windows import (
    WindowStartupLocation, HorizontalAlignment, VerticalAlignment, Visibility,
)
from System.Windows.Controls import Grid
from System.Windows.Controls.Primitives import Thumb
from System.Windows.Input import Cursors
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

import mo_theme
from mo_core import to_text, log

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_FILE = os.path.join(HERE, 'Theme.xaml')


# ======================================================================
# loading
# ======================================================================

def _parse(path):
    stream = MemoryStream(File.ReadAllBytes(path))
    try:
        return XamlReader.Load(stream)
    finally:
        try:
            stream.Close()
        except Exception:
            pass


def load_window(name, theme_mode=u"auto"):
    """Parse a layout, merge Theme.xaml into it, apply the palette.

    Theme.xaml is merged after the layout has been parsed, which is exactly
    why the layouts may only use DynamicResource: a StaticResource would be
    resolved during the parse, when the dictionary is not there yet, and the
    failure arrives as a blank white pyRevit window.
    """
    window = _parse(os.path.join(HERE, name))
    try:
        window.Resources.MergedDictionaries.Add(_parse(THEME_FILE))
    except Exception as err:
        log(u"Theme.xaml would not merge: {0}".format(to_text(err)))
    mo_theme.apply(window, theme_mode)
    try:
        window.WindowStartupLocation = WindowStartupLocation.CenterScreen
    except Exception:
        pass
    return window


def icon_source(path):
    """A BitmapImage from bytes. No System.Uri anywhere near it."""
    try:
        if not os.path.isfile(path):
            return None
        image = BitmapImage()
        image.BeginInit()
        image.StreamSource = MemoryStream(File.ReadAllBytes(path))
        image.CacheOption = BitmapCacheOption.OnLoad
        image.EndInit()
        return image
    except Exception:
        return None


def set_icon(window, image_name='icon.png'):
    """Anything decorative goes in a try/except: cosmetics never take a tool
    down."""
    try:
        source = icon_source(os.path.join(HERE, image_name))
        if source is None:
            return False
        element = window.FindName('LogoImage')
        if element is not None:
            element.Source = source
        try:
            window.Icon = source
        except Exception:
            pass
        return True
    except Exception:
        return False


# ======================================================================
# chrome
# ======================================================================

def wire_header(window, settings, on_theme_changed=None):
    """Drag by the header, close, and the Auto/Dark/Light chip.

    Handlers are bound Python side with += rather than wired in the XAML with
    Click="name": XAML-wired handlers are unreliable under IronPython, and a
    handler that never fires leaves a window that looks fine and does nothing.
    """
    header = window.FindName('HeaderBar')
    if header is not None:
        def drag(sender, args):
            try:
                window.DragMove()
            except Exception:
                pass
        header.MouseLeftButtonDown += drag

    close_button = window.FindName('CloseButton')
    if close_button is not None:
        def close(sender, args):
            try:
                window.Close()
            except Exception:
                pass
        close_button.Click += close

    chip = window.FindName('ThemeChip')
    if chip is not None:
        chip.Content = mo_theme.CHIP_LABEL.get(
            to_text(settings.get(u"theme", u"auto")).lower(), u"Auto")

        def cycle(sender, args):
            mode = mo_theme.next_in_cycle(settings.get(u"theme", u"auto"))
            settings[u"theme"] = mode
            chip.Content = mo_theme.CHIP_LABEL.get(mode, u"Auto")
            mo_theme.apply(window, mode)
            if on_theme_changed is not None:
                try:
                    on_theme_changed(mode)
                except Exception:
                    pass
        chip.Click += cycle

    version_label = window.FindName('VersionLabel')
    if version_label is not None:
        import mo_core
        version_label.Text = u"v{0}".format(mo_core.__version__)

    set_icon(window)
    attach_egg(window)
    return window


GRIP_SPECS = (
    ('n', HorizontalAlignment.Stretch, VerticalAlignment.Top, 'SizeNS'),
    ('s', HorizontalAlignment.Stretch, VerticalAlignment.Bottom, 'SizeNS'),
    ('w', HorizontalAlignment.Left, VerticalAlignment.Stretch, 'SizeWE'),
    ('e', HorizontalAlignment.Right, VerticalAlignment.Stretch, 'SizeWE'),
    ('nw', HorizontalAlignment.Left, VerticalAlignment.Top, 'SizeNWSE'),
    ('se', HorizontalAlignment.Right, VerticalAlignment.Bottom, 'SizeNWSE'),
    ('ne', HorizontalAlignment.Right, VerticalAlignment.Top, 'SizeNESW'),
    ('sw', HorizontalAlignment.Left, VerticalAlignment.Bottom, 'SizeNESW'),
)

GRIP_PX = 6.0


def add_resize_grips(window, host_name='RootGrid'):
    """Eight thumbs round the edge, because WPF cannot resize this window.

    A borderless AllowsTransparency window has nothing hit testable in its
    transparent frame, so the resize border never fires however ResizeMode is
    set and the window is stuck at its start size. The overlay carries no
    Background of its own, so everything underneath stays clickable.
    """
    host = window.FindName(host_name)
    if host is None:
        return False
    overlay = Grid()
    try:
        Grid.SetRowSpan(overlay, 99)
        Grid.SetColumnSpan(overlay, 99)
    except Exception:
        pass

    for name, halign, valign, cursor_name in GRIP_SPECS:
        thumb = Thumb()
        thumb.Width = GRIP_PX if halign != HorizontalAlignment.Stretch else float('nan')
        thumb.Height = GRIP_PX if valign != VerticalAlignment.Stretch else float('nan')
        thumb.HorizontalAlignment = halign
        thumb.VerticalAlignment = valign
        thumb.Opacity = 0.0
        try:
            thumb.Cursor = getattr(Cursors, cursor_name)
        except Exception:
            pass
        thumb.DragDelta += _grip_handler(window, name)
        overlay.Children.Add(thumb)

    host.Children.Add(overlay)
    return True


def _grip_handler(window, name):
    def handler(sender, args):
        try:
            dx = float(args.HorizontalChange)
            dy = float(args.VerticalChange)
            if 'w' in name:
                width = window.Width - dx
                if width >= window.MinWidth:
                    window.Left += dx
                    window.Width = width
            if 'e' in name:
                width = window.Width + dx
                if width >= window.MinWidth:
                    window.Width = width
            if 'n' in name:
                height = window.Height - dy
                if height >= window.MinHeight:
                    window.Top += dy
                    window.Height = height
            if 's' in name:
                height = window.Height + dy
                if height >= window.MinHeight:
                    window.Height = height
        except Exception:
            pass
    return handler


# ======================================================================
# the easter egg
# ======================================================================

def attach_egg(window, element_name='LogoArea'):
    """Arm the RevoBIM logo. Three slow clicks and it wakes up.

    Nothing to do with the egg is shipped by this tool: startup.py, the hooks
    and lib\\revobim\\egg are the extension's, shared and singular, and a tool
    that shipped its own copy would silently overwrite whatever was there.
    This only asks the egg that is already installed to watch the logo.
    """
    try:
        from revobim.egg import egg_hook
    except Exception:
        return False
    try:
        target = window.FindName(element_name)
        if target is None:
            target = window
        egg_hook.attach(window, target)
        return True
    except Exception:
        return False


# ======================================================================
# a themed message, and a themed yes/no
# ======================================================================

def message(title, body, theme_mode=u"auto", owner=None,
            ok_text=u"OK", alt_text=u"", cancel_text=u""):
    """Returns True for the primary button, False for the alternative, and
    None for cancel or for the window being closed.

    A silent return False in a confirm step is indistinguishable from a broken
    button, so a window that will not open falls back to Revit's own dialog
    rather than quietly answering no.
    """
    try:
        window = load_window('MatchOffsetMessage.xaml', theme_mode)
    except Exception as err:
        log(u"Message window would not load: {0}".format(to_text(err)))
        return _fallback_dialog(title, body, alt_text or cancel_text)

    state = {'answer': None}
    try:
        window.FindName('MessageTitle').Text = to_text(title)
        window.FindName('MessageBody').Text = to_text(body)
        wire_header(window, {u"theme": theme_mode})

        primary = window.FindName('PrimaryButton')
        primary.Content = to_text(ok_text)

        def say_yes(sender, args):
            state['answer'] = True
            window.Close()
        primary.Click += say_yes

        alt = window.FindName('AltButton')
        if alt_text:
            alt.Content = to_text(alt_text)
            alt.Visibility = Visibility.Visible

            def say_no(sender, args):
                state['answer'] = False
                window.Close()
            alt.Click += say_no
        else:
            alt.Visibility = Visibility.Collapsed

        cancel = window.FindName('CancelButton')
        if cancel_text:
            cancel.Content = to_text(cancel_text)
            cancel.Visibility = Visibility.Visible

            def say_cancel(sender, args):
                state['answer'] = None
                window.Close()
            cancel.Click += say_cancel
        else:
            cancel.Visibility = Visibility.Collapsed

        if owner is not None:
            try:
                window.Owner = owner
            except Exception:
                pass
        window.ShowDialog()
    except Exception as err:
        log(u"Message window failed: {0}".format(to_text(err)))
        return _fallback_dialog(title, body, alt_text or cancel_text)
    return state['answer']


def _fallback_dialog(title, body, ask):
    try:
        from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult
        dialog = TaskDialog(to_text(title))
        dialog.MainInstruction = to_text(title)
        dialog.MainContent = to_text(body)
        if ask:
            dialog.CommonButtons = (TaskDialogCommonButtons.Yes |
                                    TaskDialogCommonButtons.No)
            return dialog.Show() == TaskDialogResult.Yes
        dialog.CommonButtons = TaskDialogCommonButtons.Close
        dialog.Show()
        return True
    except Exception:
        return None
