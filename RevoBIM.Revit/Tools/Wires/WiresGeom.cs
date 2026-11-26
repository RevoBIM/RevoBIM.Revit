using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.Wires
{
    /// <summary>
    /// Wire geometry (the arc, chamfer, trim and clearance parts of wires_core.py): plan distances, the circular arc a wire is drawn on, the chamfer,
    /// where a wire stops short of a symbol. Everything is in Revit internal feet.
    /// </summary>
    public static class WiresGeom
    {
        public const int MinVertices = 1;
        public const int MaxVertices = 8;

        /// <summary>
        /// Distance in plan only. A ceiling light sits three metres above the plan the wire is drawn on, so a 3D distance would put every fixture out
        /// of range; wires are view specific annotation over a model that is not.
        /// </summary>
        public static double PlanDistance(XYZ a, XYZ b)
        {
            if (a == null || b == null) return 1.0e9;
            double dx = a.X - b.X, dy = a.Y - b.Y;
            return Math.Sqrt(dx * dx + dy * dy);
        }

        public static XYZ PlanAt(XYZ point, double z)
        {
            return new XYZ(point.X, point.Y, z);
        }

        public static int ViewScale(View view)
        {
            try
            {
                int scale = view.Scale;
                return scale > 0 ? scale : 100;
            }
            catch (Exception)
            {
                return 100;
            }
        }

        /// <summary>Paper millimetres to internal feet at the view's scale: a wire is a symbol, so its sweep and the gap at a fitting are paper measurements.</summary>
        public static double Paper(View view, double valueMm)
        {
            return WiresSettings.Mm(valueMm * ViewScale(view));
        }

        /// <summary>The vertex count, held between 1 and 8 (a wire with no middle vertex has nothing to bend round).</summary>
        public static int ClampVertices(double value)
        {
            int count;
            try
            {
                count = (int)Math.Round(value, MidpointRounding.AwayFromZero);
            }
            catch (Exception)
            {
                count = MinVertices;
            }
            return Math.Max(MinVertices, Math.Min(MaxVertices, count));
        }

        /// <summary>
        /// Points along a true circular arc from A to B with a given sagitta, including both endpoints. A circle rather than a Bezier so the sag is exactly
        /// the depth of the arc at its middle and equal steps of angle are equal steps of arc length.
        /// </summary>
        public static List<XYZ> ArcThrough(double ax, double ay, double bx, double by, double sag, string side, int count, double planeZ)
        {
            double dx = bx - ax, dy = by - ay;
            double chord = Math.Sqrt(dx * dx + dy * dy);
            var ends = new List<XYZ> { new XYZ(ax, ay, planeZ), new XYZ(bx, by, planeZ) };
            if (chord < 1.0e-9) return ends;
            if (count < 1) return ends;

            // a sag past the half-chord would be more than a semicircle, which has no sensible reading here
            double depth = Math.Max(0.0, Math.Min(sag, chord * 0.49));
            if (depth < 1.0e-9)
            {
                var straight = new List<XYZ> { ends[0] };
                for (int step = 1; step <= count; step++)
                {
                    double position = (double)step / (count + 1);
                    straight.Add(new XYZ(ax + dx * position, ay + dy * position, planeZ));
                }
                straight.Add(ends[1]);
                return straight;
            }

            double ux = dx / chord, uy = dy / chord;
            double px, py;
            if ((side ?? "").Trim().ToLowerInvariant() == "right")
            {
                px = uy;
                py = -ux;
            }
            else
            {
                px = -uy;
                py = ux;
            }
            double half = chord / 2.0;
            double radius = (half * half + depth * depth) / (2.0 * depth);
            // the centre sits on the far side of the chord from the bulge
            double cx = (ax + bx) / 2.0 + px * (depth - radius);
            double cy = (ay + by) / 2.0 + py * (depth - radius);
            double startX = ax - cx, startY = ay - cy, endX = bx - cx, endY = by - cy;
            double startAngle = Math.Atan2(startY, startX);
            double sweep = Math.Atan2(startX * endY - startY * endX, startX * endX + startY * endY);

            var points = new List<XYZ> { ends[0] };
            for (int step = 1; step <= count; step++)
            {
                double angle = startAngle + sweep * ((double)step / (count + 1));
                points.Add(new XYZ(cx + radius * Math.Cos(angle), cy + radius * Math.Sin(angle), planeZ));
            }
            points.Add(ends[1]);
            return points;
        }

        /// <summary>How deep the arc should be, in feet: a share of the span (every wire sweeps by the same proportion) or a fixed paper measurement.</summary>
        public static double Sagitta(View view, string mode, double number, double chordLength)
        {
            double depth = (mode ?? "").Trim().ToLowerInvariant() == "paper" ? Paper(view, number) : chordLength * (number / 100.0);
            return Math.Max(0.0, Math.Min(depth, chordLength * 0.49));
        }

        /// <summary>An angle off the fitting, a straight run across, and an angle back in - what a chamfered wire is meant to look like.</summary>
        public static List<XYZ> ChamferThrough(double ax, double ay, double bx, double by, double offset, string side, double angleDeg, int extra, double planeZ)
        {
            double dx = bx - ax, dy = by - ay;
            double chord = Math.Sqrt(dx * dx + dy * dy);
            var ends = new List<XYZ> { new XYZ(ax, ay, planeZ), new XYZ(bx, by, planeZ) };
            if (chord < 1.0e-9) return ends;
            double ux = dx / chord, uy = dy / chord;
            double px, py;
            if ((side ?? "").Trim().ToLowerInvariant() == "right")
            {
                px = uy;
                py = -ux;
            }
            else
            {
                px = -uy;
                py = ux;
            }
            double depth = Math.Max(0.0, Math.Abs(offset));
            if (depth < 1.0e-9) return ends;
            double angle = Math.Max(5.0, Math.Min(85.0, angleDeg));
            double inset = depth / Math.Tan(angle * Math.PI / 180.0);
            // the two cranks must leave a straight between them
            inset = Math.Min(inset, chord * 0.45);
            var first = new XYZ(ax + ux * inset + px * depth, ay + uy * inset + py * depth, planeZ);
            var last = new XYZ(bx - ux * inset + px * depth, by - uy * inset + py * depth, planeZ);
            var points = new List<XYZ> { ends[0], first };
            for (int step = 1; step <= Math.Max(0, extra); step++)
            {
                double position = (double)step / (extra + 1);
                points.Add(new XYZ(first.X + (last.X - first.X) * position, first.Y + (last.Y - first.Y) * position, planeZ));
            }
            points.Add(last);
            points.Add(ends[1]);
            return points;
        }

        /// <summary>
        /// The vertices of one wire between two fittings. midCount is counted between the ends, so 1 gives the three-vertex wire with the middle at the
        /// deepest point of the arc. sag is the depth of the arc at its middle, already in feet.
        /// </summary>
        public static List<XYZ> SegmentPoints(XYZ pointA, XYZ pointB, double planeZ, double sag, string side, double trimA, double trimB,
                                              double midCount = 1, string wiring = "arc", double chamferAngle = 45.0)
        {
            double dx = pointB.X - pointA.X, dy = pointB.Y - pointA.Y;
            double length = Math.Sqrt(dx * dx + dy * dy);
            if (length < 1.0e-9) return null;
            double ux = dx / length, uy = dy / length;
            double ceiling = length * 0.45;
            double startTrim = Math.Max(0.0, Math.Min(trimA, ceiling));
            double endTrim = Math.Max(0.0, Math.Min(trimB, ceiling));
            double ax = pointA.X + ux * startTrim, ay = pointA.Y + uy * startTrim;
            double bx = pointB.X - ux * endTrim, by = pointB.Y - uy * endTrim;
            int count = ClampVertices(midCount);
            if ((wiring ?? "").Trim().ToLowerInvariant() == "chamfer")
            {
                // the crank takes two vertices of its own, so anything above two is spread along the straight between them
                return ChamferThrough(ax, ay, bx, by, sag, side, chamferAngle, Math.Max(0, count - 2), planeZ);
            }
            return ArcThrough(ax, ay, bx, by, sag, side, count, planeZ);
        }

        /// <summary>The distance between vertices, from the run as a whole, so a span of average length gets the number asked for and the rest in proportion.</summary>
        public static double VertexSpacing(IEnumerable<double> spanLengths, double onAverageSpan)
        {
            List<double> lengths = spanLengths.Where(v => v > 1.0e-9).ToList();
            if (lengths.Count == 0) return 0.0;
            if (onAverageSpan < 0.5) return 0.0;
            double average = lengths.Sum() / lengths.Count;
            return average / (onAverageSpan + 1.0);
        }

        public static int VerticesFor(double spanLength, double spacing, int ceiling = 8)
        {
            if (spacing <= 0.0 || spanLength <= 0.0) return 0;
            int count = (int)Math.Round(spanLength / spacing, MidpointRounding.AwayFromZero) - 1;
            return Math.Max(0, Math.Min(ceiling, count));
        }

        // ------------------------------------------------------------------ plan extent of symbols
        private static BoundingBoxXYZ Box(Element element, View view)
        {
            foreach (View source in new[] { view, null })
            {
                try
                {
                    BoundingBoxXYZ box = element.get_BoundingBox(source);
                    if (box != null) return box;
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        /// <summary>
        /// Half the element's plan size along a direction, in feet: the support function of the bounding box, exact for a box and over-stating anything
        /// inside one, so the failure direction trims the wire further clear of the symbol rather than into it.
        /// </summary>
        public static double PlanHalfExtent(Element element, View view, double dirX, double dirY)
        {
            BoundingBoxXYZ box = Box(element, view);
            if (box == null) return 0.0;
            try
            {
                double halfX = Math.Abs(box.Max.X - box.Min.X) / 2.0, halfY = Math.Abs(box.Max.Y - box.Min.Y) / 2.0;
                return Math.Abs(dirX) * halfX + Math.Abs(dirY) * halfY;
            }
            catch (Exception)
            {
                return 0.0;
            }
        }

        /// <summary>A plan radius for the symbol: the smaller half of the bounding box, so under-stating leaves the wire a touch short rather than through the symbol.</summary>
        public static double SymbolRadius(Element element, View view)
        {
            BoundingBoxXYZ box = Box(element, view);
            if (box == null) return 0.0;
            try
            {
                return Math.Min(Math.Abs(box.Max.X - box.Min.X) / 2.0, Math.Abs(box.Max.Y - box.Min.Y) / 2.0);
            }
            catch (Exception)
            {
                return 0.0;
            }
        }

        /// <summary>A direction-independent plan radius: half the bounding box diagonal in plan, which over-states a round symbol - the right way to be wrong here.</summary>
        public static double PlanRadius(Element element, View view)
        {
            BoundingBoxXYZ box = Box(element, view);
            if (box == null) return 0.0;
            try
            {
                double halfX = Math.Abs(box.Max.X - box.Min.X) / 2.0, halfY = Math.Abs(box.Max.Y - box.Min.Y) / 2.0;
                return Math.Sqrt(halfX * halfX + halfY * halfY);
            }
            catch (Exception)
            {
                return 0.0;
            }
        }

        public static double PointToSegment(double px, double py, double ax, double ay, double bx, double by)
        {
            double dx = bx - ax, dy = by - ay;
            double span = dx * dx + dy * dy;
            if (span < 1.0e-18) return Math.Sqrt((px - ax) * (px - ax) + (py - ay) * (py - ay));
            double position = ((px - ax) * dx + (py - ay) * dy) / span;
            position = Math.Max(0.0, Math.Min(1.0, position));
            double nx = ax + dx * position, ny = ay + dy * position;
            return Math.Sqrt((px - nx) * (px - nx) + (py - ny) * (py - ny));
        }

        /// <summary>True where every part of the run stays `radius` clear of a point.</summary>
        public static bool PolylineClears(List<XYZ> points, double ox, double oy, double radius)
        {
            for (int i = 0; i < points.Count - 1; i++)
            {
                if (PointToSegment(ox, oy, points[i].X, points[i].Y, points[i + 1].X, points[i + 1].Y) < radius) return false;
            }
            return true;
        }

        // ------------------------------------------------------------------ how far back off a symbol a wire stops
        /// <summary>
        /// How far short of a fitting a wire should stop, in feet. The ceilings matter more than the measurement: a fitting's bounding box is not its
        /// symbol, so a trim is capped at a paper measurement and at a third of the span, and the caller is told when the cap bit.
        /// </summary>
        public static double TrimDistance(View view, Dictionary<string, string> settings, Element element, double dirX, double dirY, double reach, out bool capped)
        {
            double gap = Paper(view, WiresSettings.Float(settings, "trim_gap_paper_mm"));
            double wanted;
            if (WiresSettings.Lower(settings, "trim_from", "extent") == "fixed") wanted = Paper(view, WiresSettings.Float(settings, "trim_fixed_paper_mm"));
            else wanted = PlanHalfExtent(element, view, dirX, dirY) + gap;
            double ceiling = Paper(view, WiresSettings.Float(settings, "trim_max_paper_mm"));
            if (ceiling <= 0.0) ceiling = Paper(view, 6);
            double limit = Math.Min(ceiling, Math.Max(0.0, reach) / 3.0);
            double trim = Math.Max(0.0, Math.Min(wanted, limit));
            capped = wanted > limit + 1.0e-9;
            return trim;
        }

        public static double TrimDistance(View view, Dictionary<string, string> settings, Element element, double dirX, double dirY, double reach)
        {
            bool capped;
            return TrimDistance(view, settings, element, dirX, dirY, reach, out capped);
        }

        /// <summary>
        /// The point a wire arriving from fromPoint should stop at. One rule, used both when a wire is drawn and when an existing one is re-aligned, so a
        /// redrawn circuit and a tidied one agree on where a wire meets its fitting.
        /// </summary>
        public static XYZ ArrivalPoint(View view, Dictionary<string, string> settings, Element element, XYZ centre, XYZ fromPoint, double? planeZ = null, string mode = null)
        {
            if (centre == null || fromPoint == null) return null;
            double z = planeZ ?? centre.Z;
            if (mode == null) mode = WiresSettings.Get(settings, "align_target", "trim");
            mode = (mode ?? "").Trim().ToLowerInvariant();
            if (mode == "centre") return new XYZ(centre.X, centre.Y, z);

            double dx = centre.X - fromPoint.X, dy = centre.Y - fromPoint.Y;
            double reach = Math.Sqrt(dx * dx + dy * dy);
            if (reach < 1.0e-9) return new XYZ(centre.X, centre.Y, z);
            double ux = dx / reach, uy = dy / reach;
            if (mode == "edge")
            {
                // where Revit itself puts a re-docked wire: the edge of the symbol
                double ceiling = Paper(view, WiresSettings.Float(settings, "trim_max_paper_mm"));
                double back = Math.Min(SymbolRadius(element, view), Math.Min(Math.Max(ceiling, 0.0), reach * 0.5));
                return new XYZ(centre.X - ux * back, centre.Y - uy * back, z);
            }
            double trim = TrimDistance(view, settings, element, ux, uy, reach);
            return new XYZ(centre.X - ux * trim, centre.Y - uy * trim, z);
        }
    }
}
