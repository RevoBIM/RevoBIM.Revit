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
        /// <summary>'Pipe Types : Copper' + 'SVP' -> 'Pipe Types : Copper (SVP)'.</summary>
        public static string LabelWithAbbreviation(string label, string abbr)
        {
            label = (label ?? "").Trim();
            abbr = (abbr ?? "").Trim();
            if (abbr.Length == 0) return label;
            if (label.Length == 0) return "(" + abbr + ")";
            return label + " (" + abbr + ")";
        }

        /// <summary>The first non-blank value (for an abbreviation read several ways).</summary>
        public static string FirstText(IEnumerable<string> values)
        {
            foreach (string v in values)
            {
                string t = (v ?? "").Trim();
                if (t.Length > 0) return t;
            }
            return "";
        }

        /// <summary>The hanger's Comments from the 'Family : Type (ABBR)' of each service on it: in the order met,
        /// joined with ', ', repeats counted - '2xCable Tray : Ladder (LV), Pipe Types : Copper (SVP)'.</summary>
        public static string ServiceComment(IEnumerable<string> labels)
        {
            var order = new List<string>();
            var count = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (string raw in labels)
            {
                string lb = (raw ?? "").Trim();
                if (lb.Length == 0) continue;
                if (!count.ContainsKey(lb)) { order.Add(lb); count[lb] = 0; }
                count[lb]++;
            }
            return string.Join(", ", order.Select(lb => count[lb] > 1 ? count[lb].ToString(CultureInfo.InvariantCulture) + "x" + lb : lb));
        }

        /// <summary>WCAG contrast ratio of two #RRGGBB colours.</summary>
        public static double Contrast(string fg, string bg)
        {
            Func<string, double> lum = h =>
            {
                double[] c = new double[3];
                for (int i = 0; i < 3; i++)
                {
                    double x = int.Parse(h.Substring(1 + 2 * i, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture) / 255.0;
                    c[i] = x <= 0.03928 ? x / 12.92 : Math.Pow((x + 0.055) / 1.055, 2.4);
                }
                return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
            };
            double a = lum(fg), b = lum(bg);
            double hi = Math.Max(a, b), lo = Math.Min(a, b);
            return (hi + 0.05) / (lo + 0.05);
        }

        // ------------------------------------------------------------------ drawer
        /// <summary>Top of a parked title bar: gap above the bottom of the working area, stacked upward by slot.</summary>
        public static double ShrunkTop(double waTop, double waH, double barH, int slot = 0, double gap = 8.0)
        {
            return Math.Max(waTop, waTop + waH - (slot + 1) * (barH + gap));
        }

        /// <summary>Where a parked window opens to: back where it was if the bar has not been moved; otherwise growing
        /// upward from wherever the bar now sits. Always kept on the screen.</summary>
        public static double ExpandTop(double savedTop, double? landedTop, double hereTop, double barH, double fullH, double waTop, double waH)
        {
            double top;
            if (landedTop != null && Math.Abs(hereTop - landedTop.Value) < 1.0) top = savedTop;
            else top = hereTop + barH - fullH;
            return Math.Min(Math.Max(waTop, top), Math.Max(waTop, waTop + waH - fullH));
        }

        /// <summary>M-A9 before M-A10: numbers compare as numbers.</summary>
        public sealed class NaturalComparer : IComparer<string>
        {
            public static readonly NaturalComparer Instance = new NaturalComparer();

            public int Compare(string a, string b)
            {
                List<string> pa = Parts((a ?? "").ToLowerInvariant()), pb = Parts((b ?? "").ToLowerInvariant());
                int n = Math.Min(pa.Count, pb.Count);
                for (int i = 0; i < n; i++)
                {
                    bool da = IsDigits(pa[i]), db = IsDigits(pb[i]);
                    if (da != db) return da ? -1 : 1;     // numbers sort before text, as the (0, n, "") / (1, 0, text) keys did
                    int c;
                    if (da)
                    {
                        string x = pa[i].TrimStart('0'), y = pb[i].TrimStart('0');
                        c = x.Length != y.Length ? x.Length.CompareTo(y.Length) : string.CompareOrdinal(x, y);
                    }
                    else c = string.CompareOrdinal(pa[i], pb[i]);
                    if (c != 0) return c;
                }
                return pa.Count.CompareTo(pb.Count);
            }

            private static bool IsDigits(string s) { return s.Length > 0 && char.IsDigit(s[0]); }

            private static List<string> Parts(string text)
            {
                var o = new List<string>();
                var sb = new StringBuilder();
                bool digits = false;
                foreach (char ch in text)
                {
                    bool d = ch >= '0' && ch <= '9';
                    if (sb.Length > 0 && d != digits) { o.Add(sb.ToString()); sb.Clear(); }
                    digits = d;
                    sb.Append(ch);
                }
                if (sb.Length > 0) o.Add(sb.ToString());
                return o;
            }
        }

        public static string ViewRowText(ViewRow r)
        {
            string kind;
            if (!ViewKindLabels.TryGetValue(r.Type ?? "", out kind)) kind = r.Type;
            return r.Name + "   |   " + kind + "   |   1:" + r.Scale.ToString(CultureInfo.InvariantCulture);
        }

        public static string SheetRowText(SheetRow r)
        {
            int n = r.Views.Count;
            return r.Number + " - " + r.Name + "   (" + n.ToString(CultureInfo.InvariantCulture) + " plan / section view" + (n == 1 ? "" : "s") + ")";
        }

        public static List<ViewRow> FilterViewRows(IEnumerable<ViewRow> rows, string query, string kind = "all")
        {
            var o = new List<ViewRow>();
            foreach (ViewRow r in rows)
            {
                bool plan = Array.IndexOf(PlanViewTypes, r.Type) >= 0;
                if (kind == "floor" && r.Type != "FloorPlan") continue;
                if (kind == "plan" && !plan) continue;
                if (kind == "section" && plan) continue;
                if (MatchWords(ViewRowText(r), query)) o.Add(r);
            }
            return o;
        }

        public static List<SheetRow> FilterSheetRows(IEnumerable<SheetRow> rows, string query)
        {
            return rows.Where(r => MatchWords(r.Number + " " + r.Name, query)).ToList();
        }

        /// <summary>Every view key to dimension in: the ticked views plus each view on a ticked sheet, each once, in order.</summary>
        public static List<long> ChosenViews(IEnumerable<long> viewKeys, IEnumerable<long> sheetKeys, IEnumerable<SheetRow> sheets)
        {
            var o = new List<long>();
            var seen = new HashSet<long>();
            var bySheet = new Dictionary<long, List<long>>();
            foreach (SheetRow r in sheets) bySheet[r.Key] = r.Views;
            var all = new List<long>(viewKeys);
            foreach (long sk in sheetKeys)
            {
                List<long> v;
                if (bySheet.TryGetValue(sk, out v)) all.AddRange(v);
            }
            foreach (long k in all)
                if (seen.Add(k)) o.Add(k);
            return o;
        }

        // ------------------------------------------------------------------ search
        /// <summary>The house search: every word of the query, in any order, any case.</summary>
        public static bool MatchWords(string text, string query)
        {
            string t = (text ?? "").ToLowerInvariant();
            foreach (string w in (query ?? "").ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries))
                if (t.IndexOf(w, StringComparison.Ordinal) < 0) return false;
            return true;
        }

        public static string NextMode(string mode)
        {
            int i = Array.IndexOf(ThemeModes, mode);
            return i < 0 ? "auto" : ThemeModes[(i + 1) % ThemeModes.Length];
        }

        /// <summary>auto follows Revit's canvas; an unreadable canvas falls back to dark.</summary>
        public static string ResolveTheme(string mode, bool? canvasIsDark)
        {
            if (mode == "dark" || mode == "light") return mode;
            if (canvasIsDark == null) return "dark";
            return canvasIsDark.Value ? "dark" : "light";
        }

        // ------------------------------------------------------------------ window size
        /// <summary>(height, top) that shows the whole tab: grow or shrink the window by the difference between the
        /// tab's content and the space it has now, never taller than the working area or shorter than the minimum,
        /// and moved up if it would run off the bottom of the screen.</summary>
        public static void FitHeight(double winH, double viewportH, double contentH, double minH, double top, double waTop, double waH, out double height, out double newTop)
        {
            double h = winH + (contentH - viewportH);
            h = Math.Max(minH, Math.Min(h, waH));
            if (top + h > waTop + waH) top = Math.Max(waTop, waTop + waH - h);
            if (top < waTop) top = waTop;
            height = h; newTop = top;
        }
    }
}
