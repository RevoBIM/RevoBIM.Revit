using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace RevoBIM.Arcade.Core
{
    /// <summary>Theme brush keys the bundled games draw with. Every one exists in Dark.xaml and Light.xaml.</summary>
    public static class BrushKeys
    {
        public const string Hero = "HeroBrush", Blue = "BlueBrush", Orange = "OrangeBrush", Green = "GreenBrush",
            Red = "RedBrush", Text = "TextBrush", Muted = "MutedBrush", Card = "CardBg", Field = "FieldBg",
            Maze = "MazeBrush", MazeFill = "MazeFillBrush", Pellet = "PelletBrush", Power = "PowerBrush",
            Ghost1 = "Ghost1Brush", Ghost2 = "Ghost2Brush", Ghost3 = "Ghost3Brush", Ghost4 = "Ghost4Brush",
            Scared = "ScaredBrush", ScaredEnd = "ScaredEndBrush", Eyes = "EyesBrush", Pupil = "PupilBrush",
            Veil = "VeilBrush", Edge = "EdgeBrush";

        /// <summary>Everything above, so the selftest can prove both palettes define it.</summary>
        public static readonly string[] All =
        {
            Hero, Blue, Orange, Green, Red, Text, Muted, Card, Field, Maze, MazeFill, Pellet, Power,
            Ghost1, Ghost2, Ghost3, Ghost4, Scared, ScaredEnd, Eyes, Pupil, Veil, Edge,
        };
    }

    /// <summary>Small drawing helpers shared by the games. Colours are always theme brush keys.</summary>
    public static class Kit
    {
        static readonly FontFamily Font = new FontFamily("Segoe UI");

        public static void Place(UIElement element, double x, double y)
        {
            Canvas.SetLeft(element, x);
            Canvas.SetTop(element, y);
        }

        public static Rectangle Rect(GameHost host, double x, double y, double w, double h, string brush, double radius = 0)
        {
            var r = new Rectangle { Width = w, Height = h, RadiusX = radius, RadiusY = radius };
            host.Fill(r, brush);
            Place(r, x, y);
            host.Surface.Children.Add(r);
            return r;
        }

        /// <summary>A circle placed by its centre.</summary>
        public static Ellipse Circle(GameHost host, double cx, double cy, double radius, string brush)
        {
            var e = new Ellipse { Width = radius * 2, Height = radius * 2 };
            host.Fill(e, brush);
            Place(e, cx - radius, cy - radius);
            host.Surface.Children.Add(e);
            return e;
        }

        public static TextBlock Label(GameHost host, double x, double y, string text, double size, string brush, bool bold = false)
        {
            var t = new TextBlock { Text = text, FontFamily = Font, FontSize = size, FontWeight = bold ? FontWeights.SemiBold : FontWeights.Normal };
            host.Text(t, brush);
            Place(t, x, y);
            host.Surface.Children.Add(t);
            return t;
        }

        /// <summary>
        /// Centred text on a strip across the whole board. top is the strip's top edge; stripBrush
        /// null means no strip. Returns the strip so a game can remove or fade it.
        /// </summary>
        public static Border Banner(GameHost host, double top, string text, double size, string brush, string? stripBrush = BrushKeys.Veil)
        {
            var label = new TextBlock
            {
                Text = text, FontFamily = Font, FontSize = size, FontWeight = FontWeights.SemiBold,
                TextAlignment = TextAlignment.Center, HorizontalAlignment = HorizontalAlignment.Center,
            };
            host.Text(label, brush);
            var strip = new Border { Width = host.BoardWidth, Padding = new Thickness(0, 3, 0, 3), Child = label };
            if (stripBrush != null) strip.SetResourceReference(Border.BackgroundProperty, stripBrush);
            Place(strip, 0, top);
            host.Surface.Children.Add(strip);
            return strip;
        }

        public static void Refill(Shape shape, string brush) => shape.SetResourceReference(Shape.FillProperty, brush);

        /// <summary>
        /// A pie slice, angles in degrees, zero pointing right and increasing clockwise (the canvas
        /// y-axis runs down). Sweeps are clamped just inside 0 and 360 so the arc stays well formed.
        /// </summary>
        public static Geometry Wedge(double cx, double cy, double radius, double startDeg, double sweepDeg)
        {
            sweepDeg = Math.Max(0.5, Math.Min(359.5, sweepDeg));
            double a0 = startDeg * Math.PI / 180.0, a1 = (startDeg + sweepDeg) * Math.PI / 180.0;
            var p0 = new Point(cx + radius * Math.Cos(a0), cy + radius * Math.Sin(a0));
            var p1 = new Point(cx + radius * Math.Cos(a1), cy + radius * Math.Sin(a1));
            var g = new StreamGeometry();
            using (var c = g.Open())
            {
                c.BeginFigure(new Point(cx, cy), true, true);
                c.LineTo(p0, true, false);
                c.ArcTo(p1, new Size(radius, radius), 0, sweepDeg > 180, SweepDirection.Clockwise, true, false);
            }
            g.Freeze();
            return g;
        }

        /// <summary>A cheap 0..1 triangle wave, for prompts that breathe rather than blink.</summary>
        public static double Wave(int frame, double span = 70)
        {
            double position = (frame % (span * 2)) / span;
            return position <= 1.0 ? position : 2.0 - position;
        }
    }
}

