using System;
using System.Collections.Generic;
using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ExcelForRevit
{
    // Excel for Revit: the formula engine. Port of efr_core.py lines 3363-3790.
    //
    // A small expression parser, deliberately not eval().  It knows column letters,
    // text and numbers, & + - * / and comparisons, and the function set below.
    // Everything is evaluated against one row at a time and written back as static
    // text: the model never stores a formula.
    //
    // Values flowing through the evaluator are `object`: double (Python float), string or bool.

    /// <summary>A formula the user got wrong. Its Message is shown to the user as is.</summary>
    public class FormulaError : Exception
    {
        public FormulaError(string message) : base(message) { }
    }

    /// <summary>
    /// What a formula can see for one target cell (Python's ctx dict, built by the window's formula_context).
    /// A null member behaves like a key missing from the Python dict.
    /// </summary>
    public interface IFormulaContext
    {
        /// <summary>Column letter (upper case, as FieldInfo.Letter) -> current text of that column in this row.</summary>
        IDictionary<string, string> Cells { get; }
        /// <summary>1-based row number of the row being evaluated (row.ridx + 1).</summary>
        int? Row { get; }
        /// <summary>1-based row number of the first formula cell (the row A5-style references are relative to).</summary>
        int? Anchor { get; }
        /// <summary>1-based position of this cell among the cells being written (the Python's n).</summary>
        int? N { get; }
        /// <summary>The element id of the row as text.</summary>
        string Id { get; }
        /// <summary>The current text of the cell being written.</summary>
        string This { get; }
        /// <summary>(column letter, 1-based row number) -> text, or null when that row is not in the schedule.</summary>
        Func<string, int, string> Lookup { get; }
    }

    /// <summary>Plain data implementation of <see cref="IFormulaContext"/>: set the members, pass it in.</summary>
    public sealed class FormulaContext : IFormulaContext
    {
        public IDictionary<string, string> Cells { get; set; }
        public int? Row { get; set; }
        public int? Anchor { get; set; }
        public int? N { get; set; }
        public string Id { get; set; }
        public string This { get; set; }
        public Func<string, int, string> Lookup { get; set; }
    }

    public static partial class Efr
    {
        private static readonly Regex TokenRe = new Regex(
            @"\G(?:"
            + @"(?<num>[0-9]+(?:\.[0-9]+)?)"
            + @"|(?<dq>""(?:[^""]|"""")*"")"
            + @"|(?<sq>'(?:[^']|'')*')"
            + @"|(?<cell>[A-Za-z]{1,3}\$?[0-9]+)"
            + @"|(?<name>[A-Za-z_][A-Za-z_0-9]*)"
            + @"|(?<op><>|<=|>=|[&+\-*/()<>=,])"
            + @")", RegexOptions.CultureInvariant);

        internal static List<(string Kind, object Value)> Tokenize(string text)
        {
            var tokens = new List<(string Kind, object Value)>();
            int pos = 0;
            int n = text.Length;
            while (pos < n)
            {
                if (char.IsWhiteSpace(text[pos]))
                {
                    pos++;
                    continue;
                }
                Match m = TokenRe.Match(text, pos);
                if (!m.Success || m.Index + m.Length == pos)
                {
                    throw new FormulaError(string.Format(CultureInfo.InvariantCulture,
                        "cannot read \"{0}\"", text.Substring(pos, Math.Min(12, n - pos))));
                }
                pos = m.Index + m.Length;
                if (m.Groups["num"].Success)
                    tokens.Add(("num", ParseDouble(m.Groups["num"].Value)));
                else if (m.Groups["dq"].Success)
                {
                    string raw = m.Groups["dq"].Value;
                    tokens.Add(("str", raw.Substring(1, raw.Length - 2).Replace("\"\"", "\"")));
                }
                else if (m.Groups["sq"].Success)
                {
                    string raw = m.Groups["sq"].Value;
                    tokens.Add(("str", raw.Substring(1, raw.Length - 2).Replace("''", "'")));
                }
                else if (m.Groups["cell"].Success)
                    tokens.Add(("cell", m.Groups["cell"].Value));
                else if (m.Groups["name"].Success)
                    tokens.Add(("name", m.Groups["name"].Value));
                else
                    tokens.Add(("op", m.Groups["op"].Value));
            }
            tokens.Add(("end", null));
            return tokens;
        }

        private static double ParseDouble(string s)
        {
            try
            {
                return double.Parse(s, NumberStyles.Float, CultureInfo.InvariantCulture);
            }
            catch (OverflowException)
            {
                return s.StartsWith("-", StringComparison.Ordinal) ? double.NegativeInfinity : double.PositiveInfinity;
            }
        }

        // Python's '{0:.6f}'.format(value), exact on every .NET version (round half to even on the exact binary value).
        private static string Fixed6(double v)
        {
            long bits = BitConverter.DoubleToInt64Bits(v);
            bool neg = bits < 0;
            int exp = (int)((bits >> 52) & 0x7FF);
            long mant = bits & 0xFFFFFFFFFFFFFL;
            int e;
            if (exp == 0) e = -1074;
            else { mant |= 1L << 52; e = exp - 1075; }
            BigInteger N = new BigInteger(mant) * 1000000;
            BigInteger q;
            if (e >= 0) q = N << e;
            else
            {
                int shift = -e;
                q = N >> shift;
                BigInteger rem = N - (q << shift);
                BigInteger half = BigInteger.One << (shift - 1);
                int cmp = rem.CompareTo(half);
                if (cmp > 0 || (cmp == 0 && !q.IsEven)) q += BigInteger.One;
            }
            string digits = q.ToString(CultureInfo.InvariantCulture);
            if (digits.Length < 7) digits = digits.PadLeft(7, '0');
            string res = digits.Substring(0, digits.Length - 6) + "." + digits.Substring(digits.Length - 6);
            return neg ? "-" + res : res;
        }

        /// <summary>Formula value to text: integers print without ".0", other numbers with up to 6 decimals.</summary>
        public static string AsText(object value)
        {
            if (value == null) return "";
            if (value is double d)
            {
                if (double.IsNaN(d) || double.IsInfinity(d))
                    throw new InvalidOperationException("number out of range");   // Python: OverflowError / ValueError
                if (Math.Abs(d - Math.Round(d)) < 1e-9)
                    return new BigInteger(Math.Round(d)).ToString(CultureInfo.InvariantCulture);
                string outText = Fixed6(d).TrimEnd('0').TrimEnd('.');
                return outText;
            }
            return Tx(value);
        }

        private static readonly Regex NumberInTextRe = new Regex(@"-?[0-9]+(?:\.[0-9]+)?", RegexOptions.CultureInvariant);

        /// <summary>Formula value to number: the first number found in the text (commas ignored), blank is 0.</summary>
        public static double AsNumber(object value, string what = "value")
        {
            if (value is double d) return d;
            string text = Tx(value).Trim();
            if (text.Length == 0) return 0.0;
            text = text.Replace(",", "");
            Match m = NumberInTextRe.Match(text);
            if (!m.Success)
                throw new FormulaError(string.Format(CultureInfo.InvariantCulture, "\"{0}\" is not a number", what));
            return ParseDouble(m.Value);
        }

        // Python int(float): truncates toward zero; clamped so a huge value still slices like a huge Python int would.
        private static long PyInt(double x)
        {
            if (double.IsNaN(x) || double.IsInfinity(x))
                throw new InvalidOperationException("number out of range");
            double t = Math.Truncate(x);
            if (t > 1e18) return 1000000000000000000L;
            if (t < -1e18) return -1000000000000000000L;
            return (long)t;
        }

        // Python s[start:stop] (None as null), negative indexes counting from the end.
        private static string PySlice(string s, long? start, long? stop)
        {
            long len = s.Length;
            long a = start ?? 0;
            long b = stop ?? len;
            if (a < 0) a = Math.Max(0, a + len); else a = Math.Min(a, len);
            if (b < 0) b = Math.Max(0, b + len); else b = Math.Min(b, len);
            if (b <= a) return "";
            return s.Substring((int)a, (int)(b - a));
        }

        // Python str.replace, including the empty "old" case (inserts "new" between every character and at both ends)
        private static string PyReplace(string s, string oldText, string newText)
        {
            if (oldText.Length == 0)
            {
                StringBuilder sb = new StringBuilder(newText);
                foreach (char ch in s) sb.Append(ch).Append(newText);
                return sb.ToString();
            }
            return s.Replace(oldText, newText);
        }

        private static readonly Regex WhitespaceRunRe = new Regex(@"\s+", RegexOptions.CultureInvariant);

        /// <summary>Zero-pad the number in the text (the last run of digits) to at least <paramref name="width"/> digits.</summary>
        internal static string Pad(string text, long width)
        {
            var parts = SplitNumber(text);
            if (parts == null) return text;
            string prefix = parts.Value.Prefix, digits = parts.Value.Digits, suffix = parts.Value.Suffix;
            bool neg = digits.StartsWith("-", StringComparison.Ordinal);
            string body = neg ? digits.Substring(1) : digits;
            if (body.Length < width) body = new string('0', (int)(width - body.Length)) + body;
            return prefix + (neg ? "-" : "") + body + suffix;
        }

        internal static string Proper(string text)
        {
            StringBuilder sb = new StringBuilder();
            bool cap = true;
            foreach (char ch in Tx(text))
            {
                if (char.IsLetter(ch))
                {
                    sb.Append(cap ? char.ToUpperInvariant(ch) : char.ToLowerInvariant(ch));
                    cap = false;
                }
                else
                {
                    sb.Append(ch);
                    cap = true;
                }
            }
            return sb.ToString();
        }

        // Excel-style ROUND (half away from zero), also for negative places.
        private static double RoundPlaces(double x, long places)
        {
            if (double.IsNaN(x) || double.IsInfinity(x)) return x;
            if (places >= 0)
            {
                if (places > 15) return x;
                return Math.Round(x, (int)places, MidpointRounding.AwayFromZero);
            }
            if (places < -300) return 0.0;
            double factor = Math.Pow(10.0, -places);
            return Math.Round(x / factor, MidpointRounding.AwayFromZero) * factor;
        }

        internal static object Fn(string name, List<object> args, IFormulaContext ctx)
        {
            name = name.ToUpperInvariant();
            Func<int, string, string> txt = (i, dflt) => i < args.Count ? AsText(args[i]) : dflt;
            Func<int, double, double> num = (i, dflt) => i < args.Count ? AsNumber(args[i], name) : dflt;

            switch (name)
            {
                case "CONCAT":
                case "CONCATENATE":
                case "JOIN":
                    {
                        StringBuilder sb = new StringBuilder();
                        foreach (object a in args) sb.Append(AsText(a));
                        return sb.ToString();
                    }
                case "UPPER":
                    return txt(0, "").ToUpperInvariant();
                case "LOWER":
                    return txt(0, "").ToLowerInvariant();
                case "PROPER":
                    return Proper(txt(0, ""));
                case "TRIM":
                    return WhitespaceRunRe.Replace(txt(0, ""), " ").Trim();
                case "LEN":
                    return (double)txt(0, "").Length;
                case "LEFT":
                    return PySlice(txt(0, ""), null, PyInt(num(1, 1.0)));
                case "RIGHT":
                    {
                        long k = PyInt(num(1, 1.0));
                        return k > 0 ? PySlice(txt(0, ""), -k, null) : "";
                    }
                case "MID":
                    {
                        long start = Math.Max(1, PyInt(num(1, 1.0)));
                        long length = PyInt(num(2, 1.0));
                        return PySlice(txt(0, ""), start - 1, start - 1 + length);
                    }
                case "REPLACE":
                case "SUBSTITUTE":
                    return PyReplace(txt(0, ""), txt(1, ""), txt(2, ""));
                case "PAD":
                    return Pad(txt(0, ""), PyInt(num(1, 0.0)));
                case "SEQ":
                    {
                        double start = num(0, 1.0);
                        double step = args.Count > 1 ? num(1, 1.0) : 1.0;
                        double value = start + step * ((ctx.N ?? 1) - 1);
                        string text = AsText(value);
                        if (args.Count > 2) text = Pad(text, PyInt(num(2, 0.0)));
                        return text;
                    }
                case "ROUND":
                    {
                        long places = PyInt(num(1, 0.0));
                        return RoundPlaces(num(0, 0.0), places);
                    }
                case "VALUE":
                case "NUM":
                    return AsNumber(txt(0, ""), name);
                case "IF":
                    {
                        object test = args.Count > 0 ? args[0] : "";
                        bool truthy;
                        if (test is bool tb) truthy = tb;
                        else if (test is double td) truthy = td != 0.0;
                        else truthy = Tx(test).Length > 0;
                        if (truthy)
                        {
                            if (args.Count < 2) throw new InvalidOperationException("list index out of range");
                            return args[1];
                        }
                        return args.Count > 2 ? args[2] : "";
                    }
            }
            throw new FormulaError(string.Format(CultureInfo.InvariantCulture, "unknown function {0}()", name));
        }

        /// <summary>Evaluate one formula against one row. Throws <see cref="FormulaError"/> for a formula the user got wrong.</summary>
        public static string EvaluateFormula(string text, IFormulaContext ctx)
        {
            string body = Tx(text).Trim();
            if (body.StartsWith("=", StringComparison.Ordinal)) body = body.Substring(1);
            if (body.Length == 0) throw new FormulaError("the formula is empty");
            object result = new FormulaParser(Tokenize(body), ctx).Parse();
            if (result is bool b) return b ? "TRUE" : "FALSE";
            return AsText(result);
        }

        public static readonly string[] FORMULA_REF_COLOURS =
            { "C_BLUE", "C_GREEN", "C_TEST_FG", "C_IMP_FG", "C_COPY_FG", "C_RO_FG" };

        private static readonly Regex SpanCellRe = new Regex(@"\G[A-Za-z]{1,3}\$?[0-9]+", RegexOptions.CultureInvariant);
        private static readonly Regex SpanNameRe = new Regex(@"\G[A-Za-z_][A-Za-z_0-9]*", RegexOptions.CultureInvariant);
        private static readonly Regex SpanNumberRe = new Regex(@"\G[0-9]+(\.[0-9]+)?", RegexOptions.CultureInvariant);

        /// <summary>
        /// Break a formula into (start, length, kind, key) runs, for colouring.
        /// kind is one of: plain, func, cell, text, number, op. `key` groups the cell
        /// references: every mention of the same cell gets the same key, so the same
        /// colour, which is what makes a long formula readable at a glance.
        /// `=`, `(`, `)` and `,` stay plain deliberately: they are punctuation.
        /// </summary>
        public static List<(int Start, int Length, string Kind, string Key)> FormulaSpans(string text)
        {
            var spans = new List<(int Start, int Length, string Kind, string Key)>();
            string body = Tx(text);
            int i = 0;
            int n = body.Length;
            while (i < n)
            {
                char ch = body[i];
                if (ch == '=' && i == 0)
                {
                    spans.Add((i, 1, "plain", null));
                    i += 1;
                    continue;
                }
                if (ch == '(' || ch == ')' || ch == ',')
                {
                    spans.Add((i, 1, "plain", null));
                    i += 1;
                    continue;
                }
                if (ch == '"' || ch == '\'')
                {
                    char quote = ch;
                    int j = i + 1;
                    while (j < n)
                    {
                        if (body[j] == quote)
                        {
                            if (j + 1 < n && body[j + 1] == quote)
                            {
                                j += 2;
                                continue;
                            }
                            j += 1;
                            break;
                        }
                        j += 1;
                    }
                    spans.Add((i, j - i, "text", null));
                    i = j;
                    continue;
                }
                Match m = SpanCellRe.Match(body, i);
                if (m.Success && (i == 0 || !(char.IsLetterOrDigit(body[i - 1]) || body[i - 1] == '_')))
                {
                    string token = m.Value;
                    spans.Add((i, token.Length, "cell", token.ToUpperInvariant().Replace("$", "")));
                    i += token.Length;
                    continue;
                }
                m = SpanNameRe.Match(body, i);
                if (m.Success)
                {
                    string word = m.Value;
                    string after = body.Substring(i + word.Length).TrimStart();
                    string kind = after.StartsWith("(", StringComparison.Ordinal) ? "func" : "cell";
                    string key = kind == "func" ? null : word.ToUpperInvariant();
                    spans.Add((i, word.Length, kind, key));
                    i += word.Length;
                    continue;
                }
                m = SpanNumberRe.Match(body, i);
                if (m.Success)
                {
                    spans.Add((i, m.Length, "number", null));
                    i += m.Length;
                    continue;
                }
                if ("&+-*/<>".IndexOf(ch) >= 0)
                {
                    spans.Add((i, 1, "op", null));
                    i += 1;
                    continue;
                }
                spans.Add((i, 1, "plain", null));
                i += 1;
            }
            return spans;
        }

        /// <summary>
        /// A stable colour (the current theme's hex string) per distinct reference, in the order they first appear.
        /// Pass the same `order` list for every span of one formula.
        /// </summary>
        public static string FormulaRefColour(string key, List<string> order)
        {
            if (!order.Contains(key)) order.Add(key);
            int slot = order.IndexOf(key) % FORMULA_REF_COLOURS.Length;
            switch (slot)
            {
                case 0: return C_BLUE;
                case 1: return C_GREEN;
                case 2: return C_TEST_FG;
                case 3: return C_IMP_FG;
                case 4: return C_COPY_FG;
                default: return C_RO_FG;
            }
        }
    }

    internal sealed class FormulaParser
    {
        private readonly List<(string Kind, object Value)> _tokens;
        private int _i;
        private readonly IFormulaContext _ctx;

        public FormulaParser(List<(string Kind, object Value)> tokens, IFormulaContext ctx)
        {
            _tokens = tokens;
            _i = 0;
            _ctx = ctx;
        }

        private (string Kind, object Value) Peek()
        {
            return _tokens[_i];
        }

        private (string Kind, object Value) Take()
        {
            var tok = _tokens[_i];
            _i += 1;
            return tok;
        }

        private void ExpectOp(string op)
        {
            var t = Take();
            if (t.Kind == "end")
                throw new FormulaError(string.Format(CultureInfo.InvariantCulture, "a closing \"{0}\" is missing", op));
            if (t.Kind != "op" || (string)t.Value != op)
                throw new FormulaError(string.Format(CultureInfo.InvariantCulture, "expected \"{0}\"", op));
        }

        public object Parse()
        {
            object value = Comparison();
            if (Peek().Kind != "end")
                throw new FormulaError(string.Format(CultureInfo.InvariantCulture,
                    "unexpected \"{0}\"", Efr.AsText(Peek().Value)));
            return value;
        }

        private bool IsOp(string op)
        {
            var t = Peek();
            return t.Kind == "op" && (string)t.Value == op;
        }

        private object Comparison()
        {
            object left = Concat();
            var t = Peek();
            if (t.Kind == "op")
            {
                string op = (string)t.Value;
                if (op == "=" || op == "<>" || op == "<" || op == ">" || op == "<=" || op == ">=")
                {
                    Take();
                    object right = Concat();
                    if (left is double || right is double)
                    {
                        double a = Efr.AsNumber(left), b = Efr.AsNumber(right);
                        switch (op)
                        {
                            case "=": return a == b;
                            case "<>": return a != b;
                            case "<": return a < b;
                            case ">": return a > b;
                            case "<=": return a <= b;
                            default: return a >= b;
                        }
                    }
                    else
                    {
                        string a = Efr.AsText(left), b = Efr.AsText(right);
                        int c = string.CompareOrdinal(a, b);
                        switch (op)
                        {
                            case "=": return a == b;
                            case "<>": return a != b;
                            case "<": return c < 0;
                            case ">": return c > 0;
                            case "<=": return c <= 0;
                            default: return c >= 0;
                        }
                    }
                }
            }
            return left;
        }

        private object Concat()
        {
            object value = Additive();
            while (true)
            {
                if (IsOp("&"))
                {
                    Take();
                    string l = Efr.AsText(value);
                    value = l + Efr.AsText(Additive());
                }
                else
                {
                    return value;
                }
            }
        }

        private object Additive()
        {
            object value = Multiplicative();
            while (true)
            {
                var t = Peek();
                if (t.Kind == "op" && ((string)t.Value == "+" || (string)t.Value == "-"))
                {
                    string op = (string)t.Value;
                    Take();
                    object right = Multiplicative();
                    double l = Efr.AsNumber(value);
                    double r = Efr.AsNumber(right);
                    value = op == "+" ? l + r : l - r;
                }
                else
                {
                    return value;
                }
            }
        }

        private object Multiplicative()
        {
            object value = Unary();
            while (true)
            {
                var t = Peek();
                if (t.Kind == "op" && ((string)t.Value == "*" || (string)t.Value == "/"))
                {
                    string op = (string)t.Value;
                    Take();
                    double right = Efr.AsNumber(Unary());
                    if (op == "*")
                    {
                        value = Efr.AsNumber(value) * right;
                    }
                    else
                    {
                        if (right == 0) throw new FormulaError("division by zero");
                        value = Efr.AsNumber(value) / right;
                    }
                }
                else
                {
                    return value;
                }
            }
        }

        private object Unary()
        {
            if (IsOp("-"))
            {
                Take();
                return -Efr.AsNumber(Unary());
            }
            if (IsOp("+"))
            {
                Take();
                return Unary();
            }
            return Primary();
        }

        private object Primary()
        {
            var tok = Take();
            string kind = tok.Kind;
            object value = tok.Value;
            if (kind == "num") return value;
            if (kind == "str") return value;
            if (kind == "op" && (string)value == "(")
            {
                object inner = Comparison();
                ExpectOp(")");
                return inner;
            }
            if (kind == "end") throw new FormulaError("the formula ends before it is finished");
            if (kind == "cell") return CellReference((string)value);
            if (kind == "name")
            {
                if (IsOp("("))
                {
                    Take();
                    var args = new List<object>();
                    var pk = Peek();
                    if (!(pk.Kind == "op" && (string)pk.Value == ")"))
                    {
                        while (true)
                        {
                            args.Add(Comparison());
                            if (IsOp(","))
                            {
                                Take();
                                continue;
                            }
                            break;
                        }
                    }
                    ExpectOp(")");
                    return Efr.Fn((string)value, args, _ctx);
                }
                return Reference((string)value);
            }
            throw new FormulaError(string.Format(CultureInfo.InvariantCulture, "unexpected \"{0}\"", Efr.AsText(value)));
        }

        private static readonly Regex CellRe = new Regex(@"^([A-Za-z]{1,3})(\$?)([0-9]+)$", RegexOptions.CultureInvariant);

        /// <summary>
        /// A5 and A$5: a column letter with a row number.
        /// Relative like Excel: A5 written against row 5 means "this row", and the
        /// same formula on row 6 reads A6. A$5 locks the row. A bare letter is the
        /// short way of writing the same-row form.
        /// </summary>
        private object CellReference(string text)
        {
            Match m = CellRe.Match(text);
            if (!m.Success)
                throw new FormulaError(string.Format(CultureInfo.InvariantCulture, "\"{0}\" is not a cell", text));
            string column = m.Groups[1].Value.ToUpperInvariant();
            bool locked = m.Groups[2].Value == "$";
            BigInteger want = BigInteger.Parse(m.Groups[3].Value, CultureInfo.InvariantCulture);
            IDictionary<string, string> cells = _ctx.Cells;
            if (cells == null || !cells.ContainsKey(column))
                throw new FormulaError(string.Format(CultureInfo.InvariantCulture,
                    "there is no column {0} in this schedule", column));
            BigInteger row;
            if (locked)
            {
                row = want;
            }
            else
            {
                BigInteger rowNow = _ctx.Row.HasValue ? new BigInteger(_ctx.Row.Value) : want;
                BigInteger anchor = _ctx.Anchor.HasValue ? new BigInteger(_ctx.Anchor.Value) : rowNow;
                if (anchor.IsZero) anchor = want;
                row = rowNow + (want - anchor);
            }
            Func<string, int, string> lookup = _ctx.Lookup;
            if (lookup == null) throw new FormulaError("cell references are not available here");
            string value = null;
            if (row >= int.MinValue && row <= int.MaxValue) value = lookup(column, (int)row);
            if (value == null)
                throw new FormulaError(string.Format(CultureInfo.InvariantCulture,
                    "row {0} is not in this schedule", row.ToString(CultureInfo.InvariantCulture)));
            return value;
        }

        private static readonly Regex LettersRe = new Regex(@"^[A-Z]+$", RegexOptions.CultureInvariant);

        private object Reference(string name)
        {
            string upper = name.ToUpperInvariant();
            if (upper == "ROW") return (double)(_ctx.Row ?? 0);
            if (upper == "N" || upper == "INDEX") return (double)(_ctx.N ?? 0);
            if (upper == "ID") return _ctx.Id ?? "";
            if (upper == "THIS") return _ctx.This ?? "";
            string cellValue;
            if (_ctx.Cells != null && _ctx.Cells.TryGetValue(upper, out cellValue)) return cellValue;
            if (LettersRe.IsMatch(upper))
                throw new FormulaError(string.Format(CultureInfo.InvariantCulture,
                    "there is no column {0} in this schedule", upper));
            throw new FormulaError(string.Format(CultureInfo.InvariantCulture, "unknown name \"{0}\"", name));
        }
    }
}
