# -*- coding: utf-8 -*-
"""Callout to 3D - the section array preview.

Everything is drawn from Shape elements rather than a font glyph, so it cannot
come out as an empty box on a machine without that font.
"""

import c3d_clr  # noqa: F401  assemblies first, always

import c3d_geom as geom

from System.Windows.Shapes import Line, Rectangle, Polygon, Ellipse   # noqa: E402
from System.Windows.Controls import Canvas, TextBlock                  # noqa: E402
from System.Windows.Media import DoubleCollection, PointCollection     # noqa: E402
from System.Windows import Point                                       # noqa: E402
from System.Windows.Input import Cursors                               # noqa: E402

PAD = 26.0


def _brush(canvas, key, fallback="#9A9A9E"):
    try:
        found = canvas.TryFindResource(key)
        if found is not None:
            return found
    except Exception:
        pass
    try:
        from System.Windows.Media import SolidColorBrush, ColorConverter
        return SolidColorBrush(ColorConverter.ConvertFromString(fallback))
    except Exception:
        return None


def _line(canvas, x1, y1, x2, y2, brush, thickness=1.0, dashed=False):
    line = Line()
    line.X1, line.Y1, line.X2, line.Y2 = x1, y1, x2, y2
    line.Stroke = brush
    line.StrokeThickness = thickness
    if dashed:
        dashes = DoubleCollection()
        dashes.Add(4.0)
        dashes.Add(3.0)
        line.StrokeDashArray = dashes
    canvas.Children.Add(line)
    return line


def _text(canvas, value, x, y, brush, size=10.0, bold=False):
    block = TextBlock()
    block.Text = u"{0}".format(value)
    block.Foreground = brush
    block.FontSize = size
    if bold:
        from System.Windows import FontWeights
        block.FontWeight = FontWeights.Bold
    Canvas.SetLeft(block, x)
    Canvas.SetTop(block, y)
    canvas.Children.Add(block)
    return block


def _arrow(canvas, tip_x, tip_y, dx, dy, brush, size=7.0):
    """A solid triangle pointing the way the section looks."""
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    polygon = Polygon()
    points = PointCollection()
    points.Add(Point(tip_x, tip_y))
    points.Add(Point(tip_x - ux * size + px * size * 0.55,
                     tip_y - uy * size + py * size * 0.55))
    points.Add(Point(tip_x - ux * size - px * size * 0.55,
                     tip_y - uy * size - py * size * 0.55))
    polygon.Points = points
    polygon.Fill = brush
    canvas.Children.Add(polygon)
    return polygon


def draw(canvas, extents, x_count, y_count, flip_x=False, flip_y=False, title="",
         per=None, on_click=None, cuts=None, on_move=None):
    """The callout in plan with every cut line the run would make on it.

    Canvas Y runs down the screen and model Y runs up the page, so every Y is
    flipped once here and nowhere else.

    Every cut line is drawn with an invisible strip over it that calls
    ``on_click`` with that section's label, so a single section can be turned
    round by clicking the line itself - which is where the eye already is.
    ``per`` is the same per-label override dictionary the geometry takes.
    """
    try:
        canvas.Children.Clear()
    except Exception:
        return

    width = float(canvas.ActualWidth or 0.0)
    height = float(canvas.ActualHeight or 0.0)
    if width < 40 or height < 40:
        return

    ink = _brush(canvas, "PreviewInkBrush", "#9A9A9E")
    blue = _brush(canvas, "BlueBrush", "#4FA3E3")
    orange = _brush(canvas, "OrangeBrush", "#E8912D")
    muted = _brush(canvas, "MutedBrush", "#9A9A9E")

    if not extents:
        _text(canvas, "This callout has no crop box to read", 14, height / 2 - 8, muted, 12)
        return

    x0, y0, x1, y1 = [float(value) for value in extents]
    span_x = max(1.0, x1 - x0)
    span_y = max(1.0, y1 - y0)
    scale = min((width - 2 * PAD) / span_x, (height - 2 * PAD) / span_y)
    draw_w = span_x * scale
    draw_h = span_y * scale
    left = (width - draw_w) / 2.0
    top = (height - draw_h) / 2.0

    def to_x(value):
        return left + (value - x0) * scale

    def to_y(value):
        return top + draw_h - (value - y0) * scale

    box = Rectangle()
    box.Width, box.Height = draw_w, draw_h
    box.Stroke = blue
    box.StrokeThickness = 1.4
    dashes = DoubleCollection()
    dashes.Add(6.0)
    dashes.Add(4.0)
    box.StrokeDashArray = dashes
    Canvas.SetLeft(box, left)
    Canvas.SetTop(box, top)
    canvas.Children.Add(box)

    _text(canvas, u"{0:.0f} x {1:.0f} mm".format(span_x, span_y),
          left, max(2.0, top - 16), muted, 10)
    if title:
        _text(canvas, title, left, min(height - 14, top + draw_h + 4), muted, 10)

    over = 10.0
    per = per or {}

    def flipped_for(label, axis_flip):
        one = per.get(label)
        if one is None:
            return bool(axis_flip)
        return bool(axis_flip) != bool(one)

    def hit(x1, y1, x2, y2, label, colour):
        """A fat transparent line over the drawn one, so the target is
        something a mouse can actually find.  A click turns that section
        round; a drag moves it - up and down for an X cut, left and right for
        a Y one - and a right click puts it back on the even spacing."""
        if on_click is None and on_move is None:
            return
        across = label.startswith("X")      # an X cut moves up and down
        strip = Line()
        strip.X1, strip.Y1, strip.X2, strip.Y2 = x1, y1, x2, y2
        strip.Stroke = _brush(canvas, "TransparentHitBrush", "#01000000")
        strip.StrokeThickness = 16.0
        try:
            strip.Cursor = Cursors.SizeNS if across else Cursors.SizeWE
            strip.ToolTip = (u"{0} - drag to move it, click to turn it round, right click to "
                             u"put it back".format(label))
        except Exception:
            pass
        state = {}

        def down(sender, args):
            point = args.GetPosition(canvas)
            state.clear()
            state.update({"start": (point.X, point.Y), "moved": False})
            try:
                strip.CaptureMouse()
            except Exception:
                pass
            args.Handled = True

        def move(sender, args):
            if "start" not in state:
                return
            point = args.GetPosition(canvas)
            shift = (point.Y - state["start"][1]) if across else (point.X - state["start"][0])
            if abs(shift) < 3.0 and not state["moved"]:
                return
            state["moved"] = True
            if "ghost" not in state:
                state["ghost"] = _line(canvas, x1, y1, x2, y2, colour, 2.0, True)
            ghost = state["ghost"]
            if across:
                y = min(max(point.Y, top), top + draw_h)
                ghost.Y1 = ghost.Y2 = y
                state["fraction"] = geom.cut_fraction(top + draw_h - y, 0.0, draw_h)
            else:
                x = min(max(point.X, left), left + draw_w)
                ghost.X1 = ghost.X2 = x
                state["fraction"] = geom.cut_fraction(x - left, 0.0, draw_w)

        def up(sender, args):
            try:
                strip.ReleaseMouseCapture()
            except Exception:
                pass
            if "start" not in state:
                return
            moved = state.get("moved")
            fraction = state.get("fraction")
            state.clear()
            args.Handled = True
            try:
                if moved and fraction is not None and on_move is not None:
                    on_move(label, fraction)
                elif not moved and on_click is not None:
                    on_click(label)
            except Exception:
                pass

        def reset(sender, args):
            args.Handled = True
            if on_move is not None and label in (cuts or {}):
                try:
                    on_move(label, None)
                except Exception:
                    pass

        strip.MouseLeftButtonDown += down
        strip.MouseMove += move
        strip.MouseLeftButtonUp += up
        strip.MouseRightButtonUp += reset
        canvas.Children.Add(strip)

    cuts = cuts or {}
    for index, station in enumerate(geom.stations_for(x_count, y0, y1, "X", cuts)):
        label = u"X{0}".format(index + 1)
        y = to_y(station)
        _line(canvas, left - over, y, left + draw_w + over, y, orange, 1.4, label in cuts)
        direction = 1.0 if flipped_for(label, flip_x) else -1.0   # canvas Y is flipped
        for x in (left + draw_w * 0.32, left + draw_w * 0.68):
            _arrow(canvas, x, y + direction * 11.0, 0.0, direction, orange)
        _text(canvas, label + (u" *" if label in cuts else u""),
              left + draw_w + over + 3, y - 8, orange, 10, True)
        hit(left - over, y, left + draw_w + over, y, label, orange)

    for index, station in enumerate(geom.stations_for(y_count, x0, x1, "Y", cuts)):
        label = u"Y{0}".format(index + 1)
        x = to_x(station)
        _line(canvas, x, top - over, x, top + draw_h + over, blue, 1.4, label in cuts)
        direction = 1.0 if flipped_for(label, flip_y) else -1.0
        for y in (top + draw_h * 0.32, top + draw_h * 0.68):
            _arrow(canvas, x + direction * 11.0, y, direction, 0.0, blue)
        _text(canvas, label + (u" *" if label in cuts else u""),
              x - 6, max(1.0, top - over - 14), blue, 10, True)
        hit(x, top - over, x, top + draw_h + over, label, blue)

    if on_click is not None and (x_count or y_count):
        _text(canvas, "drag a cut line to move it, click it to turn it round, right click to put it back",
              left, min(height - 2, top + draw_h + 17), muted, 9)

    marker = Ellipse()
    marker.Width, marker.Height = 5, 5
    marker.Fill = ink
    Canvas.SetLeft(marker, left - 2.5)
    Canvas.SetTop(marker, top + draw_h - 2.5)
    canvas.Children.Add(marker)
    _text(canvas, "origin", left + 4, top + draw_h - 15, muted, 9)
