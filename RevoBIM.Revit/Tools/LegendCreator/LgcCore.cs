using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Text;

namespace RevoBIM.Tools.LegendCreator
{
    /// <summary>
    /// Legend Creator - foundations: version, settings, the run's record.
    /// Log() always records to memory and writes the debug file only when
    /// Debug is ticked; Swallowed() notes an error a handler chose to absorb.
    /// Port of lgc_core.py.
    /// </summary>
    public static class LgcCore
    {
        public const string Version = "3.0.0";

        public static readonly string SettingsDir =
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        public static readonly string SettingsFile = Path.Combine(SettingsDir, "legend_creator.txt");
        public static readonly string LogFile = Path.Combine(SettingsDir, "legend_creator_debug.txt");
        public static readonly string ReportFile = Path.Combine(SettingsDir, "legend_creator_debug_report.txt");

        public const int TraceLimit = 3000;

        // Off unless the Debug tick is on, so a normal run writes nothing to disk.
        public static bool DebugOn;

        // What happened this run, kept in memory whether or not Debug is on.
        public static readonly List<string> Lines = new List<string>();
        public static readonly Dictionary<(string Where, string What), int> Absorbed =
            new Dictionary<(string, string), int>();
        public static readonly List<(string Where, string What)> Order = new List<(string, string)>();
        public static string Crash;
        public static string Theme;
        private static readonly Stopwatch Clock = Stopwatch.StartNew();

        private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false);

        /// <summary>Start a run's record afresh.</summary>
        public static void ResetTrace()
        {
            Lines.Clear();
            Absorbed.Clear();
            Order.Clear();
            Crash = null;
            Theme = null;
            Clock.Restart();
            DebugOn = false;
        }

        /// <summary>Record a step: always in memory, in the debug file when ticked.</summary>
        public static void Log(string message)
        {
            string line = string.Format(LgcLogic.Inv, "[{0,7:F2}s] {1}", Clock.Elapsed.TotalSeconds, message);
            Lines.Add(line);
            if (Lines.Count > TraceLimit) Lines.RemoveRange(0, Lines.Count - TraceLimit);
            if (!DebugOn) return;
            try
            {
                Directory.CreateDirectory(SettingsDir);
                File.AppendAllText(LogFile, line + "\n", Utf8);
            }
            catch (Exception)
            {
                // the log must never cost the run
            }
        }

        /// <summary>
        /// Note an exception that a handler chose to absorb. The tool absorbs
        /// errors on purpose so one odd element does not stop a run; recording
        /// each one, where and how often, keeps "it does nothing" fixable.
        /// </summary>
        public static void Swallowed(Exception error,
                                     [CallerMemberName] string member = "",
                                     [CallerLineNumber] int line = 0)
        {
            try
            {
                if (error == null) return;
                var key = (string.Format(LgcLogic.Inv, "{0}() line {1}", member, line), ErrText(error));
                if (!Absorbed.ContainsKey(key))
                {
                    Absorbed[key] = 0;
                    Order.Add(key);
                    if (Order.Count <= 400) Log("   absorbed in " + key.Item1 + ": " + key.Item2);
                }
                Absorbed[key] += 1;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Switch the debug file on or off for this run.</summary>
        public static void StartDebug(bool on)
        {
            bool was = DebugOn;
            DebugOn = on;
            if (on && !was)
            {
                Log(new string('#', 60));
                Log(string.Format(LgcLogic.Inv, "Legend Creator {0}   {1:yyyy-MM-dd HH:mm:ss}   debug on",
                                  Version, DateTime.Now));
            }
        }

        /// <summary>First line of an exception message, never throwing.</summary>
        public static string ErrText(Exception error)
        {
            string text;
            try
            {
                text = error?.Message ?? "unreadable error";
            }
            catch (Exception)
            {
                text = "unreadable error";
            }
            return text.Split('\n')[0].TrimEnd('\r');
        }

        // -----------------------------------------------------------------
        // Settings - plain key=value, falling back key by key. Same file as
        // the pyRevit tool, so both share the user's last choices.
        // -----------------------------------------------------------------
        public static Dictionary<string, string> Defaults()
        {
            return new Dictionary<string, string>
            {
                ["phase"] = LgcLogic.DefaultPhase,
                ["name_param"] = LgcLogic.DefaultNameParam,
                ["text_type"] = "",
                ["text_case"] = LgcLogic.DefaultCase,
                ["combined"] = "0",
                ["scale"] = LgcLogic.DefaultScale.ToString(LgcLogic.Inv),
                ["row_spacing"] = LgcLogic.PyFloat(LgcLogic.RowSpacingMm),
                ["text_offset"] = LgcLogic.PyFloat(LgcLogic.TextOffsetMm),
                ["column_spacing"] = LgcLogic.PyFloat(LgcLogic.DefaultColumnSpacingMm),
                ["sys_kind"] = "containment",
                ["sys_template"] = "",
                ["sys_scale"] = LgcLogic.SystemDefaultScale.ToString(LgcLogic.Inv),
                ["sys_text_type"] = "",
                ["sys_head_type"] = "",
                ["sys_swatch_w"] = LgcLogic.PyFloat(LgcLogic.SwatchWMm),
                ["sys_swatch_h"] = "containment=700;ductwork=700;pipework=300",
                ["sys_row_pitch"] = LgcLogic.PyFloat(LgcLogic.SysRowPitchMm),
                ["sys_text_gap"] = LgcLogic.PyFloat(LgcLogic.SysTextGapMm),
                ["sys_view_name"] = "",
                ["sys_upper"] = "1",
                ["sys_line_weight"] = LgcLogic.DefaultLineWeight.ToString(LgcLogic.Inv),
                ["theme_mode"] = "auto",
                ["debug"] = "0",
            };
        }

        public static Dictionary<string, string> LoadSettings()
        {
            var values = Defaults();
            try
            {
                if (File.Exists(SettingsFile))
                {
                    foreach (string raw in File.ReadAllLines(SettingsFile, Utf8))
                    {
                        string line = raw.Trim();
                        if (line.Length == 0 || line.StartsWith("#") || !line.Contains("=")) continue;
                        int eq = line.IndexOf('=');
                        string key = line.Substring(0, eq).Trim();
                        if (values.ContainsKey(key)) // unknown keys ignored
                            values[key] = line.Substring(eq + 1).Trim();
                    }
                }
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return values;
        }

        public static void SaveSettings(Dictionary<string, string> values)
        {
            try
            {
                Directory.CreateDirectory(SettingsDir);
                var text = new StringBuilder("# RevoBIM PY - Legend Creator\n");
                foreach (string key in values.Keys.OrderBy(k => k, StringComparer.Ordinal))
                    text.Append(key).Append('=').Append(values[key]).Append('\n');
                File.WriteAllText(SettingsFile, text.ToString(), Utf8);
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        public static string Get(this Dictionary<string, string> settings, string key, string fallback = "")
        {
            return settings.TryGetValue(key, out string value) ? value : fallback;
        }
    }
}
