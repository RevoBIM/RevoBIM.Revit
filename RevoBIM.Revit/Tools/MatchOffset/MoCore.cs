using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

namespace RevoBIM.Tools.MatchOffset
{
    /// <summary>One row of the category table: settings key, label, BuiltInCategory name, group, on by default.</summary>
    public sealed class MoCategory
    {
        public string Key, Label, Bic, Group;
        public bool On;

        public MoCategory(string key, string label, string bic, string group, bool on)
        {
            Key = key;
            Label = label;
            Bic = bic;
            Group = group;
            On = on;
        }
    }

    /// <summary>
    /// Match Offset: version, settings, logging and the pure maths. Nothing in this file touches Revit or WPF.
    /// Port of mo_core.py (pyRevit tool version 1.18.0). Settings live in %AppData%\RevoBIM\match_offset.txt, the
    /// same file and keys as the pyRevit tool.
    /// </summary>
    public static class MoCore
    {
        public const string Version = "1.18.0";
        public const string ToolName = "Match Offset";

        public const int SettingsVersion = 7;
        public const string SettingsFile = "match_offset.txt";
        public const string LogFile = "match_offset.log";
        public const string ErrorFile = "match_offset_last_error.txt";
        public const string DebugFile = "match_offset_debug.txt";

        public const double MmPerFt = 304.8;
        public const double Eps = 1e-6;
        public const double TolMm = 0.1;
        public const double TolFt = TolMm / MmPerFt;

        public const string AnchorBottom = "bottom";
        public const string AnchorMiddle = "middle";
        public const string AnchorTop = "top";

        public static string AnchorLabel(string anchor)
        {
            switch (anchor)
            {
                case AnchorBottom: return "Bottom";
                case AnchorMiddle: return "Middle";
                case AnchorTop: return "Top";
                default: return anchor;
            }
        }

        // ======================================================================
        // build info, for the debug header: one pasted report says which build ran
        // ======================================================================

        public static string BuildInfo()
        {
            try
            {
                Assembly assembly = typeof(MoCore).Assembly;
                string path = assembly.Location;
                string written = "";
                try
                {
                    written = File.GetLastWriteTime(path).ToString("yyyy-MM-dd HH:mm:ss");
                }
                catch (Exception)
                {
                }
                string date = "";
                string revit = "";
                foreach (AssemblyMetadataAttribute meta in assembly.GetCustomAttributes(typeof(AssemblyMetadataAttribute), false))
                {
                    if (meta.Key == "BuildDate") date = meta.Value;
                    if (meta.Key == "RevitVersion") revit = meta.Value;
                }
                string info = assembly.GetName().Version == null ? "?" : assembly.GetName().Version.ToString(3);
                return "add-in " + info + " | built " + date + " | Revit " + revit + " build | " + path + " (written " + written + ")";
            }
            catch (Exception)
            {
                return "build info unavailable";
            }
        }

        // ======================================================================
        // text and numbers
        // ======================================================================

        public static double FtToMm(double ft) { return ft * MmPerFt; }
        public static double MmToFt(double mm) { return mm / MmPerFt; }

        /// <summary>A millimetre value as it reads in a prompt or a report: trailing zeros trimmed.</summary>
        public static string FormatMm(double value, int places = 1)
        {
            if (double.IsNaN(value) || double.IsInfinity(value)) return "?";
            if (Math.Abs(value) < 0.05) value = 0.0;
            string text = value.ToString("F" + places, System.Globalization.CultureInfo.InvariantCulture);
            if (text.Contains(".")) text = text.TrimEnd('0').TrimEnd('.');
            if (text == "" || text == "-") text = "0";
            return text;
        }

        /// <summary>A number out of a settings value or a text box, or null.</summary>
        public static double? ParseNumber(string text)
        {
            string raw = (text ?? "").Trim().Replace(",", "");
            if (raw.Length == 0) return null;
            if (raw.EndsWith("mm", StringComparison.OrdinalIgnoreCase)) raw = raw.Substring(0, raw.Length - 2).Trim();
            double value;
            if (double.TryParse(raw, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out value)) return value;
            return null;
        }

        public static double ParseNumber(string text, double fallback)
        {
            double? value = ParseNumber(text);
            return value.HasValue ? value.Value : fallback;
        }

        // ======================================================================
        // the rounding rule
        // ======================================================================

        public const string RoundUp = "up";
        public const string RoundNearest = "nearest";
        public const string RoundDown = "down";

        /// <summary>
        /// Round a millimetre value to a multiple of step. A step of zero or less is no rounding. "Up" means
        /// towards plus infinity; a value already on a multiple is left alone (the epsilon stops 2450.0000000001
        /// being pushed to 2475).
        /// </summary>
        public static double RoundValue(double valueMm, double stepMm, string mode)
        {
            if (stepMm <= 0.0) return valueMm;
            double quotient = valueMm / stepMm;
            double count;
            if (mode == RoundDown) count = Math.Floor(quotient + Eps);
            else if (mode == RoundNearest) count = Math.Floor(quotient + 0.5 + Eps);
            else count = Math.Ceiling(quotient - Eps);
            return count * stepMm;
        }

        // ======================================================================
        // anchors, slopes and deltas
        // ======================================================================

        public static double AnchorValue(double bottom, double middle, double top, string anchor)
        {
            if (anchor == AnchorBottom) return bottom;
            if (anchor == AnchorTop) return top;
            return middle;
        }

        public static double SlopeDegrees(double rise, double run)
        {
            rise = Math.Abs(rise);
            run = Math.Abs(run);
            if (run < Eps) return rise > Eps ? 90.0 : 0.0;
            return Math.Atan2(rise, run) * 180.0 / Math.PI;
        }

        public sealed class Datum
        {
            public double DatumFt, RawMm, RoundedMm;
            public bool WasRounded;
        }

        /// <summary>
        /// Turn the source element's own elevations into the datum to apply. Rounding on the "level" datum works
        /// on the offset from the element's own reference level (the number in the properties palette); on
        /// "project" it works on the project elevation.
        /// </summary>
        public static Datum CaptureDatum(double bottom, double middle, double top, string anchor, double levelElevationFt,
                                         double stepMm, string mode, string datum)
        {
            double raw = AnchorValue(bottom, middle, top, anchor);
            double baseFt = datum == "level" ? levelElevationFt : 0.0;
            var result = new Datum();
            result.RawMm = FtToMm(raw - baseFt);
            result.RoundedMm = RoundValue(result.RawMm, stepMm, mode);
            result.WasRounded = Math.Abs(result.RoundedMm - result.RawMm) > TolMm;
            result.DatumFt = baseFt + MmToFt(result.RoundedMm);
            return result;
        }

        /// <summary>How far up (positive) this element has to move to meet the datum.</summary>
        public static double DeltaFor(double bottom, double middle, double top, string anchor, double datumFt)
        {
            return datumFt - AnchorValue(bottom, middle, top, anchor);
        }

        // ======================================================================
        // categories
        // ======================================================================

        public const string Pipework = "Pipework";
        public const string Ductwork = "Ductwork";
        public const string Electrical = "Electrical";
        public const string Fire = "Fire and safety";
        public const string Equipment = "Equipment and fixtures";
        public const string Fabrication = "Fabrication and supports";
        public const string Other = "Structure and architecture";

        public static readonly string[] CategoryGroups = { Pipework, Ductwork, Electrical, Fire, Equipment, Fabrication, Other };

        // The BuiltInCategory name is resolved late, by name, so a category a release does not have (Fire Protection,
        // Audio Visual Devices, Plumbing Equipment and MEP Ancillary Framing arrived at different releases) is skipped
        // rather than taking the tool down. The structural and architectural ones at the end are off by default.
        public static readonly MoCategory[] CategoryDefs =
        {
            new MoCategory("pipes", "Pipes", "OST_PipeCurves", Pipework, true),
            new MoCategory("flex_pipes", "Flex pipes", "OST_FlexPipeCurves", Pipework, true),
            new MoCategory("pipe_fittings", "Pipe fittings", "OST_PipeFitting", Pipework, true),
            new MoCategory("pipe_accessories", "Pipe accessories", "OST_PipeAccessory", Pipework, true),
            new MoCategory("pipe_insulation", "Pipe insulation", "OST_PipeInsulations", Pipework, true),
            new MoCategory("plumbing_fixtures", "Plumbing fixtures", "OST_PlumbingFixtures", Pipework, true),
            new MoCategory("plumbing_equipment", "Plumbing equipment", "OST_PlumbingEquipment", Pipework, true),

            new MoCategory("ducts", "Ducts", "OST_DuctCurves", Ductwork, true),
            new MoCategory("flex_ducts", "Flex ducts", "OST_FlexDuctCurves", Ductwork, true),
            new MoCategory("duct_fittings", "Duct fittings", "OST_DuctFitting", Ductwork, true),
            new MoCategory("duct_accessories", "Duct accessories", "OST_DuctAccessory", Ductwork, true),
            new MoCategory("air_terminals", "Air terminals", "OST_DuctTerminal", Ductwork, true),
            new MoCategory("duct_insulation", "Duct insulation", "OST_DuctInsulations", Ductwork, true),
            new MoCategory("duct_lining", "Duct lining", "OST_DuctLinings", Ductwork, true),
            new MoCategory("mech_equipment", "Mechanical equipment", "OST_MechanicalEquipment", Ductwork, true),
            new MoCategory("mech_control_devices", "Mechanical control devices", "OST_MechanicalControlDevices", Ductwork, true),

            new MoCategory("cable_trays", "Cable trays", "OST_CableTray", Electrical, true),
            new MoCategory("cable_tray_fittings", "Cable tray fittings", "OST_CableTrayFitting", Electrical, true),
            new MoCategory("conduits", "Conduits", "OST_Conduit", Electrical, true),
            new MoCategory("conduit_fittings", "Conduit fittings", "OST_ConduitFitting", Electrical, true),
            new MoCategory("elec_equipment", "Electrical equipment", "OST_ElectricalEquipment", Electrical, true),
            new MoCategory("elec_fixtures", "Electrical fixtures", "OST_ElectricalFixtures", Electrical, true),
            new MoCategory("lighting_fixtures", "Lighting fixtures", "OST_LightingFixtures", Electrical, true),
            new MoCategory("lighting_devices", "Lighting devices", "OST_LightingDevices", Electrical, true),
            new MoCategory("data_devices", "Data devices", "OST_DataDevices", Electrical, true),
            new MoCategory("comm_devices", "Communication devices", "OST_CommunicationDevices", Electrical, true),
            new MoCategory("telephone_devices", "Telephone devices", "OST_TelephoneDevices", Electrical, true),
            new MoCategory("audio_visual", "Audio visual devices", "OST_AudioVisualDevices", Electrical, true),

            new MoCategory("sprinklers", "Sprinklers", "OST_Sprinklers", Fire, true),
            new MoCategory("fire_protection", "Fire protection", "OST_FireProtection", Fire, true),
            new MoCategory("fire_alarm_devices", "Fire alarm devices", "OST_FireAlarmDevices", Fire, true),
            new MoCategory("security_devices", "Security devices", "OST_SecurityDevices", Fire, true),
            new MoCategory("nurse_call_devices", "Nurse call devices", "OST_NurseCallDevices", Fire, true),

            new MoCategory("specialty_equipment", "Specialty equipment", "OST_SpecialityEquipment", Equipment, true),
            new MoCategory("medical_equipment", "Medical equipment", "OST_MedicalEquipment", Equipment, true),
            new MoCategory("food_service", "Food service equipment", "OST_FoodServiceEquipment", Equipment, true),
            new MoCategory("generic_models", "Generic models", "OST_GenericModel", Equipment, true),
            new MoCategory("casework", "Casework", "OST_Casework", Equipment, false),
            new MoCategory("furniture", "Furniture", "OST_Furniture", Equipment, false),
            new MoCategory("furniture_systems", "Furniture systems", "OST_FurnitureSystems", Equipment, false),

            new MoCategory("fab_ductwork", "Fabrication ductwork", "OST_FabricationDuctwork", Fabrication, true),
            new MoCategory("fab_pipework", "Fabrication pipework", "OST_FabricationPipework", Fabrication, true),
            new MoCategory("fab_containment", "Fabrication containment", "OST_FabricationContainment", Fabrication, true),
            new MoCategory("fab_hangers", "Fabrication hangers", "OST_FabricationHangers", Fabrication, true),
            // the support steel modelled in MEP (strut, channel, trapeze bars)
            new MoCategory("mep_ancillary_framing", "MEP ancillary framing", "OST_MEPAncillaryFraming", Fabrication, true),

            new MoCategory("structural_framing", "Structural framing", "OST_StructuralFraming", Other, false),
            new MoCategory("structural_columns", "Structural columns", "OST_StructuralColumns", Other, false),
            new MoCategory("columns", "Columns", "OST_Columns", Other, false),
            new MoCategory("structural_foundations", "Structural foundations", "OST_StructuralFoundation", Other, false),
            new MoCategory("stairs", "Stairs", "OST_Stairs", Other, false),
            new MoCategory("railings", "Railings", "OST_StairsRailing", Other, false),
        };

        public static readonly string[] CategoryKeys = CategoryDefs.Select(c => c.Key).ToArray();
        public static readonly string[] DefaultCategoryKeys = CategoryDefs.Where(c => c.On).Select(c => c.Key).ToArray();

        // Categories placed as a point rather than drawn as a run: what they sit at is their own level offset (the
        // insertion point), not the extent of whatever their family draws.
        public static readonly HashSet<string> PointBasedKeys = new HashSet<string>
        {
            "plumbing_fixtures", "plumbing_equipment", "air_terminals", "mech_equipment", "mech_control_devices",
            "elec_equipment", "elec_fixtures", "lighting_fixtures", "lighting_devices",
            "data_devices", "comm_devices", "telephone_devices", "audio_visual",
            "sprinklers", "fire_protection", "fire_alarm_devices", "security_devices", "nurse_call_devices",
            "specialty_equipment", "medical_equipment", "food_service",
            "casework", "furniture", "furniture_systems",
        };

        public const string FromInsertion = "insertion";
        public const string FromSolid = "solid";
        public const string FromBox = "box";
        public const string FromParameters = "parameters";
        public const string FromBearing = "bearing";
        public const string FromTop = "top";

        public static readonly HashSet<string> FabKeys = new HashSet<string> { "fab_ductwork", "fab_pipework", "fab_containment", "fab_hangers" };
        public static readonly HashSet<string> HangerKeys = new HashSet<string> { "fab_hangers" };
        public static readonly HashSet<string> FramingKeys = new HashSet<string> { "mep_ancillary_framing" };

        public static bool IsPointBased(string key) { return PointBasedKeys.Contains(key); }
        public static bool IsFabrication(string key) { return FabKeys.Contains(key); }
        public static bool IsHanger(string key) { return HangerKeys.Contains(key); }
        public static bool IsFraming(string key) { return FramingKeys.Contains(key); }

        public static List<MoCategory> CategoriesIn(string group) { return CategoryDefs.Where(c => c.Group == group).ToList(); }

        /// <summary>
        /// What a hanger rod has to become when the hanger moves: the top stays and the bottom goes with the hanger.
        /// Null where there is no rod left (a hanger raised further than its rods are long).
        /// </summary>
        public static double? RodLengthAfter(double length, double delta)
        {
            double wanted = length - delta;
            return wanted <= 0.0 ? (double?)null : wanted;
        }

        /// <summary>Which way a family's offset from host runs, from one trial write: +1 as asked, -1 the other way, 0 neither.</summary>
        public static int HostOffsetDirection(double asked, double moved)
        {
            double tol = TolFt * 10;
            if (Math.Abs(asked) <= tol) return 0;
            if (Math.Abs(moved - asked) <= tol) return 1;
            if (Math.Abs(moved + asked) <= tol) return -1;
            return 0;
        }

        public static string LevelOffsetText(string name, double bottomAbsFt, double levelAbsFt, string label)
        {
            double above = FtToMm(bottomAbsFt - levelAbsFt);
            return name + ": " + label.ToLowerInvariant() + " now " + FormatMm(above) + " mm above its own level";
        }

        // ---- hanger geometry: which piece is the bearer and which the rods ----

        public const double UprightRatio = 1.5;
        public const double BearerShare = 0.15;
        public const double FaceShare = 0.02;
        public const double HeadFt = 150.0 / MmPerFt;

        /// <summary>One solid of a hanger: lowest and highest point, plan span, plan area and its flat faces (upness, area, height).</summary>
        public sealed class HangerMember
        {
            public double Low, High, Span, Area;
            public List<double[]> Faces = new List<double[]>();
        }

        /// <summary>A rod, a drop, a riser clamp: taller than it is wide. A bearer is wider than it is tall.</summary>
        public static bool IsUpright(double low, double high, double span, double ratio = UprightRatio)
        {
            double rise = high - low;
            if (span <= 0.0) return rise > 0.0;
            return rise > ratio * span;
        }

        /// <summary>
        /// The top of a hanger's bearer, told apart from the rest of the hanger: throw away the rods, keep the broad
        /// pieces at the foot of them, take the highest real face among those. Null where the geometry does not come
        /// in pieces that can be told apart.
        /// </summary>
        public static double? BearingFromMembers(List<HangerMember> members, double minNormalZ = 0.9)
        {
            if (members == null || members.Count < 2) return null;

            var uprights = new List<double[]>();
            var bearers = new List<HangerMember>();
            foreach (HangerMember member in members)
            {
                if (IsUpright(member.Low, member.High, member.Span)) uprights.Add(new[] { member.Low, member.High });
                else bearers.Add(member);
            }
            if (bearers.Count == 0) return null;

            double biggest = 0.0;
            foreach (HangerMember bearer in bearers) if (bearer.Area > biggest) biggest = bearer.Area;
            if (biggest <= 0.0) return null;

            // Anything up at the structure is an anchor, not a bearer. The rods say where the structure is.
            double? ceiling = null;
            if (uprights.Count > 0)
            {
                double? foot = null;
                double longest = 0.0;
                foreach (double[] rod in uprights)
                {
                    if (foot == null || rod[0] < foot.Value) foot = rod[0];
                    if (rod[1] - rod[0] > longest) longest = rod[1] - rod[0];
                }
                ceiling = foot.Value + Math.Max(HeadFt, 0.25 * longest);
            }

            double? best = null;
            foreach (HangerMember bearer in bearers)
            {
                if (bearer.Area < BearerShare * biggest) continue;
                if (ceiling.HasValue && bearer.Low > ceiling.Value) continue;
                foreach (double[] face in bearer.Faces)
                {
                    if (face[0] < minNormalZ) continue;
                    if (face[1] < FaceShare * biggest) continue;
                    if (best == null || face[2] > best.Value) best = face[2];
                }
            }
            return best;
        }

        /// <summary>The top of a hanger where it is one lump: the biggest upward-facing flat surface it has.</summary>
        public static double? BestBearing(List<double[]> faces, double minNormalZ = 0.9)
        {
            double? bestArea = null;
            double height = 0.0;
            foreach (double[] face in faces)
            {
                if (face[0] < minNormalZ) continue;
                if (bestArea == null || face[1] > bestArea.Value)
                {
                    bestArea = face[1];
                    height = face[2];
                }
            }
            return bestArea.HasValue ? (double?)height : null;
        }

        // ======================================================================
        // settings
        // ======================================================================

        public static readonly Dictionary<string, string> Defaults = new Dictionary<string, string>
        {
            { "settings_version", SettingsVersion.ToString() },
            { "theme", "auto" },                  // auto | dark | light
            { "round_step_mm", "0" },
            { "round_mode", RoundUp },            // up | nearest | down
            { "round_datum", "level" },           // level | project
            { "move_source_on_round", "on" },
            { "measure", "size" },                // size | box
            { "point_measure", "solid" },         // insertion | solid | box
            { "fab_measure", "parameters" },      // parameters | solid | box
            { "fab_hanger_top", "bearing" },      // bearing | solid | box
            { "fab_hanger_rods", "on" },
            { "framing_measure", "top" },         // top | solid | box
            { "include_insulation", "off" },
            { "sloped", "skip" },                 // skip | point
            { "slope_tol_deg", "0.5" },
            { "connected_fittings", "skip" },     // skip | move
            { "use_preselection", "off" },
            { "remember_datum", "off" },
            { "show_results", "problems" },       // problems | always | never
            { "debug_report", "on" },
            { "silent", "off" },
            { "categories", string.Join("|", DefaultCategoryKeys) },
            { "key_bottom", "AB" },
            { "key_middle", "AQ" },
            { "key_top", "AT" },
            { "key_slope", "AS" },

            // Match Offset Slope
            { "slope_match_slope", "on" },
            { "slope_source", "main" },           // main | fixed
            { "slope_fixed_n", "80" },
            { "slope_direction", "towards" },     // towards | away | keep
            { "slope_trim", "on" },
            { "slope_fitting", "auto" },          // auto | none
            { "slope_hand_fitting", "on" },
            { "slope_square_branch", "on" },
            { "slope_stub_mm", "0" },
            { "slope_apparent", "on" },
            { "slope_extend_main", "on" },
            { "slope_steep_deg", "46" },
            { "slope_limit", "400" },
            { "slope_end_tol_mm", "1" },
            { "slope_inline_deg", "2" },
            { "slope_in_line", "on" },
            { "slope_repeat", "pairs" },          // pairs | main
            { "slope_inline_offset_mm", "50" },
            { "shortcuts_path", "" },
            { "last_datum_ft", "" },
            { "last_datum_anchor", "" },
        };

        // Keys a version reset because their meaning changed.
        private static readonly SortedDictionary<int, string[]> Migrations = new SortedDictionary<int, string[]>
        {
            { 2, new[] { "move_source_on_round" } },
            { 3, new string[0] },
            { 4, new[] { "categories" } },
            { 5, new[] { "categories", "point_measure" } },
            { 6, new string[0] },
            { 7, new string[0] },
        };

        // Categories added since a version, ticked onto a saved list rather than resetting it.
        private static readonly SortedDictionary<int, string[]> AddedCategories = new SortedDictionary<int, string[]>
        {
            { 6, new[] { "mep_ancillary_framing" } },
        };

        public static string Get(Dictionary<string, string> settings, string key)
        {
            string value;
            if (settings != null && settings.TryGetValue(key, out value)) return value;
            return Defaults.TryGetValue(key, out value) ? value : "";
        }

        public static bool IsOn(Dictionary<string, string> settings, string key)
        {
            string value = Get(settings, key).Trim().ToLowerInvariant();
            return value == "on" || value == "1" || value == "true" || value == "yes";
        }

        public static string OnOff(bool flag) { return flag ? "on" : "off"; }

        public static bool IsSilent(Dictionary<string, string> settings) { return IsOn(settings, "silent"); }

        public static string AppDataDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string SettingsPath() { return Path.Combine(AppDataDir(), SettingsFile); }
        public static string LogPath() { return Path.Combine(AppDataDir(), LogFile); }
        public static string ErrorPath() { return Path.Combine(AppDataDir(), ErrorFile); }
        public static string DebugPath() { return Path.Combine(AppDataDir(), DebugFile); }

        public static bool EnsureDir()
        {
            try
            {
                Directory.CreateDirectory(AppDataDir());
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Plain key=value text to a dict, splitting on the first = only. Unknown keys are dropped.</summary>
        public static Dictionary<string, string> ParseSettings(string text)
        {
            var values = new Dictionary<string, string>(Defaults);
            foreach (string raw in (text ?? "").Replace("\r\n", "\n").Split('\n'))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#")) continue;
                int at = line.IndexOf('=');
                if (at < 0) continue;
                string key = line.Substring(0, at).Trim();
                if (key.Length == 0 || !Defaults.ContainsKey(key)) continue;
                values[key] = line.Substring(at + 1).Trim();
            }
            return values;
        }

        public static string WithCategories(string saved, IEnumerable<string> keys)
        {
            var have = (saved ?? "").Split('|').Where(k => k.Length > 0).ToList();
            foreach (string key in keys) if (!have.Contains(key)) have.Add(key);
            return string.Join("|", have);
        }

        /// <summary>Reset any key whose meaning changed since the file was written.</summary>
        public static Dictionary<string, string> Migrate(Dictionary<string, string> values)
        {
            int was = (int)ParseNumber(Get(values, "settings_version"), 0);
            foreach (KeyValuePair<int, string[]> step in Migrations)
            {
                if (was >= step.Key) continue;
                foreach (string key in step.Value) values[key] = Defaults.ContainsKey(key) ? Defaults[key] : "";
            }
            foreach (KeyValuePair<int, string[]> step in AddedCategories)
            {
                if (was < step.Key) values["categories"] = WithCategories(Get(values, "categories"), step.Value);
            }
            values["settings_version"] = SettingsVersion.ToString();
            return values;
        }

        public static Dictionary<string, string> LoadSettings()
        {
            try
            {
                string path = SettingsPath();
                if (File.Exists(path)) return Migrate(ParseSettings(File.ReadAllText(path, Encoding.UTF8)));
            }
            catch (Exception)
            {
            }
            return Migrate(new Dictionary<string, string>(Defaults));
        }

        public static bool SaveSettings(Dictionary<string, string> values)
        {
            try
            {
                EnsureDir();
                var lines = new List<string>();
                foreach (string key in Defaults.Keys.OrderBy(k => k, StringComparer.Ordinal))
                    lines.Add(key + "=" + Get(values, key));
                File.WriteAllText(SettingsPath(), string.Join("\n", lines) + "\n", new UTF8Encoding(false));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static List<string> EnabledCategories(Dictionary<string, string> values)
        {
            var keys = new List<string>();
            foreach (string part in Get(values, "categories").Split('|'))
            {
                string key = part.Trim();
                if (key.Length > 0 && CategoryKeys.Contains(key) && !keys.Contains(key)) keys.Add(key);
            }
            return keys;
        }

        // ======================================================================
        // logging
        // ======================================================================

        // Lines are buffered and written once at the end of a run: opening the file per element turned a hundred
        // matched elements into a hundred file handles.
        private static readonly List<string> LogBuffer = new List<string>();
        private const int LogFlushAt = 400;

        public static void Log(string message)
        {
            try
            {
                lock (LogBuffer)
                {
                    LogBuffer.Add(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + message);
                    if (LogBuffer.Count >= LogFlushAt) FlushLog();
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Write whatever is buffered. Called in a finally, so a run that dies still leaves its log.</summary>
        public static void FlushLog()
        {
            lock (LogBuffer)
            {
                if (LogBuffer.Count == 0) return;
                try
                {
                    EnsureDir();
                    File.AppendAllText(LogPath(), string.Join("\n", LogBuffer) + "\n", new UTF8Encoding(false));
                }
                catch (Exception)
                {
                }
                finally
                {
                    LogBuffer.Clear();
                }
            }
        }

        // ======================================================================
        // the status prompt
        // ======================================================================

        /// <summary>The status prompt Revit shows during the picks: the only place the tool says what it captured.</summary>
        public static string PromptText(string anchor, double? datumMm, bool rounded, double stepMm)
        {
            string label = AnchorLabel(anchor);
            if (!datumMm.HasValue)
                return "Match Offset " + label + ": pick the element to take the " + label.ToLowerInvariant() + " offset from";
            string text = label + " " + FormatMm(datumMm.Value);
            if (rounded) text += " (rounded to " + FormatMm(stepMm) + ")";
            return text + " - pick elements to match, Esc to finish";
        }
    }

    /// <summary>What a run has to say for itself. Notes are informational; problems are what opens the results window.</summary>
    public sealed class MoReport
    {
        public readonly List<string> Notes = new List<string>();
        public readonly List<string> Problems = new List<string>();
        public int Matched;
        public string DatumText = "";

        /// <summary>The debug recorder, when one is running, so every function that takes a report can write to it.</summary>
        public MoRecorder Debug;

        public void Note(string text) { Notes.Add(text ?? ""); }
        public void Problem(string text) { Problems.Add(text ?? ""); }
        public void MatchedOne() { Matched++; }

        /// <summary>A line for the debug report only.</summary>
        public void Say(string text)
        {
            if (Debug != null) Debug.Line("  " + text);
        }

        public void NotePair(string key, string value)
        {
            if (Debug != null) Debug.Pair(key, value);
        }

        public bool ShouldShow(string showResults)
        {
            string mode = (showResults ?? "").Trim().ToLowerInvariant();
            if (mode == "never") return false;
            if (mode == "always") return Problems.Count > 0 || Notes.Count > 0 || Matched > 0;
            return Problems.Count > 0;
        }
    }
}
