using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.WorksetManagement
{
    /// <summary>
    /// Workset Management: version, settings, palettes and every rule the tool runs on (renaming, filtering,
    /// sorting, validation, the delete plan, the spreadsheet diff, the category claims). Nothing here touches the
    /// Revit API. Port of wsm_core.py (tool version 3.1.0).
    /// </summary>
    public static partial class WsmCore
    {
        public const string Version = "3.1.0";
        public const string ToolName = "Workset Management";
        public const string ToolKey = "workset_management";

        public static string AppDataDir
        {
            get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM"); }
        }
        public static string SettingsPath { get { return Path.Combine(AppDataDir, ToolKey + ".txt"); } }
        public static string DebugPath { get { return Path.Combine(AppDataDir, ToolKey + "_debug.txt"); } }
        public static string LoadErrorPath { get { return Path.Combine(AppDataDir, ToolKey + "_last_error.txt"); } }
        public static string RoutineDir { get { return Path.Combine(AppDataDir, "workset_routines"); } }
        public static string ErrorPath { get { return Path.Combine(AppDataDir, ToolKey + "_errors.txt"); } }
        public static string ReportPath { get { return Path.Combine(AppDataDir, ToolKey + "_report.txt"); } }
        public const int ErrorLogLimit = 200000;

        public const string SettingsVersion = "2";

        public static readonly string[] SettingKeys =
        {
            "settings_version", "theme", "tab", "auto_editable", "new_rows", "show_results", "hide_empty_categories",
            "subgroup_service_type", "last_export_dir", "last_routine_dir", "debug", "width", "height",
        };

        public static Dictionary<string, string> Defaults()
        {
            return new Dictionary<string, string>
            {
                { "settings_version", SettingsVersion },
                { "theme", "follow" },
                { "tab", "manage" },
                { "auto_editable", "true" },
                { "new_rows", "10" },
                { "show_results", "needed" },
                { "hide_empty_categories", "true" },
                { "subgroup_service_type", "true" },
                { "last_export_dir", "" },
                { "last_routine_dir", "" },
                { "debug", "true" },
                { "width", "1260" },
                { "height", "820" },
            };
        }

        public const string NewRowPlaceholder = "<type a new workset name here>";
        public const string NewRowKey = "NEW";
        public const string BadNameChars = ":{}[]|;<>?`~\\";
        public const int MaxNameLength = 255;

        public static readonly string[] SubgroupBics = { "OST_CableTray", "OST_CableTrayFitting" };
        public static readonly string[] DatumBics = { "OST_Levels", "OST_Grids", "OST_VolumeOfInterest" };
        public static readonly string[] ServiceParamNames = { "Service Type", "BGL_Service Type", "Service" };
        public const string NoService = "(no service type)";
        public const string NoCategory = "(no category)";
        public const string NoColour = "Transparent";

        // ================================================================ text

        public static string Txt(object value) { return value == null ? "" : Convert.ToString(value, CultureInfo.InvariantCulture); }

        public static bool AsBool(string value, bool fallback = false)
        {
            string text = Txt(value).Trim().ToLowerInvariant();
            if (text == "true" || text == "1" || text == "yes" || text == "on") return true;
            if (text == "false" || text == "0" || text == "no" || text == "off") return false;
            return fallback;
        }

        public static int AsInt(string value, int fallback = 0)
        {
            double d;
            if (double.TryParse(Txt(value).Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out d)) return (int)d;
            return fallback;
        }

        private static readonly Regex NumRe = new Regex(@"(\d+)", RegexOptions.Compiled);

        private struct NatPart
        {
            public int Kind; public long Num; public string Text;
        }

        private static List<NatPart> NaturalParts(string value)
        {
            string text = Txt(value).ToLowerInvariant();
            var key = new List<NatPart>();
            string[] parts = NumRe.Split(text);
            for (int i = 0; i < parts.Length; i++)
            {
                if (i % 2 == 1)
                {
                    long n;
                    if (!long.TryParse(parts[i], NumberStyles.None, CultureInfo.InvariantCulture, out n)) n = long.MaxValue;
                    key.Add(new NatPart { Kind = 1, Num = n, Text = "" });
                }
                else if (parts[i].Length > 0) key.Add(new NatPart { Kind = 2, Num = 0, Text = parts[i] });
            }
            return key;
        }

        /// <summary>'P-9' before 'P-10' before 'P-100'; case folded.</summary>
        public static int NaturalCompare(string a, string b)
        {
            List<NatPart> x = NaturalParts(a), y = NaturalParts(b);
            int n = Math.Min(x.Count, y.Count);
            for (int i = 0; i < n; i++)
            {
                if (x[i].Kind != y[i].Kind) return x[i].Kind.CompareTo(y[i].Kind);
                if (x[i].Kind == 1)
                {
                    int c = x[i].Num.CompareTo(y[i].Num);
                    if (c != 0) return c;
                }
                else
                {
                    int c = string.CompareOrdinal(x[i].Text, y[i].Text);
                    if (c != 0) return c;
                }
            }
            return x.Count.CompareTo(y.Count);
        }

        public static readonly IComparer<string> Natural = Comparer<string>.Create(NaturalCompare);

        /// <summary>A stable sort, ascending or descending (descending keeps the order of equal items, as Python's reverse=True does).</summary>
        public static List<T> StableSort<T>(IEnumerable<T> items, Comparison<T> compare, bool descending)
        {
            var list = items.Select((item, index) => new KeyValuePair<int, T>(index, item)).ToList();
            list.Sort((p, q) =>
            {
                int c = compare(p.Value, q.Value);
                if (descending) c = -c;
                return c != 0 ? c : p.Key.CompareTo(q.Key);
            });
            return list.Select(p => p.Value).ToList();
        }

        public static List<string> SortedNatural(IEnumerable<string> values)
        {
            return StableSort(values, NaturalCompare, false);
        }

        // ================================================================ files

        public static List<string> ReadLines(string path)
        {
            var lines = new List<string>();
            try
            {
                if (!File.Exists(path)) return lines;
                using (var reader = new StreamReader(path, new UTF8Encoding(false), true))
                {
                    string line;
                    while ((line = reader.ReadLine()) != null) lines.Add(line.TrimEnd('\r', '\n'));
                }
            }
            catch (Exception) { }
            return lines;
        }

        public static bool WriteLines(string path, IEnumerable<string> lines)
        {
            try
            {
                string folder = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder)) Directory.CreateDirectory(folder);
            }
            catch (Exception) { }
            try
            {
                string body = string.Join("\n", lines.Select(Txt)) + "\n";
                File.WriteAllText(path, body, new UTF8Encoding(false));
                return true;
            }
            catch (Exception) { return false; }
        }

        // ================================================================ settings

        /// <summary>key=value lines to settings: defaults key by key, unknown keys ignored, migrations reset keys whose meaning changed.</summary>
        public static Dictionary<string, string> ParseSettings(IEnumerable<string> lines)
        {
            Dictionary<string, string> defaults = Defaults();
            var values = new Dictionary<string, string>(defaults);
            var stored = new Dictionary<string, string>();
            foreach (string line in lines)
            {
                string text = Txt(line).Trim();
                if (text.Length == 0 || text.StartsWith("#") || !text.Contains("=")) continue;
                int at = text.IndexOf('=');
                string key = text.Substring(0, at).Trim();
                if (defaults.ContainsKey(key)) stored[key] = text.Substring(at + 1).Trim();
            }
            foreach (var pair in stored) values[pair.Key] = pair.Value;
            string written;
            int version = AsInt(stored.TryGetValue("settings_version", out written) ? written : "1", 1);
            if (version < 2)
            {
                foreach (string key in new[] { "theme", "auto_editable", "width", "height" }) values[key] = defaults[key];
            }
            values["settings_version"] = SettingsVersion;
            return values;
        }

        public static List<string> SettingsLines(Dictionary<string, string> values)
        {
            Dictionary<string, string> defaults = Defaults();
            var lines = new List<string> { "# RevoBIM - Workset Management settings" };
            foreach (string key in defaults.Keys.OrderBy(k => k, StringComparer.Ordinal))
            {
                string v;
                lines.Add(key + "=" + Txt(values.TryGetValue(key, out v) ? v : defaults[key]));
            }
            return lines;
        }

        public static Dictionary<string, string> LoadSettings() { return ParseSettings(ReadLines(SettingsPath)); }
        public static bool SaveSettings(Dictionary<string, string> values) { return WriteLines(SettingsPath, SettingsLines(values)); }

        // ================================================================ logs

        public static string BuildInfo()
        {
            try
            {
                Assembly assembly = typeof(WsmCore).Assembly;
                string path = assembly.Location;
                string written = "";
                try { written = File.GetLastWriteTime(path).ToString("yyyy-MM-dd HH:mm:ss"); } catch (Exception) { }
                string date = "", revit = "";
                foreach (AssemblyMetadataAttribute meta in assembly.GetCustomAttributes(typeof(AssemblyMetadataAttribute), false))
                {
                    if (meta.Key == "BuildDate") date = meta.Value;
                    if (meta.Key == "RevitVersion") revit = meta.Value;
                }
                string info = assembly.GetName().Version == null ? "?" : assembly.GetName().Version.ToString(3);
                return "add-in " + info + " | built " + date + " | Revit " + revit + " build | " + path + " (written " + written + ")";
            }
            catch (Exception err) { return "build info unavailable: " + err.Message; }
        }

        /// <summary>Append one failure - where it happened and the traceback - to the error log, trimmed from the front.</summary>
        public static bool LogError(string where, string detail)
        {
            var entry = new List<string> { "==== " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  v" + Version + "  " + Txt(where) };
            entry.AddRange(Txt(detail).TrimEnd().Split('\n').Select(l => l.TrimEnd('\r')));
            var lines = ReadLines(ErrorPath);
            lines.AddRange(entry);
            lines.Add("");
            string text = string.Join("\n", lines);
            if (text.Length > ErrorLogLimit)
            {
                text = text.Substring(text.Length - ErrorLogLimit);
                int cut = text.IndexOf("==== ", StringComparison.Ordinal);
                if (cut >= 0) text = text.Substring(cut);
            }
            return WriteLines(ErrorPath, text.Split('\n'));
        }

        public static List<string> TailLines(string path, int count)
        {
            var lines = ReadLines(path);
            return count > 0 && lines.Count > count ? lines.GetRange(lines.Count - count, count) : lines;
        }

        public static List<string> ReportSection(string title, IEnumerable<string> lines)
        {
            var list = new List<string> { "", "---------------- " + Txt(title) };
            var body = lines == null ? new List<string>() : lines.Select(Txt).ToList();
            if (body.Count == 0) body.Add("(empty)");
            list.AddRange(body);
            return list;
        }

        /// <summary>Lines collected over a run; written out only when debug is on.</summary>
        public class Log
        {
            public bool Enabled;
            public readonly List<string> Lines = new List<string>();
            public Log(bool enabled = true) { Enabled = enabled; }

            public void Add(string text, params object[] args)
            {
                string line;
                try { line = args != null && args.Length > 0 ? string.Format(CultureInfo.InvariantCulture, Txt(text), args) : Txt(text); }
                catch (Exception) { line = Txt(text); }
                Lines.Add(line);
            }

            public bool Write(string header = "")
            {
                if (!Enabled) return false;
                var output = new List<string> { "RevoBIM - Workset Management v" + Version, BuildInfo() };
                if (!string.IsNullOrEmpty(header)) output.Add(header);
                output.AddRange(Lines);
                return WriteLines(DebugPath, output);
            }
        }

        // ================================================================ theme

        public static readonly string[] Themes = { "follow", "dark", "light" };

        public static string ThemeLabel(string name)
        {
            switch (NormaliseTheme(name))
            {
                case "dark": return "Dark";
                case "light": return "Light";
                default: return "Auto";
            }
        }

        public static readonly Dictionary<string, Dictionary<string, string>> Palettes = new Dictionary<string, Dictionary<string, string>>
        {
            { "dark", new Dictionary<string, string>
                {
                    { "WindowBrush", "#3C4454" }, { "CardBrush", "#353D4B" }, { "FieldBrush", "#2D3441" }, { "BarBrush", "#222933" },
                    { "EdgeBrush", "#4A5464" }, { "ChromeBrush", "#515C6B" }, { "TextBrush", "#EEF0F4" }, { "MutedBrush", "#ACB2B9" },
                    { "DisabledBrush", "#6E7684" }, { "BlueBrush", "#5AAEEB" }, { "BlueTextBrush", "#7CC0F2" }, { "OrangeBrush", "#E8912D" },
                    { "OrangeTextBrush", "#F2A452" }, { "GreenBrush", "#3FA75A" }, { "GreenHoverBrush", "#4EC06D" }, { "GreenTextBrush", "#5CC97A" },
                    { "RedBrush", "#F79A96" }, { "RedFillBrush", "#D9534F" }, { "RedSoftBrush", "#4E3842" }, { "OrangeSoftBrush", "#4E4434" },
                    { "SelectionBrush", "#3A7392" }, { "HoverBrush", "#444E5E" }, { "RowAltBrush", "#39414F" }, { "OnAccentBrush", "#101216" },
                    { "TickBrush", "#101216" }, { "ShadowBrush", "#66000000" },
                } },
            { "light", new Dictionary<string, string>
                {
                    { "WindowBrush", "#F3F3F5" }, { "CardBrush", "#FFFFFF" }, { "FieldBrush", "#FAFAFB" }, { "BarBrush", "#E6E6EA" },
                    { "EdgeBrush", "#C9C9CF" }, { "ChromeBrush", "#B4B4BC" }, { "TextBrush", "#1E1E22" }, { "MutedBrush", "#62626A" },
                    { "DisabledBrush", "#9A9AA2" }, { "BlueBrush", "#1B72BE" }, { "BlueTextBrush", "#165E9E" }, { "OrangeBrush", "#AD6310" },
                    { "OrangeTextBrush", "#8F4F08" }, { "GreenBrush", "#2E8546" }, { "GreenHoverBrush", "#2A7A41" }, { "GreenTextBrush", "#25703B" },
                    { "RedBrush", "#B3332A" }, { "RedFillBrush", "#C9443F" }, { "RedSoftBrush", "#FBE4E2" }, { "OrangeSoftBrush", "#FCEFDD" },
                    { "SelectionBrush", "#CFE3F5" }, { "HoverBrush", "#EEF2F7" }, { "RowAltBrush", "#F5F5F7" }, { "OnAccentBrush", "#FFFFFF" },
                    { "TickBrush", "#FFFFFF" }, { "ShadowBrush", "#33000000" },
                } },
        };

        public static string NormaliseTheme(string name)
        {
            string text = Txt(name).Trim().ToLowerInvariant();
            if (text == "auto" || text == "follow" || text == "") return "follow";
            if (Themes.Contains(text)) return text;
            return "follow";
        }

        public static string NextTheme(string name)
        {
            name = NormaliseTheme(name);
            return Themes[(Array.IndexOf(Themes, name) + 1) % Themes.Length];
        }

        /// <summary>setting follow|dark|light, canvas dark|light|null -> dark|light.</summary>
        public static string ResolveTheme(string setting, string canvas)
        {
            setting = NormaliseTheme(setting);
            if (setting == "dark" || setting == "light") return setting;
            if (canvas == "dark" || canvas == "light") return canvas;
            return "dark";
        }

        // ================================================================ drawer arithmetic

        public const double DrawerMs = 280.0;
        public const int DrawerTickMs = 15;
        public const int DrawerMargin = 8;
        public const int DrawerGap = 4;

        public static double EaseOut(double progress)
        {
            double p = Math.Max(0.0, Math.Min(1.0, progress));
            return 1.0 - Math.Pow(1.0 - p, 3);
        }

        public static double Lerp(double start, double end, double fraction) { return start + (end - start) * fraction; }

        public static int FreeSlot(IEnumerable<int> taken)
        {
            var set = new HashSet<int>(taken);
            int slot = 0;
            while (set.Contains(slot)) slot++;
            return slot;
        }

        public static double ParkedTop(double workTop, double workHeight, double barHeight, int slot)
        {
            double bottom = workTop + workHeight - DrawerMargin;
            return bottom - barHeight - slot * (barHeight + DrawerGap);
        }

        public static void OpenedPosition(double[] saved, double barLeft, double barTop, double barHeight, double[] parkedAt, double[] work,
                                          out double left, out double top)
        {
            left = saved[0]; top = saved[1];
            double width = saved[2], height = saved[3];
            bool moved = parkedAt == null || Math.Abs(barLeft - parkedAt[0]) > 2 || Math.Abs(barTop - parkedAt[1]) > 2;
            if (!moved) return;
            double newLeft = barLeft, newTop = barTop + barHeight - height;
            newLeft = Math.Min(newLeft, work[0] + work[2] - width);
            newLeft = Math.Max(newLeft, work[0]);
            newTop = Math.Min(newTop, work[1] + work[3] - height);
            newTop = Math.Max(newTop, work[1]);
            left = newLeft; top = newTop;
        }

        // ================================================================ names

        public static string NameProblem(string name)
        {
            string text = Txt(name);
            if (text.Trim().Length == 0) return "the name is blank";
            if (text.Length > MaxNameLength) return "the name is longer than " + MaxNameLength + " characters";
            foreach (char bad in BadNameChars)
                if (text.IndexOf(bad) >= 0) return "the name contains " + bad;
            return "";
        }

        private const string WordStart = " -_./(";

        public static string TitleCase(string text)
        {
            var sb = new StringBuilder();
            bool start = true;
            foreach (char c in Txt(text))
            {
                if (WordStart.IndexOf(c) >= 0) { sb.Append(c); start = true; continue; }
                sb.Append(start ? char.ToUpperInvariant(c) : char.ToLowerInvariant(c));
                start = false;
            }
            return sb.ToString();
        }

        /// <summary>The bulk rename operations on a name. Order: find/replace, remove characters, case, prefix and suffix, tidy.</summary>
        public class RenameOps
        {
            public string Find = "", Replace = "", Prefix = "", Suffix = "", Case = "keep";
            public bool MatchCase, Tidy;
            public int RemoveFirst, RemoveLast;
        }

        public static string RenameName(string name, RenameOps ops)
        {
            string text = Txt(name);
            if (!string.IsNullOrEmpty(ops.Find))
            {
                string replace = Txt(ops.Replace);
                if (ops.MatchCase) text = text.Replace(ops.Find, replace);
                else text = Regex.Replace(text, Regex.Escape(ops.Find), m => replace, RegexOptions.IgnoreCase);
            }
            int first = Math.Max(0, ops.RemoveFirst), last = Math.Max(0, ops.RemoveLast);
            if (first > 0) text = first >= text.Length ? "" : text.Substring(first);
            if (last > 0) text = last < text.Length ? text.Substring(0, text.Length - last) : "";
            string mode = Txt(ops.Case).ToLowerInvariant();
            if (mode == "upper") text = text.ToUpperInvariant();
            else if (mode == "lower") text = text.ToLowerInvariant();
            else if (mode == "title") text = TitleCase(text);
            text = Txt(ops.Prefix) + text + Txt(ops.Suffix);
            if (ops.Tidy) text = string.Join(" ", text.Split((char[])null, StringSplitOptions.RemoveEmptyEntries));
            return text;
        }

        public static bool OpsEmpty(RenameOps ops)
        {
            return string.IsNullOrEmpty(ops.Find) && string.IsNullOrEmpty(ops.Prefix) && string.IsNullOrEmpty(ops.Suffix) &&
                   ops.RemoveFirst == 0 && ops.RemoveLast == 0 && Txt(ops.Case).ToLowerInvariant() == "keep" && !ops.Tidy;
        }

        // ================================================================ filters

        private static readonly Regex NumExpr = new Regex(@"^\s*(>=|<=|<>|!=|>|<|=)?\s*(-?\d+)\s*$", RegexOptions.Compiled);
        private static readonly Regex NumRange = new Regex(@"^\s*(\d+)\s*(?:-|\.\.)\s*(\d+)\s*$", RegexOptions.Compiled);

        /// <summary>'&gt;0', '&lt;=10', '=0', '5', '10-50', '!=0'. Anything else is a substring.</summary>
        public static bool NumericMatch(int number, string expr)
        {
            expr = Txt(expr).Trim();
            if (expr.Length == 0) return true;
            Match m = NumRange.Match(expr);
            if (m.Success)
            {
                int low = int.Parse(m.Groups[1].Value), high = int.Parse(m.Groups[2].Value);
                if (low > high) { int t = low; low = high; high = t; }
                return number >= low && number <= high;
            }
            m = NumExpr.Match(expr);
            if (m.Success)
            {
                string op = m.Groups[1].Success && m.Groups[1].Value.Length > 0 ? m.Groups[1].Value : "=";
                int value = int.Parse(m.Groups[2].Value);
                switch (op)
                {
                    case ">": return number > value;
                    case "<": return number < value;
                    case ">=": return number >= value;
                    case "<=": return number <= value;
                    case "<>":
                    case "!=": return number != value;
                    default: return number == value;
                }
            }
            return number.ToString(CultureInfo.InvariantCulture).Contains(expr.ToLowerInvariant());
        }

        /// <summary>Every space separated word appears in value, case folded. A word starting with '-' must NOT appear.</summary>
        public static bool TextMatch(string value, string expr)
        {
            string[] words = Txt(expr).ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            if (words.Length == 0) return true;
            string hay = Txt(value).ToLowerInvariant();
            foreach (string word in words)
            {
                if (word.StartsWith("-") && word.Length > 1) { if (hay.Contains(word.Substring(1))) return false; }
                else if (!hay.Contains(word)) return false;
            }
            return true;
        }

        /// <summary>The Categories filter: every word must appear in ONE category name; '-word' rules out any category with that word.</summary>
        public static bool AnyWordMatches(IEnumerable<KeyValuePair<string, int>> categories, string expr)
        {
            string[] words = Txt(expr).ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            var wanted = words.Where(w => !(w.StartsWith("-") && w.Length > 1)).ToList();
            var banned = words.Where(w => w.StartsWith("-") && w.Length > 1).Select(w => w.Substring(1)).ToList();
            var names = categories.Select(c => Txt(c.Key).ToLowerInvariant()).ToList();
            foreach (string word in banned)
                if (names.Any(n => n.Contains(word))) return false;
            if (wanted.Count == 0) return true;
            return names.Any(n => wanted.All(w => n.Contains(w)));
        }

        // ================================================================ rows

        public const string StateNone = "", StateRename = "rename", StateNew = "new", StateDelete = "delete", StateMerge = "merge", StateError = "error";

        /// <summary>What GridTable needs of a row, workset or scope box.</summary>
        public abstract class StagedRow
        {
            public string Key = "";
            public string Orig = "";
            public string Name = "";
            public string DeleteTo;
            public bool Merge, IsNew;
            public string Problem = "";
            public abstract string State();
            public abstract bool Staged();
            public abstract string EffectiveName();
            public virtual bool Renamed() { return !IsNew && Name != Orig; }
        }

        public class WsRow : StagedRow
        {
            public int Iid;
            public int Count;
            public bool Editable = true, Visible = true, Active;
            public string Owner = "";
            public List<KeyValuePair<string, int>> Categories = new List<KeyValuePair<string, int>>();
            public string Colour = NoColour;

            public WsRow(string key, string name, int count = 0, bool editable = true, string owner = "", bool isNew = false, int iid = -1, bool active = false)
            {
                Key = key; Iid = iid; Orig = isNew ? "" : Txt(name); Name = Txt(name); Count = count; Editable = editable;
                Owner = Txt(owner); IsNew = isNew; Active = active;
            }

            public override bool Staged() { return IsNew || Renamed() || DeleteTo != null; }

            public override string State()
            {
                if (Problem.Length > 0) return StateError;
                if (DeleteTo != null) return Merge ? StateMerge : StateDelete;
                if (IsNew) return StateNew;
                if (Renamed()) return StateRename;
                return StateNone;
            }

            /// <summary>The name this workset will carry once Apply has run; one being deleted keeps its old name until it goes.</summary>
            public override string EffectiveName() { return DeleteTo != null ? Orig : Name; }
        }

        public static string Plural(int n, string one, string many) { return n == 1 ? one : many; }

        public static List<KeyValuePair<string, int>> CategoryBreakdown(Dictionary<string, int> counts)
        {
            var items = counts.Where(p => p.Value != 0).Select(p => new KeyValuePair<string, int>(Txt(p.Key).Length > 0 ? Txt(p.Key) : NoCategory, p.Value)).ToList();
            items = StableSort(items, (a, b) => NaturalCompare(a.Key, b.Key), false);
            return StableSort(items, (a, b) => a.Value.CompareTo(b.Value), true);
        }

        public static string CategorySummary(List<KeyValuePair<string, int>> categories, int limit = 3)
        {
            if (categories == null || categories.Count == 0) return "";
            var parts = categories.Take(limit).Select(c => c.Key + " " + c.Value).ToList();
            if (categories.Count > limit) parts.Add("+" + (categories.Count - limit) + " more");
            return string.Join("  Â·  ", parts);
        }

        public static readonly string[] Columns = { "name", "count", "cats", "editable", "visible", "owner", "change" };
        public static readonly Dictionary<string, string> ColumnTitles = new Dictionary<string, string>
        {
            { "name", "Workset" }, { "count", "Elements" }, { "editable", "Editable" }, { "visible", "Visible in all views" },
            { "owner", "Owner" }, { "change", "Change" }, { "cats", "Categories" },
        };
        public static readonly string[] NumericColumns = { "count" };
        public static readonly string[] TickColumns = { "editable", "visible", "owner", "change" };

        public static string RowValue(WsRow row, string column)
        {
            switch (column)
            {
                case "name": return row.Name;
                case "count": return row.Count.ToString(CultureInfo.InvariantCulture);
                case "cats": return CategorySummary(row.Categories);
                case "visible": return row.IsNew ? "" : (row.Visible ? "Yes" : "No");
                case "editable": return row.Editable ? "Yes" : "No";
                case "owner": return row.Owner.Length > 0 ? row.Owner : "(nobody)";
            }
            return "";
        }

        public static string ChangeText(WsRow row, Dictionary<string, StagedRow> byKey)
        {
            if (row.Problem.Length > 0) return "âš  " + row.Problem;
            if (row.DeleteTo != null)
            {
                StagedRow target;
                string targetName = byKey.TryGetValue(row.DeleteTo, out target) ? target.EffectiveName() : "?";
                string noun = row.Count == 1 ? "" : "s";
                if (row.Merge) return "Merge into " + targetName + " - move " + row.Count + " element" + noun;
                if (row.Count > 0) return "Delete - move " + row.Count + " element" + noun + " to " + targetName;
                return "Delete - it is empty";
            }
            if (row.IsNew) return "New workset";
            if (row.Renamed()) return "Rename from " + row.Orig;
            return "";
        }

        public static string TickValue(WsRow row, string column)
        {
            if (column == "change")
            {
                switch (row.State())
                {
                    case StateRename: return "Rename";
                    case StateNew: return "New";
                    case StateDelete: return "Delete";
                    case StateMerge: return "Merge";
                    case StateError: return "Needs a look";
                    default: return "(no change)";
                }
            }
            return RowValue(row, column);
        }

        public class Filters
        {
            public Dictionary<string, string> Text = new Dictionary<string, string>();
            public Dictionary<string, HashSet<string>> Ticks = new Dictionary<string, HashSet<string>>();
        }

        public static bool RowPasses(WsRow row, Filters f, Dictionary<string, StagedRow> byKey, string exclude = null)
        {
            foreach (var pair in f.Text)
            {
                if (pair.Key == exclude || Txt(pair.Value).Trim().Length == 0) continue;
                if (NumericColumns.Contains(pair.Key)) { if (!NumericMatch(row.Count, pair.Value)) return false; }
                else if (pair.Key == "change") { if (!TextMatch(ChangeText(row, byKey), pair.Value)) return false; }
                else if (pair.Key == "cats") { if (!AnyWordMatches(row.Categories, pair.Value)) return false; }
                else if (!TextMatch(RowValue(row, pair.Key), pair.Value)) return false;
            }
            foreach (var pair in f.Ticks)
            {
                if (pair.Key == exclude || pair.Value == null) continue;
                if (!pair.Value.Contains(TickValue(row, pair.Key))) return false;
            }
            return true;
        }

        public static List<string> TickChoices(IEnumerable<WsRow> rows, string column, Filters f, Dictionary<string, StagedRow> byKey)
        {
            var seen = new HashSet<string>();
            foreach (WsRow row in rows)
                if (RowPasses(row, f, byKey, column)) seen.Add(TickValue(row, column));
            return SortedNatural(seen);
        }

        public static List<WsRow> SortRows(IEnumerable<WsRow> rows, List<KeyValuePair<string, bool>> stack)
        {
            List<WsRow> ordered = StableSort(rows, (a, b) => NaturalCompare(a.Orig.Length > 0 ? a.Orig : a.Name, b.Orig.Length > 0 ? b.Orig : b.Name), false);
            for (int level = stack.Count - 1; level >= 0; level--)
            {
                string column = stack[level].Key; bool desc = stack[level].Value;
                if (NumericColumns.Contains(column)) ordered = StableSort(ordered, (a, b) => a.Count.CompareTo(b.Count), desc);
                else if (column == "cats") ordered = StableSort(ordered, (a, b) => a.Categories.Count.CompareTo(b.Categories.Count), desc);
                else if (column == "change") ordered = StableSort(ordered, (a, b) => NaturalCompare(TickValue(a, "change"), TickValue(b, "change")), desc);
                else ordered = StableSort(ordered, (a, b) => NaturalCompare(RowValue(a, column), RowValue(b, column)), desc);
            }
            return ordered;
        }

        /// <summary>A click on a heading. Plain: that column alone, flipping if it was the only level. Shift: add as a level, or flip it.</summary>
        public static List<KeyValuePair<string, bool>> PushSort(List<KeyValuePair<string, bool>> stack, string column, bool addLevel, int limit = 3)
        {
            var list = new List<KeyValuePair<string, bool>>(stack);
            for (int i = 0; i < list.Count; i++)
            {
                if (list[i].Key == column)
                {
                    if (addLevel || list.Count == 1) { list[i] = new KeyValuePair<string, bool>(column, !list[i].Value); return list; }
                    return new List<KeyValuePair<string, bool>> { new KeyValuePair<string, bool>(column, false) };
                }
            }
            if (addLevel && list.Count > 0)
            {
                if (list.Count >= limit) list = list.Take(limit - 1).ToList();
                list.Add(new KeyValuePair<string, bool>(column, false));
                return list;
            }
            return new List<KeyValuePair<string, bool>> { new KeyValuePair<string, bool>(column, false) };
        }

        /// <summary>Set Problem on every row that cannot be applied as staged. Returns the number of rows with a problem.</summary>
        public static int Validate(IList<WsRow> rows)
        {
            var byKey = rows.ToDictionary(r => r.Key);
            foreach (WsRow row in rows) row.Problem = "";
            var names = new Dictionary<string, List<WsRow>>();
            foreach (WsRow row in rows)
            {
                string key = row.EffectiveName().Trim().ToLowerInvariant();
                List<WsRow> list;
                if (!names.TryGetValue(key, out list)) names[key] = list = new List<WsRow>();
                list.Add(row);
            }
            if (rows.Count > 0 && rows.All(r => r.DeleteTo != null))
            {
                foreach (WsRow row in rows) row.Problem = "at least one workset has to stay";
                return rows.Count;
            }
            int problems = 0;
            foreach (WsRow row in rows)
            {
                if (row.DeleteTo != null)
                {
                    WsRow target;
                    if (!byKey.TryGetValue(row.DeleteTo, out target)) row.Problem = "the workset taking its elements has gone - pick another";
                    else if (target.DeleteTo != null) row.Problem = target.EffectiveName() + " takes its elements but is being deleted too";
                    if (row.Problem.Length > 0) problems++;
                    continue;
                }
                if (!(row.IsNew || row.Renamed())) continue;
                string problem = NameProblem(row.Name);
                if (problem.Length == 0)
                {
                    List<WsRow> clash;
                    if (names.TryGetValue(row.Name.Trim().ToLowerInvariant(), out clash) && clash.Count > 1)
                        problem = "another workset is already called " + row.Name.Trim();
                }
                if (problem.Length > 0) { row.Problem = problem; problems++; }
            }
            return problems;
        }

        /// <summary>[(key, old, new)] for the rows named whose name changes. Rows staged for deletion are left alone.</summary>
        public static List<Tuple<string, string, string>> BulkRenamePlan(IEnumerable<StagedRow> rows, IEnumerable<string> keys, RenameOps ops)
        {
            var wanted = new HashSet<string>(keys);
            var plan = new List<Tuple<string, string, string>>();
            foreach (StagedRow row in rows)
            {
                if (!wanted.Contains(row.Key) || row.DeleteTo != null) continue;
                string created = RenameName(row.Name, ops);
                if (created != row.Name) plan.Add(Tuple.Create(row.Key, row.Name, created));
            }
            return plan;
        }

        /// <summary>Stage the rows for deletion, their elements going to targetKey. A new (unapplied) workset is simply dropped.</summary>
        public static List<WsRow> StageDeletes(List<WsRow> rows, IEnumerable<string> keys, string targetKey, out string message)
        {
            var wanted = new HashSet<string>(keys);
            message = "";
            if (wanted.Contains(targetKey)) { message = "The workset taking the elements cannot be one being deleted."; return rows; }
            var kept = new List<WsRow>();
            foreach (WsRow row in rows)
            {
                if (wanted.Contains(row.Key))
                {
                    if (row.IsNew) continue;
                    row.Name = row.Orig; row.DeleteTo = targetKey; row.Merge = false;
                }
                kept.Add(row);
            }
            var left = new HashSet<string>(kept.Select(r => r.Key));
            foreach (WsRow row in kept)
                if (row.DeleteTo != null && !left.Contains(row.DeleteTo)) row.DeleteTo = null;
            return kept;
        }

        /// <summary>Undo whatever is staged on the rows named (all rows when keys is null). New rows are dropped.</summary>
        public static List<T> Revert<T>(IEnumerable<T> rows, ISet<string> keys = null) where T : StagedRow
        {
            var output = new List<T>();
            foreach (T row in rows)
            {
                if (keys != null && !keys.Contains(row.Key)) { output.Add(row); continue; }
                if (row.IsNew) continue;
                row.Name = row.Orig; row.DeleteTo = null; row.Merge = false;
                output.Add(row);
            }
            var left = new HashSet<string>(output.Select(r => r.Key));
            foreach (T row in output)
                if (row.DeleteTo != null && row.DeleteTo != ScopeDelete && !left.Contains(row.DeleteTo)) { row.DeleteTo = null; row.Merge = false; }
            return output;
        }

        /// <summary>Merge the rows named into masterKey: every other one moves its elements onto the master and goes.</summary>
        public static List<WsRow> StageMerge(List<WsRow> rows, IEnumerable<string> keys, string masterKey, out string message)
        {
            var wanted = new HashSet<string>(keys);
            message = "";
            if (!wanted.Contains(masterKey)) { message = "The master has to be one of the worksets being merged."; return rows; }
            if (wanted.Count < 2) { message = "Select at least two worksets to merge."; return rows; }
            var kept = new List<WsRow>();
            foreach (WsRow row in rows)
            {
                if (row.Key == masterKey) { row.DeleteTo = null; row.Merge = false; }
                else if (wanted.Contains(row.Key))
                {
                    if (row.IsNew) continue;
                    row.Name = row.Orig; row.DeleteTo = masterKey; row.Merge = true;
                }
                kept.Add(row);
            }
            return kept;
        }

        public static List<WsRow> DeleteTargets(IEnumerable<WsRow> rows, IEnumerable<string> deletingKeys)
        {
            var wanted = new HashSet<string>(deletingKeys);
            return rows.Where(r => !wanted.Contains(r.Key) && r.DeleteTo == null).ToList();
        }

        // ---------------------------------------------------------------- the plan

        public class DeleteItem
        {
            public int Iid; public string Name; public int Count; public int TargetIid; public string TargetName; public bool TargetNew; public bool Merge;
        }
        public class RenameItem { public int Iid; public string Old; public string New; }
        public class Plan
        {
            public List<string> Creates = new List<string>();
            public List<RenameItem> Renames = new List<RenameItem>();
            public List<DeleteItem> Deletes = new List<DeleteItem>();
            public int Count { get { return Creates.Count + Renames.Count + Deletes.Count; } }
        }

        public static Plan BuildPlan(IEnumerable<WsRow> rows)
        {
            var list = rows.ToList();
            var byKey = list.ToDictionary(r => r.Key);
            var plan = new Plan();
            foreach (WsRow row in list)
            {
                if (row.Problem.Length > 0) continue;
                if (row.DeleteTo != null)
                {
                    WsRow target;
                    if (!byKey.TryGetValue(row.DeleteTo, out target)) continue;
                    plan.Deletes.Add(new DeleteItem
                    {
                        Iid = row.Iid, Name = row.Orig, Count = row.Count, TargetIid = target.Iid,
                        TargetName = target.EffectiveName(), TargetNew = target.IsNew, Merge = row.Merge,
                    });
                }
                else if (row.IsNew) plan.Creates.Add(row.Name.Trim());
                else if (row.Renamed()) plan.Renames.Add(new RenameItem { Iid = row.Iid, Old = row.Orig, New = row.Name.Trim() });
            }
            return plan;
        }

        public static List<string> PlanLines(Plan plan)
        {
            var lines = new List<string>();
            foreach (string name in plan.Creates) lines.Add("Create   " + name);
            foreach (RenameItem item in plan.Renames) lines.Add("Rename   " + item.Old + "  ->  " + item.New);
            foreach (DeleteItem item in plan.Deletes)
            {
                if (item.Merge) lines.Add("Merge    " + item.Name + "  into  " + item.TargetName + "  (" + item.Count + " elements)");
                else lines.Add("Delete   " + item.Name + "  (" + item.Count + " elements to " + item.TargetName + ")");
            }
            return lines;
        }

        // ================================================================ spreadsheet diff

        public class SheetRow { public int Number; public string IdCell; public string NameCell; }
        public class ImportResult
        {
            public Dictionary<string, string> Renames = new Dictionary<string, string>();
            public List<string> Creates = new List<string>();
            public List<Tuple<string, string>> Skipped = new List<Tuple<string, string>>();
        }

        /// <summary>
        /// An id that matches a workset renames it when the name differs. A name in a row with no id is a new workset.
        /// Matching is on id, never on position or name, which is what tells a rename apart from a new workset.
        /// </summary>
        public static ImportResult ImportChanges(IEnumerable<SheetRow> sheetRows, IList<WsRow> rows)
        {
            var result = new ImportResult();
            var byIid = new Dictionary<int, WsRow>();
            foreach (WsRow row in rows) if (!row.IsNew) byIid[row.Iid] = row;
            var taken = new Dictionary<string, string>();
            foreach (WsRow row in rows) taken[row.EffectiveName().Trim().ToLowerInvariant()] = row.Key;
            var seenIds = new HashSet<int>();
            foreach (SheetRow sheet in sheetRows)
            {
                string idText = Txt(sheet.IdCell).Trim(), name = Txt(sheet.NameCell).Trim();
                if (idText.Length == 0 && name.Length == 0) continue;
                if (name == NewRowPlaceholder || name.StartsWith("<")) continue;
                int? iid = null;
                if (idText.Length > 0 && idText.ToUpperInvariant() != NewRowKey)
                {
                    double d;
                    if (double.TryParse(idText, NumberStyles.Float, CultureInfo.InvariantCulture, out d)) iid = (int)d;
                }
                WsRow match;
                if (iid.HasValue && byIid.TryGetValue(iid.Value, out match))
                {
                    if (seenIds.Contains(iid.Value)) { result.Skipped.Add(Tuple.Create(name, "row " + sheet.Number + ": that id appears twice")); continue; }
                    seenIds.Add(iid.Value);
                    if (name.Length == 0)
                    {
                        result.Skipped.Add(Tuple.Create(match.Orig, "row " + sheet.Number + ": the name cell was emptied - worksets are deleted from the table, not the spreadsheet"));
                        continue;
                    }
                    if (name == match.Orig) continue;
                    string problem = NameProblem(name);
                    string owner;
                    if (problem.Length == 0 && taken.TryGetValue(name.ToLowerInvariant(), out owner) && owner != match.Key)
                        problem = "another workset is already called " + name;
                    if (problem.Length > 0) { result.Skipped.Add(Tuple.Create(name, "row " + sheet.Number + ": " + problem)); continue; }
                    taken.Remove(match.EffectiveName().Trim().ToLowerInvariant());
                    taken[name.ToLowerInvariant()] = match.Key;
                    result.Renames[match.Key] = name;
                    continue;
                }
                if (iid.HasValue)
                {
                    result.Skipped.Add(Tuple.Create(name, "row " + sheet.Number + ": id " + iid.Value + " is not a workset in this model"));
                    continue;
                }
                if (name.Length == 0) continue;
                string newProblem = NameProblem(name);
                if (newProblem.Length == 0 && taken.ContainsKey(name.ToLowerInvariant())) newProblem = "a workset of that name already exists";
                if (newProblem.Length > 0) { result.Skipped.Add(Tuple.Create(name, "row " + sheet.Number + ": " + newProblem)); continue; }
                taken[name.ToLowerInvariant()] = "new";
                result.Creates.Add(name);
            }
            return result;
        }

        // ================================================================ assigner: the model scan

        public class CategoryEntry
        {
            public string Key, Label, ParentKey;
            public int Count;
            public List<CategoryEntry> Children = new List<CategoryEntry>();
            public List<object> ElementIds = new List<object>();    // Autodesk.Revit.DB.ElementId, kept as Revit gave them

            public CategoryEntry(string key, string label, int count = 0, string parentKey = null)
            {
                Key = key; Label = label; Count = count; ParentKey = parentKey;
            }
        }

        public class ModelScan
        {
            public List<CategoryEntry> Entries = new List<CategoryEntry>();
            public Dictionary<string, CategoryEntry> ByKey = new Dictionary<string, CategoryEntry>();
            public Dictionary<int, int> WorksetCounts = new Dictionary<int, int>();
            public Dictionary<int, Dictionary<string, int>> WorksetCategories = new Dictionary<int, Dictionary<string, int>>();
            public Dictionary<string, object> CategoryIds = new Dictionary<string, object>();
            public int Total;
            public string Error = "";

            public void Add(CategoryEntry entry)
            {
                ByKey[entry.Key] = entry;
                if (entry.ParentKey == null) Entries.Add(entry);
                else
                {
                    CategoryEntry parent;
                    if (ByKey.TryGetValue(entry.ParentKey, out parent)) parent.Children.Add(entry);
                }
            }

            public void Finish()
            {
                Entries = StableSort(Entries, (a, b) => NaturalCompare(a.Label, b.Label), false);
                foreach (CategoryEntry entry in Entries)
                    entry.Children = StableSort(entry.Children, (a, b) => NaturalCompare(a.Label, b.Label), false);
            }
        }

        public static HashSet<string> WithChildren(IEnumerable<string> selected, ModelScan scan)
        {
            var keys = new HashSet<string>();
            foreach (string key in selected)
            {
                keys.Add(key);
                CategoryEntry entry;
                if (scan.ByKey.TryGetValue(key, out entry))
                    foreach (CategoryEntry child in entry.Children) keys.Add(child.Key);
            }
            return keys;
        }

        public static Dictionary<string, string> BuildClaims(Dictionary<string, HashSet<string>> selections, ModelScan scan)
        {
            var claims = new Dictionary<string, string>();
            foreach (var pair in selections)
                foreach (string key in WithChildren(pair.Value, scan)) claims[key] = pair.Key;
            return claims;
        }

        public static bool FreeFor(Dictionary<string, string> claims, string workset, string key)
        {
            string holder;
            return !claims.TryGetValue(key, out holder) || holder == workset;
        }

        public class PickerLine { public CategoryEntry Entry; public int Depth; public bool Enabled; }

        /// <summary>
        /// What a workset's picker shows. A category another workset holds is not offered. A parent whose sub groups
        /// are partly held elsewhere stays, greyed, with only its free sub groups tickable.
        /// </summary>
        public static List<PickerLine> PickerLines(string workset, Dictionary<string, string> claims, ModelScan scan, string needle = "")
        {
            needle = Txt(needle).Trim().ToLowerInvariant();
            var output = new List<PickerLine>();
            foreach (CategoryEntry entry in scan.Entries)
            {
                if (!FreeFor(claims, workset, entry.Key)) continue;
                var children = entry.Children.Where(c => FreeFor(claims, workset, c.Key)).ToList();
                if (entry.Children.Count > 0 && children.Count == 0) continue;
                bool enabled = children.Count == entry.Children.Count;
                bool hitParent = needle.Length == 0 || entry.Label.ToLowerInvariant().Contains(needle);
                var hitChildren = children.Where(c => needle.Length == 0 || c.Label.ToLowerInvariant().Contains(needle)).ToList();
                if (!hitParent && hitChildren.Count == 0) continue;
                output.Add(new PickerLine { Entry = entry, Depth = 0, Enabled = enabled });
                foreach (CategoryEntry child in hitParent ? children : hitChildren)
                    output.Add(new PickerLine { Entry = child, Depth = 1, Enabled = true });
            }
            return output;
        }

        /// <summary>Tick or untick one line. Ticking a parent ticks all of its sub groups; unticking a sub group releases the parent.</summary>
        public static HashSet<string> Toggle(IEnumerable<string> selected, string key, bool ticked, ModelScan scan)
        {
            var result = new HashSet<string>(selected);
            CategoryEntry entry;
            scan.ByKey.TryGetValue(key, out entry);
            if (ticked) result.Add(key); else result.Remove(key);
            if (entry != null)
            {
                foreach (CategoryEntry child in entry.Children)
                {
                    if (ticked) result.Add(child.Key); else result.Remove(child.Key);
                }
                if (entry.ParentKey != null && !ticked) result.Remove(entry.ParentKey);
                if (entry.ParentKey != null && ticked)
                {
                    CategoryEntry parent;
                    if (scan.ByKey.TryGetValue(entry.ParentKey, out parent) && parent.Children.All(c => result.Contains(c.Key)))
                        result.Add(parent.Key);
                }
            }
            return result;
        }

        public static int SelectionCount(ISet<string> selected, ModelScan scan)
        {
            int count = 0;
            foreach (string key in selected)
            {
                CategoryEntry entry;
                if (scan.ByKey.TryGetValue(key, out entry) && entry.ParentKey != null && selected.Contains(entry.ParentKey)) continue;
                count++;
            }
            return count;
        }

        public static List<object> ElementIdsFor(ISet<string> selected, ModelScan scan)
        {
            var ids = new List<object>();
            foreach (string key in selected.OrderBy(k => k, StringComparer.Ordinal))
            {
                CategoryEntry entry;
                if (!scan.ByKey.TryGetValue(key, out entry)) continue;
                if (entry.ParentKey != null && selected.Contains(entry.ParentKey)) continue;
                ids.AddRange(entry.ElementIds);
            }
            return ids;
        }

        // ================================================================ colours

        private const double Golden = 0.6180339887498949;

        private static string HsvHex(double hue, double saturation, double value)
        {
            hue = hue - Math.Floor(hue);
            double h = hue * 6.0; int i = (int)Math.Floor(h); double f = h - i;
            double p = value * (1 - saturation), q = value * (1 - saturation * f), t = value * (1 - saturation * (1 - f));
            double r, g, b;
            switch (i % 6)
            {
                case 0: r = value; g = t; b = p; break;
                case 1: r = q; g = value; b = p; break;
                case 2: r = p; g = value; b = t; break;
                case 3: r = p; g = q; b = value; break;
                case 4: r = t; g = p; b = value; break;
                default: r = value; g = p; b = q; break;
            }
            return string.Format(CultureInfo.InvariantCulture, "#{0:X2}{1:X2}{2:X2}", (int)Math.Round(r * 255), (int)Math.Round(g * 255), (int)Math.Round(b * 255));
        }

        public static string DistinctColour(int index)
        {
            double hue = (0.07 + index * Golden) % 1.0;
            double saturation = new[] { 0.78, 0.58, 0.68 }[index % 3];
            double value = new[] { 0.92, 0.80, 0.70 }[(index / 3) % 3];
            return HsvHex(hue, saturation, value);
        }

        /// <summary>{workset id: '#RRGGBB'}, ordered by id so a workset keeps its colour while others are added.</summary>
        public static Dictionary<int, string> WorksetColours(IEnumerable<int> iids)
        {
            var ordered = iids.Where(i => i >= 0).Distinct().OrderBy(i => i).ToList();
            var map = new Dictionary<int, string>();
            for (int place = 0; place < ordered.Count; place++) map[ordered[place]] = DistinctColour(place);
            return map;
        }

        public static int[] HexRgb(string text)
        {
            text = Txt(text).TrimStart('#');
            if (text.Length != 6) return null;
            try
            {
                return new[] { Convert.ToInt32(text.Substring(0, 2), 16), Convert.ToInt32(text.Substring(2, 2), 16), Convert.ToInt32(text.Substring(4, 2), 16) };
            }
            catch (Exception) { return null; }
        }

        // ================================================================ routines (per project)

        private static string Esc(string text)
        {
            return Txt(text).Replace("%", "%25").Replace(";", "%3B").Replace("|", "%7C").Replace("=", "%3D");
        }

        private static string Unesc(string text)
        {
            return Txt(text).Replace("%3D", "=").Replace("%7C", "|").Replace("%3B", ";").Replace("%25", "%");
        }

        public static List<string> RoutineFileLines(Dictionary<string, Dictionary<string, List<string>>> routines)
        {
            var lines = new List<string> { "# RevoBIM - Workset Management saved routines" };
            foreach (string name in SortedNatural(routines.Keys))
            {
                var block = routines[name];
                foreach (string workset in SortedNatural(block.Keys))
                {
                    var keys = block[workset].Where(k => k.Length > 0).ToList();
                    if (keys.Count > 0)
                        lines.Add("routine|" + Esc(name) + "|" + Esc(workset) + "=" + string.Join(";", keys.Select(Esc)));
                }
            }
            return lines;
        }

        public static Dictionary<string, Dictionary<string, List<string>>> ParseRoutines(IEnumerable<string> lines)
        {
            var routines = new Dictionary<string, Dictionary<string, List<string>>>();
            foreach (string line in lines)
            {
                string text = Txt(line).Trim();
                if (text.Length == 0 || text.StartsWith("#") || !text.Contains("=")) continue;
                int at = text.IndexOf('=');
                string[] parts = text.Substring(0, at).Split('|');
                if (parts.Length != 3 || parts[0] != "routine") continue;
                string name = Unesc(parts[1]).Trim(), workset = Unesc(parts[2]).Trim();
                var keys = text.Substring(at + 1).Split(';').Where(k => k.Trim().Length > 0).Select(Unesc).ToList();
                if (name.Length > 0 && workset.Length > 0)
                {
                    Dictionary<string, List<string>> block;
                    if (!routines.TryGetValue(name, out block)) routines[name] = block = new Dictionary<string, List<string>>();
                    block[workset] = keys;
                }
            }
            return routines;
        }

        public static string ProjectKey(string title)
        {
            string name = Regex.Split(Txt(title), @"[\\/]").Last();
            if (name.Length == 0) name = "project";
            name = Regex.Replace(name, @"\.rvt$", "", RegexOptions.IgnoreCase);
            name = Regex.Replace(name, @"[^A-Za-z0-9_\-. ]+", "_").Trim();
            return name.Length > 0 ? name : "project";
        }

        // ================================================================ scope boxes

        public const string ScopeDelete = "delete";
        public static readonly string[] ScopeColumns = { "name", "used", "views", "datums", "usedby", "change" };
        public static readonly Dictionary<string, string> ScopeTitles = new Dictionary<string, string>
        {
            { "name", "Scope box" }, { "used", "Used" }, { "views", "Views" }, { "datums", "Levels & grids" },
            { "usedby", "Used by" }, { "change", "Change" },
        };
        public static readonly string[] ScopeNumeric = { "views", "datums" };
        public static readonly string[] ScopeTick = { "used", "change" };

        public class ScopeRow : StagedRow
        {
            public long Eid;
            public List<string> Views, Datums;
            public string Workset;

            public ScopeRow(long eid, string name, IEnumerable<string> views = null, IEnumerable<string> datums = null, string workset = "")
            {
                Key = "sb:" + eid; Eid = eid; Orig = Txt(name); Name = Txt(name);
                Views = SortedNatural(views ?? new string[0]); Datums = SortedNatural(datums ?? new string[0]);
                Workset = Txt(workset);
            }

            public bool Used() { return Views.Count > 0 || Datums.Count > 0; }
            public override bool Staged() { return Renamed() || DeleteTo != null; }
            public override bool Renamed() { return Name != Orig; }
            public override string EffectiveName() { return DeleteTo != null ? Orig : Name; }

            public override string State()
            {
                if (Problem.Length > 0) return StateError;
                if (DeleteTo != null) return StateDelete;
                if (Renamed()) return StateRename;
                return StateNone;
            }
        }

        public static string NameListSummary(IList<string> names, int limit = 2)
        {
            if (names.Count == 0) return "";
            string text = string.Join(", ", names.Take(limit));
            if (names.Count > limit) text += "  +" + (names.Count - limit) + " more";
            return text;
        }

        public static string ScopeUsedBy(ScopeRow row) { return NameListSummary(row.Views.Concat(row.Datums).ToList()); }

        public static string ScopeUsedFull(ScopeRow row)
        {
            var lines = new List<string>();
            if (row.Views.Count > 0)
            {
                lines.Add("Views (" + row.Views.Count + "):");
                lines.AddRange(row.Views.Select(n => "  " + n));
            }
            if (row.Datums.Count > 0)
            {
                lines.Add("Levels and grids (" + row.Datums.Count + "):");
                lines.AddRange(row.Datums.Select(n => "  " + n));
            }
            return lines.Count > 0 ? string.Join("\n", lines) : "Not used by any view, level or grid.";
        }

        public static string ScopeValue(ScopeRow row, string column)
        {
            switch (column)
            {
                case "name": return row.Name;
                case "used": return row.Used() ? "Yes" : "No";
                case "views": return row.Views.Count.ToString(CultureInfo.InvariantCulture);
                case "datums": return row.Datums.Count.ToString(CultureInfo.InvariantCulture);
                case "usedby": return ScopeUsedBy(row);
            }
            return "";
        }

        public static string ScopeChangeText(ScopeRow row)
        {
            if (row.Problem.Length > 0) return "âš  " + row.Problem;
            if (row.DeleteTo != null)
            {
                if (!row.Used()) return "Delete - not used";
                var parts = new List<string>();
                if (row.Views.Count > 0) parts.Add(row.Views.Count + " view" + (row.Views.Count == 1 ? "" : "s"));
                if (row.Datums.Count > 0) parts.Add(row.Datums.Count + " level/grid" + (row.Datums.Count == 1 ? "" : "s"));
                return "Delete - " + string.Join(" and ", parts) + " lose it";
            }
            if (row.Renamed()) return "Rename from " + row.Orig;
            return "";
        }

        public static string ScopeTickValue(ScopeRow row, string column)
        {
            if (column == "change")
            {
                switch (row.State())
                {
                    case StateRename: return "Rename";
                    case StateDelete: return "Delete";
                    case StateError: return "Needs a look";
                    default: return "(no change)";
                }
            }
            return ScopeValue(row, column);
        }

        public static bool ScopePasses(ScopeRow row, Filters f, string exclude = null)
        {
            foreach (var pair in f.Text)
            {
                if (pair.Key == exclude || Txt(pair.Value).Trim().Length == 0) continue;
                if (ScopeNumeric.Contains(pair.Key))
                {
                    if (!NumericMatch(AsInt(ScopeValue(row, pair.Key)), pair.Value)) return false;
                }
                else if (pair.Key == "usedby")
                {
                    var names = row.Views.Concat(row.Datums).Select(n => new KeyValuePair<string, int>(n, 1));
                    if (!AnyWordMatches(names, pair.Value)) return false;
                }
                else if (pair.Key == "change") { if (!TextMatch(ScopeChangeText(row), pair.Value)) return false; }
                else if (!TextMatch(ScopeValue(row, pair.Key), pair.Value)) return false;
            }
            foreach (var pair in f.Ticks)
            {
                if (pair.Key == exclude || pair.Value == null) continue;
                if (!pair.Value.Contains(ScopeTickValue(row, pair.Key))) return false;
            }
            return true;
        }

        public static List<string> ScopeTickChoices(IEnumerable<ScopeRow> rows, string column, Filters f)
        {
            var seen = new HashSet<string>();
            foreach (ScopeRow row in rows)
                if (ScopePasses(row, f, column)) seen.Add(ScopeTickValue(row, column));
            return SortedNatural(seen);
        }

        public static List<ScopeRow> ScopeSort(IEnumerable<ScopeRow> rows, List<KeyValuePair<string, bool>> stack)
        {
            List<ScopeRow> ordered = StableSort(rows, (a, b) => NaturalCompare(a.Orig, b.Orig), false);
            for (int level = stack.Count - 1; level >= 0; level--)
            {
                string column = stack[level].Key; bool desc = stack[level].Value;
                if (ScopeNumeric.Contains(column)) ordered = StableSort(ordered, (a, b) => AsInt(ScopeValue(a, column)).CompareTo(AsInt(ScopeValue(b, column))), desc);
                else if (column == "change") ordered = StableSort(ordered, (a, b) => NaturalCompare(ScopeTickValue(a, "change"), ScopeTickValue(b, "change")), desc);
                else ordered = StableSort(ordered, (a, b) => NaturalCompare(ScopeValue(a, column), ScopeValue(b, column)), desc);
            }
            return ordered;
        }

        /// <summary>Deletes run before renames, so a name freed by a delete can be taken in the same Apply.</summary>
        public static int ScopeValidate(IList<ScopeRow> rows)
        {
            foreach (ScopeRow row in rows) row.Problem = "";
            var names = new Dictionary<string, int>();
            foreach (ScopeRow row in rows)
            {
                if (row.DeleteTo != null) continue;
                string key = row.Name.Trim().ToLowerInvariant();
                int n; names.TryGetValue(key, out n); names[key] = n + 1;
            }
            int problems = 0;
            foreach (ScopeRow row in rows)
            {
                if (row.DeleteTo != null || !row.Renamed()) continue;
                string problem = NameProblem(row.Name);
                int n;
                if (problem.Length == 0 && names.TryGetValue(row.Name.Trim().ToLowerInvariant(), out n) && n > 1)
                    problem = "another scope box is already called " + row.Name.Trim();
                if (problem.Length > 0) { row.Problem = problem; problems++; }
            }
            return problems;
        }

        public static void ScopeStageDelete(IEnumerable<ScopeRow> rows, IEnumerable<string> keys)
        {
            var wanted = new HashSet<string>(keys);
            foreach (ScopeRow row in rows)
                if (wanted.Contains(row.Key)) { row.Name = row.Orig; row.DeleteTo = ScopeDelete; }
        }

        public class ScopeDeleteItem { public long Eid; public string Name; public int Views, Datums; }
        public class ScopeRenameItem { public long Eid; public string Old, New; }
        public class ScopePlan
        {
            public List<ScopeDeleteItem> Deletes = new List<ScopeDeleteItem>();
            public List<ScopeRenameItem> Renames = new List<ScopeRenameItem>();
            public int Count { get { return Deletes.Count + Renames.Count; } }
        }

        public static ScopePlan BuildScopePlan(IEnumerable<ScopeRow> rows)
        {
            var plan = new ScopePlan();
            foreach (ScopeRow row in rows)
            {
                if (row.Problem.Length > 0) continue;
                if (row.DeleteTo != null) plan.Deletes.Add(new ScopeDeleteItem { Eid = row.Eid, Name = row.Orig, Views = row.Views.Count, Datums = row.Datums.Count });
                else if (row.Renamed()) plan.Renames.Add(new ScopeRenameItem { Eid = row.Eid, Old = row.Orig, New = row.Name.Trim() });
            }
            return plan;
        }

        public static List<string> ScopePlanLines(ScopePlan plan)
        {
            var lines = new List<string>();
            foreach (ScopeDeleteItem item in plan.Deletes)
            {
                string used = item.Views > 0 || item.Datums > 0 ? "  - " + item.Views + " views and " + item.Datums + " levels/grids lose it" : "";
                lines.Add("Delete   " + item.Name + used);
            }
            foreach (ScopeRenameItem item in plan.Renames) lines.Add("Rename   " + item.Old + "  ->  " + item.New);
            return lines;
        }
    }
}


