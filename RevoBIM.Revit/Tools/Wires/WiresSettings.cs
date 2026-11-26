using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.Wires
{
    /// <summary>One row of the settings schema: (tab, section, kind, key, label, default, extra).</summary>
    public sealed class SettingRow
    {
        public string Tab, Section, Kind, Key, Label, Default, Extra;
    }

    public sealed class CategoryDef
    {
        public string Key, Label, BicName;
    }

    /// <summary>
    /// Wires settings (the top of wires_core.py). The schema drives both the file and the settings dialog: one row per setting, so adding a power
    /// rule later means adding a row here and nothing else.
    /// </summary>
    public static class WiresSettings
    {
        public const string Version = "3.7.0";
        public const string ToolName = "Wires";
        public const int SettingsVersion = 19;

        public static readonly CategoryDef[] CategoryDefs =
        {
            new CategoryDef { Key = "lighting_fixtures", Label = "Lighting Fixtures", BicName = "OST_LightingFixtures" },
            new CategoryDef { Key = "electrical_fixtures", Label = "Electrical Fixtures", BicName = "OST_ElectricalFixtures" },
            new CategoryDef { Key = "electrical_equipment", Label = "Electrical Equipment", BicName = "OST_ElectricalEquipment" },
            new CategoryDef { Key = "lighting_devices", Label = "Lighting Devices", BicName = "OST_LightingDevices" },
            new CategoryDef { Key = "data_devices", Label = "Data Devices", BicName = "OST_DataDevices" },
            new CategoryDef { Key = "fire_alarm_devices", Label = "Fire Alarm Devices", BicName = "OST_FireAlarmDevices" },
            new CategoryDef { Key = "communication_devices", Label = "Communication Devices", BicName = "OST_CommunicationDevices" },
            new CategoryDef { Key = "security_devices", Label = "Security Devices", BicName = "OST_SecurityDevices" },
            new CategoryDef { Key = "nurse_call_devices", Label = "Nurse Call Devices", BicName = "OST_NurseCallDevices" },
            new CategoryDef { Key = "telephone_devices", Label = "Telephone Devices", BicName = "OST_TelephoneDevices" },
            new CategoryDef { Key = "mechanical_equipment", Label = "Mechanical Equipment", BicName = "OST_MechanicalEquipment" },
            new CategoryDef { Key = "generic_models", Label = "Generic Models", BicName = "OST_GenericModel" },
        };

        public const string DefaultCategories = "lighting_fixtures,electrical_fixtures,electrical_equipment," +
                                                "lighting_devices,data_devices,fire_alarm_devices," +
                                                "communication_devices,security_devices";

        private static SettingRow R(string tab, string section, string kind, string key, string label, string def, string extra)
        {
            return new SettingRow { Tab = tab, Section = section, Kind = kind, Key = key, Label = label, Default = def, Extra = extra };
        }

        public static readonly SettingRow[] Schema =
        {
            // -- Circuits ------------------------------------------------------------
            R("Circuits", "Drawing the run", "choice", "arc_sag_mode", "Arc depth measured as", "span",
              "span=a share of the distance being spanned|paper=a fixed size on the sheet"),
            R("Circuits", "Drawing the run", "number", "arc_sag_percent", "Arc depth, share of the span (%)", "18",
              "The depth of the arc at its middle. A share rather than a fixed size so every wire sweeps the same amount whatever it spans - a fixed size " +
              "makes a short hop bulge hard and a long one look flat."),
            R("Circuits", "Drawing the run", "number", "arc_sag_paper_mm", "Arc depth on paper (mm), when measured that way", "3", ""),
            R("Circuits", "Drawing the run", "choice", "arc_side", "Arc bulges to the", "left", "left|right"),
            R("Circuits", "Drawing the run", "choice", "trim_from", "Trim the wire back from", "extent",
              "extent=the family's plan extent, plus a gap|fixed=a fixed gap from the centre"),
            R("Circuits", "Drawing the run", "number", "trim_gap_paper_mm", "Gap left at the symbol, on paper (mm)", "2", ""),
            R("Circuits", "Drawing the run", "number", "trim_fixed_paper_mm", "Fixed trim from centre, on paper (mm)", "4", ""),
            R("Circuits", "Drawing the run", "choice", "align_target", "Aim a wire end at", "edge",
              "edge=the edge of the symbol|centre=the connector node, in the middle of the symbol|trim=short of the symbol, by the trim above"),
            R("Circuits", "Drawing the run", "number", "trim_max_paper_mm", "Never trim back further than, on paper (mm)", "6",
              "A fitting's bounding box is not its symbol: a luminaire's box can be metres across, and a trim taken from it would drag the end of the wire " +
              "most of the way back to the next vertex. This is the ceiling on it."),
            R("Circuits", "Drawing the run", "number", "align_tolerance_mm", "Already close enough within (mm)", "1", ""),
            R("Circuits", "Drawing the run", "number", "align_max_gap_mm", "Close enough to the node (mm)", "25",
              "Revit refuses a vertex that lands on one it already has, so the end is walked in towards the node until it is accepted. This is how close " +
              "counts as arrived - 25mm is half a millimetre on a 1:50 sheet."),
            R("Circuits", "Drawing the run", "choice", "align_method", "Align a wire end by", "auto",
              "auto=re-docking it and letting Revit place it|redock=the same thing, named|auto+rebuild=and rebuilding the wire if neither works|" +
              "move=moving the vertex only|nudge=shoving the vertex and walking it in|jiggle=disconnecting and reconnecting the end|rebuild=rebuilding the wire"),
            R("Circuits", "Drawing the run", "choice", "wiring_type", "Wires are drawn as", "arc", "arc=arc wires|chamfer=chamfered wires"),
            R("Circuits", "Drawing the run", "number", "chamfer_angle_deg", "Chamfer leaves the fitting at (deg)", "45",
              "A chamfered wire is drawn as an angle off the fitting, a straight run across, and an angle back in - not as a faceted arc. This is the angle " +
              "of the two cranks; the straight between them takes the rest."),
            R("Circuits", "Drawing the run", "number", "mid_vertices", "Vertices between the ends of each wire", "1",
              "At least 1. 1 puts a single vertex at the middle of every wire, offset from the straight line between its ends. More are splayed " +
              "evenly along the same arc - so an arc wire sweeps through them and a chamfered wire facets round the curve."),
            R("Circuits", "Drawing the run", "choice", "vertex_mode", "That count is", "each",
              "each=the same on every wire|length=shared out by how long each wire is"),

            R("Circuits", "The route", "check", "two_opt", "Pull crossings out of the route", "yes", ""),
            R("Circuits", "The route", "check", "avoid_fittings", "Route clear of fittings not on the circuit", "yes",
              "Routes that run a wire across a fitting belonging to another circuit are ranked below ones that do not, and a span is flipped to arc the " +
              "other way where that clears it. What cannot be cleared is reported rather than quietly drawn through."),
            R("Circuits", "The route", "number", "clash_clearance_mm", "Keep this far clear of them (mm)", "150", ""),
            R("Circuits", "The route", "check", "group_by_space", "Chain each space as its own leg", "yes",
              "Lights in one space are chained together before the run moves on, and the span that bridges two spaces takes the permanent live wire type. " +
              "Off, spaces are ignored and the route runs straight through them."),
            R("Circuits", "The route", "check", "group_by_switch", "Chain each switch system as its own leg", "yes",
              "Lights on one switch are chained together, then the legs are joined - which is what puts one permanent live wire between rooms rather than " +
              "the run hopping back and forth."),
            R("Circuits", "The route", "check", "modeless_shuffle", "Leave Revit usable while the Shuffle prompt is open", "yes",
              "On, the prompt floats and the view can be panned and zoomed while a route is being judged. Off, it is a modal dialog - Revit is locked " +
              "behind it, which is the one to fall back to if the floating window misbehaves."),
            R("Circuits", "The route", "check", "preview_shuffle", "Offer Shuffle after placing", "yes",
              "Places the circuit, then holds a small prompt open so the route can be reshuffled before it is kept."),
            R("Circuits", "The route", "number", "max_members", "Give up on a circuit above this many members", "200", ""),

            R("Circuits", "Tags", "check", "tag_circuits", "Tag one wire per circuit", "yes", ""),
            R("Circuits", "Tags", "tagfamily", "wire_tag_family", "Wire tag family", "",
              "One tag family covers lighting and power - the tag reads the circuit off the wire, so it does not need to differ between them."),
            R("Circuits", "Tags", "tagtype", "wire_tag_type", "Wire tag type", "", ""),
            R("Circuits", "Tags", "choice", "tag_which", "Tag goes on", "homerun",
              "homerun=the home run, else the longest wire|longest=the longest wire|first=the first wire in the run"),
            R("Circuits", "Tags", "number", "tag_offset_mm", "Tag offset from the wire (mm)", "250", ""),
            R("Circuits", "Tags", "check", "tag_offset_is_paper", "That offset is a paper measurement", "no",
              "Off, 250mm is a real distance and holds its position against the model at every scale. On, it is multiplied by the view scale and holds " +
              "its position on the sheet instead."),
            R("Circuits", "Tags", "check", "tag_leader", "Tag has a leader", "yes", ""),

            R("Circuits", "What is included", "check", "skip_wired_circuits", "Leave circuits that already have wires alone", "yes", ""),
            R("Circuits", "What is included", "check", "report_offscreen", "Say when a circuit has members outside this view", "yes", ""),

            // -- Lighting ------------------------------------------------------------
            R("Lighting", "Wire types", "wiretype", "lighting_wire_type", "Lighting wire", "", ""),
            R("Lighting", "Wire types", "wiretype", "lighting_emergency_wire_type", "Lighting wire, emergency", "", ""),
            R("Lighting", "Wire types", "wiretype", "lighting_live_wire_type", "Lighting wire, permanent live", "",
              "Used where the run crosses from one switch system to another - same circuit, different switch."),
            R("Lighting", "Wire types", "parameter", "emergency_parameter", "Parameter that marks an emergency fitting", "BGL_Elec_IsEmergency",
              "Read off the fitting, instance first then type. Yes, true or 1 all count as emergency. A span with an emergency fitting at either end " +
              "takes the emergency wire type."),
            R("Lighting", "Wire types", "categories", "lighting_categories", "Lighting categories", "lighting_fixtures", ""),

            R("Lighting", "Switches and home runs", "check", "switch_home_run", "Run the home run to the switch, not the panel", "yes", ""),
            R("Lighting", "Switches and home runs", "check", "remove_panel_home_runs", "Remove home runs pointing back to the panel", "yes", ""),
            R("Lighting", "Switches and home runs", "check", "end_chain_at_switch", "End the chain at the light the switch is wired to", "yes", ""),
            R("Lighting", "Switches and home runs", "categories", "switch_categories", "Switch categories", "lighting_devices", ""),
            R("Lighting", "Switches and home runs", "choice", "home_run_style", "The home run is", "arrow",
              "arrow=a short arc from the light, pointing at the switch|full=a wire drawn all the way to the switch"),
            R("Lighting", "Switches and home runs", "number", "home_run_arrow_paper_mm", "Length of that arc, on paper (mm)", "10",
              "A paper measurement multiplied by the view scale, so the arrow is the same length on every sheet. It is clamped so it can never reach the " +
              "switch it points at. Always drawn with one middle vertex so it arcs."),
            R("Lighting", "Switches and home runs", "check", "draw_switch_line", "Draw a detail line from the light to the switch", "yes", ""),
            R("Lighting", "Switches and home runs", "linestyle", "switch_line_style", "Line style for it", "", ""),
            R("Lighting", "Switches and home runs", "check", "stub_if_no_connection", "Draw a stub where the switch will not take a wire", "yes", ""),

            // -- Power ---------------------------------------------------------------
            R("Power", "Wire types", "wiretype", "power_wire_type", "Power wire", "", ""),
            R("Power", "Wire types", "categories", "power_categories", "Power categories", "electrical_fixtures,electrical_equipment", ""),

            R("Power", "Routing", "check", "power_enabled", "Include power circuits in Auto Wire", "no",
              "Off by default. Power shares the drawing, route and tag rules on the Circuits tab; the rules that differ are not written yet, so leaving " +
              "this off keeps Auto Wire to lighting."),
            R("Power", "Routing", "note", "power_note", "", "",
              "Still to come: socket rings against radials, spurs off a ring, dedicated circuits taking a direct home run, and fused connection " +
              "units chaining to the appliance rather than to the next socket."),

            // -- Reconnect -----------------------------------------------------------
            R("Reconnect", "Finding the element", "number", "search_radius_mm", "Look this far from a loose end (mm)", "600",
              "Measured in plan only. A ceiling light sits metres above the plan the wire is drawn on."),
            R("Reconnect", "Finding the element", "check", "require_circuit", "Only offer elements that already carry a circuit", "yes", ""),
            R("Reconnect", "Finding the element", "check", "require_unwired", "Only offer elements with no wire on them yet", "yes", ""),
            R("Reconnect", "Finding the element", "check", "match_system_type", "Match the connector's system type", "yes", ""),
            R("Reconnect", "Finding the element", "categories", "categories", "Categories searched", DefaultCategories, ""),

            R("Reconnect", "Making the join", "check", "snap_on_connect", "Pull the wire end onto the connector as it joins", "yes", ""),
            R("Reconnect", "Making the join", "check", "recreate_if_refused", "Rebuild the wire where Revit refuses the join in place", "yes", ""),
            R("Reconnect", "Making the join", "warn", "cross_circuit", "Join a wire to an element on a DIFFERENT circuit", "no",
              "Off by default. On, a wire can be pulled onto a circuit it was never meant to be on, and nothing warns you."),

            R("Running", "Reporting", "choice", "show_results", "Show results", "needed",
              "needed=Only if something needs a look|always=Always|never=Never"),
            R("Running", "Reporting", "check", "debug_geometry", "Put the full wire geometry in the debug report", "no",
              "Dumps every vertex, every connector and the fitting behind it for each wire touched. Slow and long, and the only way to see what Revit thinks " +
              "a wire is made of when it will not do what it is told."),
            R("Running", "Reporting", "check", "debug_report", "Put a Debug button on the results window", "yes",
              "Writes everything about the run - release, settings, what the lookups resolved to, and every line including the informational ones - to " +
              "%APPDATA%\\RevoBIM\\wires_debug.txt, and copies it to the clipboard so it can be pasted straight into a message."),
            R("Running", "Reporting", "check", "keep_running", "Keep asking for wires until Escape", "no", ""),
        };

        private static readonly Dictionary<string, string> defaults = BuildDefaults();
        private static readonly List<string> tabs = Schema.Select(r => r.Tab).Distinct().ToList();

        private static Dictionary<string, string> BuildDefaults()
        {
            var d = new Dictionary<string, string> { { "settings_version", SettingsVersion.ToString(CultureInfo.InvariantCulture) } };
            foreach (SettingRow row in Schema)
                if (row.Kind != "note") d[row.Key] = row.Default;
            d["categories"] = DefaultCategories;
            // Not on any tab: the theme chip in every window header saves it straight away. follow / dark / light.
            d["theme"] = "follow";
            return d;
        }

        public static Dictionary<string, string> Defaults()
        {
            return new Dictionary<string, string>(defaults);
        }

        public static List<string> Tabs
        {
            get { return tabs; }
        }

        /// <summary>A settings key whose meaning changes needs a migration: MIGRATIONS[version] lists the keys reset when loading an older file.</summary>
        private static readonly Dictionary<int, string[]> Migrations = new Dictionary<int, string[]>
        {
            { 3, new[] { "wire_tag_family", "wire_tag_type" } },
            { 4, new[] { "mid_vertices", "tag_offset_mm", "tag_offset_is_paper", "tag_leader" } },
            { 5, new[] { "home_run_arrow_paper_mm", "lighting_emergency_wire_type", "emergency_parameter" } },
            { 6, new[] { "mid_vertices", "group_by_space", "draw_switch_line", "switch_line_style" } },
            { 7, new[] { "arc_sag_mode", "arc_sag_percent" } },
            { 8, new[] { "avoid_fittings", "clash_clearance_mm" } },
            { 9, new[] { "mid_vertices", "vertex_mode" } },
            { 10, new[] { "wiring_type", "mid_vertices" } },
            { 11, new[] { "chamfer_angle_deg" } },
            { 12, new[] { "modeless_shuffle", "debug_report" } },
            { 13, new[] { "align_target", "align_tolerance_mm" } },
            { 14, new[] { "align_target", "trim_max_paper_mm" } },
            { 15, new[] { "align_method" } },
            { 16, new[] { "align_method", "debug_geometry" } },
            { 17, new[] { "align_method", "align_max_gap_mm" } },
            { 18, new[] { "align_target", "align_method" } },
            { 19, new[] { "align_method" } },
        };

        // ------------------------------------------------------------------ files
        public static string SettingsDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string SettingsPath()
        {
            return Path.Combine(SettingsDir(), "wires.txt");
        }

        /// <summary>v1.0.0 shipped as "Wire Fix" and wrote here; read once if the new file does not exist yet.</summary>
        public static string LegacySettingsPath()
        {
            return Path.Combine(SettingsDir(), "wire_fix.txt");
        }

        public static string DebugPath()
        {
            return Path.Combine(SettingsDir(), "wires_debug.txt");
        }

        public static string ErrorPath()
        {
            return Path.Combine(SettingsDir(), "wires_last_error.txt");
        }

        public static string BuildInfo()
        {
            return "Wires v" + Version + ", build " + typeof(WiresSettings).Assembly.GetName().Version;
        }

        /// <summary>Reads the settings file, falling back to the defaults key by key.</summary>
        public static Dictionary<string, string> Load()
        {
            Dictionary<string, string> settings = Defaults();
            string path = SettingsPath();
            if (!File.Exists(path) && File.Exists(LegacySettingsPath())) path = LegacySettingsPath();
            try
            {
                if (File.Exists(path))
                {
                    foreach (string raw in File.ReadAllLines(path, Encoding.UTF8))
                    {
                        string line = raw.Trim();
                        if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal) || line.IndexOf('=') < 0) continue;
                        // split on the first '=' only, so a value may contain more
                        int eq = line.IndexOf('=');
                        string key = line.Substring(0, eq).Trim();
                        if (defaults.ContainsKey(key)) settings[key] = line.Substring(eq + 1).Trim();
                    }
                }
            }
            catch (Exception)
            {
            }
            // migrations - keys whose meaning changed are reset to the default
            int was;
            if (!int.TryParse(Get(settings, "settings_version", "0"), out was)) was = 0;
            foreach (int version in Migrations.Keys.OrderBy(v => v))
            {
                if (was >= version) continue;
                foreach (string key in Migrations[version])
                {
                    string d;
                    settings[key] = defaults.TryGetValue(key, out d) ? d : "";
                }
            }
            settings["settings_version"] = SettingsVersion.ToString(CultureInfo.InvariantCulture);
            return settings;
        }

        public static bool Save(Dictionary<string, string> settings)
        {
            try
            {
                Directory.CreateDirectory(SettingsDir());
                var sb = new StringBuilder();
                sb.Append("# RevoBIM PY - Wires settings\n");
                sb.Append("# version ").Append(Version).Append('\n');
                foreach (string key in defaults.Keys.OrderBy(k => k, StringComparer.Ordinal))
                {
                    string v;
                    sb.Append(key).Append('=').Append(settings.TryGetValue(key, out v) ? v : defaults[key]).Append('\n');
                }
                File.WriteAllText(SettingsPath(), sb.ToString(), new UTF8Encoding(false));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ------------------------------------------------------------------ typed reads
        public static string Get(Dictionary<string, string> settings, string key, string fallback = "")
        {
            string v;
            if (settings.TryGetValue(key, out v)) return v;
            string d;
            return defaults.TryGetValue(key, out d) ? d : fallback;
        }

        public static bool Bool(Dictionary<string, string> settings, string key)
        {
            string v = (Get(settings, key, "no") ?? "").Trim().ToLowerInvariant();
            return v == "yes" || v == "true" || v == "1" || v == "on";
        }

        public static double Float(Dictionary<string, string> settings, string key)
        {
            double v;
            if (double.TryParse((Get(settings, key, "0") ?? "").Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out v)) return v;
            string d;
            if (defaults.TryGetValue(key, out d) && double.TryParse(d, NumberStyles.Float, CultureInfo.InvariantCulture, out v)) return v;
            return 0.0;
        }

        public static string Lower(Dictionary<string, string> settings, string key, string fallback = "")
        {
            return (Get(settings, key, fallback) ?? "").Trim().ToLowerInvariant();
        }

        public static BuiltInCategory? BuiltinCategory(string name)
        {
            BuiltInCategory bic;
            if (!string.IsNullOrEmpty(name) && Enum.TryParse(name, out bic) && Enum.IsDefined(typeof(BuiltInCategory), bic)) return bic;
            return null;
        }

        /// <summary>The categories named by a comma separated settings value.</summary>
        public static List<BuiltInCategory> CategoriesFrom(string raw, string fallback)
        {
            var keys = (raw ?? "").Split(',').Select(k => k.Trim()).Where(k => k.Length > 0).ToList();
            var wanted = new List<BuiltInCategory>();
            foreach (CategoryDef def in CategoryDefs)
            {
                if (!keys.Contains(def.Key)) continue;
                BuiltInCategory? bic = BuiltinCategory(def.BicName);
                if (bic != null) wanted.Add(bic.Value);
            }
            if (wanted.Count == 0 && fallback != null)
            {
                var fb = fallback.Split(',').Select(k => k.Trim()).ToList();
                foreach (CategoryDef def in CategoryDefs)
                {
                    if (!fb.Contains(def.Key)) continue;
                    BuiltInCategory? bic = BuiltinCategory(def.BicName);
                    if (bic != null) wanted.Add(bic.Value);
                }
            }
            return wanted;
        }

        /// <summary>The BuiltInCategory list the reconnect search runs over.</summary>
        public static List<BuiltInCategory> ActiveCategories(Dictionary<string, string> settings)
        {
            return CategoriesFrom(Get(settings, "categories", DefaultCategories), DefaultCategories);
        }

        // ------------------------------------------------------------------ units
        public const double MM = 1.0 / 304.8;

        /// <summary>Millimetres to Revit internal feet (decimal feet on every release, so the conversion is a constant).</summary>
        public static double Mm(double value)
        {
            return value * MM;
        }

        public static double ToMm(double feet)
        {
            return feet / MM;
        }
    }
}
