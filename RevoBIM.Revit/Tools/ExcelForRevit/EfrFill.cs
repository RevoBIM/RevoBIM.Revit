using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ExcelForRevit
{
    // Excel for Revit: drag-fill / series rules, column letters, duplicates, LIKE escaping.
    // Port of efr_core.py lines 3236-3361 and 3791-3828. Pure logic, no Revit API, no WPF.
    public static partial class Efr
    {
        // ^(.*?)(\d+)(\D*)$ with ASCII digits only (the pyRevit source runs on non-UNICODE re).
        private static readonly Regex NumRe = new Regex(@"^(.*?)([0-9]+)([^0-9]*)$", RegexOptions.CultureInvariant);

        /// <summary>Python to_text() for the values this file handles.</summary>
        internal static string Tx(object value)
        {
            if (value == null) return "";
            if (value is string s) return s;
            if (value is bool b) return b ? "True" : "False";
            IFormattable f = value as IFormattable;
            if (f != null) return f.ToString(null, CultureInfo.InvariantCulture);
            return value.ToString();
        }

        /// <summary>
        /// (prefix, digits, suffix) around the last run of digits, or null.
        /// A leading minus counts as a sign only at the very start or after a space.
        /// In a tag like AHU-1 or SD-001 the hyphen is a separator, and reading it as
        /// a negative sign is what made a drag fill from AHU-1 produce AHU0.
        /// </summary>
        public static (string Prefix, string Digits, string Suffix)? SplitNumber(string text)
        {
            text = Tx(text);
            Match m = NumRe.Match(text);
            if (!m.Success) return null;
            string prefix = m.Groups[1].Value, digits = m.Groups[2].Value, suffix = m.Groups[3].Value;
            if (prefix.EndsWith("-", StringComparison.Ordinal)
                && (prefix.Length == 1 || char.IsWhiteSpace(prefix[prefix.Length - 2])))
            {
                prefix = prefix.Substring(0, prefix.Length - 1);
                digits = "-" + digits;
            }
            return (prefix, digits, suffix);
        }

        public static bool HasNumber(string text)
        {
            return SplitNumber(text) != null;
        }

        /// <summary>Python int() of a digit string such as "007" or "-12" (callers that did int(parts[1])).</summary>
        public static BigInteger DigitsValue(string digits)
        {
            return BigInteger.Parse(digits, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture);
        }

        /// <summary>
        /// Step implied by a run of seed values, or null if there is not one.
        /// Every value has to carry a number and the gaps have to agree; anything
        /// else is not a series and gets copied instead of guessed at.
        /// </summary>
        public static BigInteger? InferStep(IList<string> values)
        {
            List<BigInteger> nums = new List<BigInteger>();
            foreach (string v in values)
            {
                var parts = SplitNumber(v);
                if (parts == null) return null;
                BigInteger n;
                if (!BigInteger.TryParse(parts.Value.Digits, NumberStyles.AllowLeadingSign,
                        CultureInfo.InvariantCulture, out n))
                    return null;
                nums.Add(n);
            }
            if (nums.Count < 2) return null;
            BigInteger step = nums[1] - nums[0];
            for (int i = 2; i < nums.Count; i++)
            {
                if (nums[i] - nums[i - 1] != step) return null;
            }
            return step;
        }

        /// <summary>
        /// The values a drag fill should write, as a plain list.
        /// seeds: the selected cells' current text, top to bottom; count: how many cells to fill;
        /// downward: true dragging down, false dragging up.
        /// The rule, and it is the whole of the rule:
        ///   no number anywhere in the seed -> copy it
        ///   a number in the seed           -> step it, in the drag direction
        ///   several seeds with an even gap -> keep that gap
        ///   several seeds without one      -> repeat the block
        /// </summary>
        public static List<string> FillPlan(IList<string> seeds, int count, bool downward)
        {
            if (count <= 0) return new List<string>();
            if (seeds == null) return new List<string>();
            List<string> seedList = new List<string>();
            foreach (string s in seeds) seedList.Add(Tx(s));
            if (seedList.Count == 0) return new List<string>();

            BigInteger? stepN = InferStep(seedList);

            if (stepN == null && seedList.Count > 1)
            {
                // a block with no series in it repeats, the way Excel repeats it
                List<string> block = new List<string>();
                for (int i = 0; i < count; i++)
                {
                    string src = downward
                        ? seedList[i % seedList.Count]
                        : seedList[seedList.Count - 1 - (i % seedList.Count)];
                    block.Add(src);
                }
                return block;
            }

            BigInteger step = stepN ?? BigInteger.One;

            string anchor = downward ? seedList[seedList.Count - 1] : seedList[0];
            if (!HasNumber(anchor))
            {
                // plain text: copy, never invent
                List<string> copies = new List<string>();
                for (int i = 0; i < count; i++) copies.Add(anchor);
                return copies;
            }

            int direction = downward ? 1 : -1;
            BigInteger delta;
            if (seedList.Count > 1)
            {
                // an explicit gap keeps its own sign when dragged down, and is
                // mirrored when dragged up
                delta = downward ? step : -step;
            }
            else
            {
                delta = direction * BigInteger.Abs(step);
            }

            List<string> result = new List<string>();
            for (int i = 0; i < count; i++) result.Add(SeriesValueBig(anchor, delta, i + 1));
            return result;
        }

        /// <summary>
        /// seed text advanced by step*n, keeping any zero padding.
        /// Padding is kept only when the seed is actually zero-padded: SD-005 goes to
        /// SD-004, but AHU-10 goes to AHU-9 rather than AHU-09.
        /// </summary>
        public static string SeriesValue(string seed, long step, long n)
        {
            return SeriesValueBig(seed, new BigInteger(step), n);
        }

        internal static string SeriesValueBig(string seed, BigInteger step, long n)
        {
            var parts = SplitNumber(seed);
            if (parts == null) return seed;
            string prefix = parts.Value.Prefix, digits = parts.Value.Digits, suffix = parts.Value.Suffix;
            bool neg = digits.StartsWith("-", StringComparison.Ordinal);
            string body = neg ? digits.Substring(1) : digits;
            bool padded = body.Length > 1 && body.StartsWith("0", StringComparison.Ordinal);
            int width = padded ? body.Length : 0;
            BigInteger val = DigitsValue(digits) + step * n;
            string sign = val.Sign < 0 ? "-" : "";
            string outText = BigInteger.Abs(val).ToString(CultureInfo.InvariantCulture);
            if (outText.Length < width) outText = new string('0', width - outText.Length) + outText;
            return prefix + sign + outText + suffix;
        }

        /// <summary>0 -> A, 25 -> Z, 26 -> AA. The reference used in formulas.</summary>
        public static string ColLetter(int index)
        {
            int n = index;
            string outText = "";
            while (true)
            {
                // Python: n % 26 is always >= 0 and n // 26 floors; indexes here are >= 0
                int rem = ((n % 26) + 26) % 26;
                outText = ((char)('A' + rem)).ToString() + outText;
                n = (int)Math.Floor(n / 26.0) - 1;
                if (n < 0) break;
            }
            return outText;
        }

        // ------------------------------------------------------------ 3D view rank / duplicates / LIKE ==

        /// <summary>
        /// How good a candidate a 3D view is, lowest first.
        /// Revit's own default is called {3D}; a per-user one is {3D - someone}. Both
        /// beat a named working view, and a named view beats nothing at all.
        /// </summary>
        public static int Default3dRank(string name)
        {
            string text = Tx(name).Trim();
            if (text == "{3D}") return 0;
            if (text.StartsWith("{3D", StringComparison.Ordinal)) return 1;
            return 2;
        }

        /// <summary>
        /// Values that appear more than once, blanks excluded, in natural order.
        /// Blanks are left out: an empty cell repeated forty times is not the kind of
        /// duplicate anyone is hunting for, and counting them would drown the real ones.
        /// </summary>
        public static List<string> FindDuplicates(IEnumerable<string> values)
        {
            // dict in first-seen order, then a stable sort by natural key (Python's sorted is stable)
            Dictionary<string, int> counts = new Dictionary<string, int>();
            List<string> order = new List<string>();
            foreach (string raw in values)
            {
                string value = raw ?? "";
                int c;
                if (counts.TryGetValue(value, out c)) counts[value] = c + 1;
                else { counts[value] = 1; order.Add(value); }
            }
            return order
                .OrderBy(v => v, Comparer<string>.Create(NaturalKeyCompare))
                .Where(v => counts[v] > 1 && Tx(v).Trim().Length > 0)
                .ToList();
        }

        private static readonly Regex NatRe = new Regex("([0-9]+)", RegexOptions.CultureInvariant);

        // natural_key(): digit runs as numbers, text case-insensitively; compared as Python compares the lists of tuples
        private static List<(int Kind, BigInteger Num, string Text)> NaturalKeyParts(string text)
        {
            var outList = new List<(int, BigInteger, string)>();
            foreach (string part in NatRe.Split(Tx(text)))
            {
                bool digits = part.Length > 0 && part.All(ch => ch >= '0' && ch <= '9');
                if (digits) outList.Add((1, BigInteger.Parse(part, CultureInfo.InvariantCulture), ""));
                else outList.Add((0, BigInteger.Zero, part.ToLowerInvariant()));
            }
            return outList;
        }

        private static int NaturalKeyCompare(string a, string b)
        {
            var ka = NaturalKeyParts(a);
            var kb = NaturalKeyParts(b);
            int n = Math.Min(ka.Count, kb.Count);
            for (int i = 0; i < n; i++)
            {
                int c = ka[i].Kind.CompareTo(kb[i].Kind);
                if (c != 0) return c;
                c = ka[i].Num.CompareTo(kb[i].Num);
                if (c != 0) return c;
                c = string.CompareOrdinal(ka[i].Text, kb[i].Text);
                if (c != 0) return c;
            }
            return ka.Count.CompareTo(kb.Count);
        }

        /// <summary>Escape a term for a DataView RowFilter LIKE: quotes doubled, [ ] % * wrapped in brackets.</summary>
        public static string SqlLikeEscape(string term)
        {
            StringBuilder sb = new StringBuilder();
            foreach (char ch in Tx(term))
            {
                if (ch == '\'') sb.Append("''");
                else if (ch == '[' || ch == ']' || ch == '%' || ch == '*') sb.Append('[').Append(ch).Append(']');
                else sb.Append(ch);
            }
            return sb.ToString();
        }
    }
}
