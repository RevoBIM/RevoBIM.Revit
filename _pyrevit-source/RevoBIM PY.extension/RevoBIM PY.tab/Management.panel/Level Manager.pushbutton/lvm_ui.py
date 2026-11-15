# -*- coding: utf-8 -*-
"""Level Manager - XAML loading, theming, window chrome, icons and prompts.

Shared by the main window and every dialog, so they all look and behave the
same: borderless chrome, RevoBIM in blue, the tool name in orange, version
top right, shrink to taskbar, full screen by bounds, eight resize grips, and
one palette written onto each window's Resources so the theme can be swapped
on an open window.
"""
import lvm_clr  # noqa: F401
import os
import time

from System import TimeSpan
from System.IO import File, MemoryStream
from System.Windows import (
    Thickness, HorizontalAlignment, VerticalAlignment, PresentationSource,
    Visibility, SizeToContent, CornerRadius, Point, SystemParameters,
)
from System.Windows.Controls import (
    StackPanel, TextBlock, Orientation, Canvas, Viewbox, Button,
)
from System.Windows.Controls.Primitives import Thumb
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, Color, Geometry, Stretch
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Shapes import Path as WpfPath, Shape
from System.Windows.Data import Binding, RelativeSource, RelativeSourceMode
from System.Windows.Input import Cursors, Key, Keyboard, ModifierKeys
from System.Windows.Threading import DispatcherTimer
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Forms import Screen

import lvm_core as core

HERE = os.path.dirname(os.path.abspath(__file__))
to_text = core.to_text
_TEXT_CACHE = {}


def path_of(name):
    return os.path.join(HERE, name)


def read_text(name):
    if name not in _TEXT_CACHE:
        _TEXT_CACHE[name] = File.ReadAllText(path_of(name))
    return _TEXT_CACHE[name]


def load_xaml(name):
    return XamlReader.Parse(read_text(name))


# =========================================================================
# Theme
# =========================================================================

def brush(hex_text):
    r, g, b = core.hex_rgb(hex_text)
    out = SolidColorBrush(Color.FromRgb(r, g, b))
    out.Freeze()
    return out


def apply_palette(element, palette):
    """Palette brushes written straight onto the element's Resources - they
    sit in front of the merged Theme.xaml, so swapping them re-themes an open
    window with no reload and no loss of state."""
    for key, value in palette.items():
        element.Resources[key] = brush(value)


def themed(element, palette):
    """Merge Theme.xaml and the palette into an element (a window, or the
    content of a popup, which is outside the window's tree)."""
    rd = XamlReader.Parse(read_text("Theme.xaml"))
    element.Resources.MergedDictionaries.Add(rd)
    apply_palette(element, palette)
    return element


# =========================================================================
# Images and icons
# =========================================================================

def load_image(name="icon.png"):
    """From bytes, never UriSource - System.Uri moved in Revit 2025."""
    try:
        data = File.ReadAllBytes(path_of(name))
        stream = MemoryStream(data)
        img = BitmapImage()
        img.BeginInit()
        img.CacheOption = BitmapCacheOption.OnLoad
        img.StreamSource = stream
        img.EndInit()
        img.Freeze()
        return img
    except Exception:
        return None


def set_logo(image_control):
    try:
        img = load_image("icon.png")
        if img is not None:
            image_control.Source = img
    except Exception:
        pass


def line_icon(button, icon_key, label):
    """A 16-unit line icon and a label. The label TextBlock is kept on the
    button's Tag: change it with set_label, never through Content, which
    would throw the icon away."""
    panel = StackPanel()
    panel.Orientation = Orientation.Horizontal
    try:
        canvas = Canvas()
        canvas.Width = 16
        canvas.Height = 16
        path = WpfPath()
        path.Data = Geometry.Parse(core.ICONS[icon_key])
        path.StrokeThickness = 1.5
        bind = Binding("Foreground")
        bind.RelativeSource = RelativeSource(RelativeSourceMode.FindAncestor, Button, 1)
        path.SetBinding(Shape.StrokeProperty, bind)
        canvas.Children.Add(path)
        box = Viewbox()
        box.Width = 14
        box.Height = 14
        box.Stretch = Stretch.Uniform
        box.Child = canvas
        box.Margin = Thickness(0, 0, 6 if label else 0, 0)
        box.VerticalAlignment = VerticalAlignment.Center
        panel.Children.Add(box)
    except Exception:
        pass
    text = TextBlock()
    text.Text = to_text(label)
    text.VerticalAlignment = VerticalAlignment.Center
    panel.Children.Add(text)
    button.Content = panel
    button.Tag = text
    return text


def set_label(button, label):
    try:
        button.Tag.Text = to_text(label)
    except Exception:
        pass


# =========================================================================
# Owner and chrome
# =========================================================================

def set_owner(window, handle):
    try:
        WindowInteropHelper(window).Owner = handle
    except Exception:
        pass


_GRIP_TEMPLATE = (
    u'<ControlTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
    u'TargetType="Thumb"><Border Background="Transparent"/></ControlTemplate>'
)

_GRIPS = [
    # edge, horizontal, vertical, width, height, cursor
    ("L", "Left", "Stretch", 5, None, "SizeWE"),
    ("R", "Right", "Stretch", 5, None, "SizeWE"),
    ("T", "Stretch", "Top", None, 5, "SizeNS"),
    ("B", "Stretch", "Bottom", None, 5, "SizeNS"),
    ("TL", "Left", "Top", 9, 9, "SizeNWSE"),
    ("TR", "Right", "Top", 9, 9, "SizeNESW"),
    ("BL", "Left", "Bottom", 9, 9, "SizeNESW"),
    ("BR", "Right", "Bottom", 9, 9, "SizeNWSE"),
]


# =========================================================================
# Shrink to taskbar - the drawer
# =========================================================================
# Every window the tool opens has one. Pressing the shrink button slides the
# window down to the bottom of its screen like a drawer closing, leaving only
# its header bar floating above the taskbar; the button turns into a green up
# arrow that opens it again. The slide is a DispatcherTimer easing Top and
# Height together - no BeginAnimation, so nothing holds an end value that
# would block later moves and resizes.

_DRAWERS = []                       # every live drawer, for slots and owners


def _now():
    return time.time()


def _start_timer(drawer, step):
    """Run step() every 15ms until it returns False. The handler is kept on
    the drawer: a handler nothing refers to can be collected mid-slide."""
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(core.DRAWER_TICK_MS)

    def tick(sender, args):
        if not step():
            timer.Stop()

    drawer._tick = tick
    drawer._timer = timer
    timer.Tick += tick
    timer.Start()


def work_area(window):
    """(left, top, right, bottom) of the working area of the screen the
    window is on, in DIPs. A monitor above the primary has a negative top."""
    try:
        handle = WindowInteropHelper(window).Handle
        area = Screen.FromHandle(handle).WorkingArea
        sx, sy = 1.0, 1.0
        source = PresentationSource.FromVisual(window)
        if source is not None:
            m = source.CompositionTarget.TransformToDevice
            sx, sy = m.M11, m.M22
        return (area.Left / sx, area.Top / sy, area.Right / sx, area.Bottom / sy)
    except Exception:
        return (0.0, 0.0, float(SystemParameters.WorkArea.Right), float(SystemParameters.WorkArea.Bottom))


def _header_offset(header, window):
    """How far the header sits inside the window (the outer border)."""
    try:
        return float(header.TranslatePoint(Point(0, 0), window).Y)
    except Exception:
        return 1.0


def real_size(actual, declared):
    """A laid-out size, falling back to the declared one; never NaN."""
    for v in (actual, declared):
        try:
            v = float(v)
            if v == v and v > 0:
                return v
        except Exception:
            continue
    return 0.0


def open_parent(owner):
    """A dialog about to open over a parked window opens it first, so it
    does not centre itself on a bar at the bottom of the screen."""
    d = drawer_of(owner)
    if d is not None and d.state == "shrunk":
        try:
            d.expand(animate=False)
        except Exception:
            pass


def same(a, b):
    if a is b:
        return True
    if a is None or b is None:
        return False
    try:
        return bool(a.Equals(b))
    except Exception:
        return False


def drawer_of(window):
    for d in _DRAWERS:
        if same(d.window, window):
            return d
    return None


class Drawer(object):
    """open -> closing -> shrunk -> opening -> open."""

    def __init__(self, window, header, button, grips=None, shrink_glyph=None, expand_glyph=None):
        self.window = window
        self.header = header
        self.button = button
        self.grips = grips
        self.shrink_glyph = shrink_glyph
        self.expand_glyph = expand_glyph
        self.state = "open"
        self.saved = None
        self.parked = None
        self.bar = 0.0
        self.slot = None
        self.hidden = []            # [element, visibility it had]
        self.lifted = []            # drawers this one shrank with it
        self.restore = {}
        self.header_corner = None
        self._timer = None
        self._tick = None
        self._finished = None
        button.Click += self.on_click
        window.Closed += self.on_closed
        _DRAWERS.append(self)

    # ---- queries -------------------------------------------------------------
    def parked_now(self):
        return self.state != "open"

    def true_bounds(self):
        """The window's size as the user knows it - never the 50px bar."""
        w = self.window
        if self.saved is not None and self.state != "open":
            return self.saved
        return (w.Left, w.Top, w.Width, w.Height)

    def set_visibility(self, element, value):
        """Visibility changes from the tool while parked go to the stored
        value, so a progress bar cannot appear inside a parked bar and is
        still right when the window opens again."""
        for entry in self.hidden:
            if same(entry[0], element):
                entry[1] = value
                return
        element.Visibility = value

    # ---- gestures --------------------------------------------------------------
    def on_click(self, sender, args):
        self.toggle()

    def toggle(self):
        if self.state == "open":
            self.shrink()
        elif self.state == "shrunk":
            self.expand()

    def on_closed(self, sender, args):
        try:
            if self._timer is not None:
                self._timer.Stop()
        except Exception:
            pass
        try:
            _DRAWERS.remove(self)
        except ValueError:
            pass
        lifted, self.lifted = self.lifted, []
        for d in lifted:
            try:
                d.expand()
            except Exception:
                pass

    # ---- shrink ------------------------------------------------------------------
    def shrink(self, animate=True):
        if self.state != "open":
            return
        self.state = "closing"
        w = self.window
        owner = drawer_of(getattr(w, "Owner", None))
        if owner is not None and owner.state == "open":
            owner.shrink(animate=False)
            self.lifted.append(owner)
        for d in list(_DRAWERS):
            if d is not self and d.state == "open" and same(getattr(d.window, "Owner", None), w):
                d.shrink(animate=False)
                self.lifted.append(d)
        # Actual size: a SizeToContent window (the prompt) has a NaN Height
        self.saved = (w.Left, w.Top, real_size(w.ActualWidth, w.Width), real_size(w.ActualHeight, w.Height))
        self.restore = {"MinHeight": w.MinHeight, "SizeToContent": w.SizeToContent}
        w.SizeToContent = SizeToContent.Manual
        w.MinHeight = 0
        self.bar = float(self.header.ActualHeight) + 2.0 * _header_offset(self.header, w)
        area = work_area(w)
        occupied = {}
        for d in _DRAWERS:
            if d is not self and d.slot is not None:
                occupied[d.slot] = d.bar
        self.slot = core.free_slot(occupied.keys())
        top = core.shrunk_top(area[3], self.bar, core.slot_heights(self.slot, occupied, self.bar))
        self.parked = (w.Left, top)
        if self.grips is not None:
            self.grips.Visibility = Visibility.Collapsed
        w.Height = self.saved[3]
        self._pin(self.saved[3])
        self._glyphs(True)
        self._slide(w.Top, top, self.bar, self._landed, animate)

    def _landed(self):
        w = self.window
        parent = self.header.Parent
        self.hidden = []
        try:
            for child in parent.Children:
                if same(child, self.header):
                    continue
                self.hidden.append([child, child.Visibility])
                child.Visibility = Visibility.Collapsed
        except Exception:
            pass
        try:
            self.header_corner = self.header.CornerRadius
            self.header.CornerRadius = CornerRadius(6)
        except Exception:
            pass
        self._unpin()
        w.Top = self.parked[1]
        w.Height = self.bar
        self.state = "shrunk"

    # ---- expand ------------------------------------------------------------------
    def expand(self, animate=True):
        if self.state != "shrunk":
            return
        self.state = "opening"
        w = self.window
        for child, vis in self.hidden:
            try:
                child.Visibility = vis
            except Exception:
                pass
        self.hidden = []
        try:
            if self.header_corner is not None:
                self.header.CornerRadius = self.header_corner
        except Exception:
            pass
        rect = core.expand_rect(self.saved, self.parked, (w.Left, w.Top), self.bar, work_area(w))
        w.Left = rect[0]
        w.Width = rect[2]
        w.Height = rect[3]          # full height at once, below the bar; then slide up
        self._pin(rect[3])
        self._slide(w.Top, rect[1], rect[3], self._opened, animate)

    def _opened(self):
        w = self.window
        self._unpin()
        try:
            w.MinHeight = self.restore.get("MinHeight", 0)
            w.SizeToContent = self.restore.get("SizeToContent", SizeToContent.Manual)
        except Exception:
            pass
        if self.grips is not None:
            self.grips.Visibility = Visibility.Visible
        self.slot = None
        self.saved = None
        self.state = "open"
        self._glyphs(False)
        lifted, self.lifted = self.lifted, []
        for d in lifted:
            try:
                d.expand(animate=False)
            except Exception:
                pass
        try:
            w.Activate()
        except Exception:
            pass

    # ---- mechanics -----------------------------------------------------------------
    def _pin(self, height):
        """Hold the body at full height while the window slides over it, so
        it reads as a drawer being drawn away, not a window being squashed -
        and the table does not re-measure on every frame."""
        try:
            body = self.window.Content
            body.Height = float(height)
            body.VerticalAlignment = VerticalAlignment.Top
        except Exception:
            pass

    def _unpin(self):
        try:
            body = self.window.Content
            body.Height = float("nan")
            body.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    def _glyphs(self, shrunk):
        try:
            self.shrink_glyph.Visibility = Visibility.Collapsed if shrunk else Visibility.Visible
            self.expand_glyph.Visibility = Visibility.Visible if shrunk else Visibility.Collapsed
        except Exception:
            pass
        try:
            self.button.ToolTip = (u"Open the window again (Esc, Enter or double-click the bar)"
                                   if shrunk else u"Shrink to the taskbar so Revit can be seen (Ctrl+Shift+H)")
        except Exception:
            pass

    def _slide(self, top0, top1, height1, done, animate=True):
        """Slide Top only; the height is set once at the end (shrinking) or
        once at the start (opening). Moving Top and Height every frame is two
        window moves per frame and makes the bottom edge flicker. A frame
        that throws lands the window at the end state, never half way."""
        w = self.window
        state = {"done": False}

        def finish():
            if state["done"]:
                return
            state["done"] = True
            try:
                w.Top = top1
                w.Height = height1
            except Exception:
                pass
            done()

        if not animate:
            finish()
            return
        t0 = _now()

        def step():
            try:
                p = (_now() - t0) / core.DRAWER_SECONDS
                if p >= 1.0:
                    finish()
                    return False
                w.Top = core.frame_at((top0, 0.0), (top1, 0.0), p)[0]
                return True
            except Exception:
                finish()
                return False

        try:
            _start_timer(self, step)
        except Exception:
            finish()


# =========================================================================
# Chrome
# =========================================================================

class Chrome(object):
    """Drag by the header, double-click or F11 for full screen, the shrink
    drawer, the close button, and eight resize grips - a borderless
    AllowsTransparency window gets none of these from WPF."""

    def __init__(self, window, header, close_btn, full_btn=None, grips=None,
                 full_glyph=None, shrink_btn=None):
        self.window = window
        self.full = False
        self.saved = None
        self.full_glyph = full_glyph
        self.has_full = full_btn is not None
        self.drawer = None
        if shrink_btn is not None:
            self.drawer = Drawer(window, header, shrink_btn, grips,
                                 window.FindName("ShrinkGlyph"), window.FindName("ExpandGlyph"))
        header.MouseLeftButtonDown += self._header_down
        close_btn.Click += self._close
        if full_btn is not None:
            full_btn.Click += self._full_click
        window.PreviewKeyDown += self._key
        if grips is not None:
            self._add_grips(grips)

    def parked(self):
        return self.drawer is not None and self.drawer.parked_now()

    def true_bounds(self):
        # full screen first: a full-screen window that is then parked would
        # otherwise save the screen-sized rectangle as its size
        if self.full and self.saved is not None:
            return self.saved
        if self.drawer is not None and self.drawer.parked_now():
            return self.drawer.true_bounds()
        w = self.window
        return (w.Left, w.Top, w.Width, w.Height)

    def _close(self, sender, args):
        self.window.Close()

    def _full_click(self, sender, args):
        self.toggle_full()

    def _key(self, sender, args):
        try:
            mods = Keyboard.Modifiers
            ctrl_shift = (mods & ModifierKeys.Control) == ModifierKeys.Control and \
                         (mods & ModifierKeys.Shift) == ModifierKeys.Shift
            if self.drawer is not None and ctrl_shift and args.Key == Key.H:
                self.drawer.toggle()
                args.Handled = True
                return
            if self.parked():
                # parked: Esc, Enter and F11 open it again rather than closing
                # a dialog or filling the screen with a window nobody can see
                if args.Key in (Key.Escape, Key.Enter, Key.Return, Key.F11):
                    self.drawer.expand()
                args.Handled = True
                return
            if args.Key == Key.F11 and self.has_full:
                self.toggle_full()
                args.Handled = True
        except Exception:
            pass

    def _header_down(self, sender, args):
        try:
            if self.parked():
                if args.ClickCount == 2:
                    self.drawer.expand()
                    args.Handled = True
                    return
                self.window.DragMove()
                return
            if args.ClickCount == 2 and self.full_glyph is not None:
                self.toggle_full()
                args.Handled = True
                return
            if self.full:
                self._leave_full()
            self.window.DragMove()
        except Exception:
            pass

    def toggle_full(self):
        if self.parked():
            self.drawer.expand()
            return
        if self.full:
            self._leave_full()
        else:
            self._enter_full()

    def _enter_full(self):
        w = self.window
        self.saved = (w.Left, w.Top, w.Width, w.Height)
        try:
            left, top, right, bottom = work_area(w)
            w.Left = left
            w.Top = top
            w.Width = right - left
            w.Height = bottom - top
            self.full = True
            self._glyph()
        except Exception:
            self.saved = None

    def _leave_full(self):
        if self.saved is not None:
            left, top, width, height = self.saved
            w = self.window
            w.Width = width
            w.Height = height
            w.Left = left
            w.Top = top
        self.full = False
        self._glyph()

    def _glyph(self):
        if self.full_glyph is None:
            return
        try:
            self.full_glyph.Width = 9 if self.full else 11
            self.full_glyph.Height = 9 if self.full else 11
        except Exception:
            pass

    def _add_grips(self, grid):
        template = XamlReader.Parse(_GRIP_TEMPLATE)
        for edge, h, v, width, height, cursor in _GRIPS:
            th = Thumb()
            th.Template = template
            th.HorizontalAlignment = getattr(HorizontalAlignment, h)
            th.VerticalAlignment = getattr(VerticalAlignment, v)
            if width is not None:
                th.Width = width
            if height is not None:
                th.Height = height
            th.Cursor = getattr(Cursors, cursor)
            th.DragDelta += self._make_drag(edge)
            grid.Children.Add(th)

    def _make_drag(self, edge):
        def handler(sender, args):
            self._drag(edge, args.HorizontalChange, args.VerticalChange)
        return handler

    def _drag(self, edge, dx, dy):
        w = self.window
        if self.parked():
            return
        if self.full:
            self.full = False
            self._glyph()
        if "R" in edge:
            w.Width = max(w.MinWidth, w.Width + dx)
        if "B" in edge:
            w.Height = max(w.MinHeight, w.Height + dy)
        if "L" in edge:
            new_w = max(w.MinWidth, w.Width - dx)
            w.Left = w.Left + (w.Width - new_w)
            w.Width = new_w
        if "T" in edge:
            new_h = max(w.MinHeight, w.Height - dy)
            w.Top = w.Top + (w.Height - new_h)
            w.Height = new_h


def dialog_chrome(window, palette, version=True):
    """Theme a child dialog and wire its header and close button."""
    themed(window, palette)
    try:
        set_logo(window.FindName("Logo"))
    except Exception:
        pass
    if version:
        try:
            window.FindName("VersionTxt").Text = u"v" + core.__version__
        except Exception:
            pass
    return Chrome(window, window.FindName("Header"), window.FindName("CloseBtn"),
                  shrink_btn=window.FindName("ShrinkBtn"))


# =========================================================================
# Prompt
# =========================================================================

def ask(owner, palette, body, yes_text=u"Continue", no_text=u"Cancel", title=u"Level Manager"):
    win = load_xaml("Prompt.xaml")
    dialog_chrome(win, palette)
    try:
        win.FindName("TitleTxt").Text = to_text(title)
    except Exception:
        pass
    win.FindName("BodyTxt").Text = to_text(body)
    yes = win.FindName("YesBtn")
    no = win.FindName("NoBtn")
    yes.Content = to_text(yes_text)
    no.Content = to_text(no_text)
    answer = [False]

    def on_yes(sender, args):
        answer[0] = True
        win.Close()

    def on_no(sender, args):
        win.Close()

    yes.Click += on_yes
    no.Click += on_no
    try:
        open_parent(owner)
        win.Owner = owner
    except Exception:
        pass
    win.ShowDialog()
    return answer[0]


# =========================================================================
# Easter egg - three slow clicks on the logo
# =========================================================================

def wire_egg(window, logo, theme_name):
    """Pacman opens only on three slow clicks of the logo, top left.

    The shared egg_hook.attach is deliberately NOT used here: it arms the
    whole window, so clicks elsewhere (a header, a row, an arrow) counted
    towards the game. This counts on the logo itself; any click anywhere else
    in the window starts the count again.
    """
    counter = core.LogoClicks()

    def fire():
        try:
            from revobim.egg import egg_hook
            egg_hook.launch(window, theme_name(), "pacman")
        except Exception:
            pass

    def on_logo(sender, args):
        try:
            if counter.click(args.Timestamp):
                fire()
            args.Handled = True         # not a header drag or a double-click full screen
        except Exception:
            pass

    def on_window(sender, args):
        try:
            if not logo.Equals(args.OriginalSource):
                counter.reset()
        except Exception:
            pass

    try:
        logo.MouseLeftButtonDown += on_logo
        window.PreviewMouseLeftButtonDown += on_window
    except Exception:
        pass
    return counter
