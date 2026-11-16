using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace RevoBIM.Tools.HangerAutomation
{
    // =====================================================================================================
    // Hanger Automation - Family Hangers tab, pure logic (no Revit). Port of hfam_core.py.
    // Lengths are decimal feet unless a name ends in Mm.
    // =====================================================================================================

    /// <summary>
    /// The per-family settings (the Python dict of FAM_DEFAULTS keys; every value is the text the file holds).
    /// Mode is the one extra key the UI adds with dict(cfg, mode=...): "hang" or "floor", null when absent.
    /// </summary>
    public class FamConfig
    {
        public string Left = "";             // instance length stretching one way from centre
        public string Right = "";            // instance length stretching the other way
        public string Rod = HfamCore.RodDefault;   // drop rod length
        public string Axis = "X";            // the family's width runs along its X (left/right) or Y
        public string Clearance = "0";       // mm added to each half width
        public string Soffit = "level";      // level = base of the level above; structure = ray to structure
        public string Swap = "0";            // 1 = the first width parameter is the family's positive side
        // floor supports (Family Floor Support tab)
        public string FirstBar = HfamCore.FirstBarDefault;           // level -> top of the bottom bar (the service invert)
        public string Height = HfamCore.SupportHeightDefault;        // bottom bar top -> top bar underside (the service depth)
        public string HeightClear = "0";     // mm added to the support height above the service
        // floor support style: rect = Rectangular Floor Based (frame round the service),
        // circ = Circular System Based (a ring round a pipe / round duct on a post)
        public string Style = "rect";
        public string Dia = HfamCore.DiameterDefault;                // circ: ring diameter, set to the service's (insulated) diameter
        public string CircHeight = HfamCore.SupportHeightDefault;    // circ: base -> service centre (the ring centre)
        public string CircAxis = "X";        // circ: the service runs along the family's X or Y

        /// <summary>The extra "mode" key some callers add (dict(cfg, mode=...)); null = not set.</summary>
        public string Mode;

        public FamConfig() { }

        public FamConfig Clone() { return (FamConfig)MemberwiseClone(); }

        /// <summary>The value for a file key (left, right, rod, axis, clearance, soffit, swap, first_bar, height,
        /// height_clear, style, dia, circ_height, circ_axis) or "mode"; null for any other key.</summary>
        public string this[string key]
        {
            get
            {
                switch (key)
                {
                    case "left": return Left;
                    case "right": return Right;
                    case "rod": return Rod;
                    case "axis": return Axis;
                    case "clearance": return Clearance;
                    case "soffit": return Soffit;
                    case "swap": return Swap;
                    case "first_bar": return FirstBar;
                    case "height": return Height;
                    case "height_clear": return HeightClear;
                    case "style": return Style;
                    case "dia": return Dia;
                    case "circ_height": return CircHeight;
                    case "circ_axis": return CircAxis;
                    case "mode": return Mode;
                }
                return null;
            }
            set
            {
                switch (key)
                {
                    case "left": Left = value; break;
                    case "right": Right = value; break;
                    case "rod": Rod = value; break;
                    case "axis": Axis = value; break;
                    case "clearance": Clearance = value; break;
                    case "soffit": Soffit = value; break;
                    case "swap": Swap = value; break;
                    case "first_bar": FirstBar = value; break;
                    case "height": Height = value; break;
                    case "height_clear": HeightClear = value; break;
                    case "style": Style = value; break;
                    case "dia": Dia = value; break;
                    case "circ_height": CircHeight = value; break;
                    case "circ_axis": CircAxis = value; break;
                    case "mode": Mode = value; break;
                }
            }
        }

        /// <summary>cfg.get(key, dflt).</summary>
        public string Get(string key, string dflt)
        {
            string v = this[key];
            return v ?? dflt;
        }
    }

    /// <summary>One type in the family list (the dicts list_family_types builds and filter_types reads).</summary>
    public class FamTypeItem
    {
        public string Key;        // item_key(family, type)
        public string Family;
        public string Type;
        public string Cat;        // BuiltInCategory name, e.g. OST_GenericModel
        public string CatLabel;
        public Autodesk.Revit.DB.ElementId Id;
    }

    /// <summary>
    /// A service's (or unit's) section as the hanger fitting code sees it (the Python dict: a, b, width, depth, round,
    /// ins, ins_used, bare_width, bare_depth, keys, ext_neg, ext_pos, across, span_height, unit, run_from, length, bottom,
    /// plus set_left / set_right / set_dia / set_height the placing code writes into it).
    /// Nullable members are the keys that may be absent in the dict.
    /// </summary>
    public class Section
    {
        public V3 A, B;
        public double Width, Depth;
        public bool Round;
        public double Ins;
        public bool InsUsed;
        public double? BareWidth, BareDepth;
        public List<long> Keys;
        public double? ExtNeg, ExtPos;
        public V3? Across;
        public double? SpanHeight;
        public bool Unit;
        public string RunFrom;
        public double? Length;
        public double? Bottom;
        public double? SetLeft, SetRight, SetDia, SetHeight;

        /// <summary>dict(sec): a shallow copy (the Keys list is shared, as in Python).</summary>
        public Section Clone() { return (Section)MemberwiseClone(); }
    }

    /// <summary>One service in a grouped hanger (bundle members: key, a, b, width, depth).</summary>
    public class BundleMember
    {
        public long Key;
        public V3 A, B;
        public double Width, Depth;
        public BundleMember() { }
        public BundleMember(long key, V3 a, V3 b, double width, double depth) { Key = key; A = a; B = b; Width = width; Depth = depth; }
    }

    /// <summary>The Hanger rules: (z_tol_ft, gap_tol_ft, angle_deg, centre).</summary>
    public class GroupRules
    {
        public double ZTolFt, GapTolFt, AngleDeg;
        public string Centre = "mean";
        public GroupRules() { }
        public GroupRules(double zTolFt, double gapTolFt, double angleDeg, string centre) { ZTolFt = zTolFt; GapTolFt = gapTolFt; AngleDeg = angleDeg; Centre = centre; }
        /// <summary>(BUNDLE_Z_MM / MM, BUNDLE_GAP_MM / MM, BUNDLE_ANGLE_DEG, 'mean') - what bundle_for uses when no rules are given.</summary>
        public static GroupRules Default()
        {
            return new GroupRules(HfamCore.BundleZMm / FhaCore.MM, HfamCore.BundleGapMm / FhaCore.MM, HfamCore.BundleAngleDeg, "mean");
        }
    }

    /// <summary>The result of HfamCore.Bundle: one hanger round several services.</summary>
    public class HangerBundle
    {
        public List<long> Keys = new List<long>();
        public double Width, ExtNeg, ExtPos;
        public V3 Across;
        public double Bottom, Top;
        public List<string> Notes = new List<string>();
        public V3 Point, A, B;
    }

    /// <summary>A straight to pick_segment: (key, a, b).</summary>
    public class KeySeg
    {
        public long Key;
        public V3 A, B;
        public KeySeg() { }
        public KeySeg(long key, V3 a, V3 b) { Key = key; A = a; B = b; }
    }

    /// <summary>A hanger for group_runs: (key, point, along) - along is the run direction at the hanger.</summary>
    public class RunHanger
    {
        public long Key;
        public V3 P, Along;
        public RunHanger() { }
        public RunHanger(long key, V3 p, V3 along) { Key = key; P = p; Along = along; }
    }

    /// <summary>One straight line of hangers: its direction and the hanger keys sorted along it.</summary>
    public class RunGroup
    {
        public V3 Dir;
        public List<long> Keys = new List<long>();
    }

    /// <summary>A connector of an in-line unit: origin and basisZ.</summary>
    public class InlineConn
    {
        public V3 Origin, Basis;
        public InlineConn() { }
        public InlineConn(V3 origin, V3 basis) { Origin = origin; Basis = basis; }
    }

    public static class HfamCore
    {
        public const double MM = FhaCore.MM;

        // category key (BuiltInCategory name) -> label, in list order
        public static readonly List<KeyValuePair<string, string>> Categories = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("all", "All hanger categories"),
            new KeyValuePair<string, string>("OST_GenericModel", "Generic Models"),
            new KeyValuePair<string, string>("OST_MEPAncillaryFraming", "MEP Ancillary Framing"),
            new KeyValuePair<string, string>("OST_DuctAccessory", "Duct Accessories"),
        };

        public const string RodDefault = "BGL_DIM_Drop Rod Length";
        public const string FirstBarDefault = "First Bar Offset";
        public const string SupportHeightDefault = "BIM_Hanger_Support_Height";
        public const string DiameterDefault = "BIM_DIM_Diameter";

        /// <summary>The per-family keys in the order FAM_DEFAULTS lists them.</summary>
        public static readonly string[] FamKeys =
        {
            "left", "right", "rod", "axis", "clearance", "soffit", "swap",
            "first_bar", "height", "height_clear", "style", "dia", "circ_height", "circ_axis",
        };

        /// <summary>FAM_DEFAULTS as a key -> value table (use new FamConfig() for a default config object).</summary>
        public static readonly Dictionary<string, string> FamDefaults = BuildFamDefaults();

        private static Dictionary<string, string> BuildFamDefaults()
        {
            var c = new FamConfig();
            var d = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (string k in FamKeys) d[k] = c[k];
            return d;
        }

        public static readonly string[] Modes = { "hang", "floor" };
        public static readonly List<KeyValuePair<string, string>> Styles = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("rect", "Rectangular Floor Based"),
            new KeyValuePair<string, string>("circ", "Circular System Based"),
        };
        public static readonly List<KeyValuePair<string, string>> RunAxes = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("X", "X - left / right"),
            new KeyValuePair<string, string>("Y", "Y - front / back"),
        };
        public static readonly List<KeyValuePair<string, string>> Axes = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("X", "X - left / right"),
            new KeyValuePair<string, string>("Y", "Y - front / back"),
        };
        public static readonly List<KeyValuePair<string, string>> Soffits = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("level", "Base of the level above"),
            new KeyValuePair<string, string>("structure", "Underside of structure above"),
        };

        private static string F0(double v)
        {
            // Python's '{0:.0f}'.format(v)
            string s = Math.Round(v, MidpointRounding.ToEven).ToString("0", CultureInfo.InvariantCulture);
            if ((s == "0" || s == "-0") && (v < 0 || (v == 0 && 1.0 / v < 0))) s = "-0";
            else if (s == "-0") s = "0";
            return s;
        }

        private static string L(long k) { return k.ToString(CultureInfo.InvariantCulture); }

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

        // ================================================================ the list
        /// <summary>Every search word must appear in 'family type' (any case, any order).</summary>
        public static List<FamTypeItem> FilterTypes(IEnumerable<FamTypeItem> items, string category, string text)
        {
            var words = (text ?? "").ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            var o = new List<FamTypeItem>();
            foreach (FamTypeItem it in items)
            {
                if (!string.IsNullOrEmpty(category) && category != "all" && it.Cat != category) continue;
                string hay = ((it.Family ?? "") + " " + (it.Type ?? "")).ToLowerInvariant();
                if (words.All(w => hay.Contains(w))) o.Add(it);
            }
            return o;
        }

        public static string ItemKey(string family, string typeName)
        {
            return family + " : " + typeName;
        }

        // ============================================================== DW/144 etc
        // DW/144 maximum support spacing for horizontal ductwork. Based on duct weight only; closer spacings may be
        // needed for rigidity or the structure. The tool uses min(your maximum, this) when the DW/144 tick is on.
        public static readonly double[][] Dw144Rect = { new[] { 1500.0, 3000.0 }, new[] { 1e9, 2500.0 } };    // longer side up to, spacing
        public static readonly double[][] Dw144Round = { new[] { 1120.0, 3000.0 }, new[] { 1e9, 2500.0 } };   // diameter up to, spacing

        public static double Dw144SpacingMm(double widthMm, double depthMm, bool isRound)
        {
            double size = isRound ? widthMm : Math.Max(widthMm, depthMm);
            foreach (double[] r in (isRound ? Dw144Round : Dw144Rect))
                if (size <= r[0] + 1e-6) return r[1];
            return Dw144Rect[Dw144Rect.Length - 1][1];
        }

        public static double SpanSpacingMm(double userMaxMm, bool useDw144, double widthMm, double depthMm, bool isRound)
        {
            double s = Math.Max(100.0, userMaxMm);
            if (useDw144) s = Math.Min(s, Dw144SpacingMm(widthMm, depthMm, isRound));
            return s;
        }

        /// <summary>FhaCore.PlanStations config for one span of family hangers.</summary>
        public static PlanConfig AutoConfig(IDictionary<string, string> settings, double spacingMm)
        {
            return new PlanConfig
            {
                Spacing = spacingMm,
                StartOff = FhaCore.AsFloat(settings, "fam_start_off", 300.0),
                EndOff = FhaCore.AsFloat(settings, "fam_end_off", 300.0),
                TakeoffMax = 600.0,
                TakeoffClear = FhaCore.AsFloat(settings, "fam_takeoff_clear", 400.0),
                MinGap = 500.0,
                Edge = Math.Max(100.0, FhaCore.AsFloat(settings, "fam_flange_clear", 150.0)),
            };
        }

        // ============================================================ placement
        /// <summary>Value for each of the two stretch parameters: half the duct plus clearance.</summary>
        public static double HalfWidth(double widthFt, double clearanceMm)
        {
            return widthFt / 2.0 + clearanceMm / MM;
        }

        /// <summary>Drop rod from the family's reference level (the duct invert) up to the soffit, or null when the
        /// soffit is not above it (or there is none).</summary>
        public static double? RodLength(double refZ, double? soffitZ)
        {
            if (soffitZ == null) return null;
            double len = soffitZ.Value - refZ;
            if (len > 1e-6) return len;
            return null;
        }

        /// <summary>Lowest level elevation strictly above z (the base of the level above), else null.</summary>
        public static double? LevelAbove(IEnumerable<double> levelElevations, double z, double tolFt = 1.0 / MM)
        {
            double? best = null;
            foreach (double e in levelElevations)
                if (e > z + tolFt && (best == null || e < best.Value)) best = e;
            return best;
        }

        public static double? LevelBelow(IEnumerable<double> levelElevations, double z, double tolFt = 1.0 / MM)
        {
            double? best = null;
            foreach (double e in levelElevations)
                if (e <= z + tolFt && (best == null || e > best.Value)) best = e;
            return best;
        }

        /// <summary>Plan rotation (radians) turning `current` onto `wanted` (x, y of each). A hanger is symmetric, so
        /// facing either way is aligned: the answer is folded into (-90, 90] degrees so it never spins a hanger round needlessly.</summary>
        public static double RotationTo(double currentX, double currentY, double wantedX, double wantedY)
        {
            double a = Math.Atan2(currentX * wantedY - currentY * wantedX,
                                  currentX * wantedX + currentY * wantedY);
            while (a > Math.PI / 2.0 + 1e-9) a -= Math.PI;
            while (a <= -Math.PI / 2.0 + 1e-9) a += Math.PI;
            return a;
        }

        public static double RotationTo(V3 current, V3 wanted)
        {
            return RotationTo(current.X, current.Y, wanted.X, wanted.Y);
        }

        /// <summary>(along, across) unit plan vectors of a duct from a to b.</summary>
        public static void PlanDirs(V3 a, V3 b, out V3 along, out V3 across)
        {
            V3 d = FhaCore.VNorm(new V3(b.X - a.X, b.Y - a.Y, 0.0));
            along = d;
            across = new V3(-d.Y, d.X, 0.0);
        }

        /// <summary>Where the family's own X axis must point: across the duct when its width runs along X, along the duct
        /// when its width runs along Y.</summary>
        public static V3 FamilyXDir(string axis, V3 along, V3 across)
        {
            return axis == "X" ? across : along;
        }

        /// <summary>Closest point to p on the duct centreline a-b, kept marginFt off the ends.</summary>
        public static V3 OnCentreline(V3 a, V3 b, V3 p, double marginFt)
        {
            V3 ab = FhaCore.VSub(b, a);
            double len = FhaCore.VLen(ab);
            if (len < 1e-9) return a;
            double t, d; V3 q;
            FhaCore.ClosestOnSegment(p, a, b, out t, out q, out d);
            double s = t * len;
            if (len > 2.0 * marginFt) s = Math.Max(marginFt, Math.Min(len - marginFt, s));
            else s = len / 2.0;
            return FhaCore.VAdd(a, FhaCore.VScale(ab, s / len));
        }

        // ============================================================== re-align
        /// <summary>Unclamped position of p along a-b in plan (0 at a, 1 at b).</summary>
        public static double LineParam(V3 a, V3 b, V3 p)
        {
            double abx = b.X - a.X, aby = b.Y - a.Y;
            double den = abx * abx + aby * aby;
            if (den < 1e-12) return 0.0;
            return ((p.X - a.X) * abx + (p.Y - a.Y) * aby) / den;
        }

        /// <summary>The point on the duct's centreline square across from p: p keeps its position along the run and only
        /// its sideways offset changes. The line is NOT clipped to the segment, so a hanger beyond this segment's end stays
        /// exactly where it is along the run. Z follows the centreline (sloped ducts).</summary>
        public static V3 OnLine(V3 a, V3 b, V3 p)
        {
            double t = LineParam(a, b, p);
            return new V3(a.X + (b.X - a.X) * t, a.Y + (b.Y - a.Y) * t, a.Z + (b.Z - a.Z) * t);
        }

        public static double PlanOffset(V3 a, V3 b, V3 p)
        {
            V3 q = OnLine(a, b, p);
            return Math.Sqrt((p.X - q.X) * (p.X - q.X) + (p.Y - q.Y) * (p.Y - q.Y));
        }

        /// <summary>The segment the hanger actually sits on: p falls within its length (tolFt either end, for hangers on
        /// a joint) and it is the nearest in plan. Null when p is off every segment.</summary>
        public static long? PickSegment(V3 p, IEnumerable<KeySeg> segs, double tolFt)
        {
            long? bestKey = null;
            double bestOff = 0;
            foreach (KeySeg s in segs)
            {
                double len = Math.Sqrt((s.B.X - s.A.X) * (s.B.X - s.A.X) + (s.B.Y - s.A.Y) * (s.B.Y - s.A.Y));
                if (len < 1e-9) continue;
                double t = LineParam(s.A, s.B, p);
                double slack = tolFt / len;
                if (t < -slack || t > 1.0 + slack) continue;
                double off = PlanOffset(s.A, s.B, p);
                if (bestKey == null || off < bestOff)
                {
                    bestOff = off;
                    bestKey = s.Key;
                }
            }
            return bestKey;
        }

        // ============================================================ dimensions
        /// <summary>A plan direction with its sign fixed (pointing +X, or +Y when vertical), so hangers facing either way
        /// along a run agree.</summary>
        public static V3 CanonicalDir(V3 d)
        {
            V3 n = FhaCore.VNorm(new V3(d.X, d.Y, 0.0));
            if (n.X < -1e-6 || (Math.Abs(n.X) <= 1e-6 && n.Y < 0))
                n = new V3(-n.X, -n.Y, 0.0);
            return n;
        }

        private class RunGroupAcc
        {
            public V3 Dir;
            public double Off;
            public List<KeyValuePair<double, long>> Members = new List<KeyValuePair<double, long>>();
        }

        /// <summary>One group per straight line of hangers (same direction, same line within lineTolFt), 2 or more,
        /// each with the keys sorted along the run.</summary>
        public static List<RunGroup> GroupRuns(IEnumerable<RunHanger> hangers, double lineTolFt, double angleTolDeg = 3.0)
        {
            var groups = new List<RunGroupAcc>();
            double cosTol = Math.Cos(angleTolDeg * (Math.PI / 180.0));
            foreach (RunHanger h in hangers)
            {
                V3 d = CanonicalDir(h.Along);
                if (d.X == 0.0 && d.Y == 0.0 && d.Z == 0.0) continue;
                double nx = -d.Y, ny = d.X;
                double off = h.P.X * nx + h.P.Y * ny;
                double s = h.P.X * d.X + h.P.Y * d.Y;
                RunGroupAcc home = null;
                foreach (RunGroupAcc g in groups)
                {
                    if (Math.Abs(g.Dir.X * d.X + g.Dir.Y * d.Y) >= cosTol && Math.Abs(g.Off - off) <= lineTolFt)
                    {
                        home = g;
                        break;
                    }
                }
                if (home == null)
                {
                    var g = new RunGroupAcc { Dir = d, Off = off };
                    g.Members.Add(new KeyValuePair<double, long>(s, h.Key));
                    groups.Add(g);
                }
                else home.Members.Add(new KeyValuePair<double, long>(s, h.Key));
            }
            var o = new List<RunGroup>();
            foreach (RunGroupAcc g in groups)
            {
                if (g.Members.Count >= 2)
                {
                    var sorted = g.Members.ToList();
                    sorted.Sort((x, y) => x.Key != y.Key ? x.Key.CompareTo(y.Key) : x.Value.CompareTo(y.Value));
                    var rg = new RunGroup { Dir = g.Dir };
                    foreach (var m in sorted) rg.Keys.Add(m.Value);
                    o.Add(rg);
                }
            }
            return o;
        }

        /// <summary>Which centre reference of a family instance is square to the run: CenterLeftRight is the plane across
        /// the family's X (hand), CenterFrontBack across its Y (facing). The one whose normal lies along the run wins.
        /// (Only x and y of each vector are used.)</summary>
        public static string ReferenceTypeAcross(V3 hand, V3 facing, V3 along)
        {
            double h = Math.Abs(hand.X * along.X + hand.Y * along.Y);
            double f = Math.Abs(facing.X * along.X + facing.Y * along.Y);
            return h >= f ? "CenterLeftRight" : "CenterFrontBack";
        }

        // ============================================================ insulation
        /// <summary>The size a hanger has to fit. Outside insulation (the default) the hanger wraps the insulated duct:
        /// width + 2t, depth + 2t, so the invert it sits on drops by t. Inside, it fits the bare duct. Returns a new
        /// section; BareWidth / BareDepth keep the duct's own size.</summary>
        public static Section ApplyInsulation(Section sec, bool outside)
        {
            double t = sec.Ins;
            Section o = sec.Clone();
            o.BareWidth = sec.Width;
            o.BareDepth = sec.Depth;
            o.InsUsed = outside && t > 0;
            if (o.InsUsed)
            {
                o.Width = sec.Width + 2.0 * t;
                o.Depth = sec.Depth + 2.0 * t;
            }
            return o;
        }

        // ===================================================== grouped services
        public const double BundleZMm = 50.0;       // bottoms within this of each other
        public const double BundleGapMm = 500.0;    // clear gap in plan between neighbours under this
        public const double BundleAngleDeg = 2.0;   // counts as parallel
        public static readonly List<KeyValuePair<string, string>> Centres = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("mean", "Mean of the service centres"),
            new KeyValuePair<string, string>("edges", "Middle of the outer edges"),
        };

        /// <summary>The rules for services the user selected to hang together: no gap or height limit (they were
        /// chosen), only parallel and alongside count.</summary>
        public static GroupRules WrapRules(GroupRules rules)
        {
            return new GroupRules(1.0e9, 1.0e9, rules.AngleDeg, rules.Centre);
        }

        /// <summary>(z_tol_ft, gap_tol_ft, angle_deg, centre) from the Hanger rules settings.</summary>
        public static GroupRules GroupRulesFrom(IDictionary<string, string> settings)
        {
            string centre;
            if (!settings.TryGetValue("fam_group_centre", out centre) || (centre != "mean" && centre != "edges")) centre = "mean";
            return new GroupRules(FhaCore.AsFloat(settings, "fam_group_z", BundleZMm) / MM,
                                  FhaCore.AsFloat(settings, "fam_group_gap", BundleGapMm) / MM,
                                  FhaCore.AsFloat(settings, "fam_group_angle", BundleAngleDeg),
                                  centre);
        }

        private class BundleRow
        {
            public long Key;
            public double Off, W, Bottom, Top;
            public bool Lead;
        }

        public static HangerBundle Bundle(V3 point, IList<BundleMember> members, double zTolFt = BundleZMm / MM, double gapTolFt = BundleGapMm / MM,
                                    double angleDeg = BundleAngleDeg, string centre = "mean")
        {
            // One hanger round several services.
            //
            // members: [(key, a, b, width, depth)] with the sizes the hanger has to fit (insulation already applied);
            // members[0] is the service the hanger was placed for (the lead), `point` is on or near its centreline.
            //
            // A service joins when it is parallel to the lead (within angle_deg), runs alongside it at this point, its
            // clear gap in plan to the group's nearest edge is under gap_tol_ft (chained neighbour to neighbour), and every
            // bottom in the group stays within z_tol_ft of the others.
            //
            // The hanger is centred on the mean of the members' centres ('mean'), or midway between the outer edges
            // ('edges'); ext_neg / ext_pos are how far it must reach either side of that centre (along `across`, the
            // lead's plan normal) to the outer edges. It sits at the lowest bottom.
            //
            // Returns keys, width, ext_neg, ext_pos, across, bottom, top, point, a, b, notes; a / b are the lead's
            // centreline moved to the hanger centre and down to the lowest bottom, so the hanger can be fitted to it
            // like a single service of depth 0.
            BundleMember m0 = members[0];
            V3 a0 = m0.A, b0 = m0.B;
            V3 along, across;
            PlanDirs(a0, b0, out along, out across);
            V3 q0 = OnLine(a0, b0, point);
            double cosTol = Math.Cos(angleDeg * (Math.PI / 180.0));
            var rows = new List<BundleRow>();
            var notes = new List<string>();
            for (int i = 0; i < members.Count; i++)
            {
                BundleMember m = members[i];
                if (i != 0)
                {
                    V3 dd, dn;
                    PlanDirs(m.A, m.B, out dd, out dn);
                    if (Math.Abs(dd.X * along.X + dd.Y * along.Y) < cosTol)
                    {
                        notes.Add(L(m.Key) + ": not parallel");
                        continue;
                    }
                    double t = LineParam(m.A, m.B, q0);
                    if (t < -1e-6 || t > 1.0 + 1e-6)
                    {
                        notes.Add(L(m.Key) + ": does not run alongside here");
                        continue;
                    }
                }
                V3 q = OnLine(m.A, m.B, q0);
                double off = (q.X - q0.X) * across.X + (q.Y - q0.Y) * across.Y;
                rows.Add(new BundleRow { Key = m.Key, Off = off, W = m.Width, Bottom = q.Z - m.Depth / 2.0, Top = q.Z + m.Depth / 2.0, Lead = i == 0 });
            }
            rows = rows.Select((r, idx) => new { r, idx }).OrderBy(z => z.r.Off).ThenBy(z => z.idx).Select(z => z.r).ToList();   // stable sort on off
            int li = 0;
            for (int i = 0; i < rows.Count; i++) if (rows[i].Lead) { li = i; break; }
            int lo = li, hi = li;
            var bottoms = new List<double> { rows[li].Bottom };

            Func<int, int, double> gap = (i, j) => (rows[j].Off - rows[j].W / 2.0) - (rows[i].Off + rows[i].W / 2.0);   // clear gap between rows i < j

            while (true)
            {
                var options = new List<KeyValuePair<double, string>>();
                if (lo > 0) options.Add(new KeyValuePair<double, string>(gap(lo - 1, lo), "lo"));
                if (hi < rows.Count - 1) options.Add(new KeyValuePair<double, string>(gap(hi, hi + 1), "hi"));
                options.Sort((x, y) => x.Key != y.Key ? x.Key.CompareTo(y.Key) : string.CompareOrdinal(x.Value, y.Value));
                bool grown = false;
                foreach (var opt in options)
                {
                    double g = opt.Key;
                    string side = opt.Value;
                    int j = side == "lo" ? lo - 1 : hi + 1;
                    var nb = new List<double>(bottoms) { rows[j].Bottom };
                    if (g < gapTolFt && nb.Max() - nb.Min() <= zTolFt + 1e-9)
                    {
                        bottoms = nb;
                        if (side == "lo") lo = j;
                        else hi = j;
                        grown = true;
                        break;
                    }
                }
                if (!grown) break;
            }
            var group = rows.GetRange(lo, hi - lo + 1);
            for (int i = 0; i < rows.Count; i++)
            {
                BundleRow r = rows[i];
                if ((lo <= i && i <= hi) || r.Lead) continue;
                int near = i < lo ? lo - 1 : hi + 1;
                double g = i < lo ? gap(i, lo) : gap(hi, i);
                var nb = new List<double>(bottoms) { r.Bottom };
                var why = new List<string>();
                if (i == near && g >= gapTolFt)
                    why.Add("gap " + F0(g * MM) + " mm (limit " + F0(gapTolFt * MM) + ")");
                if (nb.Max() - nb.Min() > zTolFt + 1e-9)
                    why.Add("height differs by " + F0((nb.Max() - nb.Min()) * MM) + " mm (limit " + F0(zTolFt * MM) + ")");
                notes.Add(L(r.Key) + ": left out - " + (why.Count > 0 ? string.Join(", ", why) : "beyond a service that was left out"));
            }
            double left = group.Min(r => r.Off - r.W / 2.0);
            double right = group.Max(r => r.Off + r.W / 2.0);
            double c;
            if (centre == "edges" || group.Count == 1) c = (left + right) / 2.0;
            else
            {
                double sum = 0.0;
                foreach (BundleRow r in group) sum += r.Off;
                c = sum / (double)group.Count;
            }
            double bottom = bottoms.Min();
            double dz = bottom - q0.Z;
            V3 shift = new V3(across.X * c, across.Y * c, dz);
            var res = new HangerBundle
            {
                Width = right - left,
                ExtNeg = c - left,
                ExtPos = right - c,
                Across = across,
                Bottom = bottom,
                Top = group.Max(r => r.Top),
                Notes = notes,
                Point = new V3(q0.X + shift.X, q0.Y + shift.Y, bottom),
                A = FhaCore.VAdd(a0, shift),
                B = FhaCore.VAdd(b0, shift),
            };
            foreach (BundleRow r in group) res.Keys.Add(r.Key);
            return res;
        }

        /// <summary>The section the hanger fitting code uses.
        /// A single service (no neighbours joined) keeps its OWN section - round flag, depth, insulation - so it is fitted
        /// and locked exactly like a hanger placed with no pre-selection. A group becomes depth 0 on a line at the lowest
        /// bottom, carrying how far to reach either side of its centre.</summary>
        public static Section BundleSection(HangerBundle b, Section leadSec)
        {
            if (b.Keys.Count <= 1)
            {
                Section s = leadSec.Clone();
                s.Keys = new List<long>(b.Keys);
                return s;
            }
            return new Section
            {
                A = b.A, B = b.B, Width = b.Width, Depth = 0.0, Round = false,
                Ins = leadSec.Ins, InsUsed = leadSec.InsUsed,
                BareWidth = b.Width, BareDepth = 0.0, Keys = b.Keys,
                ExtNeg = b.ExtNeg, ExtPos = b.ExtPos, Across = b.Across,
                SpanHeight = b.Top - b.Bottom,
            };
        }

        /// <summary>Where the hanger goes: a group's centre at its lowest bottom, or a single service's own centreline
        /// (its invert follows from its depth).</summary>
        public static V3 BundlePoint(HangerBundle b, Section leadSec, V3 point)
        {
            if (b.Keys.Count <= 1) return OnLine(leadSec.A, leadSec.B, point);
            return b.Point;
        }

        // ===================================================== equipment / accessories
        private static bool Unit2(V3 v, out double x, out double y)
        {
            double len = Math.Sqrt(v.X * v.X + v.Y * v.Y);
            if (len > 1e-9) { x = v.X / len; y = v.Y / len; return true; }
            x = y = 0;
            return false;
        }

        /// <summary>A 'service' for a hanger under a unit (mechanical equipment or a duct accessory): the hanger spans
        /// ACROSS the unit at its bottom face.
        /// hand / facing: the unit's plan axes; pts: points on its geometry (world); bottomZ: its lowest downward face
        /// (else the lowest point); runHint: a plan direction the unit runs along (its in-line connectors), else the longer
        /// side; pick: where the user clicked (unused, as in the Python).
        /// Returns a section like a duct's (a, b through the unit's centre across, width across, depth so the invert is
        /// the bottom face) plus Unit, RunFrom, Length, Bottom.</summary>
        public static Section UnitSection(V3 hand, V3 facing, IList<V3> pts, double? bottomZ = null, V3? runHint = null, V3? pick = null)
        {
            double hx, hy, fx, fy;
            if (!Unit2(hand, out hx, out hy)) { hx = 1.0; hy = 0.0; }
            if (!Unit2(facing, out fx, out fy)) { fx = 0.0; fy = 1.0; }
            double ehMin = pts.Min(p => p.X * hx + p.Y * hy), ehMax = pts.Max(p => p.X * hx + p.Y * hy);
            double efMin = pts.Min(p => p.X * fx + p.Y * fy), efMax = pts.Max(p => p.X * fx + p.Y * fy);
            string runFrom = "longer side";
            bool hasHint = false;
            double ix = 0, iy = 0;
            if (runHint != null) hasHint = Unit2(runHint.Value, out ix, out iy);
            bool runIsH;
            if (hasHint)
            {
                runIsH = Math.Abs(ix * hx + iy * hy) >= Math.Abs(ix * fx + iy * fy);
                runFrom = "its connectors";
            }
            else runIsH = (ehMax - ehMin) >= (efMax - efMin);
            double rx, ry, runMin, runMax, ax, ay, acMin, acMax;
            if (runIsH) { rx = hx; ry = hy; runMin = ehMin; runMax = ehMax; ax = fx; ay = fy; acMin = efMin; acMax = efMax; }
            else { rx = fx; ry = fy; runMin = efMin; runMax = efMax; ax = hx; ay = hy; acMin = ehMin; acMax = ehMax; }
            double zMin = pts.Min(p => p.Z), zMax = pts.Max(p => p.Z);
            double bottom = bottomZ == null ? zMin : bottomZ.Value;
            double top = zMax;
            if (top - bottom < 1e-6) top = bottom + 1e-3;
            double zc = (bottom + top) / 2.0;
            double cAc = (acMin + acMax) / 2.0;
            Func<double, V3> at = s => new V3(rx * s + ax * cAc, ry * s + ay * cAc, zc);
            V3 a = at(runMin), b = at(runMax);
            double width = acMax - acMin;
            return new Section
            {
                A = a, B = b, Width = width, Depth = top - bottom, Round = false,
                Ins = 0.0, InsUsed = false, BareWidth = width, BareDepth = top - bottom,
                Unit = true, RunFrom = runFrom, Length = runMax - runMin, Bottom = bottom,
            };
        }

        /// <summary>Plan direction (z = 0) of an in-line unit from its connectors: two horizontal connectors facing
        /// opposite ways. Null if there is no pair.</summary>
        public static V3? InlineDirection(IList<InlineConn> conns)
        {
            var flat = conns.Where(c => Math.Abs(c.Basis.Z) < 0.1).ToList();
            for (int i = 0; i < flat.Count; i++)
                for (int j = i + 1; j < flat.Count; j++)
                {
                    V3 d1 = flat[i].Basis, d2 = flat[j].Basis;
                    if (d1.X * d2.X + d1.Y * d2.Y < -0.9) return new V3(d1.X, d1.Y, 0.0);
                }
            return null;
        }

        /// <summary>(left, right) stretch values. A single service: half its width each side. A group: the family's
        /// positive-axis side ('right', or 'left' when swapped) reaches the group's edge on that side, the other the
        /// opposite edge. axisVec: the family's axis in plan (x, y used).</summary>
        public static void SideValues(Section sec, V3 axisVec, double clearanceFt, out double left, out double right, bool swap = false)
        {
            if (sec.ExtNeg == null)
            {
                double h = sec.Width / 2.0 + clearanceFt;
                left = h; right = h;
                return;
            }
            V3 ac = sec.Across.Value;
            double s = axisVec.X * ac.X + axisVec.Y * ac.Y;
            double pos, neg;
            if (s >= 0) { pos = sec.ExtPos.Value; neg = sec.ExtNeg.Value; }
            else { pos = sec.ExtNeg.Value; neg = sec.ExtPos.Value; }
            double l = neg + clearanceFt, r = pos + clearanceFt;
            if (swap) { left = r; right = l; }
            else { left = l; right = r; }
        }

        // ============================================================ drop rods
        /// <summary>Drop rod from the hanger's reference level up to a target's underside.</summary>
        public static double? RodToTarget(double refZ, double? targetZ)
        {
            return RodLength(refZ, targetZ);
        }

        /// <summary>(positive, negative) reach of a hanger across the run, from the plan corners of its bounding box,
        /// measured from its centre point.</summary>
        public static void Reaches(IEnumerable<V3> corners, V3 centre, V3 across, out double positive, out double negative)
        {
            var proj = corners.Select(c => (c.X - centre.X) * across.X + (c.Y - centre.Y) * across.Y).ToList();
            positive = proj.Max();
            negative = -proj.Min();
        }

        /// <summary>True when the hanger came out the wrong way round: its long side is on the side that should be short.
        /// Families differ in which of their two stretch parameters points which way, so this is measured, not assumed.</summary>
        public static bool SidesMirrored(double reachPos, double reachNeg, double wantPos, double wantNeg, double tolFt = 1.0 / MM)
        {
            double asIs = Math.Abs(reachPos - wantPos) + Math.Abs(reachNeg - wantNeg);
            double swapped = Math.Abs(reachPos - wantNeg) + Math.Abs(reachNeg - wantPos);
            return swapped + tolFt < asIs;
        }
    }
}
