using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.FilterManager
{
    /// <summary>
    /// Filter Manager: version, settings, search matching and layout maths. Port of fm_core.py (v3.31.0).
    /// </summary>
    public static class FmCore
    {
        public const string Version = "v3.31.0";
        public const string ToolName = "Filter Manager";
        public const string BreadcrumbFile = "filter_manager_last_run.txt";
        public const string LayoutFile = "filter_manager_layout.txt";
        public const string Title = "RevoBIM Filter Manager";

        public static long EidValue(ElementId id)
        {
            if (id == null) return 0;
            try { return id.Value; }
            catch (Exception) { return 0; }
        }

        // ---------------------------------------------------------------------------
        //  The Revit session
        // ---------------------------------------------------------------------------
        private static UIApplication _uiapp;

        public static void SetUiApp(UIApplication uiapp) { _uiapp = uiapp; }

        public static int RevitVersion()
        {
            try
            {
                if (_uiapp != null) return int.Parse(_uiapp.Application.VersionNumber);
            }
            catch (Exception) { }
            try
            {
                return int.Parse(_uiapp.ActiveUIDocument.Document.Application.VersionNumber);
            }
            catch (Exception) { return 0; }
        }

        public static bool OpenExternally(string path)
        {
            try
            {
                var psi = new ProcessStartInfo(path) { UseShellExecute = true };
                Process.Start(psi);
                return true;
            }
            catch (Exception) { return false; }
        }

        public static bool WriteText(string path, string text)
        {
            try
            {
                File.WriteAllText(path, text ?? "", new UTF8Encoding(false));
                return true;
            }
            catch (Exception) { return false; }
        }

        // ---------------------------------------------------------------------------
        //  Folders, breadcrumb, settings
        // ---------------------------------------------------------------------------
        public static string SettingsFolder()
        {
            string baseDir;
            try
            {
                baseDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
                if (!Directory.Exists(baseDir)) Directory.CreateDirectory(baseDir);
            }
            catch (Exception) { return Path.GetTempPath(); }
            return baseDir;
        }

        /// <summary>
        /// Write a stage marker to disk and flush it immediately. A hard Revit crash leaves no traceback, so
        /// the last line of this file names the stage that killed it.
        /// </summary>
        public static void Crumb(string stage)
        {
            try
            {
                string path = Path.Combine(SettingsFolder(), BreadcrumbFile);
                File.AppendAllText(path, DateTime.Now.ToString("HH:mm:ss") + "  " + stage + "\r\n");
            }
            catch (Exception) { }
        }

        public static string CrumbReset()
        {
            try
            {
                string path = Path.Combine(SettingsFolder(), BreadcrumbFile);
                string previous = File.Exists(path) ? File.ReadAllText(path) : "";
                File.WriteAllText(path, "RevoBIM Filter Manager " + Version + "  " +
                                        DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "\r\n");
                return previous;
            }
            catch (Exception) { return ""; }
        }

        public static string LastStage(string previousText)
        {
            try
            {
                var lines = (previousText ?? "").Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
                    .Select(l => l.Trim()).Where(l => l.Length > 0).ToList();
                return lines.Count > 0 ? lines[lines.Count - 1] : null;
            }
            catch (Exception) { return null; }
        }

        public static List<string> RecentCrumbs(int count = 12)
        {
            try
            {
                string path = Path.Combine(SettingsFolder(), BreadcrumbFile);
                if (!File.Exists(path)) return new List<string> { "(nothing recorded yet)" };
                var lines = File.ReadAllLines(path).Select(l => l.TrimEnd()).Where(l => l.Trim().Length > 0).ToList();
                if (lines.Count == 0) return new List<string> { "(nothing recorded yet)" };
                return lines.Skip(Math.Max(0, lines.Count - count)).ToList();
            }
            catch (Exception) { return new List<string> { "(the breadcrumb file could not be read)" }; }
        }

        /// <summary>A plain key=value text file. Not JSON: stays readable and hand editable. A missing or damaged file gives an empty dictionary.</summary>
        public static Dictionary<string, string> LoadSettings(string name)
        {
            var result = new Dictionary<string, string>();
            try
            {
                string path = Path.Combine(SettingsFolder(), name);
                if (!File.Exists(path)) return result;
                foreach (string line in File.ReadAllLines(path))
                {
                    int eq = line.IndexOf('=');
                    if (eq < 0) continue;
                    string key = line.Substring(0, eq).Trim();
                    if (key.Length > 0 && !key.StartsWith("#")) result[key] = line.Substring(eq + 1).Trim();
                }
            }
            catch (Exception) { }
            return result;
        }

        public static bool SaveSettings(string name, Dictionary<string, string> values)
        {
            var rows = new List<string> { "# RevoBIM Filter Manager " + Version };
            foreach (string key in values.Keys.OrderBy(k => k, StringComparer.Ordinal))
                rows.Add(key + "=" + values[key]);
            return WriteText(Path.Combine(SettingsFolder(), name), string.Join("\r\n", rows) + "\r\n");
        }

        public static string LogFolder()
        {
            try
            {
                string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "RevoBIM", "Logs");
                if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
                return dir;
            }
            catch (Exception) { return Path.GetTempPath(); }
        }

        public static string LogPath(string prefix)
        {
            return Path.Combine(LogFolder(), prefix + "_" + DateTime.Now.ToString("yyyyMMdd_HHmmss") + ".log");
        }

        // ---------------------------------------------------------------------------
        //  Search and rows
        // ---------------------------------------------------------------------------
        /// <summary>Whether every word of the search is found somewhere in the given text.</summary>
        public static bool ContainsAll(string search, IEnumerable<string> haystacks)
        {
            string[] words = (search ?? "").ToLowerInvariant().Split(new[] { ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
            if (words.Length == 0) return true;
            string hay = string.Join(" ", (haystacks ?? new string[0]).Select(h => h ?? "")).ToLowerInvariant();
            foreach (string word in words)
                if (hay.IndexOf(word, StringComparison.Ordinal) < 0) return false;
            return true;
        }

        public static bool RowVisible(string name, int usageCount, string search = "", bool unusedOnly = false, IEnumerable<string> extra = null)
        {
            if (unusedOnly && usageCount > 0) return false;
            var hay = new List<string> { name };
            if (extra != null) hay.AddRange(extra);
            return ContainsAll(search, hay);
        }

        public static string TypeKey(FmViewRow row) { return row.Kind + "|" + row.Type; }

        /// <summary>
        /// Whether a row in Target Views survives the view-type dropdown, the search and the lock tick.
        /// onlyIds is "Show only selected".
        /// </summary>
        public static bool ViewRowVisible(FmViewRow row, ICollection<string> hiddenTypes = null, string search = "",
                                          bool hideLocked = false, ICollection<long> onlyIds = null)
        {
            if (onlyIds != null && !onlyIds.Contains(row.Idv)) return false;
            if (hideLocked && row.Locked) return false;
            if (hiddenTypes != null && hiddenTypes.Count > 0 && hiddenTypes.Contains(TypeKey(row))) return false;
            return ContainsAll(search, new[] { row.Name, row.Kind, row.Type, row.Template });
        }

        /// <summary>(key, label, count) for the view-type dropdown, family by family.</summary>
        public static List<Tuple<string, string, int>> ViewTypeEntries(IEnumerable<FmViewRow> rows)
        {
            var counts = new Dictionary<string, int>();
            var labels = new Dictionary<string, string>();
            var order = new Dictionary<string, Tuple<string, string>>();
            foreach (FmViewRow row in rows)
            {
                string key = TypeKey(row);
                string kind = row.Kind ?? "";
                string tname = string.IsNullOrEmpty(row.Type) ? kind : row.Type;
                int n;
                counts.TryGetValue(key, out n);
                counts[key] = n + 1;
                labels[key] = tname == kind ? tname : tname + "  (" + kind + ")";
                order[key] = Tuple.Create(kind.ToLowerInvariant(), tname.ToLowerInvariant());
            }
            return counts.Keys
                .OrderBy(k => order[k].Item1, StringComparer.Ordinal)
                .ThenBy(k => order[k].Item2, StringComparer.Ordinal)
                .Select(k => Tuple.Create(k, labels[k], counts[k])).ToList();
        }

        public static string DropdownCaption(int total, int hidden, string noun = "view types")
        {
            if (hidden <= 0) return "All " + noun + "  (" + total + ")";
            int shown = total - hidden;
            if (shown <= 0) return "None ticked";
            return shown + " of " + total + " " + noun;
        }

        /// <summary>
        /// Whether a use count satisfies what was typed in the # box: blank matches everything; a number
        /// matches exactly; &gt;0, &gt;=2, &lt;5, &lt;=1, =3, &lt;&gt;0 and a range 2-5 work. Anything unreadable is
        /// treated as no filter.
        /// </summary>
        public static bool UsesMatch(long count, string expression)
        {
            string text = (expression ?? "").Trim();
            if (text.Length == 0) return true;
            text = text.Replace(" ", "");
            long n;
            string[] prefixes = { ">=", "<=", "<>", ">", "<", "=" };
            foreach (string prefix in prefixes)
            {
                if (!text.StartsWith(prefix, StringComparison.Ordinal)) continue;
                if (!long.TryParse(text.Substring(prefix.Length), out n)) return true;
                switch (prefix)
                {
                    case ">=": return count >= n;
                    case "<=": return count <= n;
                    case "<>": return count != n;
                    case ">": return count > n;
                    case "<": return count < n;
                    default: return count == n;
                }
            }
            int dash = text.Length > 1 ? text.IndexOf('-', 1) : -1;
            if (dash > 0)
            {
                long low, high;
                if (long.TryParse(text.Substring(0, dash), out low) && long.TryParse(text.Substring(dash + 1), out high))
                    return low <= count && count <= high;
                return true;
            }
            if (long.TryParse(text, out n)) return count == n;
            return true;
        }

        // ---------------------------------------------------------------------------
        //  Layout maths
        // ---------------------------------------------------------------------------
        /// <summary>Share the page width between the table's columns: each keeps its minimum and takes a share of the spare.</summary>
        public static double[] DistributeWidths(double[] minimums, double[] weights, double available)
        {
            var mins = minimums.ToArray();
            double[] w = weights.Select(x => Math.Max(0.0, x)).ToArray();
            double floor = mins.Sum();
            if (available <= floor || mins.Length == 0) return mins;
            double totalWeight = w.Sum();
            if (totalWeight <= 0) return mins;
            double spare = available - floor;
            var widths = new double[mins.Length];
            for (int i = 0; i < mins.Length; i++)
                widths[i] = Math.Round(mins[i] + spare * (w[i] / totalWeight), 2);
            double drift = Math.Round(available - widths.Sum(), 2);
            if (drift != 0)
            {
                int biggest = 0;
                for (int i = 1; i < w.Length; i++) if (w[i] > w[biggest]) biggest = i;
                widths[biggest] = Math.Round(widths[biggest] + drift, 2);
            }
            return widths;
        }

        /// <summary>Fit a window onto a smaller screen: returns (size, minimum), never below the floor.</summary>
        public static Tuple<double, double> ShrinkToFit(double size, double minimum, double available, double floor = 360.0)
        {
            if (available <= 0) return Tuple.Create(size, minimum);
            double newMinimum = Math.Min(minimum, Math.Max(floor, Math.Min(minimum, available)));
            double newSize = Math.Min(size, available);
            if (newSize < newMinimum) newSize = newMinimum;
            return Tuple.Create(newSize, newMinimum);
        }

        /// <summary>Share a fixed pool of width between two columns as one is dragged.</summary>
        public static Tuple<double, double> SplitWidths(double first, double second, double minFirst, double minSecond, double change)
        {
            double pool = first + second;
            if (pool <= 0) return Tuple.Create(first, second);
            double low = minFirst;
            double high = pool - minSecond;
            if (high < low)
            {
                double share = (low + minSecond) != 0 ? pool * (low / (low + minSecond)) : pool / 2.0;
                return Tuple.Create(share, pool - share);
            }
            double wanted = Math.Max(low, Math.Min(first + change, high));
            return Tuple.Create(wanted, pool - wanted);
        }
    }

    /// <summary>One ordinary view that can take filters (a row of the Target Views list).</summary>
    public class FmViewRow
    {
        public ElementId Id;
        public long Idv;
        public string Name = "";
        public string Kind = "";
        public string Type = "";
        public string Template = "";
        public bool Locked;
    }
}
