using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamCore
    {
        // ===================================================== family settings file
        public static string FamiliesPath()
        {
            return Path.Combine(FhaCore.SettingsDir(), "hanger_automation_families.txt");
        }

        // str.splitlines() on a unicode string: \n \r\n \r \v \f \x1c \x1d \x1e \x85 \u2028 \u2029
        private static List<string> SplitLines(string text)
        {
            var o = new List<string>();
            var sb = new StringBuilder();
            for (int i = 0; i < text.Length; i++)
            {
                char ch = text[i];
                if (ch == '\r')
                {
                    o.Add(sb.ToString()); sb.Clear();
                    if (i + 1 < text.Length && text[i + 1] == '\n') i++;
                }
                else if (ch == '\n' || ch == '\v' || ch == '\f' || ch == '\u001c' || ch == '\u001d' || ch == '\u001e'
                         || ch == '\u0085' || ch == '\u2028' || ch == '\u2029')
                {
                    o.Add(sb.ToString()); sb.Clear();
                }
                else sb.Append(ch);
            }
            if (sb.Length > 0) o.Add(sb.ToString());
            return o;
        }

        /// <summary>[Family name] sections of key=value lines -> {family: config}. A key absent from a section keeps its
        /// default (the Python dict held only the keys present; fam_config / dump_families filled the rest in the same way).</summary>
        public static Dictionary<string, FamConfig> ParseFamilies(string text)
        {
            var o = new Dictionary<string, FamConfig>(StringComparer.Ordinal);
            FamConfig cur = null;
            foreach (string raw in SplitLines(text ?? ""))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal)) continue;
                if (line.StartsWith("[", StringComparison.Ordinal) && line.EndsWith("]", StringComparison.Ordinal))
                {
                    string name = line.Substring(1, line.Length - 2).Trim();
                    if (!o.TryGetValue(name, out cur))
                    {
                        cur = new FamConfig();
                        o[name] = cur;
                    }
                    continue;
                }
                int eq = line.IndexOf('=');
                if (cur == null || eq < 0) continue;
                string k = line.Substring(0, eq).Trim();
                if (Array.IndexOf(FamKeys, k) >= 0) cur[k] = line.Substring(eq + 1).Trim();
            }
            return o;
        }

        /// <summary>The file text (lines joined with \n, as the Python builds it).</summary>
        public static string DumpFamilies(IDictionary<string, FamConfig> fams)
        {
            var lines = new List<string> { "# Hanger Automation - family hanger settings" };
            var names = fams.Keys.ToList();
            names.Sort(StringComparer.Ordinal);
            var keys = FamKeys.ToList();
            keys.Sort(StringComparer.Ordinal);
            foreach (string name in names)
            {
                lines.Add("[" + name + "]");
                FamConfig c = fams[name];
                foreach (string k in keys)
                    lines.Add(k + "=" + (c[k] ?? FamDefaults[k]));
            }
            return string.Join("\n", lines) + "\n";
        }

        public static Dictionary<string, FamConfig> LoadFamilies(string path = null)
        {
            string p = string.IsNullOrEmpty(path) ? FamiliesPath() : path;
            try
            {
                if (File.Exists(p))
                    return ParseFamilies(File.ReadAllText(p, new UTF8Encoding(false)));
            }
            catch (Exception) { }
            return new Dictionary<string, FamConfig>(StringComparer.Ordinal);
        }

        /// <summary>Written as UTF-8 without a BOM; like Python's text-mode io.open, every \n becomes the platform line ending.</summary>
        public static bool SaveFamilies(IDictionary<string, FamConfig> fams, string path = null)
        {
            string p = string.IsNullOrEmpty(path) ? FamiliesPath() : path;
            try
            {
                string folder = Path.GetDirectoryName(p);
                if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder)) Directory.CreateDirectory(folder);
                string text = DumpFamilies(fams);
                if (Environment.NewLine != "\n") text = text.Replace("\n", Environment.NewLine);
                File.WriteAllText(p, text, new UTF8Encoding(false));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Settings for one family, defaults filled in, width parameters guessed from the family's own
        /// parameter names when none have been chosen.</summary>
        public static FamConfig FamConfigFor(IDictionary<string, FamConfig> fams, string family, IEnumerable<string> paramNames = null)
        {
            // dict(FAM_DEFAULTS) updated with the family's saved keys (a Mode the entry carries, from the UI's
            // dict(cfg, mode=...), is carried through too); always a new object.
            FamConfig cfg;
            FamConfig saved = null;
            if (fams != null && fams.TryGetValue(family ?? "", out saved) && saved != null) cfg = saved.Clone();
            else cfg = new FamConfig();
            List<string> names = paramNames == null ? null : paramNames.ToList();
            bool have = names != null && names.Count > 0;
            if (have && !(cfg.Left.Length > 0 && cfg.Right.Length > 0))
            {
                string gl, gr;
                GuessWidthParams(names, out gl, out gr);
                cfg.Left = cfg.Left.Length > 0 ? cfg.Left : gl;
                cfg.Right = cfg.Right.Length > 0 ? cfg.Right : gr;
            }
            if (have && !names.Contains(cfg.Rod))
            {
                string g = GuessRodParam(names);
                if (g.Length > 0) cfg.Rod = g;
            }
            if (have && !names.Contains(cfg.FirstBar))
            {
                string g = GuessFirstBarParam(names);
                if (g.Length > 0) cfg.FirstBar = g;
            }
            if (have && !names.Contains(cfg.Height))
            {
                string g = GuessSupportHeightParam(names);
                if (g.Length > 0) cfg.Height = g;
            }
            if (have && !names.Contains(cfg.Dia))
            {
                string g = GuessDiameterParam(names);
                if (g.Length > 0) cfg.Dia = g;
            }
            if (have && !names.Contains(cfg.CircHeight))
            {
                string g = GuessSupportHeightParam(names);
                if (g.Length > 0) cfg.CircHeight = g;
            }
            if (cfg.Axis != "X" && cfg.Axis != "Y") cfg.Axis = "X";
            if (cfg.Soffit != "level" && cfg.Soffit != "structure") cfg.Soffit = "level";
            if (cfg.Style != "rect" && cfg.Style != "circ") cfg.Style = "rect";
            if (cfg.CircAxis != "X" && cfg.CircAxis != "Y") cfg.CircAxis = "X";
            return cfg;
        }

        /// <summary>Has this family been through Family settings (saved at least once)?</summary>
        public static bool Configured(IDictionary<string, FamConfig> fams, string family)
        {
            return fams != null && family != null && fams.ContainsKey(family);
        }

        /// <summary>'BIM_DIM_Diameter' style: a name containing diameter (else dia).</summary>
        public static string GuessDiameterParam(IEnumerable<string> names)
        {
            var list = names.ToList();
            foreach (string want in new[] { "diameter", "dia" })
                foreach (string n in list)
                    if (n.ToLowerInvariant().IndexOf(want, StringComparison.Ordinal) >= 0) return n;
            return "";
        }

        private static HashSet<string> Words(string name)
        {
            var o = new HashSet<string>(FhaCore.NameTokens(name), StringComparer.Ordinal);
            foreach (string w in (name ?? "").ToLowerInvariant().Replace('_', ' ').Split((char[])null, StringSplitOptions.RemoveEmptyEntries))
                o.Add(w);
            return o;
        }

        /// <summary>(left, right) from a family's length parameters: a Left / Right pair first (BGL_DIM_Width Left,
        /// Width_L ...), then any pair differing only in left / right or L / R.</summary>
        public static void GuessWidthParams(IEnumerable<string> names, out string left, out string right)
        {
            left = right = "";
            foreach (string n in names)
            {
                HashSet<string> w = Words(n);
                string low = n.ToLowerInvariant();
                if (left.Length == 0 && (w.Contains("left") || low.EndsWith("_l", StringComparison.Ordinal) || low.EndsWith(" l", StringComparison.Ordinal)))
                    left = n;
                else if (right.Length == 0 && (w.Contains("right") || low.EndsWith("_r", StringComparison.Ordinal) || low.EndsWith(" r", StringComparison.Ordinal)))
                    right = n;
            }
        }

        public static string GuessRodParam(IEnumerable<string> names)
        {
            foreach (string n in names)
            {
                string low = n.ToLowerInvariant();
                if (low.Contains("rod") && (low.Contains("length") || low.Contains("len"))) return n;
            }
            return "";
        }

        /// <summary>'First Bar Offset' style: first + bar, else bar + offset.</summary>
        public static string GuessFirstBarParam(IEnumerable<string> names)
        {
            var list = names.ToList();
            foreach (string[] want in new[] { new[] { "first", "bar" }, new[] { "bar", "offset" } })
                foreach (string n in list)
                {
                    string low = n.ToLowerInvariant();
                    if (want.All(w => low.Contains(w)) && !low.Contains("last")) return n;
                }
            return "";
        }

        /// <summary>'BIM_Hanger_Support_Height' style: support + height.</summary>
        public static string GuessSupportHeightParam(IEnumerable<string> names)
        {
            foreach (string n in names)
            {
                string low = n.ToLowerInvariant();
                if (low.Contains("support") && low.Contains("height")) return n;
            }
            return "";
        }

        /// <summary>(first bar offset, support height) for a floor support: the bottom bar's top at the service invert
        /// (measured from the level the support stands on), the gap to the top bar the service's full depth - insulation
        /// included when the support goes round it - plus the clearance above. A group uses the span from its lowest
        /// bottom to its highest top.</summary>
        public static void FloorValues(double zInvert, double levelZ, Section sec, double heightClearFt, out double first, out double height)
        {
            first = zInvert - levelZ;
            double h = sec.SpanHeight ?? sec.Depth;
            height = h + heightClearFt;
        }

        /// <summary>The Floor Support tab's control name for a Family Hangers one.</summary>
        public static string FlrName(string name)
        {
            if (name == "FamPanel") return "FloorPanel";
            if (name == "LstFamilies") return "LstFlrFamilies";
            int i = name.IndexOf("Fam", StringComparison.Ordinal);
            if (i < 0) return name;
            return name.Substring(0, i) + "Flr" + name.Substring(i + 3);
        }
    }
}
