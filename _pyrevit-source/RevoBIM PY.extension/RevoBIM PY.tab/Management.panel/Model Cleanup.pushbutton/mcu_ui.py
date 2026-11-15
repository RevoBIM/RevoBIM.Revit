# -*- coding: utf-8 -*-
"""Window plumbing shared by every Model Cleanup window.

XAML loading and theming, the borderless chrome (drag, eight resize grips,
full screen by bounds), the dark and light chip, the easter egg, the themed
prompt, and the wrapper that makes sure no button can fail silently.
"""
import io
import os
import time

import mcu_clr  # noqa: F401 - must come before any System.* import
import mcu_core as core
import mcu_theme

from System import Action, TimeSpan, Double
from System.IO import StringReader, MemoryStream, File
from System.Xml import XmlReader
from System.Windows import (Window, SystemParameters, PresentationSource, WindowState,
                            Visibility, Thickness, HorizontalAlignment, VerticalAlignment,
                            SizeToContent, WindowStartupLocation, CornerRadius, Point)
from System.Windows.Markup import XamlReader
from System.Windows.Controls import Button, Border
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Threading import DispatcherPriority, DispatcherTimer

HERE = os.path.dirname(os.path.abspath(__file__))


def read_text(path):
    with io.open(path, u"r", encoding=u"utf-8") as handle:
        return handle.read()


# ============================================================
# theme state - one per run, shared by every open window
# ============================================================

class ThemeState(object):
    """Auto follows the Revit canvas; the chip cycles Auto, Dark, Light and
    the choice is remembered."""

    def __init__(self, uiapp, settings):
        self.settings = settings
        self.mode = core.normalise_theme_mode(settings.get(u"theme_mode"))
        self.canvas_dark = None
        try:
            self.canvas_dark = mcu_theme.canvas_is_dark(uiapp)
        except Exception:
            self.canvas_dark = None
        self.windows = []

    @property
    def resolved(self):
        return core.resolve_theme(self.mode, self.canvas_dark)

    def palette(self):
        return mcu_theme.palette(self.resolved)

    def register(self, window, chip, chip_text):
        entry = (window, chip, chip_text)
        self.windows.append(entry)
        mcu_theme.apply(window, self.resolved)
        self._label(chip, chip_text)
        if chip is not None:
            chip.Click += safe_handler(window, self._on_chip)

        def closed(sender, args):
            self.windows = [item for item in self.windows if item[0] is not window]
        window.Closed += closed

    def _on_chip(self, sender, args):
        self.mode = core.next_theme_mode(self.mode)
        self.settings[u"theme_mode"] = self.mode
        core.save_global(self.settings)
        self.apply_all()

    def apply_all(self):
        for window, chip, chip_text in list(self.windows):
            try:
                mcu_theme.apply(window, self.resolved)
                self._label(chip, chip_text)
            except Exception:
                core.log(u"theme: could not repaint a window")

    def _label(self, chip, chip_text):
        label = core.theme_chip_label(self.mode, self.resolved)
        if chip_text is not None:
            chip_text.Text = label
        if chip is not None:
            if self.mode == core.THEME_AUTO:
                canvas = u"unknown" if self.canvas_dark is None else (
                    u"dark" if self.canvas_dark else u"light")
                tip = u"Following the Revit canvas ({0}). Click to fix it to Dark.".format(canvas)
            elif self.mode == core.THEME_DARK:
                tip = u"Dark. Click for Light."
            else:
                tip = u"Light. Click to follow the Revit canvas again."
            chip.ToolTip = tip


# ============================================================
# loading
# ============================================================

def load_window(file_name, theme_state=None):
    text = read_text(os.path.join(HERE, file_name))
    window = XamlReader.Load(XmlReader.Create(StringReader(text)))
    theme_text = read_text(os.path.join(HERE, u"Theme.xaml"))
    dictionary = XamlReader.Load(XmlReader.Create(StringReader(theme_text)))
    window.Resources.MergedDictionaries.Add(dictionary)
    if theme_state is not None:
        mcu_theme.apply(window, theme_state.resolved)
    return window


def finder(window):
    def find(name):
        element = window.FindName(name)
        if element is None:
            raise LookupError(u"{0} has no element named {1}".format(
                core.to_text(window.Title), name))
        return element
    return find


def load_icon(image, path=None):
    """No System.Uri - it moved assemblies in Revit 2025. Bytes instead."""
    path = path or os.path.join(HERE, u"icon.png")
    try:
        if not os.path.isfile(path):
            return False
        bitmap = BitmapImage()
        bitmap.BeginInit()
        bitmap.StreamSource = MemoryStream(File.ReadAllBytes(path))
        bitmap.CacheOption = BitmapCacheOption.OnLoad
        bitmap.EndInit()
        image.Source = bitmap
        return True
    except Exception:
        return False


def set_version(text_block):
    try:
        text_block.Text = u"v" + core.__version__
    except Exception:
        pass


# ============================================================
# the easter egg - three slow clicks on the RevoBIM logo
# ============================================================

def attach_egg(window, logo_host=None, theme_state=None):
    """The egg lives in the shared lib\\revobim\\egg package and is not
    shipped with this tool. attach_to_window is the current call; attach is
    the older form. Decorative, so it can never take the tool down."""
    try:
        from revobim.egg import egg_hook
    except Exception:
        return False

    def palette():
        if theme_state is None:
            return mcu_theme.DARK
        return theme_state.palette()

    attach_to_window = getattr(egg_hook, u"attach_to_window", None)
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

    attach = getattr(egg_hook, u"attach", None)
    if attach is None or logo_host is None:
        return False
    try:
        attach(logo_host, host_window=window, theme=palette)
        return True
    except Exception:
        return False


# ============================================================
# chrome
# ============================================================

def _dpi_scale(window):
    try:
        source = PresentationSource.FromVisual(window)
        return float(source.CompositionTarget.TransformToDevice.M11) or 1.0
    except Exception:
        return 1.0


def work_area(window):
    """The working area of the screen the window is on, in WPF units."""
    try:
        from System.Windows.Forms import Screen
        from System.Windows.Interop import WindowInteropHelper
        handle = WindowInteropHelper(window).Handle
        area = Screen.FromHandle(handle).WorkingArea
        scale = _dpi_scale(window)
        return (area.Left / scale, area.Top / scale,
                area.Width / scale, area.Height / scale)
    except Exception:
        area = SystemParameters.WorkArea
        return (area.Left, area.Top, area.Width, area.Height)


class Chrome(object):
    """Borderless window: header drag, eight resize grips, full screen by
    bounds (F11, the button, or a double click on the header)."""

    GRIPS = (u"GripN", u"GripS", u"GripW", u"GripE",
             u"GripNW", u"GripNE", u"GripSW", u"GripSE")

    def __init__(self, window, is_busy=None, drawer=None):
        self.window = window
        self.find = finder(window)
        self.is_busy = is_busy or (lambda: False)
        self.drawer = drawer
        self.full = False
        self.saved = None
        self.find(u"HeaderBar").MouseLeftButtonDown += self._on_header_down
        self.find(u"FullScreenButton").Click += safe_handler(window, self._on_full)
        self.find(u"CloseButton").Click += safe_handler(window, self._on_close)
        for name in self.GRIPS:
            self.find(name).DragDelta += self._grip_handler(name)
        window.PreviewKeyDown += self._on_key

    def _on_close(self, sender, args):
        self.window.Close()

    def parked(self):
        return self.drawer is not None and self.drawer.parked

    def _on_full(self, sender, args):
        if self.parked():
            self.drawer.expand()
            return
        self.toggle_full()

    def _on_key(self, sender, args):
        try:
            if args.Handled or self.parked():
                return
            if args.Key == Key.F11:
                self.toggle_full()
                args.Handled = True
        except Exception:
            pass

    def _on_header_down(self, sender, args):
        try:
            if args.ClickCount == 2:
                if self.parked():
                    self.drawer.expand()
                else:
                    self.toggle_full()
                return
            # DragMove is a modal message loop; never start one mid-job, when
            # Revit is inside the API call the job is making
            if self.is_busy():
                return
            if self.full and not self.parked():
                self.leave_full()
            self.window.DragMove()
        except Exception:
            pass

    def toggle_full(self):
        if self.full:
            self.leave_full()
        else:
            self.enter_full()

    def enter_full(self):
        window = self.window
        self.saved = (window.Left, window.Top, window.Width, window.Height)
        left, top, width, height = work_area(window)
        window.Left, window.Top = left, top
        window.Width, window.Height = width, height
        self.full = True

    def leave_full(self):
        if self.saved is not None:
            window = self.window
            window.Left, window.Top, window.Width, window.Height = self.saved
        self.full = False

    def _grip_handler(self, name):
        def handler(sender, args):
            try:
                self._resize(name, args.HorizontalChange, args.VerticalChange)
            except Exception:
                pass
        return handler

    def _resize(self, name, dx, dy):
        window = self.window
        self.full = False
        if u"E" in name[4:]:
            width = window.Width + dx
            if width >= window.MinWidth:
                window.Width = width
        if u"W" in name[4:]:
            width = window.Width - dx
            if width >= window.MinWidth:
                window.Left = window.Left + dx
                window.Width = width
        if u"S" in name[4:]:
            height = window.Height + dy
            if height >= window.MinHeight:
                window.Height = height
        if u"N" in name[4:]:
            height = window.Height - dy
            if height >= window.MinHeight:
                window.Top = window.Top + dy
                window.Height = height


def revit_handle(uiapp):
    """Revit's main window handle, or None."""
    try:
        handle = uiapp.MainWindowHandle
        if handle is not None and int(handle.ToInt64()) != 0:
            return handle
    except Exception:
        pass
    try:
        from System.Diagnostics import Process
        handle = Process.GetCurrentProcess().MainWindowHandle
        if int(handle.ToInt64()) != 0:
            return handle
    except Exception:
        pass
    return None


def own_to_revit(window, uiapp):
    """An owned window always sits above its owner, so a sync or a save that
    hands focus back to Revit cannot bury it - and it still goes behind other
    applications like any Revit dialog."""
    handle = revit_handle(uiapp)
    if handle is None:
        return False
    try:
        from System.Windows.Interop import WindowInteropHelper
        WindowInteropHelper(window).Owner = handle
        return True
    except Exception:
        return False


def bring_to_front(window):
    """Backstop after a long Revit call: restore, raise and focus. Topmost is
    only pulsed, never left on, so other applications are not covered."""
    try:
        if window.WindowState == WindowState.Minimized:
            window.WindowState = WindowState.Normal
    except Exception:
        pass
    try:
        window.Activate()
        window.Topmost = True
        window.Topmost = False
        window.Focus()
    except Exception:
        pass


# ============================================================
# shrink to taskbar - the drawer
# ============================================================

DRAWERS = {}


def guarded(handler, stage):
    """For handlers that must never raise a dialog - the drawer's - but must
    never fail silently either: the failure goes to the error file."""
    def wrapped(sender, args):
        try:
            return handler(sender, args)
        except Exception:
            core.write_error(stage, core.format_exception())
    return wrapped


def _dispatcher_timer(tick):
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(core.DRAWER_TICK_MS)

    def on_tick(sender, args):
        tick()
    timer.Tick += guarded(on_tick, u"shrink to taskbar (frame)")
    return timer


def _key_name(key):
    name = core.to_text(key)
    return name.split(u".")[-1]


class WindowDrawer(object):
    """The shrink button top right. Pressed, the window slides down to the
    bottom of its screen like a drawer closing, leaving only its header bar
    floating clear of the taskbar so Revit can be seen; the button turns into
    a green up arrow that slides it back. Ctrl+Shift+H works both ways.

    The slide is eased by hand on a timer - plain assignments every frame,
    never a Storyboard, so nothing is left holding the window's end value.
    The timer, clock and screen lookup are arguments so the bench can drive a
    whole slide against a stand-in window."""

    def __init__(self, window, header, root, button, grips=None, is_busy=None,
                 timer_factory=None, clock=None, area_of=None):
        self.window = window
        self.header = header
        self.root = root
        self.button = button
        self.grips = grips
        self.is_busy = is_busy or (lambda: False)
        self.timer_factory = timer_factory or _dispatcher_timer
        self.clock = clock or time.time
        self.area_of = area_of or work_area
        self.owner = None
        self.took_owner_down = False
        self.parked = False
        self.sliding = False
        self.restore = None
        self.parked_at = None
        self.bar = 0.0
        self.root_height = None
        self.saved_min = 0.0
        self.saved_size_to = None
        self.saved_corner = None
        self.hidden = []
        self.timer = None
        self.errors = []
        self._start = self._end = self._done = None
        self._t0 = 0.0
        button.Click += guarded(self._on_click, u"shrink to taskbar")
        window.PreviewKeyDown += self._on_key
        window.Closed += self._on_closed
        DRAWERS[id(window)] = self
        self._dress()

    # ------------------------------------------------------- wiring
    def _on_click(self, sender, args):
        try:
            self.toggle()
        except Exception:
            core.write_error(u"shrink to taskbar", core.format_exception())

    def _on_key(self, sender, args):
        try:
            mods = Keyboard.Modifiers
            ctrl = (mods & ModifierKeys.Control) == ModifierKeys.Control
            shift = (mods & ModifierKeys.Shift) == ModifierKeys.Shift
            action = core.drawer_key_action(_key_name(args.Key), ctrl, shift,
                                            self.parked, self.sliding)
            if action is None:
                return
            args.Handled = True
            if action == u"toggle":
                self.toggle()
            elif action == u"open":
                self.expand()
        except Exception:
            core.log(u"drawer key: " + core.format_exception())

    def _on_closed(self, sender, args):
        DRAWERS.pop(id(self.window), None)
        try:
            if self.timer is not None:
                self.timer.Stop()
        except Exception:
            pass
        if self.took_owner_down and self.owner is not None and self.owner.parked:
            self.owner.expand(instant=True, activate=False)

    def link_owner(self, owner_window):
        self.owner = DRAWERS.get(id(owner_window))

    def toggle(self):
        if self.parked:
            return self.expand()
        return self.shrink()

    def _dress(self):
        try:
            if self.parked:
                self.button.Tag = u"shrunk"
                self.button.ToolTip = u"Open the window again (Ctrl+Shift+H)"
            else:
                self.button.Tag = None
                self.button.ToolTip = u"Shrink to a bar so Revit can be seen (Ctrl+Shift+H)"
        except Exception:
            pass

    # ------------------------------------------------------- geometry
    def _bar_height(self):
        try:
            offset = self.header.TranslatePoint(Point(0, 0), self.window).Y
        except Exception:
            offset = 1.0
        offset = max(0.0, min(4.0, float(offset)))
        return float(self.header.ActualHeight) + 2.0 * offset

    def _height(self):
        height = self.window.Height
        try:
            if Double.IsNaN(height):
                height = self.window.ActualHeight
        except Exception:
            pass
        return float(height)

    def _stack(self):
        return len([d for d in DRAWERS.values() if d is not self and d.parked])

    def _release(self):
        for prop in (Window.TopProperty, Window.HeightProperty, Window.LeftProperty):
            try:
                self.window.BeginAnimation(prop, None)
            except Exception:
                pass

    def _apply(self, frame):
        left, top, height = frame
        window = self.window
        window.Left = left
        window.Top = top
        window.Height = max(1.0, height)

    # ------------------------------------------------------- the slides
    def shrink(self, instant=False):
        if self.parked or self.sliding:
            return False
        window = self.window
        if self.owner is not None and not self.owner.parked:
            self.owner.shrink(instant=True)
            self.took_owner_down = True
        self._release()
        height = self._height()
        self.restore = (float(window.Left), float(window.Top), float(window.Width), height)
        self.saved_min = window.MinHeight
        self.saved_size_to = window.SizeToContent
        self.root_height = float(self.root.ActualHeight)
        self.bar = self._bar_height()
        area = self.area_of(window)
        top = core.parked_top(area, self.bar, self._stack())
        left = core.clamp_left(area, float(window.Left), float(window.Width))
        window.SizeToContent = SizeToContent.Manual
        window.MinHeight = 0
        # pinned, so the grid is clipped by the shrinking window rather than
        # re-measured every frame
        self.root.Height = self.root_height
        self.root.VerticalAlignment = VerticalAlignment.Top
        if self.grips is not None:
            self.grips.Visibility = Visibility.Collapsed
        self.parked_at = (left, top)
        self.parked = True
        self._dress()
        self._slide((float(window.Left), float(window.Top), height),
                    (left, top, self.bar), self._landed_parked, instant)
        return True

    def _landed_parked(self):
        self.hidden = []
        try:
            for child in list(self.root.Children):
                if child is self.header:
                    continue
                self.hidden.append((child, child.Visibility))
                child.Visibility = Visibility.Collapsed
        except Exception:
            pass
        self.root.Height = Double.NaN
        self.root.VerticalAlignment = VerticalAlignment.Stretch
        self.window.Height = self.bar
        try:
            self.saved_corner = self.header.CornerRadius
            self.header.CornerRadius = CornerRadius(5)
        except Exception:
            self.saved_corner = None

    def expand(self, instant=False, activate=True):
        if not self.parked or self.sliding:
            return False
        window = self.window
        # only an owner this drawer took down - one the user parked stays put
        if self.took_owner_down and self.owner is not None and self.owner.parked:
            self.owner.expand(instant=True, activate=False)
        self.took_owner_down = False
        self._release()
        now_at = (float(window.Left), float(window.Top))
        target = core.reopen_bounds(self.restore, self.parked_at, now_at, self.bar,
                                    self.area_of(window))
        for child, visibility in self.hidden:
            # only what is still as the drawer left it: something shown while
            # parked (the progress bar, as a job starts) keeps its new state
            try:
                if child.Visibility == Visibility.Collapsed:
                    child.Visibility = visibility
            except Exception:
                pass
        self.hidden = []
        if self.saved_corner is not None:
            try:
                self.header.CornerRadius = self.saved_corner
            except Exception:
                pass
        if self.root_height:
            self.root.Height = self.root_height
            self.root.VerticalAlignment = VerticalAlignment.Top
        window.Width = target[2]
        self._slide((now_at[0], now_at[1], self._height()),
                    (target[0], target[1], target[3]), self._landed_open, instant)
        if activate:
            try:
                window.Activate()
            except Exception:
                pass
        return True

    def _landed_open(self):
        self.root.Height = Double.NaN
        self.root.VerticalAlignment = VerticalAlignment.Stretch
        window = self.window
        try:
            window.MinHeight = self.saved_min
        except Exception:
            pass
        if self.saved_size_to is not None:
            try:
                window.SizeToContent = self.saved_size_to
            except Exception:
                pass
        if self.grips is not None:
            self.grips.Visibility = Visibility.Visible
        self.parked = False
        self._dress()

    def _slide(self, start, end, done, instant):
        self.sliding = True
        if instant:
            self._land(end, done)
            return
        self._start, self._end, self._done = start, end, done
        self._t0 = self.clock()
        try:
            self.timer = self.timer_factory(self._tick)
            self.timer.Start()
        except Exception:
            self.errors.append(core.format_exception())
            self._land(end, done)

    def _tick(self):
        try:
            progress = (self.clock() - self._t0) / core.DRAWER_SECONDS
            if progress >= 1.0:
                self.timer.Stop()
                self._land(self._end, self._done)
                return
            self._apply(tuple(core.tween(a, b, progress)
                              for a, b in zip(self._start, self._end)))
        except Exception:
            # a frame that throws lands the window at the end state, so the
            # drawer can never be left half way with sliding stuck on
            self.errors.append(core.format_exception())
            try:
                self.timer.Stop()
            except Exception:
                pass
            self._land(self._end, self._done)

    def _land(self, end, done):
        try:
            self._release()
        except Exception:
            pass
        try:
            self._apply(end)
        except Exception:
            self.errors.append(core.format_exception())
        try:
            done()
        except Exception:
            self.errors.append(core.format_exception())
        self.sliding = False


def drawer_for(window):
    return DRAWERS.get(id(window))


def set_owner(dialog, owner):
    """Every dialog gets its owner here: linked to the owner's drawer, and
    centred on the screen rather than on a parked 40px bar."""
    if owner is None:
        return
    try:
        dialog.Owner = owner
    except Exception:
        return
    owner_drawer = drawer_for(owner)
    if owner_drawer is not None and owner_drawer.parked:
        dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen
    own = drawer_for(dialog)
    if own is not None:
        own.link_owner(owner)


def attach_drawer(window, find, is_busy=None, grips_name=u"GripLayer"):
    grips = None
    try:
        grips = find(grips_name)
    except Exception:
        grips = None
    return WindowDrawer(window, find(u"HeaderBar"), find(u"RootGrid"),
                        find(u"ShrinkButton"), grips, is_busy)


# ============================================================
# Revit's own window while a job runs
# ============================================================

def set_revit_enabled(handle, enabled):
    """A job pumps the dispatcher to move the progress bar, and that pumps
    Revit's window too. Revit is switched off for the length of a job so a
    click on the ribbon cannot start a command in the middle of it, and on
    again the moment the job ends - every path."""
    if handle is None:
        return False
    try:
        import ctypes
        ctypes.windll.user32.EnableWindow(ctypes.c_void_p(int(handle.ToInt64())),
                                          bool(enabled))
        return True
    except Exception:
        return False


def standard_window(file_name, theme_state, is_busy=None):
    """Load, theme, chrome, version, icon, chip and egg in one go."""
    window = load_window(file_name, theme_state)
    find = finder(window)
    # the drawer goes first: its key handler has to see a key before the
    # window's own (Escape on a parked bar opens it, never closes it)
    drawer = attach_drawer(window, find, is_busy)
    chrome = Chrome(window, is_busy, drawer)
    set_version(find(u"VersionText"))
    load_icon(find(u"HeaderIcon"))
    theme_state.register(window, find(u"ThemeChip"), find(u"ThemeChipText"))
    attach_egg(window, find(u"LogoText"), theme_state)
    return window, find, chrome, drawer


# ============================================================
# busy, progress and the dispatcher
# ============================================================

def _noop():
    return None


def pump(window):
    """Let the window repaint. Never call this inside an open transaction."""
    try:
        window.Dispatcher.Invoke(Action(_noop), DispatcherPriority.Background)
    except Exception:
        pass


class ProgressBar(object):
    """The thick bar along the bottom: percent in the bar, the stage on the
    left, time left and time elapsed on the right.

    Revit runs on the same thread as this window, so the bar can only move
    between API calls. Callers report often - every chunk, every replayed
    element, every purge pass - and this class decides when a repaint is
    worth a dispatcher pump."""

    STATE_BRUSH = {
        u"run": u"BlueBrush",
        u"ok": u"GreenBrush",
        u"warn": u"OrangeBrush",
        u"fail": u"RedBrush",
    }

    def __init__(self, window, find):
        self.window = window
        self.find = find
        self.clock = core.ProgressClock()
        self.stage = u""
        self.last_paint = None
        self.last_percent = None
        self.running = False
        try:
            find(u"ProgressTrack").SizeChanged += self._on_resize
        except Exception:
            pass

    def _on_resize(self, sender, args):
        try:
            self._paint_fill()
        except Exception:
            pass

    def begin(self, stage):
        self.clock.start()
        self.stage = core.to_text(stage)
        self.running = True
        self.find(u"ProgressPanel").Visibility = Visibility.Visible
        self._colour(u"run")
        self.last_paint = None
        self.paint(force=True)

    def update(self, fraction, stage=None):
        if not self.running:
            self.begin(stage or self.stage)
        changed = False
        if stage is not None and core.to_text(stage) != self.stage:
            self.stage = core.to_text(stage)
            changed = True
        self.clock.update(fraction)
        now = self.clock.now()
        percent = self.clock.percent()
        if changed or core.should_repaint(self.last_paint, now, self.last_percent, percent):
            self.paint()

    def finish(self, message, state=u"ok"):
        if state == u"fail":
            self.clock.finished_at = self.clock.now()
        else:
            self.clock.finish()
        self.running = False
        self.stage = core.to_text(message)
        self._colour(state)
        self.paint(force=True)

    def hide(self):
        self.running = False
        self.find(u"ProgressPanel").Visibility = Visibility.Collapsed

    def _colour(self, state):
        key = self.STATE_BRUSH.get(state, u"BlueBrush")
        self.find(u"ProgressFill").SetResourceReference(Border.BackgroundProperty, key)

    def _paint_fill(self):
        track = self.find(u"ProgressTrack")
        fill = self.find(u"ProgressFill")
        fraction = self.clock.fraction
        width = track.ActualWidth * fraction
        if fraction > 0:
            width = max(width, track.ActualHeight)   # a round end needs room
        fill.Width = min(track.ActualWidth, width)

    def paint(self, force=False):
        try:
            self._paint_fill()
            self.find(u"ProgressPercent").Text = u"{0}%".format(self.clock.percent())
            self.find(u"ProgressStage").Text = self.stage
            self.find(u"ProgressEta").Text = core.progress_line(self.clock)
        except Exception:
            core.log(u"progress paint: " + core.format_exception())
        self.last_paint = self.clock.now()
        self.last_percent = self.clock.percent()
        pump(self.window)


# ============================================================
# prompts
# ============================================================

def _fallback_prompt(title, message, buttons):
    """Revit's own dialog, used only if the themed one cannot open. Every
    button except the first becomes a command link, so a three-way choice
    stays three-way; closing the dialog is the first button."""
    try:
        from Autodesk.Revit.UI import (TaskDialog, TaskDialogCommandLinkId,
                                       TaskDialogResult)
        dialog = TaskDialog(u"RevoBIM " + core.to_text(title))
        dialog.MainContent = core.to_text(message)
        if len(buttons) <= 1:
            dialog.Show()
            return buttons[0][1] if buttons else None
        choices = buttons[1:5]
        for index, (label, _, _) in enumerate(choices):
            link = getattr(TaskDialogCommandLinkId, u"CommandLink{0}".format(index + 1))
            dialog.AddCommandLink(link, core.to_text(label))
        answer = dialog.Show()
        for index, (_, value, _) in enumerate(choices):
            if answer == getattr(TaskDialogResult, u"CommandLink{0}".format(index + 1)):
                return value
        return buttons[0][1]
    except Exception:
        return buttons[0][1] if buttons else None


def prompt(owner, title, message, buttons=None, theme_state=None,
           input_text=None, input_hint=u""):
    """buttons: [(label, value, style_key)] left to right; the last is the
    default. Returns the value, or (value, text) when input_text is given.
    Falls back to Revit's own dialog if the themed one cannot open - a
    confirm step that fails must never read as a silent no."""
    buttons = buttons or [(u"OK", True, u"GreenButton")]
    try:
        window = load_window(u"McuPrompt.xaml", theme_state)
        find = finder(window)
        set_version(find(u"VersionText"))
        load_icon(find(u"HeaderIcon"))
        find(u"PromptTitle").Text = core.to_text(title)
        find(u"MessageText").Text = core.to_text(message)
        box = find(u"InputBox")
        if input_text is not None:
            box.Visibility = Visibility.Visible
            box.Text = core.to_text(input_text)
            box.Tag = input_hint
        drawer = attach_drawer(window, find)
        set_owner(window, owner)
        result = {u"value": buttons[0][1]}
        panel = find(u"ButtonPanel")
        for index, (label, value, style_key) in enumerate(buttons):
            button = Button()
            button.Content = label
            button.Margin = Thickness(8, 0, 0, 0)
            try:
                button.Style = window.FindResource(style_key or u"BaseButton")
            except Exception:
                pass
            button.Click += _prompt_click(window, result, value)
            if index == len(buttons) - 1:
                button.IsDefault = True
            if index == 0 and len(buttons) > 1:
                button.IsCancel = True
            panel.Children.Add(button)
        panel.HorizontalAlignment = HorizontalAlignment.Right

        def header_down(sender, args):
            try:
                if args.ClickCount == 2 and drawer.parked:
                    drawer.expand()
                    return
                window.DragMove()
            except Exception:
                pass
        find(u"HeaderBar").MouseLeftButtonDown += header_down
        if input_text is not None:
            box.Focus()
            box.SelectAll()
        window.ShowDialog()
        if input_text is not None:
            return result[u"value"], core.to_text(box.Text)
        return result[u"value"]
    except Exception:
        core.log(u"prompt fell back to TaskDialog: " + core.format_exception())
        value = _fallback_prompt(title, message, buttons)
        if input_text is not None:
            return value, core.to_text(input_text)
        return value


def _prompt_click(window, result, value):
    def handler(sender, args):
        result[u"value"] = value
        try:
            window.Close()
        except Exception:
            pass
    return handler


def show_error(owner, stage, text, theme_state=None):
    core.write_error(stage, text)
    message = u"{0} failed.\n\n{1}\n\nThe full text is in {2}".format(
        stage, core.to_text(text)[-1500:], core.error_path())
    prompt(owner, u"Something went wrong", message,
           [(u"OK", True, u"BaseButton")], theme_state)


# ============================================================
# no silent handlers
# ============================================================

def safe_handler(window, handler, theme_state=None, stage=None):
    """Every button goes through this: an exception is logged, shown, and
    never swallowed."""
    label = stage or getattr(handler, u"__name__", u"a button")

    def wrapped(sender, args):
        try:
            return handler(sender, args)
        except Exception:
            text = core.format_exception()
            try:
                show_error(window, label, text, theme_state)
            except Exception:
                core.write_error(label, text)
    return wrapped
