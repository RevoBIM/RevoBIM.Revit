using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ModelCleanup
{
    /// <summary>
    /// NWC export - every rule, no Revit. The export runs first in Clean Up, on the model being cleaned,
    /// into the same folder the copy is saved in. One primary 3D view is named after the model; every
    /// other ticked view is a secondary named model_&lt;view&gt;. Port of mcu_nwc.py.
    /// </summary>
    public static class McuNwc
    {
        public const string SourceDefaults = "defaults";
        public const string SourceCustom = "custom";

        public static readonly List<(string Key, string Label)> Coordinates = new List<(string, string)>
            { ("shared", "Shared"), ("internal", "Project internal") };

        public static readonly List<(string Key, string Label)> Parameters = new List<(string, string)>
            { ("all", "All"), ("elements", "Elements"), ("none", "None") };

        public static string Choice(string value, List<(string Key, string Label)> options, string fallback)
        {
            value = (value ?? "").Trim().ToLowerInvariant();
            return options.Any(o => o.Key == value) ? value : fallback;
        }

        public static double Faceting(string value)
        {
            double number;
            if (!double.TryParse((value ?? "").Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out number)) return 1.0;
            return Math.Min(10.0, Math.Max(0.1, number));
        }

        /// <summary>What to set on NavisworksExportOptions, as plain values. With the exporter defaults, only the view scope is set.</summary>
        public static Dictionary<string, object> OptionsPlan(Dictionary<string, string> template)
        {
            var plan = new Dictionary<string, object> { { "ExportScope", "View" } };
            if (template.Get("nwc_source") == SourceDefaults) return plan;
            plan["Coordinates"] = Choice(template.Get("nwc_coordinates"), Coordinates, "shared") == "shared" ? "Shared" : "Internal";
            string parameters = Choice(template.Get("nwc_parameters"), Parameters, "all");
            plan["Parameters"] = parameters == "all" ? "All" : parameters == "elements" ? "Elements" : "None";
            plan["FacetingFactor"] = Faceting(template.Get("nwc_faceting"));
            foreach (var option in McuCore.NwcBoolOptions)
                plan[option.Prop] = McuCore.AsBool(template.Get(option.Key, option.Default), option.Default == "1");
            return plan;
        }

        // ============================================================
        // which views
        // ============================================================

        public static (List<string> Views, string Primary) Selection(Dictionary<string, string> template)
        {
            return Normalise(McuCore.SplitRetain(template.Get("nwc_views")), template.Get("nwc_primary"));
        }

        /// <summary>Ticked views, in natural order, and a primary that is one of them.</summary>
        public static (List<string> Views, string Primary) Normalise(IEnumerable<string> viewsIn, string primary)
        {
            var views = viewsIn.Where(v => !string.IsNullOrWhiteSpace(v)).ToList();
            if (!string.IsNullOrEmpty(primary) && !views.Contains(primary)) views.Add(primary);
            views = views.Distinct().ToList();
            views.Sort(McuCore.NaturalCompare);
            if (string.IsNullOrEmpty(primary) || !views.Contains(primary)) primary = views.Count > 0 ? views[0] : "";
            return (views, primary);
        }

        public static (List<string> Views, string Primary) Untick(IEnumerable<string> views, string primary, string name)
        {
            var kept = views.Where(v => v != name).ToList();
            if (primary == name) primary = "";
            return Normalise(kept, primary);
        }

        public static List<string> Rows(IEnumerable<string> names, string search, ICollection<string> views, bool onlySelected = false)
        {
            var words = (search ?? "").ToLowerInvariant().Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
            var output = new List<string>();
            var sorted = names.Distinct().ToList();
            sorted.Sort(McuCore.NaturalCompare);
            foreach (string name in sorted)
            {
                if (onlySelected && !views.Contains(name)) continue;
                if (words.Length > 0 && !words.All(w => name.ToLowerInvariant().Contains(w))) continue;
                output.Add(name);
            }
            return output;
        }

        public static string SafePart(string text)
        {
            text = Regex.Replace(text ?? "", "[\\\\/:*?\"<>|]", "-");
            text = Regex.Replace(text, "\\s+", " ").Trim().Trim('.');
            return text.Length > 0 ? text : "View";
        }

        /// <summary>[(view name, file name without .nwc)] - primary first, named after the model; clashes get a number.</summary>
        public static List<(string View, string File)> FileNames(string modelStem, IEnumerable<string> viewsIn, string primaryIn)
        {
            string stem = SafePart(McuCore.ModelStem(modelStem));
            if (stem.Length == 0) stem = "Model";
            var (views, primary) = Normalise(viewsIn, primaryIn);
            var output = new List<(string, string)>();
            var used = new HashSet<string>();
            var ordered = new List<string>();
            if (!string.IsNullOrEmpty(primary)) ordered.Add(primary);
            ordered.AddRange(views.Where(v => v != primary));
            foreach (string view in ordered)
            {
                string name = view == primary ? stem : stem + "_" + SafePart(view);
                string baseName = name;
                int count = 2;
                while (used.Contains(name.ToLowerInvariant()))
                {
                    name = baseName + " (" + count + ")";
                    count++;
                }
                used.Add(name.ToLowerInvariant());
                output.Add((view, name));
            }
            return output;
        }

        /// <summary>Split the planned exports into found (view id, view, file) and the names this model does not have.</summary>
        public static (List<(long Id, string View, string File)> Found, List<string> Missing) Resolve(
            Dictionary<string, long> namesToIds, IEnumerable<(string View, string File)> planned)
        {
            var found = new List<(long, string, string)>();
            var missing = new List<string>();
            foreach (var item in planned)
            {
                long id;
                if (namesToIds.TryGetValue(item.View, out id) && id != 0) found.Add((id, item.View, item.File));
                else missing.Add(item.View);
            }
            return (found, missing);
        }

        public static string Summary(List<string> views, string primary, string modelStem)
        {
            if (views.Count == 0) return "No 3D views ticked - NWC export will be skipped.";
            var names = FileNames(modelStem, views, primary);
            string text = views.Count + " view(s). Primary: " + primary + ". Files: " +
                          string.Join(", ", names.Take(4).Select(n => n.File + ".nwc"));
            if (names.Count > 4) text += " and " + (names.Count - 4) + " more";
            return text;
        }

        /// <summary>Reasons the export cannot run as set - empty when it can.</summary>
        public static List<string> Problems(Dictionary<string, string> template, bool available)
        {
            var output = new List<string>();
            if (!McuCore.AsBool(template.Get("export_nwc"))) return output;
            if (!available) output.Add("The Navisworks exporter is not installed for this Revit.");
            if (Selection(template).Views.Count == 0) output.Add("NWC export is on, but no 3D view is ticked.");
            return output;
        }
    }
}
