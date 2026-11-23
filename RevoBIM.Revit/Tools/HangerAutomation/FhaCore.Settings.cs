using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class FhaCore
    {
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
    }
}
