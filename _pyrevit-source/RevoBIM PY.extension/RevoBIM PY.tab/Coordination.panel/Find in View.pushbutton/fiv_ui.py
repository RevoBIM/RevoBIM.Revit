# -*- coding: utf-8 -*-
"""Find in View - XAML loading, theming, window chrome and the message window."""

import fiv_clr  # noqa: F401 - must be imported before any System.* name

import os
import sys
import time

from System.IO import StringReader, MemoryStream, File
from System.Xml import XmlReader
from System.Windows import (ResourceDictionary, Visibility, SystemParameters,
                            ResizeMode, SizeToContent, CornerRadius, Point,
                            VerticalAlignment)
from System.Windows.Markup import XamlReader
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Input import Key
from System.Windows.Threading import DispatcherTimer
from System import Double, TimeSpan

import fiv_core
import theme as fiv_theme

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def _read(path):
    handle = open(path, 'r')
    try:
        return handle.read()
    finally:
        handle.close()


def parse_xaml(path):
    """XamlReader.Parse via a StringReader avoids any file path complications."""
    return XamlReader.Load(XmlReader.Create(StringReader(_read(path))))


def load_window(name, palette_name):
    """Parse a layout, merge Theme.xaml into it, then write the palette on top.

    Theme.xaml is merged AFTER the layout has been parsed, which is why a
    layout may only ever use DynamicResource.
    """
    window = parse_xaml(os.path.join(HERE, name))
    dictionary = parse_xaml(os.path.join(HERE, 'Theme.xaml'))
    if not isinstance(dictionary, ResourceDictionary):
        raise Exception('Theme.xaml did not parse as a ResourceDictionary')
    window.Resources.MergedDictionaries.Add(dictionary)
    fiv_theme.apply(window, palette_name)
    return window


def load_icon(image_control, filename='icon.png'):
    """Load from bytes: System.Uri moved assemblies and throws on Revit 2025+.

    Decorative, so any failure is swallowed - cosmetics can never take a tool
    down.
    """
    try:
        path = os.path.join(HERE, filename)
        if not os.path.isfile(path):
            return
        bitmap = BitmapImage()
        bitmap.BeginInit()
        bitmap.StreamSource = MemoryStream(File.ReadAllBytes(path))
        bitmap.CacheOption = BitmapCacheOption.OnLoad
        bitmap.EndInit()
        image_control.Source = bitmap
    except Exception:
        pass


# ---------------------------------------------------------------------------
# the easter egg
# ---------------------------------------------------------------------------
#
# The egg itself lives once, in the extension's shared lib, at
# lib/revobim/egg.  It is never shipped with a tool - the tool only wires its
# own logo to it.

EGG_ENTRY_POINTS = [
    ('revobim.egg', 'launch'),
    ('revobim.egg', 'show'),
    ('revobim.egg', 'open_egg'),
    ('revobim.egg', 'run'),
    ('revobim.egg', 'start'),
    ('revobim.egg', 'main'),
    ('revobim.egg.launcher', 'launch'),
    ('revobim.egg.launcher', 'show'),
    ('revobim.egg.launcher', 'run'),
    ('revobim.egg.launcher', 'main'),
    ('revobim.egg.egg', 'launch'),
    ('revobim.egg.egg', 'main'),
]


def extension_lib():
    """Find the extension's lib folder by walking up from this button.

    pyRevit puts it on sys.path itself, but only for engines that have loaded
    the extension the usual way - finding it here as well costs nothing and
    means the egg works however the tool was reached.
    """
    folder = HERE
    for _step in range(6):
        candidate = os.path.join(folder, 'lib')
        if os.path.isdir(os.path.join(candidate, 'revobim')):
            return candidate
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return None


def ensure_egg_path():
    library = extension_lib()
    if library and library not in sys.path:
        sys.path.append(library)
    return library


def launch_egg(window=None):
    """Open the shared egg.  Returns (opened, what was tried)."""
    ensure_egg_path()
    tried = []
    for module_name, attribute in EGG_ENTRY_POINTS:
        try:
            module = __import__(module_name, globals(), locals(), [attribute])
        except Exception as error:
            tried.append('{0} - {1}'.format(module_name, error))
            continue
        function = getattr(module, attribute, None)
        if function is None:
            tried.append('{0}.{1} - no such name'.format(module_name, attribute))
            continue
        for arguments in ((window,), ()):
            try:
                function(*arguments)
                return True, '{0}.{1}'.format(module_name, attribute)
            except TypeError:
                continue
            except Exception as error:
                tried.append('{0}.{1} - {2}'.format(module_name, attribute, error))
                break
    return False, '\n'.join(tried)


def wire_egg(logo, window, palette_name='dark'):
    """Three slow clicks on the RevoBIM logo open the egg.

    PreviewMouseLeftButtonDown, marked handled: the header bar's own
    MouseLeftButtonDown starts a DragMove that captures the mouse, and a
    captured mouse never delivers the button up the count would need.  Tunnel
    down to the logo first and the drag never runs - the cost is that the
    window cannot be dragged by its logo, which nobody does.
    """
    if logo is None:
        return
    state = {'clicks': []}

    def on_click(sender, args):
        try:
            args.Handled = True
            fire, kept = fiv_core.egg_click(state['clicks'], time.time())
            state['clicks'] = kept
            if not fire:
                return
            opened, report = launch_egg(window)
            if not opened:
                message('The RevoBIM egg is not answering.\n\n'
                        'What was tried:\n{0}'.format(report or 'nothing'),
                        palette_name, None, False, 'Easter egg', window)
        except Exception:
            pass

    try:
        logo.PreviewMouseLeftButtonDown += on_click
        logo.Cursor = None
    except Exception:
        pass


def own_to_revit(window, uiapp):
    """Owned windows float above Revit instead of slipping behind it."""
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = uiapp.MainWindowHandle
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# the shrink drawer
# ---------------------------------------------------------------------------
#
# Every window the tool opens carries one. Built once here and handed to each
# window class, which is what keeps the gesture identical between a window
# whose chrome comes from a layout file and one that builds it in code.

# every drawer alive, so two parked bars do not land on top of each other
_PARKED = []


class WindowDrawer(object):

    def __init__(self, window, header, root, button, shrink_path=None,
                 expand_path=None, shell=None, grips=None):
        self.window = window
        self.header = header
        self.root = root
        self.button = button
        self.shrink_path = shrink_path
        self.expand_path = expand_path
        self.shell = shell
        self.grips = grips

        self.shrunk = False
        self.sliding = False
        self.slot = 0
        self._saved = None
        self._was_visible = {}
        self._timer = None
        self._corners = None

        try:
            button.Click += self._on_click
        except Exception:
            pass

    # ----------------------------------------------------------------- state

    def toggle(self):
        if self.sliding:
            return
        if self.shrunk:
            self.expand()
        else:
            self.shrink()

    def _on_click(self, sender, args):
        self.toggle()

    # ------------------------------------------------------------ the slide

    def _screen_area(self):
        """(top, height) of the working area of the screen the window is on."""
        try:
            import clr
            clr.AddReference('System.Windows.Forms')
            from System.Windows.Forms import Screen
            from System.Windows import PresentationSource

            helper = WindowInteropHelper(self.window)
            bounds = Screen.FromHandle(helper.Handle).WorkingArea
            scale = 1.0
            source = PresentationSource.FromVisual(self.window)
            if source is not None and source.CompositionTarget is not None:
                matrix = source.CompositionTarget.TransformToDevice
                if matrix.M22:
                    scale = matrix.M22
            # signed: a monitor ABOVE the primary one has a negative top, and
            # reading it as zero parks the bar on the wrong screen
            return (bounds.Y / scale, bounds.Height / scale)
        except Exception:
            try:
                return (0.0, SystemParameters.WorkArea.Height)
            except Exception:
                return (0.0, 1000.0)

    def _bar(self):
        offset = 7.0
        try:
            point = self.header.TranslatePoint(Point(0, 0), self.window)
            offset = max(0.0, point.Y)
        except Exception:
            pass
        height = 0.0
        try:
            height = self.header.ActualHeight
        except Exception:
            height = 0.0
        return fiv_core.bar_height(height, offset)

    def _animate(self, top_to, height_to, done):
        """Ease Top and Height together, by hand, on a timer.

        A Storyboard on a borderless window's Top and Height fights the layout
        pass. Easing by hand also means there is no animation left holding the
        property afterwards - an animation that is never released leaves a
        window that can never be moved or resized again, with nothing raised
        to say so.
        """
        try:
            top_from = float(self.window.Top)
            height_from = float(self.window.Height)
        except Exception:
            top_from, height_from = top_to, height_to

        state = {'elapsed': 0.0}
        self.sliding = True
        timer = DispatcherTimer()
        self._timer = timer
        timer.Interval = TimeSpan.FromMilliseconds(fiv_core.DRAWER_TICK_MS)

        def land():
            try:
                timer.Stop()
            except Exception:
                pass
            self._timer = None
            self.sliding = False
            try:
                self.window.Top = top_to
                self.window.Height = height_to
            except Exception:
                pass
            try:
                done()
            except Exception:
                pass

        def tick(sender, args):
            # a frame that throws still has to land the window, or it is left
            # half shut with no way back
            try:
                state['elapsed'] += fiv_core.DRAWER_TICK_MS
                progress = state['elapsed'] / fiv_core.DRAWER_MS
                if progress >= 1.0:
                    land()
                    return
                self.window.Top = fiv_core.drawer_frame(top_from, top_to, progress)
                self.window.Height = fiv_core.drawer_frame(height_from, height_to,
                                                           progress)
            except Exception:
                land()

        timer.Tick += tick
        try:
            timer.Start()
        except Exception:
            land()

    # ---------------------------------------------------------------- shrink

    def shrink(self):
        if self.shrunk or self.sliding:
            return
        window = self.window
        # A window sized to its content has Height = NaN until something sets
        # it, and a slide that starts from NaN lands nowhere. Pin the measured
        # height first, and save THAT as the height to reopen at.
        try:
            if Double.IsNaN(window.Height):
                window.Height = window.ActualHeight
        except Exception:
            pass
        try:
            self._saved = (window.Left, window.Top, window.Width, window.Height,
                           window.MinHeight, window.SizeToContent,
                           window.ResizeMode)
        except Exception:
            return
        try:
            if Double.IsNaN(self._saved[3]) or self._saved[3] <= 0:
                return
        except Exception:
            return

        # MinHeight and SizeToContent both veto a Height change, and a vetoed
        # one leaves the window half shut for the rest of the session
        try:
            window.MinHeight = 0
            window.SizeToContent = SizeToContent.Manual
            window.ResizeMode = ResizeMode.NoResize
        except Exception:
            pass

        # pin the body, or the grid re-measures on every frame and it reads as
        # a window being squashed rather than a drawer being drawn away
        try:
            self.root.Height = self.root.ActualHeight
            self.root.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass
        try:
            if self.shell is not None:
                self.shell.ClipToBounds = True
        except Exception:
            pass

        bar = self._bar()
        area_top, area_height = self._screen_area()
        self.slot = fiv_core.free_slot([other.slot for other in _PARKED])
        if self not in _PARKED:
            _PARKED.append(self)
        target = fiv_core.shrunk_top(area_top, area_height, bar, self.slot)
        self.shrunk = True
        self._set_glyph(True)
        self._animate(target, bar, self._landed)

    def _landed(self):
        """Hide the body only once the bar is down."""
        self._was_visible = {}
        try:
            for child in self.root.Children:
                if child is self.header:
                    continue
                try:
                    self._was_visible[child] = child.Visibility
                    # a panel already hidden stays hidden when it comes back
                    child.Visibility = Visibility.Collapsed
                except Exception:
                    pass
        except Exception:
            pass
        self._park_grips(True)
        try:
            if self.shell is not None:
                self._corners = self.shell.CornerRadius
            self.header.CornerRadius = CornerRadius(5)
        except Exception:
            pass

    def _park_grips(self, parked):
        """The grip overlay spans every row, so left visible it lines the bar
        with invisible drag handles and swallows the click on the arrow."""
        if self.grips is None:
            return
        try:
            self.grips.Visibility = Visibility.Collapsed if parked \
                else Visibility.Visible
            self.grips.IsHitTestVisible = not parked
        except Exception:
            pass

    # ---------------------------------------------------------------- expand

    def expand(self):
        if not self.shrunk or self.sliding or not self._saved:
            return
        left, top, width, height, min_height, size_to, resize = self._saved

        # show the body before the slide back, not after
        try:
            for child in self._was_visible:
                child.Visibility = self._was_visible[child]
        except Exception:
            pass
        self._was_visible = {}
        try:
            self.header.CornerRadius = CornerRadius(5, 5, 0, 0)
        except Exception:
            pass

        bar = self._bar()
        area_top, area_height = self._screen_area()
        try:
            parked_top = float(self.window.Top)
        except Exception:
            parked_top = top
        target_top = fiv_core.expand_top(parked_top, height, bar, area_top,
                                         area_height)
        try:
            self.window.Left = left
        except Exception:
            pass

        self.shrunk = False
        self._set_glyph(False)
        if self in _PARKED:
            _PARKED.remove(self)

        def done():
            # unpin, and put back everything the slide had to relax
            try:
                self.root.Height = Double.NaN
                self.root.VerticalAlignment = VerticalAlignment.Stretch
            except Exception:
                pass
            try:
                self.window.MinHeight = min_height
                self.window.SizeToContent = size_to
                self.window.ResizeMode = resize
            except Exception:
                pass
            self._park_grips(False)
            try:
                self.window.Activate()
            except Exception:
                pass

        self._animate(target_top, height, done)

    def restore_now(self):
        """Put the window back with no slide - for closing while parked."""
        if not self.shrunk or not self._saved:
            return
        left, top, width, height, min_height, size_to, resize = self._saved
        try:
            for child in self._was_visible:
                child.Visibility = self._was_visible[child]
        except Exception:
            pass
        try:
            self.root.Height = Double.NaN
            self.root.VerticalAlignment = VerticalAlignment.Stretch
            self.window.MinHeight = min_height
            self.window.SizeToContent = size_to
            self.window.ResizeMode = resize
            self.window.Left, self.window.Top = left, top
            self.window.Width, self.window.Height = width, height
        except Exception:
            pass
        self._park_grips(False)
        self.shrunk = False
        self._set_glyph(False)
        if self in _PARKED:
            _PARKED.remove(self)

    def true_height(self):
        """The real height while parked, so closing shrunk saves a size worth
        reopening at rather than a 60 pixel bar."""
        if self.shrunk and self._saved:
            return self._saved[3]
        try:
            return self.window.Height
        except Exception:
            return 0.0

    # ----------------------------------------------------------------- glyph

    def _set_glyph(self, parked):
        try:
            self.button.Tag = 'shrunk' if parked else ''
        except Exception:
            pass
        try:
            if self.shrink_path is not None:
                self.shrink_path.Visibility = Visibility.Collapsed if parked \
                    else Visibility.Visible
            if self.expand_path is not None:
                self.expand_path.Visibility = Visibility.Visible if parked \
                    else Visibility.Collapsed
        except Exception:
            pass
        try:
            self.button.ToolTip = 'Open the window again (Ctrl+Shift+H)' if parked \
                else 'Shrink to the taskbar so Revit can be seen (Ctrl+Shift+H)'
        except Exception:
            pass


def is_shrink_key(args):
    """Ctrl+Shift+H, the shortcut the whole suite uses for this."""
    try:
        from System.Windows.Input import ModifierKeys, Keyboard
        if args.Key != Key.H:
            return False
        wanted = ModifierKeys.Control | ModifierKeys.Shift
        return (Keyboard.Modifiers & wanted) == wanted
    except Exception:
        return False


# ---------------------------------------------------------------------------
# chrome
# ---------------------------------------------------------------------------

class Chrome(object):
    """Dragging, the resize grips and full screen, for a borderless window."""

    def __init__(self, window, header, root_grid=None):
        self.window = window
        self.header = header
        self.full_screen = False
        self.drawer = None
        self._saved = None
        try:
            header.MouseLeftButtonDown += self._on_header_down
        except Exception:
            pass

    # ------------------------------------------------------------------ drag

    def _on_header_down(self, sender, args):
        try:
            # while parked, a double click opens the window and a single click
            # drags the bar - it must never maximise something nobody can see
            if self.drawer is not None and self.drawer.shrunk:
                if args.ClickCount == 2:
                    self.drawer.expand()
                else:
                    self.window.DragMove()
                return
            if args.ClickCount == 2:
                self.toggle_full_screen()
                return
            if self.full_screen:
                self.toggle_full_screen()
            self.window.DragMove()
        except Exception:
            pass

    # ----------------------------------------------------------------- grips

    def attach_grips(self, grips):
        """grips is a dict of name -> Thumb, names from N/S/E/W/NE/NW/SE/SW."""
        for name in grips:
            thumb = grips[name]
            if thumb is None:
                continue
            thumb.DragDelta += self._make_grip(name)

    def _make_grip(self, name):
        def handler(sender, args):
            try:
                if self.full_screen:
                    return
                window = self.window
                horizontal = args.HorizontalChange
                vertical = args.VerticalChange
                if 'W' in name:
                    width = window.Width - horizontal
                    if width >= window.MinWidth:
                        window.Left = window.Left + horizontal
                        window.Width = width
                if 'E' in name:
                    width = window.Width + horizontal
                    if width >= window.MinWidth:
                        window.Width = width
                if 'N' in name:
                    height = window.Height - vertical
                    if height >= window.MinHeight:
                        window.Top = window.Top + vertical
                        window.Height = height
                if 'S' in name:
                    height = window.Height + vertical
                    if height >= window.MinHeight:
                        window.Height = height
            except Exception:
                pass
        return handler

    # ----------------------------------------------------------- full screen

    def toggle_full_screen(self):
        # filling the screen with a window that is parked out of sight helps
        # nobody: open it instead
        if self.drawer is not None and self.drawer.shrunk:
            self.drawer.expand()
            return False
        try:
            window = self.window
            if self.full_screen:
                if self._saved:
                    window.Left, window.Top, window.Width, window.Height = self._saved
                self.full_screen = False
                return False

            self._saved = (window.Left, window.Top, window.Width, window.Height)
            area = self._working_area()
            if area:
                window.Left, window.Top, window.Width, window.Height = area
            self.full_screen = True
            return True
        except Exception:
            return self.full_screen

    def _working_area(self):
        """Bounds, not WindowState.Maximized.

        Maximising a borderless AllowsTransparency window covers the task bar
        and lands on the wrong monitor.  The working area comes back in device
        pixels and has to be divided by the DPI scale.
        """
        try:
            import clr
            clr.AddReference('System.Windows.Forms')
            from System.Windows.Forms import Screen
            from System.Windows import PresentationSource

            helper = WindowInteropHelper(self.window)
            screen = Screen.FromHandle(helper.Handle)
            bounds = screen.WorkingArea

            scale_x = 1.0
            scale_y = 1.0
            source = PresentationSource.FromVisual(self.window)
            if source is not None and source.CompositionTarget is not None:
                matrix = source.CompositionTarget.TransformToDevice
                if matrix.M11:
                    scale_x = matrix.M11
                if matrix.M22:
                    scale_y = matrix.M22

            return (bounds.X / scale_x, bounds.Y / scale_y,
                    bounds.Width / scale_x, bounds.Height / scale_y)
        except Exception:
            try:
                return (0.0, 0.0,
                        SystemParameters.WorkArea.Width,
                        SystemParameters.WorkArea.Height)
            except Exception:
                return None


# ---------------------------------------------------------------------------
# message window
# ---------------------------------------------------------------------------

def message(text, palette_name='dark', owner_uiapp=None, confirm=False, title=None,
            owner_window=None):
    """Themed message or Yes/No confirm.

    Any failure falls back to Revit's own TaskDialog: a silent return from a
    dialog is indistinguishable from a broken button.
    """
    try:
        window = load_window('FindInViewMessage.xaml', palette_name)
        find = window.FindName
        load_icon(find('HeaderIcon'))
        wire_egg(find('HeaderIcon'), window, palette_name)
        find('MessageText').Text = text
        chrome = Chrome(window, find('HeaderBar'))
        chrome.drawer = WindowDrawer(window, find('HeaderBar'), find('RootGrid'),
                                     find('ShrinkBtn'), find('PathShrink'),
                                     find('PathExpand'), find('RootBorder'))
        find('VersionText').Text = 'v' + fiv_core.__version__
        if title:
            find('TitleTool').Text = title

        result = {'value': False}

        ok_button = find('OkBtn')
        no_button = find('NoBtn')
        if confirm:
            ok_button.Content = 'Yes'
            no_button.Visibility = Visibility.Visible

        def say_yes(sender, args):
            result['value'] = True
            window.Close()

        def say_no(sender, args):
            result['value'] = False
            window.Close()

        ok_button.Click += say_yes
        no_button.Click += say_no
        find('CloseBtn').Click += say_no

        def on_key(sender, args):
            if chrome.drawer is not None and chrome.drawer.shrunk:
                # a key press must not answer a prompt that is out of sight
                if args.Key in (Key.Escape, Key.Enter, Key.F11):
                    chrome.drawer.expand()
                    args.Handled = True
                return
            if is_shrink_key(args):
                chrome.drawer.toggle()
                args.Handled = True
            elif args.Key == Key.Escape:
                say_no(sender, args)
            elif args.Key == Key.Enter:
                say_yes(sender, args)

        window.PreviewKeyDown += on_key

        owned = False
        if owner_window is not None:
            # a confirm raised from the tool's own modal window belongs to that
            # window, or it can open behind it and read as a hang
            try:
                window.Owner = owner_window
                owned = True
            except Exception:
                owned = False
        if not owned and owner_uiapp is not None:
            own_to_revit(window, owner_uiapp)
        window.ShowDialog()
        return result['value']
    except Exception:
        return _task_dialog(text, confirm)


def _task_dialog(text, confirm):
    try:
        from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult
        dialog = TaskDialog('RevoBIM ' + fiv_core.TOOL_NAME)
        dialog.MainInstruction = fiv_core.TOOL_NAME
        dialog.MainContent = text
        if confirm:
            dialog.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
            return dialog.Show() == TaskDialogResult.Yes
        dialog.Show()
        return True
    except Exception:
        return False
