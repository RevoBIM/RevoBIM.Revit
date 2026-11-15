using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace RevoBIM.Arcade.Core
{
    /// <summary>
    /// Helpers for the picker icons: small coloured drawings on a 24 x 24 canvas with gradients for
    /// shading. Icons keep their own colours in both themes, like a logo does.
    /// </summary>
    public static class IconKit
    {
        public static Color C(string hex) => (Color)ColorConverter.ConvertFromString(hex);

        /// <summary>Top-to-bottom gradient.</summary>
        public static Brush Vertical(string top, string bottom) =>
            new LinearGradientBrush(C(top), C(bottom), new Point(0.5, 0), new Point(0.5, 1));

        /// <summary>A lit-from-the-top-left sphere.</summary>
        public static Brush Glow(string centre, string mid, string edge) =>
            new RadialGradientBrush(new GradientStopCollection
            {
                new GradientStop(C(centre), 0.0), new GradientStop(C(mid), 0.55), new GradientStop(C(edge), 1.0),
            })
            { Center = new Point(0.5, 0.5), GradientOrigin = new Point(0.32, 0.28), RadiusX = 0.75, RadiusY = 0.75 };

        public static Brush Solid(string hex) => new SolidColorBrush(C(hex));

        public static Canvas Box() => new Canvas { Width = 24, Height = 24 };

        /// <summary>Puts a 24 x 24 drawing in a Viewbox of the picker's icon size.</summary>
        public static UIElement Wrap(Canvas drawing, double size = 36) => new Viewbox { Width = size, Height = size, Child = drawing };

        public static Path Shape(string data, Brush fill, Brush? stroke = null, double thickness = 0.6) => new Path
        {
            Data = Geometry.Parse(data), Fill = fill, Stroke = stroke, StrokeThickness = stroke == null ? 0 : thickness,
            StrokeLineJoin = PenLineJoin.Round,
        };

        public static Rectangle Block(double x, double y, double w, double h, double radius, Brush fill, Brush? stroke = null)
        {
            var r = new Rectangle { Width = w, Height = h, RadiusX = radius, RadiusY = radius, Fill = fill, Stroke = stroke, StrokeThickness = stroke == null ? 0 : 0.6 };
            Canvas.SetLeft(r, x); Canvas.SetTop(r, y);
            return r;
        }

        public static Ellipse Dot(double cx, double cy, double rx, double ry, Brush fill)
        {
            var e = new Ellipse { Width = rx * 2, Height = ry * 2, Fill = fill };
            Canvas.SetLeft(e, cx - rx); Canvas.SetTop(e, cy - ry);
            return e;
        }
    }
}
