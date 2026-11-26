using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using RevoBIM.Helpers;

namespace RevoBIM.Tools.CircuitManager
{
    /// <summary>One entry of the path mode menu: the API member name and the label shown in the table.</summary>
    public sealed class PathModeInfo
    {
        public string Name;
        public string Label;
    }

    /// <summary>
    /// Circuit Manager - pure rules (cm_logic.py): path mode names, lengths, typed and pasted values, filtering,
    /// sorting, staged edits, settings. No WPF and no Revit in here.
    /// </summary>
    public static class CmLogic
    {
        public const string Version = "1.0.1";
        public const string ToolName = "Circuit Manager";
        public const string ToolKey = "circuit_manager";

        public const double MmPerFoot = 304.8;
        public const double MaxOffsetFt = 30000.0;   // Revit refuses |PathOffset| above this

        // (API enum member name, label shown in the table) - order is menu order
        public static readonly PathModeInfo[] PathModes =
        {
            new PathModeInfo { Name = "FarthestDevice", Label = "Farthest Device" },
            new PathModeInfo { Name = "AllDevices", Label = "All Devices" },
            new PathModeInfo { Name = "Custom", Label = "Custom" },
        };

        private static readonly Regex Squasher = new Regex(@"[\s_\-]+");

        private static string Squash(string text)
        {
            return Squasher.Replace(text ?? "", "").ToLowerInvariant();
        }

        /// <summary>'FarthestDevice' to 'Farthest Device'. Unknown names pass through.</summary>
        public static string PathModeLabel(string apiName)
        {
            string key = Squash(apiName);
            foreach (PathModeInfo m in PathModes)
                if (Squash(m.Name) == key) return m.Label;
            return apiName ?? "";
        }

        /// <summary>Label, API name or a sensible abbreviation to the API member name, or null.</summary>
        public static string ParsePathMode(string text)
        {
            string key = Squash(text);
            if (key.Length == 0) return null;
            foreach (PathModeInfo m in PathModes)
                if (key == Squash(m.Name) || key == Squash(m.Label)) return m.Name;
            switch (key)
            {
                case "farthest":
                case "far":
                case "fd": return "FarthestDevice";
                case "all":
                case "ad":
                case "alldevice": return "AllDevices";
                case "cus":
                case "c": return "Custom";
            }
            return null;
        }

        /// <summary>Splits rows into those that can take the mode and those refused (Revit refuses Custom without a stored path).</summary>
        public static void ModeTargets(IEnumerable<int> rows, string mode, Dictionary<int, bool> customOk,
                                       out List<int> ok, out List<KeyValuePair<int, string>> refused)
        {
            ok = new List<int>();
            refused = new List<KeyValuePair<int, string>>();
            foreach (int r in rows)
            {
                bool has;
                if (mode == "Custom" && !(customOk.TryGetValue(r, out has) && has))
                    refused.Add(new KeyValuePair<int, string>(r, "no custom path stored - edit the path in Revit first"));
                else ok.Add(r);
            }
        }

        // ------------------------------------------------------------------ lengths
        public static string FormatMm(double? mm)
        {
            if (mm == null) return "";
            return mm.Value.ToString("0.0", CultureInfo.InvariantCulture);
        }

        public static string FeetToMmText(double? feet)
        {
            if (feet == null) return "";
            return FormatMm(feet.Value * MmPerFoot);
        }

        private static readonly Regex Num = new Regex(@"^[+-]?(\d+(\.\d*)?|\.\d+)$");

        /// <summary>'2750', '2,750.0 mm', ' 2750mm ' to 2750.0; metres with an explicit unit; null if not a length or one Revit would refuse.</summary>
        public static double? ParseMm(string text)
        {
            string t = (text ?? "").Trim().ToLowerInvariant().Replace(",", "").Replace(" ", "");
            if (t.Length == 0) return null;
            double scale = 1.0;
            if (t.EndsWith("mm", StringComparison.Ordinal)) t = t.Substring(0, t.Length - 2);
            else if (t.EndsWith("m", StringComparison.Ordinal))
            {
                t = t.Substring(0, t.Length - 1);
                scale = 1000.0;
            }
            if (!Num.IsMatch(t)) return null;
            double v;
            if (!double.TryParse(t, NumberStyles.Float, CultureInfo.InvariantCulture, out v)) return null;
            double mm = v * scale;
            if (Math.Abs(mm / MmPerFoot) > MaxOffsetFt) return null;
            return mm;
        }

        public static double MmToFeet(double mm)
        {
            return mm / MmPerFoot;
        }

        public static bool SameMm(string a, string b, double tol = 0.05)
        {
            double? x = ParseMm(a), y = ParseMm(b);
            if (x == null || y == null) return (a ?? "").Trim() == (b ?? "").Trim();
            return Math.Abs(x.Value - y.Value) <= tol;
        }

        // ------------------------------------------------------------------ typed or pasted values
        private static readonly string[] Yes = { "yes", "y", "true", "1", "on", "x" };
        private static readonly string[] No = { "no", "n", "false", "0", "off", "" };

        public static bool IsYes(string text)
        {
            return Yes.Contains((text ?? "").Trim().ToLowerInvariant());
        }

        /// <summary>Validates text for a column kind (pm path mode, po offset in mm, int, yesno, double, string). Returns the value or null with an error.</summary>
        public static string NormaliseInput(string kind, string text, out string error)
        {
            error = null;
            string t = (text ?? "").Trim();
            switch (kind)
            {
                case "pm":
                {
                    string name = ParsePathMode(t);
                    if (name == null)
                    {
                        error = "not a path mode";
                        return null;
                    }
                    return PathModeLabel(name);
                }
                case "po":
                {
                    double? mm = ParseMm(t);
                    if (mm == null)
                    {
                        error = "not a length in mm";
                        return null;
                    }
                    return FormatMm(mm);
                }
                case "yesno":
                {
                    string low = t.ToLowerInvariant();
                    if (Yes.Contains(low)) return "Yes";
                    if (No.Contains(low)) return "No";
                    error = "not yes / no";
                    return null;
                }
                case "int":
                {
                    if (Regex.IsMatch(t, @"^[+-]?\d+$"))
                    {
                        long n;
                        if (long.TryParse(t, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out n))
                            return n.ToString(CultureInfo.InvariantCulture);
                    }
                    error = "not a whole number";
                    return null;
                }
                case "double":
                    if (t.Length == 0)
                    {
                        error = "blank";
                        return null;
                    }
                    return t;
            }
            return text ?? "";
        }

        public static bool SameValue(string kind, string a, string b)
        {
            if (kind == "po") return SameMm(a, b);
            if (kind == "pm") return ParsePathMode(a) == ParsePathMode(b);
            return (a ?? "").Trim() == (b ?? "").Trim();
        }

        // ------------------------------------------------------------------ clipboard
        /// <summary>Excel's tab separated block to rows of cells; one trailing newline is not a blank row.</summary>
        public static List<string[]> ParseClipboard(string text)
        {
            string t = (text ?? "").Replace("\r\n", "\n").Replace("\r", "\n");
            if (t.EndsWith("\n", StringComparison.Ordinal)) t = t.Substring(0, t.Length - 1);
            var rows = new List<string[]>();
            if (t.Length == 0)
            {
                rows.Add(new[] { "" });
                return rows;
            }
            foreach (string line in t.Split('\n')) rows.Add(line.Split('\t'));
            return rows;
        }

        public static string ToClipboard(List<List<string>> block)
        {
            return string.Join("\r\n", block.Select(row => string.Join("\t", row))) + "\r\n";
        }

        /// <summary>Selected cells (row position, column position, text) to a rectangular block; gaps copy as blanks.</summary>
        public static List<List<string>> CopyBlock(List<Tuple<int, int, string>> cells)
        {
            var block = new List<List<string>>();
            if (cells.Count == 0) return block;
            List<int> rows = cells.Select(c => c.Item1).Distinct().OrderBy(x => x).ToList();
            List<int> cols = cells.Select(c => c.Item2).Distinct().OrderBy(x => x).ToList();
            var look = new Dictionary<Tuple<int, int>, string>();
            foreach (var c in cells) look[Tuple.Create(c.Item1, c.Item2)] = c.Item3;
            foreach (int r in rows)
            {
                var line = new List<string>();
                foreach (int c in cols)
                {
                    string v;
                    line.Add(look.TryGetValue(Tuple.Create(r, c), out v) ? v : "");
                }
                block.Add(line);
            }
            return block;
        }

        /// <summary>
        /// Where each pasted value goes: (row position, column position, text). One value copied fills every
        /// selected cell; a block is laid out from the top-left selected cell, walking the visible rows and columns.
        /// </summary>
        public static List<Tuple<int, int, string>> PastePlan(List<string[]> clip, List<Tuple<int, int>> selected,
                                                              List<int> rowPositions, List<int> colPositions)
        {
            var plan = new List<Tuple<int, int, string>>();
            if (selected.Count == 0 || clip.Count == 0) return plan;
            if (clip.Count == 1 && clip[0].Length == 1)
            {
                string value = clip[0][0];
                foreach (var rc in selected.Distinct().OrderBy(x => x.Item1).ThenBy(x => x.Item2))
                    plan.Add(Tuple.Create(rc.Item1, rc.Item2, value));
                return plan;
            }
            int top = selected.Min(x => x.Item1);
            int left = selected.Min(x => x.Item2);
            int r0 = rowPositions.IndexOf(top);
            int c0 = colPositions.IndexOf(left);
            if (r0 < 0 || c0 < 0) return plan;
            for (int i = 0; i < clip.Count; i++)
            {
                if (r0 + i >= rowPositions.Count) break;
                for (int j = 0; j < clip[i].Length; j++)
                {
                    if (c0 + j >= colPositions.Count) break;
                    plan.Add(Tuple.Create(rowPositions[r0 + i], colPositions[c0 + j], clip[i][j]));
                }
            }
            return plan;
        }

        // ------------------------------------------------------------------ filtering and sorting
        public static bool MatchesText(string value, string term)
        {
            return RevoChrome.MatchesText(value, term);
        }

        public static bool RowVisible(Dictionary<string, string> values, Dictionary<string, string> textFilters,
                                      Dictionary<string, HashSet<string>> tickFilters, string exclude = null)
        {
            foreach (var entry in textFilters)
            {
                if (entry.Key == exclude) continue;
                string v;
                values.TryGetValue(entry.Key, out v);
                if (!MatchesText(v ?? "", entry.Value)) return false;
            }
            foreach (var entry in tickFilters)
            {
                if (entry.Key == exclude || entry.Value == null) continue;
                string v;
                values.TryGetValue(entry.Key, out v);
                if (!entry.Value.Contains(v ?? "")) return false;
            }
            return true;
        }

        /// <summary>Values for a column's tick list: what the OTHER filters allow.</summary>
        public static List<string> ListValues(IEnumerable<Dictionary<string, string>> rowsValues, string key,
                                              Dictionary<string, string> textFilters, Dictionary<string, HashSet<string>> tickFilters)
        {
            var seen = new HashSet<string>();
            foreach (var values in rowsValues)
            {
                if (RowVisible(values, textFilters, tickFilters, key))
                {
                    string v;
                    values.TryGetValue(key, out v);
                    seen.Add(v ?? "");
                }
            }
            var list = seen.ToList();
            list.Sort((a, b) => NaturalCompare(a, b));
            return list;
        }

        public static bool IsFiltered(string key, Dictionary<string, string> textFilters, Dictionary<string, HashSet<string>> tickFilters)
        {
            string t;
            textFilters.TryGetValue(key, out t);
            HashSet<string> tick;
            tickFilters.TryGetValue(key, out tick);
            return (t ?? "").Trim().Length > 0 || tick != null;
        }

        private static readonly Regex Chunk = new Regex(@"(\d+(?:\.\d+)?)");

        /// <summary>P-9 &lt; P-10 &lt; P-100: numbers compare as numbers, text case-blind.</summary>
        public static int NaturalCompare(string a, string b)
        {
            List<Tuple<int, double, string>> ka = NaturalKey(a), kb = NaturalKey(b);
            int n = Math.Min(ka.Count, kb.Count);
            for (int i = 0; i < n; i++)
            {
                int c = ka[i].Item1.CompareTo(kb[i].Item1);
                if (c != 0) return c;
                c = ka[i].Item2.CompareTo(kb[i].Item2);
                if (c != 0) return c;
                c = string.CompareOrdinal(ka[i].Item3, kb[i].Item3);
                if (c != 0) return c;
            }
            return ka.Count.CompareTo(kb.Count);
        }

        private static List<Tuple<int, double, string>> NaturalKey(string value)
        {
            var key = new List<Tuple<int, double, string>>();
            foreach (string part in Chunk.Split((value ?? "").ToLowerInvariant()))
            {
                if (part.Length == 0) continue;
                if (Chunk.IsMatch(part) && Chunk.Match(part).Value == part)
                    key.Add(Tuple.Create(0, double.Parse(part, CultureInfo.InvariantCulture), ""));
                else key.Add(Tuple.Create(1, 0.0, part));
            }
            return key;
        }

        /// <summary>Indices of the rows in display order (stable, natural).</summary>
        public static List<int> SortOrder(List<Dictionary<string, string>> rowsValues, string key, bool descending)
        {
            List<int> idx = Enumerable.Range(0, rowsValues.Count).ToList();
            Comparison<int> cmp = (x, y) =>
            {
                string a, b;
                rowsValues[x].TryGetValue(key, out a);
                rowsValues[y].TryGetValue(key, out b);
                int c = NaturalCompare(a, b);
                return descending ? -c : c;
            };
            return StableSort(idx, cmp);
        }

        /// <summary>LINQ's OrderBy is stable, so equal rows keep the order they came in.</summary>
        public static List<int> StableSort(List<int> items, Comparison<int> cmp)
        {
            return items.OrderBy(i => i, Comparer<int>.Create(cmp)).ToList();
        }
        // ------------------------------------------------------------------ settings
        public const int SettingsVersion = 1;

        public static Dictionary<string, string> Defaults()
        {
            return new Dictionary<string, string>
            {
                { "settings_version", SettingsVersion.ToString(CultureInfo.InvariantCulture) },
                { "theme", "follow" },
                { "columns", "" },
                { "sort_key", "panel" },
                { "sort_desc", "0" },
                { "debug", "1" },
                { "open_note", "" },
            };
        }

        public static Dictionary<string, string> ParseSettings(string text)
        {
            Dictionary<string, string> result = Defaults();
            foreach (string raw in (text ?? "").Replace("\r\n", "\n").Split('\n'))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal) || line.IndexOf('=') < 0) continue;
                int eq = line.IndexOf('=');
                result[line.Substring(0, eq).Trim()] = line.Substring(eq + 1).Trim();
            }
            result["settings_version"] = SettingsVersion.ToString(CultureInfo.InvariantCulture);
            return result;
        }

        public static string DumpSettings(Dictionary<string, string> settings)
        {
            var sb = new StringBuilder();
            foreach (string k in settings.Keys.OrderBy(x => x, StringComparer.Ordinal))
                sb.Append(k).Append('=').Append((settings[k] ?? "").Replace("\n", " ")).Append('\n');
            return sb.ToString();
        }

        public static List<string> SplitColumns(string text)
        {
            return (text ?? "").Split('|').Where(c => c.Trim().Length > 0).ToList();
        }

        public static string JoinColumns(IEnumerable<string> keys)
        {
            return string.Join("|", keys);
        }
    }

    /// <summary>
    /// Staged edits, keyed by (element id, column key) - never by cell position - so they survive sorting,
    /// filtering and column rebuilds. Undo is per batch: a paste into forty cells is one Ctrl+Z.
    /// </summary>
    public sealed class CmStage
    {
        public readonly Dictionary<Tuple<long, string>, string> Edits = new Dictionary<Tuple<long, string>, string>();
        private readonly List<List<KeyValuePair<Tuple<long, string>, string>>> undo = new List<List<KeyValuePair<Tuple<long, string>, string>>>();

        public int Count
        {
            get { return Edits.Count; }
        }

        public bool CanUndo
        {
            get { return undo.Count > 0; }
        }

        public string Get(long eid, string key)
        {
            string v;
            return Edits.TryGetValue(Tuple.Create(eid, key), out v) ? v : null;
        }

        public bool Has(long eid, string key)
        {
            return Edits.ContainsKey(Tuple.Create(eid, key));
        }

        /// <summary>A value equal to the model's original unstages that cell. Returns the cells whose state moved.</summary>
        public List<Tuple<long, string>> ApplyBatch(IEnumerable<Tuple<long, string, string>> changes,
                                                    Dictionary<Tuple<long, string>, string> originals, Dictionary<string, string> kinds)
        {
            var before = new List<KeyValuePair<Tuple<long, string>, string>>();
            var touched = new List<Tuple<long, string>>();
            foreach (var ch in changes)
            {
                var k = Tuple.Create(ch.Item1, ch.Item2);
                string old;
                Edits.TryGetValue(k, out old);
                before.Add(new KeyValuePair<Tuple<long, string>, string>(k, old));
                string orig;
                originals.TryGetValue(k, out orig);
                string kind;
                if (!kinds.TryGetValue(ch.Item2, out kind)) kind = "string";
                if (CmLogic.SameValue(kind, ch.Item3, orig ?? ""))
                    Edits.Remove(k);
                else Edits[k] = ch.Item3;
                touched.Add(k);
            }
            if (touched.Count > 0) undo.Add(before);
            return touched;
        }

        public List<Tuple<long, string>> UndoLast()
        {
            var touched = new List<Tuple<long, string>>();
            if (undo.Count == 0) return touched;
            List<KeyValuePair<Tuple<long, string>, string>> batch = undo[undo.Count - 1];
            undo.RemoveAt(undo.Count - 1);
            for (int i = batch.Count - 1; i >= 0; i--)
            {
                if (batch[i].Value == null) Edits.Remove(batch[i].Key);
                else Edits[batch[i].Key] = batch[i].Value;
                touched.Add(batch[i].Key);
            }
            return touched;
        }

        public List<Tuple<long, string>> Clear(IEnumerable<Tuple<long, string>> keys = null)
        {
            List<Tuple<long, string>> touched;
            if (keys == null)
            {
                touched = Edits.Keys.ToList();
                Edits.Clear();
            }
            else
            {
                touched = keys.Where(k => Edits.ContainsKey(k)).ToList();
                foreach (var k in touched) Edits.Remove(k);
            }
            undo.Clear();
            return touched;
        }

        /// <summary>Per element: path mode first, then offset, then the rest - a mode change can reset the offset.</summary>
        public Dictionary<long, List<KeyValuePair<string, string>>> ByElement()
        {
            var output = new Dictionary<long, List<KeyValuePair<string, string>>>();
            foreach (var entry in Edits)
            {
                List<KeyValuePair<string, string>> list;
                if (!output.TryGetValue(entry.Key.Item1, out list))
                {
                    list = new List<KeyValuePair<string, string>>();
                    output[entry.Key.Item1] = list;
                }
                list.Add(new KeyValuePair<string, string>(entry.Key.Item2, entry.Value));
            }
            foreach (long eid in output.Keys.ToList())
            {
                output[eid] = output[eid].OrderBy(kv => kv.Key == "pm" ? 0 : kv.Key == "po" ? 1 : 2)
                                         .ThenBy(kv => kv.Key, StringComparer.Ordinal).ToList();
            }
            return output;
        }
    }
}
