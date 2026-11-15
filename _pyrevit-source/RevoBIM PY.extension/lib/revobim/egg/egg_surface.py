# -*- coding: utf-8 -*-
"""The drawing surface a game is handed.

Retained mode on purpose. Clearing a Canvas and rebuilding several hundred
shapes thirty times a second is slower than the game logic it is drawing; every
shape is created once against a key and afterwards only moved, refilled or
removed. A game therefore never allocates in its tick loop.

A game only ever sees these methods, so writing a new one needs no WPF
knowledge at all - and swapping this surface for a different renderer later
would not touch a single game.
"""

import math

from revobim.egg import egg_clr  # noqa: F401  - assemblies first, always

from System.Windows import Point, Size, TextAlignment
from System.Windows.Controls import Canvas, TextBlock
from System.Windows.Media import (ArcSegment, ColorConverter, FontFamily,
                                  LineSegment, PathFigure, PathGeometry,
                                  SolidColorBrush, SweepDirection)
from System.Windows.Shapes import Ellipse, Path, Rectangle


class Surface(object):
    def __init__(self, canvas, palette):
        self.canvas = canvas
        self.palette = palette
        self._items = {}
        self._brushes = {}

    # -- colours ==========================================================

    def brush(self, colour):
        """Accept a palette key ('hero') or a literal hex ('#F5C518')."""
        value = self.palette.get(colour, colour)
        cached = self._brushes.get(value)
        if cached is not None:
            return cached
        try:
            made = SolidColorBrush(ColorConverter.ConvertFromString(value))
            made.Freeze()
        except Exception:
            made = SolidColorBrush(ColorConverter.ConvertFromString("#FF00FF"))
        self._brushes[value] = made
        return made

    def colour(self, value, alpha=1.0):
        """The name the desktop surface uses. Both answer to both, so a game
        cannot be written against one implementation by accident."""
        return self.brush(value)

    # -- shapes ===========================================================

    def _place(self, key, element, x, y):
        Canvas.SetLeft(element, x)
        Canvas.SetTop(element, y)
        self.canvas.Children.Add(element)
        self._items[key] = element
        return element

    def rect(self, key, x, y, w, h, colour, radius=0):
        shape = self._items.get(key)
        if shape is None:
            shape = Rectangle()
            self._place(key, shape, x, y)
        shape.Width = max(0.0, w)
        shape.Height = max(0.0, h)
        shape.RadiusX = radius
        shape.RadiusY = radius
        shape.Fill = self.brush(colour)
        Canvas.SetLeft(shape, x)
        Canvas.SetTop(shape, y)
        return shape

    def ellipse(self, key, cx, cy, r, colour):
        shape = self._items.get(key)
        if shape is None:
            shape = Ellipse()
            self._place(key, shape, cx - r, cy - r)
        shape.Width = r * 2.0
        shape.Height = r * 2.0
        shape.Fill = self.brush(colour)
        Canvas.SetLeft(shape, cx - r)
        Canvas.SetTop(shape, cy - r)
        return shape

    def wedge(self, key, cx, cy, r, start_deg, sweep_deg, colour):
        """A pie slice. Angles in degrees, zero pointing right, clockwise.

        This is what draws a mouth. Building it here rather than in the game
        keeps PathGeometry out of every game module.
        """
        shape = self._items.get(key)
        if shape is None:
            shape = Path()
            self._place(key, shape, 0, 0)
        sweep = max(0.1, min(359.9, sweep_deg))
        a0 = math.radians(start_deg)
        a1 = math.radians(start_deg + sweep)
        figure = PathFigure()
        figure.StartPoint = Point(cx, cy)
        figure.Segments.Add(LineSegment(
            Point(cx + r * math.cos(a0), cy + r * math.sin(a0)), True))
        figure.Segments.Add(ArcSegment(
            Point(cx + r * math.cos(a1), cy + r * math.sin(a1)),
            Size(r, r), 0.0, sweep > 180.0, SweepDirection.Clockwise, True))
        figure.IsClosed = True
        geometry = PathGeometry()
        geometry.Figures.Add(figure)
        shape.Data = geometry
        shape.Fill = self.brush(colour)
        Canvas.SetLeft(shape, 0)
        Canvas.SetTop(shape, 0)
        return shape

    def label(self, key, x, y, text, size=12, colour="text", bold=False):
        shape = self._items.get(key)
        if shape is None:
            shape = TextBlock()
            shape.FontFamily = FontFamily("Segoe UI")
            self._place(key, shape, x, y)
        shape.Text = text
        shape.FontSize = size
        shape.FontWeight = _weight(bold)
        shape.Foreground = self.brush(colour)
        Canvas.SetLeft(shape, x)
        Canvas.SetTop(shape, y)
        return shape

    def banner(self, key, y, width, text, size=15, colour="orange",
               behind="bg"):
        """A centred line of text on a full width strip.

        Here rather than in the game so no game module ever has to import
        TextAlignment - or anything else out of System.Windows.
        """
        self.rect(key + "_bg", 0, y - (size + 6) / 2.0, width, size + 12,
                  behind, 4)
        label = self.label(key, 0, y - (size + 1) / 2.0, text, size, colour,
                           True)
        try:
            label.Width = width
            label.TextAlignment = TextAlignment.Center
        except Exception:
            pass
        return label

    def drop_banner(self, key):
        self.remove(key)
        self.remove(key + "_bg")

    # -- updates ==========================================================

    def move(self, key, x, y):
        shape = self._items.get(key)
        if shape is None:
            return
        Canvas.SetLeft(shape, x)
        Canvas.SetTop(shape, y)

    def move_centre(self, key, cx, cy):
        shape = self._items.get(key)
        if shape is None:
            return
        Canvas.SetLeft(shape, cx - (shape.Width / 2.0))
        Canvas.SetTop(shape, cy - (shape.Height / 2.0))

    def fill(self, key, colour):
        shape = self._items.get(key)
        if shape is not None:
            shape.Fill = self.brush(colour)

    def alpha(self, key, value):
        shape = self._items.get(key)
        if shape is not None:
            shape.Opacity = max(0.0, min(1.0, value))

    def lift(self, key):
        """Move a shape to the front.

        Canvas draws in child order, so an overlay built after the board is
        already on top - until a restart rebuilds the board underneath it.
        """
        shape = self._items.get(key)
        if shape is None:
            return
        try:
            self.canvas.Children.Remove(shape)
            self.canvas.Children.Add(shape)
        except Exception:
            pass

    def show(self, key, visible):
        shape = self._items.get(key)
        if shape is not None:
            shape.Opacity = 1.0 if visible else 0.0

    def has(self, key):
        return key in self._items

    def remove(self, key):
        shape = self._items.pop(key, None)
        if shape is not None:
            try:
                self.canvas.Children.Remove(shape)
            except Exception:
                pass

    def clear(self):
        try:
            self.canvas.Children.Clear()
        except Exception:
            pass
        self._items = {}


def _weight(bold):
    from System.Windows import FontWeights
    return FontWeights.Bold if bold else FontWeights.Normal
