# -*- coding: utf-8 -*-
"""Space Data Push - window plumbing: XAML loading, icon, borderless-window
chrome (drag, eight resize grips, full screen), and the easter egg link."""
import sdp_clr

import ctypes
import io
import os

from System import Action
from System.IO import File, MemoryStream
from System.Windows import CornerRadius, PresentationSource, Thickness, WindowState
from System.Windows.Controls import TextChangedEventHandler
from System.Windows.Controls.Primitives import TextBoxBase
from System.Windows.Forms import Screen
from System.Windows.Input import Key
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Shell import WindowChrome
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage

HERE = os.path.dirname(os.path.abspath(__file__))

EGG_MIN_GAP_MS = 250
EGG_MAX_GAP_MS = 2000
EGG_CLICKS = 3


# --------------------------------------------------------------------- loading

def read_text(path):
    with io.open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def load_window(xaml_name):
    """Parse the layout, then merge Theme.xaml in AFTER it - which is why the
    layout may only use DynamicResource."""
    window = XamlReader.Parse(read_text(os.path.join(HERE, xaml_name)))
    theme_dict = XamlReader.Parse(read_text(os.path.join(HERE, 'Theme.xaml')))
    window.Resources.MergedDictionaries.Add(theme_dict)
    return window


def set_icon(image, filename):
    """Icons load from bytes, not a Uri: System.Uri moved assemblies in 2025."""
    try:
        data = File.ReadAllBytes(os.path.join(HERE, filename))
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.StreamSource = MemoryStream(data)
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.EndInit()
        bmp.Freeze()
        image.Source = bmp
    except Exception:
        pass


def on_ui(window, fn):
    """Run fn on the window's dispatcher. Never runs it twice."""
    state = {'ran': False}

    def runner():
        state['ran'] = True
        fn()

    try:
        window.Dispatcher.Invoke(Action(runner))
    except Exception:
        if not state['ran']:
            try:
                fn()
            except Exception:
                pass


def text_of(obj):
    if obj is None:
        return u''
    try:
        return u'%s' % (obj,)
    except Exception:
        return u''


def checked(box):
    return box.IsChecked == True


def owner_handle(uiapp):
    try:
        return uiapp.MainWindowHandle
    except Exception:
        pass
    try:
        from System.Diagnostics import Process
        return Process.GetCurrentProcess().MainWindowHandle
    except Exception:
        return None


def own_window(window, uiapp):
    """Owned by Revit's main window, so it floats above Revit instead of slipping
    behind it, which is what makes an unowned modeless window look like a crash."""
    try:
        handle = owner_handle(uiapp)
        if handle is not None:
            WindowInteropHelper(window).Owner = handle
    except Exception:
        pass


# ------------------------------------------------------- the window's own frame

# Windows draws a thin frame of its own round a top-level window, in the system
# colour - white on a light Windows theme - and WindowStyle="None" does not take it
# away: it only removes the caption. That frame is the line round the tool. Two
# routes take it off, both harmless if they fail, and both are tried:
#   1. WindowChrome with no glass frame, which is pure WPF and works everywhere;
#   2. stripping the border bits off the window style, and asking DWM for no border
#      colour (Windows 11), which covers the cases WindowChrome leaves a hair of.

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_BORDER = 0x00800000
WS_DLGFRAME = 0x00400000
WS_THICKFRAME = 0x00040000
WS_EX_WINDOWEDGE = 0x00000100
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_STATICEDGE = 0x00020000
WS_EX_DLGMODALFRAME = 0x00000001
SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # NOSIZE NOMOVE NOZORDER NOACTIVATE FRAMECHANGED
DWMWA_BORDER_COLOR = 34
DWMWA_COLOR_NONE = 0xFFFFFFFE


def apply_chrome(window):
    """Route 1: a WindowChrome with nothing in it. WPF then owns the non-client
    area and draws no frame, while the header drag and the grips are unaffected."""
    try:
        chrome = WindowChrome()
        chrome.CaptionHeight = 0.0
        chrome.CornerRadius = CornerRadius(0)
        chrome.GlassFrameThickness = Thickness(0)
        chrome.ResizeBorderThickness = Thickness(0)
        chrome.UseAeroCaptionButtons = False
        WindowChrome.SetWindowChrome(window, chrome)
        return True
    except Exception:
        return False


def strip_border(window):
    """Route 2: take the border bits off the window style and tell DWM not to draw
    a border colour. Needs the handle, so it is called from SourceInitialized."""
    done = []
    hwnd = 0
    try:
        hwnd = int(WindowInteropHelper(window).Handle.ToInt64())
    except Exception:
        return done
    if not hwnd:
        return done
    try:
        user32 = ctypes.windll.user32
        get_long = getattr(user32, 'GetWindowLongPtrW', None) or user32.GetWindowLongW
        set_long = getattr(user32, 'SetWindowLongPtrW', None) or user32.SetWindowLongW
        style = get_long(hwnd, GWL_STYLE)
        set_long(hwnd, GWL_STYLE, style & ~(WS_BORDER | WS_DLGFRAME | WS_THICKFRAME))
        ex_style = get_long(hwnd, GWL_EXSTYLE)
        set_long(hwnd, GWL_EXSTYLE, ex_style & ~(WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE
                                                 | WS_EX_STATICEDGE | WS_EX_DLGMODALFRAME))
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)
        done.append('style')
    except Exception:
        pass
    try:
        value = ctypes.c_int(DWMWA_COLOR_NONE)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_BORDER_COLOR, ctypes.byref(value), ctypes.sizeof(value))
        done.append('dwm')
    except Exception:
        pass
    return done


def frameless(window):
    """Everything that takes the system frame off, wired up. Safe to call once, in
    the window's constructor: the handle part waits for SourceInitialized."""
    apply_chrome(window)

    def on_source(sender, args):
        strip_border(window)

    window.SourceInitialized += on_source
    return on_source


# ---------------------------------------------------------------------- chrome

GRIPS = [
    ('GripT', 'T'), ('GripB', 'B'), ('GripL', 'L'), ('GripR', 'R'),
    ('GripTL', 'TL'), ('GripTR', 'TR'), ('GripBL', 'BL'), ('GripBR', 'BR'),
]


class Chrome(object):
    """Drag by the header, resize by eight grips, full screen by bounds.

    A borderless AllowsTransparency window cannot be resized by WPF (nothing in
    its transparent frame is hit testable) and maximising it the normal way covers
    the task bar on the wrong monitor. So: Thumb grips, and full screen replaces
    the window's bounds with the working area of the screen it is on, divided by
    the DPI scale.
    """

    def __init__(self, window, find):
        self.window = window
        self.find = find
        self.full = False
        self.saved = None
        self._keep = []

    def wire(self):
        header = self.find('HeaderBar')
        header.MouseLeftButtonDown += self.on_header_down
        self.find('FullBtn').Click += self.on_full_click
        self.find('CloseBtn').Click += self.on_close_click
        self.window.PreviewKeyDown += self.on_key
        for name, mode in GRIPS:
            self._wire_grip(self.find(name), mode)

    def on_close_click(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def on_full_click(self, sender, args):
        self.toggle_full()

    def on_key(self, sender, args):
        try:
            if args.Key == Key.F11:
                self.toggle_full()
                args.Handled = True
            elif args.Key == Key.Escape and self.full:
                self.leave_full()
                args.Handled = True
        except Exception:
            pass

    def on_header_down(self, sender, args):
        try:
            if args.ClickCount == 2:
                self.toggle_full()
                return
            if self.full:
                self.leave_full()
            self.window.DragMove()
        except Exception:
            pass

    def _wire_grip(self, grip, mode):
        def on_delta(sender, e):
            try:
                if self.full:
                    self.leave_full()
                w = self.window
                dx = e.HorizontalChange
                dy = e.VerticalChange
                if 'R' in mode:
                    w.Width = max(w.MinWidth, w.Width + dx)
                if 'B' in mode:
                    w.Height = max(w.MinHeight, w.Height + dy)
                if 'L' in mode:
                    new_w = max(w.MinWidth, w.Width - dx)
                    w.Left = w.Left + (w.Width - new_w)
                    w.Width = new_w
                if 'T' in mode:
                    new_h = max(w.MinHeight, w.Height - dy)
                    w.Top = w.Top + (w.Height - new_h)
                    w.Height = new_h
            except Exception:
                pass
        grip.DragDelta += on_delta
        self._keep.append(on_delta)

    def toggle_full(self):
        if self.full:
            self.leave_full()
        else:
            self.enter_full()

    def enter_full(self):
        w = self.window
        try:
            self.saved = (w.Left, w.Top, w.Width, w.Height)
            w.WindowState = WindowState.Normal
            area = Screen.FromHandle(WindowInteropHelper(w).Handle).WorkingArea
            scale_x = 1.0
            scale_y = 1.0
            try:
                matrix = PresentationSource.FromVisual(w).CompositionTarget.TransformToDevice
                scale_x = matrix.M11 or 1.0
                scale_y = matrix.M22 or 1.0
            except Exception:
                pass
            w.Left = area.Left / scale_x
            w.Top = area.Top / scale_y
            w.Width = area.Width / scale_x
            w.Height = area.Height / scale_y
            self.full = True
        except Exception:
            self.full = False

    def leave_full(self):
        w = self.window
        try:
            if self.saved is not None:
                w.Left, w.Top, w.Width, w.Height = self.saved
        except Exception:
            pass
        self.full = False


# ------------------------------------------------- dropdowns that narrow as you type

class FilterCombo(object):
    """An editable ComboBox whose text box IS its search: typing narrows the list.

    The full list is held here, never in the ComboBox, because filtering means
    replacing the items and WPF clears the text when it does. So every refill
    restores the text and the caret behind a flag, and a selection change while
    that flag is up is ignored - otherwise typing would be read as picking.

    Leaving the box with text that matches nothing puts the last real value back,
    so the box can never sit showing something that was never chosen.
    """

    def __init__(self, combo, on_pick, blank_label=None):
        self.combo = combo
        self.on_pick = on_pick
        self.blank_label = blank_label
        self.items = []
        self.value = u''
        self.busy = 0
        self.box = None
        self._keep = []
        self.wire()

    def wire(self):
        c = self.combo
        c.IsEditable = True
        c.IsTextSearchEnabled = False
        c.StaysOpenOnEdit = True
        handler = TextChangedEventHandler(self.on_text)
        c.AddHandler(TextBoxBase.TextChangedEvent, handler)
        c.SelectionChanged += self.on_selection
        c.DropDownOpened += self.on_opened
        c.DropDownClosed += self.on_closed
        c.LostKeyboardFocus += self.on_lost_focus
        c.PreviewKeyDown += self.on_key
        self._keep.append(handler)

    # -------------------------------------------------------------- filling

    def set_items(self, items, value=None):
        """Replace the list this box offers, keeping the current value on it."""
        self.items = list(items)
        if value is not None:
            self.value = value
        if self.value and self.value not in self.items and self.value != self.blank_label:
            self.items.insert(0, self.value)
        self.show_all()

    def set_value(self, value):
        self.value = value or u''
        self.show_all()

    def shown_items(self):
        items = list(self.items)
        if self.blank_label and self.blank_label not in items:
            items.insert(0, self.blank_label)
        return items

    def show_all(self):
        self.fill(self.shown_items(), self.display())

    def display(self):
        if self.value:
            return self.value
        return self.blank_label or u''

    def fill(self, items, text, caret=None):
        """Rebuild the list only when it is actually different.

        Clearing and re-adding the items is what makes a dropdown flicker, and the
        window fills every box several times while it opens. Comparing first means
        all of that costs nothing and the boxes are still as the window is shown.
        """
        text = text or u''
        same_items = self.current_items() == list(items)
        if same_items and text_of(self.combo.Text) == text:
            return
        self.busy += 1
        try:
            if not same_items:
                self.combo.Items.Clear()
                for n in items:
                    self.combo.Items.Add(n)
            index = items.index(self.value) if self.value in items else -1
            if self.combo.SelectedIndex != index:
                self.combo.SelectedIndex = index
            self.combo.Text = text
            box = self.text_box()
            if box is not None:
                box.CaretIndex = len(text) if caret is None else caret
        finally:
            self.busy -= 1

    def current_items(self):
        try:
            return [text_of(i) for i in self.combo.Items]
        except Exception:
            return []

    def text_box(self):
        if self.box is None:
            try:
                self.box = self.combo.Template.FindName('PART_EditableTextBox', self.combo)
            except Exception:
                self.box = None
        return self.box

    # -------------------------------------------------------------- events

    def on_text(self, sender, args):
        if self.busy:
            return
        try:
            self.box = args.OriginalSource
        except Exception:
            pass
        query = text_of(self.combo.Text)
        shown, matched = keyword_filter(self.shown_items(), query)
        caret = None
        box = self.text_box()
        if box is not None:
            caret = box.CaretIndex
        self.fill(shown, query, caret)
        if query:
            try:
                self.combo.IsDropDownOpen = True
            except Exception:
                pass
        return matched

    def on_selection(self, sender, args):
        if self.busy:
            return
        item = self.combo.SelectedItem
        if item is None:
            return
        picked = text_of(item)
        self.value = u'' if (self.blank_label and picked == self.blank_label) else picked
        self.show_all()
        if self.on_pick is not None:
            self.on_pick(self.value)

    def on_opened(self, sender, args):
        if text_of(self.combo.Text) == self.display():
            self.show_all()

    def on_closed(self, sender, args):
        self.revert()

    def on_lost_focus(self, sender, args):
        self.revert()

    def on_key(self, sender, args):
        try:
            if args.Key == Key.Escape and self.combo.IsDropDownOpen:
                self.combo.IsDropDownOpen = False
                self.revert()
                args.Handled = True
        except Exception:
            pass

    def revert(self):
        """Anything typed that was never picked goes back to the real value."""
        if self.busy:
            return
        if text_of(self.combo.Text) != self.display():
            self.show_all()


def keyword_filter(names, query):
    """Names holding every word typed, any case. A miss keeps the full list, so a
    typo never leaves an empty dropdown. Same rule as the logic module's, kept here
    so this widget has no import back into it."""
    words = [w for w in text_of(query).lower().split() if w]
    if not words:
        return list(names), True
    out = [n for n in names if all(w in text_of(n).lower() for w in words)]
    return (out, True) if out else (list(names), False)


# ------------------------------------------------------------------ easter egg

def _find_egg_hook():
    """lib\\revobim\\egg\\egg_hook, reached by name so a missing package is not fatal."""
    for dotted in (u'revobim.egg.egg_hook', u'egg_hook'):
        try:
            mod = __import__(dotted, fromlist=[u'egg_hook'])
            if hasattr(mod, 'launch') or hasattr(mod, 'attach'):
                return mod
        except Exception:
            continue
    return None


class ClickCounter(object):
    """Three slow clicks on the RevoBIM logo. A gap under 250ms is a double
    click and restarts the count; a gap over 2s restarts it too. ClickCount only
    ever reports 1 or 2, so the gaps are timed from args.Timestamp - which can
    arrive twice for one physical click, hence the de-duplication."""

    def __init__(self, window, hook, theme_getter):
        self.window = window
        self.hook = hook
        self.theme_getter = theme_getter
        self.count = 0
        self.last = None
        self.last_ts = None

    def on_down(self, sender, args):
        try:
            ts = int(args.Timestamp)
            if self.last_ts is not None and ts == self.last_ts:
                return
            self.last_ts = ts
            if self.last is None:
                self.count = 1
            else:
                gap = ts - self.last
                if gap < EGG_MIN_GAP_MS or gap > EGG_MAX_GAP_MS:
                    self.count = 1
                else:
                    self.count += 1
            self.last = ts
            if self.count >= EGG_CLICKS:
                self.count = 0
                self.last = None
                self.launch()
        except Exception:
            pass

    def launch(self):
        hook = self.hook
        theme = self.theme_getter()
        for call in (lambda: hook.launch(self.window, theme, None),
                     lambda: hook.launch(self.window, theme),
                     lambda: hook.launch(self.window)):
            try:
                call()
                return
            except TypeError:
                continue
            except Exception:
                return


def attach_egg(window, logo, theme_getter, keep):
    """Wire the easter egg to the RevoBIM logo and to NOTHING else.

    Three slow clicks on the logo, counted here, are the only way in. egg_hook's
    own attach() is deliberately not used for the wiring: what it arms varies with
    its version, and arming anything besides this one control is how clicking Close
    three times ends up starting the game. Returns 'counter' or 'none'.
    """
    hook = _find_egg_hook()
    if hook is None:
        return u'none'
    if getattr(hook, 'launch', None) is None:
        return u'none'
    counter = ClickCounter(window, hook, theme_getter)
    logo.PreviewMouseLeftButtonDown += counter.on_down
    keep.append(counter)
    return u'counter'
