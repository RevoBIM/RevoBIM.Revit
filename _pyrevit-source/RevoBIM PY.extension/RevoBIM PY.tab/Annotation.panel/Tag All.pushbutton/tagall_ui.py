# -*- coding: utf-8 -*-
"""WPF plumbing shared by every window in the tool.

Loading a layout, merging Theme.xaml after it, applying a palette, the
borderless chrome with its own resize grips and full screen by bounds, the
easter egg on the logo, guarded event handlers, and the themed prompt and
results windows.
"""
import os
import traceback

import tagall_clr  # noqa: F401  (assemblies first)
import tagall_core as core
import tagall_drawer as drawer_module
import theme

from System import Action
from System.IO import StringReader, MemoryStream, File
from System.Xml import XmlReader
from System.Windows import Visibility, WindowStartupLocation, TextWrapping, VerticalAlignment, Thickness
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Controls import TextBlock, Border
from System.Windows.Input import Key, MouseButtonState
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherPriority, DispatcherTimer

HERE = os.path.dirname(os.path.abspath(__file__))

_LAST_ERROR = {"text": u""}


def read_text(path):
    import io
    with io.open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def load_window(file_name, mode):
    """Parse the layout, then merge Theme.xaml, then write the palette.

    The order matters: the layout may only use DynamicResource, because the
    dictionary is merged after XamlReader has parsed it.
    """
    window = XamlReader.Load(XmlReader.Create(StringReader(read_text(os.path.join(HERE, file_name)))))
    dictionary = XamlReader.Load(XmlReader.Create(StringReader(read_text(os.path.join(HERE, "Theme.xaml")))))
    window.Resources.MergedDictionaries.Add(dictionary)
    theme.apply(window, theme.resolve(mode))
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


def own_to_revit(window, handle):
    try:
        if handle:
            WindowInteropHelper(window).Owner = handle
            return True
    except Exception:
        pass
    return False


def brush_for(window, key):
    try:
        return window.Resources[key]
    except Exception:
        return SolidColorBrush()


def set_brush(element, prop_name, key):
    """Brushes are applied by resource reference so a palette swap reaches
    elements built in code as well as the ones in the layout."""
    try:
        prop = getattr(type(element), prop_name + "Property")
        element.SetResourceReference(prop, key)
        return True
    except Exception:
        return False


# ====================== button icons ======================
# 16x16 stroke icons in WPF path mini-language. Every one is a line drawing
# so it reads at one weight beside the text, and its stroke is bound to the
# button's own Foreground - hover, disabled and both themes come for free.

ICONS = {
    "tag": "M1.5,8 L6,3.5 L14.5,3.5 L14.5,12.5 L6,12.5 Z M9,7 L9,9",
    "tag_all": "M1.5,8 L6,3.5 L14.5,3.5 L14.5,12.5 L6,12.5 Z M7.5,8 L9.5,10 L12.5,6",
    "refresh": "M13,8 A5,5 0 1 1 11.5,4.4 M11.8,1.5 L11.8,4.6 L8.7,4.6",
    "add": "M8,2.5 L8,13.5 M2.5,8 L13.5,8",
    "remove": "M3,8 L13,8",
    "clear": "M2.5,4.5 L13.5,4.5 M6,4.5 L6,2.5 L10,2.5 L10,4.5 M4,4.5 L4.8,13.5 L11.2,13.5 L12,4.5",
    "tick": "M2.5,8.5 L6.5,12.5 L13.5,4",
    "cross": "M3.5,3.5 L12.5,12.5 M12.5,3.5 L3.5,12.5",
    "box": "M3,3 L13,3 L13,13 L3,13 Z",
    "expand": "M3,4 L8,8 L13,4 M3,9 L8,13 L13,9",
    "collapse": "M3,8 L8,4 L13,8 M3,13 L8,9 L13,13",
    "pointer": "M4,2 L4,13 L7,10.3 L9.4,14.5 L11.1,13.6 L8.8,9.5 L12.7,9.3 Z",
    "link": "M6.5,9.5 L9.5,6.5 M8.2,4.3 L9.4,3.1 A2.4,2.4 0 0 1 12.9,6.6 L11.7,7.8 M7.8,11.7 L6.6,12.9 A2.4,2.4 0 0 1 3.1,9.4 L4.3,8.2",
    "eye": "M1.5,8 Q8,1.5 14.5,8 Q8,14.5 1.5,8 Z M8,6 A2,2 0 1 1 7.99,6",
    "theme": "M8,2.5 A5.5,5.5 0 1 0 8,13.5 A5.5,5.5 0 1 0 8,2.5 M8,2.5 L8,13.5 M8,5 L11.5,5 M8,8 L13.5,8 M8,11 L11.5,11",
    "copy": "M5.5,5.5 L13,5.5 L13,13 L5.5,13 Z M3,10.5 L3,3 L10.5,3",
    "sheet": "M3.5,1.5 L10,1.5 L12.5,4 L12.5,14.5 L3.5,14.5 Z M10,1.5 L10,4 L12.5,4",
    "views": "M1.5,3.5 L14.5,3.5 L14.5,12.5 L1.5,12.5 Z M1.5,6.5 L14.5,6.5 M5.5,6.5 L5.5,12.5",
    "shrink": "M8,2 L8,10 M4.5,6.5 L8,10 L11.5,6.5 M2.5,13.5 L13.5,13.5",
    "unshrink": "M2.5,2.5 L13.5,2.5 M8,14 L8,6 M4.5,9.5 L8,6 L11.5,9.5",
    "views_sheets": "M2.5,2 L13.5,2 L13.5,14 L2.5,14 Z M4.5,4 L11.5,4 L11.5,9.5 L4.5,9.5 Z M4.5,12 L8.5,12",
    "categories": "M2.5,2.5 L7,2.5 L7,6 L2.5,6 Z M4.75,6 L4.75,12 L8.5,12 M4.75,8.5 L8.5,8.5 M8.5,7.25 L13.5,7.25 L13.5,9.75 L8.5,9.75 Z M8.5,10.75 L13.5,10.75 L13.5,13.25 L8.5,13.25 Z",
    "chevron_closed": "M6,3.5 L10.5,8 L6,12.5",
    "chevron_open": "M3.5,6 L8,10.5 L12.5,6",
}

# the Family Tags groups: header button -> (icon, title). Each header is a
# chevron, the group's icon and its title, built by group_toggle
GROUP_FOR = {
    "ViewsGroupToggle": ("views_sheets", u"Views / Sheets"),
    "CategoriesGroupToggle": ("categories", u"Categories"),
    "FamiliesGroupToggle": ("tag", u"Families to tag"),
}

# every button in every layout, and the icon it carries; None keeps the
# layout's own text as the label
ICON_FOR = {
    "ThemeChip": ("theme", None),
    "LinksToggle": ("link", None),
    "LinksAll": ("tick", None),
    "LinksNone": ("cross", None),
    "LinksRefresh": ("refresh", None),
    "ExpandAll": ("expand", None),
    "CollapseAll": ("collapse", None),
    "AddSelected": ("add", None),
    "AddFromRevit": ("pointer", None),
    "ClearTicks": ("box", None),
    "ClearTable": ("clear", None),
    "RemoveHighlighted": ("remove", None),
    "TagAllButton": ("tag_all", None),
    "ShrinkButton": ("shrink", None),
    "SourceCurrent": ("eye", None),
    "SourceTicked": ("tick", None),
    "SourceSheets": ("sheet", None),
    "YesButton": ("tick", None),
    "NoButton": ("cross", None),
    "CopyButton": ("copy", None),
    "OkButton": ("tick", None),
}

# buttons whose glyph is the whole button - a close cross, the full screen
# frame drawn in the layout
ICON_EXEMPT = ("CloseButton", "FullScreenButton")


def icon_path(icon, button, size=14):
    """The icon, drawn on a fixed 16x16 canvas inside a Viewbox.

    Every icon is drawn in the same 16-unit box, so a Viewbox round a
    16x16 canvas scales them all by the same amount and a short stroke
    stays short. Stretching the Path itself would fit each icon to its own
    bounds, blowing a minus sign up to the size of a bin.
    """
    from System.Windows.Shapes import Path as ShapePath
    from System.Windows.Media import Geometry, PenLineCap, PenLineJoin
    from System.Windows.Controls import Canvas, Viewbox
    from System.Windows.Data import Binding
    path = ShapePath()
    path.Data = Geometry.Parse(ICONS[icon])
    path.StrokeThickness = 1.6
    path.StrokeStartLineCap = PenLineCap.Round
    path.StrokeEndLineCap = PenLineCap.Round
    path.StrokeLineJoin = PenLineJoin.Round
    binding = Binding("Foreground")
    binding.Source = button
    path.SetBinding(ShapePath.StrokeProperty, binding)
    canvas = Canvas()
    canvas.Width = 16
    canvas.Height = 16
    canvas.Children.Add(path)
    box = Viewbox()
    box.Width = size
    box.Height = size
    box.Child = canvas
    box.VerticalAlignment = VerticalAlignment.Center
    box.IsHitTestVisible = False
    return box


def iconize(button, icon, label=None, size=14):
    """Give a button its icon and a named label.

    The label TextBlock is kept on the button's Tag, and from here on the
    label changes through set_label - setting Content again would throw the
    icon away, which is the trap this whole arrangement exists to avoid.
    """
    from System.Windows.Controls import StackPanel, TextBlock, Orientation
    if label is None:
        try:
            current = button.Content
            label = current if isinstance(current, (type(u""), str)) else u""
        except Exception:
            label = u""
    panel = StackPanel()
    panel.Orientation = Orientation.Horizontal
    panel.Children.Add(icon_path(icon, button, size))
    text = TextBlock()
    text.Text = core.to_text(label)
    text.VerticalAlignment = VerticalAlignment.Center
    if text.Text:
        text.Margin = Thickness(6, 0, 0, 0)
    panel.Children.Add(text)
    button.Content = panel
    button.Tag = text
    return button


def set_label(button, text):
    try:
        label = button.Tag
        label.Text = core.to_text(text)
        label.Margin = Thickness(6, 0, 0, 0) if label.Text else Thickness(0)
        return True
    except Exception:
        return False


def iconize_named(window, names=None):
    """Iconize every named button the layout carries."""
    done = []
    for name, (icon, label) in ICON_FOR.items():
        if names is not None and name not in names:
            continue
        try:
            button = window.FindName(name)
        except Exception:
            button = None
        if button is None:
            continue
        try:
            iconize(button, icon, label)
            done.append(name)
        except Exception:
            core.log(u"icon for {0} failed:\n{1}".format(name, traceback.format_exc()))
    return done


def icon_button(icon, label=u"", style=None, tooltip=None, size=14):
    """A themed button built in code, with its icon. A bare Button falls back
    to the OS chrome, so the style is set by resource reference."""
    from System.Windows.Controls import Button
    button = Button()
    if style:
        button.SetResourceReference(Button.StyleProperty, style)
    if tooltip:
        button.ToolTip = tooltip
    iconize(button, icon, label, size)
    return button


def group_toggle(button, icon, title):
    """A group's header button: chevron, the group's icon, and its title in
    the heading style. The title TextBlock goes on Tag, as iconize does, so
    set_label still works; the chevron is the panel's first child and is
    swapped by set_group_open."""
    from System.Windows.Controls import StackPanel, TextBlock, Orientation
    panel = StackPanel()
    panel.Orientation = Orientation.Horizontal
    panel.Children.Add(icon_path("chevron_closed", button, 12))
    glyph = icon_path(icon, button, 16)
    glyph.Margin = Thickness(6, 0, 0, 0)
    panel.Children.Add(glyph)
    text = TextBlock()
    text.Text = core.to_text(title)
    try:
        text.SetResourceReference(TextBlock.StyleProperty, "Heading")
    except Exception:
        pass
    text.Margin = Thickness(8, 0, 0, 0)
    text.VerticalAlignment = VerticalAlignment.Center
    try:
        from System.Windows.Data import Binding
        binding = Binding("Foreground")
        binding.Source = button
        text.SetBinding(TextBlock.ForegroundProperty, binding)
    except Exception:
        pass
    panel.Children.Add(text)
    button.Content = panel
    button.Tag = text
    return button


def set_group_open(button, is_open):
    """Point a group header's chevron down when open, right when shut."""
    try:
        panel = button.Content
        panel.Children.RemoveAt(0)
        panel.Children.Insert(0, icon_path("chevron_open" if is_open else "chevron_closed", button, 12))
        return True
    except Exception:
        return False


def select_all_on_focus(box):
    """Click into a number box and its contents are selected, ready to be
    typed over. A mouse click normally lands the caret and clears the
    selection that GotKeyboardFocus has just made, so the first click is
    taken on the preview and turned into a focus instead."""
    def focused(sender, args):
        try:
            sender.SelectAll()
        except Exception:
            pass

    def pressed(sender, args):
        try:
            if not sender.IsKeyboardFocusWithin:
                sender.Focus()
                args.Handled = True
        except Exception:
            pass
    box.GotKeyboardFocus += focused
    box.PreviewMouseLeftButtonDown += pressed
    return box


def corner(radius):
    from System.Windows import CornerRadius
    return CornerRadius(radius)


def transparent():
    """A real transparent brush, not None. A Border with no Background is
    invisible to hit testing, so the row would only take clicks where its
    child happens to be."""
    try:
        from System.Windows.Media import Brushes
        return Brushes.Transparent
    except Exception:
        return None


def resize_cursor():
    try:
        from System.Windows.Input import Cursors
        return Cursors.SizeWE
    except Exception:
        return None


def hand_cursor():
    try:
        from System.Windows.Input import Cursors
        return Cursors.Hand
    except Exception:
        return None


def control_held():
    """Ctrl down right now. Read from the keyboard rather than carried on the
    event, because a preview handler sees the mouse args, not the key ones."""
    try:
        from System.Windows.Input import Keyboard, ModifierKeys
        return bool(Keyboard.Modifiers & ModifierKeys.Control)
    except Exception:
        return False


def shift_held():
    try:
        from System.Windows.Input import Keyboard, ModifierKeys
        return bool(Keyboard.Modifiers & ModifierKeys.Shift)
    except Exception:
        return False


def pump(window):
    """Let WPF repaint. Only ever called between transactions - a dispatcher
    pump inside an open transaction is a hard crash."""
    try:
        window.Dispatcher.Invoke(Action(lambda: None), DispatcherPriority.Background)
    except Exception:
        pass


# ====================== guarded handlers ======================

def last_error():
    return _LAST_ERROR["text"]


def wpf_window(owner):
    """The real WPF Window behind whatever was handed in - the window itself,
    or a wrapper carrying one as `.window`."""
    if owner is None:
        return None
    try:
        from System.Windows import Window as WpfWindow
        if isinstance(owner, WpfWindow):
            return owner
    except Exception:
        pass
    return getattr(owner, "window", None)


def ui_safe(owner, function, name=None):
    """Wrap an event handler so a failure inside it is reported instead of
    swallowed. An unguarded handler that throws leaves the window on screen
    with nothing responding and no traceback to read - a dead button with
    nothing anywhere to say why.
    """
    label = name or getattr(function, "__name__", "handler")

    def wrapped(*args):
        try:
            return function(*args)
        except Exception:
            text = traceback.format_exc()
            _LAST_ERROR["text"] = text
            core.log(u"handler {0} failed:\n{1}".format(label, text))
            try:
                owner.set_status(u"{0} failed - see the log".format(label), True)
            except Exception:
                pass
            try:
                show_message(wpf_window(owner), u"{0} failed".format(label),
                             u"Something went wrong inside the tool. The traceback is in\n{0}\n\n{1}".format(
                                 core.log_path(), text[-1500:]),
                             getattr(owner, "mode", core.THEME_AUTO))
            except Exception:
                pass
    return wrapped


# ====================== the easter egg ======================

def attach_egg(window, logo_host, mode):
    """Three slow clicks on the RevoBIM logo.

    The egg lives in the extension's shared lib\\revobim\\egg package and is
    not shipped with this tool. The current call is `attach_to_window`, which
    finds the logo itself; `attach` is the older form kept as a fallback.
    Anything decorative belongs in a try/except that swallows failures, so
    cosmetics can never take a tool down.
    """
    try:
        from revobim.egg import egg_hook
    except Exception:
        return False
    palette = lambda: theme.palette(theme.resolve(mode))  # noqa: E731

    attach_to_window = getattr(egg_hook, "attach_to_window", None)
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

    attach = getattr(egg_hook, "attach", None)
    if attach is None or logo_host is None:
        return False
    try:
        attach(logo_host, host_window=window, theme=palette)
        return True
    except Exception:
        return False


# ====================== chrome ======================

class WpfPlatform(object):
    """Everything the drawer needs from WPF, in one place, so the drawer
    itself (tagall_drawer) has none and the bench can drive it."""

    def on_click(self, button, handler):
        button.Click += ui_safe(None, handler, "shrink to the taskbar")

    def on_closed(self, window, handler):
        window.Closed += ui_safe(None, handler, "close a parked window")

    def height(self, window):
        """A SizeToContent window reports NaN for Height until it is set."""
        try:
            value = float(window.Height)
            if value == value and value > 0:
                return value
        except Exception:
            pass
        return float(window.ActualHeight)

    def owner(self, window):
        try:
            return window.Owner
        except Exception:
            return None

    def owned(self, window):
        try:
            return list(window.OwnedWindows)
        except Exception:
            return []

    def manual_size(self):
        from System.Windows import SizeToContent
        return SizeToContent.Manual

    def bar_height(self, header, window):
        """The parked bar: the header, plus the frame's border above and
        below it - measured, since the header's height depends on its
        contents and the screen's text scaling."""
        offset = 1.0
        try:
            from System.Windows import Point
            offset = header.TranslatePoint(Point(0, 0), window).Y
        except Exception:
            pass
        offset = max(0.0, min(12.0, float(offset)))
        return float(header.ActualHeight) + 2.0 * offset

    def work_area(self, window):
        """Top and bottom of the working area of the window's own screen, in
        WPF units. SystemParameters.WorkArea is the primary monitor, which is
        how a bar lands on the wrong screen."""
        try:
            from System.Windows.Forms import Screen
            from System.Windows import PresentationSource
            area = Screen.FromHandle(WindowInteropHelper(window).Handle).WorkingArea
            scale = 1.0
            try:
                scale = PresentationSource.FromVisual(window).CompositionTarget.TransformToDevice.M22
            except Exception:
                pass
            return area.Top / scale, area.Bottom / scale
        except Exception:
            from System.Windows import SystemParameters
            area = SystemParameters.WorkArea
            return area.Top, area.Bottom

    def pin(self, window, height):
        from System.Windows import VerticalAlignment as Align
        root = window.Content
        root.Height = height
        root.VerticalAlignment = Align.Top

    def unpin(self, window):
        from System import Double
        from System.Windows import VerticalAlignment as Align
        root = window.Content
        root.Height = Double.NaN
        root.VerticalAlignment = Align.Stretch

    def parts_beside(self, header, window):
        """Everything beside the header on the way up to the window: the
        body and footer beside it, and the resize grips beside the frame."""
        out = []
        node = header
        while node is not None:
            parent = node.Parent
            if parent is None or parent is window:
                break
            children = getattr(parent, "Children", None)
            if children is not None:
                for child in children:
                    if child is not node:
                        out.append(child)
            node = parent
        return out

    def visibility(self, part):
        return part.Visibility

    def collapse(self, part):
        part.Visibility = Visibility.Collapsed

    def restore_visibility(self, part, visibility):
        part.Visibility = visibility

    def round_header(self, header):
        from System.Windows import CornerRadius
        previous = header.CornerRadius
        header.CornerRadius = CornerRadius(6)
        return previous

    def restore_header(self, header, previous):
        if previous is not None:
            header.CornerRadius = previous

    def shrunk_look(self, button, shrunk):
        """Shrink glyph, or the green up arrow that brings it back."""
        if button is None:
            return
        try:
            from System.Windows.Controls import Button
            iconize(button, "unshrink" if shrunk else "shrink", u"")
            if shrunk:
                button.SetResourceReference(Button.ForegroundProperty, "GreenBrush")
                button.ToolTip = u"Bring the window back (Ctrl+Shift+H)"
            else:
                button.ClearValue(Button.ForegroundProperty)
                button.ToolTip = u"Shrink to the taskbar, to see the model (Ctrl+Shift+H)"
        except Exception:
            core.log(u"shrink button look failed:\n{0}".format(traceback.format_exc()))

    def activate(self, window):
        try:
            window.Activate()
        except Exception:
            pass

    def now(self):
        import time
        return time.time() * 1000.0

    def timer(self, milliseconds, tick):
        from System import TimeSpan
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromMilliseconds(milliseconds)

        def ticked(sender, args):
            tick(timer)
        timer.Tick += ticked
        timer.Start()
        return timer


PLATFORM = WpfPlatform()


def key_name(args):
    try:
        return core.to_text(args.Key)
    except Exception:
        return u""


def drawer_key(drawer, args):
    """Hand a key press to a window's drawer first. True when it took it."""
    if drawer is None:
        return False
    if drawer.key(key_name(args), control_held(), shift_held()):
        args.Handled = True
        return True
    return False


def make_drawer(window, header, button):
    """A drawer for a window whose chrome is not a Chrome - the prompt."""
    drawer = drawer_module.WindowDrawer(window, header, button, PLATFORM)
    PLATFORM.shrunk_look(button, False)
    return drawer


def centre_if_owner_parked(window, owner):
    """A dialog opened while the window it belongs to is parked would open
    centred on a forty-pixel bar at the foot of the screen. Centre it on the
    screen instead."""
    owner_drawer = drawer_module.drawer_of(owner)
    if owner_drawer is not None and owner_drawer.busy():
        window.WindowStartupLocation = WindowStartupLocation.CenterScreen


class Chrome(object):
    """Borderless window: drag by the header, eight resize grips, full screen
    by bounds rather than WindowState.Maximized, and the shrink drawer.

    While the window is parked or sliding, full screen and the grips are
    refused - F11 or the full-screen button reopen it instead - and a press
    on the header drags the bar."""

    def __init__(self, window, header, grips, full_button=None, shrink_button=None):
        self.window = window
        self.saved = None
        self.grips = {}
        self.drawer = None
        if shrink_button is not None:
            self.drawer = make_drawer(window, header, shrink_button)
        header.MouseLeftButtonDown += self._header_down
        for name, thumb in grips.items():
            if thumb is None:
                continue
            self.grips[name] = thumb
            thumb.DragDelta += self._make_drag(name)
            if core.edge_fills_screen(name):
                thumb.MouseDoubleClick += self._edge_double
        if full_button is not None:
            full_button.Click += self._full_click
        window.PreviewKeyDown += self._key

    def _header_down(self, sender, args):
        try:
            if self.drawer is not None:
                if self.drawer.header_down(args.ClickCount):
                    return
                if self.drawer.shrunk:
                    self.window.DragMove()      # the parked bar still drags
                    return
            if args.ClickCount == 2:
                self.toggle_full()
                return
            if self.is_full():
                self.leave_full()
            self.window.DragMove()
        except Exception:
            pass

    def _full_click(self, sender, args):
        self.toggle_full()

    def _edge_double(self, sender, args):
        """A double-click on the top or bottom edge fills the monitor the
        window is on, and puts it back the same way - the header's double
        click, reached from the edge where Windows users already look for
        it."""
        try:
            if self.drawer is not None and (self.drawer.busy() or self.drawer.shrunk):
                return
            self.toggle_full()
            args.Handled = True
        except Exception:
            pass

    def _key(self, sender, args):
        try:
            if drawer_key(self.drawer, args):
                return
            if args.Key == Key.F11:
                self.toggle_full()
                args.Handled = True
            elif args.Key == Key.Escape and self.is_full():
                self.leave_full()
                args.Handled = True
        except Exception:
            pass

    def _make_drag(self, name):
        def handler(sender, args):
            try:
                if self.drawer is not None and self.drawer.busy():
                    return
                if self.is_full():
                    self.leave_full()
                self._resize(name, args.HorizontalChange, args.VerticalChange)
            except Exception:
                pass
        return handler

    def _resize(self, name, dx, dy):
        w = self.window
        min_w = max(w.MinWidth, 200.0)
        min_h = max(w.MinHeight, 150.0)
        if "E" in name:
            w.Width = max(min_w, w.Width + dx)
        if "S" in name:
            w.Height = max(min_h, w.Height + dy)
        if "W" in name:
            new_w = max(min_w, w.Width - dx)
            w.Left += (w.Width - new_w)
            w.Width = new_w
        if "N" in name:
            new_h = max(min_h, w.Height - dy)
            w.Top += (w.Height - new_h)
            w.Height = new_h

    def is_full(self):
        return self.saved is not None

    def true_size(self):
        """The size to remember: the parked window's real size, not its bar."""
        if self.drawer is not None:
            return self.drawer.true_size()
        return self.window.Width, self.window.Height

    def toggle_full(self):
        if self.drawer is not None and self.drawer.busy():
            if self.drawer.shrunk:
                self.drawer.expand()
            return
        if self.is_full():
            self.leave_full()
        else:
            self.enter_full()

    def enter_full(self):
        """SystemParameters.WorkArea is the primary monitor, not the one the
        window is on. Find the screen from the window handle and divide by
        the DPI scale, or a scaled display overshoots."""
        w = self.window
        try:
            from System.Windows.Forms import Screen
            from System.Windows import PresentationSource
            handle = WindowInteropHelper(w).Handle
            area = Screen.FromHandle(handle).WorkingArea
            scale_x = scale_y = 1.0
            try:
                matrix = PresentationSource.FromVisual(w).CompositionTarget.TransformToDevice
                scale_x, scale_y = matrix.M11, matrix.M22
            except Exception:
                pass
            self.saved = (w.Left, w.Top, w.Width, w.Height)
            w.Left = area.Left / scale_x
            w.Top = area.Top / scale_y
            w.Width = area.Width / scale_x
            w.Height = area.Height / scale_y
        except Exception:
            self.saved = None

    def leave_full(self):
        if self.saved is None:
            return
        left, top, width, height = self.saved
        self.saved = None
        w = self.window
        w.Left, w.Top, w.Width, w.Height = left, top, width, height


def grips_of(window, names):
    out = {}
    for name in names:
        try:
            out[name] = window.FindName(name)
        except Exception:
            out[name] = None
    return out


# ====================== small windows ======================

class Prompt(object):
    """Themed yes/no. Modal to its owner, which is fine from a modeless
    window - it is not a Revit dialog and no transaction is open."""

    def __init__(self, owner, title, message, mode, yes=u"Continue", no=u"Cancel"):
        self.answer = False
        self.mode = mode
        self.window = load_window("TagAllPrompt.xaml", mode)
        w = self.window
        find = w.FindName
        find("ToolTitle").Text = title
        find("MessageText").Text = message
        iconize_named(w, ("YesButton", "NoButton"))
        set_label(find("YesButton"), yes)
        set_label(find("NoButton"), no)
        find("VersionText").Text = u"v{0}".format(core.__version__)
        load_icon(find("LogoImage"))
        find("YesButton").Click += self._yes
        find("NoButton").Click += self._no
        self.drawer = make_drawer(w, find("HeaderBar"), find("ShrinkButton"))
        find("HeaderBar").MouseLeftButtonDown += self._drag
        w.PreviewKeyDown += self._key
        try:
            if owner is not None:
                w.Owner = owner
                centre_if_owner_parked(w, owner)
            else:
                w.WindowStartupLocation = WindowStartupLocation.CenterScreen
        except Exception:
            pass
        attach_egg(w, find("LogoHost"), mode)

    def _drag(self, sender, args):
        try:
            if self.drawer.header_down(args.ClickCount):
                return
            self.window.DragMove()
        except Exception:
            pass

    def _key(self, sender, args):
        # parked, Escape and Enter reopen the prompt rather than answer it
        if drawer_key(self.drawer, args):
            return
        if args.Key == Key.Escape:
            self._no(sender, args)
        elif args.Key == Key.Enter:
            self._yes(sender, args)

    def _yes(self, sender, args):
        self.answer = True
        self.window.Close()

    def _no(self, sender, args):
        self.answer = False
        self.window.Close()

    def ask(self):
        try:
            self.window.ShowDialog()
            return self.answer
        except Exception:
            return self._fallback()

    def _fallback(self):
        """Any dialog standing between a user and a write needs a fallback,
        not an `except: return False` - a silent no reads exactly like a
        broken button."""
        try:
            from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult
            dialog = TaskDialog(u"RevoBIM {0}".format(core.TOOL_NAME))
            dialog.MainInstruction = self.window.FindName("ToolTitle").Text
            dialog.MainContent = self.window.FindName("MessageText").Text
            dialog.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
            return dialog.Show() == TaskDialogResult.Yes
        except Exception:
            return False


def ask(owner, title, message, mode, yes=u"Continue", no=u"Cancel"):
    return Prompt(owner, title, message, mode, yes, no).ask()


def show_message(owner, title, message, mode):
    """A one-button prompt."""
    prompt = Prompt(owner, title, message, mode, yes=u"OK", no=u"Close")
    try:
        prompt.window.FindName("NoButton").Visibility = Visibility.Collapsed
    except Exception:
        pass
    return prompt.ask()


class Results(object):
    """The post-run report. Problems in red, notes in the body colour."""

    def __init__(self, owner, summary, problems, notes, mode):
        self.mode = mode
        self.window = load_window("TagAllResults.xaml", mode)
        w = self.window
        find = w.FindName
        find("SummaryText").Text = summary
        find("VersionText").Text = u"v{0}".format(core.__version__)
        load_icon(find("LogoImage"))
        self.text = u"\n".join([summary, u""] + [u"! " + core.to_text(p) for p in problems] +
                               [u"- " + core.to_text(n) for n in notes])
        lines = find("Lines")
        for text, key in [(p, "RedBrush") for p in problems] + [(n, "TextBrush") for n in notes]:
            block = TextBlock()
            block.Text = core.to_text(text)
            block.TextWrapping = TextWrapping.Wrap
            block.Margin = _thickness(0, 2, 0, 2)
            set_brush(block, "Foreground", key)
            lines.Children.Add(block)
        find("StatusText").Text = u"{0} problem{1}, {2} note{3}".format(
            len(problems), u"" if len(problems) == 1 else u"s",
            len(notes), u"" if len(notes) == 1 else u"s")
        iconize_named(w, ("CopyButton", "OkButton"))
        find("OkButton").Click += self._close
        find("CloseButton").Click += self._close
        find("CopyButton").Click += self._copy
        self.chrome = Chrome(w, find("HeaderBar"), grips_of(w, ("GripSE", "GripE", "GripS")),
                             shrink_button=find("ShrinkButton"))
        w.PreviewKeyDown += self._key
        try:
            if owner is not None:
                w.Owner = owner
                centre_if_owner_parked(w, owner)
            else:
                w.WindowStartupLocation = WindowStartupLocation.CenterScreen
        except Exception:
            pass
        attach_egg(w, find("LogoHost"), mode)

    def _key(self, sender, args):
        # parked, Escape reopens the report rather than closing it
        if self.chrome.drawer is not None and self.chrome.drawer.busy():
            return
        if args.Key == Key.Escape:
            self._close(sender, args)

    def _close(self, sender, args):
        self.window.Close()

    def _copy(self, sender, args):
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(self.text)
            self.window.FindName("StatusText").Text = u"Copied"
        except Exception:
            pass

    def show(self):
        try:
            self.window.Show()
        except Exception:
            core.log(u"results window failed:\n{0}".format(traceback.format_exc()))


def _thickness(left, top, right, bottom):
    from System.Windows import Thickness
    return Thickness(left, top, right, bottom)


def thickness(left, top, right, bottom):
    return _thickness(left, top, right, bottom)


def make_timer(milliseconds, callback):
    """A DispatcherTimer that fires once. Used for the modeless-engine proof:
    if the engine has been torn down the callback never runs."""
    from System import TimeSpan
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(milliseconds)

    def tick(sender, args):
        try:
            timer.Stop()
        except Exception:
            pass
        try:
            callback()
        except Exception:
            pass
    timer.Tick += tick
    timer.Start()
    return timer


def mouse_down():
    try:
        from System.Windows.Input import Mouse
        return Mouse.LeftButton == MouseButtonState.Pressed
    except Exception:
        return False
