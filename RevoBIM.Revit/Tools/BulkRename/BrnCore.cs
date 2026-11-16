using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.BulkRename
{
    /// <summary>The two things a Project Browser item can have renamed: its name, and (sheets) its number.</summary>
    public enum Field
    {
        Name,
        Number,
    }

    /// <summary>What a rename would do to one field of one item.</summary>
    public enum ItemState
    {
        Same,
        Change,
        Clash,
        Bad,
    }

    /// <summary>The find / replace / prefix / suffix typed in the tools column.</summary>
    public sealed class Rules
    {
        public string Find = "";
        public string Replace = "";
        public bool MatchCase;
        public string Prefix = "";
        public string Suffix = "";

        public bool IsEmpty
        {
            get { return string.IsNullOrEmpty(Find) && string.IsNullOrEmpty(Prefix) && string.IsNullOrEmpty(Suffix); }
        }
    }

    /// <summary>A piece of a new name, and whether the rules put it there (shown orange in the preview).</summary>
    public struct Segment
    {
        public string Text;
        public bool Changed;

        public Segment(string text, bool changed)
        {
            Text = text;
            Changed = changed;
        }
    }

    /// <summary>One selected item. Id is the real ElementId; Key is its integer.</summary>
    public sealed class Row
    {
        public readonly ElementId Id;
        public readonly long Key;
        public readonly string Kind;
        public readonly Dictionary<Field, string> Values = new Dictionary<Field, string>();
        public readonly Dictionary<Field, string> Scopes = new Dictionary<Field, string>();

        public Row(ElementId id, long key, string kind, string name, string number = null,
                   string nameScope = null, string numberScope = null)
        {
            Id = id;
            Key = key;
            Kind = kind;
            Values[Field.Name] = name;
            Scopes[Field.Name] = nameScope;
            Scopes[Field.Number] = numberScope;
            if (number != null) Values[Field.Number] = number;
        }

        public bool Has(Field field)
        {
            return Values.ContainsKey(field);
        }

        public string ScopeOf(Field field)
        {
            string scope;
            return Scopes.TryGetValue(field, out scope) ? scope : null;
        }
    }

    /// <summary>What one field of one row would become.</summary>
    public sealed class Item
    {
        public readonly Row Row;
        public readonly Field Field;
        public readonly string Old;
        public readonly string Scope;
        public readonly string New;
        public readonly List<Segment> Segments;
        public string Reason;
        public ItemState State = ItemState.Same;

        public Item(Row row, Field field, Rules rules)
        {
            Row = row;
            Field = field;
            Old = row.Values[field];
            Scope = row.ScopeOf(field);
            New = BrnCore.ApplyRules(Old, rules, out Segments);
            if (New != Old)
            {
                Reason = BrnCore.BadReason(Old, New);
                State = Reason != null ? ItemState.Bad : ItemState.Change;
            }
        }

        public string Final
        {
            get { return State == ItemState.Change ? New : Old; }
        }
    }

    /// <summary>
    /// Bulk Rename rules, settings and window maths. Port of brn_core.py. Nothing in here touches Revit
    /// beyond holding an ElementId, and nothing touches WPF.
    /// </summary>
    public static class BrnCore
    {
        public const string ToolName = "Bulk Rename";
        public const string SettingsName = "bulk_rename.txt";
        public const string DebugName = "bulk_rename_debug.txt";
        public const string ErrorName = "bulk_rename_last_error.txt";
        public const int SettingsVersion = 1;
        public const string Version = "1.1.0";

        public static readonly Field[] Fields = { Field.Name, Field.Number };
        public static readonly string[] ParamKeys = { "sheet_param_1", "sheet_param_2", "sheet_param_3" };

        /// <summary>Characters Revit will not take in a name.</summary>
        public const string Illegal = "\\:{}[]|;<>?`~";
        public const string ParkPrefix = "zz-rbrn-parked-";

        // drawer
        public const double SlideSeconds = 0.28;
        public const int TickMs = 15;
        public const double BarGap = 8.0;
        public const double StackGap = 4.0;

        public static readonly Dictionary<string, string> Defaults = new Dictionary<string, string>
        {
            { "theme", "auto" },
            { "debug", "1" },
            { "sheet_param_1", "BGL_Sheet Title 1" },
            { "sheet_param_2", "BGL_Sheet Title 2" },
            { "sheet_param_3", "BGL_Sheet Title 3" },
            { "sheet_delimiter", "_" },
            { "sheet_format", "none" },
        };

        // ==================== rules ====================

        /// <summary>The new text and its pieces. Find and replace first, then the prefix, then the suffix.</summary>
        public static string ApplyRules(string text, Rules rules, out List<Segment> segments)
        {
            text = text ?? "";
            var raw = new List<Segment>();
            raw.Add(new Segment(rules.Prefix ?? "", true));
            if (!string.IsNullOrEmpty(rules.Find))
            {
                StringComparison comparison = rules.MatchCase ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
                int pos = 0;
                while (true)
                {
                    int at = text.IndexOf(rules.Find, pos, comparison);
                    if (at < 0) break;
                    raw.Add(new Segment(text.Substring(pos, at - pos), false));
                    raw.Add(new Segment(rules.Replace ?? "", true));
                    pos = at + rules.Find.Length;
                }
                raw.Add(new Segment(text.Substring(pos), false));
            }
            else
            {
                raw.Add(new Segment(text, false));
            }
            raw.Add(new Segment(rules.Suffix ?? "", true));
            segments = Merge(raw);
            return string.Concat(segments.Select(s => s.Text));
        }

        private static List<Segment> Merge(List<Segment> segments)
        {
            var output = new List<Segment>();
            foreach (Segment piece in segments)
            {
                if (string.IsNullOrEmpty(piece.Text)) continue;
                if (output.Count > 0 && output[output.Count - 1].Changed == piece.Changed)
                    output[output.Count - 1] = new Segment(output[output.Count - 1].Text + piece.Text, piece.Changed);
                else
                    output.Add(piece);
            }
            return output;
        }

        /// <summary>
        /// Why Revit would refuse this text, or null. A character the name already has is not held against
        /// it, so a prefix on an old name still works.
        /// </summary>
        public static string BadReason(string old, string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return "Would leave it empty";
            foreach (char ch in Illegal)
            {
                if (text.IndexOf(ch) >= 0 && old.IndexOf(ch) < 0)
                    return "Revit does not allow " + ch + " in a name";
            }
            return null;
        }

        // ==================== order ====================

        /// <summary>Digits compare as numbers, everything else as lower case text.</summary>
        public static int CompareNatural(string left, string right)
        {
            string[] a = SplitNatural(left);
            string[] b = SplitNatural(right);
            int shared = Math.Min(a.Length, b.Length);
            for (int i = 0; i < shared; i++)
            {
                bool aNumber = i % 2 == 1;   // odd positions are the digit runs
                int compared = aNumber ? CompareDigits(a[i], b[i]) : string.CompareOrdinal(a[i], b[i]);
                if (compared != 0) return compared;
            }
            return a.Length.CompareTo(b.Length);
        }

        private static string[] SplitNatural(string text)
        {
            text = (text ?? "").ToLowerInvariant();
            var parts = new List<string>();
            var current = new StringBuilder();
            bool inDigits = false;
            foreach (char ch in text)
            {
                bool digit = ch >= '0' && ch <= '9';
                if (digit != inDigits)
                {
                    parts.Add(current.ToString());
                    current.Clear();
                    inDigits = digit;
                }
                current.Append(ch);
            }
            parts.Add(current.ToString());
            return parts.ToArray();
        }

        private static int CompareDigits(string a, string b)
        {
            a = a.TrimStart('0');
            b = b.TrimStart('0');
            if (a.Length != b.Length) return a.Length.CompareTo(b.Length);
            return string.CompareOrdinal(a, b);
        }

        /// <summary>Sheets first, by number. Everything else by kind, then name. Stable.</summary>
        public static List<Row> SortRows(IEnumerable<Row> rows)
        {
            return rows.OrderBy(r => r, Comparer<Row>.Create(CompareRows)).ToList();
        }

        private static int CompareRows(Row a, Row b)
        {
            int ak = a.Has(Field.Number) ? 0 : 1;
            int bk = b.Has(Field.Number) ? 0 : 1;
            if (ak != bk) return ak.CompareTo(bk);
            if (ak == 0) return CompareNatural(a.Values[Field.Number], b.Values[Field.Number]);
            int kind = CompareNatural(a.Kind, b.Kind);
            return kind != 0 ? kind : CompareNatural(a.Values[Field.Name], b.Values[Field.Name]);
        }

        // ==================== evaluation ====================

        /// <summary>
        /// What every selected field would become. taken is {scope: names held by elements outside the batch}.
        /// A name kept by one clash can become the next one's clash, so this repeats until nothing moves.
        /// </summary>
        public static List<Item> Evaluate(IList<Row> rows, IDictionary<Field, Rules> rules,
                                          IDictionary<string, HashSet<string>> taken)
        {
            var items = new List<Item>();
            foreach (Field field in Fields)
            {
                foreach (Row row in rows)
                {
                    if (row.Has(field)) items.Add(new Item(row, field, rules[field]));
                }
            }
            bool moved = true;
            while (moved)
            {
                moved = false;
                var landing = new Dictionary<string, int>();
                foreach (Item item in items)
                {
                    if (item.Scope == null) continue;
                    string key = item.Scope + "\u0001" + item.Final;
                    int seen;
                    landing.TryGetValue(key, out seen);
                    landing[key] = seen + 1;
                }
                foreach (Item item in items)
                {
                    if (item.State != ItemState.Change || item.Scope == null) continue;
                    HashSet<string> held;
                    if (taken != null && taken.TryGetValue(item.Scope, out held) && held.Contains(item.New))
                    {
                        item.State = ItemState.Clash;
                        item.Reason = "Already used by an item not selected";
                        moved = true;
                    }
                    else if (landing[item.Scope + "\u0001" + item.New] > 1)
                    {
                        item.State = ItemState.Clash;
                        item.Reason = "Another selected item would get the same name";
                        moved = true;
                    }
                }
            }
            return items;
        }

        public static List<Item> Changes(IEnumerable<Item> items)
        {
            return items.Where(i => i.State == ItemState.Change).ToList();
        }

        /// <summary>
        /// Changes leaving a name that another change is landing on. Those go through a parked name first,
        /// so a swap does not clash with itself.
        /// </summary>
        public static List<Item> NeedsParking(IEnumerable<Item> items)
        {
            List<Item> changing = Changes(items);
            var going = new Dictionary<string, Item>();
            foreach (Item item in changing)
                going[(item.Scope ?? "") + "\u0001" + item.Old] = item;
            var output = new List<Item>();
            foreach (Item item in changing)
            {
                if (item.Scope == null) continue;
                Item other;
                if (going.TryGetValue(item.Scope + "\u0001" + item.New, out other) && !ReferenceEquals(other, item)
                    && !output.Contains(other))
                    output.Add(other);
            }
            return output;
        }

        public static int Count(IEnumerable<Item> items, ItemState state)
        {
            return items.Count(i => i.State == state);
        }

        public static string StatusLine(IList<Item> items)
        {
            int change = Count(items, ItemState.Change);
            int stopped = Count(items, ItemState.Clash) + Count(items, ItemState.Bad);
            if (change == 0 && stopped == 0) return "Type in a tool to preview the change.";
            string text = change + " will change";
            if (stopped > 0) text += ", " + stopped + " left alone";
            return text;
        }

        public static string Plural(int count, string word)
        {
            return count == 1 ? "1 " + word : count + " " + word + "s";
        }

        // ==================== settings ====================

        public static string DataDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string SettingsPath()
        {
            return Path.Combine(DataDir(), SettingsName);
        }

        public static Dictionary<string, string> ParseSettings(string text)
        {
            var output = new Dictionary<string, string>(Defaults);
            foreach (string raw in (text ?? "").Split('\n'))
            {
                string line = raw.TrimEnd('\r');
                int eq = line.IndexOf('=');
                if (eq < 0) continue;
                string key = line.Substring(0, eq).Trim();
                string value = line.Substring(eq + 1);
                if (key == "sheet_delimiter")
                    output[key] = value;               // a space is a real delimiter
                else if (Defaults.ContainsKey(key))
                    output[key] = value.Trim();
            }
            string theme = output["theme"];
            if (theme != "auto" && theme != "dark" && theme != "light") output["theme"] = Defaults["theme"];
            string format = output["sheet_format"];
            if (format != "upper" && format != "title" && format != "none") output["sheet_format"] = Defaults["sheet_format"];
            return output;
        }

        public static string FormatSettings(IDictionary<string, string> settings)
        {
            var lines = new List<string> { "settings_version=" + SettingsVersion };
            foreach (string key in Defaults.Keys.OrderBy(k => k, StringComparer.Ordinal))
            {
                string value;
                lines.Add(key + "=" + (settings.TryGetValue(key, out value) ? value : Defaults[key]));
            }
            return string.Join("\n", lines) + "\n";
        }

        public static Dictionary<string, string> LoadSettings()
        {
            string text = "";
            try
            {
                text = File.ReadAllText(SettingsPath(), Encoding.UTF8);
            }
            catch (Exception)
            {
            }
            return ParseSettings(text);
        }

        public static void SaveSettings(IDictionary<string, string> settings)
        {
            try
            {
                Directory.CreateDirectory(DataDir());
                File.WriteAllText(SettingsPath(), FormatSettings(settings), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }

        // ==================== theme choice ====================

        public static string NextTheme(string mode)
        {
            string[] order = { "auto", "dark", "light" };
            int at = Array.IndexOf(order, mode);
            return at < 0 ? "auto" : order[(at + 1) % 3];
        }

        public static string ResolveTheme(string mode, string canvas)
        {
            if (mode == "dark" || mode == "light") return mode;
            return canvas == "dark" || canvas == "light" ? canvas : "dark";
        }

        public static string CanvasFromRgb(int red, int green, int blue)
        {
            double light = 0.299 * red + 0.587 * green + 0.114 * blue;
            return light < 128 ? "dark" : "light";
        }

        // ==================== window maths ====================

        public static double Ease(double progress)
        {
            progress = Math.Max(0.0, Math.Min(1.0, progress));
            return 1.0 - Math.Pow(1.0 - progress, 3);
        }

        public static int FreeSlot<T>(IList<T> slots) where T : class
        {
            for (int i = 0; i < slots.Count; i++)
            {
                if (slots[i] == null) return i;
            }
            return slots.Count;
        }

        /// <summary>Top of a parked bar. below is the height of the bars already stacked under it.</summary>
        public static double ParkedTop(double workTop, double workHeight, double barHeight, double below)
        {
            return workTop + workHeight - barHeight - BarGap - below;
        }

        /// <summary>Back where it was, or upward from where the bar was carried to. Returns (left, top).</summary>
        public static Tuple<double, double> ExpandRect(Rect4 saved, double barLeft, double barTop,
                                                       double parkedLeft, double parkedAt, Rect4 work)
        {
            if (Math.Abs(barLeft - parkedLeft) <= 2 && Math.Abs(barTop - parkedAt) <= 2)
                return Tuple.Create(saved.Left, saved.Top);
            double newTop = barTop - saved.Height + 40;
            newTop = Math.Max(work.Top, Math.Min(newTop, work.Top + work.Height - saved.Height));
            double newLeft = Math.Max(work.Left, Math.Min(barLeft, work.Left + work.Width - saved.Width));
            return Tuple.Create(newLeft, newTop);
        }

        /// <summary>A window rectangle dragged by a grip; edge holds L, T, R, B.</summary>
        public static Rect4 Resize(Rect4 rect, string edge, double dx, double dy, double minWidth, double minHeight)
        {
            double left = rect.Left, top = rect.Top, width = rect.Width, height = rect.Height;
            if (edge.Contains("R")) width = Math.Max(minWidth, width + dx);
            if (edge.Contains("B")) height = Math.Max(minHeight, height + dy);
            if (edge.Contains("L"))
            {
                double next = Math.Max(minWidth, width - dx);
                left += width - next;
                width = next;
            }
            if (edge.Contains("T"))
            {
                double next = Math.Max(minHeight, height - dy);
                top += height - next;
                height = next;
            }
            return new Rect4(left, top, width, height);
        }

        /// <summary>
        /// Always count values. Anything past the last slot stays in it, so no part of the name is lost;
        /// a short name blanks the rest so no old value is left behind.
        /// </summary>
        public static string[] SplitSheetName(string name, string delimiter, int count = 3)
        {
            name = name ?? "";
            var parts = string.IsNullOrEmpty(delimiter)
                ? new List<string> { name }
                : name.Split(new[] { delimiter }, StringSplitOptions.None).ToList();
            if (parts.Count > count)
            {
                string rest = string.Join(delimiter, parts.Skip(count - 1));
                parts = parts.Take(count - 1).ToList();
                parts.Add(rest);
            }
            parts = parts.Select(p => p.Trim()).ToList();
            while (parts.Count < count) parts.Add("");
            return parts.ToArray();
        }

        /// <summary>The text format chosen for the push: upper, title (each word capitalised) or none.</summary>
        public static string FormatText(string value, string mode)
        {
            value = (value ?? "").Trim();
            if (mode == "upper") return value.ToUpperInvariant();
            if (mode == "title")
                return string.Join(" ", value.Split(' ').Select(w => w.Length == 0 ? w : w.Substring(0, 1).ToUpperInvariant() + w.Substring(1).ToLowerInvariant()));
            return value;
        }

        public static string FormatLabel(string mode)
        {
            return mode == "upper" ? "UPPERCASE" : mode == "title" ? "Camel Case" : "Not formatted";
        }
        /// <summary>(parameter, value) for the slots that have a parameter set.</summary>
        public static List<KeyValuePair<string, string>> SheetWrites(string name, IDictionary<string, string> settings)
        {
            string delimiter;
            if (!settings.TryGetValue("sheet_delimiter", out delimiter)) delimiter = "";
            string format;
            if (!settings.TryGetValue("sheet_format", out format)) format = "none";
            string[] values = SplitSheetName(name, delimiter).Select(v => FormatText(v, format)).ToArray();
            var output = new List<KeyValuePair<string, string>>();
            for (int i = 0; i < ParamKeys.Length; i++)
            {
                string param;
                if (!settings.TryGetValue(ParamKeys[i], out param)) param = "";
                param = (param ?? "").Trim();
                if (param.Length > 0) output.Add(new KeyValuePair<string, string>(param, values[i]));
            }
            return output;
        }

        /// <summary>Width the list needs for (main text width, side text width) pairs. chrome is padding, frame and scroll bar.</summary>
        public static double ListWidth(IEnumerable<Tuple<double, double>> pairs, double gap = 14.0, double chrome = 34.0)
        {
            double widest = 0.0;
            foreach (Tuple<double, double> pair in pairs)
                widest = Math.Max(widest, pair.Item1 + (pair.Item2 > 0 ? pair.Item2 + gap : 0.0));
            return widest + chrome;
        }

        /// <summary>
        /// (left, width) grown by extra. Never narrower, never wider than the screen, and moved left when the
        /// right edge would run off it.
        /// </summary>
        public static Tuple<double, double> Widened(double left, double width, double extra, double workLeft, double workWidth)
        {
            if (extra <= 0) return Tuple.Create(left, width);
            double newWidth = Math.Min(width + extra, workWidth);
            double rightLimit = workLeft + workWidth;
            double newLeft = Math.Max(workLeft, Math.Min(left, rightLimit - newWidth));
            return Tuple.Create(newLeft, newWidth);
        }
    }

    /// <summary>left, top, width, height.</summary>
    public struct Rect4
    {
        public double Left, Top, Width, Height;

        public Rect4(double left, double top, double width, double height)
        {
            Left = left;
            Top = top;
            Width = width;
            Height = height;
        }
    }

    /// <summary>The debug log: %APPDATA%\RevoBIM\bulk_rename_debug.txt, appended to while the Debug tick is on.</summary>
    public sealed class BrnLog
    {
        public bool Enabled;
        public readonly string Path;

        public BrnLog(bool enabled)
        {
            Enabled = enabled;
            Path = System.IO.Path.Combine(BrnCore.DataDir(), BrnCore.DebugName);
        }

        public void Write(string text)
        {
            if (!Enabled) return;
            try
            {
                Directory.CreateDirectory(BrnCore.DataDir());
                File.AppendAllText(Path, (text ?? "") + "\n", new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }

        /// <summary>The text of the last failure, kept next to the settings, so a report can be pasted.</summary>
        public static void WriteError(string stage, string text)
        {
            try
            {
                Directory.CreateDirectory(BrnCore.DataDir());
                File.WriteAllText(System.IO.Path.Combine(BrnCore.DataDir(), BrnCore.ErrorName),
                                  "Bulk Rename stopped at: " + stage + "\n\n" + text, new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }
}
