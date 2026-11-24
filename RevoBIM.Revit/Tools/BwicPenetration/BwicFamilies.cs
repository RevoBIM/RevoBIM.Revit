using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using RevoBIM.Tools.ExcelForRevit;

namespace RevoBIM.Tools.BwicPenetration
{
    /// <summary>One sizing role of a family: which parameter plays it.</summary>
    public sealed class BwicRole
    {
        public string Key, Label, Help, Setting, Kind;
        public string[] Shapes;
        public bool Required;

        public BwicRole(string key, string label, string help, string setting, string kind, string[] shapes, bool required)
        {
            Key = key; Label = label; Help = help; Setting = setting; Kind = kind; Shapes = shapes; Required = required;
        }
    }

    public sealed class BwicSlotInfo
    {
        public string Slot, Label, FamilyKey, TypeKey;

        public BwicSlotInfo(string slot, string label, string familyKey, string typeKey)
        {
            Slot = slot; Label = label; FamilyKey = familyKey; TypeKey = typeKey;
        }
    }

    public sealed class BwicSplitAxis
    {
        public string Axis, Label, Role;

        public BwicSplitAxis(string axis, string label, string role)
        {
            Axis = axis; Label = label; Role = role;
        }
    }

    /// <summary>
    /// Family profiles (port of bwic_families.py): which parameter of a family plays which sizing role. A profile is a nested
    /// dictionary (string / bool / dictionary) kept in one JSON file beside the settings; <see cref="Overlay"/> writes the chosen
    /// family's profile onto the settings keys the core reads. Settings are a plain string dictionary.
    /// </summary>
    public static class BwicFamilies
    {
        public const string Rect = "rectangular";
        public const string Circ = "circular";
        public const string Standard = "standard";
        public const string Split = "split";
        public const string SplitPrefix = "@split:";
        public const string FollowSettings = "";
        public const string ActiveWorkset = "<active>";
        public const string FollowLabel = "As Settings";
        public const string ActiveLabel = "<active workset>";
        public const double DefaultClearanceMm = 50.0;

        public static readonly BwicSlotInfo[] Slots =
        {
            new BwicSlotInfo("wall", "Wall penetration, rectangular", "wall_family", "wall_type"),
            new BwicSlotInfo("wall_circ", "Wall penetration, circular", "wall_circ_family", "wall_circ_type"),
            new BwicSlotInfo("slab_rect", "Slab penetration, rectangular", "slab_family", "slab_type"),
            new BwicSlotInfo("slab_circ", "Slab penetration, circular", "slab_circ_family", "slab_circ_type"),
        };

        public static readonly Dictionary<string, string[]> SlotShapes = new Dictionary<string, string[]>
        {
            { "wall", new[] { Rect } }, { "wall_circ", new[] { Circ } },
            { "slab_rect", new[] { Rect } }, { "slab_circ", new[] { Circ } },
        };

        public static readonly Dictionary<string, string> ShapeKey = new Dictionary<string, string>();

        public static readonly Dictionary<string, string> RadiusKey = new Dictionary<string, string>
        {
            { "wall_circ", "wall_circ_radius" }, { "slab_circ", "slab_circular_radius" },
        };

        private static readonly string[] Both = { Rect, Circ };
        private static readonly string[] RectOnly = { Rect };
        private static readonly string[] CircOnly = { Circ };

        private static List<BwicRole> SlabPosition()
        {
            return new List<BwicRole>
            {
                new BwicRole("vertical", "Vertical height", "Written with the floor thickness. Single-level families.", "slab_height_param", "length", Both, false),
                new BwicRole("top_height", "Top height", "Height of the top of the opening. Single-level families.", "slab_top_height_param", "length", Both, false),
                new BwicRole("level_offset", "Offset from level", "Base of the opening above its level. Single-level families.", "slab_level_offset_param", "length", Both, false),
                new BwicRole("base_level", "Base level", "Blank uses Revit's own Base Level. Two-level families.", "slab_base_level_param", "any", Both, false),
                new BwicRole("top_level", "Top level", "Blank uses Revit's own Top Level. Two-level families.", "slab_top_level_param", "any", Both, false),
                new BwicRole("base_offset", "Base offset", "Blank uses Revit's own Base Offset. Two-level families.", "slab_base_offset_param", "length", Both, false),
                new BwicRole("top_offset", "Top offset", "Blank uses Revit's own Top Offset. Two-level families.", "slab_top_offset_param", "length", Both, false),
                new BwicRole("level_code", "Level code", "Text parameter the level code (00, 01, RF) is written to.", "slab_level_code_param", "any", Both, false),
            };
        }

        public static readonly Dictionary<string, List<BwicRole>> Roles = BuildRoles();

        private static Dictionary<string, List<BwicRole>> BuildRoles()
        {
            var slabRect = new List<BwicRole>
            {
                new BwicRole("plan_x", "Plan width", "One plan dimension of the opening, plus clearance.", "slab_width_param", "length", RectOnly, true),
                new BwicRole("plan_y", "Plan depth", "The other plan dimension, plus clearance.", "slab_length_param", "length", RectOnly, true),
            };
            slabRect.AddRange(SlabPosition());
            var slabCirc = new List<BwicRole>
            {
                new BwicRole("diameter", "Diameter or radius", "Outside diameter of the service plus the gap each side.", "slab_circular_param", "length", CircOnly, true),
            };
            slabCirc.AddRange(SlabPosition());
            return new Dictionary<string, List<BwicRole>>
            {
                { "wall", new List<BwicRole>
                    {
                        new BwicRole("through", "Through the wall", "Written with the wall thickness.", "wall_length_param", "length", Both, false),
                        new BwicRole("across", "Width along the wall", "Extent of the services along the wall, plus clearance.", "wall_width_param", "length", RectOnly, true),
                        new BwicRole("height", "Height", "Extent of the services top to bottom, plus clearance.", "wall_height_param", "length", RectOnly, true),
                    } },
                { "wall_circ", new List<BwicRole>
                    {
                        new BwicRole("through", "Through the wall", "Written with the wall thickness.", "wall_circ_length_param", "length", CircOnly, false),
                        new BwicRole("diameter", "Diameter or radius", "Outside diameter of the pipe plus the gap each side, or the circle around a group.", "wall_circ_diameter_param", "length", CircOnly, true),
                    } },
                { "slab_rect", slabRect },
                { "slab_circ", slabCirc },
            };
        }

        public static readonly Dictionary<string, BwicSplitAxis[]> SplitAxes = new Dictionary<string, BwicSplitAxis[]>
        {
            { "wall", new[] { new BwicSplitAxis("x", "X = Width", "across"), new BwicSplitAxis("y", "Y = Length", "through"), new BwicSplitAxis("z", "Z = Height", "height") } },
            { "slab_rect", new[] { new BwicSplitAxis("x", "X = Width", "plan_x"), new BwicSplitAxis("y", "Y = Length", "plan_y"), new BwicSplitAxis("z", "Z = Height", "vertical") } },
            { "wall_circ", new[] { new BwicSplitAxis("y", "Y = Length", "through") } },
            { "slab_circ", new[] { new BwicSplitAxis("y", "Y = Length", "vertical") } },
        };

        public static readonly Dictionary<string, string> SplitLabel = new Dictionary<string, string>
        {
            { "wall", "X+ / X-" }, { "slab_rect", "X+ / X-" }, { "wall_circ", "Y+ / Y-" }, { "slab_circ", "Y+ / Y-" },
        };

        private static readonly Dictionary<string, string[]> Hints = new Dictionary<string, string[]>
        {
            { "through", new[] { "length", "thickness", "depth", "through" } },
            { "across", new[] { "width" } },
            { "height", new[] { "height" } },
            { "diameter", new[] { "diameter", "dia", "radius" } },
            { "plan_x", new[] { "width" } },
            { "plan_y", new[] { "depth", "length", "height" } },
        };

        // ---------------------------------------------------------------- dictionary helpers

        public static string Get(Dictionary<string, string> settings, string key)
        {
            string value;
            return settings != null && settings.TryGetValue(key, out value) && value != null ? value : "";
        }

        public static Dictionary<string, object> Sub(IDictionary<string, object> dict, string key)
        {
            object value;
            if (dict != null && dict.TryGetValue(key, out value)) return value as Dictionary<string, object>;
            return null;
        }

        public static string Str(IDictionary<string, object> dict, string key)
        {
            object value;
            if (dict != null && dict.TryGetValue(key, out value) && value != null)
            {
                if (value is bool) return (bool)value ? "True" : "False";
                return Convert.ToString(value, CultureInfo.InvariantCulture);
            }
            return "";
        }

        public static bool Bool(IDictionary<string, object> dict, string key)
        {
            object value;
            if (dict != null && dict.TryGetValue(key, out value) && value is bool) return (bool)value;
            return false;
        }

        public static HashSet<string> AxisRoles(string slot)
        {
            BwicSplitAxis[] axes;
            return SplitAxes.TryGetValue(slot, out axes) ? new HashSet<string>(axes.Select(a => a.Role)) : new HashSet<string>();
        }

        // ---------------------------------------------------------------- split pairs

        public static string EncodeSplit(string minus, string plus)
        {
            return SplitPrefix + minus + "|" + plus;
        }

        /// <summary>(minus, plus) for a split pair, or null for an ordinary parameter.</summary>
        public static string[] DecodeSplit(string name)
        {
            if (string.IsNullOrEmpty(name) || !name.StartsWith(SplitPrefix, StringComparison.Ordinal)) return null;
            string rest = name.Substring(SplitPrefix.Length);
            int bar = rest.IndexOf('|');
            string minus = bar < 0 ? rest : rest.Substring(0, bar);
            string plus = bar < 0 ? "" : rest.Substring(bar + 1);
            if (minus.Length == 0 || plus.Length == 0) return null;
            return new[] { minus, plus };
        }

        /// <summary>(parameter, share of the size) to write a size to: an ordinary parameter takes it all, a pair half each.</summary>
        public static List<KeyValuePair<string, double>> SplitParts(string name)
        {
            string[] pair = DecodeSplit(name);
            if (pair == null) return new List<KeyValuePair<string, double>> { new KeyValuePair<string, double>(name, 1.0) };
            return new List<KeyValuePair<string, double>>
            {
                new KeyValuePair<string, double>(pair[0], 0.5), new KeyValuePair<string, double>(pair[1], 0.5),
            };
        }

        public static string ShowName(string name)
        {
            string[] pair = DecodeSplit(name);
            return pair != null ? pair[0] + " + " + pair[1] : name;
        }

        public static string SlotFamilyKey(string slot) { return Slots.First(s => s.Slot == slot).FamilyKey; }
        public static string SlotTypeKey(string slot) { return Slots.First(s => s.Slot == slot).TypeKey; }

        public static List<BwicRole> RolesFor(string slot, string shape)
        {
            return Roles[slot].Where(r => r.Shapes.Contains(shape)).ToList();
        }

        public static string DefaultShape(string slot) { return SlotShapes[slot][0]; }

        // ---------------------------------------------------------------- which list a family belongs in

        private static readonly string[] RoundParamWords = { "diameter", "radius" };
        private static readonly string[] RoundNameWords = { "circular", "round" };

        public static string FamilyShape(IEnumerable<string> lengthNames, string familyName, bool placed)
        {
            if (lengthNames != null)
                foreach (string name in lengthNames)
                {
                    string low = (name ?? "").ToLowerInvariant();
                    if (RoundParamWords.Any(w => low.Contains(w))) return Circ;
                }
            if (!placed)
            {
                string low = (familyName ?? "").ToLowerInvariant();
                if (RoundNameWords.Any(w => low.Contains(w))) return Circ;
            }
            return Rect;
        }

        /// <summary>Where a straight run is inside a wall, as fractions along the run; null when parallel to the wall.</summary>
        public static double[] WallSpan(double dStart, double dEnd, double halfThickness)
        {
            double travel = dEnd - dStart;
            if (Math.Abs(travel) < 1e-9) return null;
            double a = (-halfThickness - dStart) / travel;
            double b = (halfThickness - dStart) / travel;
            double tIn = Math.Min(a, b), tOut = Math.Max(a, b);
            tIn = Math.Min(Math.Max(tIn, 0.0), 1.0);
            tOut = Math.Min(Math.Max(tOut, 0.0), 1.0);
            return new[] { tIn, tOut };
        }

        private static string Guess(string role, IList<string> names, List<string> taken)
        {
            string[] hints;
            if (!Hints.TryGetValue(role, out hints)) return "";
            foreach (string hint in hints)
                foreach (string name in names)
                {
                    if (taken.Contains(name)) continue;
                    if (name.ToLowerInvariant().Contains(hint)) return name;
                }
            return "";
        }

        /// <summary>{axis: {minus, plus}} found by name, e.g. WLG_X_Minus.</summary>
        public static Dictionary<string, Dictionary<string, object>> GuessSplit(string slot, IEnumerable<string> names)
        {
            var found = new Dictionary<string, Dictionary<string, object>>();
            BwicSplitAxis[] axes;
            if (!SplitAxes.TryGetValue(slot, out axes)) return found;
            var list = names.ToList();
            foreach (BwicSplitAxis ax in axes)
            {
                var letter = new Regex("(^|[^a-z0-9])" + ax.Axis + "($|[^a-z0-9])");
                string minusName = "", plusName = "";
                foreach (string name in list)
                {
                    string low = name.ToLowerInvariant();
                    if (!letter.IsMatch(low)) continue;
                    if (Regex.IsMatch(low, @"minus|neg(ative)?\b|(^|[_\s])m($|[_\s])") && minusName.Length == 0) minusName = name;
                    else if (Regex.IsMatch(low, @"plus|pos(itive)?\b|(^|[_\s])p($|[_\s])") && plusName.Length == 0) plusName = name;
                }
                found[ax.Axis] = new Dictionary<string, object> { { "minus", minusName }, { "plus", plusName } };
            }
            return found;
        }

        /// <summary>A first profile for a family: today's settings where they fit, else a guess from the parameter names.</summary>
        public static Dictionary<string, object> SeedProfile(string slot, Dictionary<string, string> settings, IList<string> lengthNames, IList<string> allNames = null)
        {
            var all = (allNames ?? lengthNames).ToList();
            string shapeKey;
            string shape = ShapeKey.TryGetValue(slot, out shapeKey) ? Get(settings, shapeKey) : "";
            if (shape.Length == 0) shape = DefaultShape(slot);
            if (!SlotShapes[slot].Contains(shape)) shape = DefaultShape(slot);
            string radiusKey;
            bool radius = RadiusKey.TryGetValue(slot, out radiusKey) && Get(settings, radiusKey) == "yes";
            var roles = new Dictionary<string, object>();
            var profile = new Dictionary<string, object> { { "shape", shape }, { "radius", radius }, { "roles", roles } };
            var taken = new List<string>();
            foreach (string shapeOption in SlotShapes[slot])
                foreach (BwicRole role in RolesFor(slot, shapeOption))
                {
                    if (roles.ContainsKey(role.Key)) continue;
                    IList<string> names = role.Kind == "length" ? lengthNames : all;
                    string current = Get(settings, role.Setting);
                    string value;
                    if (current.Length > 0 && (names == null || names.Count == 0 || names.Contains(current))) value = current;
                    else value = Guess(role.Key, names ?? new List<string>(), taken);
                    roles[role.Key] = value;
                    if (value.Length > 0) taken.Add(value);
                }
            profile["drive"] = Standard;
            if (SplitAxes.ContainsKey(slot))
            {
                var guessed = GuessSplit(slot, lengthNames ?? new List<string>());
                var splitObj = new Dictionary<string, object>();
                foreach (var kv in guessed) splitObj[kv.Key] = kv.Value;
                profile["split"] = splitObj;
                var needed = RolesFor(slot, shape).Where(r => r.Required).Select(r => r.Key).ToList();
                var deciding = SplitAxes[slot].Where(a => needed.Contains(a.Role)).ToList();
                if (deciding.Count == 0) deciding = SplitAxes[slot].ToList();
                bool pairsComplete = deciding.All(a => Str(guessed[a.Axis], "minus").Length > 0 && Str(guessed[a.Axis], "plus").Length > 0);
                bool standardMissing = deciding.Any(a => Str(roles, a.Role).Length == 0);
                if (pairsComplete && standardMissing)
                {
                    profile["drive"] = Split;
                    foreach (BwicSplitAxis a in deciding) roles[a.Role] = "";
                }
            }
            string dia = Str(roles, "diameter");
            string rk;
            if (dia.Length > 0 && dia.ToLowerInvariant().Contains("radius")
                && (!RadiusKey.TryGetValue(slot, out rk) || Get(settings, rk).Length == 0))
                profile["radius"] = true;
            return profile;
        }

        /// <summary>What would stop this profile sizing the family. Empty means fine.</summary>
        public static List<string> Problems(string slot, Dictionary<string, object> profile, IList<string> lengthNames = null)
        {
            bool split = Str(profile, "drive") == Split && SplitAxes.ContainsKey(slot);
            List<string> found = split ? SplitProblems(slot, profile, lengthNames) : new List<string>();
            object clearance;
            bool hasClearance = profile.TryGetValue("clearance_mm", out clearance) && clearance != null;
            string bad = hasClearance ? ClearanceProblem(Convert.ToString(clearance, CultureInfo.InvariantCulture) ?? "", true) : null;
            if (bad != null) found.Add(bad);
            HashSet<string> skip = split ? AxisRoles(slot) : new HashSet<string>();
            string shape = Str(profile, "shape");
            if (shape.Length == 0) shape = DefaultShape(slot);
            var roles = Sub(profile, "roles") ?? new Dictionary<string, object>();
            var used = new Dictionary<string, string>();
            foreach (BwicRole r in RolesFor(slot, shape))
            {
                if (skip.Contains(r.Key)) continue;
                string value = Str(roles, r.Key);
                if (r.Required && value.Length == 0)
                {
                    found.Add(r.Label + " has no parameter");
                    continue;
                }
                if (value.Length == 0) continue;
                if (lengthNames != null && lengthNames.Count > 0 && r.Kind == "length" && !lengthNames.Contains(value))
                    found.Add(r.Label + " uses \"" + value + "\", which this family does not have");
                if (r.Kind == "length" && (r.Key == "through" || r.Key == "across" || r.Key == "height" || r.Key == "diameter"
                                           || r.Key == "plan_x" || r.Key == "plan_y"))
                {
                    if (used.ContainsKey(value)) found.Add(used[value] + " and " + r.Label + " both use \"" + value + "\"");
                    else used[value] = r.Label;
                }
            }
            return found;
        }

        public static List<string> SplitProblems(string slot, Dictionary<string, object> profile, IList<string> lengthNames = null)
        {
            var found = new List<string>();
            var split = Sub(profile, "split") ?? new Dictionary<string, object>();
            bool any = SplitAxes[slot].Any(a =>
            {
                var pair = Sub(split, a.Axis);
                return Str(pair, "minus").Length > 0 && Str(pair, "plus").Length > 0;
            });
            if (!any) found.Add("No Minus / Plus pair is set - choose one, or use Standard");
            var needed = RolesFor(slot, DefaultShape(slot)).Where(r => r.Required).Select(r => r.Key).ToList();
            var used = new Dictionary<string, string>();
            foreach (BwicSplitAxis a in SplitAxes[slot])
            {
                var pair = Sub(split, a.Axis);
                string minus = Str(pair, "minus"), plus = Str(pair, "plus");
                if (minus.Length == 0 && plus.Length == 0)
                {
                    if (needed.Contains(a.Role)) found.Add(a.Label + " has no Minus / Plus pair");
                    continue;
                }
                if (minus.Length == 0 || plus.Length == 0)
                {
                    found.Add(a.Label + " needs both a Minus and a Plus parameter");
                    continue;
                }
                var sides = new List<KeyValuePair<string, string>>
                {
                    new KeyValuePair<string, string>("Minus", minus), new KeyValuePair<string, string>("Plus", plus),
                };
                if (minus == plus)
                {
                    found.Add(a.Label + " uses \"" + minus + "\" for both sides");
                    sides = new List<KeyValuePair<string, string>> { new KeyValuePair<string, string>("Minus", minus) };
                }
                foreach (var side in sides)
                {
                    if (lengthNames != null && lengthNames.Count > 0 && !lengthNames.Contains(side.Value))
                        found.Add(a.Label + " " + side.Key + " uses \"" + side.Value + "\", which this family does not have");
                    if (used.ContainsKey(side.Value)) found.Add(used[side.Value] + " and " + a.Label + " both use \"" + side.Value + "\"");
                    else used[side.Value] = a.Label;
                }
            }
            return found;
        }

        /// <summary>Settings with the slot's chosen family profile written over them (a new dictionary).</summary>
        public static Dictionary<string, string> Overlay(Dictionary<string, string> settings, string slot, Dictionary<string, object> profiles)
        {
            var output = new Dictionary<string, string>(settings);
            string family = Get(settings, SlotFamilyKey(slot));
            Dictionary<string, object> profile = family.Length == 0 ? null : Sub(profiles, family);
            if (family.Length == 0 || profile == null || profile.Count == 0) return output;
            string shape = Str(profile, "shape");
            if (shape.Length == 0) shape = DefaultShape(slot);
            var roles = Sub(profile, "roles") ?? new Dictionary<string, object>();
            foreach (BwicRole r in Roles[slot])
                if (r.Shapes.Contains(shape) && roles.ContainsKey(r.Key)) output[r.Setting] = Str(roles, r.Key);
            if (Str(profile, "drive") == Split && SplitAxes.ContainsKey(slot))
            {
                var split = Sub(profile, "split") ?? new Dictionary<string, object>();
                foreach (BwicSplitAxis a in SplitAxes[slot])
                {
                    var pair = Sub(split, a.Axis);
                    if (Str(pair, "minus").Length > 0 && Str(pair, "plus").Length > 0)
                        output[Roles[slot].First(r => r.Key == a.Role).Setting] = EncodeSplit(Str(pair, "minus"), Str(pair, "plus"));
                }
            }
            output["family_workset"] = ProfileWorkset(profile);
            double? own = ClearanceValue(profile.ContainsKey("clearance_mm") ? profile["clearance_mm"] : null);
            output["family_clearance"] = own == null ? "" : G(own.Value);
            string sk;
            if (ShapeKey.TryGetValue(slot, out sk)) output[sk] = shape;
            string rk;
            if (RadiusKey.TryGetValue(slot, out rk)) output[rk] = Bool(profile, "radius") ? "yes" : "no";
            return output;
        }

        /// <summary>Python's {:g}: shortest form, no trailing zeros.</summary>
        public static string G(double value)
        {
            return value.ToString("0.######", CultureInfo.InvariantCulture);
        }

        // ---------------------------------------------------------------- clearance

        public static double? ClearanceValue(object text)
        {
            if (text == null) return null;
            double value;
            string s = text is double ? ((double)text).ToString("R", CultureInfo.InvariantCulture) : Convert.ToString(text, CultureInfo.InvariantCulture);
            s = (s ?? "").Trim();
            if (!double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out value)) return null;
            if (value < 0 || double.IsNaN(value)) return null;
            return value;
        }

        public static double? FamilyClearance(string family, Dictionary<string, object> profiles)
        {
            var profile = Sub(profiles, family ?? "");
            if (profile == null || !profile.ContainsKey("clearance_mm")) return null;
            return ClearanceValue(profile["clearance_mm"]);
        }

        public static double ClearanceFor(string family, Dictionary<string, object> profiles, double defaultMm = DefaultClearanceMm)
        {
            double? own = FamilyClearance(family, profiles);
            return own ?? defaultMm;
        }

        /// <summary>A message for a bad clearance text; null when fine. present = the key exists in the profile.</summary>
        public static string ClearanceProblem(string text, bool present = true)
        {
            if (!present) return null;
            if (text == null) return null;
            if (text.Trim().Length == 0) return "Clearance is needed - a number of mm each side";
            if (ClearanceValue(text) == null) return "Clearance must be a number of mm, 0 or more";
            return null;
        }

        public static bool IsSet(string family, Dictionary<string, object> profiles)
        {
            if (string.IsNullOrEmpty(family)) return false;
            var profile = Sub(profiles, family);
            return profile != null && profile.Count > 0;
        }

        public static List<string> SetFirst(IEnumerable<string> names, Dictionary<string, object> profiles)
        {
            var list = names.ToList();
            var ready = list.Where(n => IsSet(n, profiles)).OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
            ready.AddRange(list.Where(n => !IsSet(n, profiles)));
            return ready;
        }

        // ---------------------------------------------------------------- workset

        public static Dictionary<string, string> ProfileWorksets(Dictionary<string, object> profile)
        {
            string old = Str(profile, "workset");
            if (old.Length == 0) old = FollowSettings;
            var saved = Sub(profile, "worksets") ?? new Dictionary<string, object>();
            var result = new Dictionary<string, string>();
            foreach (string drive in new[] { Standard, Split })
            {
                string value = saved.ContainsKey(drive) ? Str(saved, drive) : old;
                result[drive] = string.IsNullOrEmpty(value) ? FollowSettings : value;
            }
            return result;
        }

        public static string ProfileWorkset(Dictionary<string, object> profile)
        {
            string drive = Str(profile, "drive") == Split ? Split : Standard;
            return ProfileWorksets(profile)[drive];
        }

        public static string FamilyWorkset(string family, Dictionary<string, object> profiles)
        {
            return ProfileWorkset(Sub(profiles, family ?? ""));
        }

        /// <summary>The workset to place on, by name, or null for the active workset.</summary>
        public static string WorksetChoice(string familyChoice, string settingsName)
        {
            if (familyChoice == ActiveWorkset) return null;
            if (!string.IsNullOrEmpty(familyChoice)) return familyChoice;
            return string.IsNullOrEmpty(settingsName) ? null : settingsName;
        }

        public static string WorksetLabel(string choice)
        {
            if (choice == ActiveWorkset) return ActiveLabel;
            return string.IsNullOrEmpty(choice) ? FollowLabel : choice;
        }

        // ---------------------------------------------------------------- summary

        public static string Summary(string slot, Dictionary<string, object> profile)
        {
            if (profile == null || profile.Count == 0) return "No family settings saved yet -- using the defaults.";
            string line = SizeSummary(slot, profile);
            double? clearance = ClearanceValue(profile.ContainsKey("clearance_mm") ? profile["clearance_mm"] : null);
            if (clearance != null) line = line + " · Clearance " + G(clearance.Value) + " mm";
            string workset = ProfileWorkset(profile);
            if (workset.Length > 0) line = line + " · Workset: " + WorksetLabel(workset);
            return line;
        }

        public static string SizeSummary(string slot, Dictionary<string, object> profile)
        {
            bool splitMode = Str(profile, "drive") == Split && SplitAxes.ContainsKey(slot);
            var pairs = new List<string>();
            if (splitMode)
            {
                var split = Sub(profile, "split") ?? new Dictionary<string, object>();
                foreach (BwicSplitAxis a in SplitAxes[slot])
                {
                    var pair = Sub(split, a.Axis);
                    if (Str(pair, "minus").Length > 0 && Str(pair, "plus").Length > 0)
                        pairs.Add(a.Axis.ToUpperInvariant() + " " + Str(pair, "minus") + " + " + Str(pair, "plus"));
                }
                if (SlotShapes[slot].Length == 1 && SlotShapes[slot][0] == Rect)
                    return SplitLabel[slot] + ": " + (pairs.Count > 0 ? string.Join(", ", pairs) : "no pairs set");
            }
            HashSet<string> skip = splitMode ? AxisRoles(slot) : new HashSet<string>();
            string shape = Str(profile, "shape");
            if (shape.Length == 0) shape = DefaultShape(slot);
            var roles = Sub(profile, "roles") ?? new Dictionary<string, object>();
            var parts = new List<string>();
            foreach (BwicRole r in RolesFor(slot, shape))
            {
                if (skip.Contains(r.Key)) continue;
                if (r.Required || r.Key == "through")
                {
                    string value = Str(roles, r.Key);
                    if (value.Length == 0) value = "-";
                    string label = r.Label;
                    if (r.Key == "diameter") label = Bool(profile, "radius") ? "Radius" : "Diameter";
                    parts.Add(label + " " + value);
                }
            }
            string lead = shape == Circ ? "Round" : "Rectangular";
            if (splitMode) lead = lead + ", " + SplitLabel[slot];
            parts.AddRange(pairs);
            return lead + ": " + string.Join(", ", parts);
        }

        // ---------------------------------------------------------------- resize

        public static string SlotForFamily(string family, string context, Dictionary<string, string> settings,
                                           Dictionary<string, object> profile = null, IList<string> lengthNames = null)
        {
            string[] slots = context == "wall" ? new[] { "wall", "wall_circ" } : new[] { "slab_rect", "slab_circ" };
            foreach (string slot in slots)
                if (!string.IsNullOrEmpty(family) && Get(settings, SlotFamilyKey(slot)) == family) return slot;
            string shape = Str(profile, "shape");
            if (shape != Rect && shape != Circ && lengthNames != null && lengthNames.Count > 0)
            {
                var low = lengthNames.Select(n => n.ToLowerInvariant()).ToList();
                bool roundSize = low.Any(n => n.Contains("diameter") || n.Contains("radius"));
                var guess = GuessSplit("wall", lengthNames);
                bool width = low.Any(n => n.Contains("width")) || Str(guess["x"], "minus").Length > 0;
                shape = roundSize && !width ? Circ : Rect;
            }
            return shape == Circ ? slots[1] : slots[0];
        }

        /// <summary>(slot, settings, saved?) for resizing a BWIC of this family.</summary>
        public static Tuple<string, Dictionary<string, string>, bool> SettingsForFamily(string family, string context,
            Dictionary<string, string> settings, Dictionary<string, object> profiles, IList<string> lengthNames = null)
        {
            var saved = Sub(profiles, family);
            if (saved != null && saved.Count == 0) saved = null;
            string slot = SlotForFamily(family, context, settings, saved, lengthNames);
            var values = new Dictionary<string, string>(settings);
            values[SlotFamilyKey(slot)] = family;
            var profile = saved ?? SeedProfile(slot, values, lengthNames ?? new List<string>());
            var wrapper = new Dictionary<string, object> { { family, profile } };
            return Tuple.Create(slot, Overlay(values, slot, wrapper), saved != null);
        }

        /// <summary>Diameter of a round hole through a wall, in mm.</summary>
        public static double RoundHoleMm(double outerMm, double spanAMm, double spanBMm, double gapMm, double stepMm)
        {
            double b = outerMm > 0 ? outerMm : Math.Sqrt(spanAMm * spanAMm + spanBMm * spanBMm);
            double raw = b + 2.0 * gapMm;
            double step = stepMm > 0 ? stepMm : 1.0;
            return Math.Ceiling(raw / step - 1e-9) * step;
        }

        public static double RoundValue(double diameter, bool radius) { return radius ? diameter / 2.0 : diameter; }

        // ---------------------------------------------------------------- file

        public static Dictionary<string, object> Load(string path)
        {
            try
            {
                if (!File.Exists(path)) return new Dictionary<string, object>();
                string text = File.ReadAllText(path, Encoding.UTF8);
                if (text.Trim().Length == 0) return new Dictionary<string, object>();
                var data = new EfrSettingsJson(text).ParseDocument() as Dictionary<string, object>;
                return data ?? new Dictionary<string, object>();
            }
            catch (Exception)
            {
                return new Dictionary<string, object>();
            }
        }

        /// <summary>Write every profile through a temporary file so a crash mid write cannot lose them all.</summary>
        public static void Save(string path, Dictionary<string, object> profiles)
        {
            string folder = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(folder)) Directory.CreateDirectory(folder);
            string temp = path + ".tmp";
            File.WriteAllText(temp, EfrSettingsJson.Dump(SortedCopy(profiles)), new UTF8Encoding(false));
            if (File.Exists(path)) File.Delete(path);
            File.Move(temp, path);
        }

        private static object SortedCopy(object value)
        {
            var dict = value as IDictionary;
            if (dict != null)
            {
                var result = new SortedDictionary<string, object>(StringComparer.Ordinal);
                foreach (DictionaryEntry e in dict) result[Convert.ToString(e.Key)] = SortedCopy(e.Value);
                return result;
            }
            return value;
        }

        public static Dictionary<string, object> DeepCopy(Dictionary<string, object> source)
        {
            var copy = new Dictionary<string, object>();
            foreach (var kv in source)
            {
                var d = kv.Value as Dictionary<string, object>;
                var l = kv.Value as List<object>;
                copy[kv.Key] = d != null ? (object)DeepCopy(d) : l != null ? new List<object>(l) : kv.Value;
            }
            return copy;
        }
    }
}
