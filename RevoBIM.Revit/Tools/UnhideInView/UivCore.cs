using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.UnhideInView
{
    /// <summary>A view as listed in the right-hand table.</summary>
    public sealed class UivView
    {
        public long Key;
        public View View;
        public string Name = "";
        public string Type = "";
        public long? TemplateKey;
        public ElementId TemplateId;
        public string TemplateName = "";
    }

    /// <summary>One row of the hidden elements table.</summary>
    public sealed class UivElementRow
    {
        public long Key;
        public string IdText = "";
        public string Category = "";
        public string FamilyType = "";
        public string Level = "";
        public string Note = "";
        public bool Warn;
        public bool Bad;
    }

    /// <summary>A category (or subcategory) as read from the document.</summary>
    public sealed class UivCategory
    {
        public long Key;
        public Category Category;
        public string Name = "";
        public bool IsModel;
        public long? Parent;
    }

    /// <summary>Hidden state of one category in one view: hidden, and the template name when a template decides it.</summary>
    public struct UivCatState
    {
        public string ControlledBy;
    }

    public sealed class UivCategoryRow
    {
        public long Key;
        public string Name = "";
        public int HiddenIn;
        public int Targets;
        public string HiddenText = "";
        public string Note = "";
        public List<string> Templates = new List<string>();
    }

    public sealed class UivPlanElements
    {
        public long View;
        public List<long> Elements = new List<long>();
    }

    public sealed class UivPlanCategories
    {
        public long Owner;
        public bool IsTemplate;
        public List<long> Categories = new List<long>();
    }

    public sealed class UivSkip
    {
        public string Kind = "";
        public long Owner;
        public long Key;
        public string Reason = "";
    }

    public sealed class UivPlan
    {
        public List<UivPlanElements> Elements = new List<UivPlanElements>();
        public List<UivPlanCategories> Categories = new List<UivPlanCategories>();
        public List<UivSkip> Skipped = new List<UivSkip>();
    }

    public sealed class UivResult
    {
        public int ElementsOk;
        public int ElementViews;
        public int CategoriesOk;
        public int CategoryOwners;
        public List<KeyValuePair<long, long>> OkElements = new List<KeyValuePair<long, long>>();
        public List<UivPlanCategories> OkCategories = new List<UivPlanCategories>();
        public List<UivSkip> Refused = new List<UivSkip>();
        public List<UivSkip> Skipped = new List<UivSkip>();
    }

    /// <summary>
    /// Unhide in View - core rules (port of uiv_core.py, version 1.1.0). What a view is called, which views are
    /// listed, how the scan is sliced, what Unhide will do, what the buttons say, settings and palettes.
    /// </summary>
    public static class UivCore
    {
        public const string Version = "1.1.0";
        public const string ToolName = "Unhide in View";

        // ---------------------------------------------------------------- build / files --

        public static string BuildInfo()
        {
            try
            {
                Assembly assembly = typeof(UivCore).Assembly;
                string path = assembly.Location;
                string written = "";
                try { written = File.GetLastWriteTime(path).ToString("yyyy-MM-dd HH:mm:ss"); } catch (Exception) { }
                string date = "", revit = "";
                foreach (AssemblyMetadataAttribute meta in assembly.GetCustomAttributes(typeof(AssemblyMetadataAttribute), false))
                {
                    if (meta.Key == "BuildDate") date = meta.Value;
                    if (meta.Key == "RevitVersion") revit = meta.Value;
                }
                string info = assembly.GetName().Version == null ? "?" : assembly.GetName().Version.ToString(3);
                return "add-in " + info + " | built " + date + " | Revit " + revit + " build | " + path + " (written " + written + ")";
            }
            catch (Exception err)
            {
                return "build info unavailable: " + err.Message;
            }
        }

        public static string SettingsDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string SettingsPath() { return Path.Combine(SettingsDir(), "unhide_in_view.txt"); }
        public static string DebugPath() { return Path.Combine(SettingsDir(), "unhide_in_view_debug.txt"); }
        public static string ErrorPath() { return Path.Combine(SettingsDir(), "unhide_in_view_last_error.txt"); }

        // ---------------------------------------------------------------- text helpers --

        /// <summary>Every whitespace separated term in query appears in text, any case.</summary>
        public static bool KeywordMatch(string text, string query)
        {
            string q = (query ?? "").Trim().ToLowerInvariant();
            if (q.Length == 0) return true;
            string t = (text ?? "").ToLowerInvariant();
            foreach (string term in q.Split((char[])null, StringSplitOptions.RemoveEmptyEntries))
                if (!t.Contains(term)) return false;
            return true;
        }

        private static readonly Regex Digits = new Regex(@"\d+", RegexOptions.Compiled);

        /// <summary>A string that sorts P-9 before P-10 (DataView compares strings, so numbers are padded).</summary>
        public static string NaturalKey(string text)
        {
            return Digits.Replace((text ?? "").ToLowerInvariant(), m => m.Value.PadLeft(12, '0'));
        }

        public static string Plural(int n, string one, string many = null)
        {
            return n == 1 ? n + " " + one : n + " " + (many ?? one + "s");
        }

        // ---------------------------------------------------------------- views --

        private static readonly HashSet<string> SkipViewTypes = new HashSet<string>
        {
            "Schedule", "PanelSchedule", "ColumnSchedule", "ProjectBrowser", "SystemBrowser", "Internal", "Undefined",
            "Report", "CostReport", "LoadsReport", "PresureLossReport", "PressureLossReport", "SystemsAnalysisReport",
        };

        private static readonly Dictionary<string, string> ViewTypeLabels = new Dictionary<string, string>
        {
            { "FloorPlan", "Floor Plan" }, { "CeilingPlan", "Ceiling Plan" }, { "EngineeringPlan", "Structural Plan" },
            { "AreaPlan", "Area Plan" }, { "ThreeD", "3D" }, { "Section", "Section" }, { "Elevation", "Elevation" },
            { "Detail", "Detail" }, { "DraftingView", "Drafting" }, { "Legend", "Legend" }, { "DrawingSheet", "Sheet" },
            { "Rendering", "Rendering" }, { "Walkthrough", "Walkthrough" },
        };

        public static bool ViewIsListed(string viewTypeName, bool isTemplate)
        {
            return !isTemplate && !SkipViewTypes.Contains(viewTypeName ?? "");
        }

        public static string ViewTypeLabel(string viewTypeName)
        {
            string name = viewTypeName ?? "";
            string label;
            if (ViewTypeLabels.TryGetValue(name, out label)) return label;
            string split = Regex.Replace(name, "(?<=[a-z])(?=[A-Z])", " ");
            return split.Length == 0 ? "View" : split;
        }

        /// <summary>Sheets read as their number and name, the way the browser shows them.</summary>
        public static string ViewDisplayName(string name, string sheetNumber)
        {
            return string.IsNullOrEmpty(sheetNumber) ? name : sheetNumber + " - " + name;
        }

        public static string CountText(int? count)
        {
            return count == null ? "…" : count.Value.ToString();
        }

        /// <summary>The views list filter. Unscanned views are left out while the toggle is on.</summary>
        public static bool ViewRowVisible(string name, string typeLabel, int? count, string query, bool onlyHidden)
        {
            if (onlyHidden && (count == null || count.Value == 0)) return false;
            return KeywordMatch(name + " " + typeLabel, query);
        }

        public static bool RowMatchesColumns(Dictionary<string, string> values, Dictionary<string, string> filters)
        {
            foreach (KeyValuePair<string, string> f in filters)
            {
                string v;
                values.TryGetValue(f.Key, out v);
                if (!KeywordMatch(v ?? "", f.Value)) return false;
            }
            return true;
        }

        // ---------------------------------------------------------------- staging --

        /// <summary>Ticked elements keyed (view, element); ticked categories applied to whichever views are the target.</summary>
        public sealed class Staging
        {
            public Dictionary<long, HashSet<long>> Elements = new Dictionary<long, HashSet<long>>();
            public HashSet<long> Categories = new HashSet<long>();

            public void SetElement(long viewKey, long elemKey, bool on)
            {
                HashSet<long> bucket;
                if (!Elements.TryGetValue(viewKey, out bucket))
                {
                    bucket = new HashSet<long>();
                    Elements[viewKey] = bucket;
                }
                if (on) bucket.Add(elemKey); else bucket.Remove(elemKey);
                if (bucket.Count == 0) Elements.Remove(viewKey);
            }

            public bool ElementTicked(long viewKey, long elemKey)
            {
                HashSet<long> bucket;
                return Elements.TryGetValue(viewKey, out bucket) && bucket.Contains(elemKey);
            }

            public void SetCategory(long key, bool on)
            {
                if (on) Categories.Add(key); else Categories.Remove(key);
            }

            public int ElementTotal() { return Elements.Values.Sum(v => v.Count); }
            public int ElementViews() { return Elements.Values.Count(v => v.Count > 0); }

            public void PruneView(long viewKey, HashSet<long> stillHidden)
            {
                HashSet<long> bucket;
                if (!Elements.TryGetValue(viewKey, out bucket) || bucket.Count == 0) return;
                var keep = new HashSet<long>(bucket.Where(stillHidden.Contains));
                if (keep.Count > 0) Elements[viewKey] = keep; else Elements.Remove(viewKey);
            }

            public void PruneCategories(HashSet<long> offered)
            {
                Categories = new HashSet<long>(Categories.Where(offered.Contains));
            }

            public bool Anything() { return ElementTotal() > 0 || Categories.Count > 0; }
        }

        /// <summary>Categories act on the ticked views; with none ticked, on the view being looked at.</summary>
        public static List<long> TargetViews(IEnumerable<long> ticked, long? focus)
        {
            var list = ticked.ToList();
            if (list.Count > 0) return list;
            if (focus != null) return new List<long> { focus.Value };
            return new List<long>();
        }

        // ---------------------------------------------------------------- categories --

        /// <summary>Rows for the category list: categories hidden in at least one target, sorted by name.</summary>
        public static List<UivCategoryRow> SummariseCategories(List<long> targets,
            Dictionary<long, Dictionary<long, UivCatState>> stateByView, Dictionary<long, string> names)
        {
            var rows = new Dictionary<long, UivCategoryRow>();
            var templates = new Dictionary<long, SortedSet<string>>();
            foreach (long vk in targets)
            {
                Dictionary<long, UivCatState> state;
                if (!stateByView.TryGetValue(vk, out state) || state == null) continue;
                foreach (KeyValuePair<long, UivCatState> pair in state)
                {
                    UivCategoryRow r;
                    if (!rows.TryGetValue(pair.Key, out r))
                    {
                        string name;
                        r = new UivCategoryRow { Key = pair.Key, Name = names.TryGetValue(pair.Key, out name) ? name : pair.Key.ToString(), Targets = targets.Count };
                        rows[pair.Key] = r;
                        templates[pair.Key] = new SortedSet<string>(StringComparer.Ordinal);
                    }
                    r.HiddenIn++;
                    if (!string.IsNullOrEmpty(pair.Value.ControlledBy)) templates[pair.Key].Add(pair.Value.ControlledBy);
                }
            }
            foreach (UivCategoryRow r in rows.Values)
            {
                r.HiddenText = r.HiddenIn + " / " + r.Targets;
                r.Templates = templates[r.Key].ToList();
                r.Note = r.Templates.Count == 0 ? "" : r.Templates.Count == 1 ? "Template: " + r.Templates[0] : "Templates: " + string.Join(", ", r.Templates);
            }
            return rows.Values.OrderBy(r => NaturalKey(r.Name), StringComparer.Ordinal).ToList();
        }

        // ---------------------------------------------------------------- the plan --

        /// <summary>
        /// Turns what is ticked into actions. A category controlled by a template is unhidden on the template only when
        /// changeTemplates is set, once per template however many target views share it; otherwise it is skipped.
        /// </summary>
        public static UivPlan BuildPlan(Staging staging, Dictionary<long, HashSet<long>> hiddenByView, List<long> targets,
            Dictionary<long, Dictionary<long, UivCatState>> catState, bool changeTemplates, Func<long, long?> templateOf)
        {
            var plan = new UivPlan();
            foreach (long vk in staging.Elements.Keys.OrderBy(k => k))
            {
                HashSet<long> ticked = staging.Elements[vk];
                HashSet<long> hidden;
                hiddenByView.TryGetValue(vk, out hidden);
                var go = new List<long>();
                foreach (long ek in ticked.OrderBy(k => k))
                {
                    if (hidden != null && !hidden.Contains(ek))
                    {
                        plan.Skipped.Add(new UivSkip { Kind = "element", Owner = vk, Key = ek, Reason = "no longer hidden" });
                        continue;
                    }
                    go.Add(ek);
                }
                if (go.Count > 0) plan.Elements.Add(new UivPlanElements { View = vk, Elements = go });
            }

            var perOwner = new Dictionary<string, UivPlanCategories>();
            var ownerOrder = new List<string>();
            foreach (long vk in targets)
            {
                Dictionary<long, UivCatState> state;
                if (!catState.TryGetValue(vk, out state) || state == null) continue;
                foreach (long ck in staging.Categories.OrderBy(k => k))
                {
                    UivCatState pair;
                    if (!state.TryGetValue(ck, out pair)) continue;
                    bool isTemplate = false;
                    long ownerKey = vk;
                    if (!string.IsNullOrEmpty(pair.ControlledBy))
                    {
                        if (!changeTemplates)
                        {
                            plan.Skipped.Add(new UivSkip { Kind = "category", Owner = vk, Key = ck, Reason = "controlled by view template " + pair.ControlledBy });
                            continue;
                        }
                        long? t = templateOf(vk);
                        if (t == null) continue;
                        isTemplate = true;
                        ownerKey = t.Value;
                    }
                    string id = (isTemplate ? "T" : "V") + ownerKey;
                    UivPlanCategories entry;
                    if (!perOwner.TryGetValue(id, out entry))
                    {
                        entry = new UivPlanCategories { Owner = ownerKey, IsTemplate = isTemplate };
                        perOwner[id] = entry;
                        ownerOrder.Add(id);
                    }
                    if (!entry.Categories.Contains(ck)) entry.Categories.Add(ck);
                }
            }
            foreach (string id in ownerOrder) plan.Categories.Add(perOwner[id]);
            return plan;
        }

        public static void PlanCounts(UivPlan plan, out int elements, out int elementViews, out int categories, out int owners)
        {
            elements = plan.Elements.Sum(e => e.Elements.Count);
            elementViews = plan.Elements.Count;
            categories = plan.Categories.Sum(c => c.Categories.Count);
            owners = plan.Categories.Count;
        }

        /// <summary>The green button. Says what it will do; plain 'Unhide' when nothing.</summary>
        public static string UnhideLabel(int elements, int categories)
        {
            var parts = new List<string>();
            if (elements > 0) parts.Add(Plural(elements, "element"));
            if (categories > 0) parts.Add(Plural(categories, "category", "categories"));
            return parts.Count == 0 ? "Unhide" : "Unhide " + string.Join(" + ", parts);
        }

        public static string ViewsButtonLabel(int views, int hidden)
        {
            if (views == 0) return "Unhide all in ticked views";
            return "Unhide all in " + Plural(views, "view") + " (" + hidden + ")";
        }

        public static string SummariseResult(UivResult result)
        {
            var parts = new List<string>();
            if (result.ElementsOk > 0)
                parts.Add("Unhid " + Plural(result.ElementsOk, "element") + " in " + Plural(result.ElementViews, "view"));
            if (result.CategoriesOk > 0)
                parts.Add(Plural(result.CategoriesOk, "category", "categories") + " unhidden in " + Plural(result.CategoryOwners, "view"));
            if (parts.Count == 0) parts.Add("Nothing was unhidden");
            string text = string.Join(". ", parts) + ".";
            if (result.Refused.Count > 0) text += " " + result.Refused.Count + " refused - see the red rows.";
            if (result.Skipped.Count > 0) text += " " + result.Skipped.Count + " skipped - see the debug log.";
            return text;
        }

        // ---------------------------------------------------------------- theme --

        public static readonly string[] ThemeCycle = { "follow", "dark", "light" };

        public static string ThemeLabel(string mode)
        {
            return mode == "dark" ? "Dark" : mode == "light" ? "Light" : "Auto";
        }

        public static string NormaliseTheme(string mode)
        {
            string m = (mode ?? "").Trim().ToLowerInvariant();
            if (m == "auto") return "follow";
            return ThemeCycle.Contains(m) ? m : "follow";
        }

        public static string NextTheme(string mode)
        {
            int i = Array.IndexOf(ThemeCycle, NormaliseTheme(mode));
            return ThemeCycle[(i + 1) % ThemeCycle.Length];
        }

        /// <summary>What to paint: the stored mode, or the canvas when following it (dark when it cannot be read).</summary>
        public static string ResolveTheme(string mode, string canvas)
        {
            mode = NormaliseTheme(mode);
            if (mode == "dark" || mode == "light") return mode;
            return canvas == "dark" || canvas == "light" ? canvas : "dark";
        }

        public static readonly Dictionary<string, Dictionary<string, string>> Palettes = new Dictionary<string, Dictionary<string, string>>
        {
            { "dark", new Dictionary<string, string>
                {
                    { "Bg", "#232326" }, { "Card", "#2B2B2E" }, { "Field", "#1C1C1F" }, { "Bar", "#1C1C1F" }, { "Edge", "#3E3E42" },
                    { "WinEdge", "#4A4A50" }, { "Text", "#E4E4E4" }, { "Muted", "#9A9A9E" }, { "Blue", "#4FA3E3" }, { "Orange", "#E8912D" },
                    { "Green", "#3FA75A" }, { "GreenHover", "#4EC06D" }, { "Red", "#D9534F" }, { "Sel", "#2B5473" }, { "RowAlt", "#202023" },
                    { "Hover", "#33363B" }, { "Staged", "#4A3519" }, { "BadWash", "#4A2523" }, { "OnAccent", "#FFFFFF" }, { "Tick", "#10243A" },
                    { "Disabled", "#5A5A60" },
                } },
            { "light", new Dictionary<string, string>
                {
                    { "Bg", "#F3F3F5" }, { "Card", "#FFFFFF" }, { "Field", "#FFFFFF" }, { "Bar", "#E6E7EA" }, { "Edge", "#C9CBD1" },
                    { "WinEdge", "#AEB1B8" }, { "Text", "#1E1F22" }, { "Muted", "#5F6168" }, { "Blue", "#1B72BE" }, { "Orange", "#B96A12" },
                    { "Green", "#2E8546" }, { "GreenHover", "#37A055" }, { "Red", "#C0392B" }, { "Sel", "#CFE3F5" }, { "RowAlt", "#F7F8FA" },
                    { "Hover", "#E9EEF4" }, { "Staged", "#FBE6CC" }, { "BadWash", "#F7D9D6" }, { "OnAccent", "#FFFFFF" }, { "Tick", "#FFFFFF" },
                    { "Disabled", "#B5B7BD" },
                } },
        };

        // ---------------------------------------------------------------- shrink to taskbar (WPF units) --

        public const double DrawerSeconds = 0.28;
        public const int DrawerTickMs = 15;
        public const double DrawerMargin = 8.0;
        public const double DrawerMoved = 2.0;

        public const string ShrinkTip = "Shrink to the bottom of the screen (Ctrl+Shift+H)";
        public const string ExpandTip = "Open the window again (Ctrl+Shift+H, Enter or double-click the bar)";

        /// <summary>Cubic ease-out, 0..1 -> 0..1.</summary>
        public static double EaseOut(double p)
        {
            if (double.IsNaN(p) || p >= 1.0) return 1.0;
            if (p <= 0.0) return 0.0;
            return 1.0 - Math.Pow(1.0 - p, 3);
        }

        public static double Lerp(double a, double b, double t) { return a + (b - a) * t; }

        public static double BarHeight(double headerHeight, double frameOffset)
        {
            return Math.Max(1.0, headerHeight + 2.0 * Math.Max(0.0, frameOffset));
        }

        /// <summary>Top of the parked bar: clear of the taskbar at the bottom of the screen's working area.</summary>
        public static double ParkedTop(double[] area, double barHeight)
        {
            return area[1] + area[3] - DrawerMargin - barHeight;
        }

        public static bool BarMoved(double[] parked, double[] now)
        {
            return Math.Abs(now[0] - parked[0]) > DrawerMoved || Math.Abs(now[1] - parked[1]) > DrawerMoved;
        }

        public static double Clamp(double v, double low, double high)
        {
            return high < low ? low : Math.Max(low, Math.Min(high, v));
        }

        /// <summary>
        /// Where the window opens to (left, top, width, height). Back where it was if the bar was not moved; otherwise
        /// upward from where the bar now sits, kept on the screen the bar is on.
        /// </summary>
        public static double[] ExpandBounds(double[] saved, double[] parked, double[] now, double barHeight, double[] area)
        {
            if (!BarMoved(parked, now)) return saved;
            double h = Math.Min(saved[3], area[3]);
            double w = Math.Min(saved[2], area[2]);
            double top = Clamp(now[1] + barHeight - h, area[1], area[1] + area[3] - h);
            double left = Clamp(now[0], area[0], area[0] + area[2] - w);
            return new[] { left, top, w, h };
        }

        // ---------------------------------------------------------------- settings --

        public const string SettingsVersion = "1";

        public static readonly Dictionary<string, string> Defaults = new Dictionary<string, string>
        {
            { "settings_version", SettingsVersion },
            { "theme", "follow" },
            { "debug", "1" },
            { "only_hidden", "0" },
            { "change_templates", "0" },
            { "width", "1320" },
            { "height", "800" },
            { "split", "0.56" },
            { "cat_split", "0.34" },
            { "scan_budget_ms", "120" },
        };

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
                        int eq = line.IndexOf('=');
                        if (line.Length == 0 || line.StartsWith("#") || eq < 0) continue;
                        string key = line.Substring(0, eq).Trim();
                        if (Defaults.ContainsKey(key)) values[key] = line.Substring(eq + 1).Trim();
                    }
                }
            }
            catch (Exception)
            {
            }
            values["settings_version"] = SettingsVersion;
            values["theme"] = NormaliseTheme(values["theme"]);
            return values;
        }

        public static bool SaveSettings(Dictionary<string, string> values)
        {
            try
            {
                Directory.CreateDirectory(SettingsDir());
                var sb = new StringBuilder("# RevoBIM Unhide in View settings - key=value\n");
                foreach (string key in Defaults.Keys.OrderBy(k => k, StringComparer.Ordinal))
                {
                    string v;
                    sb.Append(key).Append('=').Append(values.TryGetValue(key, out v) ? v : Defaults[key]).Append('\n');
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
            return s.TryGetValue(key, out v) ? v : (Defaults.TryGetValue(key, out v) ? v : "");
        }

        public static bool AsBool(string value)
        {
            string v = (value ?? "").Trim().ToLowerInvariant();
            return v == "1" || v == "true" || v == "yes" || v == "on";
        }

        public static double AsDouble(string value, double fallback, double low, double high)
        {
            double v;
            if (!double.TryParse(value, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out v)) v = fallback;
            return Math.Max(low, Math.Min(high, v));
        }

        // ---------------------------------------------------------------- debug log --

        /// <summary>Lines kept in memory for Copy debug, mirrored to the debug file. Never throws.</summary>
        public sealed class DebugLog
        {
            private const int Limit = 6000;
            public bool Enabled;
            public readonly List<string> Lines = new List<string>();

            public DebugLog(bool enabled) { Enabled = enabled; }

            public void Add(string text)
            {
                if (!Enabled) return;
                lock (Lines)
                {
                    Lines.Add(DateTime.Now.ToString("HH:mm:ss.fff") + " " + text);
                    if (Lines.Count > Limit) Lines.RemoveRange(0, Lines.Count - Limit);
                }
            }

            public string Text(string header)
            {
                lock (Lines) return (string.IsNullOrEmpty(header) ? "" : header + "\r\n") + string.Join("\r\n", Lines);
            }

            public bool Flush(string header)
            {
                if (!Enabled) return false;
                try
                {
                    Directory.CreateDirectory(SettingsDir());
                    File.WriteAllText(DebugPath(), Text(header), new UTF8Encoding(false));
                    return true;
                }
                catch (Exception)
                {
                    return false;
                }
            }
        }
    }

    /// <summary>
    /// Finds the elements hidden in each view, a slice at a time. Progress inside a view is kept, so a slice can stop half
    /// way through a big model and the next slice carries on from the same element.
    /// </summary>
    public sealed class UivScanner
    {
        private const int CheckEvery = 256;

        private sealed class Partial
        {
            public List<IList<Element>> Segments;
            public int Segment;
            public int Index;
            public List<ElementId> Found = new List<ElementId>();
        }

        private readonly Func<long, List<IList<Element>>> segmentsFor;
        private readonly Func<Element, long, bool> isHidden;
        private readonly Stopwatch clock = Stopwatch.StartNew();
        private readonly Dictionary<long, Partial> partial = new Dictionary<long, Partial>();

        public List<long> Order;
        public readonly int Total;
        public readonly Dictionary<long, List<ElementId>> Results = new Dictionary<long, List<ElementId>>();
        public int Errors;
        public long Checked;

        public UivScanner(IEnumerable<long> viewKeys, Func<long, List<IList<Element>>> segmentsFor, Func<Element, long, bool> isHidden)
        {
            Order = viewKeys.ToList();
            Total = Order.Count;
            this.segmentsFor = segmentsFor;
            this.isHidden = isHidden;
        }

        public bool Finished() { return Order.Count == 0; }
        public int Done() { return Results.Count; }

        /// <summary>Scan these next, in the order given, ahead of everything else.</summary>
        public void Bump(IEnumerable<long> viewKeys)
        {
            var wanted = new List<long>();
            foreach (long k in viewKeys) if (Order.Contains(k) && !wanted.Contains(k)) wanted.Add(k);
            if (wanted.Count == 0) return;
            var rest = Order.Where(k => !wanted.Contains(k));
            Order = wanted.Concat(rest).ToList();
        }

        /// <summary>Scans until the budget is spent; returns the views finished in this slice.</summary>
        public List<long> Step(double budgetSeconds)
        {
            double start = clock.Elapsed.TotalSeconds;
            var finished = new List<long>();
            while (Order.Count > 0)
            {
                long vk = Order[0];
                Partial st;
                if (!partial.TryGetValue(vk, out st))
                {
                    var segs = new List<IList<Element>>();
                    try
                    {
                        segs = segmentsFor(vk) ?? segs;
                    }
                    catch (Exception)
                    {
                        Errors++;
                    }
                    st = new Partial { Segments = segs };
                    partial[vk] = st;
                }
                while (st.Segment < st.Segments.Count)
                {
                    IList<Element> seg = st.Segments[st.Segment];
                    while (st.Index < seg.Count)
                    {
                        Element item = seg[st.Index];
                        st.Index++;
                        Checked++;
                        try
                        {
                            if (isHidden(item, vk)) st.Found.Add(item.Id);
                        }
                        catch (Exception)
                        {
                            Errors++;
                        }
                        if (st.Index % CheckEvery == 0 && clock.Elapsed.TotalSeconds - start >= budgetSeconds) return finished;
                    }
                    st.Segment++;
                    st.Index = 0;
                }
                Results[vk] = st.Found;
                partial.Remove(vk);
                Order.RemoveAt(0);
                finished.Add(vk);
                if (clock.Elapsed.TotalSeconds - start >= budgetSeconds) return finished;
            }
            return finished;
        }
    }
}
