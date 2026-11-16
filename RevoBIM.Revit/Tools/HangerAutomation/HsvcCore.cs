using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

namespace RevoBIM.Tools.HangerAutomation
{
    // =====================================================================================================
    // Hanger Automation - Hanger Service Type Assigner: the pure rules (no Revit, no WPF).
    // Port of hsvc_core.py.
    //
    // The tab lists every hanger placed in the project (FAB hangers and MEP Ancillary Framing families)
    // grouped by family, type, level and comments; the list filters, sorts (multi-level) and regroups;
    // selected groups can be shown in the default 3D view; and each hanger's Comments can be rewritten from
    // the services it actually carries ('Pipe Types : Copper (SVP)').
    // =====================================================================================================

    /// <summary>One hanger in the list (hsvc_revit.record_of's dict: id, family, type, level, comments, cat = "fab" / "framing").</summary>
    public class HangerRecord
    {
        public long Id;
        public string Family = "", Type = "", Level = "", Comments = "", Cat = "";

        /// <summary>rec.get(field, ''): family / type / level / comments / cat by name, "" for anything else.</summary>
        public string this[string field]
        {
            get
            {
                switch (field)
                {
                    case "family": return Family ?? "";
                    case "type": return Type ?? "";
                    case "level": return Level ?? "";
                    case "comments": return Comments ?? "";
                    case "cat": return Cat ?? "";
                }
                return "";
            }
        }
    }

    /// <summary>The identity of a group: the values of the grouped-on fields (the Python tuple of strings), usable as a dictionary / set key.</summary>
    public sealed class GroupKey : IEquatable<GroupKey>
    {
        public readonly string[] Parts;
        public GroupKey(string[] parts) { Parts = parts ?? new string[0]; }

        public bool Equals(GroupKey other)
        {
            if (ReferenceEquals(other, null) || other.Parts.Length != Parts.Length) return false;
            for (int i = 0; i < Parts.Length; i++)
                if (!string.Equals(Parts[i], other.Parts[i], StringComparison.Ordinal)) return false;
            return true;
        }

        public override bool Equals(object obj) { return Equals(obj as GroupKey); }

        public override int GetHashCode()
        {
            int h = 17;
            foreach (string s in Parts) h = h * 31 + StringComparer.Ordinal.GetHashCode(s ?? "");
            return h;
        }

        public override string ToString() { return "(" + string.Join(", ", Parts) + ")"; }
    }

    /// <summary>One row of the list (group_records' dicts: family / type / level / comments, count, ids, key).</summary>
    public class HangerGroup
    {
        public GroupKey Key;
        public List<long> Ids = new List<long>();
        public int Count;
        public string Family = "", Type = "", Level = "", Comments = "";

        /// <summary>g[field]: family / type / level / comments by name, "" for anything else (g.get(f, '') in the sort).</summary>
        public string this[string field]
        {
            get
            {
                switch (field)
                {
                    case "family": return Family;
                    case "type": return Type;
                    case "level": return Level;
                    case "comments": return Comments;
                }
                return "";
            }
            set
            {
                switch (field)
                {
                    case "family": Family = value; break;
                    case "type": Type = value; break;
                    case "level": Level = value; break;
                    case "comments": Comments = value; break;
                }
            }
        }
    }

    /// <summary>One level of the sort: the field (family / type / level / comments / count) and whether it is descending.</summary>
    public class SortLevel
    {
        public string Field;
        public bool Desc;
        public SortLevel() { }
        public SortLevel(string field, bool desc) { Field = field; Desc = desc; }
    }

    /// <summary>An axis-aligned box (the Python (lo, hi) pair of 3-tuples).</summary>
    public class Box
    {
        public V3 Lo, Hi;
        public Box() { }
        public Box(V3 lo, V3 hi) { Lo = lo; Hi = hi; }
    }

    /// <summary>A straight a hanger can carry (the dicts hsvc_revit.Services builds: el, a, b, width, depth, ins).</summary>
    public class ServiceRec
    {
        public Autodesk.Revit.DB.Element El;
        public V3 A, B;
        public double Width, Depth, Ins;
    }

    /// <summary>A family hanger for Carried: p = its location, lo / hi = its box.</summary>
    public class HangerBox
    {
        public V3 P, Lo, Hi;
        public HangerBox() { }
        public HangerBox(V3 p, V3 lo, V3 hi) { P = p; Lo = lo; Hi = hi; }
    }

    /// <summary>What a hanger carries: ('bar', rest_z) - services resting on a bar at rest_z; ('ring', ring_z, radius) - services
    /// running through a ring. Kind is "bar" or "ring", Z the rest_z / ring_z, Radius the ring's radius (0 / null = use half the
    /// service's width).</summary>
    public class CarryRule
    {
        public string Kind;
        public double Z;
        public double? Radius;
        public static CarryRule Bar(double restZ) { return new CarryRule { Kind = "bar", Z = restZ }; }
        public static CarryRule Ring(double ringZ, double radius) { return new CarryRule { Kind = "ring", Z = ringZ, Radius = radius }; }
    }

    /// <summary>Services bucketed by plan cells, so finding what passes a hanger looks at a handful of services, not every one in the model.</summary>
    public class PlanIndex<T>
    {
        public double Cell;
        public readonly Dictionary<long, List<int>> Buckets = new Dictionary<long, List<int>>();
        public readonly List<int> Wide = new List<int>();
        public readonly List<T> Items = new List<T>();

        public PlanIndex(double cellFt = 10.0) { Cell = cellFt; }

        private static long CellKey(int i, int j) { return ((long)i << 32) | (uint)j; }

        private IEnumerable<long> Cells(V3 lo, V3 hi)
        {
            double c = Cell;
            int x0 = (int)Math.Floor(lo.X / c), x1 = (int)Math.Floor(hi.X / c);
            int y0 = (int)Math.Floor(lo.Y / c), y1 = (int)Math.Floor(hi.Y / c);
            for (int i = x0; i <= x1; i++)
                for (int j = y0; j <= y1; j++)
                    yield return CellKey(i, j);
        }

        public void Add(T item, V3 lo, V3 hi)
        {
            int n = Items.Count;
            Items.Add(item);
            var cells = Cells(lo, hi).ToList();
            if (cells.Count > 4000)            // absurdly long: keep it out of the grid, always checked
            {
                Wide.Add(n);
                return;
            }
            foreach (long k in cells)
            {
                List<int> b;
                if (!Buckets.TryGetValue(k, out b)) { b = new List<int>(); Buckets[k] = b; }
                b.Add(n);
            }
        }

        public List<T> Near(V3 lo, V3 hi)
        {
            var seen = new HashSet<int>();
            var o = new List<T>();
            foreach (long k in Cells(lo, hi))
            {
                List<int> b;
                if (Buckets.TryGetValue(k, out b))
                    foreach (int n in b)
                        if (seen.Add(n)) o.Add(Items[n]);
            }
            foreach (int n in Wide)
                if (seen.Add(n)) o.Add(Items[n]);
            return o;
        }
    }

    public static class HsvcCore
    {
        // the fields a hanger is listed by, in column order
        public static readonly string[] Fields = { "family", "type", "level", "comments" };
        public static readonly Dictionary<string, string> Labels = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            {"family", "Family"}, {"type", "Type"}, {"level", "Level"}, {"comments", "Comments"}, {"count", "Count"},
        };
        public static readonly string[] Sortable = { "family", "type", "level", "comments", "count" };
        public const string Mixed = "(various)";
        public static readonly List<KeyValuePair<string, string>> Categories = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("all", "All hangers"),
            new KeyValuePair<string, string>("fab", "FAB Hangers"),
            new KeyValuePair<string, string>("framing", "MEP Ancillary Framing"),
        };
        public static readonly List<KeyValuePair<string, string>> Scopes = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("selected", "Selected rows"),
            new KeyValuePair<string, string>("all", "Every row in the list"),
        };
        public const int MaxSort = 4;
        public const double RestTolMm = 150.0;       // a service rests on a hanger's bar when its underside is within this of it

        // temporary colours in the 3D check, one per category, in the order met
        public static readonly int[][] CatColours =
        {
            new[] { 0, 114, 230 }, new[] { 0, 170, 90 }, new[] { 230, 140, 0 }, new[] { 200, 40, 160 }, new[] { 0, 180, 200 },
            new[] { 220, 50, 50 }, new[] { 150, 100, 230 }, new[] { 120, 160, 0 }, new[] { 240, 200, 0 }, new[] { 100, 100, 100 },
        };

        public static string LabelWithAbbreviation(string label, string abbr) { return FhaCore.LabelWithAbbreviation(label, abbr); }
        public static string FirstText(IEnumerable<string> values) { return FhaCore.FirstText(values); }

        // ------------------------------------------------------------ the list
        /// <summary>A hanger passes the category and the house search (every word, any field).</summary>
        public static bool RecordMatches(HangerRecord rec, string query, string category)
        {
            if ((category == "fab" || category == "framing") && rec.Cat != category) return false;
            string text = string.Join(" ", Fields.Select(f => rec[f]));
            return FhaCore.MatchWords(text, query);
        }

        /// <summary>Groups of hangers: one per distinct value of the `by` fields. A field not grouped on shows its value
        /// when the group agrees, else Mixed. Returns the groups in the order first met.</summary>
        public static List<HangerGroup> GroupRecords(IEnumerable<HangerRecord> records, IEnumerable<string> by)
        {
            var byList = by == null ? new List<string>() : by.ToList();
            var useFields = Fields.Where(f => byList.Contains(f)).ToList();
            var groups = new Dictionary<GroupKey, HangerGroup>();
            var order = new List<GroupKey>();
            foreach (HangerRecord r in records)
            {
                var key = new GroupKey(useFields.Select(f => r[f]).ToArray());
                HangerGroup g;
                if (!groups.TryGetValue(key, out g))
                {
                    g = new HangerGroup { Key = key };
                    foreach (string f in Fields) g[f] = r[f];
                    groups[key] = g;
                    order.Add(key);
                }
                else
                {
                    foreach (string f in Fields)
                        if (!useFields.Contains(f) && g[f] != r[f]) g[f] = Mixed;
                }
                g.Ids.Add(r.Id);
                g.Count += 1;
            }
            return order.Select(k => groups[k]).ToList();
        }

        /// <summary>Sort by the grouped fields, in column order, ascending.</summary>
        public static List<SortLevel> DefaultStack(IEnumerable<string> by)
        {
            var byList = by == null ? new List<string>() : by.ToList();
            var o = Fields.Where(f => byList.Contains(f)).Select(f => new SortLevel(f, false)).ToList();
            if (o.Count == 0) o.Add(new SortLevel("family", false));
            return o;
        }

        /// <summary>A heading clicked: on its own it starts the sort again on that field (flipping it if it already led
        /// alone); with Shift it adds a level, or flips that level's direction if it is already in the sort.</summary>
        public static List<SortLevel> ClickSort(IEnumerable<SortLevel> stack, string field, bool add)
        {
            var st = stack == null ? new List<SortLevel>() : stack.Select(s => new SortLevel(s.Field, s.Desc)).ToList();
            for (int i = 0; i < st.Count; i++)
            {
                if (st[i].Field == field)
                {
                    if (add || st.Count == 1)
                    {
                        st[i] = new SortLevel(st[i].Field, !st[i].Desc);
                        return st;
                    }
                    return new List<SortLevel> { new SortLevel(field, false) };
                }
            }
            if (add && st.Count < MaxSort)
            {
                st.Add(new SortLevel(field, false));
                return st;
            }
            return new List<SortLevel> { new SortLevel(field, false) };
        }

        /// <summary>M-A9 before M-A10 (fha_core.natural_key): the lower-cased text split round its digit runs; a number part
        /// sorts before a text part, numbers by value.</summary>
        private static int NaturalCompare(string a, string b)
        {
            List<string> pa = NaturalParts((a ?? "").ToLowerInvariant()), pb = NaturalParts((b ?? "").ToLowerInvariant());
            int n = Math.Min(pa.Count, pb.Count);
            for (int i = 0; i < n; i++)
            {
                // parts alternate text, number, text ... starting with a (possibly empty) text part, as re.split(r'(\d+)')
                // gives, so at the same index both lists hold the same kind of part
                bool isNumber = i % 2 == 1;
                int c;
                if (isNumber)
                {
                    string x = pa[i].TrimStart('0'), y = pb[i].TrimStart('0');
                    c = x.Length != y.Length ? x.Length.CompareTo(y.Length) : string.CompareOrdinal(x, y);
                }
                else c = string.CompareOrdinal(pa[i], pb[i]);
                if (c != 0) return c < 0 ? -1 : 1;
            }
            return pa.Count.CompareTo(pb.Count);
        }

        // re.split(r'(\d+)', text): text, digits, text, digits ... text (always an odd count, the text parts may be empty)
        private static List<string> NaturalParts(string text)
        {
            var o = new List<string>();
            var sb = new StringBuilder();
            bool digits = false;
            foreach (char ch in text)
            {
                bool d = ch >= '0' && ch <= '9';
                if (d != digits)
                {
                    o.Add(sb.ToString());
                    sb.Clear();
                    digits = d;
                }
                sb.Append(ch);
            }
            o.Add(sb.ToString());
            if (digits) o.Add("");   // the text after a trailing number
            return o;
        }

        private sealed class NaturalStringComparer : IComparer<string>
        {
            public int Compare(string a, string b) { return NaturalCompare(a, b); }
        }

        /// <summary>Multi-level, natural order, each level its own direction (stable sorts, least significant first).</summary>
        public static List<HangerGroup> SortGroups(IEnumerable<HangerGroup> groups, IEnumerable<SortLevel> stack)
        {
            var o = groups.ToList();
            var levels = stack == null ? new List<SortLevel>() : stack.ToList();
            levels.Reverse();
            foreach (SortLevel lv in levels)
            {
                string field = lv.Field;
                if (field == "count")
                    o = (lv.Desc ? o.OrderByDescending(g => g.Count) : o.OrderBy(g => g.Count)).ToList();
                else
                    o = (lv.Desc ? o.OrderByDescending(g => g[field], new NaturalStringComparer())
                                 : o.OrderBy(g => g[field], new NaturalStringComparer())).ToList();
            }
            return o;
        }

        /// <summary>'Family 1(up arrow)' - the place and direction in the sort, when it is in it.</summary>
        public static string HeadingText(string field, IList<SortLevel> stack)
        {
            if (stack != null)
            {
                for (int i = 0; i < stack.Count; i++)
                {
                    if (stack[i].Field == field)
                    {
                        string arrow = stack[i].Desc ? "\u25BC" : "\u25B2";
                        return stack.Count > 1
                            ? Labels[field] + "  " + (i + 1).ToString(CultureInfo.InvariantCulture) + arrow
                            : Labels[field] + "  " + arrow;
                    }
                }
            }
            return Labels[field];
        }

        /// <summary>Every hanger id in the picked groups (indices into groups), once each.</summary>
        public static List<long> IdsOf(IList<HangerGroup> groups, IEnumerable<int> picked)
        {
            var seen = new HashSet<long>();
            var o = new List<long>();
            foreach (int i in picked)
            {
                if (0 <= i && i < groups.Count)
                    foreach (long h in groups[i].Ids)
                        if (seen.Add(h)) o.Add(h);
            }
            return o;
        }

        public static string Summary(IList<HangerRecord> records, IList<HangerGroup> groups, int nSelected)
        {
            int listed = 0;
            foreach (HangerGroup g in groups) listed += g.Count;
            return records.Count.ToString(CultureInfo.InvariantCulture) + " hangers in the project | "
                + listed.ToString(CultureInfo.InvariantCulture) + " listed in "
                + groups.Count.ToString(CultureInfo.InvariantCulture) + " rows | "
                + nSelected.ToString(CultureInfo.InvariantCulture) + " selected";
        }

        // ------------------------------------------------- which services a hanger carries
        /// <summary>A service rests on a bar at restZ: its underside within tol of it (a little below allowed - the bar's top
        /// vs the service's insulation).</summary>
        public static bool RestsOn(double svcBottom, double restZ, double tol)
        {
            return restZ - tol <= svcBottom && svcBottom <= restZ + tol;
        }

        /// <summary>A service runs through a ring centred at ringZ.</summary>
        public static bool ThroughRing(double svcZ, double ringZ, double radius, double tol)
        {
            return Math.Abs(svcZ - ringZ) <= radius + tol;
        }

        /// <summary>The (r, g, b) for the index-th category met (wraps round).</summary>
        public static int[] ColourFor(int index)
        {
            return CatColours[index % CatColours.Length];
        }

        /// <summary>list(CAT_COLOURS).index(rgb): the position of a colour in CatColours, -1 when it is not one of them.</summary>
        public static int ColourIndex(int[] rgb)
        {
            for (int i = 0; i < CatColours.Length; i++)
                if (rgb != null && rgb.Length == 3 && CatColours[i][0] == rgb[0] && CatColours[i][1] == rgb[1] && CatColours[i][2] == rgb[2]) return i;
            return -1;
        }

        public static Box PadBox(V3 lo, V3 hi, double pad)
        {
            return new Box(new V3(lo.X - pad, lo.Y - pad, lo.Z - pad), new V3(hi.X + pad, hi.Y + pad, hi.Z + pad));
        }

        /// <summary>The box round all the boxes, or null when there are none.</summary>
        public static Box UnionBox(IEnumerable<Box> boxes)
        {
            bool any = false;
            double lx = 0, ly = 0, lz = 0, hx = 0, hy = 0, hz = 0;
            foreach (Box b in boxes)
            {
                if (!any)
                {
                    lx = b.Lo.X; ly = b.Lo.Y; lz = b.Lo.Z;
                    hx = b.Hi.X; hy = b.Hi.Y; hz = b.Hi.Z;
                    any = true;
                }
                else
                {
                    lx = Math.Min(lx, b.Lo.X); ly = Math.Min(ly, b.Lo.Y); lz = Math.Min(lz, b.Lo.Z);
                    hx = Math.Max(hx, b.Hi.X); hy = Math.Max(hy, b.Hi.Y); hz = Math.Max(hz, b.Hi.Z);
                }
            }
            return any ? new Box(new V3(lx, ly, lz), new V3(hx, hy, hz)) : null;
        }

        /// <summary>Plan box round a centreline a-b, reach to each side.</summary>
        public static Box SegmentBox(V3 a, V3 b, double reach)
        {
            V3 lo = new V3(Math.Min(a.X, b.X) - reach, Math.Min(a.Y, b.Y) - reach, Math.Min(a.Z, b.Z) - reach);
            V3 hi = new V3(Math.Max(a.X, b.X) + reach, Math.Max(a.Y, b.Y) + reach, Math.Max(a.Z, b.Z) + reach);
            return new Box(lo, hi);
        }

        /// <summary>(t, length): how far along a-b the point square across from p is, in feet.</summary>
        public static void Station(V3 a, V3 b, V3 p, out double t, out double length)
        {
            V3 d = FhaCore.VSub(b, a);
            double len = FhaCore.VLen(d);
            if (len < 1e-9)
            {
                t = 0.0; length = 0.0;
                return;
            }
            t = FhaCore.VDot(FhaCore.VSub(p, a), d) / len;
            length = len;
        }

        public static bool InPlanBox(V3 q, V3 lo, V3 hi, double slack)
        {
            return lo.X - slack <= q.X && q.X <= hi.X + slack && lo.Y - slack <= q.Y && q.Y <= hi.Y + slack;
        }

        /// <summary>Which services a (family) hanger carries.
        /// hanger: its location and box. rule: Bar(restZ) - services resting on a bar at restZ (their underside, bare or
        /// insulated, within tol); Ring(ringZ, radius) - services running through a ring. A service counts only where its
        /// centreline passes the hanger inside the hanger's plan box and inside the service's own length.
        /// Returns the services, ordered across the hanger.</summary>
        public static List<ServiceRec> Carried(HangerBox hanger, IEnumerable<ServiceRec> services, CarryRule rule, double tol, double endSlack)
        {
            V3 p = hanger.P;
            var found = new List<KeyValuePair<V3, ServiceRec>>();
            foreach (ServiceRec s in services)
            {
                double t, len;
                Station(s.A, s.B, p, out t, out len);
                if (t < -endSlack || t > len + endSlack) continue;
                V3 d = FhaCore.VNorm(FhaCore.VSub(s.B, s.A));
                V3 q = FhaCore.VAdd(s.A, FhaCore.VScale(d, t));
                if (!InPlanBox(q, hanger.Lo, hanger.Hi, endSlack)) continue;
                bool ok;
                if (rule.Kind == "ring")
                {
                    double radius = (rule.Radius != null && rule.Radius.Value != 0.0) ? rule.Radius.Value : s.Width / 2.0;
                    ok = ThroughRing(q.Z, rule.Z, radius, tol);
                }
                else
                {
                    double half = s.Depth / 2.0;
                    ok = RestsOn(q.Z - half, rule.Z, tol) || RestsOn(q.Z - half - s.Ins, rule.Z, tol);
                }
                if (ok) found.Add(new KeyValuePair<V3, ServiceRec>(q, s));
            }
            if (found.Count > 1)   // left to right across the first service's run
            {
                V3 d = FhaCore.VNorm(FhaCore.VSub(found[0].Value.B, found[0].Value.A));
                V3 across = new V3(-d.Y, d.X, 0.0);
                found = found.Select((kv, i) => new { kv, i }).OrderBy(z => FhaCore.VDot(z.kv.Key, across)).ThenBy(z => z.i).Select(z => z.kv).ToList();
            }
            return found.Select(kv => kv.Value).ToList();
        }
    }
}
