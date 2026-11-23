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
        // ===================================================== equipment / accessories
        private static bool Unit2(V3 v, out double x, out double y)
        {
            double len = Math.Sqrt(v.X * v.X + v.Y * v.Y);
            if (len > 1e-9) { x = v.X / len; y = v.Y / len; return true; }
            x = y = 0;
            return false;
        }

        /// <summary>A 'service' for a hanger under a unit (mechanical equipment or a duct accessory): the hanger spans
        /// ACROSS the unit at its bottom face.
        /// hand / facing: the unit's plan axes; pts: points on its geometry (world); bottomZ: its lowest downward face
        /// (else the lowest point); runHint: a plan direction the unit runs along (its in-line connectors), else the longer
        /// side; pick: where the user clicked (unused, as in the Python).
        /// Returns a section like a duct's (a, b through the unit's centre across, width across, depth so the invert is
        /// the bottom face) plus Unit, RunFrom, Length, Bottom.</summary>
        public static Section UnitSection(V3 hand, V3 facing, IList<V3> pts, double? bottomZ = null, V3? runHint = null, V3? pick = null)
        {
            double hx, hy, fx, fy;
            if (!Unit2(hand, out hx, out hy)) { hx = 1.0; hy = 0.0; }
            if (!Unit2(facing, out fx, out fy)) { fx = 0.0; fy = 1.0; }
            double ehMin = pts.Min(p => p.X * hx + p.Y * hy), ehMax = pts.Max(p => p.X * hx + p.Y * hy);
            double efMin = pts.Min(p => p.X * fx + p.Y * fy), efMax = pts.Max(p => p.X * fx + p.Y * fy);
            string runFrom = "longer side";
            bool hasHint = false;
            double ix = 0, iy = 0;
            if (runHint != null) hasHint = Unit2(runHint.Value, out ix, out iy);
            bool runIsH;
            if (hasHint)
            {
                runIsH = Math.Abs(ix * hx + iy * hy) >= Math.Abs(ix * fx + iy * fy);
                runFrom = "its connectors";
            }
            else runIsH = (ehMax - ehMin) >= (efMax - efMin);
            double rx, ry, runMin, runMax, ax, ay, acMin, acMax;
            if (runIsH) { rx = hx; ry = hy; runMin = ehMin; runMax = ehMax; ax = fx; ay = fy; acMin = efMin; acMax = efMax; }
            else { rx = fx; ry = fy; runMin = efMin; runMax = efMax; ax = hx; ay = hy; acMin = ehMin; acMax = ehMax; }
            double zMin = pts.Min(p => p.Z), zMax = pts.Max(p => p.Z);
            double bottom = bottomZ == null ? zMin : bottomZ.Value;
            double top = zMax;
            if (top - bottom < 1e-6) top = bottom + 1e-3;
            double zc = (bottom + top) / 2.0;
            double cAc = (acMin + acMax) / 2.0;
            Func<double, V3> at = s => new V3(rx * s + ax * cAc, ry * s + ay * cAc, zc);
            V3 a = at(runMin), b = at(runMax);
            double width = acMax - acMin;
            return new Section
            {
                A = a, B = b, Width = width, Depth = top - bottom, Round = false,
                Ins = 0.0, InsUsed = false, BareWidth = width, BareDepth = top - bottom,
                Unit = true, RunFrom = runFrom, Length = runMax - runMin, Bottom = bottom,
            };
        }

        /// <summary>Plan direction (z = 0) of an in-line unit from its connectors: two horizontal connectors facing
        /// opposite ways. Null if there is no pair.</summary>
        public static V3? InlineDirection(IList<InlineConn> conns)
        {
            var flat = conns.Where(c => Math.Abs(c.Basis.Z) < 0.1).ToList();
            for (int i = 0; i < flat.Count; i++)
                for (int j = i + 1; j < flat.Count; j++)
                {
                    V3 d1 = flat[i].Basis, d2 = flat[j].Basis;
                    if (d1.X * d2.X + d1.Y * d2.Y < -0.9) return new V3(d1.X, d1.Y, 0.0);
                }
            return null;
        }

        /// <summary>(left, right) stretch values. A single service: half its width each side. A group: the family's
        /// positive-axis side ('right', or 'left' when swapped) reaches the group's edge on that side, the other the
        /// opposite edge. axisVec: the family's axis in plan (x, y used).</summary>
        public static void SideValues(Section sec, V3 axisVec, double clearanceFt, out double left, out double right, bool swap = false)
        {
            if (sec.ExtNeg == null)
            {
                double h = sec.Width / 2.0 + clearanceFt;
                left = h; right = h;
                return;
            }
            V3 ac = sec.Across.Value;
            double s = axisVec.X * ac.X + axisVec.Y * ac.Y;
            double pos, neg;
            if (s >= 0) { pos = sec.ExtPos.Value; neg = sec.ExtNeg.Value; }
            else { pos = sec.ExtNeg.Value; neg = sec.ExtPos.Value; }
            double l = neg + clearanceFt, r = pos + clearanceFt;
            if (swap) { left = r; right = l; }
            else { left = l; right = r; }
        }

        // ============================================================ drop rods
        /// <summary>Drop rod from the hanger's reference level up to a target's underside.</summary>
        public static double? RodToTarget(double refZ, double? targetZ)
        {
            return RodLength(refZ, targetZ);
        }

        /// <summary>(positive, negative) reach of a hanger across the run, from the plan corners of its bounding box,
        /// measured from its centre point.</summary>
        public static void Reaches(IEnumerable<V3> corners, V3 centre, V3 across, out double positive, out double negative)
        {
            var proj = corners.Select(c => (c.X - centre.X) * across.X + (c.Y - centre.Y) * across.Y).ToList();
            positive = proj.Max();
            negative = -proj.Min();
        }

        /// <summary>True when the hanger came out the wrong way round: its long side is on the side that should be short.
        /// Families differ in which of their two stretch parameters points which way, so this is measured, not assumed.</summary>
        public static bool SidesMirrored(double reachPos, double reachNeg, double wantPos, double wantNeg, double tolFt = 1.0 / MM)
        {
            double asIs = Math.Abs(reachPos - wantPos) + Math.Abs(reachNeg - wantNeg);
            double swapped = Math.Abs(reachPos - wantNeg) + Math.Abs(reachNeg - wantPos);
            return swapped + tolFt < asIs;
        }
    }
}
