# -*- coding: utf-8 -*-
"""Family Viewer - XAML loading, theming, window chrome, resizing, full screen,
docking to Revit's edges, and the themed prompt.
"""

import fv_clr  # noqa: F401  - must be first

import os

from System.IO import File, MemoryStream, StringReader
from System.Windows import (
    FrameworkElement, HorizontalAlignment, PresentationSource,
    ResourceDictionary, VerticalAlignment, Visibility, WindowState,
)
from System.Windows.Controls.Primitives import Thumb
from System.Windows.Input import Cursors
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage
from System.Xml import XmlReader

import fv_core
import theme

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_FILE = os.path.join(HERE, 'Theme.xaml')

GRIP = 6.0
SNAP_EDGE = 16.0


# ---------------------------------------------------------------------------
# XAML
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# small shared helpers.  These used to be copied between modules - the
# ancestor walk lived in two files and the folder-opening code in two places -
# which is how two copies of a fix end up disagreeing.
# ---------------------------------------------------------------------------

def styled(control, key):
    """Give a control a theme style.  Cosmetic, so it never raises."""
    try:
        control.SetResourceReference(FrameworkElement.StyleProperty, key)
    except Exception:
        pass
    return control


def ancestor(element, wanted=None, tag=None, tag_prefix=None, depth=24):
    """Walk up the visual tree to the first node of a type, or carrying a Tag
    (exactly, or starting with a prefix)."""
    from System.Windows.Media import VisualTreeHelper
    node = element
    steps = 0
    while node is not None and steps < depth:
        if wanted is not None and isinstance(node, wanted):
            return node
        if tag is not None or tag_prefix is not None:
            try:
                text = str(getattr(node, 'Tag', '') or '')
            except Exception:
                text = ''
            if tag is not None and text == tag:
                return node
            if tag_prefix is not None and text.startswith(tag_prefix):
                return node
        try:
            node = VisualTreeHelper.GetParent(node)
        except Exception:
            return None
        steps += 1
    return None


def open_folder(path):
    """Open Explorer on a file, selecting it, or on its folder."""
    from System.Diagnostics import Process
    try:
        Process.Start('explorer.exe', '/select,"' + path + '"')
        return True
    except Exception:
        pass
    try:
        Process.Start(os.path.dirname(path))
        return True
    except Exception:
        fv_core.log('could not open the folder:\n' + fv_core.format_exc())
        return False


def _parse(path):
    handle = open(path, 'r')
    try:
        text = handle.read()
    finally:
        handle.close()
    try:
        text = text.decode('utf-8')
    except Exception:
        pass
    return XamlReader.Load(XmlReader.Create(StringReader(text)))


def load_dictionary(path=None):
    dictionary = _parse(path or THEME_FILE)
    if not isinstance(dictionary, ResourceDictionary):
        raise ValueError('Theme.xaml did not parse as a ResourceDictionary.')
    return dictionary


def load_window(xaml_name, palette_name='dark'):
    """Parse the layout, merge Theme.xaml into it, then write the palette
    straight onto window.Resources.

    Theme.xaml is merged AFTER the layout is parsed, so a StaticResource in a
    layout file would fail at load - which is the blank white pyRevit window.
    Layouts use DynamicResource only, and the bench check enforces it.
    """
    path = xaml_name
    if not os.path.isabs(path):
        path = os.path.join(HERE, xaml_name)
    window = _parse(path)
    window.Resources.MergedDictionaries.Add(load_dictionary())
    theme.apply(window, palette_name)
    return window


def load_element(xaml_name, palette_name=None):
    """Parse a layout whose root is a plain element rather than a Window.

    Pass a palette name where the element is the top of its own tree - the
    dockable pane, which has no window above it to resolve a brush from.  Pass
    None where it is going inside a window that has already merged Theme.xaml,
    so there is one dictionary and one palette rather than two that can drift
    apart on a theme switch.
    """
    path = xaml_name
    if not os.path.isabs(path):
        path = os.path.join(HERE, xaml_name)
    element = _parse(path)
    if palette_name:
        element.Resources.MergedDictionaries.Add(load_dictionary())
        theme.apply(element, palette_name)
    return element


def set_theme(window, palette_name):
    theme.apply(window, palette_name)


def image_from_file(path):
    """From bytes through a MemoryStream, never BitmapImage.UriSource - System.Uri
    moved assemblies and throws ImportError at module load on Revit 2025 and
    later, which kills the script before any of it runs."""
    try:
        if not os.path.isfile(path):
            return None
        stream = MemoryStream(File.ReadAllBytes(path))
        image = BitmapImage()
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


# ---------------------------------------------------------------------------
# screens, DPI and Revit's own window
# ---------------------------------------------------------------------------

def dpi_scale(window):
    try:
        source = PresentationSource.FromVisual(window)
        if source is not None and source.CompositionTarget is not None:
            matrix = source.CompositionTarget.TransformToDevice
            sx = matrix.M11 or 1.0
            sy = matrix.M22 or 1.0
            return sx, sy
    except Exception:
        pass
    return 1.0, 1.0


def working_area(handle=None):
    """The working area (taskbar excluded) of the screen Revit is on, in
    physical pixels."""
    try:
        from System.Windows.Forms import Screen
        screen = None
        if handle is not None:
            try:
                screen = Screen.FromHandle(handle)
            except Exception:
                screen = None
        if screen is None:
            screen = Screen.PrimaryScreen
        area = screen.WorkingArea
        return float(area.X), float(area.Y), float(area.Width), float(area.Height)
    except Exception:
        return 0.0, 0.0, 1600.0, 900.0


def revit_bounds(handle):
    """Revit's own window rectangle in physical pixels, read through UI
    Automation.

    UIAutomationClient is a managed assembly that ships with both .NET
    Framework 4.8 and the .NET 8 desktop runtime, so this works on Revit 2024
    through 2027 with no P/Invoke - which IronPython cannot do without
    compiling C# at runtime, and runtime C# compilation is a .NET Framework
    only trick that would break on 2025 and later.
    """
    if handle is None:
        return None
    try:
        from System.Windows.Automation import AutomationElement
        element = AutomationElement.FromHandle(handle)
        if element is None:
            return None
        rect = element.Current.BoundingRectangle
        if rect.Width <= 0 or rect.Height <= 0:
            return None
        return float(rect.X), float(rect.Y), float(rect.Width), float(rect.Height)
    except Exception:
        return None


def dock_rect(window, handle, side, width_px, top_inset):
    """Where a docked window sits, in device independent units.

    Revit's own rectangle where UI Automation will give it, clamped into the
    screen's working area; the working area on its own where it will not.
    """
    scale_x, scale_y = dpi_scale(window)
    area = working_area(handle)
    bounds = revit_bounds(handle)
    if bounds is None:
        bounds = area

    left = max(bounds[0], area[0])
    top = max(bounds[1], area[1])
    right = min(bounds[0] + bounds[2], area[0] + area[2])
    bottom = min(bounds[1] + bounds[3], area[1] + area[3])
    if right <= left or bottom <= top:
        left, top = area[0], area[1]
        right, bottom = area[0] + area[2], area[1] + area[3]

    top = top + float(top_inset) * scale_y
    if bottom - top < 200 * scale_y:
        top = bottom - 200 * scale_y

    panel = float(width_px) * scale_x
    panel = min(panel, (right - left) * 0.9)
    if side == 'right':
        x = right - panel
    else:
        x = left
    return (x / scale_x, top / scale_y, panel / scale_x,
            (bottom - top) / scale_y)


# ---------------------------------------------------------------------------
# chrome
# ---------------------------------------------------------------------------

class Chrome(object):
    """Drag, resize grips, full screen and docking for one borderless window.

    A borderless AllowsTransparency window cannot be resized by WPF: there is
    nothing hit testable in its transparent frame, so the resize border never
    fires however ResizeMode is set.  The window carries eight Thumb strips of
    its own instead.
    """

    SIDES = [
        ('left',   HorizontalAlignment.Left,    VerticalAlignment.Stretch, Cursors.SizeWE),
        ('right',  HorizontalAlignment.Right,   VerticalAlignment.Stretch, Cursors.SizeWE),
        ('top',    HorizontalAlignment.Stretch, VerticalAlignment.Top,     Cursors.SizeNS),
        ('bottom', HorizontalAlignment.Stretch, VerticalAlignment.Bottom,  Cursors.SizeNS),
        ('tl',     HorizontalAlignment.Left,    VerticalAlignment.Top,     Cursors.SizeNWSE),
        ('br',     HorizontalAlignment.Right,   VerticalAlignment.Bottom,  Cursors.SizeNWSE),
        ('tr',     HorizontalAlignment.Right,   VerticalAlignment.Top,     Cursors.SizeNESW),
        ('bl',     HorizontalAlignment.Left,    VerticalAlignment.Bottom,  Cursors.SizeNESW),
    ]

    def __init__(self, window, revit_handle=None, settings=None):
        self.window = window
        self.handle = revit_handle
        self.settings = settings or {}
        self.full = False
        self.saved = None
        self.dock_side = 'float'
        self.floating = None
        self.follow = None
        self.on_state = None

    # -- owning ----------------------------------------------------------

    def own_to_revit(self):
        """Owned by Revit, and findable from the task bar.

        An unowned modeless window slips behind Revit and reads as a crash, so
        it is owned to Revit's main window handle.  Owning it is not enough on
        its own: a click into Revit can still put Revit's own child windows in
        front of it, and then there is no way back to it except moving Revit.

        So the window also carries `ShowInTaskbar="True"`.  Hovering Revit's
        task bar button shows it in the group of thumbnails, and it has its own
        entry as well, so there is always a way to bring it back.  The owner is
        re-asserted on Activated too, because Revit re-parents its main window
        on some operations and an owner set once can quietly come undone.
        """
        if self.handle is None:
            return
        self._own()
        try:
            self.window.Activated += self._reown
        except Exception:
            pass

    def _own(self):
        try:
            helper = WindowInteropHelper(self.window)
            if helper.Owner != self.handle:
                helper.Owner = self.handle
        except Exception:
            pass

    def _reown(self, sender=None, args=None):
        self._own()

    def bring_to_front(self):
        """Used when the ribbon button is pressed on an already open window."""
        try:
            if self.window.WindowState == WindowState.Minimized:
                self.window.WindowState = WindowState.Normal
        except Exception:
            pass
        try:
            self.window.Show()
            self.window.Activate()
            self.window.Focus()
        except Exception:
            pass

    # -- dragging --------------------------------------------------------

    def wire_header(self, header):
        if header is None:
            return
        header.MouseLeftButtonDown += self._header_down
        header.MouseLeftButtonUp += self._header_up

    def _header_down(self, sender, args):
        try:
            if args.ClickCount == 2:
                self.toggle_full()
                return
        except Exception:
            pass
        # dragging a docked or full screen window lets it go
        if self.full:
            self.toggle_full()
        elif self.dock_side != 'float':
            self.undock(keep_under_cursor=True)
        try:
            self.window.DragMove()
        except Exception:
            pass

    def _header_up(self, sender, args):
        if not fv_core.as_bool(self.settings, 'snap_on_drag'):
            return
        if self.full or self.dock_side != 'float':
            return
        try:
            from System.Windows.Forms import Control
            point = Control.MousePosition
        except Exception:
            return
        area = working_area(self.handle)
        if point.X <= area[0] + SNAP_EDGE:
            self.dock('left')
        elif point.X >= area[0] + area[2] - SNAP_EDGE:
            self.dock('right')
        elif point.Y <= area[1] + SNAP_EDGE:
            self.toggle_full(True)

    # -- resize grips ----------------------------------------------------

    def add_grips(self, layer):
        """layer is a Grid in the layout with NO Background, so everything
        underneath it stays clickable."""
        if layer is None:
            return
        for name, horizontal, vertical, cursor in self.SIDES:
            thumb = Thumb()
            thumb.Tag = name
            thumb.HorizontalAlignment = horizontal
            thumb.VerticalAlignment = vertical
            thumb.Cursor = cursor
            thumb.Opacity = 0.0
            if horizontal != HorizontalAlignment.Stretch:
                thumb.Width = GRIP
            if vertical != VerticalAlignment.Stretch:
                thumb.Height = GRIP
            try:
                thumb.SetResourceReference(FrameworkElement.StyleProperty, 'GripThumb')
            except Exception:
                pass
            thumb.DragDelta += self._grip_drag
            layer.Children.Add(thumb)

    def _grip_drag(self, sender, args):
        if self.full:
            return
        if self.dock_side != 'float':
            self.undock()
        window = self.window
        name = str(sender.Tag)
        dx = args.HorizontalChange
        dy = args.VerticalChange
        try:
            if name in ('left', 'tl', 'bl'):
                new_width = window.Width - dx
                if new_width >= window.MinWidth:
                    window.Left = window.Left + dx
                    window.Width = new_width
            if name in ('right', 'tr', 'br'):
                new_width = window.Width + dx
                if new_width >= window.MinWidth:
                    window.Width = new_width
            if name in ('top', 'tl', 'tr'):
                new_height = window.Height - dy
                if new_height >= window.MinHeight:
                    window.Top = window.Top + dy
                    window.Height = new_height
            if name in ('bottom', 'bl', 'br'):
                new_height = window.Height + dy
                if new_height >= window.MinHeight:
                    window.Height = new_height
        except Exception:
            pass

    # -- full screen -----------------------------------------------------

    def toggle_full(self, want=None):
        """By bounds, not WindowState.Maximized.  A borderless
        AllowsTransparency window maximised the normal way covers the taskbar
        and lands on the wrong monitor."""
        window = self.window
        drawer = DRAWERS.get(window)
        if drawer is not None and drawer.shrunk:
            # full screen on a parked window opens it instead: filling the
            # screen with a window nobody can see helps nobody
            drawer.expand()
            return
        target = (not self.full) if want is None else bool(want)
        if target == self.full:
            return
        if target:
            if self.dock_side != 'float':
                self.undock()
            self.saved = (window.Left, window.Top, window.Width, window.Height)
            scale_x, scale_y = dpi_scale(window)
            handle = None
            try:
                handle = WindowInteropHelper(window).Handle
            except Exception:
                handle = None
            area = working_area(handle or self.handle)
            window.Left = area[0] / scale_x
            window.Top = area[1] / scale_y
            window.Width = area[2] / scale_x
            window.Height = area[3] / scale_y
            self.full = True
        else:
            if self.saved:
                window.Left, window.Top, window.Width, window.Height = self.saved
            self.full = False
        self._announce()

    # -- docking ---------------------------------------------------------

    def dock(self, side):
        if side not in ('left', 'right'):
            self.undock()
            return
        window = self.window
        if self.full:
            self.toggle_full(False)
        if self.dock_side == 'float':
            self.floating = (window.Left, window.Top, window.Width, window.Height)
        self.dock_side = side
        self._place_dock()
        if fv_core.as_bool(self.settings, 'follow_revit'):
            self._start_follow()
        self._announce()

    def _place_dock(self):
        width = fv_core.as_int(self.settings, 'dock_width', 240, 1600)
        inset = 0
        try:
            inset = int(self.settings.get('dock_top_inset', '0'))
        except Exception:
            inset = 0
        rect = dock_rect(self.window, self.handle, self.dock_side, width, inset)
        try:
            self.window.Left, self.window.Top = rect[0], rect[1]
            self.window.Width, self.window.Height = rect[2], rect[3]
        except Exception:
            pass

    def undock(self, keep_under_cursor=False):
        if self.dock_side == 'float':
            return
        # a docked window remembers the width it was dragged to
        try:
            scale_x, _ = dpi_scale(self.window)
            self.settings['dock_width'] = str(int(self.window.Width * scale_x))
        except Exception:
            pass
        self.dock_side = 'float'
        self._stop_follow()
        window = self.window
        if self.floating:
            width = self.floating[2]
            height = self.floating[3]
        else:
            width = max(window.MinWidth, 1100.0)
            height = max(window.MinHeight, 700.0)
        if keep_under_cursor:
            try:
                from System.Windows.Forms import Control
                scale_x, scale_y = dpi_scale(window)
                point = Control.MousePosition
                window.Left = point.X / scale_x - width * 0.5
                window.Top = point.Y / scale_y - 16.0
            except Exception:
                pass
        elif self.floating:
            window.Left, window.Top = self.floating[0], self.floating[1]
        window.Width, window.Height = width, height
        self._announce()

    def _start_follow(self):
        """Revit moving or resizing takes the docked panel with it.  Polling on
        a timer rather than hooking a window event: there is no managed event
        for another process's window moving, and a poll cannot leak a
        subscription the way an IronPython bound method can."""
        from System.Windows.Threading import DispatcherTimer
        from System import TimeSpan
        if self.follow is not None:
            return
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromMilliseconds(400)
        timer.Tick += self._follow_tick
        timer.Start()
        self.follow = timer

    def _stop_follow(self):
        if self.follow is None:
            return
        try:
            self.follow.Stop()
        except Exception:
            pass
        self.follow = None

    def _follow_tick(self, sender, args):
        if self.dock_side == 'float':
            self._stop_follow()
            return
        try:
            self._place_dock()
        except Exception:
            pass

    def close(self):
        self._stop_follow()

    def _announce(self):
        if self.on_state:
            try:
                self.on_state(self.dock_side, self.full)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------

def prompt(owner, palette_name, title, message, ok_text='OK',
           cancel_text=None, accent='blue'):
    """A themed message or confirm.

    Any dialog standing between a user and an action needs a fallback rather
    than an "except: return False" - a silent no is indistinguishable from a
    broken button.
    """
    try:
        window = load_window('FamilyViewerPrompt.xaml', palette_name)
        find = window.FindName
        find('PromptTitle').Text = title
        find('PromptBody').Text = message
        ok = find('PromptOk')
        ok.Content = ok_text
        try:
            ok.SetResourceReference(
                FrameworkElement.StyleProperty,
                'BtnOrange' if accent == 'orange' else 'BtnGreen')
        except Exception:
            pass
        cancel = find('PromptCancel')
        if cancel_text:
            cancel.Content = cancel_text
            cancel.Visibility = Visibility.Visible
        else:
            cancel.Visibility = Visibility.Collapsed

        answer = {'value': not cancel_text}

        def say_yes(sender, args):
            answer['value'] = True
            window.DialogResult = True

        def say_no(sender, args):
            answer['value'] = False
            window.DialogResult = False

        ok.Click += say_yes
        cancel.Click += say_no
        find('PromptClose').Click += say_no
        header = find('PromptHeader')

        def drag(sender, args):
            try:
                window.DragMove()
            except Exception:
                pass

        header.MouseLeftButtonDown += drag
        try:
            find('PromptVersion').Text = 'v' + fv_core.__version__
        except Exception:
            pass
        WindowDrawer(window, header, find('PromptRoot'), find('PromptShrink'),
                     owner=owner)
        own_dialog(window, owner)
        window.ShowDialog()
        return answer['value']
    except Exception:
        fv_core.log('themed prompt failed, falling back:\n' + fv_core.format_exc())
        return _revit_prompt(title, message, bool(cancel_text))


def _revit_prompt(title, message, ask):
    try:
        from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult
        dialog = TaskDialog(title)
        dialog.MainInstruction = title
        dialog.MainContent = message
        if ask:
            dialog.CommonButtons = (TaskDialogCommonButtons.Yes |
                                    TaskDialogCommonButtons.No)
            return dialog.Show() == TaskDialogResult.Yes
        dialog.CommonButtons = TaskDialogCommonButtons.Close
        dialog.Show()
        return True
    except Exception:
        return not ask


# ===========================================================================
# Shrink to taskbar
#
# Every window the tool opens carries a shrink control beside full screen and
# close.  Pressed, the window slides to the bottom of its screen like a drawer
# closing, leaving only its header floating clear of the taskbar so Revit can
# be worked in; the control becomes a green up arrow that opens it again.
#
# The slide sets Top and Height from a DispatcherTimer rather than through
# BeginAnimation.  An animation holds its end value and outranks every later
# plain assignment, so a drawer that forgets to release one leaves a window
# that can never be moved or resized again, with nothing raised to say so.
# A timer-driven slide cannot fail that way.
#
# The parking and reopening arithmetic is plain functions so the bench can
# prove it - including a second monitor ABOVE the primary, where a negative
# work-area top is what sends a naive bar to the wrong screen.
# ===========================================================================

DRAWER_MARGIN = 6.0         # gap between the parked bar and the taskbar
DRAWER_STEPS = 14           # frames in a slide
DRAWER_FRAME_MS = 15        # ~210ms a slide

# window -> its drawer, so the chrome and any dialog it owns can find it
DRAWERS = {}


def ease_out(t):
    t = max(0.0, min(1.0, float(t)))
    return 1.0 - (1.0 - t) ** 3


def tween(start, end, t):
    return start + (end - start) * ease_out(t)


def park_rect(area, left, width, bar_height, stack=0, margin=DRAWER_MARGIN):
    """Where the bar parks: (left, top, height), in the window's own units.

    `area` is the working area of the screen the window is ON (x, y, w, h) -
    never the primary screen's, or a window on a second monitor parks on the
    wrong one.  `stack` lifts a bar one bar-height up, so a dialog parks above
    the owner it takes down with it.
    """
    x, y, w, h = [float(value) for value in area]
    top = y + h - margin - bar_height - stack * (bar_height + margin)
    usable = min(float(width), w)
    left = max(x, min(float(left), x + w - usable))
    return left, top, float(bar_height)


def reopen_rect(saved, parked, bar_left, bar_top, area, bar_height):
    """Where the window reopens: (left, top, height).

    Back where it was if the bar has not been moved.  Carried somewhere else,
    it opens UPWARD from where the bar now sits - jumping back to a place the
    user has already moved on from is worse than not having moved.  Either way
    it is kept inside the working area.
    """
    s_left, s_top, s_height = [float(value) for value in saved]
    x, y, w, h = [float(value) for value in area]
    height = min(s_height, h)
    moved = (abs(float(bar_left) - parked[0]) > 2.0 or
             abs(float(bar_top) - parked[1]) > 2.0)
    if moved:
        left = float(bar_left)
        top = float(bar_top) + float(bar_height) - height
    else:
        left, top = s_left, s_top
    if top + height > y + h:
        top = y + h - height
    if top < y:
        top = y
    return left, top, height


def window_area(window):
    """The working area of the screen this WINDOW is on, in its own units."""
    try:
        from System.Windows.Forms import Screen
        handle = WindowInteropHelper(window).Handle
        area = Screen.FromHandle(handle).WorkingArea
        scale_x, scale_y = dpi_scale(window)
        return (area.X / scale_x, area.Y / scale_y,
                area.Width / scale_x, area.Height / scale_y)
    except Exception:
        return working_area(None)


def _dispatcher_timer():
    from System import TimeSpan
    from System.Windows.Threading import DispatcherTimer
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(DRAWER_FRAME_MS)
    return timer


class WindowDrawer(object):
    """The shrink-to-taskbar behaviour for one window.

    Hand one to every window: the main window, the batch rename window, the
    settings and every prompt.  `root` is the element carrying the whole
    layout, pinned for the slide; `grips` is the resize overlay, parked with
    the window; `owner` is the owner window of a modal dialog.
    """

    def __init__(self, window, header, root, button, grips=None, owner=None,
                 timer_factory=None, area_reader=None):
        self.window = window
        self.header = header
        self.root = root
        self.button = button
        self.grips = grips
        self.owner_drawer = DRAWERS.get(owner) if owner is not None else None
        self.timer_factory = timer_factory or _dispatcher_timer
        self.area_reader = area_reader or window_area
        self.shrunk = False
        self.sliding = False
        self.busy = False
        self.took_owner = False
        self.saved = None
        self.parked = None
        self.saved_min = 0.0
        self.saved_size_to = None
        self.bar = 40.0
        self.stack = 0
        self.errors = []
        DRAWERS[window] = self
        try:
            button.Click += self.on_click
        except Exception:
            pass
        try:
            window.PreviewKeyDown += self.on_key
        except Exception:
            pass
        try:
            header.PreviewMouseLeftButtonDown += self.on_header_down
        except Exception:
            pass
        try:
            window.Closed += self.on_closed
        except Exception:
            pass

    # -- the button and the keys ------------------------------------------

    def on_click(self, sender, args):
        self.toggle()

    def toggle(self):
        if self.shrunk:
            self.expand()
        else:
            self.shrink()

    def on_key(self, sender, args):
        """Ctrl+Shift+H either way.  While parked, Escape, Enter and F11 open
        the window rather than reaching an exit prompt or filling the screen
        with a window nobody can see."""
        try:
            from System.Windows.Input import Key, Keyboard, ModifierKeys
            mods = Keyboard.Modifiers
            ctrl_shift = (mods & ModifierKeys.Control) == ModifierKeys.Control \
                and (mods & ModifierKeys.Shift) == ModifierKeys.Shift
            if ctrl_shift and args.Key == Key.H:
                args.Handled = True
                self.toggle()
                return
            if self.shrunk and args.Key in (Key.Escape, Key.Enter, Key.Return,
                                             Key.F11):
                args.Handled = True
                self.expand()
        except Exception:
            pass

    def on_header_down(self, sender, args):
        """While parked the bar owns its own clicks: a double click opens it
        rather than maximising, and a drag moves the bar - except mid-job,
        where DragMove's modal message loop is not something to start inside
        Revit's API context."""
        if not self.shrunk:
            return
        args.Handled = True
        try:
            if args.ClickCount == 2:
                self.expand()
                return
        except Exception:
            pass
        if self.busy or self.sliding:
            return
        try:
            self.window.DragMove()
        except Exception:
            pass

    # -- shrinking --------------------------------------------------------

    def _bar_height(self):
        try:
            height = float(self.header.ActualHeight)
        except Exception:
            height = 0.0
        if not height or height != height:
            height = 40.0
        return height + 2.0          # the window's own 1px border, both sides

    def shrink(self, stack=None):
        if self.shrunk or self.sliding:
            return
        window = self.window
        if stack is None:
            # a dialog parks above the owner it takes down with it
            stack = 1 if self.owner_drawer is not None else 0
        self.stack = stack
        try:
            height = float(window.ActualHeight) or float(window.Height)
        except Exception:
            height = 400.0
        self.saved = (window.Left, window.Top, height)
        self.bar = self._bar_height()
        left, top, bar = park_rect(self.area_reader(window), window.Left,
                                   window.ActualWidth, self.bar, stack)
        self.parked = (left, top)

        # MinHeight and SizeToContent both veto a Height change, and a vetoed
        # one leaves the window half shut
        # (each in its own try: one refused property must not skip the next)
        try:
            self.saved_min = window.MinHeight
            window.MinHeight = 0.0
        except Exception:
            pass
        try:
            from System.Windows import SizeToContent
            self.saved_size_to = window.SizeToContent
            window.SizeToContent = SizeToContent.Manual
        except Exception:
            pass
        # pin the body, so the grid is clipped by the shrinking window rather
        # than re-measured twenty times a second
        try:
            self.root.Height = self.root.ActualHeight
        except Exception:
            pass
        try:
            self.root.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass
        # park the grips, or they line the bar with invisible drag handles and
        # swallow the click on the arrow that brings the window back
        if self.grips is not None:
            try:
                self.grips.Visibility = Visibility.Collapsed
            except Exception:
                pass
        self.shrunk = True
        self._paint()
        try:
            window.Left = left
        except Exception:
            pass
        self._slide((window.Top, height), (top, bar), None)

        # a modal dialog takes its owner down with it, or the owner sits over
        # Revit and shrinking the dialog has shown nothing
        owner = self.owner_drawer
        if owner is not None and not owner.shrunk:
            owner.shrink(stack=0)
            self.took_owner = True

    # -- opening ----------------------------------------------------------

    def expand(self):
        if not self.shrunk or self.sliding:
            return
        window = self.window
        left, top, height = reopen_rect(
            self.saved, self.parked or (window.Left, window.Top), window.Left,
            window.Top, self.area_reader(window), self.bar)
        try:
            window.Left = left
        except Exception:
            pass
        self._slide((window.Top, window.Height), (top, height),
                    self._opened)

    def _opened(self):
        window = self.window
        try:
            window.MinHeight = self.saved_min
        except Exception:
            pass
        try:
            self.root.Height = float('nan')
        except Exception:
            pass
        try:
            self.root.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass
        try:
            if self.saved_size_to is not None:
                window.SizeToContent = self.saved_size_to
        except Exception:
            pass
        if self.grips is not None:
            try:
                self.grips.Visibility = Visibility.Visible
            except Exception:
                pass
        self.shrunk = False
        self._paint()
        if self.took_owner and self.owner_drawer is not None:
            # back without being activated over the dialog
            self.took_owner = False
            self.owner_drawer.expand()

    def on_closed(self, sender, args):
        DRAWERS.pop(self.window, None)
        if self.took_owner and self.owner_drawer is not None:
            self.took_owner = False
            self.owner_drawer.expand()

    def _paint(self):
        try:
            self.button.Tag = 'shrunk' if self.shrunk else ''
        except Exception:
            pass

    # -- the slide --------------------------------------------------------

    def _slide(self, start, end, done):
        """Top and Height from start to end over a few frames, then `done`.

        Every way out lands the window at the end: a timer that cannot be made
        or started lands it at once, and an exception inside a frame is caught
        IN the frame.  A real DispatcherTimer never calls Tick from inside
        Start(), so an exception escaping a frame would go to the dispatcher
        and leave the drawer sliding for good, unable to toggle again.
        """
        window = self.window
        self.sliding = True
        state = {'step': 0, 'landed': False}

        def land():
            if state['landed']:
                return
            state['landed'] = True
            self.sliding = False
            try:
                window.Top = end[0]
                window.Height = end[1]
            except Exception:
                self.errors.append(fv_core.format_exc())
            if done is not None:
                try:
                    done()
                except Exception:
                    self.errors.append(fv_core.format_exc())

        try:
            timer = self.timer_factory()
        except Exception:
            land()
            return

        def frame(sender, args):
            try:
                state['step'] += 1
                t = state['step'] / float(DRAWER_STEPS)
                window.Top = tween(start[0], end[0], t)
                window.Height = max(1.0, tween(start[1], end[1], t))
                if state['step'] >= DRAWER_STEPS:
                    timer.Stop()
                    land()
            except Exception:
                self.errors.append(fv_core.format_exc())
                try:
                    timer.Stop()
                except Exception:
                    pass
                land()

        try:
            timer.Tick += frame
            timer.Start()
        except Exception:
            land()


def own_dialog(dialog, owner):
    """Give a dialog its owner.  When the owner is parked, centre the dialog
    on the SCREEN: centred on a 40px bar at the bottom of the screen, most of
    it would be off the screen - and that is exactly when a dialog turns up
    unasked, as a job's summary arriving while the tool is shrunk."""
    if owner is None:
        return
    try:
        dialog.Owner = owner
    except Exception:
        return
    drawer = DRAWERS.get(owner)
    if drawer is not None and drawer.shrunk:
        try:
            from System.Windows import WindowStartupLocation
            dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen
        except Exception:
            pass
