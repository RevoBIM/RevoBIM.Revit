# -*- coding: utf-8 -*-
"""XAML loading, theming, window chrome, the easter egg and the themed
message window. Everything decorative is wrapped so it can never take the
tool down."""
import msm_clr  # noqa: F401  - assemblies first

import io
import os
import time
import traceback

from System import Action, TimeSpan
from System.IO import StringReader, MemoryStream, File, FileStream, FileMode, StreamWriter
from System.IO.Compression import ZipArchive, ZipArchiveMode, CompressionLevel
from System.Text import UTF8Encoding
from System.Diagnostics import Process
from Microsoft.Win32 import SaveFileDialog
from System.Xml import XmlReader
from System.Windows import (WindowState, SystemParameters, PresentationSource,
                            Visibility, Window, Point, SizeToContent, VerticalAlignment)
from System.Windows.Markup import XamlReader
from System.Windows.Input import Key, MouseButtonState, Keyboard, ModifierKeys, Mouse
from System.Windows.Threading import DispatcherTimer
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

import msm_core as core
import msm_theme as theme

HERE = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# logging
# ============================================================

def log_path():
    return os.path.join(core.settings_dir(), core.DEBUG_NAME)


def log(text, enabled=True):
    if not enabled:
        return
    try:
        folder = core.settings_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        stamp = time.strftime(u"%Y-%m-%d %H:%M:%S")
        with io.open(log_path(), u"a", encoding=u"utf-8") as handle:
            handle.write(u"{0}  {1}\n".format(stamp, text))
    except Exception:
        pass


def ui_safe(handler, where=u"", on_error=None):
    """Wrap a WPF handler. A closure that throws inside WPF is swallowed with
    no trace, which reads as a dead button - so report it instead."""
    def wrapped(sender, args):
        try:
            return handler(sender, args)
        except Exception:
            text = traceback.format_exc()
            log(u"handler {0} failed:\n{1}".format(where, text))
            if on_error is not None:
                try:
                    on_error(u"{0} failed - see {1}".format(where or u"That", log_path()))
                except Exception:
                    pass
    return wrapped


# ============================================================
# XAML
# ============================================================

def read_text(path):
    with io.open(path, u"r", encoding=u"utf-8") as handle:
        return handle.read()


def load_window(file_name, mode):
    text = read_text(os.path.join(HERE, file_name))
    window = XamlReader.Load(XmlReader.Create(StringReader(text)))
    theme_text = read_text(os.path.join(HERE, u"Theme.xaml"))
    dictionary = XamlReader.Load(XmlReader.Create(StringReader(theme_text)))
    window.Resources.MergedDictionaries.Add(dictionary)
    theme.apply(window, mode)
    return window


def load_icon(image, path=None):
    """No System.Uri - it moved assembly in Revit 2025 and throws at import.
    Images come from bytes."""
    path = path or os.path.join(HERE, u"icon.png")
    try:
        if image is None or not os.path.isfile(path):
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


def set_owner(window, uiapp):
    """Own the window to Revit's main window, so a modeless window floats
    above Revit instead of slipping behind it and reading as a crash."""
    try:
        handle = uiapp.MainWindowHandle
        WindowInteropHelper(window).Owner = handle
        return True
    except Exception:
        pass
    try:
        WindowInteropHelper(window).Owner = Process.GetCurrentProcess().MainWindowHandle
        return True
    except Exception:
        return False


# ============================================================
# easter egg - three slow clicks on the RevoBIM logo
# ============================================================

CLICK_GAP_MIN_MS = 250
CLICK_GAP_MAX_MS = 2000


class SlowClicks(object):
    """Local fallback for an older egg package with no attach call: three
    clicks, each gap between 250ms and 2s. WPF ClickCount only reports 1 or 2,
    so the gaps are measured from the event Timestamp, and a repeated
    Timestamp (the same click seen twice) is ignored."""

    def __init__(self, needed=3):
        self.needed = needed
        self.stamps = []

    def click(self, stamp_ms):
        if self.stamps and stamp_ms == self.stamps[-1]:
            return False
        if self.stamps:
            gap = stamp_ms - self.stamps[-1]
            if gap < CLICK_GAP_MIN_MS or gap > CLICK_GAP_MAX_MS:
                self.stamps = []
        self.stamps.append(stamp_ms)
        if len(self.stamps) >= self.needed:
            self.stamps = []
            return True
        return False


def attach_egg(window, logo_host, get_palette):
    """The egg lives in the extension's shared lib\\revobim\\egg package and is
    not shipped with this tool. attach_to_window is the current call and finds
    the logo itself; attach is the older form; a local click counter calling
    launch is the last resort."""
    try:
        from revobim.egg import egg_hook
    except Exception:
        return False

    attach_to_window = getattr(egg_hook, u"attach_to_window", None)
    if attach_to_window is not None:
        try:
            attach_to_window(window, theme=get_palette, tool=core.TOOL_NAME)
            return True
        except TypeError:
            try:
                attach_to_window(window, theme=get_palette)
                return True
            except Exception:
                pass
        except Exception:
            pass

    attach = getattr(egg_hook, u"attach", None)
    if attach is not None and logo_host is not None:
        try:
            attach(logo_host, host_window=window, theme=get_palette)
            return True
        except Exception:
            pass

    launch = getattr(egg_hook, u"launch", None)
    if launch is None or logo_host is None:
        return False
    counter = SlowClicks()

    def on_down(sender, args):
        try:
            if counter.click(int(args.Timestamp)):
                launch(window, get_palette, None)
        except Exception:
            pass
    try:
        logo_host.PreviewMouseLeftButtonDown += on_down
        return True
    except Exception:
        return False


# ============================================================
# chrome: drag, resize grips, full screen by bounds
# ============================================================

def _dpi_scale(window):
    try:
        source = PresentationSource.FromVisual(window)
        return float(source.CompositionTarget.TransformToDevice.M11) or 1.0
    except Exception:
        return 1.0


def work_area(window):
    """The working area of the screen the window is on, in WPF units -
    SystemParameters.WorkArea is only ever the primary monitor."""
    try:
        from System.Windows.Forms import Screen
        handle = WindowInteropHelper(window).Handle
        area = Screen.FromHandle(handle).WorkingArea
        scale = _dpi_scale(window)
        return (area.Left / scale, area.Top / scale,
                area.Width / scale, area.Height / scale)
    except Exception:
        area = SystemParameters.WorkArea
        return (area.Left, area.Top, area.Width, area.Height)


# ============================================================
# shrink to the taskbar: the drawer
# ============================================================

# every drawer alive, so a dialog can take its owner down with it and the
# bars can stack instead of landing on top of one another
_DRAWERS = []
_NAN = float(u"nan")


def drawer_for(window):
    for drawer in _DRAWERS:
        if drawer.window is window:
            return drawer
    return None


def _frame_top(window, header):
    """How far the header sits inside the window - the rounded border's
    edge - so the parked bar keeps its frame."""
    try:
        return float(header.TranslatePoint(Point(0, 0), window).Y)
    except Exception:
        return 1.0


def _dispatcher_timer(window, tick):
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(core.DRAWER_TICK_MS)
    timer.Tick += tick
    return timer


def _clock_ms():
    return time.time() * 1000.0


def _ctrl_shift_h(args):
    try:
        return (args.Key == Key.H and
                Keyboard.Modifiers == (ModifierKeys.Control | ModifierKeys.Shift))
    except Exception:
        return False


class WindowDrawer(object):
    """Shrink to the taskbar. Slides the window down to the bottom of its
    screen like a drawer closing, leaving only its header bar floating so
    Revit can be seen; the button becomes a green up arrow that slides it
    back. One per window, built by Chrome from the BtnShrink in the header.

    Top and Height are eased together by hand on a 15ms timer - a Storyboard
    on a borderless window fights the layout pass, and one never released
    holds its end value over every later assignment. The timer, clock,
    working area and header offset are arguments, so the bench drives whole
    slides against a stand-in window."""

    def __init__(self, window, header, button, root=None, grips=None,
                 timer_factory=None, clock=None, area_of=None, frame_of=None):
        self.window = window
        self.header = header
        self.button = button
        self.root = root if root is not None else window.Content
        self.grips = grips if grips is not None else window.FindName(u"GripLayer")
        self.timer_factory = timer_factory or _dispatcher_timer
        self.clock = clock or _clock_ms
        self.area_of = area_of or work_area
        self.frame_of = frame_of or _frame_top
        self.parked = False
        self.sliding = None        # u"down" / u"up" while a slide runs
        self.slide = None
        self.timer = None
        self.saved = None          # (left, top, width, height) when it parked
        self.parked_at = None      # (left, top) of the bar as it landed
        self.bar = 0.0
        self.kept = None           # MinHeight, SizeToContent
        self.root_kept = None      # root Height, VerticalAlignment
        self.root_height = 0.0
        self.grips_were = None
        self.hidden = []           # (element, Visibility) collapsed on landing
        self.owner = None
        try:
            owner_window = window.Owner
        except Exception:
            owner_window = None
        if owner_window is not None:
            self.owner = drawer_for(owner_window)
        # a window opening over a parked owner brings the owner back first,
        # so CenterOwner centres on the window rather than on its bar
        if self.owner is not None and self.owner.parked:
            self.owner.reopen(animate=False)
        _DRAWERS.append(self)
        if button is not None:
            button.Click += self._on_button
        try:
            window.Closed += self._on_closed
        except Exception:
            pass
        self._glyph()

    # ---------------- events ----------------

    def _on_button(self, sender, args):
        try:
            self.toggle()
        except Exception:
            log(u"shrink to taskbar failed:\n" + traceback.format_exc())

    def _on_closed(self, sender, args):
        try:
            self._stop()
        except Exception:
            pass
        if self in _DRAWERS:
            _DRAWERS.remove(self)
        # closing a parked dialog brings back the window it took down
        if self.owner is not None and self.owner.parked:
            try:
                self.owner.reopen()
            except Exception:
                pass

    def _on_tick(self, sender, args):
        try:
            self.frame()
        except Exception:
            # a frame that throws lands the window at the end of its slide
            self._land()

    # ---------------- the two gestures ----------------

    def toggle(self):
        if self.parked:
            self.reopen()
        else:
            self.shrink()

    def shrink(self):
        if self.parked:
            return
        # a dialog does not stand alone over Revit: its owner goes down first
        # and the dialog's bar stacks above the owner's
        if self.owner is not None and not self.owner.parked:
            self.owner.shrink()
        w = self.window
        try:
            Mouse.Capture(None)   # closes any StaysOpen=False popup
        except Exception:
            pass
        if self.saved is None:
            self.saved = (w.Left, w.Top, w.ActualWidth, w.ActualHeight)
            self._relax()
            self._pin(self.root.ActualHeight)
            self._park_grips()
        below = core.stacked_below([d.bar for d in _DRAWERS if d.parked and d is not self])
        self.bar = core.bar_height(self.frame_of(w, self.header), self.header.ActualHeight)
        area = self.area_of(w)
        top = core.parked_top(area[1], area[3], self.bar, below)
        self.parked = True
        self.parked_at = (w.Left, top)
        self._glyph()
        self._start(w.Top, top, w.ActualHeight, self.bar, u"down")

    def reopen(self, animate=True):
        if not self.parked or self.saved is None:
            return
        w = self.window
        mid_slide = self.sliding == u"down"
        self.parked = False
        if mid_slide:
            left, top = self.saved[0], self.saved[1]
        else:
            left, top = core.reopen_bounds(self.saved, self.parked_at, (w.Left, w.Top),
                                           self.bar, self.area_of(w))
        w.Left = left
        # the body comes back pinned at its full height, so it is drawn out
        # whole rather than re-laid out on every frame
        self._pin(self.root_height)
        self._show_hidden()
        self._glyph()
        self._start(w.Top, top, w.ActualHeight, self.saved[3], u"up")
        if not animate:
            self._land()
        # bring the rest of the stack back with it
        if self.owner is not None and self.owner.parked:
            self.owner.reopen(animate)
        for drawer in list(_DRAWERS):
            if drawer.owner is self and drawer.parked:
                drawer.reopen(animate)

    # ---------------- the slide ----------------

    def _start(self, top0, top1, height0, height1, direction):
        self.slide = (self.clock(), float(top0), float(top1),
                      float(height0), float(height1))
        self.sliding = direction
        try:
            if self.timer is None:
                self.timer = self.timer_factory(self.window, self._on_tick)
            self.timer.Start()
        except Exception:
            self._land()

    def frame(self):
        if self.slide is None:
            return
        started, top0, top1, height0, height1 = self.slide
        progress = core.slide_progress(started, self.clock())
        w = self.window
        w.Top = core.slide_value(top0, top1, progress)
        w.Height = max(1.0, core.slide_value(height0, height1, progress))
        if progress >= 1.0:
            self._land()

    def _stop(self):
        if self.timer is not None:
            try:
                self.timer.Stop()
            except Exception:
                pass

    def _land(self):
        self._stop()
        slide, direction = self.slide, self.sliding
        self.slide = None
        self.sliding = None
        w = self.window
        # nothing may be left holding Top or Height - released each in its
        # own try, apart from the assignment, since this is also the path
        # when a slide could not start at all
        for prop in (Window.TopProperty, Window.HeightProperty):
            try:
                w.BeginAnimation(prop, None)
            except Exception:
                pass
        if slide is not None:
            try:
                w.Top = slide[2]
                w.Height = max(1.0, slide[4])
            except Exception:
                pass
        if direction == u"down":
            self._hide_rest()
            self._unpin()
        elif direction == u"up":
            self._restore()

    # ---------------- the five traps ----------------

    def _relax(self):
        """MinHeight and SizeToContent each veto a Height change, and a
        vetoed slide leaves the window half shut."""
        w = self.window
        self.kept = (w.MinHeight, w.SizeToContent)
        height = w.ActualHeight
        w.SizeToContent = SizeToContent.Manual
        w.MinHeight = 0
        w.Height = height

    def _pin(self, height):
        """Hold the body at its full height for the slide and let the window
        clip it, so the tables are not re-measured on every frame."""
        root = self.root
        if root is None:
            return
        try:
            if self.root_kept is None:
                self.root_kept = (root.Height, root.VerticalAlignment)
            self.root_height = float(height or root.ActualHeight)
            root.Height = self.root_height
            root.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass

    def _unpin(self):
        root = self.root
        if root is None or self.root_kept is None:
            return
        try:
            root.Height, root.VerticalAlignment = self.root_kept
        except Exception:
            try:
                root.Height = _NAN
                root.VerticalAlignment = VerticalAlignment.Stretch
            except Exception:
                pass

    def _park_grips(self):
        """The grip overlay spans the whole window; left showing it would
        line the parked bar with drag handles and swallow the arrow's click."""
        if self.grips is None:
            return
        try:
            self.grips_were = self.grips.Visibility
            self.grips.Visibility = Visibility.Collapsed
        except Exception:
            pass

    def _hide_rest(self):
        """Once landed, everything but the header collapses - each sibling on
        the way from the header up to the window - so the bar is a bar, with
        its own rounded frame, and nothing hidden can take a click."""
        self.hidden = []
        child = self.header
        while child is not None and child is not self.window:
            try:
                parent = child.Parent
            except Exception:
                break
            children = getattr(parent, u"Children", None)
            if children is not None:
                for sibling in list(children):
                    if sibling is child:
                        continue
                    try:
                        self.hidden.append((sibling, sibling.Visibility))
                        sibling.Visibility = Visibility.Collapsed
                    except Exception:
                        pass
            child = parent

    def _show_hidden(self):
        """Put back exactly what each one was - a closed panel stays closed."""
        for element, visibility in self.hidden:
            try:
                element.Visibility = visibility
            except Exception:
                pass
        self.hidden = []

    def _restore(self):
        w = self.window
        self._unpin()
        self.root_kept = None
        if self.kept is not None:
            min_height, size_to_content = self.kept
            try:
                w.MinHeight = min_height
                w.SizeToContent = size_to_content
            except Exception:
                pass
            self.kept = None
        if self.grips is not None and self.grips_were is not None:
            try:
                self.grips.Visibility = self.grips_were
            except Exception:
                pass
        self.grips_were = None
        self.saved = None
        self.parked_at = None

    def _glyph(self):
        """Down arrow onto a bar while open; a green up arrow while parked."""
        try:
            find = self.window.FindName
            shrink, expand = find(u"ShrinkGlyph"), find(u"ExpandGlyph")
            if shrink is not None:
                shrink.Visibility = Visibility.Collapsed if self.parked else Visibility.Visible
            if expand is not None:
                expand.Visibility = Visibility.Visible if self.parked else Visibility.Collapsed
            if self.button is not None:
                self.button.ToolTip = (u"Bring the window back (Ctrl+Shift+H)" if self.parked else
                                       u"Shrink to the taskbar so Revit can be seen (Ctrl+Shift+H)")
        except Exception:
            pass


class Chrome(object):
    """Drag, resize grips, full screen by bounds, close, and shrink to the
    taskbar - the same gestures on every window the tool opens."""
    GRIPS = (u"GripN", u"GripS", u"GripW", u"GripE",
             u"GripNW", u"GripNE", u"GripSW", u"GripSE")

    def __init__(self, window, header=None, full_button=None,
                 full_glyph_back=None, close_button=None, resizable=True):
        self.window = window
        self.full = False
        self.saved = None
        self.full_glyph_back = full_glyph_back
        self.drawer = None
        shrink_button = window.FindName(u"BtnShrink")
        if header is not None and shrink_button is not None:
            self.drawer = WindowDrawer(window, header, shrink_button)
        if header is not None:
            header.MouseLeftButtonDown += self.on_header_down
        if full_button is not None:
            full_button.Click += lambda s, a: self.toggle_full()
        if close_button is not None:
            close_button.Click += lambda s, a: self.window.Close()
        if resizable:
            for name in self.GRIPS:
                grip = window.FindName(name)
                if grip is not None:
                    grip.DragDelta += self._make_drag(name)
        else:
            layer = window.FindName(u"GripLayer")
            if layer is not None:
                layer.Visibility = Visibility.Collapsed
        window.PreviewKeyDown += self.on_key

    def on_header_down(self, sender, args):
        try:
            drawer = self.drawer
            if drawer is not None and drawer.parked:
                # parked: a double-click brings it back, a drag carries the bar
                if args.ClickCount == 2:
                    drawer.reopen()
                elif args.ButtonState == MouseButtonState.Pressed:
                    self.window.DragMove()
                return
            if args.ClickCount == 2 and self.full_glyph_back is not None:
                self.toggle_full()
                return
            if self.full:
                self.leave_full(keep_position=True)
            if args.ButtonState == MouseButtonState.Pressed:
                self.window.DragMove()
        except Exception:
            pass

    def on_key(self, sender, args):
        try:
            drawer = self.drawer
            if drawer is not None:
                if _ctrl_shift_h(args):
                    drawer.toggle()
                    args.Handled = True
                    return
                if drawer.parked:
                    # Escape, Enter and F11 bring it back rather than closing
                    # or filling the screen with a window nobody can see;
                    # every other key is held so nothing acts on what is hidden
                    if args.Key in (Key.Escape, Key.Enter, Key.F11):
                        drawer.reopen()
                    args.Handled = True
                    return
            if args.Key == Key.F11 and self.full_glyph_back is not None:
                self.toggle_full()
                args.Handled = True
            elif args.Key == Key.Escape and self.full:
                self.leave_full()
                args.Handled = True
        except Exception:
            pass

    def _make_drag(self, name):
        def drag(sender, args):
            try:
                if self.full:
                    self.full = False
                    self._glyph()
                w = self.window
                min_w = w.MinWidth or 300
                min_h = w.MinHeight or 200
                dx = args.HorizontalChange
                dy = args.VerticalChange
                if u"E" in name[4:]:
                    w.Width = max(min_w, w.ActualWidth + dx)
                if u"S" in name[4:]:
                    w.Height = max(min_h, w.ActualHeight + dy)
                if u"W" in name[4:]:
                    new_w = max(min_w, w.ActualWidth - dx)
                    w.Left = w.Left + (w.ActualWidth - new_w)
                    w.Width = new_w
                if u"N" in name[4:]:
                    new_h = max(min_h, w.ActualHeight - dy)
                    w.Top = w.Top + (w.ActualHeight - new_h)
                    w.Height = new_h
            except Exception:
                pass
        return drag

    def _glyph(self):
        try:
            if self.full_glyph_back is not None:
                self.full_glyph_back.Visibility = (Visibility.Visible if self.full
                                                   else Visibility.Collapsed)
        except Exception:
            pass

    def toggle_full(self):
        if self.full:
            self.leave_full()
        else:
            self.enter_full()

    def enter_full(self):
        w = self.window
        self.saved = (w.Left, w.Top, w.Width, w.Height)
        left, top, width, height = work_area(w)
        w.WindowState = WindowState.Normal
        w.Left, w.Top, w.Width, w.Height = left, top, width, height
        self.full = True
        self._glyph()

    def leave_full(self, keep_position=False):
        w = self.window
        if self.saved is not None:
            left, top, width, height = self.saved
            w.Width, w.Height = width, height
            if not keep_position:
                w.Left, w.Top = left, top
        self.full = False
        self._glyph()


# ============================================================
# themed message window, with Revit's own dialog as the fallback
# ============================================================

def _task_dialog(title, body, yes_no):
    try:
        from Autodesk.Revit.UI import (TaskDialog, TaskDialogCommonButtons,
                                       TaskDialogResult)
        dialog = TaskDialog(title)
        dialog.MainContent = body
        if yes_no:
            dialog.CommonButtons = (TaskDialogCommonButtons.Yes |
                                    TaskDialogCommonButtons.No)
            return dialog.Show() == TaskDialogResult.Yes
        dialog.Show()
        return True
    except Exception:
        return False


def message(owner, title, body, yes_text=None, no_text=None, mode=u"auto"):
    """Returns True for yes / OK. A dialog standing between the user and a
    write must never swallow its own failure and answer 'no' - if the themed
    window cannot open, Revit's own dialog asks instead."""
    yes_no = no_text is not None
    try:
        window = load_window(u"MsmMessage.xaml", mode)
        find = window.FindName
        find(u"TitleText").Text = title
        find(u"BodyText").Text = body
        find(u"VersionText").Text = u"v{0}".format(core.__version__)
        load_icon(find(u"Logo"))
        yes = find(u"BtnYes")
        no = find(u"BtnNo")
        yes.Content = yes_text or u"OK"
        if yes_no:
            no.Content = no_text
        else:
            no.Visibility = Visibility.Collapsed
        state = {u"answer": False}

        def on_yes(sender, args):
            state[u"answer"] = True
            window.Close()

        yes.Click += on_yes
        no.Click += lambda s, a: window.Close()
        if owner is not None:
            try:
                window.Owner = owner
            except Exception:
                pass
        Chrome(window, header=find(u"HeaderBar"), close_button=find(u"BtnClose"),
               resizable=False)
        attach_egg(window, find(u"LogoHost"),
                   lambda: theme.palette(theme.resolve(mode)))
        window.ShowDialog()
        return state[u"answer"]
    except Exception:
        log(u"themed message failed, using TaskDialog:\n" + traceback.format_exc())
        return _task_dialog(title, body, yes_no)


def later(window, action):
    """Run something on the window's dispatcher once the current work is
    done - used to report from an ExternalEvent without blocking on it."""
    try:
        window.Dispatcher.BeginInvoke(Action(action))
        return True
    except Exception:
        try:
            action()
        except Exception:
            pass
        return False


# ============================================================
# Excel export: where to save, writing the zip, showing it
# ============================================================

def ask_save_path(owner, filename, folder):
    """Windows' own Save As; the path, or None if it was cancelled."""
    dialog = SaveFileDialog()
    dialog.Title = u"Export pipe systems to Excel"
    dialog.Filter = u"Excel workbook (*.xlsx)|*.xlsx"
    dialog.DefaultExt = u".xlsx"
    dialog.AddExtension = True
    dialog.OverwritePrompt = True
    dialog.FileName = filename
    if folder and os.path.isdir(folder):
        dialog.InitialDirectory = folder
    try:
        answer = dialog.ShowDialog(owner) if owner is not None else dialog.ShowDialog()
    except Exception:
        answer = dialog.ShowDialog()
    if answer is True or u"{0}".format(answer) == u"True":
        return dialog.FileName
    return None


def write_xlsx(path, parts):
    """Zip the parts from msm_xlsx.build_parts to path, UTF-8 without a BOM.
    A file open in Excel raises here and the caller says so."""
    stream = FileStream(path, FileMode.Create)
    try:
        archive = ZipArchive(stream, ZipArchiveMode.Create)
        try:
            for name, text in parts:
                entry = archive.CreateEntry(name, CompressionLevel.Optimal)
                writer = StreamWriter(entry.Open(), UTF8Encoding(False))
                try:
                    writer.Write(text)
                finally:
                    writer.Dispose()
        finally:
            archive.Dispose()
    finally:
        stream.Dispose()


def show_in_folder(path):
    try:
        Process.Start(u"explorer.exe", u'/select,"{0}"'.format(path))
    except Exception:
        pass
