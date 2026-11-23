using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class FhaCore
    {
        // ------------------------------------------------------------------ dimensions
        /// <summary>Side of the run the dimension string goes on: toward -Y (below the run on screen), else +X for a run along Y.</summary>
        public static V3 ChooseNormal(V3 direction)
        {
            V3 n = VNorm(new V3(direction.Y, -direction.X, 0.0));
            if (Math.Abs(n.Y) > 1e-6)
            {
                if (n.Y > 0) n = VScale(n, -1.0);
            }
            else if (n.X < 0) n = VScale(n, -1.0);
            return n;
        }

        /// <summary>Dimension line for a span: parallel to it, offset to the chosen side and run a little past both ends.</summary>
        public static void DimLine(V3 pStart, V3 pEnd, double offsetMm, out V3 p0, out V3 p1, out V3 normal, double overMm = 300.0)
        {
            V3 d = VNorm(VSub(pEnd, pStart));
            V3 n = ChooseNormal(d);
            V3 off = VScale(n, offsetMm / MM);
            double ext = overMm / MM;
            p0 = VAdd(VAdd(pStart, off), VScale(d, -ext));
            p1 = VAdd(VAdd(pEnd, off), VScale(d, ext));
            normal = n;
        }

        /// <summary>Dimension line for a run seen in a section / elevation: offset DOWN the view and lying in the
        /// view's plane (through origin, normal the view direction) so Revit can draw it.</summary>
        public static void DimLineInView(V3 pStart, V3 pEnd, double offsetMm, V3 up, V3 normal, V3 origin, out V3 p0, out V3 p1, double overMm = 300.0)
        {
            V3 d = VNorm(VSub(pEnd, pStart));
            V3 off = VScale(VNorm(up), -offsetMm / MM);
            double ext = overMm / MM;
            V3 n = VNorm(normal);
            Func<V3, V3> onto = p => VSub(p, VScale(n, VDot(VSub(p, origin), n)));
            p0 = onto(VAdd(VAdd(pStart, off), VScale(d, -ext)));
            p1 = onto(VAdd(VAdd(pEnd, off), VScale(d, ext)));
        }

        /// <summary>items sorted by t; refs closer than tolFt keep the first.</summary>
        public static List<KeyValuePair<double, T>> CollapseRefs<T>(IEnumerable<KeyValuePair<double, T>> items, double tolFt)
        {
            var o = new List<KeyValuePair<double, T>>();
            // a stable sort on t, as Python's sorted(key=t)
            foreach (var kv in items.Select((x, i) => new { x, i }).OrderBy(z => z.x.Key).ThenBy(z => z.i).Select(z => z.x))
            {
                if (o.Count > 0 && kv.Key - o[o.Count - 1].Key < tolFt) continue;
                o.Add(kv);
            }
            return o;
        }

        // ------------------------------------------------------------------ rods
        /// <summary>Value to give SetRodLength so the rod top reaches hitZ. GetRodLength includes the structural
        /// extension, SetRodLength excludes it.</summary>
        public static double RodTargetLength(double curTotalFt, double endZ, double hitZ, double structExtFt = 0.0)
        {
            return (curTotalFt + (hitZ - endZ)) - structExtFt;
        }

        /// <summary>True if the rod top is at the soffit, or inside the allowed extension.</summary>
        public static bool RodOk(double endZ, double hitZ, double extFt, double tolFt)
        {
            return (Math.Abs(endZ - hitZ) <= tolFt) || (hitZ - tolFt <= endZ && endZ <= hitZ + extFt + tolFt);
        }

        // ------------------------------------------------------------------ span positions
        /// <summary>Chain items + id -> (entry point, exit point) -> segments in span order.</summary>
        public static List<SpanSeg> SpanSegments(IEnumerable<ChainItem> chain, IDictionary<long, KeyValuePair<V3, V3>> points)
        {
            var o = new List<SpanSeg>();
            double s = 0.0;
            foreach (ChainItem it in chain)
            {
                KeyValuePair<V3, V3> pts;
                if (it.Kind == "straight" && points.TryGetValue(it.Id, out pts))
                    o.Add(new SpanSeg { S0 = s, A = pts.Key, B = pts.Value, Id = it.Id });
                s += it.Len;
            }
            return o;
        }

        /// <summary>Station (ft from span start) of a point lying on the span, else null. Only the plan offset
        /// counts against maxOffFt (a hanger or tap sits above or below the centreline); the vertical offset is allowed up to 5 ft.</summary>
        public static double? StationOfPoint(IEnumerable<SpanSeg> segs, V3 p, double maxOffFt)
        {
            double? best = null; double bestDxy = 0;
            foreach (SpanSeg sg in segs)
            {
                double t, d; V3 q;
                ClosestOnSegment(p, sg.A, sg.B, out t, out q, out d);
                double dxy = Math.Sqrt((p.X - q.X) * (p.X - q.X) + (p.Y - q.Y) * (p.Y - q.Y));
                double dz = Math.Abs(p.Z - q.Z);
                if (dxy > maxOffFt || dz > 5.0) continue;
                double segLen = VLen(VSub(sg.B, sg.A));
                if ((t <= 0.0 || t >= 1.0) && VLen(VSub(p, q)) > maxOffFt) continue;
                double st = sg.S0 + t * segLen;
                if (best == null || dxy < bestDxy) { best = st; bestDxy = dxy; }
            }
            return best;
        }

        /// <summary>Station of a hanger that really sits ON this span, else null. Stricter than StationOfPoint: the
        /// point must project inside a segment (endTolFt of slack at the ends, no clamping).</summary>
        public static double? StationOnRun(IEnumerable<SpanSeg> segs, V3 p, double maxOffFt, double endTolFt = 10.0 / MM, double maxDzFt = 5.0)
        {
            double? best = null; double bestDxy = 0;
            foreach (SpanSeg sg in segs)
            {
                V3 ab = VSub(sg.B, sg.A);
                double L = VLen(ab);
                if (L < 1e-9) continue;
                V3 d = VScale(ab, 1.0 / L);
                double along = VDot(VSub(p, sg.A), d);
                if (along < -endTolFt || along > L + endTolFt) continue;
                V3 q = VAdd(sg.A, VScale(d, along));
                double dxy = Math.Sqrt((p.X - q.X) * (p.X - q.X) + (p.Y - q.Y) * (p.Y - q.Y));
                if (dxy > maxOffFt || Math.Abs(p.Z - q.Z) > maxDzFt) continue;
                double st = sg.S0 + Math.Max(0.0, Math.Min(L, along));
                if (best == null || dxy < bestDxy) { best = st; bestDxy = dxy; }
            }
            return best;
        }

        /// <summary>Move stations off takeoffs (taps on the run). A station within clearFt of a block moves to the
        /// nearer side of it, as long as that spot is on the span and clear of every other block; if neither side
        /// is free the station is dropped.</summary>
        public static List<double> AvoidBlocks(IEnumerable<double> stations, IList<double> blocks, double clearFt, double lengthFt, double edgeFt)
        {
            if (blocks == null || blocks.Count == 0) return stations.ToList();
            Func<double, bool> free = s => edgeFt <= s && s <= lengthFt - edgeFt && blocks.All(b => Math.Abs(s - b) >= clearFt - 1e-9);
            var o = new List<double>();
            foreach (double s in stations)
            {
                if (free(s)) { o.Add(s); continue; }
                double near = blocks[0];
                foreach (double b in blocks) if (Math.Abs(s - b) < Math.Abs(s - near)) near = b;   // min() keeps the first of equals
                var options = new List<double> { near - clearFt, near + clearFt };
                if (Math.Abs(options[1] - s) < Math.Abs(options[0] - s)) options.Reverse();
                foreach (double c in options)
                    if (free(c)) { o.Add(c); break; }
            }
            o.Sort();
            return o;
        }

        /// <summary>A restricted range covering the size wins (tightest first); an unrestricted condition is the fallback. Null if none.</summary>
        public static int? PickCondition(IEnumerable<Condition> conditions, double sizeFt)
        {
            var hits = new List<KeyValuePair<double, int>>();
            int? loose = null;
            foreach (Condition c in conditions)
            {
                if (c.Unrestricted)
                {
                    if (loose == null) loose = c.Index;
                    continue;
                }
                double hi = c.Upper;
                if (hi < 0) hi = 1e9;   // open-ended upper bound
                if (c.Lower - 1e-6 <= sizeFt && sizeFt <= hi + 1e-6) hits.Add(new KeyValuePair<double, int>(hi - c.Lower, c.Index));
            }
            if (hits.Count > 0)
            {
                KeyValuePair<double, int> b = hits[0];
                foreach (var h in hits)
                    if (h.Key < b.Key || (h.Key == b.Key && h.Value < b.Value)) b = h;
                return b.Value;
            }
            return loose;
        }

        // ------------------------------------------------------------------ hanger matching
        /// <summary>Lower-case word tokens with every digit removed, so 'Clevis 300' and 'CLEVIS-450' share 'clevis'.</summary>
        public static HashSet<string> NameTokens(params string[] texts)
        {
            var o = new HashSet<string>(StringComparer.Ordinal);
            foreach (string t in texts)
            {
                var word = new StringBuilder();
                foreach (char ch in (t ?? "").ToLowerInvariant() + " ")
                {
                    if (char.IsLetter(ch)) word.Append(ch);
                    else
                    {
                        if (word.Length >= 2) o.Add(word.ToString());
                        word.Clear();
                    }
                }
            }
            return o;
        }

        /// <summary>How alike two hangers are. The item id is the strongest evidence; names are compared as size-free word sets.</summary>
        public static double SignatureScore(HangerSignature old, HangerSignature nw)
        {
            double score = 0.0;
            if (!string.IsNullOrEmpty(old.ItemId) && old.ItemId == nw.ItemId) score += 5.0;
            Func<string, string> norm = x => (x ?? "").Trim().ToLowerInvariant();
            if (norm(old.Product).Length > 0 && norm(old.Product) == norm(nw.Product)) score += 2.0;
            if (norm(old.Code).Length > 0 && norm(old.Code) == norm(nw.Code)) score += 1.5;
            if (norm(old.Alias).Length > 0 && norm(old.Alias) == norm(nw.Alias)) score += 1.0;
            HashSet<string> ta = NameTokens(old.Name, old.Product, old.Alias), tb = NameTokens(nw.Name, nw.Product, nw.Alias);
            if (ta.Count > 0 && tb.Count > 0)
            {
                int inter = ta.Count(x => tb.Contains(x));
                int union = ta.Count + tb.Count - inter;
                score += 3.0 * inter / (double)union;
            }
            return score;
        }
    }
}
