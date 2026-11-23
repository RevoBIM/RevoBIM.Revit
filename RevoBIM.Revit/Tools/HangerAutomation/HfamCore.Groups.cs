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
        // ============================================================ dimensions
        /// <summary>A plan direction with its sign fixed (pointing +X, or +Y when vertical), so hangers facing either way
        /// along a run agree.</summary>
        public static V3 CanonicalDir(V3 d)
        {
            V3 n = FhaCore.VNorm(new V3(d.X, d.Y, 0.0));
            if (n.X < -1e-6 || (Math.Abs(n.X) <= 1e-6 && n.Y < 0))
                n = new V3(-n.X, -n.Y, 0.0);
            return n;
        }

        private class RunGroupAcc
        {
            public V3 Dir;
            public double Off;
            public List<KeyValuePair<double, long>> Members = new List<KeyValuePair<double, long>>();
        }

        /// <summary>One group per straight line of hangers (same direction, same line within lineTolFt), 2 or more,
        /// each with the keys sorted along the run.</summary>
        public static List<RunGroup> GroupRuns(IEnumerable<RunHanger> hangers, double lineTolFt, double angleTolDeg = 3.0)
        {
            var groups = new List<RunGroupAcc>();
            double cosTol = Math.Cos(angleTolDeg * (Math.PI / 180.0));
            foreach (RunHanger h in hangers)
            {
                V3 d = CanonicalDir(h.Along);
                if (d.X == 0.0 && d.Y == 0.0 && d.Z == 0.0) continue;
                double nx = -d.Y, ny = d.X;
                double off = h.P.X * nx + h.P.Y * ny;
                double s = h.P.X * d.X + h.P.Y * d.Y;
                RunGroupAcc home = null;
                foreach (RunGroupAcc g in groups)
                {
                    if (Math.Abs(g.Dir.X * d.X + g.Dir.Y * d.Y) >= cosTol && Math.Abs(g.Off - off) <= lineTolFt)
                    {
                        home = g;
                        break;
                    }
                }
                if (home == null)
                {
                    var g = new RunGroupAcc { Dir = d, Off = off };
                    g.Members.Add(new KeyValuePair<double, long>(s, h.Key));
                    groups.Add(g);
                }
                else home.Members.Add(new KeyValuePair<double, long>(s, h.Key));
            }
            var o = new List<RunGroup>();
            foreach (RunGroupAcc g in groups)
            {
                if (g.Members.Count >= 2)
                {
                    var sorted = g.Members.ToList();
                    sorted.Sort((x, y) => x.Key != y.Key ? x.Key.CompareTo(y.Key) : x.Value.CompareTo(y.Value));
                    var rg = new RunGroup { Dir = g.Dir };
                    foreach (var m in sorted) rg.Keys.Add(m.Value);
                    o.Add(rg);
                }
            }
            return o;
        }

        /// <summary>Which centre reference of a family instance is square to the run: CenterLeftRight is the plane across
        /// the family's X (hand), CenterFrontBack across its Y (facing). The one whose normal lies along the run wins.
        /// (Only x and y of each vector are used.)</summary>
        public static string ReferenceTypeAcross(V3 hand, V3 facing, V3 along)
        {
            double h = Math.Abs(hand.X * along.X + hand.Y * along.Y);
            double f = Math.Abs(facing.X * along.X + facing.Y * along.Y);
            return h >= f ? "CenterLeftRight" : "CenterFrontBack";
        }

        // ============================================================ insulation
        /// <summary>The size a hanger has to fit. Outside insulation (the default) the hanger wraps the insulated duct:
        /// width + 2t, depth + 2t, so the invert it sits on drops by t. Inside, it fits the bare duct. Returns a new
        /// section; BareWidth / BareDepth keep the duct's own size.</summary>
        public static Section ApplyInsulation(Section sec, bool outside)
        {
            double t = sec.Ins;
            Section o = sec.Clone();
            o.BareWidth = sec.Width;
            o.BareDepth = sec.Depth;
            o.InsUsed = outside && t > 0;
            if (o.InsUsed)
            {
                o.Width = sec.Width + 2.0 * t;
                o.Depth = sec.Depth + 2.0 * t;
            }
            return o;
        }

        /// <summary>The rules for services the user selected to hang together: no gap or height limit (they were
        /// chosen), only parallel and alongside count.</summary>
        public static GroupRules WrapRules(GroupRules rules)
        {
            return new GroupRules(1.0e9, 1.0e9, rules.AngleDeg, rules.Centre);
        }

        /// <summary>(z_tol_ft, gap_tol_ft, angle_deg, centre) from the Hanger rules settings.</summary>
        public static GroupRules GroupRulesFrom(IDictionary<string, string> settings)
        {
            string centre;
            if (!settings.TryGetValue("fam_group_centre", out centre) || (centre != "mean" && centre != "edges")) centre = "mean";
            return new GroupRules(FhaCore.AsFloat(settings, "fam_group_z", BundleZMm) / MM,
                                  FhaCore.AsFloat(settings, "fam_group_gap", BundleGapMm) / MM,
                                  FhaCore.AsFloat(settings, "fam_group_angle", BundleAngleDeg),
                                  centre);
        }

        private class BundleRow
        {
            public long Key;
            public double Off, W, Bottom, Top;
            public bool Lead;
        }

        public static HangerBundle Bundle(V3 point, IList<BundleMember> members, double zTolFt = BundleZMm / MM, double gapTolFt = BundleGapMm / MM,
                                    double angleDeg = BundleAngleDeg, string centre = "mean")
        {
            // One hanger round several services.
            //
            // members: [(key, a, b, width, depth)] with the sizes the hanger has to fit (insulation already applied);
            // members[0] is the service the hanger was placed for (the lead), `point` is on or near its centreline.
            //
            // A service joins when it is parallel to the lead (within angle_deg), runs alongside it at this point, its
            // clear gap in plan to the group's nearest edge is under gap_tol_ft (chained neighbour to neighbour), and every
            // bottom in the group stays within z_tol_ft of the others.
            //
            // The hanger is centred on the mean of the members' centres ('mean'), or midway between the outer edges
            // ('edges'); ext_neg / ext_pos are how far it must reach either side of that centre (along `across`, the
            // lead's plan normal) to the outer edges. It sits at the lowest bottom.
            //
            // Returns keys, width, ext_neg, ext_pos, across, bottom, top, point, a, b, notes; a / b are the lead's
            // centreline moved to the hanger centre and down to the lowest bottom, so the hanger can be fitted to it
            // like a single service of depth 0.
            BundleMember m0 = members[0];
            V3 a0 = m0.A, b0 = m0.B;
            V3 along, across;
            PlanDirs(a0, b0, out along, out across);
            V3 q0 = OnLine(a0, b0, point);
            double cosTol = Math.Cos(angleDeg * (Math.PI / 180.0));
            var rows = new List<BundleRow>();
            var notes = new List<string>();
            for (int i = 0; i < members.Count; i++)
            {
                BundleMember m = members[i];
                if (i != 0)
                {
                    V3 dd, dn;
                    PlanDirs(m.A, m.B, out dd, out dn);
                    if (Math.Abs(dd.X * along.X + dd.Y * along.Y) < cosTol)
                    {
                        notes.Add(L(m.Key) + ": not parallel");
                        continue;
                    }
                    double t = LineParam(m.A, m.B, q0);
                    if (t < -1e-6 || t > 1.0 + 1e-6)
                    {
                        notes.Add(L(m.Key) + ": does not run alongside here");
                        continue;
                    }
                }
                V3 q = OnLine(m.A, m.B, q0);
                double off = (q.X - q0.X) * across.X + (q.Y - q0.Y) * across.Y;
                rows.Add(new BundleRow { Key = m.Key, Off = off, W = m.Width, Bottom = q.Z - m.Depth / 2.0, Top = q.Z + m.Depth / 2.0, Lead = i == 0 });
            }
            rows = rows.Select((r, idx) => new { r, idx }).OrderBy(z => z.r.Off).ThenBy(z => z.idx).Select(z => z.r).ToList();   // stable sort on off
            int li = 0;
            for (int i = 0; i < rows.Count; i++) if (rows[i].Lead) { li = i; break; }
            int lo = li, hi = li;
            var bottoms = new List<double> { rows[li].Bottom };

            Func<int, int, double> gap = (i, j) => (rows[j].Off - rows[j].W / 2.0) - (rows[i].Off + rows[i].W / 2.0);   // clear gap between rows i < j

            while (true)
            {
                var options = new List<KeyValuePair<double, string>>();
                if (lo > 0) options.Add(new KeyValuePair<double, string>(gap(lo - 1, lo), "lo"));
                if (hi < rows.Count - 1) options.Add(new KeyValuePair<double, string>(gap(hi, hi + 1), "hi"));
                options.Sort((x, y) => x.Key != y.Key ? x.Key.CompareTo(y.Key) : string.CompareOrdinal(x.Value, y.Value));
                bool grown = false;
                foreach (var opt in options)
                {
                    double g = opt.Key;
                    string side = opt.Value;
                    int j = side == "lo" ? lo - 1 : hi + 1;
                    var nb = new List<double>(bottoms) { rows[j].Bottom };
                    if (g < gapTolFt && nb.Max() - nb.Min() <= zTolFt + 1e-9)
                    {
                        bottoms = nb;
                        if (side == "lo") lo = j;
                        else hi = j;
                        grown = true;
                        break;
                    }
                }
                if (!grown) break;
            }
            var group = rows.GetRange(lo, hi - lo + 1);
            for (int i = 0; i < rows.Count; i++)
            {
                BundleRow r = rows[i];
                if ((lo <= i && i <= hi) || r.Lead) continue;
                int near = i < lo ? lo - 1 : hi + 1;
                double g = i < lo ? gap(i, lo) : gap(hi, i);
                var nb = new List<double>(bottoms) { r.Bottom };
                var why = new List<string>();
                if (i == near && g >= gapTolFt)
                    why.Add("gap " + F0(g * MM) + " mm (limit " + F0(gapTolFt * MM) + ")");
                if (nb.Max() - nb.Min() > zTolFt + 1e-9)
                    why.Add("height differs by " + F0((nb.Max() - nb.Min()) * MM) + " mm (limit " + F0(zTolFt * MM) + ")");
                notes.Add(L(r.Key) + ": left out - " + (why.Count > 0 ? string.Join(", ", why) : "beyond a service that was left out"));
            }
            double left = group.Min(r => r.Off - r.W / 2.0);
            double right = group.Max(r => r.Off + r.W / 2.0);
            double c;
            if (centre == "edges" || group.Count == 1) c = (left + right) / 2.0;
            else
            {
                double sum = 0.0;
                foreach (BundleRow r in group) sum += r.Off;
                c = sum / (double)group.Count;
            }
            double bottom = bottoms.Min();
            double dz = bottom - q0.Z;
            V3 shift = new V3(across.X * c, across.Y * c, dz);
            var res = new HangerBundle
            {
                Width = right - left,
                ExtNeg = c - left,
                ExtPos = right - c,
                Across = across,
                Bottom = bottom,
                Top = group.Max(r => r.Top),
                Notes = notes,
                Point = new V3(q0.X + shift.X, q0.Y + shift.Y, bottom),
                A = FhaCore.VAdd(a0, shift),
                B = FhaCore.VAdd(b0, shift),
            };
            foreach (BundleRow r in group) res.Keys.Add(r.Key);
            return res;
        }

        /// <summary>The section the hanger fitting code uses.
        /// A single service (no neighbours joined) keeps its OWN section - round flag, depth, insulation - so it is fitted
        /// and locked exactly like a hanger placed with no pre-selection. A group becomes depth 0 on a line at the lowest
        /// bottom, carrying how far to reach either side of its centre.</summary>
        public static Section BundleSection(HangerBundle b, Section leadSec)
        {
            if (b.Keys.Count <= 1)
            {
                Section s = leadSec.Clone();
                s.Keys = new List<long>(b.Keys);
                return s;
            }
            return new Section
            {
                A = b.A, B = b.B, Width = b.Width, Depth = 0.0, Round = false,
                Ins = leadSec.Ins, InsUsed = leadSec.InsUsed,
                BareWidth = b.Width, BareDepth = 0.0, Keys = b.Keys,
                ExtNeg = b.ExtNeg, ExtPos = b.ExtPos, Across = b.Across,
                SpanHeight = b.Top - b.Bottom,
            };
        }

        /// <summary>Where the hanger goes: a group's centre at its lowest bottom, or a single service's own centreline
        /// (its invert follows from its depth).</summary>
        public static V3 BundlePoint(HangerBundle b, Section leadSec, V3 point)
        {
            if (b.Keys.Count <= 1) return OnLine(leadSec.A, leadSec.B, point);
            return b.Point;
        }
    }
}
