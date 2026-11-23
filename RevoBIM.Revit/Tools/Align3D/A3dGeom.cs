using System;

namespace RevoBIM.Tools.Align3D
{
    public struct A3dPoint
    {
        public double X, Y, Z;
        public A3dPoint(double x, double y, double z) { X = x; Y = y; Z = z; }
    }

    /// <summary>The two end points of an element's location line - its centreline for pipes, ducts, cable trays and conduits.</summary>
    public sealed class A3dAxis
    {
        public A3dPoint P0, P1;
        public A3dAxis(A3dPoint p0, A3dPoint p1) { P0 = p0; P1 = p1; }
    }

    public sealed class A3dPlan
    {
        public bool Ok;
        public string FirstKind, SecondKind;
        public double MoveX, MoveY, MoveZ;
        public double Distance;
        public bool Already;
        public string Mode = "";
        public string Reason = "";
    }

    /// <summary>
    /// 3D Align - the alignment rules (port of a3d_geom.py). No Revit in here. Lengths are Revit's internal decimal feet.
    /// </summary>
    public static class A3dGeom
    {
        /// <summary>Steeper than this is an upright, the same line Drainage Elevation Match uses.</summary>
        public const double SteepDeg = 46.0;
        /// <summary>Closer than this in plan counts as aligned: nothing is moved.</summary>
        public const double AlignedMm = 0.1;
        public const double AlignedFt = AlignedMm / A3dSettings.MmPerFt;

        public const string Vertical = "vertical";
        public const string Horizontal = "horizontal";

        private const double Eps = 1e-9;

        private sealed class Frame
        {
            public double Ox, Oy, Dx, Dy, Length;
        }

        public static string ModeLabel(string first, string second)
        {
            if (first == Vertical && second == Vertical) return "vertical to vertical - centred in X and Y";
            if (first == Vertical && second == Horizontal) return "horizontal centreline run through the vertical";
            return "vertical moved onto the horizontal centreline";
        }

        /// <summary>Angle of the axis above the horizontal plane, 0 to 90, or null if it has no length.</summary>
        public static double? PitchDeg(A3dAxis axis)
        {
            double plan = Math.Sqrt(Sq(axis.P1.X - axis.P0.X) + Sq(axis.P1.Y - axis.P0.Y));
            double rise = Math.Abs(axis.P1.Z - axis.P0.Z);
            if (plan < Eps && rise < Eps) return null;
            return Math.Atan2(rise, plan) * 180.0 / Math.PI;
        }

        private static double Sq(double v) { return v * v; }

        public static string Classify(A3dAxis axis)
        {
            if (axis == null) return null;
            double? pitch = PitchDeg(axis);
            if (pitch == null) return null;
            return pitch.Value > SteepDeg ? Vertical : Horizontal;
        }

        private static double MidZ(A3dAxis a) { return (a.P0.Z + a.P1.Z) / 2.0; }

        /// <summary>Where an upright's centreline sits in plan at height z. Follows the lean of one that is steep but not plumb.</summary>
        private static void XyAtZ(A3dAxis a, double z, out double x, out double y)
        {
            double dz = a.P1.Z - a.P0.Z;
            if (Math.Abs(dz) < Eps)
            {
                x = (a.P0.X + a.P1.X) / 2.0;
                y = (a.P0.Y + a.P1.Y) / 2.0;
                return;
            }
            double t = (z - a.P0.Z) / dz;
            x = a.P0.X + t * (a.P1.X - a.P0.X);
            y = a.P0.Y + t * (a.P1.Y - a.P0.Y);
        }

        private static Frame PlanFrame(A3dAxis a)
        {
            double length = Math.Sqrt(Sq(a.P1.X - a.P0.X) + Sq(a.P1.Y - a.P0.Y));
            if (length < Eps) return null;
            return new Frame { Ox = a.P0.X, Oy = a.P0.Y, Dx = (a.P1.X - a.P0.X) / length, Dy = (a.P1.Y - a.P0.Y) / length, Length = length };
        }

        /// <summary>Height of a (possibly falling) run at a plan distance along it.</summary>
        private static double ZAlong(A3dAxis a, Frame f, double along)
        {
            return a.P0.Z + (along / f.Length) * (a.P1.Z - a.P0.Z);
        }

        /// <summary>The plan vector from the nearest point on the line to the point, and how far along the line that nearest point is.</summary>
        private static void OffsetFromLine(double px, double py, Frame f, out double ox, out double oy, out double along)
        {
            double vx = px - f.Ox, vy = py - f.Oy;
            along = vx * f.Dx + vy * f.Dy;
            ox = vx - along * f.Dx;
            oy = vy - along * f.Dy;
        }

        public static bool IsAligned(double distanceFt) { return distanceFt < AlignedFt; }

        /// <summary>
        /// How far, and which way, the second element has to move in plan. The move is always horizontal (dz = 0) and, where a
        /// horizontal run is involved, always square to that run - so nothing slides along its own length and no height or fall changes.
        /// </summary>
        public static A3dPlan PlanAlignment(A3dAxis first, A3dAxis second)
        {
            string kind1 = Classify(first), kind2 = Classify(second);
            var output = new A3dPlan { FirstKind = kind1, SecondKind = kind2 };
            if (kind1 == null || kind2 == null)
            {
                output.Reason = "one of the elements has no length to take a centreline from";
                return output;
            }
            if (kind1 == Horizontal && kind2 == Horizontal)
            {
                output.Reason = "both are horizontal - click a vertical first to centre a run on it, or a horizontal first and then a vertical";
                return output;
            }

            double mx = 0.0, my = 0.0;
            if (kind1 == Vertical && kind2 == Vertical)
            {
                double z = MidZ(second);
                double tx, ty, cx, cy;
                XyAtZ(first, z, out tx, out ty);
                XyAtZ(second, z, out cx, out cy);
                mx = tx - cx;
                my = ty - cy;
            }
            else if (kind1 == Vertical)
            {
                Frame frame = PlanFrame(second);
                double z = MidZ(second);
                for (int i = 0; i < 3; i++)
                {
                    double tx, ty, along;
                    XyAtZ(first, z, out tx, out ty);
                    OffsetFromLine(tx, ty, frame, out mx, out my, out along);
                    z = ZAlong(second, frame, along);
                }
            }
            else
            {
                Frame frame = PlanFrame(first);
                double z = MidZ(first);
                for (int i = 0; i < 3; i++)
                {
                    double cx, cy, ox, oy, along;
                    XyAtZ(second, z, out cx, out cy);
                    OffsetFromLine(cx, cy, frame, out ox, out oy, out along);
                    mx = -ox;
                    my = -oy;
                    z = ZAlong(first, frame, along);
                }
            }

            double distance = Math.Sqrt(mx * mx + my * my);
            output.Ok = true;
            output.MoveX = mx;
            output.MoveY = my;
            output.MoveZ = 0.0;
            output.Distance = distance;
            output.Already = IsAligned(distance);
            output.Mode = ModeLabel(kind1, kind2);
            return output;
        }

        /// <summary>The largest distance either end point of an axis travelled.</summary>
        public static double MovedBy(A3dAxis before, A3dAxis after)
        {
            if (before == null || after == null) return 0.0;
            return Math.Max(Dist(before.P0, after.P0), Dist(before.P1, after.P1));
        }

        private static double Dist(A3dPoint a, A3dPoint b)
        {
            return Math.Sqrt(Sq(a.X - b.X) + Sq(a.Y - b.Y) + Sq(a.Z - b.Z));
        }
    }
}
