using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.LegendCreator
{
    /// <summary>One System Colour Legend recipe (pyRevit lgc_logic.SYSTEM_KINDS).</summary>
    public sealed class LegendKind
    {
        public string Key, Label, Source, Style, Template, NameToken, RegionPrefix, Heading, ViewName, GroupSuffix;
        public bool Ready, Centreline, Grouped;
        public string[] Categories;
        public double SwatchH;
    }

    /// <summary>
    /// Legend Creator - pure logic: constants, legend kinds, palettes and every
    /// calculation that needs neither Revit nor WPF. Port of lgc_logic.py.
    /// </summary>
    public static class LgcLogic
    {
        public static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        // --- The house legend standard -----------------------------------
        public const string ViewPrefix = "WIP_";
        public const string CombinedName = "WIP_COMBINED";

        // Spacings are quoted AT THE REFERENCE SCALE and scaled with the view,
        // so the spacing stays constant on paper. See ScaledMm().
        public const int ReferenceScale = 100;
        public const int DefaultScale = 100;
        public const double RowSpacingMm = 900.0;
        public const double TextOffsetMm = 1000.0;
        public const double DefaultColumnSpacingMm = 3000.0;
        public static readonly int[] ScaleChoices = { 1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000 };

        // --- System Colour Legend (quoted at 1:200) -----------------------
        public const int SystemReferenceScale = 200;
        public const int SystemDefaultScale = 200;
        public const double SwatchWMm = 2500.0;
        public const double SwatchHMm = 700.0;
        public const double SysRowPitchMm = 1600.0;
        public const double SysTextGapMm = 700.0;
        public const double SysHeadingGapMm = 1400.0;

        // Pipe system classifications, grouped for the legend, matched on keywords.
        public static readonly (string Group, string[] Keywords)[] PipeGroups =
        {
            ("Domestic", new[] { "domestic" }),
            ("Hydronic", new[] { "hydronic" }),
            ("Sanitary & Vent", new[] { "sanitary", "vent" }),
            ("Fire Protection", new[] { "fire" }),
        };
        public const string PipeGroupOther = "Other";

        public const int DefaultLineWeight = 3;
        public const int MinLineWeight = 1;
        public const int MaxLineWeight = 16;

        public const string CentrelineName = "LEG_Centreline";
        // Line patterns are paper millimetres - never scaled with the swatch.
        public const string CentrelinePatternName = "LEG_Centreline 5-2-2-2";
        public static readonly (bool Dash, double Length)[] CentrelineSegments =
            { (true, 5.0), (false, 2.0), (true, 2.0), (false, 2.0) };
        public static readonly (int R, int G, int B) CentrelineRgb = (128, 128, 128);
        public const double CentrelineOverhang = 0.4;

        public static readonly LegendKind[] SystemKinds =
        {
            new LegendKind
            {
                Key = "containment", Label = "Containment Legend", Ready = true,
                Source = "filters", Style = "fill",
                Template = "04_Documentation_Floorplan_Containment",
                Categories = new[] { "OST_CableTray", "OST_CableTrayFitting", "OST_CableTrayRun" },
                NameToken = "containment", RegionPrefix = "LEG_CONT_",
                Heading = "CONTAINMENT LEGEND", ViewName = "WIP_Containment Legend", SwatchH = 700.0,
            },
            new LegendKind
            {
                Key = "ductwork", Label = "Ductwork Legend", Ready = true,
                Source = "duct_systems", Style = "outline", Template = "",
                Categories = new[] { "OST_DuctCurves", "OST_FlexDuctCurves", "OST_DuctFitting",
                                     "OST_DuctAccessory", "OST_DuctTerminal" },
                NameToken = "", RegionPrefix = "LEG_DUCT_",
                Heading = "DUCTWORK LEGEND", ViewName = "WIP_Ductwork Legend", SwatchH = 700.0,
            },
            new LegendKind
            {
                Key = "pipework", Label = "Pipework Legend", Ready = true,
                Source = "pipe_systems", Style = "outline",
                Centreline = true, Grouped = true, GroupSuffix = "PIPEWORK LEGEND", Template = "",
                Categories = new[] { "OST_PipeCurves", "OST_FlexPipeCurves", "OST_PipeFitting",
                                     "OST_PipeAccessory" },
                NameToken = "", RegionPrefix = "LEG_PIPE_",
                Heading = "PIPEWORK LEGEND", ViewName = "WIP_Pipework Legend",
                // 75mm at 1:50 = 300mm at the 1:200 reference - a thin band
                SwatchH = 300.0,
            },
        };

        public const string DefaultPhase = "New Construction";
        public const string DefaultNameParam = "Description";
        public const string CaseAsIs = "asis";
        public const string CaseUpper = "upper";
        public const string CaseCamel = "camel";
        public const string DefaultCase = CaseAsIs;

        public const string NameTypeName = "<Type Name>";
        public const string NameFamilyType = "<Family : Type>";

        // Categories that can take Revit down as legend components - never offered.
        public static readonly string[] BlockedCategories =
        {
            "OST_RvtLinks", "OST_IOSModelGroups", "OST_Mass", "OST_MassForm",
            "OST_Parts", "OST_Topography", "OST_Toposolid", "OST_BuildingPad",
            "OST_RasterImages", "OST_Rebar", "OST_AreaRein", "OST_PathRein",
            "OST_FabricAreas", "OST_FabricReinforcement", "OST_StructConnections",
            "OST_PipingSystem", "OST_DuctSystem", "OST_ElectricalCircuit",
            "OST_SwitchSystem", "OST_Rooms", "OST_MEPSpaces", "OST_Areas",
            "OST_HVAC_Zones", "OST_Coordination_Model", "OST_PointClouds",
        };

        // The only things ClearLegend is ever allowed to delete.
        public static readonly string[] ClearableCategories =
        {
            "OST_LegendComponents", "OST_TextNotes", "OST_DetailComponents",
            "OST_Lines", "OST_FilledRegion", "OST_MaskingRegion",
            "OST_GenericAnnotation", "OST_Dimensions",
        };

        // --- Palettes - both must carry every key ---------------------------
        public static readonly Dictionary<string, Dictionary<string, string>> Palettes =
            new Dictionary<string, Dictionary<string, string>>
            {
                ["dark"] = new Dictionary<string, string>
                {
                    ["Base"] = "#3C4454", ["Card"] = "#353D4B", ["Field"] = "#2D3441",
                    ["Bar"] = "#212932", ["Line"] = "#4B5566", ["Edge"] = "#586376",
                    ["Ink"] = "#F0F0F8", ["Muted"] = "#AEB4BB", ["Blue"] = "#4FA3E3",
                    ["BlueHover"] = "#8FBEFC", ["Orange"] = "#E8912D", ["Green"] = "#3FA75A",
                    ["GreenHover"] = "#4EC06D", ["OnGreen"] = "#0E2214", ["Red"] = "#D9534F",
                    ["Sel"] = "#2B5473", ["RowEvenBrush"] = "#353D4B", ["RowOddBrush"] = "#2D3441",
                    ["RowHover"] = "#2B5473", ["PillBrush"] = "#4B5566", ["CtrlBorder"] = "#66728A",
                    ["CtrlFill"] = "#465061", ["TickGlyph"] = "#1B1F24", ["Thumb"] = "#66728A",
                },
                ["light"] = new Dictionary<string, string>
                {
                    ["Base"] = "#F1F1F4", ["Card"] = "#FFFFFF", ["Field"] = "#FFFFFF",
                    ["Bar"] = "#E4E4EA", ["Line"] = "#D2D2DA", ["Edge"] = "#B4B4BE",
                    ["Ink"] = "#1F1F23", ["Muted"] = "#5C5C66",
                    ["Blue"] = "#1B72BE", ["BlueHover"] = "#155C99",
                    ["Orange"] = "#B96A12", ["Green"] = "#2E8546", ["GreenHover"] = "#37A056",
                    ["OnGreen"] = "#FFFFFF", ["Red"] = "#C1443F", ["Sel"] = "#CBE0F2",
                    ["RowEvenBrush"] = "#FFFFFF", ["RowOddBrush"] = "#F5F5F8",
                    ["RowHover"] = "#CBE0F2", ["PillBrush"] = "#E4E4EA", ["CtrlBorder"] = "#9A9AA4",
                    ["CtrlFill"] = "#EDEDF1", ["TickGlyph"] = "#FFFFFF", ["Thumb"] = "#B0B0BA",
                },
            };

        public const string ThemeAuto = "auto";
        public static readonly string[] ThemeOrder = { ThemeAuto, "dark", "light" };

        // --- Helpers ----------------------------------------------------------
        /// <summary>Python-style float(): invariant, surrounding spaces allowed.</summary>
        public static bool TryNumber(string text, out double value)
        {
            return double.TryParse((text ?? "").Trim(), NumberStyles.Float, Inv, out value)
                   && !double.IsNaN(value) && !double.IsInfinity(value);
        }

        /// <summary>'a=1;b=2' to {a: 1, b: 2}. A damaged entry falls back.</summary>
        public static Dictionary<string, double> ParseKvList(string text, Dictionary<string, double> fallback)
        {
            var values = new Dictionary<string, double>(fallback);
            foreach (string raw in (text ?? "").Split(';'))
            {
                string chunk = raw.Trim();
                int eq = chunk.IndexOf('=');
                if (chunk.Length == 0 || eq < 0) continue;
                if (!TryNumber(chunk.Substring(eq + 1), out double number)) continue;
                if (number > 0) values[chunk.Substring(0, eq).Trim()] = number;
            }
            return values;
        }

        public static string FormatKvList(Dictionary<string, double> values)
        {
            return string.Join(";", values.Keys.OrderBy(k => k, StringComparer.Ordinal)
                                         .Select(k => k + "=" + FormatMm(values[k])));
        }

        public const double MmPerFoot = 304.8;

        /// <summary>Millimetres to Revit internal units (decimal feet).</summary>
        public static double ToInternal(double millimetres) => millimetres / MmPerFoot;

        private static readonly Regex Word = new Regex("[A-Za-z][A-Za-z']*");

        /// <summary>Capitalise each word. Tokens holding digits (FD30, 900x2100) are left alone.</summary>
        public static string ToCamelCase(string text)
        {
            var words = new List<string>();
            foreach (string token in text.Split(' '))
            {
                if (token.Length == 0 || token.Any(char.IsDigit))
                {
                    words.Add(token);
                    continue;
                }
                words.Add(Word.Replace(token, m =>
                    m.Value.Substring(0, 1).ToUpperInvariant() + m.Value.Substring(1).ToLowerInvariant()));
            }
            return string.Join(" ", words);
        }

        public static string ApplyCase(string text, string mode)
        {
            if (string.IsNullOrEmpty(text)) return text;
            if (mode == CaseUpper) return text.ToUpperInvariant();
            if (mode == CaseCamel) return ToCamelCase(text);
            return text;
        }

        /// <summary>Trim a number to what a millimetre box should show.</summary>
        public static string FormatMm(double value)
        {
            double rounded = Math.Round(value, 1, MidpointRounding.AwayFromZero);
            double whole = Math.Truncate(rounded);
            if (Math.Abs(rounded - whole) < 0.05)
                return ((long)whole).ToString(Inv);
            return rounded.ToString("0.0", Inv);
        }

        /// <summary>A distance quoted at a reference scale, restated for another scale.</summary>
        public static double ScaledMm(double baseMm, double scale, double reference = ReferenceScale)
        {
            return reference == 0 ? baseMm : baseMm * (scale / reference);
        }

        /// <summary>The inverse - a distance typed at some scale, back to the reference.</summary>
        public static double UnscaledMm(double valueMm, double scale, double reference = ReferenceScale)
        {
            return scale == 0 ? valueMm : valueMm * (reference / scale);
        }

        public static int Channel(int value) => Math.Max(0, Math.Min(255, value));

        /// <summary>(r, g, b) to '#RRGGBB'; null gives the neutral grey.</summary>
        public static string RgbHex((int R, int G, int B)? rgb)
        {
            if (rgb == null) return "#9A9A9E";
            var c = rgb.Value;
            return string.Format(Inv, "#{0:X2}{1:X2}{2:X2}", Channel(c.R), Channel(c.G), Channel(c.B));
        }

        /// <summary>The colour as Python printed its tuple, for the log.</summary>
        public static string RgbText((int R, int G, int B)? rgb)
        {
            return rgb == null ? "None" : string.Format(Inv, "({0}, {1}, {2})", rgb.Value.R, rgb.Value.G, rgb.Value.B);
        }

        /// <summary>WIP_Doors, then WIP_Doors_2, WIP_Doors_3 ...</summary>
        public static string UniqueViewName(string baseName, HashSet<string> taken)
        {
            if (!taken.Contains(baseName))
            {
                taken.Add(baseName);
                return baseName;
            }
            for (int index = 2; ; index++)
            {
                string candidate = baseName + "_" + index.ToString(Inv);
                if (!taken.Contains(candidate))
                {
                    taken.Add(candidate);
                    return candidate;
                }
            }
        }

        /// <summary>Turn a filter or rule string into the label that goes on the legend.</summary>
        public static string TidyLabel(string text, string token)
        {
            string label = Regex.Replace(text ?? "", "[_]+", " ").Trim();
            if (!string.IsNullOrEmpty(token))
                label = Regex.Replace(label, @"(?i)\b" + Regex.Escape(token) + @"\b", " ");
            label = Regex.Replace(label, @"^[\s\-:>|]+", "");
            label = Regex.Replace(label, @"[\s\-:>|]+$", "");
            return Regex.Replace(label, @"\s{2,}", " ").Trim();
        }

        /// <summary>Revit packs a colour into an integer as R + G*256 + B*65536.</summary>
        public static (int R, int G, int B)? DecodeColourInt(int number)
        {
            if (number < 0) return null;
            return (number % 256, (number / 256) % 256, (number / 65536) % 256);
        }

        public static int GroupOrder(string name)
        {
            for (int i = 0; i < PipeGroups.Length; i++)
                if (PipeGroups[i].Group == name) return i;
            return PipeGroups.Length; // Other last
        }

        /// <summary>[(header, entries)] in the order the legend should read.</summary>
        public static List<(string Header, List<LegendEntry> Entries)> GroupedEntries(
            List<LegendEntry> entries, LegendKind kind)
        {
            if (!kind.Grouped)
                return new List<(string, List<LegendEntry>)> { (kind.Heading, entries) };

            var order = new List<string>();
            var buckets = new Dictionary<string, List<LegendEntry>>();
            foreach (var entry in entries)
            {
                string group = string.IsNullOrEmpty(entry.Group) ? PipeGroupOther : entry.Group;
                if (!buckets.ContainsKey(group))
                {
                    buckets[group] = new List<LegendEntry>();
                    order.Add(group);
                }
                buckets[group].Add(entry);
            }
            string suffix = kind.GroupSuffix ?? kind.Heading;
            return order.OrderBy(GroupOrder) // stable, like Python's sort
                        .Select(g => ((g + " " + suffix).ToUpperInvariant(), buckets[g]))
                        .ToList();
        }

        /// <summary>Which template to preselect, and why: (index or -1, reason).</summary>
        public static (int Index, string Reason) ChooseTemplate(
            IList<string> names, IList<int> counts, string saved, string fallback, bool usesFilters)
        {
            if (!string.IsNullOrEmpty(saved) && names.Contains(saved))
                return (names.IndexOf(saved), "used last time");
            if (!string.IsNullOrEmpty(fallback) && names.Contains(fallback))
                return (names.IndexOf(fallback), "the default for this kind");
            if (usesFilters && counts != null && counts.Count > 0 && counts.Max() > 0)
            {
                int best = counts.Max();
                return (counts.IndexOf(best), string.Format(Inv, "holds the most matching filters ({0})", best));
            }
            if (names.Count > 0) return (0, "nothing in this model matches - first in list");
            return (-1, "this model has no view templates");
        }

        /// <summary>A phase id value worth filtering on, or null. Real ids are positive.</summary>
        public static long? UsablePhase(long? value)
        {
            if (value == null || value.Value <= 0) return null;
            return value;
        }

        /// <summary>'keep', 'no phase' or 'other phase' for one element.</summary>
        public static string PhaseVerdict(long? wantPhase, long? onPhase)
        {
            if (wantPhase == null) return "keep";
            if (onPhase == null) return "no phase";
            return onPhase.Value == wantPhase.Value ? "keep" : "other phase";
        }

        /// <summary>Revit takes 1 to 16. Anything else is coerced rather than refused.</summary>
        public static int ClampWeight(string value)
        {
            if (!TryNumber(value, out double number)) return DefaultLineWeight;
            return ClampWeight(number);
        }

        public static int ClampWeight(double value)
        {
            int weight = (int)Math.Round(value, MidpointRounding.AwayFromZero);
            return Math.Max(MinLineWeight, Math.Min(MaxLineWeight, weight));
        }

        private static readonly Regex InvalidNameChars = new Regex(@"[\\:{}\[\]|;<>?`~]");

        /// <summary>Revit refuses these characters in an element name.</summary>
        public static string SafeStyleName(string name)
        {
            string cleaned = InvalidNameChars.Replace(name ?? "", "-").Trim();
            return cleaned.Length > 0 ? cleaned : "Unnamed";
        }

        /// <summary>The legend group for a pipe system's classification text.</summary>
        public static string ClassifyPipe(string text)
        {
            text = (text ?? "").ToLowerInvariant();
            foreach (var (group, keywords) in PipeGroups)
                if (keywords.Any(k => text.Contains(k))) return group;
            return PipeGroupOther;
        }

        /// <summary>Abbreviation - Description, either half alone, or the fallback.</summary>
        public static string JoinLabel(string abbreviation, string description, string fallback)
        {
            var parts = new[] { abbreviation ?? "", description ?? "" }
                .Where(p => p.Trim().Length > 0).Select(p => p.Trim()).ToList();
            return parts.Count > 0 ? string.Join(" - ", parts) : fallback;
        }

        /// <summary>A pinned mode as it is, otherwise Revit's own, otherwise dark.</summary>
        public static string PickTheme(string mode, string revitValue)
        {
            if (mode == "dark" || mode == "light") return mode;
            return string.IsNullOrEmpty(revitValue) ? "dark" : revitValue;
        }

        /// <summary>'dark', 'light' or null from however a UITheme value prints.</summary>
        public static string ReadThemeText(object value)
        {
            string text = (value?.ToString() ?? "").ToLowerInvariant();
            if (text.Contains("dark")) return "dark";
            if (text.Contains("light")) return "light";
            return null;
        }

        /// <summary>The chip's cycle: Auto -> Dark -> Light -> Auto.</summary>
        public static string NextThemeMode(string mode)
        {
            int position = Array.IndexOf(ThemeOrder, mode);
            if (position < 0) position = 0;
            return ThemeOrder[(position + 1) % ThemeOrder.Length];
        }

        /// <summary>Python's str.capitalize().</summary>
        public static string Capitalize(string text)
        {
            if (string.IsNullOrEmpty(text)) return text;
            return text.Substring(0, 1).ToUpperInvariant() + text.Substring(1).ToLowerInvariant();
        }

        /// <summary>A number as Python printed a float in a rule value: 2.0, 2.5.</summary>
        public static string PyFloat(double value)
        {
            string text = value.ToString("R", Inv);
            if (text.IndexOfAny(new[] { '.', 'E', 'e' }) < 0 && !double.IsInfinity(value) && !double.IsNaN(value))
                text += ".0";
            return text;
        }
    }
}
