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
        // ------------------------------------------------------------------ vectors
        public static V3 VSub(V3 a, V3 b) { return new V3(a.X - b.X, a.Y - b.Y, a.Z - b.Z); }
        public static V3 VAdd(V3 a, V3 b) { return new V3(a.X + b.X, a.Y + b.Y, a.Z + b.Z); }
        public static V3 VScale(V3 a, double s) { return new V3(a.X * s, a.Y * s, a.Z * s); }
        public static double VDot(V3 a, V3 b) { return a.X * b.X + a.Y * b.Y + a.Z * b.Z; }
        public static double VLen(V3 a) { return Math.Sqrt(VDot(a, a)); }

        public static V3 VNorm(V3 a)
        {
            double n = VLen(a);
            if (n < 1e-12) return new V3(0, 0, 0);
            return new V3(a.X / n, a.Y / n, a.Z / n);
        }

        /// <summary>t (clamped to 0..1), the point and the distance of p on segment a-b.</summary>
        public static void ClosestOnSegment(V3 p, V3 a, V3 b, out double t, out V3 q, out double dist)
        {
            V3 ab = VSub(b, a);
            double den = VDot(ab, ab);
            if (den < 1e-12)
            {
                t = 0.0; q = a; dist = VLen(VSub(p, a));
                return;
            }
            t = VDot(VSub(p, a), ab) / den;
            t = Math.Max(0.0, Math.Min(1.0, t));
            q = VAdd(a, VScale(ab, t));
            dist = VLen(VSub(p, q));
        }

        // ------------------------------------------------------------------ rehosting
        /// <summary>Nearest horizontal straight to point p. Dist is the distance from connector 0, clamped so the
        /// hanger is never asked to sit on the very end of the straight. Null if none within maxDistFt.</summary>
        public static NearestHostResult NearestHost(V3 p, IEnumerable<HostSeg> hosts, double maxDistFt, double marginFt)
        {
            HostSeg bestHost = null;
            double bestD = 0, bestT = 0;
            foreach (HostSeg h in hosts)
            {
                if (!h.Horizontal) continue;
                double t, d; V3 q;
                ClosestOnSegment(p, h.A, h.B, out t, out q, out d);
                if (d > maxDistFt) continue;
                if (bestHost == null)
                {
                    bestHost = h; bestD = d; bestT = t;
                    continue;
                }
                double r1 = Math.Round(d, 6, MidpointRounding.AwayFromZero), r0 = Math.Round(bestD, 6, MidpointRounding.AwayFromZero);
                if (r1 < r0 || (r1 == r0 && h.Id < bestHost.Id)) { bestHost = h; bestD = d; bestT = t; }
            }
            if (bestHost == null) return null;
            double length = VLen(VSub(bestHost.B, bestHost.A));
            double dist;
            if (length > 2.0 * marginFt) dist = Math.Max(marginFt, Math.Min(length - marginFt, bestT * length));
            else dist = length / 2.0;
            return new NearestHostResult { Host = bestHost, Dist = dist, D = bestD, T = bestT };
        }

        private static bool IsTakeoff(string t) { return t == "tap" || t == "tee_branch"; }

        private static SpanEnd End(string type, long? id) { return new SpanEnd { Type = type, Id = id }; }

        /// <summary>Walk away from part pid through connector exitIdx. Straights and in-line parts are walked
        /// through; anything else ends the span and says what kind of end it is.</summary>
        private static SpanEnd WalkDir(Dictionary<long, PartRec> parts, long pid, int? exitIdx, HashSet<long> visited, List<ChainItem> items)
        {
            long cur = pid;
            int? ex = exitIdx;
            while (true)
            {
                List<ConnRec> conns = parts[cur].Conns;
                if (ex == null || ex.Value >= conns.Count) return End("open", null);
                ConnRec c = conns[ex.Value];
                long? nid = c.To;
                if (nid == null || !parts.ContainsKey(nid.Value)) return End("open", null);
                PartRec n = parts[nid.Value];
                int? nin = c.ToConn;
                string kind = n.Kind;
                if (kind == "straight" || kind == "inline")
                {
                    if (kind == "straight" && !n.Horizontal) return End("vertical", nid);
                    if (visited.Contains(nid.Value) || nin == null || n.Conns.Count != 2)
                        return End(visited.Contains(nid.Value) ? "loop" : "other", nid);
                    int nxt = 1 - nin.Value;
                    items.Add(new ChainItem { Id = nid.Value, Kind = kind, Len = n.Len, Entry = nin.Value, Exit = nxt });
                    visited.Add(nid.Value);
                    cur = nid.Value;
                    ex = nxt;
                    continue;
                }
                if (kind == "bend") return End("bend", nid);
                if (kind == "accessory") return End("accessory", nid);
                if (kind == "tee")
                {
                    string role = null;
                    if (nin != null && nin.Value < n.Conns.Count) role = n.Conns[nin.Value].Role;
                    return End(role == "branch" ? "tee_branch" : "tee_main", nid);
                }
                if (kind == "tap") return End("tap", nid);
                return End("other", nid);
            }
        }

        private static Span ReverseSpan(Span span)
        {
            var r = new Span { StartEnd = span.EndEnd, EndEnd = span.StartEnd };
            for (int i = span.Chain.Count - 1; i >= 0; i--)
            {
                ChainItem it = span.Chain[i];
                r.Chain.Add(new ChainItem { Id = it.Id, Kind = it.Kind, Len = it.Len, Entry = it.Exit, Exit = it.Entry });
            }
            return r;
        }

        private static int PriorityOf(string type)
        {
            int p;
            return Priority.TryGetValue(type ?? "", out p) ? p : 3;
        }

        /// <summary>Start the span at the end a run 'begins' from: after a bend first.</summary>
        public static Span OrientSpan(Span span)
        {
            int ps = PriorityOf(span.StartEnd.Type), pe = PriorityOf(span.EndEnd.Type);
            if (pe < ps) return ReverseSpan(span);
            if (pe == ps && span.Chain[0].Id > span.Chain[span.Chain.Count - 1].Id) return ReverseSpan(span);
            return span;
        }

        public static double SpanLength(Span span)
        {
            double s = 0;
            foreach (ChainItem it in span.Chain) s += it.Len;
            return s;
        }

        /// <summary>Group horizontal straights into spans. A span is a maximal chain of straights joined directly
        /// or through in-line parts; bends, tees, taps, vertical drops and open ends finish it.</summary>
        public static List<Span> BuildSpans(Dictionary<long, PartRec> parts)
        {
            var visited = new HashSet<long>();
            var spans = new List<Span>();
            var ids = parts.Keys.ToList();
            ids.Sort();
            foreach (long pid in ids)
            {
                PartRec p = parts[pid];
                if (p.Kind != "straight" || !p.Horizontal) continue;
                if (visited.Contains(pid) || p.Conns.Count != 2) continue;
                visited.Add(pid);
                var fwd = new List<ChainItem>();
                SpanEnd fend = WalkDir(parts, pid, 1, visited, fwd);
                var bwd = new List<ChainItem>();
                SpanEnd bend = WalkDir(parts, pid, 0, visited, bwd);
                var span = new Span { StartEnd = bend, EndEnd = fend };
                for (int i = bwd.Count - 1; i >= 0; i--)
                {
                    ChainItem it = bwd[i];
                    span.Chain.Add(new ChainItem { Id = it.Id, Kind = it.Kind, Len = it.Len, Entry = it.Exit, Exit = it.Entry });
                }
                span.Chain.Add(new ChainItem { Id = pid, Kind = "straight", Len = p.Len, Entry = 0, Exit = 1 });
                span.Chain.AddRange(fwd);
                spans.Add(OrientSpan(span));
            }
            return spans;
        }

        // ------------------------------------------------------------------ stations
        /// <summary>Hanger stations (feet from the span start) for one span.
        /// The first hanger sits StartOff from the start (TakeoffClear at a takeoff), then one every Spacing; a span
        /// finishing at a bend or set down gets a hanger EndOff before it, spacing allowed to shrink to fit it in;
        /// a short span that starts or ends at a takeoff is a takeoff stub: no hangers.</summary>
        public static List<double> PlanStations(double lengthFt, string startType, string endType, PlanConfig cfg)
        {
            double L = lengthFt * MM;
            double S = cfg.Spacing, a = cfg.StartOff, b = cfg.EndOff, tk = cfg.TakeoffClear, mg = cfg.MinGap, edge = cfg.Edge;
            var none = new List<double>();
            if (L < 2.0 * edge) return none;
            bool hasTakeoff = IsTakeoff(startType) || IsTakeoff(endType);
            if (hasTakeoff && L <= cfg.TakeoffMax) return none;
            double first = IsTakeoff(startType) ? tk : a;
            bool endRequired = endType == "bend" || endType == "vertical" || endType == "accessory";
            double last;
            if (endRequired) last = L - b;
            else if (IsTakeoff(endType)) last = L - tk;
            else if (endType == "tee_main") last = L - a;
            else last = L - edge;
            if (first > last) return new List<double> { L / 2.0 / MM };
            if (last - first < mg)
                return endRequired ? new List<double> { ((first + last) / 2.0) / MM } : new List<double> { first / MM };
            var stations = new List<double> { first };
            double p = first;
            if (endRequired)
            {
                while (p + S < last - mg)
                {
                    p += S;
                    stations.Add(p);
                }
                double gap = last - p;
                if (gap > S + 1e-6)
                {
                    int n = (int)Math.Ceiling(gap / S - 1e-9);
                    double step = gap / n;
                    for (int i = 1; i < n; i++) stations.Add(p + step * i);
                }
                stations.Add(last);
            }
            else
            {
                while (p + S <= last + 1e-6)
                {
                    p += S;
                    stations.Add(p);
                }
            }
            return stations.Select(s => s / MM).ToList();
        }

        /// <summary>Station along a span -> (straight id, entry connector, distance, station). A station that falls
        /// inside an in-line part (reducer, damper) or too close to a joint is moved to the nearest spot a hanger can sit.</summary>
        public static Located Locate(List<ChainItem> chain, double stationFt, double marginFt)
        {
            double pos = 0.0;
            Located best = null;
            double bestD = 0, bestStart = 0;
            foreach (ChainItem it in chain)
            {
                if (it.Kind == "straight" && it.Len > 2.0 * marginFt)
                {
                    double lo = pos + marginFt, hi = pos + it.Len - marginFt;
                    double d, s;
                    if (stationFt < lo) { d = lo - stationFt; s = lo; }
                    else if (stationFt > hi) { d = stationFt - hi; s = hi; }
                    else { d = 0.0; s = stationFt; }
                    double rd = Math.Round(d, 9, MidpointRounding.AwayFromZero);
                    if (best == null || rd < bestD || (rd == bestD && pos < bestStart))
                    {
                        best = new Located { Id = it.Id, Entry = it.Entry, Dist = s - pos, Station = s };
                        bestD = rd; bestStart = pos;
                    }
                }
                pos += it.Len;
            }
            return best;
        }

        public static List<double> Dedupe(IEnumerable<double> stations, double minSepFt)
        {
            var o = new List<double>();
            var sorted = stations.ToList();
            sorted.Sort();
            foreach (double s in sorted)
                if (o.Count == 0 || s - o[o.Count - 1] >= minSepFt) o.Add(s);
            return o;
        }

        /// <summary>Remove stations within clearFt of a hanger that is already there.</summary>
        public static List<double> DropNear(IEnumerable<double> stations, IEnumerable<double> existing, double clearFt)
        {
            var ex = existing.ToList();
            return stations.Where(s => ex.All(e => Math.Abs(s - e) > clearFt)).ToList();
        }
    }
}
