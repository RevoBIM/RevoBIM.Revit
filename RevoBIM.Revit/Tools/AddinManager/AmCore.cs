using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.AddinManager
{
    /// <summary>
    /// Addin Manager: version, settings, paths, debug log and the pure helpers (search, ordering, dock and
    /// drag arithmetic). Port of rba_core.py. No WPF and no Revit API in here.
    /// </summary>
    internal static class AmCore
    {
        public const string Version = "1.1.7";
        public const string ToolName = "Addin Manager";
        public const string SettingsName = "addin_manager.txt";
        public const string DebugName = "addin_manager_debug.txt";
        public const string ErrorName = "addin_manager_last_error.txt";

        /// <summary>The dockable pane GUID. Fixed for the life of the tool: Revit keys the user's docking layout off it.</summary>
        public static readonly Guid PaneGuid = new Guid("0C5E9A47-31B8-4D62-A7F4-6B2E8D1C93A5");

        /// <summary>Between the parts of an addin's key. Never the list separator.</summary>
        public const string KeySep = "::";
        /// <summary>Between the entries of a saved list.</summary>
        public const char ListSep = '|';

        public static readonly int[] IconSizes = { 16, 24, 32, 48, 64 };

        public const int FavGrow = 12;
        public const int FavMinIcon = 32;
        public const double FavDragPx = 5;
        public const int FavHoldMs = 320;

        public static readonly Dictionary<string, string> Defaults = new Dictionary<string, string>
        {
            { "settings_version", "1" },
            { "theme", "auto" },          // auto | dark | light
            { "icon_size", "32" },        // 16 | 24 | 32 | 48 | 64
            { "dock", "left" },           // left | right | floating
            { "group_by", "tab" },        // tab | panel
            { "watch", "1" },
            { "watch_ms", "1500" },
            { "collapsed", "" },
            { "show_tooltips", "1" },
            { "show_footer", "1" },
            { "show_paths", "0" },
            { "include_builtin", "1" },   // addin buttons that sit on Revit's own tabs
            { "name_filter", "" },        // only tabs whose name contains this
            { "hidden_tabs", "" },        // tabs the user switched off in Settings (normalised names)
            { "debug", "1" },
            { "favourites", "" },
            { "fav_labels", "1" },
            { "view", "all" },            // all | favourites
            { "pinned", "" },
            { "qat", "" },
            { "win_w", "380" },
            { "win_h", "900" },
            { "win_left", "" },
            { "win_top", "" },
        };

        // ------------------------------------------------------------------ paths

        public static string Root()
        {
            string baseDir = Environment.GetEnvironmentVariable("APPDATA");
            if (string.IsNullOrEmpty(baseDir)) baseDir = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            return Path.Combine(baseDir, "RevoBIM");
        }

        public static string SettingsPath() { return Path.Combine(Root(), SettingsName); }
        public static string DebugPath() { return Path.Combine(Root(), DebugName); }
        public static string ErrorPath() { return Path.Combine(Root(), ErrorName); }

        public static void EnsureRoot()
        {
            try { Directory.CreateDirectory(Root()); } catch (Exception) { }
        }

        /// <summary>Modification time of the settings file, so a pane can notice another window changed it.</summary>
        public static long SettingsStamp()
        {
            try { return File.GetLastWriteTimeUtc(SettingsPath()).Ticks; } catch (Exception) { return 0; }
        }

        // ------------------------------------------------------------------ text

        private static readonly Regex Ws = new Regex(@"\s+", RegexOptions.Compiled);

        public static string Normalise(string value)
        {
            if (value == null) return "";
            return Ws.Replace(value.Replace("\\n", " "), " ").Trim().ToLowerInvariant();
        }

        public static string Flatten(string value)
        {
            if (value == null) return "";
            return Ws.Replace(value.Replace("\\n", " "), " ").Trim();
        }

        /// <summary>Every word typed must appear somewhere in the haystack, in any order.</summary>
        public static bool MatchesSearch(string haystack, List<string> terms)
        {
            if (terms == null || terms.Count == 0) return true;
            string hay = Normalise(haystack);
            foreach (string term in terms)
                if (hay.IndexOf(term, StringComparison.Ordinal) < 0) return false;
            return true;
        }

        public static List<string> Terms(string search)
        {
            var list = new List<string>();
            foreach (string part in Normalise(search).Split(' '))
                if (part.Length > 0) list.Add(part);
            return list;
        }

        private static readonly Regex Digits = new Regex(@"(\d+)", RegexOptions.Compiled);

        /// <summary>Natural ordering: "Panel 2" before "Panel 10".</summary>
        public static int NaturalCompare(string a, string b)
        {
            string[] pa = Digits.Split((a ?? "").ToLowerInvariant());
            string[] pb = Digits.Split((b ?? "").ToLowerInvariant());
            int n = Math.Min(pa.Length, pb.Length);
            for (int i = 0; i < n; i++)
            {
                if (pa[i] == pb[i]) continue;
                bool da = i % 2 == 1, db = i % 2 == 1;
                if (da && db)
                {
                    long x, y;
                    if (long.TryParse(pa[i], NumberStyles.None, CultureInfo.InvariantCulture, out x) &&
                        long.TryParse(pb[i], NumberStyles.None, CultureInfo.InvariantCulture, out y) && x != y)
                        return x < y ? -1 : 1;
                }
                int c = string.CompareOrdinal(pa[i], pb[i]);
                if (c != 0) return c;
            }
            return pa.Length.CompareTo(pb.Length);
        }

        // ------------------------------------------------------------------ settings

        public static Dictionary<string, string> LoadSettings()
        {
            var values = new Dictionary<string, string>(Defaults);
            try
            {
                string path = SettingsPath();
                if (File.Exists(path))
                {
                    foreach (string raw in File.ReadAllLines(path, Encoding.UTF8))
                    {
                        string line = raw.Trim();
                        if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal)) continue;
                        int eq = line.IndexOf('=');
                        if (eq < 0) continue;
                        string key = line.Substring(0, eq).Trim();
                        if (Defaults.ContainsKey(key)) values[key] = line.Substring(eq + 1).Trim();
                    }
                }
            }
            catch (Exception)
            {
                // a damaged file falls back to the defaults key by key
            }
            return values;
        }

        public static bool SaveSettings(Dictionary<string, string> values)
        {
            try
            {
                EnsureRoot();
                var keys = new List<string>(Defaults.Keys);
                keys.Sort(StringComparer.Ordinal);
                var sb = new StringBuilder();
                sb.Append("# Addin Manager settings - plain key=value, safe to hand edit\n");
                foreach (string key in keys)
                {
                    string v;
                    if (!values.TryGetValue(key, out v)) v = Defaults[key];
                    sb.Append(key).Append('=').Append(v).Append('\n');
                }
                File.WriteAllText(SettingsPath(), sb.ToString(), new UTF8Encoding(false));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static string Get(Dictionary<string, string> s, string key)
        {
            string v;
            if (s != null && s.TryGetValue(key, out v) && v != null) return v;
            string d;
            return Defaults.TryGetValue(key, out d) ? d : "";
        }

        public static bool AsBool(Dictionary<string, string> s, string key)
        {
            string v = Get(s, key).Trim().ToLowerInvariant();
            return v == "1" || v == "true" || v == "yes" || v == "on";
        }

        public static int AsInt(Dictionary<string, string> s, string key, int fallback)
        {
            int n;
            return int.TryParse(Get(s, key).Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out n) ? n : fallback;
        }

        public static List<string> AsList(Dictionary<string, string> s, string key)
        {
            var list = new List<string>();
            foreach (string part in Get(s, key).Split(ListSep))
            {
                string t = part.Trim();
                if (t.Length > 0) list.Add(t);
            }
            return list;
        }

        public static void SetList(Dictionary<string, string> s, string key, IEnumerable<string> items)
        {
            var parts = new List<string>();
            foreach (string item in items)
            {
                if (item.IndexOf(ListSep) >= 0) throw new ArgumentException("a " + key + " entry contains the list separator: " + item);
                parts.Add(item);
            }
            s[key] = string.Join(ListSep.ToString(), parts.ToArray());
        }

        // ------------------------------------------------------------------ debug log

        private static bool debugOn = true;
        private static bool headerWritten;

        public static void SetDebug(bool on) { debugOn = on; }

        public static string BuildInfo()
        {
            string dll = "";
            string stamp = "";
            try
            {
                Assembly a = typeof(AmCore).Assembly;
                dll = a.Location;
                if (File.Exists(dll)) stamp = File.GetLastWriteTime(dll).ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
                return "Addin Manager " + Version + " | add-in " + a.GetName().Version + " | " + dll + " | written " + stamp;
            }
            catch (Exception)
            {
                return "Addin Manager " + Version;
            }
        }

        public static void Log(string message)
        {
            if (!debugOn) return;
            try
            {
                EnsureRoot();
                var sb = new StringBuilder();
                if (!headerWritten)
                {
                    headerWritten = true;
                    sb.Append("==== ").Append(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture))
                      .Append(' ').Append(BuildInfo()).Append('\n');
                }
                sb.Append(message).Append('\n');
                File.AppendAllText(DebugPath(), sb.ToString(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }

        public static void LogException(string where, Exception err)
        {
            Log("[" + where + "] " + err);
        }

        // ------------------------------------------------------------------ dock arithmetic

        /// <summary>(left, top, width, height) of a window snapped to one side of the target area.</summary>
        public static double[] DockRect(double[] target, double width, string side, double minWidth)
        {
            width = Math.Max(minWidth, Math.Min(width, target[2]));
            if (side == "right") return new[] { target[0] + target[2] - width, target[1], width, target[3] };
            return new[] { target[0], target[1], width, target[3] };
        }

        public static bool RectDiffers(double[] a, double[] b, double tolerance = 1.0)
        {
            if (a == null || b == null) return true;
            for (int i = 0; i < Math.Min(a.Length, b.Length); i++)
                if (Math.Abs(a[i] - b[i]) > tolerance) return true;
            return false;
        }

        // ------------------------------------------------------------------ favourites

        public static int FavIconSize(int listIconSize) { return Math.Max(FavMinIcon, listIconSize + FavGrow); }

        public static List<string> FavAdd(List<string> keys, string key)
        {
            var list = keys.FindAll(k => k.Length > 0);
            if (!list.Contains(key)) list.Add(key);
            return list;
        }

        public static List<string> FavRemove(List<string> keys, string key)
        {
            return keys.FindAll(k => k.Length > 0 && k != key);
        }

        /// <summary>Which slot the pointer is over, given each tile's (left, top, w, h). -1 when there are no tiles.</summary>
        public static int DropIndex(List<double[]> rects, double x, double y)
        {
            if (rects.Count == 0) return -1;
            for (int i = 0; i < rects.Count; i++)
            {
                double[] r = rects[i];
                if (r[0] <= x && x < r[0] + r[2] && r[1] <= y && y < r[1] + r[3]) return i;
            }
            int best = 0;
            for (int i = 0; i < rects.Count; i++)
            {
                double[] r = rects[i];
                bool rowHit = r[1] <= y && y < r[1] + r[3];
                if (y >= r[1] + r[3] || (rowHit && x >= r[0])) best = i;
            }
            return best;
        }

        /// <summary>The saved order with the shown tiles rearranged in place; favourites not on screen keep their places.</summary>
        public static List<string> MergeOrder(List<string> saved, List<string> shown)
        {
            var visible = new HashSet<string>(shown);
            var queue = new Queue<string>(shown);
            var result = new List<string>();
            foreach (string key in saved)
                result.Add(visible.Contains(key) && queue.Count > 0 ? queue.Dequeue() : key);
            while (queue.Count > 0) result.Add(queue.Dequeue());
            return result;
        }
    }
}
