using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.SheetNamePush
{
    /// <summary>One sheet as listed in the window. Number and Name hold what is in the model now.</summary>
    public sealed class SnpRecord
    {
        public long Id;
        public string Number = "";
        public string Name = "";
        public ViewSheet Sheet;

        public string Get(string field) { return field == "number" ? Number : Name; }
        public void Set(string field, string value) { if (field == "number") Number = value; else Name = value; }
    }

    /// <summary>What a Find/Replace or Prefix/Suffix window works on: the id and the value as currently staged.</summary>
    public sealed class SnpTarget
    {
        public long Id;
        public string Number = "";
        public string Name = "";

        public string Get(string field) { return field == "number" ? Number : Name; }
    }

    /// <summary>One line of the results window: a parameter, the value pushed to it, and what happened.</summary>
    public sealed class SnpPushResult
    {
        public string Parameter = "";
        public string Value;
        public string Status = "";
    }

    public sealed class SnpPushRow
    {
        public string Number = "";
        public string Name = "";
        public List<SnpPushResult> Results = new List<SnpPushResult>();
    }

    /// <summary>
    /// Sheet Name Push (port of script.py, version 2.2.2): browse, edit and stamp sheets in one window. Rules and settings
    /// here, the Revit reads and writes below, windows in UI\SheetNamePush\.
    /// </summary>
    public static class SnpCore
    {
        public const string Version = "2.2.2";
        public const string ToolName = "Sheet Name Push";
        public const string SettingsVersion = "3";
        public const double CharPx = 7.1;

        public static readonly string[] DefaultParams = { "BGL_Sheet Title 1", "BGL_Sheet Title 2", "BGL_Sheet Title 3" };

        public static readonly Dictionary<string, string> ModeLabels = new Dictionary<string, string>
        {
            { "upper", "UPPERCASE" },
            { "title", "Camel Case (Capitalize Each Word)" },
            { "none", "Don't Format Text" },
        };

        // ---------------------------------------------------------------- build / files --

        public static string DataDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        /// <summary>Unchanged from pyRevit: a missing settings file falls back to the defaults silently, so renaming it would throw away every saved choice.</summary>
        public static string SettingsPath() { return Path.Combine(DataDir(), "sheet_management.txt"); }
        public static string DebugPath() { return Path.Combine(DataDir(), "sheet_name_push_debug.txt"); }
        public static string ErrorPath() { return Path.Combine(DataDir(), "sheet_name_push_last_error.txt"); }

        public static string BuildInfo()
        {
            try
            {
                Assembly assembly = typeof(SnpCore).Assembly;
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

        // ---------------------------------------------------------------- debug log --

        /// <summary>The debug file, one per run: the build line first, then compact "prefix:" lines for each decision. Never throws.</summary>
        public sealed class Log
        {
            private readonly List<string> lines = new List<string>();

            public Log(string revitVersion, string document)
            {
                lines.Add("Sheet Name Push " + Version + " (" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + ")");
                lines.Add("build: " + BuildInfo());
                lines.Add("revit: " + revitVersion + " | document: " + document);
                Flush();
            }

            public void Write(string line)
            {
                lock (lines)
                {
                    lines.Add(DateTime.Now.ToString("HH:mm:ss.fff") + " " + line);
                    Flush();
                }
            }

            private void Flush()
            {
                try
                {
                    Directory.CreateDirectory(DataDir());
                    File.WriteAllText(DebugPath(), string.Join("\r\n", lines) + "\r\n", new UTF8Encoding(false));
                }
                catch (Exception)
                {
                }
            }
        }

        // ---------------------------------------------------------------- settings --

        /// <summary>Plain key=value under %APPDATA%\RevoBIM - falls back key by key.</summary>
        public static Dictionary<string, string> LoadSettings()
        {
            var cfg = new Dictionary<string, string>
            {
                { "settings_version", SettingsVersion },
                { "param_1", DefaultParams[0] },
                { "param_2", DefaultParams[1] },
                { "param_3", DefaultParams[2] },
                { "format_mode", "upper" },
            };
            try
            {
                if (File.Exists(SettingsPath()))
                {
                    foreach (string raw in File.ReadAllLines(SettingsPath(), Encoding.UTF8))
                    {
                        string line = raw.Trim();
                        int eq = line.IndexOf('=');
                        if (line.Length == 0 || line.StartsWith("#") || eq < 0) continue;
                        string key = line.Substring(0, eq).Trim();
                        if (cfg.ContainsKey(key)) cfg[key] = line.Substring(eq + 1).Trim();
                    }
                }
            }
            catch (Exception)
            {
            }
            if (!ModeLabels.ContainsKey(cfg["format_mode"])) cfg["format_mode"] = "upper";
            return cfg;
        }

        public static bool SaveSettings(Dictionary<string, string> cfg)
        {
            try
            {
                Directory.CreateDirectory(DataDir());
                var sb = new StringBuilder("# RevoBIM Sheet Name Push settings\n");
                foreach (string key in cfg.Keys.OrderBy(k => k, StringComparer.Ordinal)) sb.Append(key).Append('=').Append(cfg[key]).Append('\n');
                File.WriteAllText(SettingsPath(), sb.ToString(), new UTF8Encoding(false));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ---------------------------------------------------------------- text rules --

        public static string FormatText(string value, string mode)
        {
            value = (value ?? "").Trim();
            if (mode == "upper") return value.ToUpperInvariant();
            if (mode == "title")
                return string.Join(" ", value.Split(' ').Select(w => w.Length == 0 ? w : w.Substring(0, 1).ToUpperInvariant() + w.Substring(1).ToLowerInvariant()));
            return value;
        }

        /// <summary>The first three "_" separated segments of a sheet name, formatted.</summary>
        public static List<string> SplitSheetName(string name, string mode)
        {
            return (name ?? "").Split('_').Take(3).Select(p => FormatText(p, mode)).ToList();
        }

        public static string Replace(string text, string find, string repl, bool matchCase)
        {
            if (string.IsNullOrEmpty(find)) return text;
            if (matchCase) return text.Replace(find, repl);
            return Regex.Replace(text, Regex.Escape(find), repl.Replace("$", "$$"), RegexOptions.IgnoreCase);
        }

        public static string ApplyAffix(string text, string prefix, string suffix, bool remove)
        {
            if (remove)
            {
                if (prefix.Length > 0 && text.StartsWith(prefix, StringComparison.Ordinal)) text = text.Substring(prefix.Length);
                if (suffix.Length > 0 && text.EndsWith(suffix, StringComparison.Ordinal)) text = text.Substring(0, text.Length - suffix.Length);
                return text;
            }
            return prefix + text + suffix;
        }

        /// <summary>Per sheet, the fields that would change and their new values.</summary>
        public static Dictionary<long, Dictionary<string, string>> Compute(IEnumerable<SnpTarget> targets, IEnumerable<string> fields,
            Func<string, string> change)
        {
            var changes = new Dictionary<long, Dictionary<string, string>>();
            foreach (SnpTarget t in targets)
            {
                var row = new Dictionary<string, string>();
                foreach (string field in fields)
                {
                    string before = t.Get(field);
                    string after = change(before);
                    if (after != before) row[field] = after;
                }
                if (row.Count > 0) changes[t.Id] = row;
            }
            return changes;
        }

        // ---------------------------------------------------------------- the model --

        public static long Key(ElementId id) { return id == null ? 0 : id.Value; }

        /// <summary>Writable string parameters found on sheets, for the Settings lists.</summary>
        public static List<string> SheetTextParameters(Document doc)
        {
            var names = new HashSet<string>();
            try
            {
                foreach (Element sheet in new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)).WhereElementIsNotElementType().Take(40))
                {
                    foreach (Parameter p in sheet.Parameters)
                    {
                        try
                        {
                            if (p.IsReadOnly || p.StorageType != StorageType.String) continue;
                            names.Add(p.Definition.Name);
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
            }
            catch (Exception)
            {
            }
            return names.OrderBy(n => n, StringComparer.Ordinal).ToList();
        }

        public static List<SnpRecord> CollectSheetRecords(Document doc)
        {
            var records = new List<SnpRecord>();
            foreach (ViewSheet s in new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)).WhereElementIsNotElementType().Cast<ViewSheet>())
            {
                try { if (s.IsPlaceholder) continue; } catch (Exception) { }
                records.Add(new SnpRecord { Id = Key(s.Id), Number = s.SheetNumber, Name = s.Name, Sheet = s });
            }
            records.Sort((a, b) => string.CompareOrdinal(a.Number, b.Number));
            return records;
        }

        /// <summary>Writes one field to a sheet and reads it back; false when Revit would not take it.</summary>
        public static bool WriteField(ViewSheet sheet, string field, string value)
        {
            if (field == "number")
            {
                sheet.SheetNumber = value;
                return sheet.SheetNumber == value;
            }
            sheet.Name = value;
            return sheet.Name == value;
        }

        public static SnpPushRow PushSheetName(ViewSheet sheet, string mode, IList<string> paramNames)
        {
            string name = sheet.Name;
            List<string> segments = SplitSheetName(name, mode);
            var row = new SnpPushRow { Number = sheet.SheetNumber, Name = name };
            for (int i = 0; i < paramNames.Count; i++)
            {
                string paramName = paramNames[i];
                if (string.IsNullOrEmpty(paramName)) continue;
                if (i >= segments.Count)
                {
                    row.Results.Add(new SnpPushResult { Parameter = paramName, Status = "skipped (no segment)" });
                    continue;
                }
                string value = segments[i];
                Parameter param = sheet.LookupParameter(paramName);
                if (param == null)
                {
                    row.Results.Add(new SnpPushResult { Parameter = paramName, Value = value, Status = "missing parameter" });
                    continue;
                }
                if (param.IsReadOnly)
                {
                    row.Results.Add(new SnpPushResult { Parameter = paramName, Value = value, Status = "read-only" });
                    continue;
                }
                try
                {
                    bool set = param.Set(value);
                    row.Results.Add(new SnpPushResult { Parameter = paramName, Value = value, Status = set ? "OK" : "error: Revit would not take the value" });
                }
                catch (Exception ex)
                {
                    row.Results.Add(new SnpPushResult { Parameter = paramName, Value = value, Status = "error: " + ex.Message });
                }
            }
            return row;
        }
    }
}
