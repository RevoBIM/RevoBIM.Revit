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

    /// <summary>A 3D point or vector (the Python tuples of three floats).</summary>
    public struct V3
    {
        public double X, Y, Z;
        public V3(double x, double y, double z) { X = x; Y = y; Z = z; }
        public override string ToString() { return "(" + X.ToString("R", CultureInfo.InvariantCulture) + ", " + Y.ToString("R", CultureInfo.InvariantCulture) + ", " + Z.ToString("R", CultureInfo.InvariantCulture) + ")"; }
    }

    /// <summary>One connector of a part in the run graph. To / ToConn are null when nothing is joined; Role is "main" / "branch" on a tee.</summary>
    public class ConnRec
    {
        public long? To;
        public int? ToConn;
        public string Role;
    }

    /// <summary>A part in the run graph (fha_core "parts" values). Kind: straight / inline / bend / tee / tap / other / accessory.</summary>
    public class PartRec
    {
        public string Kind = "other";
        public double Len;
        public bool Horizontal = true;
        public List<ConnRec> Conns = new List<ConnRec>();
    }

    public class ChainItem
    {
        public long Id;
        public string Kind;
        public double Len;
        public int Entry, Exit;
    }

    /// <summary>What finishes one end of a span: bend / accessory / vertical / tee_main / tee_branch / tap / open / other / loop.</summary>
    public class SpanEnd
    {
        public string Type;
        public long? Id;
    }

    public class Span
    {
        public List<ChainItem> Chain = new List<ChainItem>();
        public SpanEnd StartEnd, EndEnd;
    }

    /// <summary>A candidate host straight for nearest_host: connector 0 / connector 1 origins.</summary>
    public class HostSeg
    {
        public long Id;
        public V3 A, B;
        public bool Horizontal = true;
        public object Tag;   // the caller's own record
    }

    public class NearestHostResult
    {
        public HostSeg Host;
        public double Dist, D, T;
    }

    public class Located
    {
        public long Id;
        public int Entry;
        public double Dist, Station;
    }

    /// <summary>One straight's piece of a span: s0 = station of its start, A / B its end points.</summary>
    public class SpanSeg
    {
        public double S0;
        public V3 A, B;
        public long Id;
    }

    /// <summary>A hanger button condition for pick_condition.</summary>
    public class Condition
    {
        public int Index;
        public double Lower, Upper;
        public bool Unrestricted;
        public Condition() { }
        public Condition(int index, double lower, double upper, bool unrestricted) { Index = index; Lower = lower; Upper = upper; Unrestricted = unrestricted; }
    }

    /// <summary>The numbers plan_stations needs, all mm (plan_config).</summary>
    public class PlanConfig
    {
        public double Spacing = 2000, StartOff = 300, EndOff = 300, TakeoffMax = 600, TakeoffClear = 400, MinGap = 500, Edge = 100;
    }

    /// <summary>A hanger's identity for signature_score (all fields may be null).</summary>
    public class HangerSignature
    {
        public string Name, Product, Alias, ItemId, Code;
    }

    /// <summary>A plan / section view a run can be dimensioned in (dim_view_rows).</summary>
    public class ViewRow
    {
        public long Key;
        public Autodesk.Revit.DB.ElementId Id;
        public string Name;
        public string Type;      // ViewType name: FloorPlan, CeilingPlan, EngineeringPlan, AreaPlan, Section, Elevation, Detail ...
        public int Scale;
    }

    /// <summary>A sheet carrying such views (dim_sheet_rows). Views = the view keys.</summary>
    public class SheetRow
    {
        public long Key;
        public Autodesk.Revit.DB.ElementId Id;
        public string Number, Name;
        public List<long> Views = new List<long>();
    }

    /// <summary>The Dimension views picker's answer (null = skip).</summary>
    public class DimChoice
    {
        public List<long> Views = new List<long>();
        public List<long> Sheets = new List<long>();
    }

    /// <summary>
    /// The questions a job asks mid-run; the window hands its implementation to the jobs (the Python
    /// settings["_ui"]). Implemented by UI\HangerAutomation\HviewUi.cs.
    /// </summary>
    public interface IFhaPrompts
    {
        /// <summary>null to skip, else the ticked views and sheets.</summary>
        DimChoice ChooseDimViews(string viewName, List<ViewRow> rows, List<SheetRow> sheets);
        /// <summary>"pick" or "level" (null if closed).</summary>
        string AskBasePick(bool linked);
        /// <summary>"sheets", "views" or null.</summary>
        string AskOpen(int nRuns, List<string> views, List<string> sheets);
    }

    /// <summary>The settings dictionary jobs receive. Python put the prompts object in the dict as "_ui"; here it is Prompts.</summary>
    public class FhaSettings : Dictionary<string, string>
    {
        public IFhaPrompts Prompts;
        public FhaSettings() : base(StringComparer.Ordinal) { }
        public FhaSettings(IDictionary<string, string> from) : base(from, StringComparer.Ordinal)
        {
            FhaSettings f = from as FhaSettings;
            if (f != null) Prompts = f.Prompts;
        }
    }

    /// <summary>What a tool reports (fha_revit.new_result): "Title: done, skipped, failed" and the lines under it.</summary>
    public class JobResult
    {
        public string Title;
        public int Done, Skipped, Failed;
        public List<string> Lines = new List<string>();
        public Dictionary<string, object> Extra = new Dictionary<string, object>();
        public JobResult() { }
        public JobResult(string title) { Title = title; }
    }

    /// <summary>A queued job: runs inside Revit's API context. Returns a JobResult (tools) or any object (quiet reads).</summary>
    public delegate object FhaJob(Autodesk.Revit.UI.UIDocument uidoc, FhaSettings settings, FhaDebugLog log);

    /// <summary>The debug file's lines (core.DebugLog).</summary>
    public sealed class FhaDebugLog
    {
        public bool Enabled;
        public List<string> Lines = new List<string>();
        public FhaDebugLog(bool enabled = true) { Enabled = enabled; }

        public void Add(string msg)
        {
            if (!Enabled) return;
            try { Lines.Add(msg ?? ""); } catch (Exception) { Lines.Add("?"); }
        }

        public string Text() { return string.Join("\n", Lines); }

        public void Write(string path = null)
        {
            if (!Enabled) return;
            try
            {
                string p = path ?? FhaCore.DebugPath();
                string folder = Path.GetDirectoryName(p);
                if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder)) Directory.CreateDirectory(folder);
                File.WriteAllText(p, Text() + "\n", new UTF8Encoding(false));
            }
            catch (Exception) { }
        }
    }

    /// <summary>The workset combo: labels, selected index and the value behind each label.</summary>
    public class WorksetItems
    {
        public List<string> Labels = new List<string>();
        public List<string> Values = new List<string>();
        public int Index;
    }

    public static class FhaCore
    {
        public const string Version = "1.16.0";
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

        /// <summary>Labels, selected index and values for a workset combo. A saved name that is no longer in the model is kept, marked.</summary>
        public static WorksetItems WorksetItemsFor(IEnumerable<string> names, string value)
        {
            var r = new WorksetItems();
            foreach (var o in WsOptions) { r.Values.Add(o.Key); r.Labels.Add(o.Value); }
            foreach (string n in names) { r.Values.Add(n); r.Labels.Add(n); }
            if (!string.IsNullOrEmpty(value) && !r.Values.Contains(value))
            {
                r.Values.Add(value);
                r.Labels.Add(value + " (not in this model)");
            }
            int i = r.Values.IndexOf(value ?? "");
            r.Index = i >= 0 ? i : 0;
            return r;
        }

        public static string WorksetValue(IList<string> values, int index)
        {
            return index >= 0 && index < values.Count ? values[index] : WsLeave;
        }

        /// <summary>Which workset id an element goes on, or null to leave it (workset_target).</summary>
        public static int? WorksetTarget(string choice, int? serviceWs, int? activeWs, int? named, bool isNew)
        {
            if (choice == WsLeave) return isNew ? serviceWs : null;
            if (choice == WsService) return serviceWs;
            if (choice == WsActive) return activeWs;
            return named != null ? named : (isNew ? serviceWs : null);
        }

        // ------------------------------------------------------------------ files
        /// <summary>settings version -> keys whose meaning changed and must be reset (none yet).</summary>
        public static readonly Dictionary<int, string[]> Migrations = new Dictionary<int, string[]>();

        public static string SettingsDir()
        {
            string b = Environment.GetEnvironmentVariable("APPDATA");
            if (string.IsNullOrEmpty(b)) b = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            return Path.Combine(b, "RevoBIM");
        }

        public static string SettingsPath() { return Path.Combine(SettingsDir(), "hanger_automation.txt"); }
        /// <summary>Before 1.1.0 the tool was Fab Hangar Automation.</summary>
        public static string LegacySettingsPath() { return Path.Combine(SettingsDir(), "fab_hangar_automation.txt"); }
        public static string DebugPath() { return Path.Combine(SettingsDir(), "hanger_automation_debug.txt"); }
        public static string LoadErrorPath() { return Path.Combine(SettingsDir(), "hanger_automation_load_error.txt"); }

        public static Dictionary<string, string> ParseSettings(string text)
        {
            var o = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (string raw in (text ?? "").Split(new[] { "\r\n", "\n", "\r" }, StringSplitOptions.None))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal)) continue;
                int eq = line.IndexOf('=');
                if (eq < 0) continue;
                o[line.Substring(0, eq).Trim()] = line.Substring(eq + 1).Trim();
            }
            return o;
        }

        private static int ToInt(string v, int dflt)
        {
            double d;
            if (v != null && double.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out d) && !double.IsNaN(d) && !double.IsInfinity(d))
                return (int)d;
            return dflt;
        }

        public static Dictionary<string, string> LoadSettings(string path = null)
        {
            var d = new Dictionary<string, string>(Defaults, StringComparer.Ordinal);
            string p = path ?? SettingsPath();
            if (path == null && !File.Exists(p) && File.Exists(LegacySettingsPath())) p = LegacySettingsPath();
            try
            {
                if (File.Exists(p))
                {
                    string text = File.ReadAllText(p, new UTF8Encoding(false));
                    if (text.Length > 0 && text[0] == '﻿') text = text.Substring(1);
                    Dictionary<string, string> saved = ParseSettings(text);
                    string verText;
                    int ver = ToInt(saved.TryGetValue("settings_version", out verText) ? verText : null, 0);
                    foreach (var kv in saved)
                        if (Defaults.ContainsKey(kv.Key)) d[kv.Key] = kv.Value;
                    for (int n = ver + 1; n <= SettingsVersion; n++)
                    {
                        string[] keys;
                        if (Migrations.TryGetValue(n, out keys))
                            foreach (string k in keys) d[k] = Defaults[k];
                    }
                }
            }
            catch (Exception)
            {
                d = new Dictionary<string, string>(Defaults, StringComparer.Ordinal);
            }
            d["settings_version"] = SettingsVersion.ToString(CultureInfo.InvariantCulture);
            return d;
        }

        public static bool SaveSettings(IDictionary<string, string> d, string path = null)
        {
            string p = path ?? SettingsPath();
            try
            {
                string folder = Path.GetDirectoryName(p);
                if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder)) Directory.CreateDirectory(folder);
                var keys = Defaults.Keys.ToList();
                keys.Sort(StringComparer.Ordinal);
                var lines = new List<string>();
                foreach (string k in keys)
                {
                    string v;
                    lines.Add(k + "=" + (d.TryGetValue(k, out v) ? v : Defaults[k]));
                }
                File.WriteAllText(p, string.Join("\n", lines) + "\n", new UTF8Encoding(false));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>d.get(key) read as a string, else the key's default, else dflt.</summary>
        public static string Get(IDictionary<string, string> d, string key, string dflt = "")
        {
            string v;
            if (d != null && d.TryGetValue(key, out v) && v != null) return v;
            if (Defaults.TryGetValue(key, out v)) return v;
            return dflt;
        }

        public static double AsFloat(IDictionary<string, string> d, string key, double dflt)
        {
            string v;
            if (d == null || !d.TryGetValue(key, out v)) Defaults.TryGetValue(key, out v);
            double r;
            if (v != null && double.TryParse(v.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out r)) return r;
            return dflt;
        }

        public static bool AsBool(IDictionary<string, string> d, string key)
        {
            string v;
            if (d == null || !d.TryGetValue(key, out v))
                if (!Defaults.TryGetValue(key, out v)) v = "0";
            v = (v ?? "").Trim();
            return v == "1" || v == "true" || v == "True" || v == "yes";
        }

        /// <summary>Millimetres typed in a box -> number, or the default if unreadable.</summary>
        public static double ParseMm(string text, double dflt)
        {
            double v;
            if (text != null && double.TryParse(text.Trim().Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out v)
                && !double.IsNaN(v) && v >= 0)
                return v;
            return dflt;
        }

        /// <summary>Settings dictionary -> the numbers PlanStations needs (all mm).</summary>
        public static PlanConfig PlanConfigFrom(IDictionary<string, string> d)
        {
            return new PlanConfig
            {
                Spacing = Math.Max(100.0, AsFloat(d, "spacing", 2000.0)),
                StartOff = AsFloat(d, "start_off", 300.0),
                EndOff = AsFloat(d, "end_off", 300.0),
                TakeoffMax = AsFloat(d, "takeoff_max", 600.0),
                TakeoffClear = AsFloat(d, "takeoff_clear", 400.0),
                MinGap = AsFloat(d, "min_gap", 500.0),
                Edge = AsFloat(d, "edge", 100.0),
            };
        }

        /// <summary>Python's "{0:g}" for a float typed back into a box: 2000.0 -> "2000".</summary>
        public static string NumText(double v)
        {
            // 'g' keeps 6 significant digits (12.3456789 -> 12.3457), drops trailing zeros, e+06 style exponent
            return v.ToString("G6", CultureInfo.InvariantCulture).Replace("E", "e");
        }

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

        /// <summary>'Pipe Types : Copper' + 'SVP' -> 'Pipe Types : Copper (SVP)'.</summary>
        public static string LabelWithAbbreviation(string label, string abbr)
        {
            label = (label ?? "").Trim();
            abbr = (abbr ?? "").Trim();
            if (abbr.Length == 0) return label;
            if (label.Length == 0) return "(" + abbr + ")";
            return label + " (" + abbr + ")";
        }

        /// <summary>The first non-blank value (for an abbreviation read several ways).</summary>
        public static string FirstText(IEnumerable<string> values)
        {
            foreach (string v in values)
            {
                string t = (v ?? "").Trim();
                if (t.Length > 0) return t;
            }
            return "";
        }

        /// <summary>The hanger's Comments from the 'Family : Type (ABBR)' of each service on it: in the order met,
        /// joined with ', ', repeats counted - '2xCable Tray : Ladder (LV), Pipe Types : Copper (SVP)'.</summary>
        public static string ServiceComment(IEnumerable<string> labels)
        {
            var order = new List<string>();
            var count = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (string raw in labels)
            {
                string lb = (raw ?? "").Trim();
                if (lb.Length == 0) continue;
                if (!count.ContainsKey(lb)) { order.Add(lb); count[lb] = 0; }
                count[lb]++;
            }
            return string.Join(", ", order.Select(lb => count[lb] > 1 ? count[lb].ToString(CultureInfo.InvariantCulture) + "x" + lb : lb));
        }

        /// <summary>WCAG contrast ratio of two #RRGGBB colours.</summary>
        public static double Contrast(string fg, string bg)
        {
            Func<string, double> lum = h =>
            {
                double[] c = new double[3];
                for (int i = 0; i < 3; i++)
                {
                    double x = int.Parse(h.Substring(1 + 2 * i, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture) / 255.0;
                    c[i] = x <= 0.03928 ? x / 12.92 : Math.Pow((x + 0.055) / 1.055, 2.4);
                }
                return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
            };
            double a = lum(fg), b = lum(bg);
            double hi = Math.Max(a, b), lo = Math.Min(a, b);
            return (hi + 0.05) / (lo + 0.05);
        }

        // ------------------------------------------------------------------ drawer
        /// <summary>Top of a parked title bar: gap above the bottom of the working area, stacked upward by slot.</summary>
        public static double ShrunkTop(double waTop, double waH, double barH, int slot = 0, double gap = 8.0)
        {
            return Math.Max(waTop, waTop + waH - (slot + 1) * (barH + gap));
        }

        /// <summary>Where a parked window opens to: back where it was if the bar has not been moved; otherwise growing
        /// upward from wherever the bar now sits. Always kept on the screen.</summary>
        public static double ExpandTop(double savedTop, double? landedTop, double hereTop, double barH, double fullH, double waTop, double waH)
        {
            double top;
            if (landedTop != null && Math.Abs(hereTop - landedTop.Value) < 1.0) top = savedTop;
            else top = hereTop + barH - fullH;
            return Math.Min(Math.Max(waTop, top), Math.Max(waTop, waTop + waH - fullH));
        }

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

        /// <summary>M-A9 before M-A10: numbers compare as numbers.</summary>
        public sealed class NaturalComparer : IComparer<string>
        {
            public static readonly NaturalComparer Instance = new NaturalComparer();

            public int Compare(string a, string b)
            {
                List<string> pa = Parts((a ?? "").ToLowerInvariant()), pb = Parts((b ?? "").ToLowerInvariant());
                int n = Math.Min(pa.Count, pb.Count);
                for (int i = 0; i < n; i++)
                {
                    bool da = IsDigits(pa[i]), db = IsDigits(pb[i]);
                    if (da != db) return da ? -1 : 1;     // numbers sort before text, as the (0, n, "") / (1, 0, text) keys did
                    int c;
                    if (da)
                    {
                        string x = pa[i].TrimStart('0'), y = pb[i].TrimStart('0');
                        c = x.Length != y.Length ? x.Length.CompareTo(y.Length) : string.CompareOrdinal(x, y);
                    }
                    else c = string.CompareOrdinal(pa[i], pb[i]);
                    if (c != 0) return c;
                }
                return pa.Count.CompareTo(pb.Count);
            }

            private static bool IsDigits(string s) { return s.Length > 0 && char.IsDigit(s[0]); }

            private static List<string> Parts(string text)
            {
                var o = new List<string>();
                var sb = new StringBuilder();
                bool digits = false;
                foreach (char ch in text)
                {
                    bool d = ch >= '0' && ch <= '9';
                    if (sb.Length > 0 && d != digits) { o.Add(sb.ToString()); sb.Clear(); }
                    digits = d;
                    sb.Append(ch);
                }
                if (sb.Length > 0) o.Add(sb.ToString());
                return o;
            }
        }

        public static string ViewRowText(ViewRow r)
        {
            string kind;
            if (!ViewKindLabels.TryGetValue(r.Type ?? "", out kind)) kind = r.Type;
            return r.Name + "   |   " + kind + "   |   1:" + r.Scale.ToString(CultureInfo.InvariantCulture);
        }

        public static string SheetRowText(SheetRow r)
        {
            int n = r.Views.Count;
            return r.Number + " - " + r.Name + "   (" + n.ToString(CultureInfo.InvariantCulture) + " plan / section view" + (n == 1 ? "" : "s") + ")";
        }

        public static List<ViewRow> FilterViewRows(IEnumerable<ViewRow> rows, string query, string kind = "all")
        {
            var o = new List<ViewRow>();
            foreach (ViewRow r in rows)
            {
                bool plan = Array.IndexOf(PlanViewTypes, r.Type) >= 0;
                if (kind == "floor" && r.Type != "FloorPlan") continue;
                if (kind == "plan" && !plan) continue;
                if (kind == "section" && plan) continue;
                if (MatchWords(ViewRowText(r), query)) o.Add(r);
            }
            return o;
        }

        public static List<SheetRow> FilterSheetRows(IEnumerable<SheetRow> rows, string query)
        {
            return rows.Where(r => MatchWords(r.Number + " " + r.Name, query)).ToList();
        }

        /// <summary>Every view key to dimension in: the ticked views plus each view on a ticked sheet, each once, in order.</summary>
        public static List<long> ChosenViews(IEnumerable<long> viewKeys, IEnumerable<long> sheetKeys, IEnumerable<SheetRow> sheets)
        {
            var o = new List<long>();
            var seen = new HashSet<long>();
            var bySheet = new Dictionary<long, List<long>>();
            foreach (SheetRow r in sheets) bySheet[r.Key] = r.Views;
            var all = new List<long>(viewKeys);
            foreach (long sk in sheetKeys)
            {
                List<long> v;
                if (bySheet.TryGetValue(sk, out v)) all.AddRange(v);
            }
            foreach (long k in all)
                if (seen.Add(k)) o.Add(k);
            return o;
        }

        // ------------------------------------------------------------------ search
        /// <summary>The house search: every word of the query, in any order, any case.</summary>
        public static bool MatchWords(string text, string query)
        {
            string t = (text ?? "").ToLowerInvariant();
            foreach (string w in (query ?? "").ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries))
                if (t.IndexOf(w, StringComparison.Ordinal) < 0) return false;
            return true;
        }

        public static string NextMode(string mode)
        {
            int i = Array.IndexOf(ThemeModes, mode);
            return i < 0 ? "auto" : ThemeModes[(i + 1) % ThemeModes.Length];
        }

        /// <summary>auto follows Revit's canvas; an unreadable canvas falls back to dark.</summary>
        public static string ResolveTheme(string mode, bool? canvasIsDark)
        {
            if (mode == "dark" || mode == "light") return mode;
            if (canvasIsDark == null) return "dark";
            return canvasIsDark.Value ? "dark" : "light";
        }

        // ------------------------------------------------------------------ vectors
        public static V3 VSub(V3 a, V3 b) { return new V3(a.X - b.X, a.Y - b.Y, a.Z - b.Z); }
        public static V3 VAdd(V3 a, V3 b) { return new V3(a.X + b.X, a.Y + b.Y, a.Z + b.Z); }
        public static V3 VScale(V3 a, double s) { return new V3(a.X * s, a.Y * s, a.Z * s); }
        public static double VDot(V3 a, V3 b) { return a.X * b.X + a.Y * b.Y + a.Z * b.Z; }
        public static double VLen(V3 a) { return Math.Sqrt(VDot(a, a)); }

        public static V3 VNorm(V3 a)
        {
            double n = VLen(a);
            if (n < 1e-12) return new V3(0, 0, 0);
            return new V3(a.X / n, a.Y / n, a.Z / n);
        }

        /// <summary>t (clamped to 0..1), the point and the distance of p on segment a-b.</summary>
        public static void ClosestOnSegment(V3 p, V3 a, V3 b, out double t, out V3 q, out double dist)
        {
            V3 ab = VSub(b, a);
            double den = VDot(ab, ab);
            if (den < 1e-12)
            {
                t = 0.0; q = a; dist = VLen(VSub(p, a));
                return;
            }
            t = VDot(VSub(p, a), ab) / den;
            t = Math.Max(0.0, Math.Min(1.0, t));
            q = VAdd(a, VScale(ab, t));
            dist = VLen(VSub(p, q));
        }

        // ------------------------------------------------------------------ rehosting
        /// <summary>Nearest horizontal straight to point p. Dist is the distance from connector 0, clamped so the
        /// hanger is never asked to sit on the very end of the straight. Null if none within maxDistFt.</summary>
        public static NearestHostResult NearestHost(V3 p, IEnumerable<HostSeg> hosts, double maxDistFt, double marginFt)
        {
            HostSeg bestHost = null;
            double bestD = 0, bestT = 0;
            foreach (HostSeg h in hosts)
            {
                if (!h.Horizontal) continue;
                double t, d; V3 q;
                ClosestOnSegment(p, h.A, h.B, out t, out q, out d);
                if (d > maxDistFt) continue;
                if (bestHost == null)
                {
                    bestHost = h; bestD = d; bestT = t;
                    continue;
                }
                double r1 = Math.Round(d, 6, MidpointRounding.AwayFromZero), r0 = Math.Round(bestD, 6, MidpointRounding.AwayFromZero);
                if (r1 < r0 || (r1 == r0 && h.Id < bestHost.Id)) { bestHost = h; bestD = d; bestT = t; }
            }
            if (bestHost == null) return null;
            double length = VLen(VSub(bestHost.B, bestHost.A));
            double dist;
            if (length > 2.0 * marginFt) dist = Math.Max(marginFt, Math.Min(length - marginFt, bestT * length));
            else dist = length / 2.0;
            return new NearestHostResult { Host = bestHost, Dist = dist, D = bestD, T = bestT };
        }

        // ------------------------------------------------------------------ run / spans
        public static readonly string[] Takeoff = { "tap", "tee_branch" };

        private static readonly Dictionary<string, int> Priority = new Dictionary<string, int>
        {
            {"bend", 0}, {"accessory", 0}, {"vertical", 1}, {"tee_main", 2}, {"open", 3}, {"other", 3},
            {"loop", 3}, {"tap", 4}, {"tee_branch", 4},
        };

        private static bool IsTakeoff(string t) { return t == "tap" || t == "tee_branch"; }

        private static SpanEnd End(string type, long? id) { return new SpanEnd { Type = type, Id = id }; }

        /// <summary>Walk away from part pid through connector exitIdx. Straights and in-line parts are walked
        /// through; anything else ends the span and says what kind of end it is.</summary>
        private static SpanEnd WalkDir(Dictionary<long, PartRec> parts, long pid, int? exitIdx, HashSet<long> visited, List<ChainItem> items)
        {
            long cur = pid;
            int? ex = exitIdx;
            while (true)
            {
                List<ConnRec> conns = parts[cur].Conns;
                if (ex == null || ex.Value >= conns.Count) return End("open", null);
                ConnRec c = conns[ex.Value];
                long? nid = c.To;
                if (nid == null || !parts.ContainsKey(nid.Value)) return End("open", null);
                PartRec n = parts[nid.Value];
                int? nin = c.ToConn;
                string kind = n.Kind;
                if (kind == "straight" || kind == "inline")
                {
                    if (kind == "straight" && !n.Horizontal) return End("vertical", nid);
                    if (visited.Contains(nid.Value) || nin == null || n.Conns.Count != 2)
                        return End(visited.Contains(nid.Value) ? "loop" : "other", nid);
                    int nxt = 1 - nin.Value;
                    items.Add(new ChainItem { Id = nid.Value, Kind = kind, Len = n.Len, Entry = nin.Value, Exit = nxt });
                    visited.Add(nid.Value);
                    cur = nid.Value;
                    ex = nxt;
                    continue;
                }
                if (kind == "bend") return End("bend", nid);
                if (kind == "accessory") return End("accessory", nid);
                if (kind == "tee")
                {
                    string role = null;
                    if (nin != null && nin.Value < n.Conns.Count) role = n.Conns[nin.Value].Role;
                    return End(role == "branch" ? "tee_branch" : "tee_main", nid);
                }
                if (kind == "tap") return End("tap", nid);
                return End("other", nid);
            }
        }

        private static Span ReverseSpan(Span span)
        {
            var r = new Span { StartEnd = span.EndEnd, EndEnd = span.StartEnd };
            for (int i = span.Chain.Count - 1; i >= 0; i--)
            {
                ChainItem it = span.Chain[i];
                r.Chain.Add(new ChainItem { Id = it.Id, Kind = it.Kind, Len = it.Len, Entry = it.Exit, Exit = it.Entry });
            }
            return r;
        }

        private static int PriorityOf(string type)
        {
            int p;
            return Priority.TryGetValue(type ?? "", out p) ? p : 3;
        }

        /// <summary>Start the span at the end a run 'begins' from: after a bend first.</summary>
        public static Span OrientSpan(Span span)
        {
            int ps = PriorityOf(span.StartEnd.Type), pe = PriorityOf(span.EndEnd.Type);
            if (pe < ps) return ReverseSpan(span);
            if (pe == ps && span.Chain[0].Id > span.Chain[span.Chain.Count - 1].Id) return ReverseSpan(span);
            return span;
        }

        public static double SpanLength(Span span)
        {
            double s = 0;
            foreach (ChainItem it in span.Chain) s += it.Len;
            return s;
        }

        /// <summary>Group horizontal straights into spans. A span is a maximal chain of straights joined directly
        /// or through in-line parts; bends, tees, taps, vertical drops and open ends finish it.</summary>
        public static List<Span> BuildSpans(Dictionary<long, PartRec> parts)
        {
            var visited = new HashSet<long>();
            var spans = new List<Span>();
            var ids = parts.Keys.ToList();
            ids.Sort();
            foreach (long pid in ids)
            {
                PartRec p = parts[pid];
                if (p.Kind != "straight" || !p.Horizontal) continue;
                if (visited.Contains(pid) || p.Conns.Count != 2) continue;
                visited.Add(pid);
                var fwd = new List<ChainItem>();
                SpanEnd fend = WalkDir(parts, pid, 1, visited, fwd);
                var bwd = new List<ChainItem>();
                SpanEnd bend = WalkDir(parts, pid, 0, visited, bwd);
                var span = new Span { StartEnd = bend, EndEnd = fend };
                for (int i = bwd.Count - 1; i >= 0; i--)
                {
                    ChainItem it = bwd[i];
                    span.Chain.Add(new ChainItem { Id = it.Id, Kind = it.Kind, Len = it.Len, Entry = it.Exit, Exit = it.Entry });
                }
                span.Chain.Add(new ChainItem { Id = pid, Kind = "straight", Len = p.Len, Entry = 0, Exit = 1 });
                span.Chain.AddRange(fwd);
                spans.Add(OrientSpan(span));
            }
            return spans;
        }

        // ------------------------------------------------------------------ stations
        /// <summary>Hanger stations (feet from the span start) for one span.
        /// The first hanger sits StartOff from the start (TakeoffClear at a takeoff), then one every Spacing; a span
        /// finishing at a bend or set down gets a hanger EndOff before it, spacing allowed to shrink to fit it in;
        /// a short span that starts or ends at a takeoff is a takeoff stub: no hangers.</summary>
        public static List<double> PlanStations(double lengthFt, string startType, string endType, PlanConfig cfg)
        {
            double L = lengthFt * MM;
            double S = cfg.Spacing, a = cfg.StartOff, b = cfg.EndOff, tk = cfg.TakeoffClear, mg = cfg.MinGap, edge = cfg.Edge;
            var none = new List<double>();
            if (L < 2.0 * edge) return none;
            bool hasTakeoff = IsTakeoff(startType) || IsTakeoff(endType);
            if (hasTakeoff && L <= cfg.TakeoffMax) return none;
            double first = IsTakeoff(startType) ? tk : a;
            bool endRequired = endType == "bend" || endType == "vertical" || endType == "accessory";
            double last;
            if (endRequired) last = L - b;
            else if (IsTakeoff(endType)) last = L - tk;
            else if (endType == "tee_main") last = L - a;
            else last = L - edge;
            if (first > last) return new List<double> { L / 2.0 / MM };
            if (last - first < mg)
                return endRequired ? new List<double> { ((first + last) / 2.0) / MM } : new List<double> { first / MM };
            var stations = new List<double> { first };
            double p = first;
            if (endRequired)
            {
                while (p + S < last - mg)
                {
                    p += S;
                    stations.Add(p);
                }
                double gap = last - p;
                if (gap > S + 1e-6)
                {
                    int n = (int)Math.Ceiling(gap / S - 1e-9);
                    double step = gap / n;
                    for (int i = 1; i < n; i++) stations.Add(p + step * i);
                }
                stations.Add(last);
            }
            else
            {
                while (p + S <= last + 1e-6)
                {
                    p += S;
                    stations.Add(p);
                }
            }
            return stations.Select(s => s / MM).ToList();
        }

        /// <summary>Station along a span -> (straight id, entry connector, distance, station). A station that falls
        /// inside an in-line part (reducer, damper) or too close to a joint is moved to the nearest spot a hanger can sit.</summary>
        public static Located Locate(List<ChainItem> chain, double stationFt, double marginFt)
        {
            double pos = 0.0;
            Located best = null;
            double bestD = 0, bestStart = 0;
            foreach (ChainItem it in chain)
            {
                if (it.Kind == "straight" && it.Len > 2.0 * marginFt)
                {
                    double lo = pos + marginFt, hi = pos + it.Len - marginFt;
                    double d, s;
                    if (stationFt < lo) { d = lo - stationFt; s = lo; }
                    else if (stationFt > hi) { d = stationFt - hi; s = hi; }
                    else { d = 0.0; s = stationFt; }
                    double rd = Math.Round(d, 9, MidpointRounding.AwayFromZero);
                    if (best == null || rd < bestD || (rd == bestD && pos < bestStart))
                    {
                        best = new Located { Id = it.Id, Entry = it.Entry, Dist = s - pos, Station = s };
                        bestD = rd; bestStart = pos;
                    }
                }
                pos += it.Len;
            }
            return best;
        }

        public static List<double> Dedupe(IEnumerable<double> stations, double minSepFt)
        {
            var o = new List<double>();
            var sorted = stations.ToList();
            sorted.Sort();
            foreach (double s in sorted)
                if (o.Count == 0 || s - o[o.Count - 1] >= minSepFt) o.Add(s);
            return o;
        }

        /// <summary>Remove stations within clearFt of a hanger that is already there.</summary>
        public static List<double> DropNear(IEnumerable<double> stations, IEnumerable<double> existing, double clearFt)
        {
            var ex = existing.ToList();
            return stations.Where(s => ex.All(e => Math.Abs(s - e) > clearFt)).ToList();
        }

        // ------------------------------------------------------------------ dimensions
        /// <summary>Side of the run the dimension string goes on: toward -Y (below the run on screen), else +X for a run along Y.</summary>
        public static V3 ChooseNormal(V3 direction)
        {
            V3 n = VNorm(new V3(direction.Y, -direction.X, 0.0));
            if (Math.Abs(n.Y) > 1e-6)
            {
                if (n.Y > 0) n = VScale(n, -1.0);
            }
            else if (n.X < 0) n = VScale(n, -1.0);
            return n;
        }

        /// <summary>Dimension line for a span: parallel to it, offset to the chosen side and run a little past both ends.</summary>
        public static void DimLine(V3 pStart, V3 pEnd, double offsetMm, out V3 p0, out V3 p1, out V3 normal, double overMm = 300.0)
        {
            V3 d = VNorm(VSub(pEnd, pStart));
            V3 n = ChooseNormal(d);
            V3 off = VScale(n, offsetMm / MM);
            double ext = overMm / MM;
            p0 = VAdd(VAdd(pStart, off), VScale(d, -ext));
            p1 = VAdd(VAdd(pEnd, off), VScale(d, ext));
            normal = n;
        }

        /// <summary>Dimension line for a run seen in a section / elevation: offset DOWN the view and lying in the
        /// view's plane (through origin, normal the view direction) so Revit can draw it.</summary>
        public static void DimLineInView(V3 pStart, V3 pEnd, double offsetMm, V3 up, V3 normal, V3 origin, out V3 p0, out V3 p1, double overMm = 300.0)
        {
            V3 d = VNorm(VSub(pEnd, pStart));
            V3 off = VScale(VNorm(up), -offsetMm / MM);
            double ext = overMm / MM;
            V3 n = VNorm(normal);
            Func<V3, V3> onto = p => VSub(p, VScale(n, VDot(VSub(p, origin), n)));
            p0 = onto(VAdd(VAdd(pStart, off), VScale(d, -ext)));
            p1 = onto(VAdd(VAdd(pEnd, off), VScale(d, ext)));
        }

        /// <summary>items sorted by t; refs closer than tolFt keep the first.</summary>
        public static List<KeyValuePair<double, T>> CollapseRefs<T>(IEnumerable<KeyValuePair<double, T>> items, double tolFt)
        {
            var o = new List<KeyValuePair<double, T>>();
            // a stable sort on t, as Python's sorted(key=t)
            foreach (var kv in items.Select((x, i) => new { x, i }).OrderBy(z => z.x.Key).ThenBy(z => z.i).Select(z => z.x))
            {
                if (o.Count > 0 && kv.Key - o[o.Count - 1].Key < tolFt) continue;
                o.Add(kv);
            }
            return o;
        }

        // ------------------------------------------------------------------ rods
        /// <summary>Value to give SetRodLength so the rod top reaches hitZ. GetRodLength includes the structural
        /// extension, SetRodLength excludes it.</summary>
        public static double RodTargetLength(double curTotalFt, double endZ, double hitZ, double structExtFt = 0.0)
        {
            return (curTotalFt + (hitZ - endZ)) - structExtFt;
        }

        /// <summary>True if the rod top is at the soffit, or inside the allowed extension.</summary>
        public static bool RodOk(double endZ, double hitZ, double extFt, double tolFt)
        {
            return (Math.Abs(endZ - hitZ) <= tolFt) || (hitZ - tolFt <= endZ && endZ <= hitZ + extFt + tolFt);
        }

        // ------------------------------------------------------------------ span positions
        /// <summary>Chain items + id -> (entry point, exit point) -> segments in span order.</summary>
        public static List<SpanSeg> SpanSegments(IEnumerable<ChainItem> chain, IDictionary<long, KeyValuePair<V3, V3>> points)
        {
            var o = new List<SpanSeg>();
            double s = 0.0;
            foreach (ChainItem it in chain)
            {
                KeyValuePair<V3, V3> pts;
                if (it.Kind == "straight" && points.TryGetValue(it.Id, out pts))
                    o.Add(new SpanSeg { S0 = s, A = pts.Key, B = pts.Value, Id = it.Id });
                s += it.Len;
            }
            return o;
        }

        /// <summary>Station (ft from span start) of a point lying on the span, else null. Only the plan offset
        /// counts against maxOffFt (a hanger or tap sits above or below the centreline); the vertical offset is allowed up to 5 ft.</summary>
        public static double? StationOfPoint(IEnumerable<SpanSeg> segs, V3 p, double maxOffFt)
        {
            double? best = null; double bestDxy = 0;
            foreach (SpanSeg sg in segs)
            {
                double t, d; V3 q;
                ClosestOnSegment(p, sg.A, sg.B, out t, out q, out d);
                double dxy = Math.Sqrt((p.X - q.X) * (p.X - q.X) + (p.Y - q.Y) * (p.Y - q.Y));
                double dz = Math.Abs(p.Z - q.Z);
                if (dxy > maxOffFt || dz > 5.0) continue;
                double segLen = VLen(VSub(sg.B, sg.A));
                if ((t <= 0.0 || t >= 1.0) && VLen(VSub(p, q)) > maxOffFt) continue;
                double st = sg.S0 + t * segLen;
                if (best == null || dxy < bestDxy) { best = st; bestDxy = dxy; }
            }
            return best;
        }

        /// <summary>Station of a hanger that really sits ON this span, else null. Stricter than StationOfPoint: the
        /// point must project inside a segment (endTolFt of slack at the ends, no clamping).</summary>
        public static double? StationOnRun(IEnumerable<SpanSeg> segs, V3 p, double maxOffFt, double endTolFt = 10.0 / MM, double maxDzFt = 5.0)
        {
            double? best = null; double bestDxy = 0;
            foreach (SpanSeg sg in segs)
            {
                V3 ab = VSub(sg.B, sg.A);
                double L = VLen(ab);
                if (L < 1e-9) continue;
                V3 d = VScale(ab, 1.0 / L);
                double along = VDot(VSub(p, sg.A), d);
                if (along < -endTolFt || along > L + endTolFt) continue;
                V3 q = VAdd(sg.A, VScale(d, along));
                double dxy = Math.Sqrt((p.X - q.X) * (p.X - q.X) + (p.Y - q.Y) * (p.Y - q.Y));
                if (dxy > maxOffFt || Math.Abs(p.Z - q.Z) > maxDzFt) continue;
                double st = sg.S0 + Math.Max(0.0, Math.Min(L, along));
                if (best == null || dxy < bestDxy) { best = st; bestDxy = dxy; }
            }
            return best;
        }

        /// <summary>Move stations off takeoffs (taps on the run). A station within clearFt of a block moves to the
        /// nearer side of it, as long as that spot is on the span and clear of every other block; if neither side
        /// is free the station is dropped.</summary>
        public static List<double> AvoidBlocks(IEnumerable<double> stations, IList<double> blocks, double clearFt, double lengthFt, double edgeFt)
        {
            if (blocks == null || blocks.Count == 0) return stations.ToList();
            Func<double, bool> free = s => edgeFt <= s && s <= lengthFt - edgeFt && blocks.All(b => Math.Abs(s - b) >= clearFt - 1e-9);
            var o = new List<double>();
            foreach (double s in stations)
            {
                if (free(s)) { o.Add(s); continue; }
                double near = blocks[0];
                foreach (double b in blocks) if (Math.Abs(s - b) < Math.Abs(s - near)) near = b;   // min() keeps the first of equals
                var options = new List<double> { near - clearFt, near + clearFt };
                if (Math.Abs(options[1] - s) < Math.Abs(options[0] - s)) options.Reverse();
                foreach (double c in options)
                    if (free(c)) { o.Add(c); break; }
            }
            o.Sort();
            return o;
        }

        /// <summary>A restricted range covering the size wins (tightest first); an unrestricted condition is the fallback. Null if none.</summary>
        public static int? PickCondition(IEnumerable<Condition> conditions, double sizeFt)
        {
            var hits = new List<KeyValuePair<double, int>>();
            int? loose = null;
            foreach (Condition c in conditions)
            {
                if (c.Unrestricted)
                {
                    if (loose == null) loose = c.Index;
                    continue;
                }
                double hi = c.Upper;
                if (hi < 0) hi = 1e9;   // open-ended upper bound
                if (c.Lower - 1e-6 <= sizeFt && sizeFt <= hi + 1e-6) hits.Add(new KeyValuePair<double, int>(hi - c.Lower, c.Index));
            }
            if (hits.Count > 0)
            {
                KeyValuePair<double, int> b = hits[0];
                foreach (var h in hits)
                    if (h.Key < b.Key || (h.Key == b.Key && h.Value < b.Value)) b = h;
                return b.Value;
            }
            return loose;
        }

        // ------------------------------------------------------------------ window size
        /// <summary>(height, top) that shows the whole tab: grow or shrink the window by the difference between the
        /// tab's content and the space it has now, never taller than the working area or shorter than the minimum,
        /// and moved up if it would run off the bottom of the screen.</summary>
        public static void FitHeight(double winH, double viewportH, double contentH, double minH, double top, double waTop, double waH, out double height, out double newTop)
        {
            double h = winH + (contentH - viewportH);
            h = Math.Max(minH, Math.Min(h, waH));
            if (top + h > waTop + waH) top = Math.Max(waTop, waTop + waH - h);
            if (top < waTop) top = waTop;
            height = h; newTop = top;
        }

        // ------------------------------------------------------------------ hanger matching
        /// <summary>Lower-case word tokens with every digit removed, so 'Clevis 300' and 'CLEVIS-450' share 'clevis'.</summary>
        public static HashSet<string> NameTokens(params string[] texts)
        {
            var o = new HashSet<string>(StringComparer.Ordinal);
            foreach (string t in texts)
            {
                var word = new StringBuilder();
                foreach (char ch in (t ?? "").ToLowerInvariant() + " ")
                {
                    if (char.IsLetter(ch)) word.Append(ch);
                    else
                    {
                        if (word.Length >= 2) o.Add(word.ToString());
                        word.Clear();
                    }
                }
            }
            return o;
        }

        /// <summary>How alike two hangers are. The item id is the strongest evidence; names are compared as size-free word sets.</summary>
        public static double SignatureScore(HangerSignature old, HangerSignature nw)
        {
            double score = 0.0;
            if (!string.IsNullOrEmpty(old.ItemId) && old.ItemId == nw.ItemId) score += 5.0;
            Func<string, string> norm = x => (x ?? "").Trim().ToLowerInvariant();
            if (norm(old.Product).Length > 0 && norm(old.Product) == norm(nw.Product)) score += 2.0;
            if (norm(old.Code).Length > 0 && norm(old.Code) == norm(nw.Code)) score += 1.5;
            if (norm(old.Alias).Length > 0 && norm(old.Alias) == norm(nw.Alias)) score += 1.0;
            HashSet<string> ta = NameTokens(old.Name, old.Product, old.Alias), tb = NameTokens(nw.Name, nw.Product, nw.Alias);
            if (ta.Count > 0 && tb.Count > 0)
            {
                int inter = ta.Count(x => tb.Contains(x));
                int union = ta.Count + tb.Count - inter;
                score += 3.0 * inter / (double)union;
            }
            return score;
        }

        // ------------------------------------------------------------------ misc
        public static string Plural(int n, string one, string many = null)
        {
            return n.ToString(CultureInfo.InvariantCulture) + " " + (n == 1 ? one : (string.IsNullOrEmpty(many) ? one + "s" : many));
        }
    }
}
