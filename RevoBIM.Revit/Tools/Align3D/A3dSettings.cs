using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

namespace RevoBIM.Tools.Align3D
{
    /// <summary>
    /// 3D Align - version, settings and paths (port of a3d_settings.py). Settings are plain key=value text at
    /// %APPDATA%\RevoBIM\3d_align.txt, shared with the pyRevit version. A missing or damaged file falls back to the defaults key
    /// by key, and keys this version does not know are ignored.
    /// </summary>
    public static class A3dSettings
    {
        public const string Version = "1.0.0";
        public const string ToolName = "3D Align";
        public const double MmPerFt = 304.8;
        public const string SettingsVersion = "1";

        public static readonly Dictionary<string, string[]> Choices = new Dictionary<string, string[]>
        {
            { "keep_running", new[] { "on", "off" } },
            { "show_results", new[] { "needs_look", "always", "never" } },
            { "on_refusal", new[] { "detach", "leave" } },
            { "theme", new[] { "follow", "dark", "light" } },
            { "debug", new[] { "on", "off" } },
        };

        public static readonly Dictionary<string, string> Defaults = new Dictionary<string, string>
        {
            { "settings_version", SettingsVersion },
            { "keep_running", "on" },
            { "show_results", "needs_look" },
            { "on_refusal", "detach" },
            { "max_move_mm", "3000" },
            { "theme", "follow" },
            { "debug", "on" },
        };

        public static readonly string[] ThemeCycle = { "follow", "dark", "light" };

        public static string DataDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string SettingsPath() { return Path.Combine(DataDir(), "3d_align.txt"); }
        public static string DebugPath() { return Path.Combine(DataDir(), "3d_align_debug.txt"); }
        public static string ErrorPath() { return Path.Combine(DataDir(), "3d_align_last_error.txt"); }

        /// <summary>The add-in build: version, build date and the DLL's path, for the debug header.</summary>
        public static string BuildInfo()
        {
            try
            {
                Assembly assembly = typeof(A3dSettings).Assembly;
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

        /// <summary>The value as it should be stored, or null when it cannot be used.</summary>
        public static string CleanValue(string key, string value)
        {
            value = (value ?? "").Trim();
            string[] allowed;
            if (Choices.TryGetValue(key, out allowed)) return allowed.Contains(value) ? value : null;
            if (key == "max_move_mm")
            {
                double number;
                if (!double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out number) || number < 0) return null;
                return number == Math.Floor(number) ? ((long)number).ToString(CultureInfo.InvariantCulture) : number.ToString(CultureInfo.InvariantCulture);
            }
            if (key == "settings_version")
            {
                int n;
                return int.TryParse(value, out n) ? n.ToString() : null;
            }
            return null;
        }

        public static Dictionary<string, string> Load()
        {
            var found = new Dictionary<string, string>();
            try
            {
                foreach (string line in File.ReadAllLines(SettingsPath(), Encoding.UTF8))
                {
                    int eq = line.IndexOf('=');
                    if (eq < 0 || line.TrimStart().StartsWith("#")) continue;
                    string key = line.Substring(0, eq).Trim();
                    if (!Defaults.ContainsKey(key)) continue;
                    string value = CleanValue(key, line.Substring(eq + 1));
                    if (value != null) found[key] = value;
                }
            }
            catch (Exception)
            {
            }
            var output = new Dictionary<string, string>(Defaults);
            foreach (KeyValuePair<string, string> pair in found) output[pair.Key] = pair.Value;
            output["settings_version"] = SettingsVersion;
            return output;
        }

        public static bool Save(Dictionary<string, string> settings)
        {
            try
            {
                Directory.CreateDirectory(DataDir());
                var lines = new List<string> { "# 3D Align v" + Version };
                foreach (string key in Defaults.Keys.OrderBy(k => k, StringComparer.Ordinal))
                {
                    string raw;
                    string value = CleanValue(key, settings.TryGetValue(key, out raw) ? raw : Defaults[key]) ?? Defaults[key];
                    lines.Add(key + "=" + value);
                }
                File.WriteAllText(SettingsPath(), string.Join("\n", lines) + "\n", new UTF8Encoding(false));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>The header chip saves the theme on its own, so a settings window that is then cancelled does not take its other unsaved edits with it.</summary>
        public static bool SaveTheme(string mode)
        {
            Dictionary<string, string> stored = Load();
            stored["theme"] = mode;
            return Save(stored);
        }

        public static string NextTheme(string mode)
        {
            int i = Array.IndexOf(ThemeCycle, mode);
            return i < 0 ? ThemeCycle[0] : ThemeCycle[(i + 1) % ThemeCycle.Length];
        }

        /// <summary>The largest move allowed in feet, or null for no limit.</summary>
        public static double? MaxMoveFt(Dictionary<string, string> settings)
        {
            string raw;
            double value;
            if (!settings.TryGetValue("max_move_mm", out raw) ||
                !double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out value))
                value = double.Parse(Defaults["max_move_mm"], CultureInfo.InvariantCulture);
            return value <= 0 ? (double?)null : value / MmPerFt;
        }

        public static bool IsOn(Dictionary<string, string> settings, string key)
        {
            string v;
            if (!settings.TryGetValue(key, out v)) Defaults.TryGetValue(key, out v);
            return v == "on";
        }

        public static string Get(Dictionary<string, string> settings, string key)
        {
            string v;
            if (!settings.TryGetValue(key, out v)) Defaults.TryGetValue(key, out v);
            return v ?? "";
        }
    }
}
