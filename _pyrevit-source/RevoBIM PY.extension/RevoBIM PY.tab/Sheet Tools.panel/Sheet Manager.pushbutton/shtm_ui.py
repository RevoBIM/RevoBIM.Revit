# -*- coding: utf-8 -*-
"""XAML loading, theming, window chrome, prompts and the small composite
controls the tool builds in code.

Layout XAML uses DynamicResource only: Theme.xaml is merged in after XamlReader
has parsed the layout, so a StaticResource fails at load - the blank white
pyRevit window again.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import os
import sys
import traceback

import shtm_core
import theme

from System.IO import StringReader, MemoryStream, File
from System.Xml import XmlReader
from System.Windows.Markup import XamlReader
from System.Windows import (
    SystemParameters, Thickness, GridLength, GridUnitType, Visibility,
)
from System.Windows.Controls import (
    Grid, TextBlock, TextBox, Button, CheckBox, ComboBox, ComboBoxItem,
    ListBox, ListBoxItem, Border, ColumnDefinition, RowDefinition,
    StackPanel,
)
from System.Windows.Controls.Primitives import Popup, PlacementMode
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Input import Key
from System.Windows.Threading import DispatcherTimer
from System import TimeSpan

HERE = os.path.dirname(os.path.abspath(__file__))


def ui_safe(function):
    """Every WPF event closure goes through this.

    An exception thrown inside a WPF event handler in IronPython is swallowed
    silently, so a dead button looks like a dead tool.
    """
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            try:
                log(traceback.format_exc())
            except Exception:
                pass
    return wrapper


def log(text):
    folder = shtm_core.settings_folder()
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(os.path.join(folder, "sheet_manager.log"), "ab")
        try:
            handle.write((u"{0}\n".format(text)).encode("utf-8"))
        finally:
            handle.close()
    except Exception:
        pass


# ====================== loading ======================

def read_text(path):
    handle = open(path, "rb")
    try:
        return handle.read().decode("utf-8", "replace")
    finally:
        handle.close()


def load_window(file_name, mode="auto"):
    """Parse the layout, then merge Theme.xaml, then write the palette."""
    text = read_text(os.path.join(HERE, file_name))
    window = XamlReader.Load(XmlReader.Create(StringReader(text)))

    theme_text = read_text(os.path.join(HERE, "Theme.xaml"))
    dictionary = XamlReader.Load(XmlReader.Create(StringReader(theme_text)))
    window.Resources.MergedDictionaries.Add(dictionary)

    theme.apply(window, mode)
    return window


def load_icon(image, path=None):
    """No System.Uri anywhere - the assembly moved in Revit 2025 and importing
    it throws at module load. Images come from bytes."""
    path = path or os.path.join(HERE, "icon.png")
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


# ====================== the easter egg ======================

def _egg_module():
    """Import the shared egg, putting the extension's lib on the path first.

    This is what `startup.py` and the two hooks do, and it is the reason they
    work when a tool does not: pyRevit only has `lib` on the path if something
    put it there this session. Walking up from this folder to the extension
    root and inserting `lib` makes the egg reachable whether or not startup.py
    ran, whether or not another tool's delivery clobbered it, and whether or
    not the hooks fired.

    `egg_auto.install()` is the automatic attachment startup.py arms, and it is
    idempotent, so calling it here costs nothing and is one more anchor.
    """
    root = os.path.dirname(os.path.abspath(__file__))
    for _step in range(6):
        root = os.path.dirname(root)
        lib = os.path.join(root, "lib")
        if os.path.isdir(os.path.join(lib, "revobim", "egg")):
            if lib not in sys.path:
                sys.path.insert(0, lib)
            break
    try:
        from revobim.egg import egg_hook
    except Exception:
        return None
    try:
        from revobim.egg import egg_auto
        egg_auto.install()
    except Exception:
        pass
    return egg_hook


def attach_egg(window, logo_host=None, mode=None):
    """Three slow clicks on the RevoBIM logo.

    The egg lives in the extension's shared lib\\revobim\\egg package and is not
    shipped with this tool. The current call is `attach_to_window`, which finds
    the logo itself whatever the layout calls it; `attach` is the older form and
    is kept as a fallback for an older copy of the package. Anything decorative
    belongs in a try/except that swallows failures, so cosmetics can never take
    a tool down.
    """
    egg_hook = _egg_module()
    if egg_hook is None:
        return False

    palette = _palette_callable(mode)

    attach_to_window = getattr(egg_hook, "attach_to_window", None)
    if attach_to_window is not None:
        try:
            attach_to_window(window, theme=palette, tool=shtm_core.TOOL_NAME)
            return True
        except TypeError:
            try:
                attach_to_window(window, theme=palette)
                return True
            except Exception:
                pass
        except Exception:
            pass

    attach = getattr(egg_hook, "attach", None)
    if attach is None or logo_host is None:
        return False
    try:
        attach(logo_host, host_window=window, theme=palette)
        return True
    except Exception:
        return False


def play_egg(window=None, mode=None):
    """Open the egg straight onto Pacman, rather than making somebody do three
    slow clicks on a logo while they are waiting for a job to finish.

    `egg_hook.launch` is the egg's own way in without the clicks - it is what
    the egg is tested with - and `game_key` is the game's file name in
    `egg\\games`.
    """
    egg_hook = _egg_module()
    if egg_hook is None:
        return False
    launch = getattr(egg_hook, "launch", None)
    if launch is None:
        return False
    palette = _palette_callable(mode)
    for key in ("pacman", "Pacman", None):
        try:
            if key is None:
                launch(host_window=window, theme=palette)
            else:
                launch(host_window=window, theme=palette, game_key=key)
            return True
        except TypeError:
            continue
        except Exception:
            continue
    return False


def _palette_callable(mode):
    """The egg asks for the palette by calling this, so it follows the tool's
    own light/dark chip rather than a value captured when the window opened."""
    def palette():
        try:
            return theme.resolve(mode() if callable(mode) else mode)
        except Exception:
            return "dark"
    return palette


# ====================== chrome ======================# ====================== chrome ======================

class Chrome(object):
    """Borderless window: drag, eight resize grips, full screen by bounds, and
    the shrink-to-taskbar drawer whenever the layout has a ShrinkBtn."""

    def __init__(self, window, header=None, on_close=None, resizable=True,
                 busy=None):
        self.window = window
        self.header = header
        self.on_close = on_close
        self.full = False
        self.saved = None
        # the height before a double click on the top or bottom edge
        self.tall_saved = None
        self.drawer = None
        self._wire(resizable)
        shrink = self.find("ShrinkBtn")
        bar = self.header if self.header is not None else self.find("HeaderBar")
        if shrink is not None and bar is not None:
            self.drawer = Drawer(window, bar, shrink, chrome=self, busy=busy)

    def parked(self):
        return self.drawer is not None and self.drawer.parked

    def find(self, name):
        try:
            return self.window.FindName(name)
        except Exception:
            return None

    def _wire(self, resizable):
        header = self.header if self.header is not None else self.find("HeaderBar")
        if header is not None:
            header.MouseLeftButtonDown += ui_safe(self._drag)
        close_button = self.find("CloseBtn")
        if close_button is not None:
            close_button.Click += ui_safe(lambda s, e: self.close())
        full_button = self.find("FullBtn")
        if full_button is not None:
            full_button.Click += ui_safe(lambda s, e: self.toggle_full())
        self.window.KeyDown += ui_safe(self._key)
        if resizable:
            self._grips()

    def _grips(self):
        pairs = [("GripL", -1, 0), ("GripR", 1, 0), ("GripT", 0, -1), ("GripB", 0, 1),
                 ("GripTL", -1, -1), ("GripTR", 1, -1), ("GripBL", -1, 1), ("GripBR", 1, 1)]
        for name, dx, dy in pairs:
            grip = self.find(name)
            if grip is None:
                continue
            grip.DragDelta += self._grip_handler(dx, dy)
            if name in ("GripT", "GripB"):
                # Preview: the Thumb takes the press for a drag otherwise
                grip.PreviewMouseLeftButtonDown += ui_safe(self._edge_pressed)

    def _edge_pressed(self, sender, event):
        if event.ClickCount == 2:
            self.toggle_tall()
            event.Handled = True

    def toggle_tall(self):
        """Full height of the screen the window is on, keeping its width and
        where it sits across; the next double click puts it back."""
        if self.parked():
            self.drawer.open()
            return
        if self.full:
            self.toggle_full()
        window = self.window
        left, top, width, height = self._work_area()
        new_top, new_height, self.tall_saved = shtm_core.full_height(
            top, height, window.Top, window.ActualHeight, self.tall_saved)
        try:
            from System.Windows import SizeToContent
            window.SizeToContent = SizeToContent.Manual
        except Exception:
            pass
        window.Top = new_top
        window.Height = max(new_height, window.MinHeight)

    def _grip_handler(self, dx, dy):
        window = self.window

        @ui_safe
        def handler(sender, event):
            if self.full or self.parked():
                return
            # resized by hand (a real drag, not the jitter of a double click):
            # the next double click stretches again
            if abs(event.HorizontalChange) > 2 or abs(event.VerticalChange) > 2:
                self.tall_saved = None
            if dx < 0:
                width = window.Width - event.HorizontalChange
                if width >= window.MinWidth:
                    window.Left += event.HorizontalChange
                    window.Width = width
            elif dx > 0:
                width = window.Width + event.HorizontalChange
                if width >= window.MinWidth:
                    window.Width = width
            if dy < 0:
                height = window.Height - event.VerticalChange
                if height >= window.MinHeight:
                    window.Top += event.VerticalChange
                    window.Height = height
            elif dy > 0:
                height = window.Height + event.VerticalChange
                if height >= window.MinHeight:
                    window.Height = height
        return handler

    @ui_safe
    def _drag(self, sender, event):
        if self.parked():
            # a parked bar drags, and a double click brings the window back
            # rather than filling the screen with something unseen; it does
            # not drag mid-job - DragMove is a modal loop, not something to
            # start while Revit is in a transaction
            if event.ClickCount == 2:
                self.drawer.open()
            elif not self.drawer.is_busy():
                try:
                    self.window.DragMove()
                except Exception:
                    pass
            return
        if event.ClickCount == 2:
            self.toggle_full()
            return
        if self.full:
            self.toggle_full()
        try:
            self.window.DragMove()
        except Exception:
            pass

    @ui_safe
    def _key(self, sender, event):
        if event.Key == Key.F11:
            self.toggle_full()
        elif event.Key == Key.Escape and self.full:
            self.toggle_full()

    def toggle_full(self):
        window = self.window
        if self.parked():
            self.drawer.open()
            return
        if self.full:
            if self.saved:
                window.Left, window.Top, window.Width, window.Height = self.saved
            self.full = False
            return
        self.saved = (window.Left, window.Top, window.Width, window.Height)
        left, top, width, height = self._work_area()
        window.Left, window.Top, window.Width, window.Height = left, top, width, height
        self.full = True

    def _work_area(self):
        return work_area(self.window)

    def close(self):
        if self.on_close is not None:
            try:
                self.on_close()
            except Exception:
                pass
        try:
            self.window.Close()
        except Exception:
            pass


def work_area(window):
    """The working area (screen less taskbar) of the screen `window` is on,
    in WPF units: left, top, width, height. A monitor above the primary has a
    negative top, and that is kept."""
    scale_x, scale_y = 1.0, 1.0
    try:
        from System.Windows import PresentationSource
        source = PresentationSource.FromVisual(window)
        matrix = source.CompositionTarget.TransformToDevice
        scale_x = matrix.M11 or 1.0
        scale_y = matrix.M22 or 1.0
    except Exception:
        pass
    try:
        from System.Windows.Forms import Screen
        from System.Drawing import Point as DrawPoint
        centre = DrawPoint(int((window.Left + window.ActualWidth / 2) * scale_x),
                           int((window.Top + min(window.ActualHeight, 40) / 2) * scale_y))
        area = Screen.FromPoint(centre).WorkingArea
        return (area.Left / scale_x, area.Top / scale_y,
                area.Width / scale_x, area.Height / scale_y)
    except Exception:
        pass
    area = SystemParameters.WorkArea
    return (area.Left, area.Top, area.Width, area.Height)


# ====================== shrink to taskbar ======================
#
# Every window the tool opens carries a shrink button top right. Pressed, the
# window slides down like a drawer closing until only its header bar floats
# just clear of the taskbar, so Revit can be seen and worked in; the button
# turns into a green up arrow that slides it back. Ctrl+Shift+H does both.
#
# What makes or breaks it (RevoBIM theme reference, "Shrink to taskbar"):
#   - eased by hand on a DispatcherTimer, never a Storyboard: an animation
#     holds its end value and outranks every later assignment, and a window
#     whose Top was animated and never released can never be moved again.
#     BeginAnimation(prop, None) is still called on Top and Height, each in
#     its own try, before every slide, in case anything else ever animates them;
#   - only Top moves during the slide, and the body is pinned at its full
#     height, so nothing re-measures on every frame - the shrinking window
#     simply clips it, which is what reads as a drawer;
#   - MinHeight and SizeToContent each veto the cut to the bar's height, so
#     both are relaxed for the trip down and put back on the way up;
#   - the resize grips go dead while parked, or they line the bar with
#     invisible handles that swallow the click on the arrow;
#   - a frame that throws lands the window at its end state.
# Windows go down together: the main window and whatever it has open (the
# builder, Settings, a prompt) park as one group, stacked in slots, and come
# back as one.

DRAWERS = []


def _drawer_of(window):
    for drawer in DRAWERS:
        try:
            if drawer.window.Equals(window):
                return drawer
        except Exception:
            continue
    return None


def _root_window(window):
    """The top of the owner chain that has a drawer."""
    root = window
    seen = 0
    while seen < 10:
        seen += 1
        try:
            owner = root.Owner
        except Exception:
            owner = None
        if owner is None or _drawer_of(owner) is None:
            return root
        root = owner
    return root


def _group(drawer):
    """Every drawer that parks with this one: the same root, still open."""
    root = _root_window(drawer.window)
    members = []
    for other in DRAWERS:
        try:
            if not other.window.IsVisible and other is not drawer:
                continue
            if _root_window(other.window).Equals(root):
                members.append(other)
        except Exception:
            continue
    # the root first, so it takes the lowest slot nearest the taskbar
    members.sort(key=lambda d: 0 if d.window.Equals(root) else 1)
    return members


def bring_back(owner):
    """Called before a new window is given an owner: if the owner is parked,
    its group opens at once - a prompt centred on a parked bar would land
    half off the screen."""
    if owner is None:
        return
    drawer = _drawer_of(owner)
    if drawer is not None and drawer.parked:
        for member in _group(drawer):
            member.open_now()


class Drawer(object):

    def __init__(self, window, header, button, chrome=None, busy=None):
        self.window = window
        self.header = header
        self.button = button
        self.chrome = chrome
        self.busy = busy
        self.parked = False
        self.sliding = False
        self.slot = None
        self.bar = 0.0
        self.parked_at = 0.0
        self.saved = None
        self.timer = None
        DRAWERS.append(self)
        button.Click += ui_safe(lambda s, e: self.toggle())
        window.PreviewKeyDown += ui_safe(self._keys)
        window.Closed += ui_safe(self._closed)
        self._paint()

    # ---- the button ----

    def _paint(self):
        """The style swaps the down arrow for the green up arrow on Tag."""
        try:
            self.button.Tag = u"shrunk" if self.parked else u""
            self.button.ToolTip = (u"Bring the window back (Ctrl+Shift+H)"
                                   if self.parked else
                                   u"Shrink to the taskbar so Revit can be seen "
                                   u"(Ctrl+Shift+H)")
        except Exception:
            pass

    def is_busy(self):
        try:
            return bool(self.busy()) if self.busy is not None else False
        except Exception:
            return False

    def toggle(self):
        if self.sliding:
            return
        if self.parked:
            self.open()
        else:
            self.shrink()

    # ---- keys ----

    def _keys(self, sender, event):
        ctrl_shift = False
        try:
            from System.Windows.Input import Keyboard, ModifierKeys
            wanted = ModifierKeys.Control | ModifierKeys.Shift
            ctrl_shift = (Keyboard.Modifiers & wanted) == wanted
        except Exception:
            pass
        if ctrl_shift and event.Key == Key.H:
            self.toggle()
            event.Handled = True
            return
        if not self.parked:
            return
        # parked: Esc, Enter and F11 bring it back rather than answering a
        # prompt nobody can see or filling the screen; nothing else gets through
        # to a text box out of sight
        if event.Key in (Key.Escape, Key.Enter, Key.Return, Key.F11):
            self.open()
        elif event.Key == Key.System:
            # Alt combinations - Alt+F4 among them - are left to Windows
            return
        event.Handled = True

    # ---- the group ----

    def shrink(self):
        for member in _group(self):
            if not member.parked and not member.sliding:
                member._park()

    def open(self):
        for member in _group(self):
            if member.parked and not member.sliding:
                member._unpark()

    def open_now(self):
        # mid-slide counts: a window caught on its way down is brought back
        # too, or the old slide would carry on and park it after all
        if self.parked or self.sliding:
            self._unpark(instant=True)

    # ---- one window ----

    def _bar_height(self):
        offset = 1.0
        try:
            from System.Windows import Point
            offset = max(0.0, self.header.TranslatePoint(Point(0, 0), self.window).Y)
        except Exception:
            pass
        return self.header.ActualHeight + 2 * offset

    def _taken(self):
        return [d.slot for d in DRAWERS if d is not self and d.slot is not None]

    def _below(self, slot):
        heights = []
        for lower in range(slot):
            for other in DRAWERS:
                if other is not self and other.slot == lower:
                    heights.append(other.bar)
        return heights

    def _park(self):
        window = self.window
        height = window.ActualHeight
        if self.chrome is not None and self.chrome.full:
            # full screen is left first, so the size coming back is the real
            # one - read from the bounds full screen kept, since the window
            # has not been laid out again yet
            try:
                kept = self.chrome.saved
                self.chrome.toggle_full()
                if kept:
                    height = kept[3]
            except Exception:
                pass
        root = window.Content
        self.saved = {
            "top": window.Top,
            "height": height,
            "min_height": window.MinHeight,
            "size_to_content": window.SizeToContent,
            "root_height": root.Height,
            "root_align": root.VerticalAlignment,
        }
        self.bar = self._bar_height()
        self.slot = shtm_core.free_slot(self._taken())
        left, top, width, height = work_area(window)
        self.parked_at = shtm_core.parked_top(top, height, self.bar,
                                              self._below(self.slot))
        self._release()
        try:
            from System.Windows import SizeToContent, VerticalAlignment
            window.SizeToContent = SizeToContent.Manual
            window.MinHeight = 0
            window.Height = self.saved["height"]
            # pinned: the body keeps its full height and the window clips it
            root.Height = root.ActualHeight
            root.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            log(u"drawer: could not pin the body\n" + traceback.format_exc())
        self._grips(False)
        self.parked = True
        self._paint()
        self._slide(window.Top, self.parked_at, self._landed_down)

    def _landed_down(self):
        try:
            self.window.Height = self.bar
        except Exception:
            pass

    def _stop(self):
        """Whatever slide is running stops where it is, so the next one is the
        only one moving the window."""
        if self.timer is not None:
            try:
                self.timer.Stop()
            except Exception:
                pass
        self.sliding = False

    def _unpark(self, instant=False):
        self._stop()
        window = self.window
        saved = self.saved or {}
        left, top, width, height = work_area(window)
        full = saved.get("height", window.ActualHeight)
        target = shtm_core.opened_top(saved.get("top", window.Top), full,
                                      self.parked_at, window.Top, top, height)
        self._release()
        try:
            window.Height = full
        except Exception:
            pass
        self.parked = False
        self.slot = None
        self._paint()
        if instant:
            window.Top = target
            self._landed_up()
            return
        self._slide(window.Top, target, self._landed_up)

    def _landed_up(self):
        window = self.window
        saved = self.saved or {}
        root = window.Content
        try:
            from System.Windows import VerticalAlignment
            root.Height = saved.get("root_height", float("nan"))
            root.VerticalAlignment = saved.get("root_align",
                                               VerticalAlignment.Stretch)
        except Exception:
            pass
        try:
            window.MinHeight = saved.get("min_height", 0)
        except Exception:
            pass
        try:
            window.SizeToContent = saved["size_to_content"]
        except Exception:
            pass
        self._grips(True)

    def _grips(self, live):
        for name in ("GripL", "GripR", "GripT", "GripB",
                     "GripTL", "GripTR", "GripBL", "GripBR", "GripLayer"):
            try:
                grip = self.window.FindName(name)
                if grip is not None:
                    grip.IsHitTestVisible = live
            except Exception:
                continue

    def _release(self):
        """Nothing may hold Top or Height: a held animation outranks every
        later assignment, silently."""
        from System.Windows import Window
        for prop in (Window.TopProperty, Window.HeightProperty):
            try:
                self.window.BeginAnimation(prop, None)
            except Exception:
                pass

    # ---- the slide ----

    def _slide(self, start, end, landed):
        from System import DateTime
        self._stop()
        self.sliding = True
        began = DateTime.Now
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromMilliseconds(shtm_core.DRAWER_TICK_MS)
        self.timer = timer

        def finish():
            timer.Stop()
            self.sliding = False
            try:
                self.window.Top = end
            except Exception:
                pass
            try:
                landed()
            except Exception:
                log(u"drawer: landing failed\n" + traceback.format_exc())

        def tick(sender, event):
            try:
                spent = (DateTime.Now - began).TotalMilliseconds
                progress = spent / float(shtm_core.DRAWER_MS)
                if progress >= 1.0:
                    finish()
                    return
                self.window.Top = shtm_core.between(start, end, progress)
            except Exception:
                # a frame that throws lands the window where it was going
                finish()

        timer.Tick += tick
        try:
            timer.Start()
        except Exception:
            finish()

    def _closed(self, sender, event):
        """A parked window closing frees its slot, and brings back the rest of
        its group - nothing is left parked with nobody to open it."""
        was_parked = self.parked
        self.parked = False
        self.slot = None
        try:
            if self.timer is not None:
                self.timer.Stop()
        except Exception:
            pass
        if self in DRAWERS:
            DRAWERS.remove(self)
        if was_parked:
            try:
                owner = self.window.Owner
            except Exception:
                owner = None
            bring_back(owner)

# ====================== prompts ======================

class Prompt(object):
    """One themed window for messages, confirmations and results."""

    def __init__(self, mode="auto", owner=None):
        self.window = load_window("ShtmPrompt.xaml", mode)
        self.owner = owner
        self.result = 0
        self.chrome = Chrome(self.window)
        load_icon(self.window.FindName("LogoImage"))
        attach_egg(self.window, self.window.FindName("LogoHost"), mode)
        self.window.FindName("VersionText").Text = u"v{0}".format(shtm_core.__version__)

    def show(self, subtitle, body, buttons=None, width=None, height=None):
        buttons = buttons or ["OK"]
        self.window.FindName("SubTitle").Text = subtitle
        self.window.FindName("BodyText").Text = body
        names = ["FirstBtn", "SecondBtn", "ThirdBtn"]
        for index, name in enumerate(names):
            button = self.window.FindName(name)
            if index < len(buttons):
                button.Content = buttons[index]
                button.Visibility = Visibility.Visible
                button.Click += self._picker(index)
            else:
                button.Visibility = Visibility.Collapsed
        if width:
            self.window.Width = width
        if height:
            self.window.Height = height
        if self.owner is not None:
            try:
                bring_back(self.owner)
                self.window.Owner = self.owner
            except Exception:
                pass
        self.window.ShowDialog()
        return self.result

    def _picker(self, index):
        @ui_safe
        def handler(sender, event):
            self.result = index
            self.window.Close()
        return handler


def ask_text(mode, owner, subtitle, body, initial=u"", ok=u"OK"):
    """A typed answer: the text, stripped, or None when cancelled or blank.
    Enter answers, Esc cancels."""
    prompt = Prompt(mode, owner)
    box = prompt.window.FindName("InputBox")
    box.Visibility = Visibility.Visible
    box.Text = initial or u""

    @ui_safe
    def keys(sender, event):
        if event.Key in (Key.Enter, Key.Return):
            prompt.result = 0
            prompt.window.Close()
            event.Handled = True
        elif event.Key == Key.Escape:
            prompt.result = 1
            prompt.window.Close()
            event.Handled = True

    @ui_safe
    def shown(sender, event):
        box.Focus()
        box.SelectAll()

    box.PreviewKeyDown += keys
    prompt.window.ContentRendered += shown
    prompt.result = 1
    # tall enough for the question and the box under it
    lines = len((body or u"").split(u"\n")) + len(body or u"") // 70
    answer = prompt.show(subtitle, body, [ok, u"Cancel"], 520, min(520, 230 + 20 * lines))
    text = (box.Text or u"").strip()
    if answer != 0 or not text:
        return None
    return text


def message(mode, owner, subtitle, body, buttons=None, width=None, height=None):
    return Prompt(mode, owner).show(subtitle, body, buttons, width, height)


def choose(mode, owner, subtitle, body, options, buttons=None):
    """The themed prompt with a list in it. Returns the picked option or None.

    The prompt's body is a single TextBlock inside a ScrollViewer, so the list
    is put in beside it rather than in a window of its own - one themed window
    is easier to keep looking right than two.
    """
    prompt = Prompt(mode, owner)
    window = prompt.window
    body_text = window.FindName("BodyText")
    holder = body_text.Parent
    listing = ListBox()
    styled(listing, "Lst.Flat")
    listing.MaxHeight = 320
    listing.Margin = Thickness(0, 10, 0, 0)
    for option in options:
        item = ListBoxItem()
        item.Content = option
        styled(item, "Lst.Item")
        listing.Items.Add(item)
    if listing.Items.Count:
        listing.SelectedIndex = 0
    try:
        # the body already sits in a StackPanel (1.9.0, for the typed answer),
        # so the list goes straight in under it
        holder.Children.Insert(1, listing)
    except Exception:
        return None
    index = prompt.show(subtitle, body, buttons or [u"Open", u"Not now"],
                        width=520, height=420)
    if index != 0:
        return None
    item = listing.SelectedItem
    if item is None:
        return None
    return u"{0}".format(item.Content)


def confirm(mode, owner, subtitle, body, yes=u"Go ahead", no=u"Cancel"):
    """A silent return False in a confirm step is indistinguishable from a
    broken button, so a prompt that will not open falls back to Revit's own."""
    try:
        return message(mode, owner, subtitle, body, [yes, no]) == 0
    except Exception:
        try:
            from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult
            dialog = TaskDialog("RevoBIM Sheet Manager")
            dialog.MainInstruction = subtitle
            dialog.MainContent = body
            dialog.CommonButtons = (TaskDialogCommonButtons.Yes |
                                    TaskDialogCommonButtons.No)
            return dialog.Show() == TaskDialogResult.Yes
        except Exception:
            return False


# ====================== small composites ======================

def styled(element, key):
    """A dependency property is static: reach it through the class, never
    through an instance."""
    try:
        from System.Windows import FrameworkElement
        element.SetResourceReference(FrameworkElement.StyleProperty, key)
    except Exception:
        pass
    return element


def text_block(text, style="Lbl.Body", margin=None):
    block = TextBlock()
    block.Text = text
    styled(block, style)
    if margin:
        block.Margin = Thickness(*margin)
    return block


def text_box(tag=u"", width=None, style="Txt.Field"):
    box = TextBox()
    box.Tag = tag
    styled(box, style)
    if width:
        box.Width = width
    return box


def button(content, style="Btn.Flat", margin=None, width=None):
    element = Button()
    element.Content = content
    styled(element, style)
    if margin:
        element.Margin = Thickness(*margin)
    if width:
        element.Width = width
    return element


def check_box(content, checked=False):
    box = CheckBox()
    box.Content = content
    box.IsChecked = checked
    styled(box, "Chk.Flat")
    return box


def combo(items, selected=None, width=None):
    box = ComboBox()
    styled(box, "Cmb.Flat")
    for item in items:
        entry = ComboBoxItem()
        entry.Content = item
        styled(entry, "Cmb.Item")
        box.Items.Add(entry)
    if width:
        box.Width = width
    if selected is not None:
        for index, item in enumerate(items):
            if item == selected:
                box.SelectedIndex = index
                break
        if box.SelectedIndex < 0 and box.Items.Count:
            box.SelectedIndex = 0
    elif box.Items.Count:
        box.SelectedIndex = 0
    return box


def combo_text(box):
    try:
        item = box.SelectedItem
        if item is None:
            return u""
        return u"{0}".format(item.Content)
    except Exception:
        return u""


class ValuePicker(object):
    """A text box with a caret that drops a searchable list.

    Two modes. Free (the default) is what the grouping value fields need: pick
    from what the project already uses, or type something new. Strict is what a
    parameter or a view template needs: the list is the only answer, so the box
    is read only and clicking it opens the list. Either way the popup carries
    its own keyword search, because a project with two hundred sheet parameters
    in it is not a list anybody wants to scroll.
    """

    def __init__(self, values, text=u"", width=None, placeholder=None,
                 strict=False, on_pick=None):
        self.values = list(values)
        self.strict = strict
        self.on_pick = on_pick
        self.root = Grid()
        self.root.ColumnDefinitions.Add(_column("*"))
        self.root.ColumnDefinitions.Add(_column("auto"))
        if width:
            self.root.Width = width

        if placeholder is None:
            placeholder = u"pick one" if strict else u"type a value or pick one"
        self.box = text_box(placeholder)
        self.box.Text = text
        if strict:
            self.box.IsReadOnly = True
            self.box.Cursor = _hand()
            self.box.PreviewMouseLeftButtonDown += ui_safe(self._open)
        Grid.SetColumn(self.box, 0)
        self.root.Children.Add(self.box)

        self.caret = button(u"\u25BE", "Btn.Flat", (4, 0, 0, 0), 30)
        Grid.SetColumn(self.caret, 1)
        self.root.Children.Add(self.caret)

        self.popup = Popup()
        self.popup.Placement = PlacementMode.Bottom
        self.popup.PlacementTarget = self.box
        self.popup.StaysOpen = False
        self.popup.AllowsTransparency = True

        shell = Border()
        shell.SetResourceReference(Border.BackgroundProperty, "CardBg")
        shell.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush")
        shell.BorderThickness = Thickness(1)
        shell.CornerRadius = _corner(3)
        shell.MinWidth = 240
        shell.Padding = Thickness(6)

        body = StackPanel()
        self.search = text_box(u"search", None, "Txt.Small")
        body.Children.Add(self.search)

        self.list = ListBox()
        styled(self.list, "Lst.Flat")
        self.list.MaxHeight = 260
        self.list.Margin = Thickness(0, 6, 0, 0)
        body.Children.Add(self.list)
        shell.Child = body
        self.popup.Child = shell
        self.root.Children.Add(self.popup)

        self.caret.Click += ui_safe(self._open)
        self.list.SelectionChanged += ui_safe(self._pick)
        self.search.TextChanged += ui_safe(self._typed)
        self.fill()

    def fill(self, needle=u""):
        self.list.Items.Clear()
        needle = (needle or u"").strip().lower()
        for value in self.values:
            label = u"{0}".format(value)
            if needle and needle not in label.lower():
                continue
            item = ListBoxItem()
            item.Content = label
            styled(item, "Lst.Item")
            self.list.Items.Add(item)
        if not self.list.Items.Count:
            item = ListBoxItem()
            item.Content = u"nothing matches that"
            item.IsEnabled = False
            styled(item, "Lst.Item")
            self.list.Items.Add(item)

    def set_values(self, values, keep=True):
        held = self.text
        self.values = list(values)
        self.fill(self.search.Text or u"")
        if keep and held in self.values:
            self.box.Text = held
        elif keep and not self.strict:
            self.box.Text = held
        else:
            self.box.Text = u""

    @ui_safe
    def _open(self, sender, event):
        self.popup.IsOpen = not self.popup.IsOpen
        if self.popup.IsOpen:
            self.search.Text = u""
            self.fill()
            try:
                self.search.Focus()
            except Exception:
                pass

    @ui_safe
    def _typed(self, sender, event):
        self.fill(sender.Text or u"")

    @ui_safe
    def _pick(self, sender, event):
        item = self.list.SelectedItem
        if item is not None and item.IsEnabled:
            self.box.Text = u"{0}".format(item.Content)
            if self.on_pick is not None:
                self.on_pick(self.box.Text)
        self.popup.IsOpen = False
        self.list.SelectedIndex = -1

    @property
    def text(self):
        return self.box.Text or u""

    def set_text(self, value):
        self.box.Text = value or u""


def _column(width):
    """A column from "auto", "*" / "2*", a number, or None (one star). Numbers
    and None are taken too: 1.9.0's template editor passed them, the helper
    threw on .endswith, and the Edit button did nothing at all."""
    definition = ColumnDefinition()
    if width is None:
        definition.Width = GridLength(1, GridUnitType.Star)
        return definition
    if isinstance(width, (int, float)):
        definition.Width = GridLength(float(width))
        return definition
    if width == "auto":
        definition.Width = GridLength(1, GridUnitType.Auto)
    elif width.endswith("*"):
        factor = width[:-1]
        definition.Width = GridLength(float(factor) if factor else 1.0,
                                      GridUnitType.Star)
    else:
        definition.Width = GridLength(float(width))
    return definition


def _row(height="auto"):
    definition = RowDefinition()
    if height == "auto":
        definition.Height = GridLength(1, GridUnitType.Auto)
    elif height.endswith("*"):
        factor = height[:-1]
        definition.Height = GridLength(float(factor) if factor else 1.0,
                                       GridUnitType.Star)
    else:
        definition.Height = GridLength(float(height))
    return definition


def job_document(uiapp, job):
    """The document a job was worked out against.

    The windows are modeless and can sit open while another project is made
    active; the element ids a job carries belong to the document it was built
    in, and used against any other they name the wrong sheets and views. So
    the job carries its document, and one that has been closed is refused
    rather than swapped for whatever happens to be active.

    Returns (document, reason) - one of them None.
    """
    document = job.get("doc")
    if document is None:
        try:
            return uiapp.ActiveUIDocument.Document, None
        except Exception:
            return None, u"no document is open"
    try:
        if not document.IsValidObject:
            return None, (u"the project this was set up in has been closed - "
                          u"nothing was written")
    except Exception:
        pass
    return document, None


def pump(dispatcher):
    """Let a window repaint while Revit is busy in an external event. Both
    argument orders of Dispatcher.Invoke exist and which one an engine binds
    to varies, so both are tried rather than assumed. Called only between
    transactions, never inside one."""
    from System import Action
    from System.Windows.Threading import DispatcherPriority

    def nothing():
        return None

    action = Action(nothing)
    try:
        dispatcher.Invoke(DispatcherPriority.Render, action)
        return True
    except Exception:
        pass
    try:
        dispatcher.Invoke(action, DispatcherPriority.Render)
        return True
    except Exception:
        return False


def solid(hex_value):
    """A brush from a hex string, for the few places a colour is fixed rather
    than a palette key - a product's own colour does not change with the
    theme."""
    from System.Windows.Media import BrushConverter
    try:
        return BrushConverter().ConvertFromString(hex_value)
    except Exception:
        from System.Windows.Media import Brushes
        return Brushes.Gray


def _hand():
    from System.Windows.Input import Cursors
    return Cursors.Hand


def _corner(radius):
    from System.Windows import CornerRadius
    return CornerRadius(radius)


def debounce(milliseconds, action):
    """One timer, restarted on every keystroke."""
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(milliseconds)

    @ui_safe
    def tick(sender, event):
        timer.Stop()
        action()

    timer.Tick += tick
    return timer


def hit_row(source):
    """Walk up the visual tree to the DataGridRow that was clicked."""
    from System.Windows.Media import VisualTreeHelper
    from System.Windows.Controls import DataGridRow
    node = source
    # bounded, and it falls back to the logical parent: VisualTreeHelper only
    # walks visuals, and the source of a click can be a content element that
    # is not one - in which case the loop used to end at the first non-visual
    # and report no row at all
    for _step in range(60):
        if node is None:
            return None
        if isinstance(node, DataGridRow):
            return node
        parent = None
        try:
            parent = VisualTreeHelper.GetParent(node)
        except Exception:
            parent = None
        if parent is None:
            try:
                parent = node.Parent
            except Exception:
                parent = None
        if parent is None:
            try:
                parent = node.TemplatedParent
            except Exception:
                parent = None
        node = parent
    return None
