# -*- coding: utf-8 -*-
"""Schematic Builder - WPF plumbing shared by every window.

Every window the tool opens is built by ``open_window``: layout parsed,
Theme.xaml merged, palette applied, version shown, owner set, and a
``Chrome`` attached that finds the header controls by name - drag, close,
full screen, the eight resize grips and the shrink-to-taskbar drawer. One
construction path is what keeps every window behaving the same, and the
bench fails if any window is built another way.

XAML is parsed with XamlReader.Parse and Theme.xaml merged in afterwards, so
layout files may only use DynamicResource. The palette is written straight
onto window.Resources, which sits in front of the merged dictionary, so it
can be swapped on an open window.
"""
import sb_clr  # noqa: F401

import io
import os

import theme
from sb_logic import (as_text, keyword_matches, drawer_park, drawer_reopen, __version__)

from System import Diagnostics, Predicate, Double, TimeSpan  # noqa: E402
from System.Windows import (  # noqa: E402
    Window, FrameworkElement, Thickness, GridLength, GridUnitType, Duration,
    VerticalAlignment, Visibility, WindowStartupLocation, SizeToContent,
)
from System.Windows.Controls import (  # noqa: E402
    Grid, ColumnDefinition, TextBlock, TextBox, Button, ComboBox,
    CheckBox, ListBoxItem, Control,
    TextChangedEventHandler,
)
from System.Windows.Controls.Primitives import TextBoxBase  # noqa: E402
from System.Windows.Interop import WindowInteropHelper  # noqa: E402
from System.Windows.Markup import XamlReader  # noqa: E402
from System.Windows.Media import SolidColorBrush, Color  # noqa: E402
from System.Windows.Media.Animation import DoubleAnimation, CubicEase, EasingMode  # noqa: E402
from System.Windows.Input import Key, Keyboard, ModifierKeys  # noqa: E402
from System.Windows.Forms import Screen  # noqa: E402

HERE = os.path.dirname(__file__)
THEME_FILE = os.path.join(HERE, "Theme.xaml")

OPEN_WINDOWS = []       # every live window, so a theme change can repaint them all
DRAWERS = {}            # window -> its WindowDrawer, so a dialog can find its owner's


# ---------------------------------------------------------------------------
# LOADING AND PALETTE
# ---------------------------------------------------------------------------

def read_file(path):
    handle = io.open(path, "r", encoding="utf-8")
    text = handle.read()
    handle.close()
    return text


def load_window(layout_name, palette_name):
    """Parse a layout, merge Theme.xaml, apply the palette. Called only by
    open_window - anything else would be a window without its chrome."""
    window = XamlReader.Parse(read_file(os.path.join(HERE, layout_name)))
    window.Resources.MergedDictionaries.Add(XamlReader.Parse(read_file(THEME_FILE)))
    apply_palette(window, palette_name)
    return window


def hex_brush(hex_text):
    text = as_text(hex_text).lstrip(u"#")
    return SolidColorBrush(Color.FromArgb(255, int(text[0:2], 16), int(text[2:4], 16),
                                          int(text[4:6], 16)))


def apply_palette(window, palette_name):
    colours = theme.palette(palette_name)
    for key in colours:
        window.Resources[key] = hex_brush(colours[key])


def canvas_theme():
    """Revit's canvas theme, 'dark' or 'light', or None where it cannot be
    read (UIThemeManager arrived in Revit 2024). UITheme.Dark is 0, so the
    read is compared, never tested for truth."""
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, "UIThemeManager", None)
        ui_theme = getattr(revit_ui, "UITheme", None)
        if manager is None or ui_theme is None:
            return None
        current = manager.CurrentCanvasTheme
        if current is None:
            return None
        return "dark" if current == getattr(ui_theme, "Dark") else "light"
    except Exception:
        return None


def palette_for(settings):
    """The palette a window should use right now, from the theme setting."""
    return theme.resolve(settings.get("theme"), canvas_theme())


def repaint_all(palette_name):
    """Swap the palette on every open window of the tool."""
    for window in list(OPEN_WINDOWS):
        try:
            apply_palette(window, palette_name)
        except Exception:
            pass


def set_style(element, key):
    element.SetResourceReference(FrameworkElement.StyleProperty, key)
    return element


def colour(element, key):
    """Point an element's Foreground at a palette brush, so it follows a
    theme switch. Works for a TextBlock and for any Control."""
    prop = TextBlock.ForegroundProperty if isinstance(element, TextBlock) else Control.ForegroundProperty
    element.SetResourceReference(prop, key)
    return element


def own_to_revit(window):
    try:
        WindowInteropHelper(window).Owner = Diagnostics.Process.GetCurrentProcess().MainWindowHandle
    except Exception:
        pass


def is_parked(window):
    drawer = DRAWERS.get(window)
    return drawer is not None and drawer.parked


def set_owner(window, owner):
    """Own a window to another of ours, or to Revit. A dialog that opens
    while its owner is parked centres on the screen instead - centred on a
    50px bar at the bottom of the screen most of it would be off it."""
    if owner is None:
        own_to_revit(window)
        return
    try:
        window.Owner = owner
        window.WindowStartupLocation = (WindowStartupLocation.CenterScreen if is_parked(owner)
                                        else WindowStartupLocation.CenterOwner)
    except Exception:
        own_to_revit(window)


def open_window(layout_name, palette_name, owner=None, modal=True, close_on_escape=False):
    """The one way a window is built. Returns (window, find, chrome)."""
    window = load_window(layout_name, palette_name)
    version = window.FindName("TxtVersion")
    if version is not None:
        version.Text = u"v{0}".format(__version__)
    set_owner(window, owner)
    chrome = Chrome(window, close_on_escape=close_on_escape, modal=modal and owner is not None)
    OPEN_WINDOWS.append(window)

    def forget(sender, args):
        try:
            OPEN_WINDOWS.remove(window)
        except ValueError:
            pass
    window.Closed += forget
    return window, window.FindName, chrome


# ---------------------------------------------------------------------------
# CHROME: drag, close, full screen, resize grips, the drawer
# ---------------------------------------------------------------------------

class Chrome(object):
    """Everything a borderless window needs, found by name: HeaderBar,
    BtnClose, BtnFull, BtnShrink and the eight Grip thumbs. WPF cannot resize
    a transparent window, hence the grips; full screen is by bounds, not
    WindowState, which covers the taskbar and picks the wrong monitor."""

    GRIPS = ("GripN", "GripS", "GripE", "GripW", "GripNE", "GripNW", "GripSE", "GripSW")

    def __init__(self, window, close_on_escape=False, modal=False):
        self.window = window
        self.saved_bounds = None
        self.full = False
        self.close_on_escape = close_on_escape
        self.header = window.FindName("HeaderBar")
        if self.header is not None:
            self.header.MouseLeftButtonDown += self.on_header_down
        close_button = window.FindName("BtnClose")
        if close_button is not None:
            close_button.Click += self.on_close
        full_button = window.FindName("BtnFull")
        if full_button is not None:
            full_button.Click += self.on_full
        window.PreviewKeyDown += self.on_key
        for name in self.GRIPS:
            grip = window.FindName(name)
            if grip is not None:
                grip.DragDelta += self.make_grip(name)
                grip.DragStarted += self.on_grip_started
        self.drawer = None
        shrink_button = window.FindName("BtnShrink")
        if shrink_button is not None and self.header is not None:
            self.drawer = WindowDrawer(self, shrink_button, modal)

    # -- geometry ------------------------------------------------------------

    def dpi(self):
        try:
            from System.Windows import PresentationSource
            matrix = PresentationSource.FromVisual(self.window).CompositionTarget.TransformToDevice
            return matrix.M11, matrix.M22
        except Exception:
            return 1.0, 1.0

    def work_area(self):
        """(left, top, right, bottom) of the screen the window is on, in DIPs.
        Negative values are real - a monitor left of or above the primary."""
        window = self.window
        scale_x, scale_y = self.dpi()
        try:
            from System.Drawing import Point
            height = window.ActualHeight or window.Height
            centre = Point(int((window.Left + window.Width / 2.0) * scale_x),
                           int((window.Top + height / 2.0) * scale_y))
            area = Screen.FromPoint(centre).WorkingArea
            return (area.Left / scale_x, area.Top / scale_y,
                    area.Right / scale_x, area.Bottom / scale_y)
        except Exception:
            return (0.0, 0.0, 1920.0, 1040.0)

    def show_grips(self, visible):
        for name in self.GRIPS:
            grip = self.window.FindName(name)
            if grip is not None:
                grip.Visibility = Visibility.Visible if visible else Visibility.Collapsed

    # -- events --------------------------------------------------------------

    def parked(self):
        return self.drawer is not None and self.drawer.parked

    def on_header_down(self, sender, args):
        try:
            if args.ClickCount == 2:
                if self.parked():
                    self.drawer.reopen()        # a parked bar reopens, never maximises
                else:
                    self.toggle_full()
                return
            if self.full:
                self.leave_full()
            self.window.DragMove()
        except Exception:
            pass

    def on_close(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def on_full(self, sender, args):
        if self.parked():
            self.drawer.reopen()
        else:
            self.toggle_full()

    def on_key(self, sender, args):
        try:
            key = args.Key
            ctrl_shift = ModifierKeys.Control | ModifierKeys.Shift
            if key == Key.H and (Keyboard.Modifiers & ctrl_shift) == ctrl_shift:
                if self.drawer is not None:
                    self.drawer.toggle()
                    args.Handled = True
                return
            if self.parked():
                # Escape, Enter and F11 bring a parked window back rather than
                # closing it, submitting it, or filling the screen with it
                if key in (Key.Escape, Key.Return, Key.F11):
                    self.drawer.reopen()
                    args.Handled = True
                return
            if key == Key.F11:
                self.toggle_full()
                args.Handled = True
            elif key == Key.Escape:
                if self.full:
                    self.leave_full()
                    args.Handled = True
                elif self.close_on_escape:
                    self.window.Close()
        except Exception:
            pass

    # -- full screen ---------------------------------------------------------

    def toggle_full(self):
        if self.full:
            self.leave_full()
        else:
            self.enter_full()

    def enter_full(self):
        window = self.window
        try:
            self.saved_bounds = (window.Left, window.Top, window.Width, window.Height)
            left, top, right, bottom = self.work_area()
            window.Left, window.Top = left, top
            window.Width, window.Height = right - left, bottom - top
            self.full = True
        except Exception:
            self.full = False

    def leave_full(self):
        if not self.full:
            return
        try:
            window = self.window
            window.Left, window.Top, window.Width, window.Height = self.saved_bounds
        except Exception:
            pass
        self.full = False

    # -- grips ---------------------------------------------------------------

    def on_grip_started(self, sender, args):
        if self.full:
            self.leave_full()

    def make_grip(self, name):
        window = self.window

        def handler(sender, args):
            try:
                dx = args.HorizontalChange
                dy = args.VerticalChange
                min_w = window.MinWidth or 300
                min_h = window.MinHeight or 200
                if "E" in name:
                    window.Width = max(min_w, window.Width + dx)
                if "S" in name:
                    window.Height = max(min_h, window.Height + dy)
                if "W" in name:
                    new_w = max(min_w, window.Width - dx)
                    window.Left += window.Width - new_w
                    window.Width = new_w
                if "N" in name:
                    new_h = max(min_h, window.Height - dy)
                    window.Top += window.Height - new_h
                    window.Height = new_h
            except Exception:
                pass
        return handler


class WindowDrawer(object):
    """Shrink a window to the bottom of the screen, leaving its header bar
    floating clear of the taskbar so Revit can be seen; the shrink button
    turns into a green up arrow (Tag="shrunk") that opens it again.

    Four things here fail silently if they are got wrong, so each is done
    on purpose: the animations are released when the slide ends (an
    animation outranks every later assignment, so a window left holding one
    can never be moved or resized again); MinHeight and SizeToContent are
    relaxed for the slide (either vetoes a Height animation half way); the
    body is pinned to its height so it is clipped like a drawer instead of
    re-laid out every frame; and the resize grips are parked, or they line
    the bar with invisible handles that swallow the click on the arrow.

    A modal dialog that is shrunk takes its owner down with it, stacked
    beneath, and brings it back when it reopens or closes - otherwise the
    owner just sits over Revit and shrinking the dialog shows nothing.
    """

    DURATION_MS = 260

    def __init__(self, chrome, button, modal=False):
        self.chrome = chrome
        self.window = chrome.window
        self.button = button
        self.modal = modal
        self.parked = False
        self.sliding = False
        self.saved = None
        self.parked_at = None
        self.saved_min_height = 0.0
        self.owner_drawer = None
        button.Click += self.on_click
        DRAWERS[self.window] = self
        self.window.Closed += self.on_closed
        self.mark(False)

    def on_click(self, sender, args):
        self.toggle()

    def on_closed(self, sender, args):
        DRAWERS.pop(self.window, None)
        if self.owner_drawer is not None and self.owner_drawer.parked:
            self.owner_drawer.reopen()
        self.owner_drawer = None

    def mark(self, parked):
        try:
            self.button.Tag = u"shrunk" if parked else u""
            self.button.ToolTip = (u"Bring the window back (Ctrl+Shift+H)" if parked
                                   else u"Shrink to the bottom of the screen (Ctrl+Shift+H)")
        except Exception:
            pass

    def toggle(self):
        if self.sliding:
            return
        if self.parked:
            self.reopen()
        else:
            self.shrink()

    def bar_height(self):
        try:
            height = self.chrome.header.ActualHeight
            if height > 0:
                return height + 2.0         # the window's 1px edge, top and bottom
        except Exception:
            pass
        return 52.0

    def shrink(self, slot=0):
        if self.parked or self.sliding:
            return
        window = self.window
        if self.chrome.full:
            self.chrome.leave_full()
        if self.modal:
            owner = DRAWERS.get(window.Owner) if window.Owner is not None else None
            if owner is not None and not owner.parked:
                owner.shrink(slot)              # the owner's bar sits beneath
                self.owner_drawer = owner
                slot += 1
        self.saved = (window.Left, window.Top, window.Width, window.ActualHeight)
        self.saved_min_height = window.MinHeight
        try:
            window.SizeToContent = SizeToContent.Manual
            window.MinHeight = 0
        except Exception:
            pass
        self.pin(True)
        self.chrome.show_grips(False)
        target = drawer_park(self.saved, self.chrome.work_area(), self.bar_height(), slot)
        self.parked_at = target
        self.parked = True
        self.mark(True)
        self.slide(target, None)

    def reopen(self):
        if not self.parked or self.sliding:
            return
        window = self.window
        now = (window.Left, window.Top, window.Width, window.ActualHeight)
        target = drawer_reopen(now, self.parked_at, self.saved, self.chrome.work_area())
        self.parked = False
        self.mark(False)
        self.slide(target, self.opened)
        owner = self.owner_drawer
        self.owner_drawer = None
        if owner is not None and owner.parked:
            owner.reopen()
            try:
                window.Activate()               # keep the dialog in front of its owner
            except Exception:
                pass

    def opened(self):
        self.pin(False)
        try:
            self.window.MinHeight = self.saved_min_height
        except Exception:
            pass
        self.chrome.show_grips(True)

    def pin(self, on):
        """Hold the body at its height while the window slides, so it is
        clipped like a drawer rather than squashed; free it afterwards."""
        body = self.window.Content
        try:
            if on:
                body.Height = body.ActualHeight
                body.VerticalAlignment = VerticalAlignment.Top
            else:
                body.Height = Double.NaN
                body.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    def slide(self, target, done):
        """Animate Top and Height to the target, then release both animations
        and write the final numbers. The same finish runs straight away if
        the animation cannot start, so the window always lands."""
        window = self.window
        left, top, width, height = target
        self.sliding = True
        state = {"finished": False}

        def finish(*args):
            if state["finished"]:
                return
            state["finished"] = True
            try:
                window.BeginAnimation(Window.TopProperty, None)
                window.BeginAnimation(Window.HeightProperty, None)
            except Exception:
                pass
            try:
                window.Left, window.Top = left, top
                window.Width, window.Height = width, height
            except Exception:
                pass
            self.sliding = False
            if done is not None:
                try:
                    done()
                except Exception:
                    pass

        try:
            window.Left, window.Width = left, width
            duration = Duration(TimeSpan.FromMilliseconds(self.DURATION_MS))
            ease = CubicEase()
            ease.EasingMode = EasingMode.EaseInOut
            move = DoubleAnimation(window.Top, top, duration)
            move.EasingFunction = ease
            size = DoubleAnimation(window.ActualHeight, height, duration)
            size.EasingFunction = ease
            size.Completed += finish
            window.BeginAnimation(Window.TopProperty, move)
            window.BeginAnimation(Window.HeightProperty, size)
        except Exception:
            finish()


# ---------------------------------------------------------------------------
# ELEMENT FACTORIES (rows built in code, never bound to Python objects)
# ---------------------------------------------------------------------------

def star(value=1.0):
    return GridLength(float(value), GridUnitType.Star)


def pixels(value):
    return GridLength(float(value), GridUnitType.Pixel)


def grid(columns):
    """columns: list of GridLength (or numbers = stars)."""
    element = Grid()
    for col in columns:
        definition = ColumnDefinition()
        definition.Width = col if isinstance(col, GridLength) else star(col)
        element.ColumnDefinitions.Add(definition)
    return element


def place(parent, element, column=0, row=None):
    Grid.SetColumn(element, int(column))
    if row is not None:
        Grid.SetRow(element, int(row))
    parent.Children.Add(element)
    return element


def label(text, style=None, dim=False, margin=None, trim=True):
    element = TextBlock()
    element.Text = as_text(text)
    element.VerticalAlignment = VerticalAlignment.Center
    if trim:
        from System.Windows import TextTrimming
        element.TextTrimming = TextTrimming.CharacterEllipsis
    if style:
        set_style(element, style)
    elif dim:
        set_style(element, "Dim")
    if margin is not None:
        element.Margin = Thickness(*margin)
    return element


def field(text=u"", placeholder=u"", margin=None):
    element = TextBox()
    set_style(element, "Field")
    element.Text = as_text(text)
    element.Tag = as_text(placeholder)
    element.VerticalAlignment = VerticalAlignment.Center
    if margin is not None:
        element.Margin = Thickness(*margin)
    return element


def button(text, style="Btn", margin=None, width=None):
    element = Button()
    set_style(element, style)
    element.Content = as_text(text)
    element.VerticalAlignment = VerticalAlignment.Center
    if margin is not None:
        element.Margin = Thickness(*margin)
    if width is not None:
        element.Width = float(width)
    return element


def combo(items, selected=None, placeholder=u"", editable=False, margin=None, search=False):
    element = ComboBox()
    set_style(element, "Combo")
    element.Tag = as_text(placeholder)
    element.IsEditable = bool(editable)
    element.VerticalAlignment = VerticalAlignment.Center
    for item in items:
        element.Items.Add(as_text(item))
    if selected is not None:
        select_text(element, selected)
    if margin is not None:
        element.Margin = Thickness(*margin)
    if search and editable:
        searchable(element, items)
    return element


# every searchable combo and the state of its search, so re-wiring one does
# not stack a second handler on it
SEARCH_STATE = {}


def searchable(combo_box, items):
    """Make an editable combo searchable.

    How it behaves, deliberately:

    - the drop-down opens **only when it is clicked**, never on its own;
    - opening it always shows **every** value, whatever is in the box - so
      picking an entry, whose name then sits in the box, does not leave the
      next open showing that one entry;
    - typing **filters the list in place** while it is open. Every word typed
      has to appear somewhere in the entry, so "bgl mark" finds
      "BGL_Instance Mark" and word order does not matter;
    - a name that is in no list can still be typed and is kept.

    The filtering is done with ``Items.Filter``, which hides entries in the
    view rather than removing them. Rebuilding ``Items`` on every keystroke -
    what this used to do - raises ``SelectionChanged`` on each rebuild, which
    every caller with a SelectionChanged handler then acts on, and fights the
    text box for the caret.
    """
    state = SEARCH_STATE.get(combo_box)
    if state is not None:
        state["items"] = [as_text(i) for i in items]
        clear_filter(combo_box)
        return combo_box
    state = {"text": u""}
    SEARCH_STATE[combo_box] = state

    def on_text(sender, args):
        try:
            text = as_text(editor_text(combo_box))
            if text == state["text"]:
                return
            state["text"] = text
            apply_filter(combo_box, text)
        except Exception:
            pass

    def on_open(sender, args):
        # clicked open: show the lot, whatever is sitting in the box
        try:
            state["text"] = as_text(editor_text(combo_box))
            clear_filter(combo_box)
        except Exception:
            pass

    def on_close(sender, args):
        try:
            state["text"] = as_text(editor_text(combo_box))
            clear_filter(combo_box)
        except Exception:
            pass

    try:
        combo_box.AddHandler(TextBoxBase.TextChangedEvent, TextChangedEventHandler(on_text))
        combo_box.DropDownOpened += on_open
        combo_box.DropDownClosed += on_close
    except Exception:
        pass
    return combo_box


def editor(combo_box):
    try:
        return combo_box.Template.FindName("PART_EditableTextBox", combo_box)
    except Exception:
        return None


def editor_text(combo_box):
    box = editor(combo_box)
    if box is not None:
        return as_text(box.Text)
    return as_text(combo_box.Text)


def apply_filter(combo_box, text):
    """Hide the entries that do not match, leaving the list itself alone."""
    words = [w for w in as_text(text).lower().split() if w]
    if not words:
        clear_filter(combo_box)
        return

    def match(item):
        try:
            return keyword_matches([as_text(item)], text) != []
        except Exception:
            return True
    try:
        combo_box.Items.Filter = Predicate[object](match)
    except Exception:
        pass


def clear_filter(combo_box):
    try:
        combo_box.Items.Filter = None
    except Exception:
        pass
    return combo_box


def refill_searchable(combo_box, items, keep=u""):
    """Give a searchable combo a different list (another category was picked).

    The items really are replaced here, so this is the one place a caller's
    SelectionChanged can fire from a refill - hence the caller-side guards."""
    clear_filter(combo_box)
    combo_box.Items.Clear()
    for item in items:
        combo_box.Items.Add(as_text(item))
    searchable(combo_box, items)
    if keep:
        select_text(combo_box, keep)
    else:
        try:
            combo_box.SelectedIndex = -1
            box = editor(combo_box)
            if box is not None:
                box.Text = u""
        except Exception:
            pass
    state = SEARCH_STATE.get(combo_box)
    if state is not None:
        state["text"] = as_text(editor_text(combo_box))
    return combo_box


def select_text(combo_box, text):
    """Pick the entry of that name, or put the text in an editable combo."""
    text = as_text(text)
    for index in range(combo_box.Items.Count):
        if as_text(combo_box.Items[index]) == text:
            combo_box.SelectedIndex = index
            return True
    if combo_box.IsEditable:
        combo_box.Text = text
        return bool(text)
    return False


def combo_text(combo_box):
    """The chosen item, or the typed text for an editable combo."""
    try:
        if combo_box.IsEditable:
            typed = as_text(editor_text(combo_box)).strip()
            if typed:
                return typed
            return as_text(combo_box.Text).strip()
        item = combo_box.SelectedItem
        return as_text(item).strip() if item is not None else u""
    except Exception:
        return u""


def check(text, checked=False, margin=None):
    element = CheckBox()
    set_style(element, "Check")
    element.Content = as_text(text)
    element.IsChecked = bool(checked)
    element.VerticalAlignment = VerticalAlignment.Center
    if margin is not None:
        element.Margin = Thickness(*margin)
    return element


def list_item(content):
    element = ListBoxItem()
    element.Content = content
    return element


def tooltip(element, text):
    try:
        element.ToolTip = as_text(text)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# MESSAGE / CONFIRM WINDOW
# ---------------------------------------------------------------------------

# modeless message windows are parked here, or the engine collects them
OPEN_MESSAGES = []


def show_message(owner, palette_name, title, body, confirm=False, subtitle=u"", modeless=False):
    """Themed message box.

    Modal returns True for OK/Yes and False for Cancel/No, and - like every
    WPF modal dialog - disables Revit until it is answered. A window that only
    reports something should be raised modeless instead, so Revit stays usable
    while it is on screen; it returns None straight away."""
    modal = confirm or not modeless
    window, find, chrome = open_window("SbMessage.xaml", palette_name, owner, modal=modal,
                                       close_on_escape=True)
    result = {"ok": False}
    find("TxtTitle").Text = as_text(title)
    find("TxtSubtitle").Text = as_text(subtitle)
    find("TxtBody").Text = as_text(body)
    ok_button = find("BtnOk")
    cancel_button = find("BtnCancel")
    ok_button.Content = u"Yes" if confirm else u"OK"
    cancel_button.Content = u"No"
    cancel_button.Visibility = Visibility.Visible if confirm else Visibility.Collapsed

    def on_ok(sender, args):
        result["ok"] = True
        window.Close()

    def on_cancel(sender, args):
        window.Close()

    ok_button.Click += on_ok
    cancel_button.Click += on_cancel
    if not modal:
        window.Show()           # parked in OPEN_WINDOWS until it closes
        return None
    window.ShowDialog()
    return result["ok"]
