# -*- coding: utf-8 -*-
"""Auto RevCloud - window plumbing shared by every window in the tool:
XAML loading, the palette, the borderless chrome, full screen, resize grips,
the owner handle and the themed prompt."""
import os
import arc_clr  # noqa: F401
import arc_core
import theme

from System import Action
from System.IO import StringReader, File, MemoryStream
from System.Xml import XmlReader
from System.Windows import (Visibility, Thickness, GridLength, GridUnitType,
                            HorizontalAlignment)
from System.Windows.Controls import (TextBlock, Grid, ColumnDefinition, ListBoxItem,
                                     Button)
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, Color
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Interop import WindowInteropHelper, HwndSource
from System.Windows.Input import Key
from System.Windows.Threading import DispatcherPriority
from System.Windows.Forms import Screen
from System.Drawing import Point
from System.Diagnostics import Process

HERE = os.path.dirname(os.path.abspath(__file__))


# ==========================================================================
# loading
# ==========================================================================

def read_text(name):
    return File.ReadAllText(os.path.join(HERE, name))


def load_xaml(name):
    """XamlReader through an XmlReader over a string, so no file path or
    URI ever reaches WPF."""
    reader = XmlReader.Create(StringReader(read_text(name)))
    return XamlReader.Load(reader)


def theme_dictionary():
    """A fresh Theme.xaml ResourceDictionary per window - a dictionary can
    only be merged into one owner."""
    return load_xaml(u"Theme.xaml")


def load_window(name):
    window = load_xaml(name)
    window.Resources.MergedDictionaries.Add(theme_dictionary())
    return window


def brush(hex_text):
    text = arc_core.unicode_str(hex_text).strip().lstrip(u"#")
    if len(text) == 6:
        text = u"FF" + text
    a = int(text[0:2], 16)
    r = int(text[2:4], 16)
    g = int(text[4:6], 16)
    b = int(text[6:8], 16)
    result = SolidColorBrush(Color.FromArgb(a, r, g, b))
    try:
        result.Freeze()
    except Exception:
        pass
    return result


def apply_palette(window, palette_name):
    """Write the palette onto window.Resources, in front of the merged
    Theme.xaml, so an open window re-themes with no reload."""
    palette = theme.palette_for(palette_name)
    for key, value in palette.items():
        window.Resources[key] = brush(value)
    window.Tag = palette_name


def palette_brush(window, key):
    try:
        found = window.Resources[key]
        if found is not None:
            return found
    except Exception:
        pass
    try:
        return window.FindResource(key)
    except Exception:
        return brush(theme.DARK.get(key, u"#FFFFFF"))


def load_icon(path):
    """BitmapImage from bytes through a MemoryStream - no System.Uri, which
    moved assemblies in 2025."""
    try:
        data = File.ReadAllBytes(path)
        stream = MemoryStream(data)
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


def set_owner(window, uiapp):
    """Own the window to Revit's main window so it floats above Revit
    rather than slipping behind it."""
    try:
        handle = uiapp.MainWindowHandle
        helper = WindowInteropHelper(window)
        helper.Owner = handle
        return True
    except Exception:
        pass
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = Process.GetCurrentProcess().MainWindowHandle
        return True
    except Exception:
        return False


def focus_revit(window=None):
    """Put Revit back in front.

    Closing this window should hand activation back to Revit, because the
    window is owned by Revit's main window. It does not always: browsing for
    a file dialog opens a shell window, and Windows can then hand activation to an
    Explorer window the user already had open rather than to the owner. Which
    is how ticking "open the sheets" ended up looking at File Explorer.

    AppActivate is the managed way to raise a process's own main window - no
    P/Invoke, and it is only ever pointed at Revit's own process id. Guarded
    because the assembly moved between .NET Framework 4.8 (Revit 2024) and
    .NET 8 (2025+), and a failure here is cosmetic.
    """
    try:
        if window is not None:
            # Owned by Revit, so raising it raises Revit's group.
            window.Activate()
    except Exception:
        pass
    try:
        from Microsoft.VisualBasic import Interaction
        Interaction.AppActivate(Process.GetCurrentProcess().Id)
        return True
    except Exception:
        pass
    return False


def pump(window):
    """Let the dispatcher paint.  Never call this inside an open
    transaction."""
    try:
        window.Dispatcher.Invoke(DispatcherPriority.Background, Action(lambda: None))
    except Exception:
        pass


# ==========================================================================
# chrome: drag, close, full screen, grips, version
# ==========================================================================

class Chrome(object):
    """Installs the borderless window behaviour on a loaded window.

    Header drag, double-click and F11 full screen by bounds (not
    WindowState.Maximized, which covers the taskbar and lands on the wrong
    monitor), Escape leaves full screen, the close button, the eight resize
    grips when the layout has them, and the version in the top right.
    """

    def __init__(self, window, version=None, on_close=None, escape_closes=False):
        self.window = window
        self.on_close = on_close
        self.escape_closes = escape_closes
        self.full = False
        self.saved = None
        self.find = window.FindName
        header = self.find(u"Header")
        if header is not None:
            header.MouseLeftButtonDown += self.on_header_down
        close = self.find(u"CloseButton")
        if close is not None:
            close.Click += self.on_close_click
        full = self.find(u"FullScreenButton")
        if full is not None:
            full.Click += self.on_full_click
        version_text = self.find(u"VersionText")
        if version_text is not None:
            version_text.Text = u"v{0}".format(version or arc_core.__version__)
        window.PreviewKeyDown += self.on_key
        self.install_grips()

    # ---- events --------------------------------------------------------
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

    def on_close_click(self, sender, args):
        self.close()

    def on_full_click(self, sender, args):
        self.toggle_full()

    def on_key(self, sender, args):
        try:
            if args.Key == Key.F11:
                self.toggle_full()
                args.Handled = True
            elif args.Key == Key.Escape:
                if self.full:
                    self.leave_full()
                    args.Handled = True
                elif self.escape_closes:
                    self.close()
                    args.Handled = True
        except Exception:
            pass

    def close(self):
        if self.on_close is not None:
            try:
                if self.on_close() is False:
                    return
            except Exception:
                pass
        try:
            self.window.Close()
        except Exception:
            pass

    # ---- full screen by bounds -----------------------------------------
    def dpi_scale(self):
        try:
            source = HwndSource.FromVisual(self.window)
            matrix = source.CompositionTarget.TransformToDevice
            return matrix.M11, matrix.M22
        except Exception:
            return 1.0, 1.0

    def toggle_full(self):
        if self.full:
            self.leave_full()
        else:
            self.enter_full()

    def enter_full(self):
        window = self.window
        try:
            self.saved = (window.Left, window.Top, window.Width, window.Height)
            sx, sy = self.dpi_scale()
            centre_x = int((window.Left + window.Width / 2.0) * sx)
            centre_y = int((window.Top + window.Height / 2.0) * sy)
            screen = Screen.FromPoint(Point(centre_x, centre_y))
            area = screen.WorkingArea
            window.Left = area.Left / sx
            window.Top = area.Top / sy
            window.Width = area.Width / sx
            window.Height = area.Height / sy
            self.full = True
            grips = self.find(u"Grips")
            if grips is not None:
                grips.Visibility = Visibility.Collapsed
        except Exception:
            self.full = False

    def leave_full(self):
        window = self.window
        if self.saved is not None:
            try:
                window.Left, window.Top, window.Width, window.Height = self.saved
            except Exception:
                pass
        self.full = False
        grips = self.find(u"Grips")
        if grips is not None:
            grips.Visibility = Visibility.Visible

    # ---- grips ---------------------------------------------------------
    def install_grips(self):
        spec = {
            u"GripLeft": (1, 0, 0, 0), u"GripRight": (0, 0, 1, 0),
            u"GripTop": (0, 1, 0, 0), u"GripBottom": (0, 0, 0, 1),
            u"GripTopLeft": (1, 1, 0, 0), u"GripTopRight": (0, 1, 1, 0),
            u"GripBottomLeft": (1, 0, 0, 1), u"GripBottomRight": (0, 0, 1, 1),
        }
        for name, edges in spec.items():
            thumb = self.find(name)
            if thumb is None:
                continue
            thumb.DragDelta += self.make_drag(edges)

    def make_drag(self, edges):
        left, top, right, bottom = edges

        def handler(sender, args):
            window = self.window
            if self.full:
                self.leave_full()
            try:
                min_w = window.MinWidth or 200
                min_h = window.MinHeight or 150
                if right:
                    window.Width = max(min_w, window.Width + args.HorizontalChange)
                if bottom:
                    window.Height = max(min_h, window.Height + args.VerticalChange)
                if left:
                    new_w = window.Width - args.HorizontalChange
                    if new_w >= min_w:
                        window.Left = window.Left + args.HorizontalChange
                        window.Width = new_w
                if top:
                    new_h = window.Height - args.VerticalChange
                    if new_h >= min_h:
                        window.Top = window.Top + args.VerticalChange
                        window.Height = new_h
            except Exception:
                pass
        return handler


# ==========================================================================
# prompts
# ==========================================================================

def ask_text(owner, title, question, initial=u"", palette=u"dark"):
    u"""Ask for one line of text. Returns the text, or None if cancelled.

    Built on the prompt window rather than a layout of its own - it is the
    same window with its message box made editable, and one fewer layout is
    one fewer thing that can fail to parse.
    """
    window = load_window(u"ArcPrompt.xaml")
    apply_palette(window, palette)
    find = window.FindName
    find(u"TitleText").Text = title
    box = find(u"MessageBox")
    box.Text = arc_core.unicode_str(initial)
    box.IsReadOnly = False
    try:
        box.AcceptsReturn = False
        box.ToolTip = question
    except Exception:
        pass
    try:
        find(u"StatusText").Text = question
    except Exception:
        pass
    yes = find(u"YesButton")
    no = find(u"NoButton")
    yes.Content = u"Save"
    no.Content = u"Cancel"
    no.Visibility = Visibility.Visible
    outcome = {u"text": None}

    def on_yes(sender, args):
        outcome[u"text"] = arc_core.unicode_str(box.Text).strip()
        window.Close()

    def on_no(sender, args):
        outcome[u"text"] = None
        window.Close()

    yes.Click += on_yes
    no.Click += on_no
    Chrome(window, escape_closes=True)
    if owner is not None:
        try:
            window.Owner = owner
        except Exception:
            pass
    try:
        box.Focus()
        box.SelectAll()
    except Exception:
        pass
    try:
        window.ShowDialog()
    except Exception:
        return None
    return outcome[u"text"] or None


def prompt(owner, title, text, yes_no=False, palette=u"dark", version=None):
    """Themed modal message.  Returns True for OK/Yes, False for No/close."""
    window = load_window(u"ArcPrompt.xaml")
    apply_palette(window, palette)
    find = window.FindName
    find(u"TitleText").Text = title
    find(u"MessageBox").Text = text
    yes = find(u"YesButton")
    no = find(u"NoButton")
    outcome = {u"ok": False}

    def on_yes(sender, args):
        outcome[u"ok"] = True
        window.Close()

    def on_no(sender, args):
        outcome[u"ok"] = False
        window.Close()

    yes.Click += on_yes
    no.Click += on_no
    if yes_no:
        yes.Content = u"Yes"
        no.Visibility = Visibility.Visible
    else:
        yes.Content = u"OK"
        no.Visibility = Visibility.Collapsed
    Chrome(window, version=version, escape_closes=True)
    if owner is not None:
        try:
            window.Owner = owner
        except Exception:
            pass
    try:
        window.ShowDialog()
    except Exception:
        return False
    return outcome[u"ok"]


# ==========================================================================
# rows built in code (WPF is never asked to read a Python attribute)
# ==========================================================================

def add_row_button(window, item, column, text, handler, tooltip=None):
    """Put a themed button into one column of a row made by make_row.

    Built in code rather than templated, for the same reason the rows are:
    WPF is never asked to read a Python attribute anywhere in this tool. A
    bare WPF Button has no implicit style, so it would come out as an OS grey
    lozenge in a dark row - the style has to be fetched and applied by hand.
    """
    try:
        button = Button()
        button.Content = arc_core.unicode_str(text)
        button.Padding = Thickness(8, 1, 8, 1)
        button.Margin = Thickness(0, 1, 4, 1)
        button.HorizontalAlignment = HorizontalAlignment.Stretch
        try:
            button.Style = window.FindResource(u"ArcSmallButton")
        except Exception:
            pass
        if tooltip:
            button.ToolTip = tooltip
        button.Click += handler
        grid = item.Content
        Grid.SetColumn(button, column)
        grid.Children.Add(button)
        return button
    except Exception:
        return None


def make_row(window, widths, texts, colours=None, tooltip=None):
    """A ListBoxItem holding a Grid of TextBlocks.  widths: list of ints
    (pixels) or '*' ; texts: list of strings; colours: list of palette keys
    or None per cell."""
    grid = Grid()
    for width in widths:
        column = ColumnDefinition()
        if width == u"*":
            column.Width = GridLength(1, GridUnitType.Star)
        else:
            column.Width = GridLength(float(width))
        grid.ColumnDefinitions.Add(column)
    blocks = []
    for index, text in enumerate(texts):
        block = TextBlock()
        block.Text = arc_core.unicode_str(text)
        block.Margin = Thickness(0, 0, 6, 0)
        try:
            block.Style = window.FindResource(u"ArcText")
        except Exception:
            pass
        key = None
        if colours and index < len(colours):
            key = colours[index]
        if key:
            block.SetResourceReference(TextBlock.ForegroundProperty, key)
        Grid.SetColumn(block, index)
        grid.Children.Add(block)
        blocks.append(block)
    item = ListBoxItem()
    item.Content = grid
    if tooltip:
        item.ToolTip = tooltip
    item.Tag = blocks
    return item


def set_cell(item, index, text, colour_key=None):
    """Update one cell of a row made by make_row."""
    try:
        blocks = item.Tag
        block = blocks[index]
        block.Text = arc_core.unicode_str(text)
        if colour_key:
            block.SetResourceReference(TextBlock.ForegroundProperty, colour_key)
        else:
            block.SetResourceReference(TextBlock.ForegroundProperty, u"TextBrush")
    except Exception:
        pass
