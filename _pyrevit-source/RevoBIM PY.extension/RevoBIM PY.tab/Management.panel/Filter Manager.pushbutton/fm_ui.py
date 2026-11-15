# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : themed widget builders.

Rows are built as WPF elements in code rather than bound to Python objects -
binding to IronPython objects is unreliable across engine versions.
WPF types are imported inside the functions that need them, so a name
missing on one release cannot kill the module at load.
"""

import fm_clr  # noqa  - must be first


def new_checkbox(text, tag, checked=False):
    from System.Windows.Controls import CheckBox
    cb = CheckBox()
    cb.Content = text
    cb.Tag = tag
    cb.IsChecked = bool(checked)
    return cb


def new_listitem(text, tag):
    from System.Windows.Controls import ListBoxItem
    item = ListBoxItem()
    item.Content = text
    item.Tag = tag
    return item


def new_combo(items, selected_index=-1, width=None, tags=None, height=None):
    """items: display strings.  tags: matching payloads, kept on the item."""
    from System.Windows.Controls import ComboBox, ComboBoxItem
    cb = ComboBox()
    cb.MinHeight = MIN_TEXTBOX_HEIGHT
    if height:
        cb.Height = height
    for i, text in enumerate(items):
        it = ComboBoxItem()
        it.Content = text
        if tags is not None and i < len(tags):
            it.Tag = tags[i]
        cb.Items.Add(it)
    if 0 <= selected_index < cb.Items.Count:
        cb.SelectedIndex = selected_index
    if width:
        cb.Width = width
    return cb


def combo_tag(combo):
    try:
        item = combo.SelectedItem
        if item is not None:
            return item.Tag
    except Exception:
        pass
    return None


def combo_text(combo):
    try:
        item = combo.SelectedItem
        if item is not None:
            return item.Content
    except Exception:
        pass
    return ""


def select_by_tag(combo, wanted, compare=None):
    for i in range(combo.Items.Count):
        tag = combo.Items[i].Tag
        hit = (tag == wanted) if compare is None else compare(tag, wanted)
        if hit:
            combo.SelectedIndex = i
            return True
    return False


# a line of Segoe UI needs about 17px, and the box has to hold that plus
# its padding and its border, or it clips its own descenders
# a line of Segoe UI 12 needs about 17px; the box has to hold that plus its
# padding (5 top and bottom) and its border, so 30 is the floor and a cell
# is given a little more than the floor
MIN_TEXTBOX_HEIGHT = 32

# every cell in a table row is this tall, so a row reads as one row rather
# than as a set of controls that happen to sit next to each other
CELL_HEIGHT = 34


def new_textbox(text="", placeholder=None, width=None):
    from System.Windows.Controls import TextBox
    tb = TextBox()
    tb.Text = u"" if text is None else u"{0}".format(text)
    if placeholder:
        tb.Tag = placeholder
    if width:
        tb.Width = width
    tb.MinHeight = MIN_TEXTBOX_HEIGHT
    tb.VerticalContentAlignment = _center()
    return tb


def _center():
    from System.Windows import VerticalAlignment
    return VerticalAlignment.Center


def new_text(text, brush_key=None, size=12, bold=False, margin=None):
    from System.Windows.Controls import TextBlock
    from System.Windows import FontWeights, Thickness
    tb = TextBlock()
    tb.Text = text
    tb.FontSize = size
    if bold:
        tb.FontWeight = FontWeights.Bold
    if margin is not None:
        tb.Margin = Thickness(*margin)
    if brush_key:
        try:
            from System.Windows.Controls import TextBlock as TB
            tb.SetResourceReference(TB.ForegroundProperty, brush_key)
        except Exception:
            pass
    return tb


def new_button(text, style_key, click=None, width=None, height=None, tag=None):
    from System.Windows.Controls import Button
    from System.Windows import FrameworkElement
    b = Button()
    b.Content = text
    if tag is not None:
        b.Tag = tag
    try:
        b.SetResourceReference(FrameworkElement.StyleProperty, style_key)
    except Exception:
        pass
    if width:
        b.Width = width
    if height:
        b.Height = height
    if click is not None:
        b.Click += click
    return b


def thickness(*args):
    from System.Windows import Thickness
    return Thickness(*args)


def col(width_star=None, pixels=None):
    from System.Windows.Controls import ColumnDefinition
    from System.Windows import GridLength, GridUnitType
    c = ColumnDefinition()
    if pixels is not None:
        c.Width = GridLength(pixels)
    else:
        c.Width = GridLength(width_star or 1, GridUnitType.Star)
    return c


def place(element, grid, column):
    from System.Windows.Controls import Grid
    Grid.SetColumn(element, column)
    grid.Children.Add(element)
    return element


def new_grid(margin=None):
    from System.Windows.Controls import Grid
    g = Grid()
    if margin is not None:
        g.Margin = thickness(*margin)
    return g


def set_visible(element, visible):
    from System.Windows import Visibility
    element.Visibility = Visibility.Visible if visible else Visibility.Collapsed


# ===========================================================================
#  Screens, DPI and full screen
# ===========================================================================
def dpi_scale(window):
    """(x, y) device pixels per WPF unit for the screen the window is on."""
    try:
        from System.Windows import PresentationSource
        src = PresentationSource.FromVisual(window)
        if src is not None:
            m = src.CompositionTarget.TransformToDevice
            sx = m.M11 if m.M11 else 1.0
            sy = m.M22 if m.M22 else 1.0
            return (sx, sy)
    except Exception:
        pass
    return (1.0, 1.0)


def working_area(window):
    """(left, top, width, height) in WPF units of the screen holding the window.

    Screen.WorkingArea is in device pixels and the window's Left/Top/Width/
    Height are in WPF units, so it has to be divided by the DPI scale or it
    overshoots on a scaled display.
    """
    try:
        import clr
        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import Screen
        from System.Windows.Interop import WindowInteropHelper
        handle = WindowInteropHelper(window).Handle
        area = Screen.FromHandle(handle).WorkingArea
        sx, sy = dpi_scale(window)
        return (area.Left / sx, area.Top / sy, area.Width / sx, area.Height / sy)
    except Exception:
        pass
    try:
        from System.Windows import SystemParameters
        r = SystemParameters.WorkArea
        return (r.Left, r.Top, r.Width, r.Height)
    except Exception:
        return (0.0, 0.0, 1280.0, 800.0)


class ScreenState(object):
    """Full screen and vertical maximise by bounds, not WindowState.

    Maximising a borderless window the normal way covers the task bar and
    lands on the wrong monitor.
    """

    def __init__(self, window):
        self.window = window
        self.saved = None          # bounds before full screen
        self.saved_v = None        # bounds before vertical maximise
        self.saved_min = None      # minimums before they were relaxed
        self.full = False
        self.vertical = False

    def relax_minimums(self, width, height):
        """Let the window shrink below its usual minimum.

        WPF honours MinWidth and MinHeight over anything else, so a window
        whose minimum is wider than the screen simply cannot go full screen -
        it stays too big and hangs off the edge. The minimum has to come
        down with the size.
        """
        import fm_core
        window = self.window
        if self.saved_min is None:
            self.saved_min = (window.MinWidth, window.MinHeight)
        _w, min_w = fm_core.shrink_to_fit(window.Width, window.MinWidth, width)
        _h, min_h = fm_core.shrink_to_fit(window.Height, window.MinHeight,
                                          height)
        window.MinWidth = min_w
        window.MinHeight = min_h

    def restore_minimums(self):
        if self.saved_min is None:
            return
        try:
            self.window.MinWidth, self.window.MinHeight = self.saved_min
        except Exception:
            pass
        self.saved_min = None

    def fit_to_screen(self):
        """Bring the window onto the screen it opened on, whatever its size."""
        import fm_core
        window = self.window
        left, top, width, height = working_area(window)
        if width <= 0 or height <= 0:
            return
        if window.Width <= width and window.Height <= height \
                and window.MinWidth <= width and window.MinHeight <= height:
            return

        self.relax_minimums(width, height)
        new_w, _min_w = fm_core.shrink_to_fit(window.Width, window.MinWidth,
                                              width)
        new_h, _min_h = fm_core.shrink_to_fit(window.Height, window.MinHeight,
                                              height)
        window.Width = new_w
        window.Height = new_h
        window.Left = max(left, min(window.Left, left + width - new_w))
        window.Top = max(top, min(window.Top, top + height - new_h))

    def _bounds(self):
        w = self.window
        return (w.Left, w.Top, w.Width, w.Height)

    def _restore(self, bounds):
        w = self.window
        w.Left, w.Top, w.Width, w.Height = bounds

    def enter_full(self):
        if self.full:
            return
        self.saved = self._bounds()
        left, top, width, height = working_area(self.window)
        self.relax_minimums(width, height)
        w = self.window
        w.Left, w.Top, w.Width, w.Height = left, top, width, height
        self.full = True
        self.vertical = False

    def exit_full(self):
        if not self.full:
            return
        # the minimums go back first, or restoring the old bounds would be
        # clamped by whatever they were relaxed to
        self.restore_minimums()
        if self.saved:
            self._restore(self.saved)
        self.full = False

    def toggle_full(self):
        if self.full:
            self.exit_full()
        else:
            self.enter_full()

    def toggle_vertical(self):
        """Expand up and down only, keeping the left edge and the width."""
        if self.full:
            self.exit_full()
            return
        w = self.window
        if self.vertical and self.saved_v:
            self.restore_minimums()
            self._restore(self.saved_v)
            self.vertical = False
            return
        self.saved_v = self._bounds()
        _left, top, width, height = working_area(self.window)
        self.relax_minimums(width, height)
        w.Top = top
        w.Height = height
        self.vertical = True

    def break_out(self, args):
        """Leave full screen for a drag, keeping the cursor on the title bar.

        The window shrinks back to its pre-full-screen size and is then
        placed so the pointer sits at the same fraction along the header as
        it did full screen - which is what dragging a maximised window does
        everywhere else.
        """
        if not self.full:
            return
        w = self.window
        fraction, offset_y = 0.5, 18.0
        try:
            pos = args.GetPosition(w)
            if w.ActualWidth:
                fraction = max(0.0, min(1.0, pos.X / w.ActualWidth))
            offset_y = pos.Y
        except Exception:
            pass

        screen_x, screen_y = cursor_on_screen(w)
        self.exit_full()

        try:
            w.Left = screen_x - (fraction * w.Width)
            w.Top = screen_y - offset_y
        except Exception:
            pass


def cursor_on_screen(window):
    """The mouse position in WPF units."""
    try:
        import clr
        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import Cursor
        p = Cursor.Position
        sx, sy = dpi_scale(window)
        return (p.X / sx, p.Y / sy)
    except Exception:
        pass
    try:
        from System.Windows.Input import Mouse
        p = Mouse.GetPosition(window)
        return (window.Left + p.X, window.Top + p.Y)
    except Exception:
        return (window.Left, window.Top)


# ===========================================================================
#  Override property panel
# ===========================================================================
def swatch(hex_text):
    from System.Windows.Controls import Border
    from System.Windows.Media import SolidColorBrush, Color as WpfColour
    from System.Windows import Thickness
    b = Border()
    b.Width = 26
    b.Height = 22
    b.BorderThickness = Thickness(1)
    b.Margin = Thickness(4, 0, 0, 0)
    try:
        b.BorderBrush = pbrush("EdgeStrong")
    except Exception:
        pass
    paint_swatch(b, hex_text)
    return b


def paint_swatch(border, hex_text):
    from System.Windows.Media import SolidColorBrush, Color as WpfColour
    try:
        s = (hex_text or "").strip().lstrip("#")
        if len(s) == 6:
            r = int(s[0:2], 16)
            g = int(s[2:4], 16)
            b = int(s[4:6], 16)
            border.Background = SolidColorBrush(WpfColour.FromRgb(r, g, b))
            return True
    except Exception:
        pass
    try:
        border.Background = pbrush("Field")
    except Exception:
        pass
    return False


def section_header(text, accent_key="Blue"):
    """A label with a 4px coloured tick to its left."""
    from System.Windows.Controls import (StackPanel, Border, TextBlock,
                                         Orientation)
    from System.Windows import Thickness, FontWeights
    from System.Windows.Controls import Border as B

    panel = StackPanel()
    panel.Orientation = Orientation.Horizontal
    panel.Margin = Thickness(0, 10, 0, 6)

    tick = Border()
    tick.Width = 4
    tick.Height = 15
    tick.Margin = Thickness(0, 0, 7, 0)
    try:
        tick.SetResourceReference(B.BackgroundProperty, accent_key)
    except Exception:
        pass
    panel.Children.Add(tick)

    label = TextBlock()
    label.Text = text
    label.FontWeight = FontWeights.Bold
    label.FontSize = 11
    try:
        label.SetResourceReference(TextBlock.ForegroundProperty, "Txt")
    except Exception:
        pass
    panel.Children.Add(label)
    return panel


def labelled_row(label_text, controls, label_width=118):
    """A label on the left and a row of controls filling the rest."""
    from System.Windows.Controls import (Grid, TextBlock, StackPanel,
                                         Orientation)
    from System.Windows import Thickness, VerticalAlignment

    grid = Grid()
    grid.Margin = Thickness(0, 0, 0, 5)
    grid.ColumnDefinitions.Add(col(pixels=label_width))
    grid.ColumnDefinitions.Add(col(1))

    label = TextBlock()
    label.Text = label_text
    label.VerticalAlignment = VerticalAlignment.Center
    label.FontSize = 11
    try:
        label.SetResourceReference(TextBlock.ForegroundProperty, "Dim")
    except Exception:
        pass
    place(label, grid, 0)

    holder = StackPanel()
    holder.Orientation = Orientation.Horizontal
    for c in controls:
        holder.Children.Add(c)
    place(holder, grid, 1)
    return grid


def brush(hex_text):
    """A SolidColorBrush from '#AARRGGBB' or '#RRGGBB'."""
    from System.Windows.Media import SolidColorBrush, Color as WpfColour
    s = (hex_text or "").strip().lstrip("#")
    try:
        if len(s) == 8:
            a = int(s[0:2], 16)
            r = int(s[2:4], 16)
            g = int(s[4:6], 16)
            b = int(s[6:8], 16)
            return SolidColorBrush(WpfColour.FromArgb(a, r, g, b))
        if len(s) == 6:
            r = int(s[0:2], 16)
            g = int(s[2:4], 16)
            b = int(s[4:6], 16)
            return SolidColorBrush(WpfColour.FromRgb(r, g, b))
    except Exception:
        pass
    # the last resort, when even the palette cannot be reached
    return SolidColorBrush(WpfColour.FromRgb(38, 38, 38))  # palette fallback


def row(pixels=None):
    from System.Windows.Controls import RowDefinition
    from System.Windows import GridLength
    r = RowDefinition()
    if pixels is not None:
        r.Height = GridLength(pixels)
    else:
        r.Height = GridLength.Auto
    return r


def wrap():
    from System.Windows import TextWrapping
    return TextWrapping.Wrap


def colour(r, g, b, a=255):
    from System.Windows.Media import Color as WpfColour
    return WpfColour.FromArgb(int(a), int(r), int(g), int(b))


def cursor_hand():
    from System.Windows.Input import Cursors
    return Cursors.Hand


# ===========================================================================
#  Pattern previews
# ===========================================================================
def line_pattern_preview(doc, pattern_id, width=120.0, height=18.0,
                         stroke=None):
    """A sample of a line pattern, drawn from its own segment list."""
    from System.Windows.Controls import Canvas
    from System.Windows.Shapes import Line

    stroke = stroke or pcolour("Txt")

    canvas = Canvas()
    canvas.Width = width
    canvas.Height = height
    canvas.Background = pbrush("FieldDeep")

    def solid():
        seg = Line()
        seg.X1, seg.Y1, seg.X2, seg.Y2 = 4, height / 2.0, width - 4, height / 2.0
        seg.Stroke = brush(stroke)
        seg.StrokeThickness = 1.6
        canvas.Children.Add(seg)
        return canvas

    if pattern_id is None:
        return solid()

    segments = []
    try:
        element = doc.GetElement(pattern_id)
        pattern = element.GetLinePattern()
        for s in pattern.GetSegments():
            segments.append((str(s.Type), abs(s.Length)))
    except Exception:
        return solid()

    total = sum(length for _kind, length in segments)
    if not segments or total <= 0:
        return solid()

    usable = width - 8
    repeats = 3.0
    scale = usable / (total * repeats)

    x = 4.0
    guard = 0
    while x < width - 4 and guard < 400:
        for kind, length in segments:
            step = length * scale
            if step <= 0:
                step = 1.0
            if "Space" not in kind:
                seg = Line()
                seg.X1 = x
                seg.X2 = min(x + step, width - 4)
                if "Dot" in kind:
                    seg.X2 = min(x + 1.6, width - 4)
                seg.Y1 = height / 2.0
                seg.Y2 = height / 2.0
                seg.Stroke = brush(stroke)
                seg.StrokeThickness = 1.6
                canvas.Children.Add(seg)
            x += step
            guard += 1
            if x >= width - 4:
                break
    return canvas


def fill_pattern_preview(doc, pattern_id, width=120.0, height=52.0,
                         stroke=None):
    """A sample of a fill pattern, drawn from its own fill grids."""
    from System.Windows.Controls import Canvas
    from System.Windows.Shapes import Line
    import math

    stroke = stroke or pcolour("Txt")

    canvas = Canvas()
    canvas.Width = width
    canvas.Height = height
    canvas.Background = pbrush("FieldDeep")
    canvas.ClipToBounds = True

    if pattern_id is None:
        return canvas

    grids = []
    solid_fill = False
    try:
        element = doc.GetElement(pattern_id)
        pattern = element.GetFillPattern()
        solid_fill = bool(pattern.IsSolidFill)
        for g in pattern.GetFillGrids():
            grids.append((float(g.Angle), float(g.Offset)))
    except Exception:
        return canvas

    if solid_fill:
        canvas.Background = brush(stroke)
        return canvas
    if not grids:
        return canvas

    offsets = [o for _a, o in grids if o > 0]
    if not offsets:
        return canvas
    scale = (height / 6.0) / min(offsets)
    scale = max(4.0, min(scale, 400.0))

    span = math.sqrt(width * width + height * height)
    for angle, offset in grids:
        step = offset * scale
        if step < 3.0:
            step = 3.0
        dx, dy = math.cos(angle), math.sin(angle)
        nx, ny = -dy, dx
        count = int(span / step) + 2
        for i in range(-count, count + 1):
            cx = width / 2.0 + nx * step * i
            cy = height / 2.0 + ny * step * i
            seg = Line()
            seg.X1 = cx - dx * span
            seg.Y1 = cy - dy * span
            seg.X2 = cx + dx * span
            seg.Y2 = cy + dy * span
            seg.Stroke = brush(stroke)
            seg.StrokeThickness = 0.9
            canvas.Children.Add(seg)
    return canvas


# ===========================================================================
#  Handler guard
# ===========================================================================
_REPORTER = [None]


def set_handler_reporter(fn):
    _REPORTER[0] = fn


def ui_safe(fn):
    """Wrap a WPF handler so a Python error is reported, not swallowed.

    An unhandled exception in a WPF handler propagates onto Revit's UI
    thread: at best the control silently does nothing, at worst it takes
    Revit down. Neither leaves a traceback to read.
    """
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            import traceback
            reporter = _REPORTER[0]
            name = getattr(fn, "__name__", "handler")
            if reporter is not None:
                try:
                    reporter(name, traceback.format_exc())
                except Exception:
                    pass
    try:
        wrapper.__name__ = fn.__name__
    except Exception:
        pass
    return wrapper


def guard_handlers(cls, extra=None):
    """Wrap every on_* method on a window class, plus any named extras."""
    names = [n for n in dir(cls) if n.startswith("on_")]
    for n in (extra or []):
        if n not in names:
            names.append(n)
    for n in names:
        try:
            fn = getattr(cls, n)
        except Exception:
            continue
        if not callable(fn):
            continue
        try:
            original = fn.__func__      # unbound method on IronPython 2
        except AttributeError:
            original = fn
        try:
            setattr(cls, n, ui_safe(original))
        except Exception:
            continue
    return cls


# ===========================================================================
#  Palette
# ===========================================================================
def pcolour(key):
    """A hex colour from the palette that is currently in force."""
    import fm_theme
    return fm_theme.get(key)


def pbrush(key):
    return brush(pcolour(key))


def apply_palette(window):
    """Write the palette straight onto the window's own resources.

    That sits in front of everything the layout declared, and because the
    layouts reference the keys with DynamicResource the whole window
    repaints with no reload and no loss of state.
    """
    import fm_theme
    from System.Windows.Media import SolidColorBrush
    palette = fm_theme.current()
    for key in palette:
        try:
            window.Resources[key] = brush(palette[key])
        except Exception:
            continue


def measure_text(text, font_size=12.0, bold=False):
    """How wide a string renders, in WPF units."""
    from System.Windows.Controls import TextBlock
    from System.Windows import Size, FontWeights
    try:
        block = TextBlock()
        block.Text = text or ""
        block.FontSize = font_size
        if bold:
            block.FontWeight = FontWeights.Bold
        block.Measure(Size(10000, 10000))
        return block.DesiredSize.Width
    except Exception:
        return len(text or "") * font_size * 0.55


def star(value):
    from System.Windows import GridLength, GridUnitType
    return GridLength(max(0.0001, float(value)), GridUnitType.Star)


def pixels(value):
    from System.Windows import GridLength
    return GridLength(max(0.0, float(value)))


def trim():
    from System.Windows import TextTrimming
    return TextTrimming.CharacterEllipsis


def trim():
    from System.Windows import TextTrimming
    return TextTrimming.CharacterEllipsis


class Debounce(object):
    """Run something once the typing stops, rather than per keystroke.

    A search box that rebuilds a list on every key press does the work five
    or six times for a word nobody has finished typing yet.
    """

    def __init__(self, action, milliseconds=220):
        from System.Windows.Threading import DispatcherTimer
        from System import TimeSpan
        self.action = action
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(milliseconds)
        self.timer.Tick += self._tick

    def _tick(self, sender, args):
        self.timer.Stop()
        try:
            self.action()
        except Exception:
            pass

    def poke(self):
        try:
            self.timer.Stop()
            self.timer.Start()
        except Exception:
            self.action()

    def cancel(self):
        try:
            self.timer.Stop()
        except Exception:
            pass


def centre():
    from System.Windows import HorizontalAlignment
    return HorizontalAlignment.Center


def hidden():
    from System.Windows import Visibility
    return Visibility.Collapsed


def geometry(path_data):
    from System.Windows.Media import Geometry
    return Geometry.Parse(path_data)


def left():
    from System.Windows import HorizontalAlignment
    return HorizontalAlignment.Left


# ===========================================================================
#  Revit's own theme, for the Auto palette
# ===========================================================================
def revit_theme():
    """"dark" or "light" from what Revit is showing, or None if unknown.

    The canvas theme comes first (2024+), because that is what the drawing
    area looks like and the tool sits next to it. Then the UI theme. Then
    Windows' own app setting, for releases with no theme API. Every step is
    wrapped: a release without the API must just fall through.
    """
    try:
        from Autodesk.Revit.UI import UIThemeManager
        for attr in ("CurrentCanvasTheme", "CurrentTheme"):
            try:
                value = str(getattr(UIThemeManager, attr)).lower()
            except Exception:
                continue
            if "dark" in value:
                return "dark"
            if "light" in value:
                return "light"
    except Exception:
        pass
    try:
        from Microsoft.Win32 import Registry
        key = Registry.CurrentUser.OpenSubKey(
            "Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize")
        if key is not None:
            value = key.GetValue("AppsUseLightTheme")
            key.Close()
            if value is not None:
                return "light" if int(value) == 1 else "dark"
    except Exception:
        pass
    return None
