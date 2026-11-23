using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamCore
    {
        public static double Dw144SpacingMm(double widthMm, double depthMm, bool isRound)
        {
            double size = isRound ? widthMm : Math.Max(widthMm, depthMm);
            foreach (double[] r in (isRound ? Dw144Round : Dw144Rect))
                if (size <= r[0] + 1e-6) return r[1];
            return Dw144Rect[Dw144Rect.Length - 1][1];
        }

        public static double SpanSpacingMm(double userMaxMm, bool useDw144, double widthMm, double depthMm, bool isRound)
        {
            double s = Math.Max(100.0, userMaxMm);
            if (useDw144) s = Math.Min(s, Dw144SpacingMm(widthMm, depthMm, isRound));
            return s;
        }

        /// <summary>FhaCore.PlanStations config for one span of family hangers.</summary>
        public static PlanConfig AutoConfig(IDictionary<string, string> settings, double spacingMm)
        {
            return new PlanConfig
            {
                Spacing = spacingMm,
                StartOff = FhaCore.AsFloat(settings, "fam_start_off", 300.0),
                EndOff = FhaCore.AsFloat(settings, "fam_end_off", 300.0),
                TakeoffMax = 600.0,
                TakeoffClear = FhaCore.AsFloat(settings, "fam_takeoff_clear", 400.0),
                MinGap = 500.0,
                Edge = Math.Max(100.0, FhaCore.AsFloat(settings, "fam_flange_clear", 150.0)),
            };
        }

        // ============================================================ placement
        /// <summary>Value for each of the two stretch parameters: half the duct plus clearance.</summary>
        public static double HalfWidth(double widthFt, double clearanceMm)
        {
            return widthFt / 2.0 + clearanceMm / MM;
        }

        /// <summary>Drop rod from the family's reference level (the duct invert) up to the soffit, or null when the
        /// soffit is not above it (or there is none).</summary>
        public static double? RodLength(double refZ, double? soffitZ)
        {
            if (soffitZ == null) return null;
            double len = soffitZ.Value - refZ;
            if (len > 1e-6) return len;
            return null;
        }

        /// <summary>Lowest level elevation strictly above z (the base of the level above), else null.</summary>
        public static double? LevelAbove(IEnumerable<double> levelElevations, double z, double tolFt = 1.0 / MM)
        {
            double? best = null;
            foreach (double e in levelElevations)
                if (e > z + tolFt && (best == null || e < best.Value)) best = e;
            return best;
        }

        public static double? LevelBelow(IEnumerable<double> levelElevations, double z, double tolFt = 1.0 / MM)
        {
            double? best = null;
            foreach (double e in levelElevations)
                if (e <= z + tolFt && (best == null || e > best.Value)) best = e;
            return best;
        }

        /// <summary>Plan rotation (radians) turning `current` onto `wanted` (x, y of each). A hanger is symmetric, so
        /// facing either way is aligned: the answer is folded into (-90, 90] degrees so it never spins a hanger round needlessly.</summary>
        public static double RotationTo(double currentX, double currentY, double wantedX, double wantedY)
        {
            double a = Math.Atan2(currentX * wantedY - currentY * wantedX,
                                  currentX * wantedX + currentY * wantedY);
            while (a > Math.PI / 2.0 + 1e-9) a -= Math.PI;
            while (a <= -Math.PI / 2.0 + 1e-9) a += Math.PI;
            return a;
        }

        public static double RotationTo(V3 current, V3 wanted)
        {
            return RotationTo(current.X, current.Y, wanted.X, wanted.Y);
        }

        /// <summary>(along, across) unit plan vectors of a duct from a to b.</summary>
        public static void PlanDirs(V3 a, V3 b, out V3 along, out V3 across)
        {
            V3 d = FhaCore.VNorm(new V3(b.X - a.X, b.Y - a.Y, 0.0));
            along = d;
            across = new V3(-d.Y, d.X, 0.0);
        }

        /// <summary>Where the family's own X axis must point: across the duct when its width runs along X, along the duct
        /// when its width runs along Y.</summary>
        public static V3 FamilyXDir(string axis, V3 along, V3 across)
        {
            return axis == "X" ? across : along;
        }

        /// <summary>Closest point to p on the duct centreline a-b, kept marginFt off the ends.</summary>
        public static V3 OnCentreline(V3 a, V3 b, V3 p, double marginFt)
        {
            V3 ab = FhaCore.VSub(b, a);
            double len = FhaCore.VLen(ab);
            if (len < 1e-9) return a;
            double t, d; V3 q;
            FhaCore.ClosestOnSegment(p, a, b, out t, out q, out d);
            double s = t * len;
            if (len > 2.0 * marginFt) s = Math.Max(marginFt, Math.Min(len - marginFt, s));
            else s = len / 2.0;
            return FhaCore.VAdd(a, FhaCore.VScale(ab, s / len));
        }

        // ============================================================== re-align
        /// <summary>Unclamped position of p along a-b in plan (0 at a, 1 at b).</summary>
        public static double LineParam(V3 a, V3 b, V3 p)
        {
            double abx = b.X - a.X, aby = b.Y - a.Y;
            double den = abx * abx + aby * aby;
            if (den < 1e-12) return 0.0;
            return ((p.X - a.X) * abx + (p.Y - a.Y) * aby) / den;
        }

        /// <summary>The point on the duct's centreline square across from p: p keeps its position along the run and only
        /// its sideways offset changes. The line is NOT clipped to the segment, so a hanger beyond this segment's end stays
        /// exactly where it is along the run. Z follows the centreline (sloped ducts).</summary>
        public static V3 OnLine(V3 a, V3 b, V3 p)
        {
            double t = LineParam(a, b, p);
            return new V3(a.X + (b.X - a.X) * t, a.Y + (b.Y - a.Y) * t, a.Z + (b.Z - a.Z) * t);
        }

        public static double PlanOffset(V3 a, V3 b, V3 p)
        {
            V3 q = OnLine(a, b, p);
            return Math.Sqrt((p.X - q.X) * (p.X - q.X) + (p.Y - q.Y) * (p.Y - q.Y));
        }

        /// <summary>The segment the hanger actually sits on: p falls within its length (tolFt either end, for hangers on
        /// a joint) and it is the nearest in plan. Null when p is off every segment.</summary>
        public static long? PickSegment(V3 p, IEnumerable<KeySeg> segs, double tolFt)
        {
            long? bestKey = null;
            double bestOff = 0;
            foreach (KeySeg s in segs)
            {
                double len = Math.Sqrt((s.B.X - s.A.X) * (s.B.X - s.A.X) + (s.B.Y - s.A.Y) * (s.B.Y - s.A.Y));
                if (len < 1e-9) continue;
                double t = LineParam(s.A, s.B, p);
                double slack = tolFt / len;
                if (t < -slack || t > 1.0 + slack) continue;
                double off = PlanOffset(s.A, s.B, p);
                if (bestKey == null || off < bestOff)
                {
                    bestOff = off;
                    bestKey = s.Key;
                }
            }
            return bestKey;
        }
    }
}
