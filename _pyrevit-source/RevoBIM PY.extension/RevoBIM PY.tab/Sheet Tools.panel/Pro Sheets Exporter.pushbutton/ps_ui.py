# -*- coding: utf-8 -*-
"""Window plumbing shared by every window in this tool.

Loading XAML, merging the theme, the borderless chrome, full screen, the
resize grips, the logo, the easter egg, folder browsing and the message
window. None of it knows anything about exporting.
"""

import ps_refs  # noqa: F401  - must be first

import os
import sys
import traceback

import time

from System import TimeSpan
from System.IO import File, MemoryStream
from System.Windows import (
    CornerRadius, GridLength, HorizontalAlignment, Point, PresentationSource,
    ResourceDictionary, SystemParameters, Thickness, VerticalAlignment,
    Visibility, WindowStartupLocation,
)
from System.Windows.Controls import (
    Border, Button, ColumnDefinition, Grid, ItemsControl, ListBox,
    ListBoxItem, TextBox,
)
from System.Windows.Controls.Primitives import PlacementMode, Popup
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Media import ScaleTransform
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage
from System.Windows.Threading import DispatcherTimer
from System.Xml import XmlReader

import ps_config
import ps_version
import theme


HERE = os.path.dirname(os.path.abspath(__file__))


def here(*parts):
    return os.path.join(HERE, *parts)


# ==========================================================================
# loading XAML
# ==========================================================================

def load_xaml(file_name):
    """Parse a layout file into a live object.

    A failure here is the classic blank white pyRevit window, so the
    exception is re-raised carrying the file name, the line and the column -
    which turns "it did not open" into "Theme.xaml line 214 column 19".
    """
    path = here(file_name)
    reader = None
    try:
        reader = XmlReader.Create(path)
        return XamlReader.Load(reader)
    except Exception as err:
        raise Exception(u'{0} would not parse: {1}'.format(file_name, err))
    finally:
        if reader is not None:
            try:
                reader.Close()
            except Exception:
                pass


def theme_dictionary():
    loaded = load_xaml('Theme.xaml')
    if not isinstance(loaded, ResourceDictionary):
        raise Exception('Theme.xaml did not load as a ResourceDictionary')
    return loaded


def load_window(file_name, theme_name='dark'):
    """A themed window from a layout file, not yet shown."""
    window = load_xaml(file_name)
    window.Resources.MergedDictionaries.Add(theme_dictionary())
    theme.apply(window, theme_name)
    set_version(window)
    set_logo(window)
    return window


def find(window, name):
    """FindName that returns None instead of throwing on a missing name."""
    try:
        return window.FindName(name)
    except Exception:
        return None


def set_version(window):
    label = find(window, 'VersionText')
    if label is not None:
        try:
            label.Text = u'v' + ps_version.__version__
        except Exception:
            pass


# ==========================================================================
# the logo
# ==========================================================================

def _icon_path():
    for name in ('icon.png', 'icon.large.png', 'logo.png'):
        candidate = here(name)
        if os.path.isfile(candidate):
            return candidate
    return None


def load_bitmap(path):
    """A BitmapImage from bytes.

    Never from a Uri: ``from System import Uri`` throws ImportError on Revit
    2025 and later, killing the module at load.
    """
    stream = None
    try:
        image = BitmapImage()
        stream = MemoryStream(File.ReadAllBytes(path))
        image.BeginInit()
        image.CacheOption = BitmapCacheOption.OnLoad
        image.StreamSource = stream
        image.EndInit()
        try:
            image.Freeze()
        except Exception:
            pass
        return image
    except Exception:
        return None
    finally:
        if stream is not None:
            try:
                stream.Dispose()
            except Exception:
                pass


def set_logo(window):
    """Put the tool icon in the header. Cosmetic, so it swallows failures."""
    try:
        host = find(window, 'LogoImage')
        if host is None:
            return
        path = _icon_path()
        if not path:
            return
        image = load_bitmap(path)
        if image is not None:
            host.Source = image
    except Exception:
        pass


# ==========================================================================
# the easter egg
# ==========================================================================

def _argument_names(function):
    """The parameter names of a Python function, on IronPython 2.7 and 3."""
    code = getattr(function, '__code__', None) or getattr(function, 'func_code', None)
    if code is None:
        return None
    try:
        count = code.co_argcount
        return list(code.co_varnames[:count])
    except Exception:
        return None


def attach_egg(window, element_name='LogoHost'):
    """Arm the extension's easter egg on this window's RevoBIM logo.

    Three slow clicks **on the logo**, and on nothing else.

    The egg itself lives in the shared ``revobim.egg`` subpackage, which this
    tool never ships - arming it from here is one of the four anchors that
    keep it alive through a delivery that does not know about it.

    Two rules, both learned the hard way:

    **Never hand it the window.** An earlier version brute-forced the call
    shape, trying ``attach(window, logo)`` first and falling through on
    TypeError. Where the extension's signature happens to accept that, the
    whole window becomes the hit area and three clicks anywhere launch the
    game - which is what users actually experienced. The signature is now
    read by reflection and the logo is passed as the element, or nothing is
    armed at all. An egg that does not fire is a small loss; an egg that
    fires while somebody is clicking Close on an export report is not.

    **Only the main window.** Dialogs and report windows carry the same
    header, and arming every one of them multiplied the chances of setting
    it off by accident. The logo in the top left of the tool is the one.
    """
    host = find(window, element_name)
    if host is None:
        # No logo, nothing to arm. Deliberately not falling back to the
        # window - that fallback is the bug this docstring is about.
        return False

    try:
        from revobim.egg import egg_hook
    except Exception:
        return False

    attach = getattr(egg_hook, 'attach', None)
    if attach is None:
        return False

    names = _argument_names(attach)
    calls = []
    if names is not None:
        count = len(names)
        if count == 0:
            calls = [lambda: attach()]
        elif count == 1:
            calls = [lambda: attach(host)]
        else:
            # Two or more: work out from the parameter names which way round
            # the element goes, rather than guessing and hoping.
            first = (names[0] or '').lower()
            if first in ('window', 'win', 'owner', 'parent'):
                calls = [lambda: attach(window, host)]
            else:
                calls = [lambda: attach(host, window)]
            calls.append(lambda: attach(host))
    else:
        # Reflection did not work (a .NET delegate, a builtin). Narrowest
        # first, and the window is never offered.
        calls = [lambda: attach(host), lambda: attach()]

    for call in calls:
        try:
            call()
            return True
        except TypeError:
            continue
        except Exception:
            return False
    return False
    return False


# ==========================================================================
# the size of the whole tool
# ==========================================================================

# The sizes the - and + step through. 100% is in the list, so a step always
# lands back on it.
ZOOM_STEPS = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6]


def zoom_step(current, direction):
    """The next size along from ``current``: direction 1 bigger, -1
    smaller, 0 back to 100%. A size between two steps snaps to the next one
    in the direction asked, and the ends hold."""
    try:
        current = float(current)
    except Exception:
        current = 1.0
    if direction == 0:
        return 1.0
    if direction > 0:
        bigger = [one for one in ZOOM_STEPS if one > current + 0.001]
        return bigger[0] if bigger else ZOOM_STEPS[-1]
    smaller = [one for one in ZOOM_STEPS if one < current - 0.001]
    return smaller[-1] if smaller else ZOOM_STEPS[0]


def zoom_clamp(value):
    try:
        value = float(value)
    except Exception:
        return 1.0
    return max(ZOOM_STEPS[0], min(ZOOM_STEPS[-1], value))


def zoom_label(scale):
    return u'{0}%'.format(int(round(float(scale) * 100)))


class Zoom(object):
    """- and + in a window's header: the whole tool smaller or bigger.

    A LayoutTransform on the window's content, not a RenderTransform. A
    render transform only draws smaller - the layout still asks for the
    full size and the edges are cut off. A layout transform lays out as if
    the window were bigger (at 80%, a 1240px window lays out 1550px of
    content) and then draws it to fit, which is what "see more on a small
    screen" needs. Kept in ``settings`` under ``key``.

    Looks for ZoomOutButton, ZoomResetButton and ZoomInButton; any missing
    is simply not wired. Ctrl+minus, Ctrl+plus and Ctrl+0 work too.
    """

    def __init__(self, window, settings=None, key='ui_scale'):
        self.window = window
        self.settings = settings
        self.key = key
        self.scale = 1.0
        if settings is not None:
            try:
                self.scale = zoom_clamp(settings.text(key, u'1') or u'1')
            except Exception:
                self.scale = 1.0
        self.reset_button = find(window, 'ZoomResetButton')
        for name, direction in (('ZoomOutButton', -1), ('ZoomInButton', 1),
                                ('ZoomResetButton', 0)):
            button = find(window, name)
            if button is None:
                continue
            try:
                button.Click += self._make_step(direction)
            except Exception:
                pass
        try:
            window.PreviewKeyDown += self._key
        except Exception:
            pass
        self.apply()

    def _make_step(self, direction):
        def handler(sender, args):
            self.step(direction)
        return handler

    def _key(self, sender, args):
        if not ctrl_down():
            return
        try:
            key = args.Key
        except Exception:
            return
        direction = None
        if key in (Key.OemPlus, Key.Add):
            direction = 1
        elif key in (Key.OemMinus, Key.Subtract):
            direction = -1
        elif key in (Key.D0, Key.NumPad0):
            direction = 0
        if direction is None:
            return
        self.step(direction)
        try:
            args.Handled = True
        except Exception:
            pass

    def step(self, direction):
        self.scale = zoom_step(self.scale, direction)
        self.apply()
        if self.settings is not None:
            try:
                self.settings.set(self.key, u'{0:.2f}'.format(
                    float(self.scale)))
                self.settings.save()
            except Exception:
                pass

    def apply(self):
        try:
            self.window.Content.LayoutTransform = ScaleTransform(
                float(self.scale), float(self.scale))
        except Exception:
            pass
        set_content(self.reset_button, zoom_label(self.scale))


# ==========================================================================
# borderless chrome
# ==========================================================================

class Chrome(object):
    """Drag, close, full screen and the resize grips for one window.

    A borderless ``AllowsTransparency`` window cannot be resized by WPF -
    there is nothing hit testable in its transparent frame, so the resize
    border never fires however ResizeMode is set. The window carries eight
    thumbs of its own instead, in an overlay Grid with no Background so
    everything underneath stays clickable.
    """

    GRIPS = {
        'GripNW': (True, True, True, True),
        'GripN': (False, True, False, True),
        'GripNE': (False, True, True, True),
        'GripW': (True, False, True, False),
        'GripE': (False, False, True, False),
        'GripSW': (True, False, True, True),
        'GripS': (False, False, False, True),
        'GripSE': (False, False, True, True),
    }

    # The edges whose double-click stretches the window top to bottom of its
    # screen, as Windows does for its own windows. Corners still resize.
    TALL_EDGES = ('GripN', 'GripS')

    def __init__(self, window, on_close=None):
        self.window = window
        self.on_close = on_close
        self.full_screen = False
        self.saved_bounds = None
        # Where the window was before a double-click stretched it top to
        # bottom; None while it is not stretched.
        self.tall_saved = None
        # Shrunk to its title bar at the bottom of the screen (1.49.0):
        # the bounds and MinHeight to come back to, the owner shrunk along
        # with it, and the drawer animation in flight.
        self.shrunk = False
        self.shrink_saved = None
        self.lifted_owner = None
        self._drawer = None
        self._hidden_parts = []
        self._header_corner = None
        # A callable saying a job is running (the main window's export):
        # the shrunk bar is not dragged then - DragMove is a modal message
        # loop, and Revit's API context is no place to start one.
        self.busy = None
        self._wire()
        _CHROMES.append(self)
        try:
            window.Closed += self._forget
        except Exception:
            pass
        try:
            window.SourceInitialized += self._place_start
        except Exception:
            pass
        try:
            window.PreviewKeyDown += self._preview_key
        except Exception:
            pass

    # ---------------------------------------------------------------- wiring
    def _wire(self):
        window = self.window

        header = find(window, 'HeaderBar')
        if header is not None:
            try:
                header.MouseLeftButtonDown += self._header_down
            except Exception:
                pass

        close_button = find(window, 'CloseButton')
        if close_button is not None:
            try:
                close_button.Click += self._close_clicked
            except Exception:
                pass

        full_button = find(window, 'FullScreenButton')
        if full_button is not None:
            try:
                full_button.Click += self._full_clicked
            except Exception:
                pass

        shrink_button = find(window, 'ShrinkButton')
        if shrink_button is not None:
            try:
                shrink_button.Click += self._shrink_clicked
            except Exception:
                pass

        try:
            window.KeyDown += self._key_down
        except Exception:
            pass

        for name in self.GRIPS:
            thumb = find(window, name)
            if thumb is None:
                continue
            try:
                thumb.DragDelta += self._make_grip(name)
            except Exception:
                continue
            if name in self.TALL_EDGES:
                # Preview: seen before the thumb takes the press for a drag.
                try:
                    thumb.PreviewMouseLeftButtonDown += self._edge_down
                except Exception:
                    pass

    def _make_grip(self, name):
        left, top, width, height = self.GRIPS[name]

        def handler(sender, args):
            self._resize(args, left, top, width, height)

        return handler

    # ------------------------------------------------------------- behaviour
    def _edge_down(self, sender, args):
        """A double-click on the top or bottom edge: the full height of the
        screen, and back again on the next."""
        try:
            if args.ClickCount != 2:
                return
            args.Handled = True
        except Exception:
            return
        self.toggle_tall()

    def toggle_tall(self):
        """Stretch the window to its screen's full working height, keeping
        its width and left edge - or, already stretched, put it back.
        Returns True when it is now stretched, False when put back, None
        when nothing could be done (full screen already fills it)."""
        if self.full_screen or self.shrunk:
            return None
        area = working_area(self.window)
        if not area:
            return None
        try:
            top, height, self.tall_saved = full_height(
                area, self.window.Top, self.window.Height, self.tall_saved)
            self.window.Top = top
            self.window.Height = height
        except Exception:
            return None
        return self.tall_saved is not None

    def _header_down(self, sender, args):
        try:
            if args.ClickCount == 2:
                # A shrunk bar's double-click brings the window back; it
                # does not go full screen from the bottom of the screen.
                if self.shrunk:
                    self.expand()
                    return
                self.toggle_full_screen()
                return
            if self.shrunk:
                # The bar can be dragged along the bottom of the screen -
                # but not while a job runs.
                if self.busy is not None and self.busy():
                    return
                self.window.DragMove()
                return
            if self.full_screen:
                # Dragging a full screen window is asking to leave it.
                self.set_full_screen(False)
            self.window.DragMove()
        except Exception:
            pass

    def _close_clicked(self, sender, args):
        if self.on_close is not None:
            try:
                self.on_close()
                return
            except Exception:
                pass
        try:
            self.window.Close()
        except Exception:
            pass

    def _full_clicked(self, sender, args):
        self.toggle_full_screen()

    def _key_down(self, sender, args):
        try:
            if args.Key == Key.F11:
                self.toggle_full_screen()
                args.Handled = True
                return
            if args.Key == Key.Escape and self.full_screen:
                self.set_full_screen(False)
                args.Handled = True
        except Exception:
            pass

    def _resize(self, args, move_left, move_top, change_width, change_height):
        window = self.window
        if self.shrunk or self._drawer is not None:
            return
        try:
            dx = args.HorizontalChange
            dy = args.VerticalChange
            min_width = window.MinWidth or 200
            min_height = window.MinHeight or 150

            if change_width:
                if move_left:
                    new_width = window.Width - dx
                    if new_width >= min_width:
                        window.Left = window.Left + dx
                        window.Width = new_width
                else:
                    new_width = window.Width + dx
                    if new_width >= min_width:
                        window.Width = new_width
            if change_height:
                if move_top:
                    new_height = window.Height - dy
                    if new_height >= min_height:
                        window.Top = window.Top + dy
                        window.Height = new_height
                else:
                    new_height = window.Height + dy
                    if new_height >= min_height:
                        window.Height = new_height
            if self.full_screen:
                self.full_screen = False
                self._say_full_screen()
        except Exception:
            pass

    # ------------------------------------------------------------ full screen
    def toggle_full_screen(self):
        if self.shrunk:
            return
        self.set_full_screen(not self.full_screen)

    # ------------------------------------------------------- shrink drawer
    # The window slides down to the bottom of its screen like a drawer
    # closing, until only its title bar floats there, so Revit can be seen
    # without closing anything. The shrink button turns into a green up
    # arrow that slides it back. Every Pro Sheets window has it: a window
    # with a ShrinkButton in its header gets it from here.
    DRAWER_SECONDS = 0.28
    DRAWER_TICK_MS = 15
    BAR_MARGIN = 8
    BAR_GAP = 4

    def _shrink_clicked(self, sender, args):
        self.toggle_shrink()

    def _preview_key(self, sender, args):
        """Ctrl+Shift+H shrinks or brings back. While shrunk, Escape, Enter
        and F11 bring the window back - Escape must not reach a dialog's
        Cancel, nor F11 fill the screen with a window nobody can see."""
        try:
            key = args.Key
            modifiers = Keyboard.Modifiers
            control = (modifiers & ModifierKeys.Control) == ModifierKeys.Control
            shift = (modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
        except Exception:
            return
        try:
            if key == Key.H and control and shift:
                self.toggle_shrink()
                args.Handled = True
                return
            if self.shrunk and key in (Key.Escape, Key.Enter, Key.Return,
                                       Key.F11):
                self.expand()
                args.Handled = True
        except Exception:
            pass

    def _place_start(self, sender=None, args=None):
        """A dialog opening over a shrunk owner is centred on its screen.
        Centred on the owner it would sit on a 42-pixel bar at the bottom,
        most of it off the screen - and that is when a prompt turns up
        unasked, while the tool is put away."""
        owner = chrome_of(getattr(self.window, 'Owner', None))
        if owner is None or not owner.shrunk:
            return
        area = working_area(owner.window)
        if not area:
            return
        try:
            left, top = centred(area, self.window.Width, self.window.Height)
            self.window.WindowStartupLocation = WindowStartupLocation.Manual
            self.window.Left = left
            self.window.Top = top
        except Exception:
            pass

    def _pin(self, height):
        """Hold the body at a fixed height for the slide and let the
        window clip it, so a virtualising grid is not re-measured on every
        frame - a drawer drawn away, not a window squashed."""
        content = getattr(self.window, 'Content', None)
        if content is None:
            return
        try:
            content.Height = float(height)
            content.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass

    def _unpin(self):
        content = getattr(self.window, 'Content', None)
        if content is None:
            return
        try:
            content.Height = float('nan')
            content.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    def toggle_shrink(self):
        if self.shrunk:
            self.expand()
        else:
            self.shrink()

    def true_size(self):
        """(width, height) of the window as the user left it: the size to
        remember, never the shrunk bar's."""
        if self.shrink_saved is not None:
            return self.shrink_saved[2], self.shrink_saved[3]
        return self.window.Width, self.window.Height

    def bar_height(self):
        """The window's height with only its title bar showing."""
        header = find(self.window, 'HeaderBar')
        if header is None:
            return 44.0
        try:
            offset = header.TranslatePoint(Point(0, 0), self.window).Y
            return float(header.ActualHeight + 2 * max(0.0, offset))
        except Exception:
            try:
                return float(header.ActualHeight) + 2.0
            except Exception:
                return 44.0

    def shrink(self):
        """Slide down to the bottom of the screen, title bar only."""
        if self.shrunk or self._drawer is not None:
            return False
        window = self.window
        # A dialog over a Pro Sheets window would still leave that window
        # covering Revit, so the owner goes down with it, first.
        owner = chrome_of(getattr(window, 'Owner', None))
        if owner is not None and not owner.shrunk:
            if owner.shrink():
                self.lifted_owner = owner
        area = working_area(window)
        if not area:
            return False
        try:
            self.shrink_saved = (window.Left, window.Top, window.Width,
                                 window.Height, window.MinHeight)
            bar = self.bar_height()
            below = [other.bar_height() for other in _SHRUNK]
            top = shrunk_top(area, bar, below, self.BAR_MARGIN, self.BAR_GAP)
            window.MinHeight = 0
        except Exception:
            self.shrink_saved = None
            return False
        self.shrunk = True
        _SHRUNK.append(self)
        self._paint_shrink()
        self._pin(window.Height)
        self._animate(window.Top, window.Height, top, bar, self._shrunk_done)
        return True

    def expand(self):
        """Slide back up to where the window was."""
        if not self.shrunk or self._drawer is not None:
            return False
        saved = self.shrink_saved
        self._show_parts()
        self.shrunk = False
        if self in _SHRUNK:
            _SHRUNK.remove(self)
        self._paint_shrink()
        if saved is None:
            return True

        def done():
            self._unpin()
            try:
                self.window.MinHeight = saved[4]
            except Exception:
                pass
            self.shrink_saved = None
            owner = self.lifted_owner
            self.lifted_owner = None
            if owner is not None:
                owner.expand()
            try:
                self.window.Activate()
            except Exception:
                pass

        try:
            self.window.Left = saved[0]
        except Exception:
            pass
        self._pin(saved[3])
        self._animate(self.window.Top, self.window.Height, saved[1],
                      saved[3], done)
        return True

    def restore_now(self):
        """Put the window back at once, no animation - before it closes."""
        self._stop_drawer()
        saved = self.shrink_saved
        if saved is None:
            return
        self._show_parts()
        self._unpin()
        try:
            (self.window.Left, self.window.Top, self.window.Width,
             self.window.Height, self.window.MinHeight) = saved
        except Exception:
            pass
        self.shrunk = False
        self.shrink_saved = None
        if self in _SHRUNK:
            _SHRUNK.remove(self)
        self._paint_shrink()

    def _shrunk_done(self):
        self._hide_parts()
        self._unpin()

    def _hide_parts(self):
        """Everything but the title bar collapsed, its corners rounded, so
        the bar floats as a bar rather than a window cut off below it."""
        header = find(self.window, 'HeaderBar')
        if header is None:
            return
        self._hidden_parts = []
        try:
            for child in header.Parent.Children:
                if child is header or child.Visibility != Visibility.Visible:
                    continue
                child.Visibility = Visibility.Collapsed
                self._hidden_parts.append(child)
        except Exception:
            pass
        # The resize grips too: a bar is moved, not resized.
        for name in self.GRIPS:
            thumb = find(self.window, name)
            if thumb is None:
                continue
            try:
                if thumb.Visibility == Visibility.Visible:
                    thumb.Visibility = Visibility.Collapsed
                    self._hidden_parts.append(thumb)
            except Exception:
                continue
        try:
            self._header_corner = header.CornerRadius
            radius = header.CornerRadius.TopLeft or 5
            header.CornerRadius = CornerRadius(radius)
        except Exception:
            self._header_corner = None

    def _show_parts(self):
        for child in self._hidden_parts:
            try:
                child.Visibility = Visibility.Visible
            except Exception:
                pass
        self._hidden_parts = []
        header = find(self.window, 'HeaderBar')
        corner = getattr(self, '_header_corner', None)
        if header is not None and corner is not None:
            try:
                header.CornerRadius = corner
            except Exception:
                pass
        self._header_corner = None

    def _paint_shrink(self):
        """The button's Tag drives its glyph: the shrink arrow, or the
        green up arrow once shrunk (ShrinkButton style in Theme.xaml)."""
        button = find(self.window, 'ShrinkButton')
        if button is None:
            return
        try:
            button.Tag = u'shrunk' if self.shrunk else u''
            button.ToolTip = (u'Expand the window' if self.shrunk else
                              u'Shrink to the bottom of the screen')
        except Exception:
            pass

    def _animate(self, top, height, end_top, end_height, done=None):
        """Top and Height eased from where they are to the end, on a
        DispatcherTimer - a Storyboard on a borderless window's Top and
        Height fights the layout pass and judders."""
        self._stop_drawer()
        start = time.time()
        window = self.window

        def tick(sender, args):
            progress = (time.time() - start) / self.DRAWER_SECONDS
            eased = ease_out(progress)
            try:
                window.Top = top + (end_top - top) * eased
                window.Height = max(1.0, height + (end_height - height) *
                                    eased)
            except Exception:
                progress = 1.0
            if progress >= 1.0:
                self._stop_drawer()
                if done is not None:
                    try:
                        done()
                    except Exception:
                        pass

        try:
            timer = DispatcherTimer()
            timer.Interval = TimeSpan.FromMilliseconds(self.DRAWER_TICK_MS)
            timer.Tick += tick
            self._drawer = timer
            timer.Start()
        except Exception:
            # No timer: jump straight there.
            self._drawer = None
            try:
                window.Top = end_top
                window.Height = end_height
            except Exception:
                pass
            if done is not None:
                done()

    def _stop_drawer(self):
        timer = self._drawer
        self._drawer = None
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass

    def _forget(self, sender=None, args=None):
        """Closed: out of the lists, and an owner it took down brought back
        - a dialog closed from its bar must not strand the main window."""
        self._stop_drawer()
        if self in _SHRUNK:
            _SHRUNK.remove(self)
        if self in _CHROMES:
            _CHROMES.remove(self)
        owner = self.lifted_owner
        self.lifted_owner = None
        if owner is not None:
            owner.expand()

    def set_full_screen(self, wanted):
        """Full screen by bounds, never ``WindowState.Maximized``.

        Maximising a borderless AllowsTransparency window the normal way
        covers the task bar and lands on the primary monitor rather than the
        one the window is on.
        """
        window = self.window
        try:
            if wanted and not self.full_screen:
                self.saved_bounds = (window.Left, window.Top,
                                     window.Width, window.Height)
                bounds = working_area(window)
                if bounds is None:
                    return
                window.Left, window.Top, window.Width, window.Height = bounds
                self.full_screen = True
            elif not wanted and self.full_screen:
                if self.saved_bounds:
                    (window.Left, window.Top,
                     window.Width, window.Height) = self.saved_bounds
                self.full_screen = False
        except Exception:
            pass
        self._say_full_screen()

    def _say_full_screen(self):
        button = find(self.window, 'FullScreenButton')
        if button is None:
            return
        try:
            button.ToolTip = (u'Leave full screen (F11)' if self.full_screen
                              else u'Full screen (F11)')
        except Exception:
            pass


def working_area(window):
    """The usable bounds of whichever screen this window is on, in DIPs.

    ``SystemParameters.WorkArea`` is the primary monitor's, not the window's,
    so it puts a full screen window on the wrong display the moment there is
    more than one. Find the screen from the window handle, then divide by the
    DPI scale - without that division it overshoots on a scaled display.
    """
    try:
        from System.Windows.Forms import Screen
        handle = WindowInteropHelper(window).Handle
        screen = Screen.FromHandle(handle)
        area = screen.WorkingArea

        scale_x = scale_y = 1.0
        try:
            presentation = PresentationSource.FromVisual(window)
            if presentation is not None and presentation.CompositionTarget is not None:
                matrix = presentation.CompositionTarget.TransformToDevice
                scale_x = matrix.M11 or 1.0
                scale_y = matrix.M22 or 1.0
        except Exception:
            scale_x = scale_y = 1.0

        return (area.Left / scale_x, area.Top / scale_y,
                area.Width / scale_x, area.Height / scale_y)
    except Exception:
        try:
            return (0.0, 0.0,
                    SystemParameters.WorkArea.Width,
                    SystemParameters.WorkArea.Height)
        except Exception:
            return None


def snug_width(needed, area_width, minimum=0, margin=12):
    """A window's width: what its content needs, never wider than its
    screen less ``margin`` each side, never narrower than ``minimum``."""
    return max(float(minimum), min(float(needed),
                                   float(area_width) - 2 * margin))


# Every live window's Chrome, and the ones shrunk to a bar, bottom first.
_CHROMES = []
_SHRUNK = []


def chrome_of(window):
    """The Chrome looking after a Pro Sheets window, or None."""
    if window is None:
        return None
    for chrome in _CHROMES:
        if chrome.window is window:
            return chrome
    return None


def centred(area, width, height):
    """(left, top) centring a window of this size on a working area."""
    return (float(area[0]) + (float(area[2]) - float(width)) / 2.0,
            float(area[1]) + (float(area[3]) - float(height)) / 2.0)


def ease_out(progress):
    """0 to 1, quick at first and settling at the end - a drawer."""
    progress = max(0.0, min(1.0, float(progress)))
    return 1.0 - (1.0 - progress) ** 3


def shrunk_top(area, bar, below=(), margin=8, gap=4):
    """Where a shrunk title bar sits: on the bottom of the screen's working
    ``area``, above any bars already shrunk there (``below``, their
    heights), so a dialog and its owner stack rather than overlap."""
    bottom = float(area[1]) + float(area[3]) - float(margin)
    for height in below or ():
        bottom -= float(height) + float(gap)
    return bottom - float(bar)


def full_height(area, top, height, saved=None):
    """(top, height, saved) after a double-click on a window's bottom bar:
    the full height of its screen's working ``area``, remembering where it
    was - or, when it is already stretched (``saved``), back to that."""
    if saved is not None:
        return float(saved[0]), float(saved[1]), None
    return float(area[1]), float(area[3]), (float(top), float(height))


def owner_area(owner=None, owner_handle=None):
    """The working area of the screen a window's owner is on: a WPF
    owner, Revit's main window by handle, or the primary screen."""
    area = None
    if owner is not None:
        area = working_area(owner)
    elif owner_handle is not None:
        area = handle_area(owner_handle)
    if not area:
        try:
            work = SystemParameters.WorkArea
            area = (work.Left, work.Top, work.Width, work.Height)
        except Exception:
            area = None
    return area


def fit_width(window, needed, owner=None, owner_handle=None, margin=12):
    """Make ``window`` as wide as ``needed`` - its content - and no wider
    than its owner's screen, centred on it left to right. Where the screen
    is narrower, what does not fit scrolls."""
    area = owner_area(owner, owner_handle)
    if not area:
        return False
    try:
        width = snug_width(needed, area[2], window.MinWidth or 0, margin)
        window.Width = width
        window.Left = area[0] + (area[2] - width) / 2.0
        return True
    except Exception:
        return False


def handle_area(handle):
    """The working area, in DIPs, of the screen a window handle is on - for
    a window owned by Revit's main window rather than a WPF one."""
    try:
        from System.Windows.Forms import Screen
        screen = Screen.FromHandle(handle)
        area = screen.WorkingArea
        scale = 1.0
        try:
            scale = float(Screen.PrimaryScreen.Bounds.Width) / \
                float(SystemParameters.PrimaryScreenWidth) or 1.0
        except Exception:
            scale = 1.0
        return (area.Left / scale, area.Top / scale, area.Width / scale,
                area.Height / scale)
    except Exception:
        return None


# ==========================================================================
# owning the window to Revit
# ==========================================================================

def own_to_revit(window, uiapp):
    """Make Revit's main window the owner of this one.

    An unowned modeless window slips behind Revit the moment Revit takes
    focus, and reads to the user as a crash. Owning it keeps it in front of
    Revit while leaving Revit completely usable underneath.
    """
    try:
        handle = uiapp.MainWindowHandle
    except Exception:
        handle = None
    if handle is None:
        return False
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = handle
        return True
    except Exception:
        return False


# ==========================================================================
# folder browsing
# ==========================================================================

def browse_folder(start=u'', description=u'Where should the export go?'):
    """A folder picker. Returns the chosen path, or an empty string."""
    dialog = None
    try:
        from System.Windows.Forms import FolderBrowserDialog, DialogResult
        dialog = FolderBrowserDialog()
        dialog.Description = description
        dialog.ShowNewFolderButton = True
        if start and os.path.isdir(start):
            dialog.SelectedPath = start
        if dialog.ShowDialog() == DialogResult.OK:
            return u'{0}'.format(dialog.SelectedPath)
    except Exception:
        pass
    finally:
        if dialog is not None:
            try:
                dialog.Dispose()
            except Exception:
                pass
    return u''


def pick_file(save, title, extension, start_name=u'',
              label=u'RevoBIM template bundle'):
    """A file open or save dialog. Returns a path, or an empty string."""
    dialog = None
    try:
        from System.Windows.Forms import (OpenFileDialog, SaveFileDialog,
                                          DialogResult)
        dialog = SaveFileDialog() if save else OpenFileDialog()
        dialog.Title = title
        dialog.Filter = ('{1} (*{0})|*{0}|'
                         'Text file (*.txt)|*.txt|'
                         'All files (*.*)|*.*'.format(extension, label))
        dialog.DefaultExt = extension.lstrip('.')
        if start_name:
            dialog.FileName = start_name
        if not save:
            dialog.Multiselect = False
        if dialog.ShowDialog() == DialogResult.OK:
            return u'{0}'.format(dialog.FileName)
    except Exception:
        pass
    finally:
        if dialog is not None:
            try:
                dialog.Dispose()
            except Exception:
                pass
    return u''


def ask_text(title, question, start=u'', theme_name='dark', owner=None):
    """A one line text prompt, built from the message window."""
    prompt = Prompt(title=title, headline=question, want_input=True,
                    input_text=start, primary=u'OK', secondary=u'Cancel',
                    theme_name=theme_name, owner=owner)
    if prompt.show() == 'primary':
        return (prompt.input_value or u'').strip()
    return None


# ==========================================================================
# the message window
# ==========================================================================

class Prompt(object):
    """A themed message, question or result window.

    Results are reported here, never in the pyRevit output window.
    """

    def __init__(self, title=u'Pro Sheets Exporter', headline=u'',
                 message=u'', detail=u'', primary=u'Close', secondary=None,
                 extra=None, theme_name='dark', owner=None,
                 want_input=False, input_text=u''):
        self.answer = None
        self.input_value = input_text
        self.window = load_window('ProSheetsPrompt.xaml', theme_name)
        self.chrome = Chrome(self.window)
        # No egg here. A message window is something you dismiss, often
        # several in a row, and arming it turned "clicking Close" into a
        # way to start a game.

        self._set('SubtitleText', title)
        self._set('HeadlineText', headline)
        self._set('MessageText', message)
        self._set('DetailText', detail)

        if not detail:
            scroller = find(self.window, 'DetailScroller')
            if scroller is not None:
                try:
                    scroller.Parent.Visibility = Visibility.Collapsed
                except Exception:
                    pass

        self._button('PrimaryButton', primary, 'primary')
        self._button('SecondaryButton', secondary, 'secondary')
        self._button('ExtraButton', extra, 'extra')

        copy_button = find(self.window, 'CopyButton')
        if copy_button is not None:
            if detail:
                try:
                    copy_button.Click += self._copy
                except Exception:
                    pass
            else:
                try:
                    copy_button.Visibility = Visibility.Collapsed
                except Exception:
                    pass

        self.want_input = want_input
        if want_input:
            self._make_input(input_text)

        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass

    def _set(self, name, text):
        element = find(self.window, name)
        if element is None:
            return
        try:
            element.Text = u'{0}'.format(text or u'')
        except Exception:
            pass

    def _button(self, name, caption, answer):
        button = find(self.window, name)
        if button is None:
            return
        if not caption:
            try:
                button.Visibility = Visibility.Collapsed
            except Exception:
                pass
            return
        try:
            button.Content = caption
            button.Visibility = Visibility.Visible
            button.Click += self._make_answer(answer)
        except Exception:
            pass

    def _make_answer(self, answer):
        def handler(sender, args):
            self.answer = answer
            if self.want_input:
                box = find(self.window, 'PromptInput')
                if box is not None:
                    try:
                        self.input_value = u'{0}'.format(box.Text)
                    except Exception:
                        pass
            if answer == 'extra':
                # The extra button acts and leaves the window open.
                return
            try:
                self.window.DialogResult = (answer == 'primary')
            except Exception:
                pass
            try:
                self.window.Close()
            except Exception:
                pass
        return handler

    def _make_input(self, start):
        from System.Windows.Controls import TextBox
        host = find(self.window, 'MessageText')
        if host is None:
            return
        try:
            box = TextBox()
            box.Name = 'PromptInput'
            box.Text = u'{0}'.format(start or u'')
            box.Margin = self.window.FindName('MessageText').Margin
            box.MinWidth = 320
            box.HorizontalAlignment = HorizontalAlignment.Stretch
            parent = host.Parent
            parent.Children.Add(box)
            self.window.RegisterName('PromptInput', box)
            box.Focus()
            box.SelectAll()
        except Exception:
            pass

    def _copy(self, sender, args):
        try:
            from System.Windows import Clipboard
            element = find(self.window, 'DetailText')
            if element is not None:
                Clipboard.SetText(u'{0}'.format(element.Text))
            button = find(self.window, 'CopyButton')
            if button is not None:
                button.Content = u'Copied'
        except Exception:
            pass

    def on_extra(self, handler):
        button = find(self.window, 'ExtraButton')
        if button is not None:
            try:
                button.Click += handler
            except Exception:
                pass

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            try:
                self.window.Show()
            except Exception:
                pass
        return self.answer


# ==========================================================================
# reporting a failure the user can act on
# ==========================================================================

def report_failure(stage, error=None, theme_name='dark'):
    """Name the stage that failed, show the traceback, and write it down.

    A tool that is one big script has no runtime left to report its own
    import failure, which is why the loader stages the work. Getting this in
    front of the user is the difference between a blank window and a message
    naming the file, the line and the column.
    """
    detail = traceback.format_exc()
    if error is not None and 'NoneType' in detail:
        detail = u'{0}'.format(error)
    text = u'Stage: {0}\n\n{1}\n\n{2}'.format(stage, error or u'', detail)
    try:
        path = ps_config.error_path()
        handle = open(path, 'wb')
        try:
            handle.write(text.encode('utf-8'))
        finally:
            handle.close()
    except Exception:
        path = u'(the log file could not be written)'

    try:
        Prompt(title='Pro Sheets Exporter',
               headline=u'The tool could not open.',
               message=u'It stopped at "{0}". The detail below is also '
                       u'saved to {1}'.format(stage, path),
               detail=text, primary=u'Close',
               theme_name=theme_name).show()
        return
    except Exception:
        pass

    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show('RevoBIM Pro Sheets Exporter',
                        u'Stopped at "{0}".\n\n{1}'.format(stage, detail)[:2000])
    except Exception:
        sys.stderr.write(text)


# ==========================================================================
# small conveniences
# ==========================================================================

def set_visible(element, visible):
    if element is None:
        return
    try:
        element.Visibility = Visibility.Visible if visible else Visibility.Collapsed
    except Exception:
        pass


def set_text(element, text):
    if element is None:
        return
    try:
        element.Text = u'{0}'.format(text)
    except Exception:
        pass


def set_content(element, text):
    if element is None:
        return
    try:
        element.Content = u'{0}'.format(text)
    except Exception:
        pass


def fill_combo(combo, items, selected=None, allow_blank=False,
               blank_text=u'(none)'):
    """Load a ComboBox and pick an entry without firing the change handler.

    The caller detaches its own handler; this only guarantees the order, so a
    selection made here is not mistaken for one the user made.
    """
    if combo is None:
        return
    try:
        combo.Items.Clear()
        if allow_blank:
            combo.Items.Add(blank_text)
        for item in items:
            combo.Items.Add(u'{0}'.format(item))
        if selected is not None:
            for index in range(combo.Items.Count):
                if u'{0}'.format(combo.Items[index]) == u'{0}'.format(selected):
                    combo.SelectedIndex = index
                    return
        if combo.Items.Count and combo.SelectedIndex < 0:
            combo.SelectedIndex = 0
    except Exception:
        pass


def combo_text(combo, blank_text=u'(none)'):
    if combo is None:
        return u''
    try:
        value = combo.SelectedItem
        if value is None:
            return u''
        text = u'{0}'.format(value)
        return u'' if text == blank_text else text
    except Exception:
        return u''


def ctrl_down():
    try:
        return (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control
    except Exception:
        return False


def shift_down():
    try:
        return (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
    except Exception:
        return False


# ==========================================================================
# a box you type into to pick from a long list
# ==========================================================================

def words_match(names, text):
    """The names holding every word typed, anywhere, in any case."""
    words = u'{0}'.format(text or u'').lower().split()
    if not words:
        return list(names)
    return [name for name in names
            if all([word in u'{0}'.format(name).lower() for word in words])]


class SearchPicker(object):
    """A text box with a list under it. Typing narrows the list to the
    names containing what is typed; click one, or arrow to it and press
    Enter, to pick it. The caret beside the box shows the whole list.

    A themed stand-in for an editable ComboBox, whose template the theme
    does not carry and whose typed text and picked item fight each other.
    ``value`` is the picked name, or u'' while what is typed matches none.
    """

    CARET = (u'<Path xmlns="http://schemas.microsoft.com/winfx/2006/xaml/'
             u'presentation" Width="8" Height="5" Stretch="Uniform"'
             u' Fill="{DynamicResource MutedBrush}" Data="M 0,0 L 8,0 L 4,5 Z"/>')

    def __init__(self, items=None, value=u'', on_change=None,
                 hint=u'Type to search', matcher=None, height=28):
        self.items = [u'{0}'.format(item) for item in (items or [])]
        self.value = u''
        self.on_change = on_change
        self.matcher = matcher or words_match
        self._suspend = False

        self.element = Grid()
        self.element.Height = height
        for width in (None, 26):
            definition = ColumnDefinition()
            if width:
                definition.Width = GridLength(width)
            self.element.ColumnDefinitions.Add(definition)
        self.box = TextBox()
        self.box.Tag = hint
        self.box.ToolTip = u'Type part of the name - the list narrows to ' \
            u'the names containing it. Down and Enter, or a click, to pick.'
        Grid.SetColumn(self.box, 0)
        self.element.Children.Add(self.box)
        self.caret = Button()
        self.caret.SetResourceReference(Button.StyleProperty, 'IconButton')
        self.caret.Width = 24
        self.caret.ToolTip = u'Show the whole list'
        try:
            self.caret.Content = XamlReader.Parse(self.CARET)
        except Exception:
            self.caret.Content = u'v'
        Grid.SetColumn(self.caret, 1)
        self.element.Children.Add(self.caret)

        self.list = ListBox()
        self.list.MaxHeight = 260
        self.list.BorderThickness = Thickness(0)
        shell = Border()
        shell.SetResourceReference(Border.BackgroundProperty, 'CardBg')
        shell.SetResourceReference(Border.BorderBrushProperty, 'EdgeBrush')
        shell.BorderThickness = Thickness(1)
        shell.CornerRadius = CornerRadius(3)
        shell.Padding = Thickness(1)
        shell.Child = self.list
        self.shell = shell
        self.popup = Popup()
        self.popup.PlacementTarget = self.element
        self.popup.Placement = PlacementMode.Bottom
        self.popup.StaysOpen = False
        self.popup.AllowsTransparency = True
        self.popup.Child = shell
        # In the picker's own Grid, so the list is in the window's logical
        # tree and its DynamicResource colours resolve.
        self.element.Children.Add(self.popup)

        self.box.TextChanged += self._typed
        self.box.PreviewKeyDown += self._key
        self.caret.Click += self._show_all
        self.list.PreviewMouseLeftButtonUp += self._clicked
        self.set_value(value)

    # ------------------------------------------------------------------
    @staticmethod
    def shown(items, text, value, matcher=None):
        """The names on offer for what is in the box: all of them while it
        is empty or still shows the picked name, else those that match."""
        text = u'{0}'.format(text or u'').strip()
        if not text or (value and text == value):
            return list(items)
        return (matcher or words_match)(items, text)

    @staticmethod
    def resolve(items, text):
        """The name the box holds exactly, any case, or u''."""
        text = u'{0}'.format(text or u'').strip().lower()
        if not text:
            return u''
        for item in items:
            if u'{0}'.format(item).lower() == text:
                return item
        return u''

    def text(self):
        try:
            return u'{0}'.format(self.box.Text or u'')
        except Exception:
            return u''

    def set_items(self, items, value=None):
        self.items = [u'{0}'.format(item) for item in (items or [])]
        self.set_value(self.value if value is None else value)

    def set_value(self, value):
        """Show a name as picked, without telling on_change."""
        value = u'{0}'.format(value or u'')
        self.value = value if value in self.items else u''
        self._suspend = True
        try:
            self.box.Text = self.value
        finally:
            self._suspend = False

    def set_enabled(self, enabled):
        for part in (self.box, self.caret):
            try:
                part.IsEnabled = bool(enabled)
            except Exception:
                pass
        if not enabled:
            self._close()

    # ------------------------------------------------------------------
    def _fill(self, names):
        self.list.Items.Clear()
        for name in names:
            self.list.Items.Add(name)

    def _open(self, names):
        self._fill(names)
        try:
            # At least as wide as the box, as a ComboBox's list is.
            self.shell.MinWidth = self.element.ActualWidth
        except Exception:
            pass
        self.popup.IsOpen = bool(names)

    def _close(self):
        try:
            self.popup.IsOpen = False
        except Exception:
            pass

    def _typed(self, sender, args):
        if self._suspend:
            return
        text = self.text()
        self.value = self.resolve(self.items, text)
        names = self.shown(self.items, text, self.value, self.matcher)
        if text.strip() and not self.value:
            self._open(names)
        else:
            self._close()
        self._tell()

    def _show_all(self, sender, args):
        self._open(self.items)
        if self.value in self.items:
            self.list.SelectedItem = self.value
        try:
            self.box.Focus()
        except Exception:
            pass

    def _key(self, sender, args):
        try:
            key = args.Key
        except Exception:
            return
        count = self.list.Items.Count
        if key in (Key.Down, Key.Up):
            if not self.popup.IsOpen:
                self._open(self.shown(self.items, self.text(), self.value,
                                      self.matcher))
                count = self.list.Items.Count
            if count:
                step = 1 if key == Key.Down else -1
                index = max(0, min(count - 1, self.list.SelectedIndex + step))
                self.list.SelectedIndex = index
                self.list.ScrollIntoView(self.list.SelectedItem)
            args.Handled = True
        elif key == Key.Enter and self.popup.IsOpen:
            if self.list.SelectedItem is not None:
                self.pick(self.list.SelectedItem)
            elif count == 1:
                self.pick(self.list.Items[0])
            args.Handled = True
        elif key == Key.Escape and self.popup.IsOpen:
            self._close()
            args.Handled = True

    def _clicked(self, sender, args):
        # Only a press on a name picks it - not one on the scroll bar.
        try:
            item = ItemsControl.ContainerFromElement(self.list,
                                                     args.OriginalSource)
        except Exception:
            item = None
        if isinstance(item, ListBoxItem) and \
                self.list.SelectedItem is not None:
            self.pick(self.list.SelectedItem)

    def pick(self, name):
        name = u'{0}'.format(name or u'')
        self._close()
        self.set_value(name)
        try:
            self.box.Focus()
            self.box.CaretIndex = len(self.text())
        except Exception:
            pass
        self._tell()

    def _tell(self):
        if self.on_change is not None:
            try:
                self.on_change(self)
            except Exception:
                pass
