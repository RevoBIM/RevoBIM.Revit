# -*- coding: utf-8 -*-
"""Callout to 3D - the sheet preview and the layout cards.

The preview is the sheet the run will make, drawn to scale: the paper, the
margins, the title strip, and one box per viewport where the chosen layout
puts it.  The boxes can be dragged.  Where one is let go is kept as the
position of its centre on the paper, by role (callout, 3d, X1, Y2 ...), and
the run puts the real viewport there at its real measured size.

All of the arithmetic is in c3d_geom, where the bench can reach it; this
module only draws and listens to the mouse.
"""

import c3d_clr  # noqa: F401  assemblies first, always

import c3d_geom as geom
import c3d_preview as preview

from System.Windows import Thickness, CornerRadius                     # noqa: E402
from System.Windows.Controls import Canvas, TextBlock, Border          # noqa: E402
from System.Windows.Shapes import Rectangle                            # noqa: E402
from System.Windows.Media import DoubleCollection                      # noqa: E402
from System.Windows.Input import Cursors                               # noqa: E402

ROLE_BRUSH = {"callout": "PreviewInkBrush", "3d": "GreenBrush", "X": "OrangeBrush",
              "Y": "BlueBrush"}
ROLE_TEXT = {"callout": "Plan", "3d": "3D"}


def role_brush_key(role):
    if role in ROLE_BRUSH:
        return ROLE_BRUSH[role]
    return ROLE_BRUSH.get((role or "X")[:1].upper(), "OrangeBrush")


def role_text(role):
    return ROLE_TEXT.get(role, role)


def _faint(brush, opacity):
    try:
        faint = brush.Clone()
        faint.Opacity = opacity
        return faint
    except Exception:
        return brush


def _rect(canvas, left, top, width, height, stroke, fill=None, thickness=1.0, dashed=False):
    shape = Rectangle()
    shape.Width = max(1.0, width)
    shape.Height = max(1.0, height)
    shape.Stroke = stroke
    shape.StrokeThickness = thickness
    if fill is not None:
        shape.Fill = fill
    if dashed:
        dashes = DoubleCollection()
        dashes.Add(4.0)
        dashes.Add(3.0)
        shape.StrokeDashArray = dashes
    Canvas.SetLeft(shape, left)
    Canvas.SetTop(shape, top)
    canvas.Children.Add(shape)
    return shape


class SheetPreview(object):
    """The draggable sheet.

    `on_moved(role, centre)` is told when a box is let go somewhere new, and
    `on_reset(role)` when one is right clicked back to where the layout puts
    it.  Neither redraws - the window owns the moves and asks for a redraw.
    """

    def __init__(self, canvas, on_moved, on_reset):
        self.canvas = canvas
        self.on_moved = on_moved
        self.on_reset = on_reset
        self.fit = None
        self.sheet = (841.0, 594.0)
        self.drag = None

    # ------------------------------------------------------------------
    def draw(self, sheet_mm, margins, layout, moved_roles=None, caption=u""):
        """sheet_mm (width, height); margins (left, right, top, bottom)."""
        canvas = self.canvas
        canvas.Children.Clear()
        self.drag = None
        width, height = float(sheet_mm[0]), float(sheet_mm[1])
        self.sheet = (width, height)
        moved_roles = set(moved_roles or [])
        try:
            canvas_w = float(canvas.ActualWidth)
            canvas_h = float(canvas.ActualHeight)
        except Exception:
            canvas_w, canvas_h = 0.0, 0.0
        if canvas_w < 40 or canvas_h < 40:
            return

        ink = preview._brush(canvas, "PreviewInkBrush")
        muted = preview._brush(canvas, "MutedBrush")
        paper = preview._brush(canvas, "CardBrush")
        edge = preview._brush(canvas, "FrameBrush")
        red = preview._brush(canvas, "RedBrush", "#D9534F")

        if layout is None:
            preview._text(canvas, u"Pick a callout to see its sheet", 14, 14, muted, 11.0)
            return

        # anything that overflows sits below the paper, and the preview has to
        # show it there rather than off the bottom of the canvas
        roles = geom.layout_roles(layout)
        lowest = min([0.0] + [cell[1] for _role, cell in roles])
        # the title block fills the preview: as big as the canvas allows
        self.fit = geom.sheet_fit(width, height - lowest, canvas_w, canvas_h, 4.0)
        k = self.fit[0]

        def at(x_mm, y_mm):
            return geom.to_canvas(self.fit, height, x_mm, y_mm)

        top_left = at(0.0, height)
        _rect(canvas, top_left[0], top_left[1], width * k, height * k, edge, paper, 1.2)
        left, right, top, bottom = [float(value) for value in margins]
        inner = at(left, height - top)
        _rect(canvas, inner[0], inner[1], (width - left - right) * k,
              (height - top - bottom) * k, _faint(muted, 0.6), None, 1.0, True)
        if right > 1.0:
            strip = at(width - right, height)
            _rect(canvas, strip[0], strip[1], right * k, height * k, edge,
                  _faint(muted, 0.12), 1.0)
            label = preview._text(canvas, u"title block", strip[0] + 6, strip[1] + 6, muted, 9.5)
            label.IsHitTestVisible = False
        if lowest < 0.0:
            sill = at(0.0, 0.0)
            preview._line(canvas, sill[0], sill[1], sill[0] + width * k, sill[1], red, 1.4, True)
            note = preview._text(canvas, u"off the sheet - needs a look",
                                 sill[0] + 4, sill[1] + 2, red, 9.5)
            note.IsHitTestVisible = False

        clashing = set()
        for pair in geom.overlaps(layout):
            clashing.update(pair)

        for role, cell in roles:
            self._box(role, cell, at, k, role in clashing, role in moved_roles, red)

        if caption:
            text = preview._text(canvas, caption, top_left[0] + 6, top_left[1] + 4, ink, 10.0)
            text.IsHitTestVisible = False

    def _box(self, role, cell, at, k, clashing, moved, red):
        canvas = self.canvas
        colour = preview._brush(canvas, role_brush_key(role))
        corner = at(cell[0], cell[1] + cell[3])
        shape = _rect(canvas, corner[0], corner[1], cell[2] * k, cell[3] * k,
                      red if clashing else colour, _faint(colour, 0.24),
                      2.0 if clashing else 1.4, moved)
        shape.Cursor = Cursors.SizeAll
        shape.ToolTip = (u"{0} - drag to move it, right click to put it back"
                         .format(role_text(role)))
        label = TextBlock()
        label.Text = role_text(role) + (u" *" if moved else u"")
        label.Foreground = preview._brush(canvas, "TextBrush")
        label.FontSize = 10.5 if cell[3] * k > 16 else 8.5
        label.IsHitTestVisible = False
        Canvas.SetLeft(label, corner[0] + 4)
        Canvas.SetTop(label, corner[1] + 2)
        canvas.Children.Add(label)

        def down(sender, args):
            point = args.GetPosition(canvas)
            self.drag = {"role": role, "cell": cell, "shape": shape, "label": label,
                         "start": (point.X, point.Y),
                         "origin": (Canvas.GetLeft(shape), Canvas.GetTop(shape)),
                         "moved": False}
            shape.CaptureMouse()
            args.Handled = True

        def move(sender, args):
            drag = self.drag
            if drag is None or drag["shape"] is not shape:
                return
            point = args.GetPosition(canvas)
            dx = point.X - drag["start"][0]
            dy = point.Y - drag["start"][1]
            if abs(dx) + abs(dy) < 2.0 and not drag["moved"]:
                return
            drag["moved"] = True
            centre = self._centre_after(drag["cell"], dx, dy)
            new_corner = geom.to_canvas(self.fit, self.sheet[1],
                                        centre[0] - cell[2] / 2.0, centre[1] + cell[3] / 2.0)
            Canvas.SetLeft(shape, new_corner[0])
            Canvas.SetTop(shape, new_corner[1])
            Canvas.SetLeft(label, new_corner[0] + 4)
            Canvas.SetTop(label, new_corner[1] + 2)
            drag["centre"] = centre

        def up(sender, args):
            drag = self.drag
            self.drag = None
            try:
                shape.ReleaseMouseCapture()
            except Exception:
                pass
            if drag is None or not drag.get("moved") or "centre" not in drag:
                return
            args.Handled = True
            self.on_moved(role, drag["centre"])

        def reset(sender, args):
            args.Handled = True
            self.on_reset(role)

        shape.MouseLeftButtonDown += down
        shape.MouseMove += move
        shape.MouseLeftButtonUp += up
        shape.MouseRightButtonUp += reset

    def _centre_after(self, cell, dx_px, dy_px):
        k = self.fit[0] or 1.0
        centre = geom.cell_centre(cell)
        wanted = (centre[0] + dx_px / k, centre[1] - dy_px / k)
        return geom.clamp_centre(cell, wanted, self.sheet[0], self.sheet[1])


# ---------------------------------------------------------------------------
# the layout cards
# ---------------------------------------------------------------------------


def draw_card(canvas, preset, x_count, y_count, selected, moves=None, dashed=False):
    """One preset drawn small: the paper and a box per view in its colour.

    Drawn with stand-in sizes but the real counts, so the card shows the
    arrangement this callout would get - four sections stack differently
    from one."""
    canvas.Children.Clear()
    width, height = float(canvas.Width), float(canvas.Height)
    sheet = (841.0, 594.0)
    layout = geom.thumbnail_layout(preset, max(0, min(int(x_count), 4)),
                                   max(0, min(int(y_count), 4)), sheet)
    if moves:
        layout = geom.apply_moves(layout, moves)     # the custom setout's card
    roles = geom.layout_roles(layout)
    lowest = min([0.0] + [cell[1] for _role, cell in roles])
    fit = geom.sheet_fit(sheet[0], sheet[1] - lowest, width, height, 3.0)
    k = fit[0]
    corner = geom.to_canvas(fit, sheet[1], 0.0, sheet[1])
    edge = preview._brush(canvas, "BlueBrush" if selected else "FrameBrush")
    _rect(canvas, corner[0], corner[1], sheet[0] * k, sheet[1] * k, edge,
          preview._brush(canvas, "FieldBrush"), 1.6 if selected else 1.0, dashed)
    for role, cell in roles:
        colour = preview._brush(canvas, role_brush_key(role))
        top_left = geom.to_canvas(fit, sheet[1], cell[0], cell[1] + cell[3])
        _rect(canvas, top_left[0], top_left[1], cell[2] * k, cell[3] * k, colour,
              _faint(colour, 0.45), 0.8)


def card(canvas, border, selected):
    """The frame round a card says which one is in use."""
    try:
        border.BorderBrush = preview._brush(border, "BlueBrush" if selected else "EdgeBrush")
        border.BorderThickness = Thickness(2.0 if selected else 1.0)
        border.Background = preview._brush(border, "HoverBrush" if selected else "CardBrush")
    except Exception:
        pass


def new_card(width=112.0, height=80.0):
    """A card: a bordered canvas of a fixed size, so it can be drawn before
    the window has been through a layout pass."""
    holder = Border()
    holder.CornerRadius = CornerRadius(4)
    holder.Margin = Thickness(0, 0, 8, 0)
    holder.Padding = Thickness(4)
    holder.Cursor = Cursors.Hand
    surface = Canvas()
    surface.Width = width
    surface.Height = height
    holder.Child = surface
    return holder, surface
