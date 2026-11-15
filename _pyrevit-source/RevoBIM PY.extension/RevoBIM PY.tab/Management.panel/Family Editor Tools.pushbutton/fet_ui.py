# =========================================================================
# Family Editor Tools - window plumbing
#
# XAML loading, theme merging, borderless chrome, resize grips, full
# screen, the themed prompt, and the easter egg hook.
# =========================================================================

import fet_clr  # noqa: F401  - assemblies first, always

import os
import traceback

from System import Double
from System.IO import File, FileMode, FileStream, MemoryStream
from System.Windows import (Application, GridLength, HorizontalAlignment,
                            Point, ResizeMode, SizeToContent, Thickness,
                            VerticalAlignment, Visibility, Window,
                            WindowStartupLocation, WindowState, WindowStyle)
from System.Windows.Controls import Grid, TextBlock
from System.Windows.Input import Cursors
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage
from System.Windows.Threading import DispatcherPriority

import fet_core
import theme

HERE = os.path.dirname(os.path.abspath(__file__))

# The easter egg's three slow clicks: a click counts as "slow" when it
# lands at least this long after the one before it, and the run resets
# when the gap grows past the window.
EGG_MIN_GAP_MS = 400
EGG_MAX_GAP_MS = 2600


def xaml_path(name):
    return os.path.join(HERE, name)


def load_xaml(name):
    u"""Parse a layout file.  A layout may only use DynamicResource, because
    Theme.xaml is merged in AFTER this call."""
    stream = FileStream(xaml_path(name), FileMode.Open)
    try:
        return XamlReader.Load(stream)
    finally:
        stream.Close()


def load_theme_dictionary():
    stream = FileStream(xaml_path(u"Theme.xaml"), FileMode.Open)
    try:
        return XamlReader.Load(stream)
    finally:
        stream.Close()


def load_window(name, palette_name):
    window = load_xaml(name)
    try:
        window.Resources.MergedDictionaries.Add(load_theme_dictionary())
    except Exception:
        pass
    theme.apply(window, palette_name)
    return window


def load_icon(path):
    u"""No System.Uri anywhere - the assembly it lives in moved in Revit
    2025 and 'from System import Uri' throws at module load."""
    try:
        if not os.path.isfile(path):
            return None
        image = BitmapImage()
        image.BeginInit()
        image.StreamSource = MemoryStream(File.ReadAllBytes(path))
        image.CacheOption = BitmapCacheOption.OnLoad
        image.EndInit()
        try:
            image.Freeze()
        except Exception:
            pass
        return image
    except Exception:
        return None


def guarded(status_setter=None):
    u"""Every WPF handler is wrapped.  A silent except: pass around
    something the user pressed is a dead button with nothing to find."""
    def wrap(func):
        def inner(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception:
                detail = traceback.format_exc()
                fet_core.log(u"handler {0} failed\n{1}".format(
                    getattr(func, u"__name__", u"?"), detail))
                try:
                    target = args[0] if args else None
                    if status_setter and target is not None:
                        getattr(target, status_setter)(
                            u"That did not work - see {0}".format(fet_core.log_path()),
                            u"red")
                except Exception:
                    pass
                return None
        try:
            inner.__name__ = func.__name__
        except Exception:
            pass
        return inner
    return wrap


ui_safe = guarded(u"set_status")


# =========================================================================
# Borderless chrome
# =========================================================================

class Chrome(object):
    u"""Drag, resize grips and full screen for a WindowStyle=None window.

    A borderless AllowsTransparency window cannot be resized by WPF - there
    is nothing hit testable in its transparent frame - so it carries eight
    Thumb strips of its own.
    """

    GRIP = 5.0

    def __init__(self, window, header=None, grip_host=None,
                 min_width=880.0, min_height=560.0):
        self.window = window
        self.header = header
        self.grip_host = grip_host
        self.min_width = min_width
        self.min_height = min_height
        self.saved_bounds = None
        self.full = False
        if header is not None:
            header.MouseLeftButtonDown += self._header_down
        if grip_host is not None:
            self._build_grips(grip_host)

    # ----- dragging -----------------------------------------------------
    def _header_down(self, sender, args):
        try:
            if args.ClickCount == 2:
                self.toggle_full()
                return
            if self.full:
                self.leave_full()
            self.window.DragMove()
        except Exception:
            pass

    # ----- resize grips -------------------------------------------------
    def _build_grips(self, host):
        from System.Windows.Controls.Primitives import Thumb
        spec = (
            (u"n", HorizontalAlignment.Stretch, VerticalAlignment.Top, Cursors.SizeNS),
            (u"s", HorizontalAlignment.Stretch, VerticalAlignment.Bottom, Cursors.SizeNS),
            (u"w", HorizontalAlignment.Left, VerticalAlignment.Stretch, Cursors.SizeWE),
            (u"e", HorizontalAlignment.Right, VerticalAlignment.Stretch, Cursors.SizeWE),
            (u"nw", HorizontalAlignment.Left, VerticalAlignment.Top, Cursors.SizeNWSE),
            (u"se", HorizontalAlignment.Right, VerticalAlignment.Bottom, Cursors.SizeNWSE),
            (u"ne", HorizontalAlignment.Right, VerticalAlignment.Top, Cursors.SizeNESW),
            (u"sw", HorizontalAlignment.Left, VerticalAlignment.Bottom, Cursors.SizeNESW),
        )
        style = None
        try:
            style = self.window.TryFindResource(u"GripThumb")
        except Exception:
            style = None
        for edge, halign, valign, cursor in spec:
            thumb = Thumb()
            thumb.HorizontalAlignment = halign
            thumb.VerticalAlignment = valign
            if u"n" in edge or u"s" in edge:
                thumb.Height = self.GRIP
            else:
                thumb.Height = Double.NaN
            if u"e" in edge or u"w" in edge:
                thumb.Width = self.GRIP
            else:
                thumb.Width = Double.NaN
            if len(edge) == 2:
                thumb.Width = self.GRIP * 2.0
                thumb.Height = self.GRIP * 2.0
            thumb.Cursor = cursor
            if style is not None:
                thumb.Style = style
            # The loop variable has to be frozen into a default argument,
            # or every thumb resizes whichever edge came last.
            def handler(sender, args, which=edge):
                self._drag(which, args)
            thumb.DragDelta += handler
            host.Children.Add(thumb)

    def _drag(self, edge, args):
        try:
            if self.full:
                return
            window = self.window
            if u"e" in edge:
                width = window.Width + args.HorizontalChange
                if width >= self.min_width:
                    window.Width = width
            if u"w" in edge:
                width = window.Width - args.HorizontalChange
                if width >= self.min_width:
                    window.Width = width
                    window.Left = window.Left + args.HorizontalChange
            if u"s" in edge:
                height = window.Height + args.VerticalChange
                if height >= self.min_height:
                    window.Height = height
            if u"n" in edge:
                height = window.Height - args.VerticalChange
                if height >= self.min_height:
                    window.Height = height
                    window.Top = window.Top + args.VerticalChange
        except Exception:
            pass

    # ----- full screen --------------------------------------------------
    def toggle_full(self):
        if self.full:
            self.leave_full()
        else:
            self.enter_full()

    def enter_full(self):
        u"""By bounds, not WindowState.Maximized.  Maximising a borderless
        AllowsTransparency window covers the task bar and lands on the
        wrong monitor.  SystemParameters.WorkArea is the PRIMARY monitor,
        not the one the window is on, so the screen is found from the
        window handle instead."""
        try:
            window = self.window
            self.saved_bounds = (window.Left, window.Top,
                                 window.Width, window.Height)
            area = self._working_area()
            if area is None:
                return
            left, top, width, height = area
            window.Left = left
            window.Top = top
            window.Width = width
            window.Height = height
            self.full = True
        except Exception:
            pass

    def leave_full(self):
        try:
            if self.saved_bounds:
                left, top, width, height = self.saved_bounds
                self.window.Left = left
                self.window.Top = top
                self.window.Width = width
                self.window.Height = height
            self.full = False
        except Exception:
            pass

    def _working_area(self):
        try:
            from System.Windows.Forms import Screen
            handle = WindowInteropHelper(self.window).Handle
            screen = Screen.FromHandle(handle)
            bounds = screen.WorkingArea
            scale_x, scale_y = self._dpi_scale()
            return (bounds.Left / scale_x, bounds.Top / scale_y,
                    bounds.Width / scale_x, bounds.Height / scale_y)
        except Exception:
            pass
        try:
            from System.Windows import SystemParameters
            return (SystemParameters.WorkArea.Left,
                    SystemParameters.WorkArea.Top,
                    SystemParameters.WorkArea.Width,
                    SystemParameters.WorkArea.Height)
        except Exception:
            return None

    def _dpi_scale(self):
        try:
            from System.Windows import PresentationSource
            source = PresentationSource.FromVisual(self.window)
            matrix = source.CompositionTarget.TransformToDevice
            return (matrix.M11 or 1.0, matrix.M22 or 1.0)
        except Exception:
            return (1.0, 1.0)


def own_to_revit(window, uiapp):
    u"""An unowned modeless window slips behind Revit and reads as a crash."""
    try:
        handle = uiapp.MainWindowHandle
    except Exception:
        try:
            from System.Diagnostics import Process
            handle = Process.GetCurrentProcess().MainWindowHandle
        except Exception:
            return False
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = handle
        return True
    except Exception:
        return False


# =========================================================================
# The easter egg
#
# Three slow clicks of the RevoBIM logo.  The game itself lives in the
# extension's shared lib\revobim\egg package and is never shipped with an
# individual tool, so every route is tried and a failure is silent.
# =========================================================================

class EggClicks(object):
    def __init__(self, element, tool_name):
        self.element = element
        self.tool_name = tool_name
        self.count = 0
        self.last = None

    def click(self):
        from System import DateTime
        now = DateTime.Now
        if self.last is None:
            gap = None
        else:
            gap = (now - self.last).TotalMilliseconds
        self.last = now
        if gap is None:
            self.count = 1
        elif gap < EGG_MIN_GAP_MS:
            # Too fast to be deliberate - a double click on the header.
            self.count = 1
        elif gap > EGG_MAX_GAP_MS:
            self.count = 1
        else:
            self.count += 1
        if self.count >= 3:
            self.count = 0
            self.last = None
            return True
        return False


def attach_egg(element, tool_name=fet_core.TOOL_NAME):
    u"""Hand the logo to the shared egg hook where it exists; otherwise
    count the three slow clicks here and launch whatever the shared package
    offers.  Either way a missing egg is silent."""
    if element is None:
        return False
    try:
        from revobim.egg import egg_hook
        egg_hook.attach(element, tool_name)
        return True
    except Exception:
        pass

    counter = EggClicks(element, tool_name)

    def on_click(sender, args):
        try:
            if counter.click():
                _launch_egg(tool_name)
        except Exception:
            pass

    try:
        element.MouseLeftButtonUp += on_click
        element.Tag = counter
        return True
    except Exception:
        return False


def _launch_egg(tool_name):
    for module_name, function_name in ((u"revobim.egg.game", u"play"),
                                       (u"revobim.egg", u"play"),
                                       (u"revobim.egg.egg_hook", u"launch")):
        try:
            module = __import__(module_name, globals(), locals(), [function_name])
            getattr(module, function_name)(tool_name)
            return True
        except Exception:
            continue
    return False


# =========================================================================
# The themed prompt
# =========================================================================

class Prompt(object):
    def __init__(self, palette_name, owner=None):
        self.palette_name = palette_name
        self.owner = owner

    def _show(self, title, message, buttons):
        window = load_window(u"FetPrompt.xaml", self.palette_name)
        find = window.FindName
        find(u"TitleText").Text = title
        find(u"MessageText").Text = message
        header = find(u"HeaderBar")
        Chrome(window, header, None, 360.0, 180.0)
        state = {u"answer": False}

        def ok(sender, args):
            state[u"answer"] = True
            window.DialogResult = True
            window.Close()

        def cancel(sender, args):
            state[u"answer"] = False
            try:
                window.DialogResult = False
            except Exception:
                pass
            window.Close()

        yes = find(u"YesButton")
        no = find(u"NoButton")
        yes.Click += ok
        no.Click += cancel
        find(u"CloseButton").Click += cancel
        if buttons == u"ok":
            yes.Content = u"OK"
            no.Visibility = Visibility.Collapsed
        try:
            if self.owner is not None:
                window.Owner = self.owner
        except Exception:
            pass
        try:
            window.ShowDialog()
        except Exception:
            return False
        return state[u"answer"]

    def say(self, title, message):
        return self._show(title, message, u"ok")

    def ask(self, title, message):
        return self._show(title, message, u"yesno")


def pump(window):
    u"""Let the dispatcher breathe.  NEVER call this between a
    Transaction.Start and its Commit - a message loop running inside an
    open transaction can leave the write with nothing committed."""
    try:
        frame_action = getattr(window.Dispatcher, u"Invoke", None)
        if frame_action is None:
            return
        window.Dispatcher.Invoke(DispatcherPriority.Background,
                                 _no_op_delegate())
    except Exception:
        pass


def _no_op_delegate():
    from System import Action

    def nothing():
        return None
    return Action(nothing)
