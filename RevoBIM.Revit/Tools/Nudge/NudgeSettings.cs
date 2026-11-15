using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace RevoBIM.Tools.Nudge
{
    /// <summary>
    /// Settings shared by Nudge Up, Nudge Down and Nudge Settings, kept in
    /// %APPDATA%\RevoBIM\nudge_settings.json (same keys as the pyRevit version,
    /// which kept the file in %APPDATA%\RevoBIM PY; that copy is read once if the
    /// new one does not exist yet). Port of revobim.nudge_settings.
    /// </summary>
    public class NudgeConfig
    {
        public double StepMm = 50.0;
        public double[] Presets = { 10.0, 25.0, 50.0, 100.0 };
        public bool SnapEnabled = true;
        public double SnapMm = 5.0;
        public bool KeepSelection = true;
        public bool RepeatLoop = true;
        public bool AllowFittings = true;
        public bool AllowFabrication = true;
        public bool RecutRods = true;

        public NudgeConfig Clone() => (NudgeConfig)MemberwiseClone();
    }

    public static class NudgeSettings
    {
        public const string Version = "1.6.0";

        private static readonly string Folder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        private static readonly string LegacyFolder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM PY");

        public static string FilePath => Path.Combine(Folder, "nudge_settings.json");

        // The buttons sit on keyboard shortcuts and read the settings on every press,
        // so the parsed result is held and only re-read when the file changes on disk.
        private static NudgeConfig cache;
        private static DateTime cacheStamp;
        private static long cacheSize;

        public static NudgeConfig Load()
        {
            try
            {
                var info = new FileInfo(FilePath);
                if (info.Exists && cache != null && info.LastWriteTimeUtc == cacheStamp && info.Length == cacheSize)
                    return cache.Clone();
                NudgeConfig config = Read(info.Exists ? FilePath : Path.Combine(LegacyFolder, "nudge_settings.json"));
                if (info.Exists)
                {
                    cache = config.Clone();
                    cacheStamp = info.LastWriteTimeUtc;
                    cacheSize = info.Length;
                }
                return config;
            }
            catch (Exception)
            {
                return new NudgeConfig();
            }
        }

        public static bool Save(NudgeConfig config)
        {
            try
            {
                Directory.CreateDirectory(Folder);
                config.StepMm = ClampStep(config.StepMm);
                config.SnapMm = ClampSnap(config.SnapMm);
                var text = new StringBuilder();
                text.Append("{\n");
                text.Append("  \"allow_fabrication\": ").Append(Bool(config.AllowFabrication)).Append(",\n");
                text.Append("  \"allow_fittings\": ").Append(Bool(config.AllowFittings)).Append(",\n");
                text.Append("  \"keep_selection\": ").Append(Bool(config.KeepSelection)).Append(",\n");
                text.Append("  \"presets\": [").Append(string.Join(", ", Array.ConvertAll(config.Presets, Num))).Append("],\n");
                text.Append("  \"recut_rods\": ").Append(Bool(config.RecutRods)).Append(",\n");
                text.Append("  \"repeat_loop\": ").Append(Bool(config.RepeatLoop)).Append(",\n");
                text.Append("  \"snap_enabled\": ").Append(Bool(config.SnapEnabled)).Append(",\n");
                text.Append("  \"snap_mm\": ").Append(Num(config.SnapMm)).Append(",\n");
                text.Append("  \"step_mm\": ").Append(Num(config.StepMm)).Append("\n");
                text.Append("}\n");
                File.WriteAllText(FilePath, text.ToString(), new UTF8Encoding(false));
                cache = null;
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static double ClampStep(double value)
        {
            if (double.IsNaN(value) || value <= 0) return 50.0;
            return value > 100000.0 ? 100000.0 : value;
        }

        public static double ClampSnap(double value)
        {
            if (double.IsNaN(value)) return 5.0;
            if (value <= 0) return 0.0;
            return value > 1000.0 ? 1000.0 : value;
        }

        private static string Bool(bool value) => value ? "true" : "false";
        private static string Num(double value) => value.ToString("0.###", CultureInfo.InvariantCulture);

        // ---- a small reader for the flat JSON this file holds (numbers, bools, one number list) ----

        private static NudgeConfig Read(string path)
        {
            var config = new NudgeConfig();
            try
            {
                if (!File.Exists(path)) return Clamped(config);
                string text = File.ReadAllText(path);
                var values = new Dictionary<string, string>(StringComparer.Ordinal);
                int i = 0;
                while (i < text.Length)
                {
                    int keyStart = text.IndexOf('"', i);
                    if (keyStart < 0) break;
                    int keyEnd = text.IndexOf('"', keyStart + 1);
                    if (keyEnd < 0) break;
                    string key = text.Substring(keyStart + 1, keyEnd - keyStart - 1);
                    int colon = text.IndexOf(':', keyEnd);
                    if (colon < 0) break;
                    int valueStart = colon + 1;
                    while (valueStart < text.Length && char.IsWhiteSpace(text[valueStart])) valueStart++;
                    int valueEnd = valueStart;
                    if (valueStart < text.Length && text[valueStart] == '[')
                    {
                        valueEnd = text.IndexOf(']', valueStart);
                        if (valueEnd < 0) break;
                        valueEnd++;
                    }
                    else
                    {
                        while (valueEnd < text.Length && text[valueEnd] != ',' && text[valueEnd] != '}' && text[valueEnd] != '\n')
                            valueEnd++;
                    }
                    values[key] = text.Substring(valueStart, valueEnd - valueStart).Trim();
                    i = valueEnd;
                }

                config.StepMm = Dbl(values, "step_mm", config.StepMm);
                config.SnapMm = Dbl(values, "snap_mm", config.SnapMm);
                config.SnapEnabled = Flag(values, "snap_enabled", config.SnapEnabled);
                config.KeepSelection = Flag(values, "keep_selection", config.KeepSelection);
                config.RepeatLoop = Flag(values, "repeat_loop", config.RepeatLoop);
                config.AllowFittings = Flag(values, "allow_fittings", config.AllowFittings);
                config.AllowFabrication = Flag(values, "allow_fabrication", config.AllowFabrication);
                config.RecutRods = Flag(values, "recut_rods", config.RecutRods);
                if (values.TryGetValue("presets", out string list))
                {
                    var found = new List<double>();
                    foreach (string part in list.Trim('[', ']').Split(','))
                        if (double.TryParse(part.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out double d))
                            found.Add(d);
                    if (found.Count > 0) config.Presets = found.ToArray();
                }
            }
            catch (Exception)
            {
                // a corrupt file must never stop the tool: fall back to defaults
                config = new NudgeConfig();
            }
            return Clamped(config);
        }

        private static NudgeConfig Clamped(NudgeConfig config)
        {
            config.StepMm = ClampStep(config.StepMm);
            config.SnapMm = ClampSnap(config.SnapMm);
            return config;
        }

        private static double Dbl(Dictionary<string, string> values, string key, double fallback)
        {
            return values.TryGetValue(key, out string raw)
                   && double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out double d) ? d : fallback;
        }

        private static bool Flag(Dictionary<string, string> values, string key, bool fallback)
        {
            if (!values.TryGetValue(key, out string raw)) return fallback;
            if (raw == "true") return true;
            if (raw == "false") return false;
            return fallback;
        }
    }
}
