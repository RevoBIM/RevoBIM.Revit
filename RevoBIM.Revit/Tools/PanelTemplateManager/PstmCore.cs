using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.PanelTemplateManager
{
    /// <summary>One line of the rename preview: the name now, the name after, and a note where the result would clash or be empty.</summary>
    public sealed class RenamePreviewRow
    {
        public string Old, New, Note;

        public string Value(string key)
        {
            if (key == "old") return Old;
            if (key == "new") return New;
            return Note;
        }
    }

    /// <summary>
    /// Panel Template Mngr - version, settings and pure helpers (pstm_core.py): names, numbers, Auto Assign maths, slot lists.
    /// </summary>
    public static class PstmCore
    {
        public const string Version = "1.10.0";
        public const string ToolName = "Panel Template Mngr";

        // ------------------------------------------------------------------ names
        /// <summary>A name not already in taken (lower case names). A clash gets "New" on the end, then "New 2" and so on.</summary>
        public static string UniqueName(string baseName, ISet<string> taken)
        {
            if (!taken.Contains(baseName.ToLowerInvariant())) return baseName;
            string candidate = baseName + " New";
            int n = 2;
            while (taken.Contains(candidate.ToLowerInvariant()))
            {
                candidate = baseName + " New " + n;
                n++;
            }
            return candidate;
        }

        private static readonly Regex NumberRe = new Regex(@"\d+");

        public static List<int> NumbersIn(string text)
        {
            var list = new List<int>();
            if (string.IsNullOrEmpty(text)) return list;
            foreach (Match m in NumberRe.Matches(text))
            {
                int v;
                if (int.TryParse(m.Value, NumberStyles.None, CultureInfo.InvariantCulture, out v)) list.Add(v);
            }
            return list;
        }

        /// <summary>The slot count a template name is advertising: largest number (default), first, or a number followed by the keyword.</summary>
        public static int? ExtractTemplateNumber(string name, string rule = "largest", string keyword = "way")
        {
            if (string.IsNullOrEmpty(name)) return null;
            rule = (rule ?? "largest").ToLowerInvariant();
            if (rule == "keyword")
            {
                string kw = Regex.Escape(string.IsNullOrWhiteSpace(keyword) ? "way" : keyword.Trim());
                Match m = Regex.Match(name, @"(\d+)\s*" + kw, RegexOptions.IgnoreCase);
                int v;
                if (m.Success && int.TryParse(m.Groups[1].Value, NumberStyles.None, CultureInfo.InvariantCulture, out v)) return v;
                return null;
            }
            List<int> nums = NumbersIn(name);
            if (nums.Count == 0) return null;
            if (rule == "first") return nums[0];
            return nums.Max();
        }

        private static readonly Regex WaysSuffixRe = new Regex(@"[\s_-]*\d+\s*ways?\s*$", RegexOptions.IgnoreCase);
        // not \bmaster\b: an underscore is a word character, so \b never fires in "BGL_Master_One Column"
        private static readonly Regex MasterRe = new Regex(@"(?<![A-Za-z0-9])master(?![A-Za-z0-9])", RegexOptions.IgnoreCase);
        private static readonly Regex GapRe = new Regex(@"\s{2,}");

        /// <summary>Takes the whole word "Master" out of a name and tidies the separators left over.</summary>
        public static string DropMaster(string text)
        {
            text = text ?? "";
            int hits = MasterRe.Matches(text).Count;
            if (hits == 0) return text;   // nothing taken out, so nothing needs tidying
            string output = MasterRe.Replace(text, "");
            output = Regex.Replace(output, @"\(\s*\)|\[\s*\]", "");
            output = Regex.Replace(output, @"[\s_-]*([_-])[\s_-]*", "$1");
            output = GapRe.Replace(output, " ");
            return output.Trim(' ', '_', '-');
        }

        /// <summary>A duplicate's name: the source's with "&lt;n&gt; Ways" on the end, an existing ways suffix replaced, "Master" removed.</summary>
        public static string NameWithWays(string baseName, int ways)
        {
            string stem = WaysSuffixRe.Replace(baseName ?? "", "").TrimEnd();
            stem = DropMaster(stem);
            return stem + " " + ways + " Ways";
        }

        public static string RenameFindReplace(string name, string find, string replace, bool matchCase = false)
        {
            string text = name ?? "";
            if (string.IsNullOrEmpty(find)) return text;
            if (matchCase) return text.Replace(find, replace ?? "");
            return Regex.Replace(text, Regex.Escape(find), m => replace ?? "", RegexOptions.IgnoreCase);
        }

        public static string RenameAffix(string name, string prefix = "", string suffix = "")
        {
            return (prefix ?? "") + (name ?? "") + (suffix ?? "");
        }

        /// <summary>What a rename would do, before anything is written. A note is set where the result would clash or be empty.</summary>
        public static List<RenamePreviewRow> PreviewRename(IEnumerable<string> names, string find = "", string replace = "", bool matchCase = false,
                                                           string prefix = "", string suffix = "", bool stripMaster = false)
        {
            var output = new List<RenamePreviewRow>();
            var seen = new Dictionary<string, string>();
            foreach (string name in names)
            {
                string nw = name ?? "";
                if (stripMaster) nw = DropMaster(nw);
                if (!string.IsNullOrEmpty(find)) nw = RenameFindReplace(nw, find, replace, matchCase);
                nw = RenameAffix(nw, prefix, suffix).Trim();
                string note = "";
                string lower = nw.ToLowerInvariant();
                string other;
                if (nw.Length == 0) note = "that would leave it with no name";
                else if (seen.TryGetValue(lower, out other) && other != name) note = "clashes with \"" + other + "\"";
                else seen[lower] = name;
                output.Add(new RenamePreviewRow { Old = name, New = nw, Note = note });
            }
            return output;
        }

        // ------------------------------------------------------------------ Auto Assign maths
        /// <summary>The way terms in a value like '12', '8+8' or '8 + 4 ways'.</summary>
        public static List<int> ParseWays(string text)
        {
            return NumbersIn(text);
        }

        /// <summary>
        /// Ways x phases: every term in the ways value is added up first, then multiplied by the number of phases ('12 ways' on
        /// 3 phases is 36 slots, '8+8 ways' on 3 phases is 48). Returns null slots with a note when it cannot be worked out.
        /// </summary>
        public static int? CalcSlots(string waysText, int? phases, out string note)
        {
            note = "";
            List<int> terms = ParseWays(waysText);
            if (terms.Count == 0)
            {
                note = "no number in the ways parameter";
                return null;
            }
            if (phases == null)
            {
                note = "no number in the phases parameter";
                return null;
            }
            if (phases.Value <= 0)
            {
                note = "phases is zero";
                return null;
            }
            return terms.Sum() * phases.Value;
        }

        public const int SlotsPerWayThreePhase = 3;

        /// <summary>Three slots per way on a three phase board, one on a single phase board.</summary>
        public static int SlotsPerWay(bool singlePhase)
        {
            return singlePhase ? 1 : SlotsPerWayThreePhase;
        }

        public static int WaysFromSlots(int slots, int? perWay = null)
        {
            int step = perWay ?? SlotsPerWayThreePhase;
            if (step <= 0) return 0;
            return slots / step;
        }

        // ------------------------------------------------------------------ settings
        public static Dictionary<string, string> Defaults()
        {
            return new Dictionary<string, string>
            {
                { "theme", "dark" },
                { "ways_param", "BGL_Number of Ways" },
                { "phases_param", "BGL_Number of Phases" },
                { "phases_fallback", "3" },
                { "name_number_rule", "largest" },
                { "name_number_keyword", "way" },
                { "default_config", "OneColumn" },
                { "default_schedule_type", "Branch Panel" },
                // a pipe separated list, so there can be as many columns as wanted
                { "columns", "" },
                { "slot_step", "3" },
                { "slot_min", "3" },
                { "slot_max", "120" },
                { "match_schedule_type", "1" },
                { "confirm_apply", "1" },
                { "rebuild_schedule", "1" },
                { "window_width", "1280" },
                { "window_height", "760" },
            };
        }

        public static string SettingsDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        /// <summary>Deliberately still the old long name: renaming it would have quietly thrown away everybody's chosen parameters and columns.</summary>
        public static string SettingsPath()
        {
            return Path.Combine(SettingsDir(), "panel_schedule_template_manager.txt");
        }

        public static Dictionary<string, string> LoadSettings()
        {
            Dictionary<string, string> values = Defaults();
            try
            {
                if (File.Exists(SettingsPath()))
                {
                    foreach (string raw in File.ReadAllLines(SettingsPath(), Encoding.UTF8))
                    {
                        string line = raw.Trim();
                        if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal) || line.IndexOf('=') < 0) continue;
                        int eq = line.IndexOf('=');
                        string key = line.Substring(0, eq).Trim();
                        // keys from an older version are ignored, not fatal
                        if (values.ContainsKey(key)) values[key] = line.Substring(eq + 1).Trim();
                    }
                }
            }
            catch (Exception)
            {
                return Defaults();
            }
            return values;
        }

        public static bool SaveSettings(Dictionary<string, string> values)
        {
            try
            {
                Directory.CreateDirectory(SettingsDir());
                var sb = new StringBuilder();
                sb.Append("# RevoBIM PY - Panel Template Mngr\n");
                sb.Append("# version ").Append(Version).Append('\n');
                Dictionary<string, string> defaults = Defaults();
                foreach (string key in defaults.Keys.OrderBy(k => k, StringComparer.Ordinal))
                {
                    string v;
                    sb.Append(key).Append('=').Append(values.TryGetValue(key, out v) ? v : defaults[key]).Append('\n');
                }
                File.WriteAllText(SettingsPath(), sb.ToString(), new UTF8Encoding(false));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static string Get(Dictionary<string, string> settings, string key)
        {
            string v;
            if (settings.TryGetValue(key, out v)) return v;
            string d;
            return Defaults().TryGetValue(key, out d) ? d : "";
        }

        public static int AsInt(string value, int fallback = 0)
        {
            int n;
            return int.TryParse((value ?? "").Trim(), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out n) ? n : fallback;
        }

        public static bool AsBool(string value, bool fallback = false)
        {
            string text = (value ?? "").Trim().ToLowerInvariant();
            if (text == "1" || text == "true" || text == "yes" || text == "on") return true;
            if (text == "0" || text == "false" || text == "no" || text == "off") return false;
            return fallback;
        }

        /// <summary>The parameter columns the table opens with (blank means not chosen yet: ways and phases from Settings come first).</summary>
        public static List<string> InitialColumns(Dictionary<string, string> settings)
        {
            string raw = Get(settings, "columns");
            List<string> names = raw.Length > 0 ? raw.Split('|').ToList() : new List<string>();
            if (names.Count == 0)
                names = new List<string> { Get(settings, "ways_param"), Get(settings, "phases_param"), "", "" };
            while (names.Count < 2) names.Add("");
            return names;
        }

        /// <summary>Saving Settings repoints the first two columns at ways and phases.</summary>
        public static List<string> ColumnsAfterSettings(List<string> names, Dictionary<string, string> settings)
        {
            names = names.ToList();
            while (names.Count < 2) names.Add("");
            string ways = Get(settings, "ways_param"), phases = Get(settings, "phases_param");
            names[0] = ways.Length > 0 ? ways : names[0];
            names[1] = phases.Length > 0 ? phases : names[1];
            return names;
        }

        /// <summary>
        /// The slot counts the duplicator offers. Three phase: multiples of the Settings step. Single phase: every whole number from 1,
        /// since a way is one slot there and the Settings minimum is written in slots for three phase boards.
        /// </summary>
        public static List<int> SlotOptions(Dictionary<string, string> settings, int? perWay = null)
        {
            int step = perWay ?? Math.Max(1, AsInt(Get(settings, "slot_step"), 3));
            step = Math.Max(1, step);
            int low = AsInt(Get(settings, "slot_min"), 3);
            if (step == 1) low = 1;
            low = Math.Max(step, low);
            int high = Math.Max(low, AsInt(Get(settings, "slot_max"), 120));
            int first = ((low + step - 1) / step) * step;
            var output = new List<int>();
            for (int n = first; n <= high; n += step) output.Add(n);
            return output;
        }

        // ------------------------------------------------------------------ the debug log
        private static bool logStarted;

        public static string LogPath()
        {
            return Path.Combine(SettingsDir(), "panel_template_mngr_debug.txt");
        }

        public static string ErrorPath()
        {
            return Path.Combine(SettingsDir(), "pstm_last_error.txt");
        }

        public static string BuildInfo()
        {
            return ToolName + " v" + Version + ", build " + typeof(PstmCore).Assembly.GetName().Version;
        }

        /// <summary>One compact line per step; the file opens with a build line each session.</summary>
        public static void Log(string text)
        {
            try
            {
                Directory.CreateDirectory(SettingsDir());
                var sb = new StringBuilder();
                if (!logStarted)
                {
                    logStarted = true;
                    sb.Append("---- ").Append(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)).Append("  ").Append(BuildInfo()).Append('\n');
                }
                sb.Append(DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture)).Append(' ').Append(text).Append('\n');
                File.AppendAllText(LogPath(), sb.ToString(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }
}
