using System;
using System.Collections.Generic;

namespace RevoBIM.Tools.HangerAutomation
{
    // =====================================================================================================
    // Hanger Automation - Circular System Based floor supports: the pure rules (no Revit, no WPF).
    // Port of hcirc_core.py.
    //
    // The circular path is separate from the rectangular one: HfamCore / HfamRevit hold the rectangular rules
    // and never call anything here. A family is circular only when it is saved as Circular System Based in
    // Family settings (cfg style).
    // =====================================================================================================

    /// <summary>A round face or arc found in a placed support (pick_ring's cands): radius, centre, axis, kind, in model feet.</summary>
    public class RingCandidate
    {
        public double Radius;
        public V3 Centre, Axis;
        public string Kind;
        public RingCandidate() { }
        public RingCandidate(double radius, V3 centre, V3 axis, string kind) { Radius = radius; Centre = centre; Axis = axis; Kind = kind; }
    }

    /// <summary>The ring pick_ring found: Z (the ring centre's height where the axis passes q), R, Kind, Off (plan distance of
    /// the axis from q), Along (|cos| between the axis and the run: 1 = the service runs through the ring), Centre (the point
    /// on the axis nearest q).</summary>
    public class RingMeasure
    {
        public double Z, R, Off, Along;
        public string Kind;
        public V3 Centre;
    }

    public static class HcircCore
    {
        public const double RingTolMm = 30.0;      // a round face / arc counts as the ring within this of half the diameter ...
        public const double RingTolShare = 0.35;   // ... or this share of it, whichever is larger
        public const double CentreOkMm = 1.0;      // the ring centre is 'on' the service centre within this

        /// <summary>A family saved as Circular System Based: a floor support or (1.14.0) a hanger - the style is saved per
        /// family, whichever tab saved it.</summary>
        public static bool IsCirc(FamConfig cfg)
        {
            return cfg != null && cfg.Style == "circ";
        }

        /// <summary>Where the family's X must point so the service runs along its X - or, runAxis 'Y', along its Y (X then
        /// lies across the service).</summary>
        public static V3 CircXDir(string runAxis, V3 along, V3 across)
        {
            return runAxis == "Y" ? across : along;
        }

        /// <summary>The rectangular 'width runs along' axis that turns a family the same way (for the dimension placer,
        /// which reads hangers by their width axis).</summary>
        public static string WidthAxis(string runAxis)
        {
            return runAxis != "Y" ? "Y" : "X";
        }

        /// <summary>The support height parameter: from the base (the level, or the top of the floor / roof / equipment
        /// picked) up to the service centre AT THIS SUPPORT - the family's height parameter runs from its reference level
        /// to the ring centre, so the ring sits on the service's centreline, and a sloping pipe gets a different height at
        /// every support. The same rule as the rectangular supports' first bar, but to the centre, not the invert.</summary>
        public static double SupportHeight(double zCentre, double standZ)
        {
            return zCentre - standZ;
        }

        /// <summary>A circular hanger's offset from its level: its reference goes on the service centreline (1.14.1) - the
        /// pipe / round duct centre where it hangs, so it follows a sloping pipe. (A Rectangular Hanger System hanger goes
        /// at the invert instead - HfamRevit, unchanged.)</summary>
        public static double HangerOffset(double zCentre, double levelZ)
        {
            return zCentre - levelZ;
        }

        /// <summary>How far (ft) the measured ring centre sits above (+) / below (-) the service centre - a check only:
        /// the height is never changed by it.</summary>
        public static double RingOff(double ringZ, double zCentre)
        {
            return ringZ - zCentre;
        }

        public static double RingTol(double wantR)
        {
            return Math.Max(RingTolMm / FhaCore.MM, wantR * RingTolShare);
        }

        private static double Round1(double v)
        {
            return Math.Round(v, 1, MidpointRounding.AwayFromZero);
        }

        /// <summary>The ring in a placed support from its round faces and arcs.
        /// cands: radius, centre, axis, kind in model feet. The ring's axis is level, it passes close to the service
        /// centre q in plan, and its radius is nearest half the diameter set. Returns the ring (Z = the ring centre's height
        /// where the axis passes q, R, Kind, Off = plan distance of the axis from q, Along = |cos| between the axis and the
        /// run: 1 = the service runs through the ring) - or null.</summary>
        public static RingMeasure PickRing(IEnumerable<RingCandidate> cands, double wantR, V3 q, V3 along)
        {
            double tol = RingTol(wantR);
            RingMeasure best = null;
            double bestK0 = 0, bestK1 = 0;
            foreach (RingCandidate cand in cands)
            {
                double r = cand.Radius;
                V3 c = cand.Centre;
                V3 a = cand.Axis;
                double la = FhaCore.VLen(a);
                if (la < 1e-9 || r <= 0) continue;
                a = FhaCore.VScale(a, 1.0 / la);
                if (Math.Abs(a.Z) > 0.25) continue;           // a level ring only (its axis runs flat)
                if (Math.Abs(r - wantR) > tol) continue;
                V3 d = FhaCore.VSub(q, c);
                double t = FhaCore.VDot(d, a);
                V3 foot = FhaCore.VAdd(c, FhaCore.VScale(a, t));   // the point on the axis nearest q
                double off = Math.Sqrt((q.X - foot.X) * (q.X - foot.X) + (q.Y - foot.Y) * (q.Y - foot.Y));
                if (off > wantR + tol) continue;
                V3 plan = new V3(a.X, a.Y, 0.0);
                double lp = FhaCore.VLen(plan);
                double cos = lp > 1e-9 ? Math.Abs(FhaCore.VDot(plan, along)) / lp : 0.0;
                double k0 = Round1(Math.Abs(r - wantR) * FhaCore.MM), k1 = Round1(off * FhaCore.MM);
                if (best == null || k0 < bestK0 || (k0 == bestK0 && k1 < bestK1))
                {
                    bestK0 = k0; bestK1 = k1;
                    best = new RingMeasure { Z = foot.Z, R = r, Kind = cand.Kind, Off = off, Along = cos, Centre = foot };
                }
            }
            return best;
        }
    }
}
