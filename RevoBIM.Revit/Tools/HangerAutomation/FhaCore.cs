using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace RevoBIM.Tools.HangerAutomation
{
    // =====================================================================================================
    // Hanger Automation - pure logic. Port of fha_core.py: no Revit calls, so it can be reasoned about on
    // its own. Lengths are decimal feet unless a name ends in Mm. Version 1.16.0 of the pyRevit tool.
    // =====================================================================================================

    // FhaCore is split into FhaCore.*.cs (see CODEMAP.md). Every static field initialiser stays in THIS file, in this
    // order: across partial files C# leaves the initialisation order undefined (Defaults reads FloorSkip).
    public static partial class FhaCore
    {
        // Bump this on every change to the tool (the owner's rule): it shows top right of the window and in the debug file.
        public const string Version = "1.18.0";

        /// <summary>Which build is running: the add-in version, build date, target framework and the DLL's own path and
        /// write time - the first thing to read in a pasted debug file.</summary>
        public static string BuildInfo()
        {
            try
            {
                System.Reflection.Assembly a = typeof(FhaCore).Assembly;
                string date = "?";
                foreach (object o in a.GetCustomAttributes(typeof(System.Reflection.AssemblyMetadataAttribute), false))
                {
                    var m = (System.Reflection.AssemblyMetadataAttribute)o;
                    if (m.Key == "BuildDate") date = m.Value;
                }
                string loc = a.Location;
                string written = "?";
                try { written = File.GetLastWriteTime(loc).ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture); } catch (Exception) { }
                return "RevoBIM Tools " + a.GetName().Version + ", built " + date + ", dll written " + written + ", "
                       + Environment.Version + ", " + loc;
            }
            catch (Exception ex)
            {
                return "unknown (" + ex.Message + ")";
            }
        }
        public const string ToolName = "Hanger Automation";
        public const double MM = 304.8;
        public const int SettingsVersion = 3;

        // ------------------------------------------------------------------ settings
        /// <summary>Family Floor Support tab keys that have no flr_ copy. (Declared before Defaults: static field
        /// initialisers run in textual order and BuildDefaults reads it.)</summary>
        public static readonly string[] FloorSkip =
        {
            "fam_rod_place", "fam_rod_realign", "fam_rod_auto", "fam_rod_linked",
            "fam_group_z", "fam_group_gap", "fam_group_angle", "fam_group_centre",
        };

        public static readonly Dictionary<string, string> Defaults = BuildDefaults();

        public static readonly List<KeyValuePair<string, string>> Bases = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("level", "The service's level"),
            new KeyValuePair<string, string>("element", "A floor, roof or equipment I pick (here or in a link)"),
        };

        private static Dictionary<string, string> BuildDefaults()
        {
            var d = new Dictionary<string, string>(StringComparer.Ordinal)
            {
                {"settings_version", "3"}, {"theme", "auto"}, {"debug", "1"}, {"button", ""},
                {"spacing", "2000"}, {"start_off", "300"}, {"end_off", "300"}, {"takeoff_max", "600"},
                {"takeoff_clear", "400"}, {"min_gap", "500"}, {"edge", "100"}, {"skip_existing", "1"},
                {"existing_clear", "300"}, {"ext_floors", "1"}, {"ext_framing", "1"}, {"ext_roofs", "0"},
                // More categories a drop rod can run up to (comma-separated BuiltInCategory names), set in the
                // "Rod target categories" window. Casework and MEP Ancillary Framing to begin with.
                {"ext_extra", "OST_Casework,OST_MEPAncillaryFraming"},
                {"extend_after", "1"}, {"extend_place", "1"}, {"match_size", "1"}, {"rehost_replace", "1"},
                {"replace_free", "0"}, {"search_radius", "1500"}, {"dims", "1"}, {"dim_type", ""},
                {"dim_offset", "800"}, {"scope", "run"}, {"active_tab", "fab"}, {"workset", ""},
                // ---- Family Hangers tab
                {"fam_category", "all"}, {"fam_symbol", ""}, {"fam_search", ""},
                {"fam_rod_place", "0"}, {"fam_rod_realign", "0"}, {"fam_rod_auto", "0"},
                {"fam_spacing", "3000"}, {"fam_dw144", "1"}, {"fam_start_off", "300"}, {"fam_end_off", "300"},
                {"fam_flange_clear", "150"}, {"fam_takeoff_clear", "400"}, {"fam_accessory", "1"},
                {"fam_skip_existing", "1"}, {"fam_dims", "0"}, {"fam_dim_offset", "800"},
                {"fam_ins_place", "1"}, {"fam_ins_realign", "1"}, {"fam_ins_auto", "1"}, {"fam_dim_type", ""},
                {"fam_rod_linked", "0"}, {"fam_lock_place", "1"}, {"fam_lock_realign", "1"}, {"fam_lock_auto", "1"},
                {"fam_group_z", "50"}, {"fam_group_gap", "500"}, {"fam_group_angle", "2"}, {"fam_group_centre", "mean"},
                {"fam_workset", ""},
                {"fam_list_h", "92"},     // height of the family list (dragged by its grip)
                {"fam_set_only", "0"},    // list only the families already set up in Family settings
                // Hanger Service Type Assigner tab
                {"svc_category", "all"}, {"svc_search", ""}, {"svc_by", "family,type,level,comments"},
                {"svc_sort", ""}, {"svc_scope", "selected"}, {"svc_tol", "150"}, {"svc_list_h", "300"},
            };
            // Family Floor Support tab: its own copy of every Family Hangers setting except the drop rod
            // ones; the grouping rules (fam_group_*) are shared.
            foreach (string k in d.Keys.ToList())
            {
                if (k.StartsWith("fam_", StringComparison.Ordinal) && Array.IndexOf(FloorSkip, k) < 0)
                    d["flr_" + k.Substring(4)] = d[k];
            }
            d["flr_base"] = "level";          // level | element (a picked floor / roof / equipment)
            d["flr_base_linked"] = "0";       // 1 = go straight to picking inside a link
            return d;
        }

        /// <summary>The Floor Support tab's key for a Family Hangers key (fam_x -> flr_x); shared keys stay as they are.</summary>
        public static string FloorKey(string key)
        {
            if (key.StartsWith("fam_", StringComparison.Ordinal) && Array.IndexOf(FloorSkip, key) < 0)
                return "flr_" + key.Substring(4);
            return key;
        }

        // ------------------------------------------------------------------ worksets
        public const string WsLeave = "";                 // as before: new hangers on the service's workset, edited ones left alone
        public const string WsService = "*service*";      // new and edited hangers on their service's workset
        public const string WsActive = "*active*";        // new and edited hangers on the active workset

        public static readonly List<KeyValuePair<string, string>> WsOptions = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>(WsLeave, "Leave as is (new hangers: the service's workset)"),
            new KeyValuePair<string, string>(WsService, "Same as the service (new and edited)"),
            new KeyValuePair<string, string>(WsActive, "Active workset (new and edited)"),
        };

        // ------------------------------------------------------------------ files
        /// <summary>settings version -> keys whose meaning changed and must be reset (none yet).</summary>
        public static readonly Dictionary<int, string[]> Migrations = new Dictionary<int, string[]>();

        // ------------------------------------------------------------------ theme
        public static readonly Dictionary<string, Dictionary<string, string>> Palettes = new Dictionary<string, Dictionary<string, string>>
        {
            {"dark", new Dictionary<string, string>   // Revit's own dark theme, accents lifted to 4.5:1 on it
            {
                {"WinBg", "#3C4454"}, {"Card", "#323C48"}, {"Field", "#2D3441"},
                {"Bar", "#222933"}, {"Edge", "#4D5666"}, {"EdgeStrong", "#515C6B"},
                {"Text", "#EEF0F4"}, {"Muted", "#ABB3BF"}, {"Blue", "#72BAF0"},
                {"BlueHover", "#8CC8F4"}, {"Orange", "#F2A452"},
                {"OrangeHover", "#F5B56E"}, {"Green", "#3FA75A"},
                {"GreenHover", "#4EC06D"}, {"Red", "#D9534F"}, {"Sel", "#3A7392"},
                {"HoverBg", "#444E5E"}, {"Disabled", "#6B7484"}, {"OnAccent", "#1B1F24"},
                {"SetText", "#7FD99A"},   // families already set up (a green that reads on the dark field)
            }},
            {"light", new Dictionary<string, string>
            {
                {"WinBg", "#F3F3F5"}, {"Card", "#FFFFFF"}, {"Field", "#FFFFFF"},
                {"Bar", "#E6E6EA"}, {"Edge", "#D0D0D6"}, {"EdgeStrong", "#B8B8C0"},
                {"Text", "#1F1F23"}, {"Muted", "#66666E"}, {"Blue", "#1B72BE"},
                {"BlueHover", "#2A86D6"}, {"Orange", "#B96A12"},
                {"OrangeHover", "#D07C1E"}, {"Green", "#2E8546"},
                {"GreenHover", "#3A9A55"}, {"Red", "#C03B36"}, {"Sel", "#CFE3F5"},
                {"HoverBg", "#E0E0E6"}, {"Disabled", "#A8A8B0"}, {"OnAccent", "#FFFFFF"},
                {"SetText", "#17602C"},   // families already set up: dark green
            }},
        };

        public static readonly string[] ThemeModes = { "auto", "dark", "light" };

        // ------------------------------------------------------------------ dim views
        public static readonly string[] PlanViewTypes = { "FloorPlan", "CeilingPlan", "EngineeringPlan", "AreaPlan" };

        public static readonly Dictionary<string, string> ViewKindLabels = new Dictionary<string, string>
        {
            {"FloorPlan", "Floor plan"}, {"CeilingPlan", "Ceiling plan"}, {"EngineeringPlan", "Structural plan"},
            {"AreaPlan", "Area plan"}, {"Section", "Section"}, {"Elevation", "Elevation"}, {"Detail", "Detail"},
        };

        public static readonly List<KeyValuePair<string, string>> ViewKinds = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("floor", "Floor plans"),
            new KeyValuePair<string, string>("plan", "All plans"),
            new KeyValuePair<string, string>("section", "Sections and elevations"),
            new KeyValuePair<string, string>("all", "All plans and sections"),
        };

        // ------------------------------------------------------------------ run / spans
        public static readonly string[] Takeoff = { "tap", "tee_branch" };

        private static readonly Dictionary<string, int> Priority = new Dictionary<string, int>
        {
            {"bend", 0}, {"accessory", 0}, {"vertical", 1}, {"tee_main", 2}, {"open", 3}, {"other", 3},
            {"loop", 3}, {"tap", 4}, {"tee_branch", 4},
        };

        // ------------------------------------------------------------------ misc
        public static string Plural(int n, string one, string many = null)
        {
            return n.ToString(CultureInfo.InvariantCulture) + " " + (n == 1 ? one : (string.IsNullOrEmpty(many) ? one + "s" : many));
        }
    }
}
