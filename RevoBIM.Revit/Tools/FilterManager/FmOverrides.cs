using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.FilterManager
{
    /// <summary>
    /// The spec dict every part of the tool passes around: a filter's graphic overrides, keyed by the same names
    /// as the pyRevit tool ("visible", "enabled", "halftone", "transparency", "proj_colour" (RRGGBB text),
    /// "proj_weight" (int), "proj_pattern" (ElementId), "cut_*", "surf_fg_pattern" ...). A missing key or null
    /// means "no override".
    /// </summary>
    public class FmSpec
    {
        public readonly Dictionary<string, object> Values = new Dictionary<string, object>();

        public static readonly string[] Keys =
        {
            "visible", "enabled", "halftone", "transparency",
            "proj_colour", "proj_weight", "proj_pattern",
            "cut_colour", "cut_weight", "cut_pattern",
            "surf_fg_pattern", "surf_fg_colour", "surf_bg_pattern", "surf_bg_colour",
            "cut_fg_pattern", "cut_fg_colour", "cut_bg_pattern", "cut_bg_colour",
        };

        public FmSpec()
        {
            foreach (string k in Keys) Values[k] = null;
            Values["visible"] = true;
            Values["enabled"] = true;
            Values["halftone"] = false;
            Values["transparency"] = 0;
        }

        public object this[string key]
        {
            get { object v; return Values.TryGetValue(key, out v) ? v : null; }
            set { Values[key] = value; }
        }

        public bool Bool(string key) { object v = this[key]; return v is bool && (bool)v; }
        public int Int(string key) { try { return Convert.ToInt32(this[key] ?? 0); } catch (Exception) { return 0; } }
        public int? IntOrNull(string key) { object v = this[key]; if (v == null) return null; try { return Convert.ToInt32(v); } catch (Exception) { return null; } }
        public string Str(string key) { return this[key] as string; }
        public ElementId Id(string key) { return this[key] as ElementId; }

        public FmSpec Copy()
        {
            var c = new FmSpec();
            foreach (var kv in Values) c.Values[kv.Key] = kv.Value;
            return c;
        }
    }

    /// <summary>One entry of a pattern / weight combo: Id (null = no override) and its name.</summary>
    public class FmChoice
    {
        public object Value;      // ElementId, int, or null
        public string Name;
        public FmChoice(object value, string name) { Value = value; Name = name; }
    }

    /// <summary>
    /// Filter graphic overrides: the same set of properties Revit's own Visibility/Graphics > Filters tab asks
    /// for, read out of and written back into OverrideGraphicSettings. Port of fm_overrides.py.
    /// </summary>
    public static class FmOverrides
    {
        public const string NoOverride = "<no override>";
        public const string SolidLine = "<solid line>";

        public static FmSpec NewSpec() { return new FmSpec(); }

        // ---------------------------------------------------------------------------
        //  Colours
        // ---------------------------------------------------------------------------
        /// <summary>'#RRGGBB' or 'RRGGBB' to (r, g, b), or null.</summary>
        public static int[] ParseHex(string text)
        {
            if (text == null) return null;
            string s = text.Trim().TrimStart('#');
            if (s.Length != 6) return null;
            try
            {
                return new[]
                {
                    Convert.ToInt32(s.Substring(0, 2), 16),
                    Convert.ToInt32(s.Substring(2, 2), 16),
                    Convert.ToInt32(s.Substring(4, 2), 16),
                };
            }
            catch (Exception) { return null; }
        }

        public static string ToHex(int[] rgb)
        {
            if (rgb == null) return null;
            return rgb[0].ToString("X2") + rgb[1].ToString("X2") + rgb[2].ToString("X2");
        }

        public static Color RevitColour(string text)
        {
            int[] rgb = ParseHex(text);
            if (rgb == null) return null;
            try { return new Color((byte)rgb[0], (byte)rgb[1], (byte)rgb[2]); }
            catch (Exception) { return null; }
        }

        /// <summary>A Revit Color to 'RRGGBB', or null where it is not a real override.</summary>
        public static string ColourFromRevit(Color c)
        {
            if (c == null) return null;
            try { if (!c.IsValid) return null; }
            catch (Exception) { }
            try { return c.Red.ToString("X2") + c.Green.ToString("X2") + c.Blue.ToString("X2"); }
            catch (Exception) { return null; }
        }

        // ---------------------------------------------------------------------------
        //  Pattern lists
        // ---------------------------------------------------------------------------
        /// <summary>No-override, solid, then every line pattern by name.</summary>
        public static List<FmChoice> LinePatterns(Document doc)
        {
            var result = new List<FmChoice> { new FmChoice(null, NoOverride) };
            try { result.Add(new FmChoice(LinePatternElement.GetSolidPatternId(), SolidLine)); }
            catch (Exception) { }
            var items = new List<FmChoice>();
            try
            {
                foreach (Element lp in new FilteredElementCollector(doc).OfClass(typeof(LinePatternElement)).ToElements())
                {
                    try { items.Add(new FmChoice(lp.Id, lp.Name)); }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            items.Sort((a, b) => string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase));
            result.AddRange(items);
            return result;
        }

        public static List<FmChoice> FillPatterns(Document doc)
        {
            var result = new List<FmChoice> { new FmChoice(null, NoOverride) };
            var items = new List<FmChoice>();
            try
            {
                foreach (Element fp in new FilteredElementCollector(doc).OfClass(typeof(FillPatternElement)).ToElements())
                {
                    try { items.Add(new FmChoice(fp.Id, fp.Name)); }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            items.Sort((a, b) => string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase));
            result.AddRange(items);
            return result;
        }

        /// <summary>Revit line weights are 1 to 16; the Value of each choice is an int (null = no override).</summary>
        public static List<FmChoice> LineWeights()
        {
            var result = new List<FmChoice> { new FmChoice(null, NoOverride) };
            for (int i = 1; i <= 16; i++) result.Add(new FmChoice(i, i.ToString()));
            return result;
        }

        // ---------------------------------------------------------------------------
        //  Reading an existing override off a view
        // ---------------------------------------------------------------------------
        public static FmSpec ReadOverrides(View view, ElementId filterId)
        {
            FmSpec spec = NewSpec();
            try { spec["visible"] = view.GetFilterVisibility(filterId); }
            catch (Exception) { }
            try { spec["enabled"] = view.GetIsFilterEnabled(filterId); }
            catch (Exception) { }

            OverrideGraphicSettings ogs;
            try { ogs = view.GetFilterOverrides(filterId); }
            catch (Exception) { return spec; }
            if (ogs == null) return spec;

            spec["halftone"] = Safe<bool>(ogs, "Halftone", false);
            spec["transparency"] = Safe<int>(ogs, "Transparency", 0);

            spec["proj_colour"] = ColourFromRevit(Safe<Color>(ogs, "ProjectionLineColor", null));
            spec["proj_weight"] = Weight(Safe<int>(ogs, "ProjectionLineWeight", -1));
            spec["proj_pattern"] = Pattern(Safe<ElementId>(ogs, "ProjectionLinePatternId", null));

            spec["cut_colour"] = ColourFromRevit(Safe<Color>(ogs, "CutLineColor", null));
            spec["cut_weight"] = Weight(Safe<int>(ogs, "CutLineWeight", -1));
            spec["cut_pattern"] = Pattern(Safe<ElementId>(ogs, "CutLinePatternId", null));

            spec["surf_fg_pattern"] = Pattern(Safe<ElementId>(ogs, "SurfaceForegroundPatternId", null));
            spec["surf_fg_colour"] = ColourFromRevit(Safe<Color>(ogs, "SurfaceForegroundPatternColor", null));
            spec["surf_bg_pattern"] = Pattern(Safe<ElementId>(ogs, "SurfaceBackgroundPatternId", null));
            spec["surf_bg_colour"] = ColourFromRevit(Safe<Color>(ogs, "SurfaceBackgroundPatternColor", null));

            spec["cut_fg_pattern"] = Pattern(Safe<ElementId>(ogs, "CutForegroundPatternId", null));
            spec["cut_fg_colour"] = ColourFromRevit(Safe<Color>(ogs, "CutForegroundPatternColor", null));
            spec["cut_bg_pattern"] = Pattern(Safe<ElementId>(ogs, "CutBackgroundPatternId", null));
            spec["cut_bg_colour"] = ColourFromRevit(Safe<Color>(ogs, "CutBackgroundPatternColor", null));
            return spec;
        }

        private static T Safe<T>(object obj, string property, T fallback)
        {
            try
            {
                PropertyInfo p = obj.GetType().GetProperty(property);
                if (p == null) return fallback;
                object v = p.GetValue(obj, null);
                return v == null ? fallback : (T)v;
            }
            catch (Exception) { return fallback; }
        }

        private static int? Weight(int value) { return value >= 1 && value <= 16 ? (int?)value : null; }

        private static ElementId Pattern(ElementId pid)
        {
            if (pid == null) return null;
            try { return FmCore.EidValue(pid) > 0 ? pid : null; }
            catch (Exception) { return null; }
        }

        // ---------------------------------------------------------------------------
        //  Building an override from a spec
        // ---------------------------------------------------------------------------
        /// <summary>OverrideGraphicSettings from a spec. Anything null is left alone.</summary>
        public static OverrideGraphicSettings BuildOverrides(FmSpec spec)
        {
            var ogs = new OverrideGraphicSettings();

            Set(ogs, "SetProjectionLineColor", RevitColour(spec.Str("proj_colour")));
            Set(ogs, "SetProjectionLineWeight", spec.IntOrNull("proj_weight"));
            Set(ogs, "SetProjectionLinePatternId", spec.Id("proj_pattern"));

            Set(ogs, "SetCutLineColor", RevitColour(spec.Str("cut_colour")));
            Set(ogs, "SetCutLineWeight", spec.IntOrNull("cut_weight"));
            Set(ogs, "SetCutLinePatternId", spec.Id("cut_pattern"));

            Set(ogs, "SetSurfaceForegroundPatternId", spec.Id("surf_fg_pattern"));
            Set(ogs, "SetSurfaceForegroundPatternColor", RevitColour(spec.Str("surf_fg_colour")));
            Set(ogs, "SetSurfaceBackgroundPatternId", spec.Id("surf_bg_pattern"));
            Set(ogs, "SetSurfaceBackgroundPatternColor", RevitColour(spec.Str("surf_bg_colour")));

            Set(ogs, "SetCutForegroundPatternId", spec.Id("cut_fg_pattern"));
            Set(ogs, "SetCutForegroundPatternColor", RevitColour(spec.Str("cut_fg_colour")));
            Set(ogs, "SetCutBackgroundPatternId", spec.Id("cut_bg_pattern"));
            Set(ogs, "SetCutBackgroundPatternColor", RevitColour(spec.Str("cut_bg_colour")));

            if (spec["surf_fg_pattern"] != null) Set(ogs, "SetSurfaceForegroundPatternVisible", true);
            if (spec["surf_bg_pattern"] != null) Set(ogs, "SetSurfaceBackgroundPatternVisible", true);
            if (spec["cut_fg_pattern"] != null) Set(ogs, "SetCutForegroundPatternVisible", true);
            if (spec["cut_bg_pattern"] != null) Set(ogs, "SetCutBackgroundPatternVisible", true);

            try { ogs.SetSurfaceTransparency(Math.Max(0, Math.Min(100, spec.Int("transparency")))); }
            catch (Exception) { }
            try { ogs.SetHalftone(spec.Bool("halftone")); }
            catch (Exception) { }
            return ogs;
        }

        private static void Set(OverrideGraphicSettings ogs, string methodName, object value)
        {
            if (value == null) return;
            try
            {
                MethodInfo m = typeof(OverrideGraphicSettings).GetMethod(methodName);
                if (m == null) return;
                m.Invoke(ogs, new[] { value });
            }
            catch (Exception) { }
        }

        /// <summary>A short human summary of a spec, for the log.</summary>
        public static string Describe(FmSpec spec)
        {
            var bits = new List<string>();
            bits.Add(spec.Bool("visible") ? "visible" : "HIDDEN");
            if (!spec.Bool("enabled")) bits.Add("filter disabled");
            if (spec.Bool("halftone")) bits.Add("halftone");
            if (spec.Int("transparency") != 0) bits.Add("transparency " + spec.Int("transparency") + "%");
            if (!string.IsNullOrEmpty(spec.Str("proj_colour"))) bits.Add("line #" + spec.Str("proj_colour"));
            if (spec.Int("proj_weight") != 0) bits.Add("weight " + spec.Int("proj_weight"));
            if (!string.IsNullOrEmpty(spec.Str("surf_fg_colour"))) bits.Add("surface #" + spec.Str("surf_fg_colour"));
            if (!string.IsNullOrEmpty(spec.Str("cut_colour"))) bits.Add("cut line #" + spec.Str("cut_colour"));
            if (!string.IsNullOrEmpty(spec.Str("cut_fg_colour"))) bits.Add("cut surface #" + spec.Str("cut_fg_colour"));
            return bits.Count > 0 ? string.Join(", ", bits) : "no overrides";
        }

        // ===========================================================================
        //  Pushing some settings and not others
        // ===========================================================================
        /// <summary>The columns of "Filters to push", in Revit's own V/G order: (key, label).</summary>
        public static readonly List<Tuple<string, string>> PushGroups = new List<Tuple<string, string>>
        {
            Tuple.Create("enabled", "Enable Filter"),
            Tuple.Create("visible", "Visibility"),
            Tuple.Create("proj_lines", "Projection Lines"),
            Tuple.Create("proj_patterns", "Projection Patterns"),
            Tuple.Create("transparency", "Transparency"),
            Tuple.Create("cut_lines", "Cut Lines"),
            Tuple.Create("cut_patterns", "Cut Patterns"),
            Tuple.Create("halftone", "Halftone"),
        };

        /// <summary>group -> the OverrideGraphicSettings properties it carries: (getter, setter, kind).</summary>
        private static readonly Dictionary<string, Tuple<string, string, string>[]> OverrideGroups =
            new Dictionary<string, Tuple<string, string, string>[]>
            {
                { "proj_lines", new[] {
                    T("ProjectionLinePatternId", "SetProjectionLinePatternId", "id"),
                    T("ProjectionLineColor", "SetProjectionLineColor", "colour"),
                    T("ProjectionLineWeight", "SetProjectionLineWeight", "weight") } },
                { "proj_patterns", new[] {
                    T("SurfaceForegroundPatternId", "SetSurfaceForegroundPatternId", "id"),
                    T("SurfaceForegroundPatternColor", "SetSurfaceForegroundPatternColor", "colour"),
                    T("IsSurfaceForegroundPatternVisible", "SetSurfaceForegroundPatternVisible", "shown"),
                    T("SurfaceBackgroundPatternId", "SetSurfaceBackgroundPatternId", "id"),
                    T("SurfaceBackgroundPatternColor", "SetSurfaceBackgroundPatternColor", "colour"),
                    T("IsSurfaceBackgroundPatternVisible", "SetSurfaceBackgroundPatternVisible", "shown") } },
                { "transparency", new[] { T("Transparency", "SetSurfaceTransparency", "number") } },
                { "cut_lines", new[] {
                    T("CutLinePatternId", "SetCutLinePatternId", "id"),
                    T("CutLineColor", "SetCutLineColor", "colour"),
                    T("CutLineWeight", "SetCutLineWeight", "weight") } },
                { "cut_patterns", new[] {
                    T("CutForegroundPatternId", "SetCutForegroundPatternId", "id"),
                    T("CutForegroundPatternColor", "SetCutForegroundPatternColor", "colour"),
                    T("IsCutForegroundPatternVisible", "SetCutForegroundPatternVisible", "shown"),
                    T("CutBackgroundPatternId", "SetCutBackgroundPatternId", "id"),
                    T("CutBackgroundPatternColor", "SetCutBackgroundPatternColor", "colour"),
                    T("IsCutBackgroundPatternVisible", "SetCutBackgroundPatternVisible", "shown") } },
                { "halftone", new[] { T("Halftone", "SetHalftone", "flag") } },
            };

        private static Tuple<string, string, string> T(string getter, string setter, string kind)
        {
            return Tuple.Create(getter, setter, kind);
        }

        public static Dictionary<string, bool> AllGroups(bool value = true)
        {
            return PushGroups.ToDictionary(g => g.Item1, g => value);
        }

        private static bool GroupOn(Dictionary<string, bool> groups, string key)
        {
            bool on;
            return groups == null || !groups.TryGetValue(key, out on) || on;
        }

        public static bool GroupsAllOn(Dictionary<string, bool> groups)
        {
            return groups == null || PushGroups.All(g => GroupOn(groups, g.Item1));
        }

        /// <summary>Whether a property holds an override rather than Revit's default.</summary>
        private static bool IsOverride(object value, string kind)
        {
            if (value == null) return false;
            try
            {
                switch (kind)
                {
                    case "id": return FmCore.EidValue((ElementId)value) > 0;
                    case "colour": return ((Color)value).IsValid;
                    case "weight": return Convert.ToInt32(value) > 0;
                    case "number": return Convert.ToInt32(value) > 0;
                    case "flag": return (bool)value;
                    case "shown": return (bool)value == false;
                }
            }
            catch (Exception) { return false; }
            return false;
        }

        /// <summary>
        /// Overrides taking each ticked group from `source` and each unticked one from `baseSettings` (the
        /// target's own, or null for a filter new to it, so an unticked group is left at Revit's default).
        /// </summary>
        public static OverrideGraphicSettings MergeOverrides(OverrideGraphicSettings source, OverrideGraphicSettings baseSettings,
                                                             Dictionary<string, bool> groups)
        {
            var ogs = new OverrideGraphicSettings();
            foreach (var kv in OverrideGroups)
            {
                OverrideGraphicSettings provider = GroupOn(groups, kv.Key) ? source : baseSettings;
                if (provider == null) continue;
                foreach (var prop in kv.Value)
                {
                    object value;
                    try
                    {
                        PropertyInfo p = typeof(OverrideGraphicSettings).GetProperty(prop.Item1);
                        if (p == null) continue;
                        value = p.GetValue(provider, null);
                    }
                    catch (Exception) { continue; }
                    if (IsOverride(value, prop.Item3)) Set(ogs, prop.Item2, value);
                }
            }
            return ogs;
        }

        /// <summary>'all settings', or the ones left out, for the log.</summary>
        public static string DescribeGroups(Dictionary<string, bool> groups)
        {
            if (GroupsAllOn(groups)) return "all settings";
            var off = PushGroups.Where(g => !GroupOn(groups, g.Item1)).Select(g => g.Item2);
            return "not pushed: " + string.Join(", ", off);
        }
    }
}
