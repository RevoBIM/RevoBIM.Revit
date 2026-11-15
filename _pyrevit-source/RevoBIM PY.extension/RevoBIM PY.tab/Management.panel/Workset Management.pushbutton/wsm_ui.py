# -*- coding: utf-8 -*-
"""RevoBIM PY - Workset Management : window furniture shared by every window.

XAML loading, the palette swap, the chrome (drag, eight resize grips, full
screen by bounds, F11), the icon, the easter egg, and the small themed
dialogs - message, confirm, text prompt, pick one, and the delete dialog.
"""

import os
import sys

import wsm_clr  # noqa: F401  (assemblies first)

from System import Action, TimeSpan                                    # noqa: E402
from System.IO import File, MemoryStream, StringReader                 # noqa: E402
from System.Windows import (CornerRadius, FontWeights, FrameworkElement,  # noqa: E402
                            GridLength, GridUnitType, HorizontalAlignment,
                            LogicalTreeHelper,
                            PresentationSource, ResizeMode, TextTrimming,
                            TextWrapping, Thickness, VerticalAlignment, Window,
                            WindowStartupLocation, WindowStyle)
from System.Windows.Controls import (Border, Button, ColumnDefinition,   # noqa: E402
                                     Grid, ListBox, ListBoxItem,
                                     Orientation, RowDefinition,
                                     ScrollBarVisibility, ScrollViewer,
                                     StackPanel, TextBlock, TextBox)
from System.Windows.Controls.Primitives import Thumb                    # noqa: E402
from System.Windows.Input import Cursors, Key, Keyboard                 # noqa: E402
from System.Windows.Interop import WindowInteropHelper                  # noqa: E402
from System.Windows.Markup import XamlReader                            # noqa: E402
from System.Windows.Media import (ColorConverter, FontFamily,            # noqa: E402
                                  SolidColorBrush, VisualTreeHelper)
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage  # noqa: E402
from System.Windows.Threading import DispatcherPriority, DispatcherTimer  # noqa: E402
from System.Xml import XmlReader                                        # noqa: E402

import wsm_core as core                                                 # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_PATH = os.path.join(HERE, "Theme.xaml")
ICON_PATH = os.path.join(HERE, "icon.png")

# The palette in use, so dialogs open in the main window's colours.
CURRENT = {"name": "dark"}

_CACHE = {}


# ================================================================ loading

def read_text(path):
    import io
    handle = io.open(path, "r", encoding="utf-8-sig")
    try:
        return handle.read()
    finally:
        handle.close()


def parse_xaml(path):
    """XamlReader on the file.  Not wpf.LoadComponent: a merged dictionary
    has to go in after parsing, and LoadComponent hides parse errors."""
    return XamlReader.Load(XmlReader.Create(StringReader(read_text(path))))


def theme_dictionary():
    """A fresh copy per window - one parsed dictionary shared between several
    windows' MergedDictionaries is not something to depend on."""
    return parse_xaml(THEME_PATH)


def brush(hex_text):
    cached = _CACHE.get(hex_text)
    if cached is not None:
        return cached
    made = SolidColorBrush(ColorConverter.ConvertFromString(hex_text))
    try:
        made.Freeze()
    except Exception:
        pass
    _CACHE[hex_text] = made
    return made


def apply_palette(element, name):
    """Write the palette onto the element's own resources, in front of the
    merged Theme.xaml, so every DynamicResource re-resolves on the spot."""
    if name not in core.PALETTES:
        name = "dark"
    palette = core.PALETTES[name]
    for key in palette:
        try:
            element.Resources[key] = brush(palette[key])
        except Exception:
            continue
    CURRENT["name"] = name
    return name


def prepare(window):
    window.Resources.MergedDictionaries.Add(theme_dictionary())
    apply_palette(window, CURRENT.get("name", "dark"))
    return window


def load_window(path):
    return prepare(parse_xaml(path))


def res(element, prop, key):
    element.SetResourceReference(prop, key)
    return element


def style(element, key):
    element.SetResourceReference(FrameworkElement.StyleProperty, key)
    return element


def load_icon(path=None):
    """Bytes into a BitmapImage - never System.Uri, which moved at 2025."""
    try:
        path = path or ICON_PATH
        if not os.path.isfile(path):
            return None
        image = BitmapImage()
        image.BeginInit()
        image.StreamSource = MemoryStream(File.ReadAllBytes(path))
        image.CacheOption = BitmapCacheOption.OnLoad
        image.EndInit()
        image.Freeze()
        return image
    except Exception:
        return None


def later(window, func, priority=None):
    """Run func after the current event has finished."""
    try:
        window.Dispatcher.BeginInvoke(priority or DispatcherPriority.Background,
                                      Action(func))
    except Exception:
        func()


def debounce(milliseconds, func):
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(milliseconds)

    def tick(sender, args):
        timer.Stop()
        func()
    timer.Tick += tick
    return timer


def repeat(milliseconds, handler):
    """A running timer calling handler(sender, args) every interval."""
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromMilliseconds(milliseconds)
    timer.Tick += handler
    timer.Start()
    return timer


def own(window, uiapp):
    """Owned by Revit's main window, so a modeless window floats in front of
    Revit instead of slipping behind it.  Before Show()."""
    try:
        WindowInteropHelper(window).Owner = uiapp.MainWindowHandle
    except Exception:
        pass


def kick(timer):
    timer.Stop()
    timer.Start()


def text_block(text, size=12, key="TextBrush", bold=False, wrap=False):
    block = TextBlock()
    block.Text = core.to_text(text)
    block.FontSize = size
    block.VerticalAlignment = VerticalAlignment.Center
    res(block, TextBlock.ForegroundProperty, key)
    if bold:
        block.FontWeight = FontWeights.SemiBold
    if wrap:
        block.TextWrapping = TextWrapping.Wrap
    else:
        block.TextTrimming = TextTrimming.CharacterEllipsis
    return block


def is_within(source, targets, stop):
    """True when source sits inside any of targets, walking up to stop."""
    node = source
    for _ in range(60):
        if node is None or node is stop:
            return False
        for target in targets:
            if node is target:
                return True
        parent = None
        try:
            parent = VisualTreeHelper.GetParent(node)
        except Exception:
            parent = None
        if parent is None:
            try:
                parent = LogicalTreeHelper.GetParent(node)
            except Exception:
                parent = None
        node = parent
    return False


def ancestor(source, kind, stop=None):
    """The nearest element of type kind at or above source, or None."""
    node = source
    for _ in range(60):
        if node is None or node is stop:
            return None
        if isinstance(node, kind):
            return node
        parent = None
        try:
            parent = VisualTreeHelper.GetParent(node)
        except Exception:
            parent = None
        if parent is None:
            try:
                parent = LogicalTreeHelper.GetParent(node)
            except Exception:
                parent = None
        node = parent
    return None


def text_box_has_focus():
    try:
        return isinstance(Keyboard.FocusedElement, TextBox)
    except Exception:
        return False


# ================================================================ chrome

class Chrome(object):
    """Drag by the header, eight resize grips, full screen by bounds.

    A borderless AllowsTransparency window has nothing hit-testable in its
    frame, so WPF never resizes it - hence the grips.  Full screen replaces
    the bounds with the working area of the screen the window is on, divided
    by the DPI scale; WindowState.Maximized would cover the task bar and land
    on the primary monitor."""

    GRIP = 5

    def __init__(self, window, header, grip_layer, full_button, skip, on_change=None):
        self.window = window
        self.header = header
        self.skip = list(skip)
        self.on_change = on_change
        self.full = False
        self.saved = None
        header.MouseLeftButtonDown += self.on_header_down
        window.PreviewKeyDown += self.on_key
        if full_button is not None:
            full_button.Click += self.on_full_click
            self.skip.append(full_button)
        if grip_layer is not None:
            self.add_grips(grip_layer)

    def add_grips(self, layer):
        g = self.GRIP
        specs = [
            ("left", HorizontalAlignment.Left, VerticalAlignment.Stretch, g, None, Cursors.SizeWE),
            ("right", HorizontalAlignment.Right, VerticalAlignment.Stretch, g, None, Cursors.SizeWE),
            ("top", HorizontalAlignment.Stretch, VerticalAlignment.Top, None, g, Cursors.SizeNS),
            ("bottom", HorizontalAlignment.Stretch, VerticalAlignment.Bottom, None, g, Cursors.SizeNS),
            ("topleft", HorizontalAlignment.Left, VerticalAlignment.Top, g * 2, g * 2, Cursors.SizeNWSE),
            ("topright", HorizontalAlignment.Right, VerticalAlignment.Top, g * 2, g * 2, Cursors.SizeNESW),
            ("bottomleft", HorizontalAlignment.Left, VerticalAlignment.Bottom, g * 2, g * 2, Cursors.SizeNESW),
            ("bottomright", HorizontalAlignment.Right, VerticalAlignment.Bottom, g * 2, g * 2, Cursors.SizeNWSE),
        ]
        for side, h_align, v_align, width, height, cursor in specs:
            thumb = Thumb()
            style(thumb, "WsGrip")
            thumb.HorizontalAlignment = h_align
            thumb.VerticalAlignment = v_align
            if width is not None:
                thumb.Width = width
            if height is not None:
                thumb.Height = height
            thumb.Cursor = cursor
            thumb.DragDelta += self.make_drag(side)
            layer.Children.Add(thumb)

    def make_drag(self, side):
        def handler(sender, args):
            try:
                self.resize(side, args.HorizontalChange, args.VerticalChange)
            except Exception:
                pass
        return handler

    def resize(self, side, dx, dy):
        window = self.window
        if self.full:
            self.full = False
            self.saved = None
        if "left" in side:
            width = max(window.MinWidth, window.Width - dx)
            window.Left += window.Width - width
            window.Width = width
        if "right" in side:
            window.Width = max(window.MinWidth, window.Width + dx)
        if "top" in side:
            height = max(window.MinHeight, window.Height - dy)
            window.Top += window.Height - height
            window.Height = height
        if "bottom" in side:
            window.Height = max(window.MinHeight, window.Height + dy)

    def on_header_down(self, sender, args):
        try:
            if is_within(args.OriginalSource, self.skip, self.header):
                return
            if args.ClickCount == 2:
                self.toggle()
                return
            if self.full:
                self.leave_full()
            self.window.DragMove()
        except Exception:
            pass

    def on_key(self, sender, args):
        try:
            if args.Key == Key.F11:
                self.toggle()
                args.Handled = True
            elif args.Key == Key.Escape and self.full:
                self.leave_full()
                args.Handled = True
        except Exception:
            pass

    def on_full_click(self, sender, args):
        self.toggle()

    def toggle(self):
        if self.full:
            self.leave_full()
        else:
            self.enter_full()

    def work_area(self):
        """The working area of the screen the window is on, in WPF units."""
        from System.Windows.Forms import Screen
        handle = WindowInteropHelper(self.window).Handle
        area = Screen.FromHandle(handle).WorkingArea
        scale_x, scale_y = 1.0, 1.0
        try:
            source = PresentationSource.FromVisual(self.window)
            matrix = source.CompositionTarget.TransformToDevice
            scale_x, scale_y = matrix.M11, matrix.M22
        except Exception:
            pass
        return (area.Left / scale_x, area.Top / scale_y,
                area.Width / scale_x, area.Height / scale_y)

    def enter_full(self):
        try:
            left, top, width, height = self.work_area()
        except Exception:
            return
        window = self.window
        self.saved = (window.Left, window.Top, window.Width, window.Height)
        window.Left, window.Top, window.Width, window.Height = left, top, width, height
        self.full = True

    def leave_full(self):
        if self.saved is not None:
            window = self.window
            window.Left, window.Top, window.Width, window.Height = self.saved
        self.saved = None
        self.full = False


# ================================================================ easter egg

def _add_lib_path():
    ext = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
    lib = os.path.join(ext, "lib")
    if os.path.isdir(lib) and lib not in sys.path:
        sys.path.append(lib)


class LogoClicks(object):
    """Three slow clicks on the logo - each gap 0.25 to 2 seconds.  A repeat
    of the same timestamp counts once; a gap outside the window, or a click
    anywhere else in the window, starts again."""

    def __init__(self, hook, window, logo, theme):
        self.hook = hook
        self.window = window
        self.logo = logo
        self.theme = theme
        self.stamps = []

    def on_logo(self, sender, args):
        try:
            stamp = args.Timestamp
            if self.stamps and stamp == self.stamps[-1]:
                return
            if self.stamps:
                gap = stamp - self.stamps[-1]
                if gap < 250 or gap > 2000:
                    self.stamps = []
            self.stamps.append(stamp)
            args.Handled = True                 # the logo never drags the window
            if len(self.stamps) >= 3:
                self.stamps = []
                self.hook.launch(self.window, self.theme(), "pacman")
        except Exception:
            self.stamps = []

    def on_window(self, sender, args):
        try:
            if not is_within(args.OriginalSource, [self.logo], self.window):
                self.stamps = []
        except Exception:
            self.stamps = []


def attach_egg(window, logo, theme):
    """The easter egg on the RevoBIM logo only.  The shared egg_hook.attach
    arms the whole window - clicks on rows and headings counted towards the
    game (found in Level Manager) - so only egg_hook.launch is used, behind a
    counter on the logo.  theme is a callable, so a palette swap takes the
    game with it.  Cosmetic: never allowed to fail."""
    try:
        _add_lib_path()
        from revobim.egg import egg_hook
    except Exception:
        return None
    try:
        counter = LogoClicks(egg_hook, window, logo, theme)
        logo.MouseLeftButtonDown += counter.on_logo
        window.PreviewMouseLeftButtonDown += counter.on_window
        return counter
    except Exception:
        return None


# ================================================================ dialogs

class Dialog(object):
    """A themed, borderless child window: header with logo, title and
    version; a body; a footer of buttons on the right."""

    def __init__(self, owner, title, width, height):
        window = Window()
        window.WindowStyle = getattr(WindowStyle, "None")
        window.AllowsTransparency = True
        window.Background = brush("#00000000")
        window.ResizeMode = ResizeMode.NoResize
        window.ShowInTaskbar = False
        window.Width = width
        window.Height = height
        window.Title = title
        if owner is not None:
            try:
                window.Owner = owner
                window.WindowStartupLocation = WindowStartupLocation.CenterOwner
            except Exception:
                window.WindowStartupLocation = WindowStartupLocation.CenterScreen
        else:
            window.WindowStartupLocation = WindowStartupLocation.CenterScreen
        prepare(window)
        self.window = window
        self.result = None

        frame = Border()
        res(frame, Border.BackgroundProperty, "WindowBrush")
        res(frame, Border.BorderBrushProperty, "ChromeBrush")
        frame.BorderThickness = Thickness(1)
        frame.CornerRadius = CornerRadius(6)
        window.Content = frame

        layout = Grid()
        for spec in (GridLength(46), GridLength(1, GridUnitType.Star), GridLength(50)):
            row = RowDefinition()
            row.Height = spec
            layout.RowDefinitions.Add(row)
        frame.Child = layout

        header = Border()
        res(header, Border.BackgroundProperty, "BarBrush")
        header.CornerRadius = CornerRadius(5, 5, 0, 0)
        header.Padding = Thickness(14, 0, 6, 0)
        layout.Children.Add(header)
        bar = Grid()
        for spec in (GridLength(1, GridUnitType.Auto), GridLength(1, GridUnitType.Star),
                     GridLength(1, GridUnitType.Auto), GridLength(1, GridUnitType.Auto)):
            column = ColumnDefinition()
            column.Width = spec
            bar.ColumnDefinitions.Add(column)
        header.Child = bar

        brand = StackPanel()
        brand.Orientation = Orientation.Horizontal
        brand.VerticalAlignment = VerticalAlignment.Center
        brand.Background = brush("#00000000")
        logo = text_block(u"RevoBIM", 16, "BlueBrush", True)
        logo.FontWeight = FontWeights.Bold
        brand.Children.Add(logo)
        brand.Children.Add(text_block(u"   " + title, 13, "OrangeBrush"))
        bar.Children.Add(brand)
        self.logo = brand

        version = text_block(u"v" + core.VERSION, 11, "MutedBrush")
        version.Margin = Thickness(0, 0, 10, 0)
        Grid.SetColumn(version, 2)
        bar.Children.Add(version)

        close = Button()
        style(close, "WsCloseButton")
        close.Content = u"\u2715"
        close.Click += self.on_cancel
        Grid.SetColumn(close, 3)
        bar.Children.Add(close)

        def drag(sender, args):
            try:
                if not is_within(args.OriginalSource, [close, brand], header):
                    window.DragMove()
            except Exception:
                pass
        header.MouseLeftButtonDown += drag

        self.body = StackPanel()
        self.body.Margin = Thickness(16, 12, 16, 6)
        scroller = ScrollViewer()
        scroller.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        scroller.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
        scroller.Content = self.body
        Grid.SetRow(scroller, 1)
        layout.Children.Add(scroller)

        footer = Border()
        res(footer, Border.BackgroundProperty, "BarBrush")
        footer.CornerRadius = CornerRadius(0, 0, 5, 5)
        footer.Padding = Thickness(14, 0, 14, 0)
        Grid.SetRow(footer, 2)
        layout.Children.Add(footer)
        self.footer = StackPanel()
        self.footer.Orientation = Orientation.Horizontal
        self.footer.HorizontalAlignment = HorizontalAlignment.Right
        self.footer.VerticalAlignment = VerticalAlignment.Center
        footer.Child = self.footer

        window.PreviewKeyDown += self.on_key
        attach_egg(window, brand, lambda: CURRENT.get("name", "dark"))

    def button(self, text, key="WsButton", handler=None, width=96):
        made = Button()
        style(made, key)
        made.Content = text
        made.MinWidth = width
        made.Margin = Thickness(8, 0, 0, 0)
        if handler is not None:
            made.Click += handler
        self.footer.Children.Add(made)
        return made

    def add(self, element):
        self.body.Children.Add(element)
        return element

    def text(self, text, key="TextBrush", size=12, bold=False, margin=None):
        block = text_block(text, size, key, bold, wrap=True)
        block.Margin = margin or Thickness(0, 0, 0, 8)
        return self.add(block)

    def on_cancel(self, sender, args):
        self.result = None
        self.window.Close()

    def on_key(self, sender, args):
        try:
            if args.Key == Key.Escape and not text_box_has_focus():
                self.result = None
                self.window.Close()
                args.Handled = True
        except Exception:
            pass

    def close_with(self, value):
        self.result = value
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.result


def message(owner, title, lines, width=640, height=460):
    """Results go here, never to the pyRevit output window."""
    dialog = Dialog(owner, title, width, height)
    if isinstance(lines, (list, tuple)):
        lines = u"\n".join([core.to_text(line) for line in lines])
    box = TextBox()
    style(box, "WsTextBox")
    box.Text = core.to_text(lines)
    box.IsReadOnly = True
    box.AcceptsReturn = True
    box.TextWrapping = TextWrapping.Wrap
    box.VerticalContentAlignment = VerticalAlignment.Top
    box.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    box.Height = height - 130
    box.FontFamily = FontFamily("Consolas")
    dialog.add(box)
    dialog.button(u"Close", "WsButton", lambda s, a: dialog.close_with(True))
    dialog.show()


def confirm(owner, title, text, lines=None, yes=u"Apply", no=u"Cancel",
            yes_key="WsGreenButton", width=600, height=420):
    dialog = Dialog(owner, title, width, height)
    dialog.text(text)
    if lines:
        box = TextBox()
        style(box, "WsTextBox")
        box.Text = u"\n".join([core.to_text(line) for line in lines])
        box.IsReadOnly = True
        box.AcceptsReturn = True
        box.TextWrapping = TextWrapping.NoWrap
        box.VerticalContentAlignment = VerticalAlignment.Top
        box.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        box.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto
        box.Height = height - 170
        dialog.add(box)
    dialog.button(no, "WsButton", lambda s, a: dialog.close_with(False))
    dialog.button(yes, yes_key, lambda s, a: dialog.close_with(True), 120)
    return bool(dialog.show())


def prompt_text(owner, title, label, default=u"", accept=u"Save"):
    dialog = Dialog(owner, title, 460, 210)
    dialog.text(label)
    box = TextBox()
    style(box, "WsTextBox")
    box.Text = core.to_text(default)
    box.Height = 30
    box.FontSize = 13
    dialog.add(box)

    def done(sender, args):
        value = core.to_text(box.Text).strip()
        if value:
            dialog.close_with(value)

    def on_enter(sender, args):
        if args.Key == Key.Enter:
            done(sender, args)
    box.KeyDown += on_enter
    dialog.button(u"Cancel", "WsButton", lambda s, a: dialog.close_with(None))
    dialog.button(accept, "WsGreenButton", done)
    dialog.window.Loaded += lambda s, a: box.Focus()
    return dialog.show()


def themed_list(height=240):
    listing = ListBox()
    style(listing, "WsListBox")
    listing.Height = height
    listing.ItemContainerStyle = listing.TryFindResource("WsListItem")
    return listing


def list_item(listing, label, tag, detail=u""):
    item = ListBoxItem()
    style(item, "WsListItem")
    line = StackPanel()
    line.Orientation = Orientation.Horizontal
    line.Children.Add(text_block(label, 12, "TextBrush"))
    if detail:
        line.Children.Add(text_block(u"   " + detail, 11, "OrangeBrush"))
    item.Content = line
    item.Tag = tag
    listing.Items.Add(item)
    return item


def prompt_choice(owner, title, label, options, accept=u"Load", on_delete=None):
    """Pick one of options.  on_delete(name) -> bool removes one from the list."""
    dialog = Dialog(owner, title, 480, 420)
    dialog.text(label)
    listing = themed_list(250)
    for option in options:
        list_item(listing, option, option)
    dialog.add(listing)

    def done(sender, args):
        item = listing.SelectedItem
        if item is not None:
            dialog.close_with(core.to_text(item.Tag))

    def remove(sender, args):
        item = listing.SelectedItem
        if item is not None and on_delete is not None and on_delete(core.to_text(item.Tag)):
            listing.Items.Remove(item)

    listing.MouseDoubleClick += done
    if on_delete is not None:
        dialog.button(u"Delete", "WsRedButton", remove)
    dialog.button(u"Cancel", "WsButton", lambda s, a: dialog.close_with(None))
    dialog.button(accept, "WsGreenButton", done)
    return dialog.show()


def delete_dialog(owner, deleting, targets):
    """deleting / targets: WsRow lists.  -> the key of the workset taking the
    elements, or None.  Nothing is deleted here - it is staged."""
    total = sum([row.count for row in deleting])
    dialog = Dialog(owner, u"Delete worksets", 560, 560)
    dialog.text(u"{0} workset{1} will be deleted when you press Apply. Nothing is "
                u"deleted from the model until then.".format(
                    len(deleting), u"" if len(deleting) == 1 else u"s"))

    listing = StackPanel()
    listing.Margin = Thickness(4, 0, 0, 10)
    for row in deleting[:14]:
        line = StackPanel()
        line.Orientation = Orientation.Horizontal
        line.Children.Add(text_block(row.orig or row.name, 12, "RedBrush", True))
        line.Children.Add(text_block(u"   {0} elements".format(row.count), 11, "OrangeBrush"))
        listing.Children.Add(line)
    if len(deleting) > 14:
        listing.Children.Add(text_block(u"... and {0} more".format(len(deleting) - 14),
                                        11, "MutedBrush"))
    dialog.add(listing)

    if total:
        dialog.text(u"Move all {0} of their elements onto:".format(total), "TextBrush",
                    12, True)
    else:
        dialog.text(u"They are empty. Revit still asks where elements would go, so "
                    u"pick a workset - nothing will move.", "MutedBrush", 11)

    search = TextBox()
    style(search, "WsTextBox")
    search.Tag = u"Filter worksets"
    search.Height = 28
    search.Margin = Thickness(0, 0, 0, 6)
    dialog.add(search)

    choices = themed_list(220)
    dialog.add(choices)

    def fill(needle):
        choices.Items.Clear()
        for row in targets:
            if core.text_match(row.effective_name(), needle):
                detail = u"{0} elements".format(row.count) if not row.is_new else u"new"
                list_item(choices, row.effective_name(), row.key, detail)
        if choices.Items.Count == 1:
            choices.SelectedIndex = 0
    fill(u"")
    search.TextChanged += lambda s, a: fill(search.Text)

    def done(sender, args):
        item = choices.SelectedItem
        if item is not None:
            dialog.close_with(core.to_text(item.Tag))

    choices.MouseDoubleClick += done
    dialog.button(u"Cancel", "WsButton", lambda s, a: dialog.close_with(None))
    dialog.button(u"Stage delete", "WsRedButton", done, 120)
    return dialog.show()


def merge_dialog(owner, rows):
    """rows: the WsRows being merged.  -> the key of the master, or None.
    Nothing is merged here - it is staged."""
    dialog = Dialog(owner, u"Merge worksets", 540, 520)
    dialog.text(u"Which workset is the master? The others move all of their elements "
                u"onto it and are then deleted, when you press Apply. Any rename staged "
                u"on the master is kept.")
    total = sum([row.count for row in rows])
    dialog.text(u"{0} worksets, {1} elements between them.".format(len(rows), total),
                "MutedBrush", 11)
    choices = themed_list(300)
    ordered = sorted(rows, key=lambda r: (-r.count, core.natural_key(r.effective_name())))
    for row in ordered:
        item = ListBoxItem()
        style(item, "WsListItem")
        line = StackPanel()
        line.Orientation = Orientation.Horizontal
        swatch = Border()
        swatch.Width = 13
        swatch.Height = 13
        swatch.CornerRadius = CornerRadius(3)
        swatch.Margin = Thickness(0, 0, 8, 0)
        swatch.Background = brush(row.colour if row.colour.startswith(u"#") else u"#00000000")
        res(swatch, Border.BorderBrushProperty, "EdgeBrush")
        swatch.BorderThickness = Thickness(1)
        line.Children.Add(swatch)
        line.Children.Add(text_block(row.effective_name(), 12, "TextBrush", True))
        line.Children.Add(text_block(u"   new" if row.is_new else
                                     u"   {0} elements".format(row.count), 11, "OrangeBrush"))
        item.Content = line
        item.Tag = row.key
        choices.Items.Add(item)
    choices.SelectedIndex = 0
    dialog.add(choices)

    def done(sender, args):
        item = choices.SelectedItem
        if item is not None:
            dialog.close_with(core.to_text(item.Tag))

    choices.MouseDoubleClick += done
    dialog.button(u"Cancel", "WsButton", lambda s, a: dialog.close_with(None))
    dialog.button(u"Stage merge", "WsOrangeButton", done, 120)
    return dialog.show()
