using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ModelCleanup
{
    /// <summary>One view, schedule or legend as the cleanup rules see it.</summary>
    public sealed class McuViewItem
    {
        public long Id;
        public string Name = "";
        public string Kind = "";
        public bool Template;
        public long Parent;
        public bool Internal;
    }

    public sealed class McuSheetItem
    {
        public long Id;
        public string Number = "";
        public string Name = "";
        public bool Placeholder;
    }

    /// <summary>A view or sheet offered in a "to retain" list.</summary>
    public sealed class McuRetainItem
    {
        public string Key = "";
        public string Label = "";
        public List<string> Folders = new List<string>();
        public long Id;
    }

    public sealed class McuRetainRow
    {
        public bool IsHeader;
        public int Level;
        public string Label = "";
        public string Path = "";
        public List<string> Children = new List<string>();
        public int Count;
        public bool Collapsed;
        public string State = "none";
        public string Key = "";
        public bool Checked;
    }

    /// <summary>
    /// Model Cleanup - version, settings, templates and every rule that decides something. Nothing in
    /// this class touches Revit or WPF. Port of mcu_core.py (2.0.0).
    /// </summary>
    public static class McuCore
    {
        public const string Version = "2.0.0";
        public const string ToolName = "Model Cleanup";
        public const int SettingsVersion = 2;
        public static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        // settings_version -> keys whose meaning changed in that version and must be reset to default
        private static readonly Dictionary<int, string[]> Migrations = new Dictionary<int, string[]>
        {
            { 2, new[] { "purge_passes" } },
        };

        // ============================================================
        // paths and logging
        // ============================================================

        public static string AppDataDir()
        {
            string baseDir = Environment.GetEnvironmentVariable("APPDATA");
            if (string.IsNullOrEmpty(baseDir)) baseDir = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            string path = Path.Combine(baseDir, "RevoBIM");
            try
            {
                if (!Directory.Exists(path)) Directory.CreateDirectory(path);
            }
            catch (Exception) { }
            return path;
        }

        public static string SettingsPath() { return Path.Combine(AppDataDir(), "model_cleanup.txt"); }

        public static string TemplatesDir()
        {
            string path = Path.Combine(AppDataDir(), "model_cleanup_templates");
            try
            {
                if (!Directory.Exists(path)) Directory.CreateDirectory(path);
            }
            catch (Exception) { }
            return path;
        }

        public static string LogPath() { return Path.Combine(AppDataDir(), "model_cleanup_debug.txt"); }
        public static string ErrorPath() { return Path.Combine(AppDataDir(), "model_cleanup_last_error.txt"); }

        public static void Log(string message)
        {
            try
            {
                string stamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", Inv);
                File.AppendAllText(LogPath(), stamp + "  " + message + "\n", new UTF8Encoding(false));
            }
            catch (Exception) { }
        }

        public static void WriteError(string stage, string text)
        {
            try
            {
                File.WriteAllText(ErrorPath(), string.Format(Inv, "RevoBIM {0} {1}\nStage: {2}\n\n{3}\n",
                    ToolName, Version, stage, text), new UTF8Encoding(false));
            }
            catch (Exception) { }
            Log("ERROR in " + stage + ": " + text);
        }

        public static string FormatException(Exception error)
        {
            try
            {
                return error == null ? "(no traceback)" : error.ToString();
            }
            catch (Exception)
            {
                return "(no traceback)";
            }
        }

        // ============================================================
        // key=value files
        // ============================================================

        /// <summary>Split on the first '=' only, so a value may itself contain '='.</summary>
        public static Dictionary<string, string> ReadKv(string path)
        {
            var output = new Dictionary<string, string>();
            string text;
            try
            {
                if (!File.Exists(path)) return output;
                text = File.ReadAllText(path, Encoding.UTF8);
            }
            catch (Exception)
            {
                return output;
            }
            foreach (string raw in text.Replace("\r\n", "\n").Split('\n'))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#") || !line.Contains("=")) continue;
                int at = line.IndexOf('=');
                output[line.Substring(0, at).Trim()] = line.Substring(at + 1).Trim();
            }
            return output;
        }

        public static bool WriteKv(string path, IEnumerable<KeyValuePair<string, string>> pairs, string header = null)
        {
            var lines = new List<string>();
            if (!string.IsNullOrEmpty(header)) lines.Add("# " + header);
            foreach (var pair in pairs) lines.Add(pair.Key + "=" + (pair.Value ?? "").Replace("\n", " "));
            try
            {
                File.WriteAllText(path, string.Join("\n", lines) + "\n", new UTF8Encoding(false));
                return true;
            }
            catch (Exception)
            {
                Log("could not write " + path);
                return false;
            }
        }

        public static bool AsBool(string value, bool fallback = false)
        {
            string text = (value ?? "").Trim().ToLowerInvariant();
            if (text == "1" || text == "true" || text == "yes" || text == "on") return true;
            if (text == "0" || text == "false" || text == "no" || text == "off") return false;
            return fallback;
        }

        public static int AsInt(string value, int fallback, int? low = null, int? high = null)
        {
            double parsed;
            if (!double.TryParse((value ?? "").Trim(), NumberStyles.Float, Inv, out parsed)) return fallback;
            int number = (int)parsed;
            if (low.HasValue && number < low.Value) number = low.Value;
            if (high.HasValue && number > high.Value) number = high.Value;
            return number;
        }

        public static string BoolText(bool flag) { return flag ? "1" : "0"; }

        public static string Get(this Dictionary<string, string> map, string key, string fallback = "")
        {
            string value;
            return map != null && map.TryGetValue(key, out value) ? value : fallback;
        }

        public static List<string> SplitList(string text)
        {
            return (text ?? "").Split('|').Select(p => p.Trim()).Where(p => p.Length > 0).ToList();
        }

        public static string JoinList(IEnumerable<string> items)
        {
            var seen = new List<string>();
            foreach (string raw in items)
            {
                string item = (raw ?? "").Trim().Replace("|", "/");
                if (item.Length > 0 && !seen.Contains(item)) seen.Add(item);
            }
            return string.Join("|", seen);
        }

        public static List<string> SplitWords(string text)
        {
            return Regex.Split(text ?? "", "[;,]").Select(p => p.Trim()).Where(p => p.Length > 0).ToList();
        }

        // ============================================================
        // global settings
        // ============================================================

        public static readonly List<KeyValuePair<string, string>> GlobalDefaults = new List<KeyValuePair<string, string>>
        {
            Pair("settings_version", SettingsVersion.ToString(Inv)),
            Pair("theme_mode", "auto"),
            Pair("last_template", "Standard Issue"),
            Pair("last_folder", ""),
            Pair("debug", "0"),
            Pair("template_folder", ""),
            // publish to ACC - one APS app per person or office, not per template
            Pair("aps_client_id", ""),
            Pair("aps_port", "8765"),
        };

        private static KeyValuePair<string, string> Pair(string key, string value)
        {
            return new KeyValuePair<string, string>(key, value);
        }

        public static Dictionary<string, string> LoadGlobal()
        {
            return MergeDefaults(ReadKv(SettingsPath()), GlobalDefaults);
        }

        public static bool SaveGlobal(Dictionary<string, string> values)
        {
            var pairs = new List<KeyValuePair<string, string>>();
            foreach (var def in GlobalDefaults) pairs.Add(Pair(def.Key, values.Get(def.Key, def.Value)));
            pairs[0] = Pair("settings_version", SettingsVersion.ToString(Inv));
            return WriteKv(SettingsPath(), pairs, "Model Cleanup settings");
        }

        /// <summary>Defaults key by key; unknown keys dropped; migrated keys reset.</summary>
        public static Dictionary<string, string> MergeDefaults(Dictionary<string, string> raw,
                                                               IEnumerable<KeyValuePair<string, string>> defaults)
        {
            var output = new Dictionary<string, string>();
            int saved = AsInt(raw.Get("settings_version", "0"), 0);
            var reset = new HashSet<string>();
            foreach (var migration in Migrations)
                if (saved < migration.Key)
                    foreach (string key in migration.Value) reset.Add(key);
            foreach (var def in defaults)
                output[def.Key] = raw.ContainsKey(def.Key) && !reset.Contains(def.Key) ? raw[def.Key] : def.Value;
            return output;
        }

        // ============================================================
        // export settings templates
        // ============================================================

        public const string DetachPreserve = "preserve";
        public const string DetachDiscard = "discard";

        // NWC export - (template key, NavisworksExportOptions property, label, default)
        public static readonly List<(string Key, string Prop, string Label, string Default)> NwcBoolOptions =
            new List<(string, string, string, string)>
        {
            ("nwc_links", "ExportLinks", "Export Revit links", "0"),
            ("nwc_properties", "ConvertElementProperties", "Convert element properties", "1"),
            ("nwc_levels", "DivideFileIntoLevels", "Divide file into levels", "1"),
            ("nwc_ids", "ExportElementIds", "Export element IDs", "1"),
            ("nwc_parts", "ExportParts", "Export parts", "0"),
            ("nwc_room_attr", "ExportRoomAsAttribute", "Export room as attribute", "0"),
            ("nwc_room_geo", "ExportRoomGeometry", "Export room geometry", "0"),
            ("nwc_urls", "ExportUrls", "Export URLs", "1"),
            ("nwc_materials", "FindMissingMaterials", "Try to find missing materials", "1"),
            ("nwc_lights", "ConvertLights", "Convert lights", "0"),
            ("nwc_linked_cad", "ConvertLinkedCADFormats", "Convert linked CAD files", "0"),
        };

        public static readonly List<KeyValuePair<string, string>> TemplateDefaults = BuildTemplateDefaults();

        private static List<KeyValuePair<string, string>> BuildTemplateDefaults()
        {
            var list = new List<KeyValuePair<string, string>>
            {
                Pair("settings_version", SettingsVersion.ToString(Inv)),
                // detach and save
                Pair("detach_mode", DetachPreserve),
                Pair("audit", "0"),
                Pair("sync_comment", "Model Cleanup - synced before issue"),
                Pair("relinquish", "1"),
                Pair("compact", "1"),
                Pair("add_suffix", "1"),
                Pair("file_suffix", "_Issue"),
                Pair("add_date", "1"),
                Pair("open_when_done", "1"),
                // publish to ACC after the sync
                Pair("offer_publish", "1"),
                Pair("publish_links", "ask"),
                // clean up
                Pair("remove_revit_links", "1"),
                Pair("remove_cad", "1"),
                Pair("remove_point_clouds", "1"),
                Pair("delete_unplaced_images", "1"),
                Pair("delete_views_off_sheet", "1"),
                Pair("delete_schedules_off_sheet", "1"),
                Pair("delete_legends_off_sheet", "0"),
                Pair("delete_unused_templates", "1"),
                Pair("delete_unused_filters", "1"),
                Pair("keep_view_words", "KEEP;Starting"),
                Pair("delete_sheets_not_retained", "0"),
                Pair("retain_views", ""),
                Pair("retain_sheets", ""),
                // purge
                Pair("purge", "1"),
                Pair("purge_passes", "4"),
                Pair("purge_exclude", ""),
                Pair("show_used", "0"),
                Pair("export_nwc", "0"),
                Pair("nwc_source", "custom"),
                Pair("nwc_coordinates", "shared"),
                Pair("nwc_parameters", "all"),
                Pair("nwc_faceting", "1"),
            };
            foreach (var option in NwcBoolOptions) list.Add(Pair(option.Key, option.Default));
            list.Add(Pair("nwc_views", ""));
            list.Add(Pair("nwc_primary", ""));
            return list;
        }

        // (key, label) - the order the clean up runs in and the order it is listed.
        public static readonly List<(string Key, string Label)> CleanupOps = new List<(string, string)>
        {
            ("export_nwc", "Export NWC first"),
            ("delete_sheets_not_retained", "Delete sheets not retained"),
            ("delete_views_off_sheet", "Delete views not retained or placed"),
            ("delete_schedules_off_sheet", "Delete schedules not retained or placed"),
            ("delete_legends_off_sheet", "Delete legends not retained or placed"),
            ("delete_unplaced_images", "Delete raster images that are not placed"),
            ("remove_revit_links", "Remove Revit links"),
            ("remove_cad", "Remove CAD links and imports"),
            ("remove_point_clouds", "Remove point clouds"),
            ("delete_unused_templates", "Delete unused view templates"),
            ("delete_unused_filters", "Delete unused view filters"),
            ("purge", "Purge unused elements"),
        };

        private static readonly List<(string Name, Dictionary<string, string> Overrides)> SeedTemplatesList =
            new List<(string, Dictionary<string, string>)>
        {
            ("Standard Issue", new Dictionary<string, string>()),
            ("Keep Links", new Dictionary<string, string>
            {
                { "remove_revit_links", "0" }, { "remove_cad", "0" }, { "remove_point_clouds", "0" },
            }),
            ("Purge Only", new Dictionary<string, string>
            {
                { "remove_revit_links", "0" }, { "remove_cad", "0" }, { "remove_point_clouds", "0" },
                { "delete_views_off_sheet", "0" }, { "delete_sheets_not_retained", "0" },
                { "delete_schedules_off_sheet", "0" }, { "delete_unused_templates", "0" },
                { "delete_unused_filters", "0" }, { "file_suffix", "_Purged" },
            }),
        };

        private const string BadNameChars = "\\/:*?\"<>|";

        public static string SanitizeName(string name)
        {
            string text = name ?? "";
            foreach (char ch in BadNameChars) text = text.Replace(ch, ' ');
            text = Regex.Replace(text, "\\s+", " ").Trim().Trim('.');
            return text.Length > 80 ? text.Substring(0, 80) : text;
        }

        public static string TemplatePath(string name, string folder = null)
        {
            return Path.Combine(folder ?? TemplatesDir(), SanitizeName(name) + ".txt");
        }

        public static Dictionary<string, string> DefaultTemplate()
        {
            var map = new Dictionary<string, string>();
            foreach (var def in TemplateDefaults) map[def.Key] = def.Value;
            return map;
        }

        public static List<string> SeedTemplates(string folder = null)
        {
            folder = folder ?? TemplatesDir();
            var written = new List<string>();
            foreach (var seed in SeedTemplatesList)
            {
                var values = DefaultTemplate();
                foreach (var over in seed.Overrides) values[over.Key] = over.Value;
                if (SaveTemplate(seed.Name, values, folder)) written.Add(seed.Name);
            }
            return written;
        }

        public static List<string> ListTemplates(string folder = null)
        {
            folder = folder ?? TemplatesDir();
            var names = new List<string>();
            try
            {
                foreach (string entry in Directory.GetFiles(folder, "*.txt"))
                    names.Add(Path.GetFileNameWithoutExtension(entry));
            }
            catch (Exception) { }
            if (names.Count == 0)
            {
                SeedTemplates(folder);
                names = SeedTemplatesList.Select(s => s.Name).ToList();
            }
            return names.Distinct().OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        // 1.2.1 renamed the tool; a comment saved under the old name is refreshed
        private static readonly Dictionary<string, string[]> RenamedDefaults = new Dictionary<string, string[]>
        {
            { "sync_comment", new[] { "RevoBIM Model Cleanup - synced before issue" } },
        };

        /// <summary>Carry settings that have been renamed or folded into another one across.</summary>
        public static Dictionary<string, string> UpgradeTemplate(Dictionary<string, string> raw,
                                                                 Dictionary<string, string> values)
        {
            var defaults = DefaultTemplate();
            foreach (var renamed in RenamedDefaults)
                if (renamed.Value.Contains(values.Get(renamed.Key))) values[renamed.Key] = defaults[renamed.Key];
            // 2.0.0: "Remove all raster images, placed or not" became "remove only the ones not placed".
            if (AsBool(raw.Get("remove_images"), false)) values["delete_unplaced_images"] = "1";
            return values;
        }

        public static Dictionary<string, string> LoadTemplate(string name, string folder = null)
        {
            var raw = ReadKv(TemplatePath(name, folder));
            return UpgradeTemplate(raw, MergeDefaults(raw, TemplateDefaults));
        }

        public static bool SaveTemplate(string name, Dictionary<string, string> values, string folder = null)
        {
            name = SanitizeName(name);
            if (name.Length == 0) return false;
            var pairs = new List<KeyValuePair<string, string>>();
            foreach (var def in TemplateDefaults) pairs.Add(Pair(def.Key, values.Get(def.Key, def.Value)));
            pairs[0] = Pair("settings_version", SettingsVersion.ToString(Inv));
            return WriteKv(TemplatePath(name, folder), pairs, "Model Cleanup export settings: " + name);
        }

        /// <summary>Never deletes the last template - the dropdown must never be empty.</summary>
        public static (bool Ok, string Reason) DeleteTemplate(string name, string folder = null)
        {
            if (ListTemplates(folder).Count <= 1) return (false, "The last template cannot be deleted.");
            try
            {
                File.Delete(TemplatePath(name, folder));
                return (true, "");
            }
            catch (Exception error)
            {
                return (false, error.Message);
            }
        }

        // ============================================================
        // sharing a template as a file
        // ============================================================

        public const string ExportPrefix = "Model Cleanup Template";
        public const string ExportMarker = "model_cleanup_template";

        public static string ExportFileName(string templateName)
        {
            string name = SanitizeName(templateName);
            return name.Length == 0 ? ExportPrefix + ".txt" : ExportPrefix + " - " + name + ".txt";
        }

        public static string NameFromFile(string path)
        {
            string stem = (path ?? "").Replace("\\", "/").TrimEnd('/').Split('/').Last();
            if (stem.ToLowerInvariant().EndsWith(".txt")) stem = stem.Substring(0, stem.Length - 4);
            if (stem.ToLowerInvariant().StartsWith(ExportPrefix.ToLowerInvariant()))
                stem = stem.Substring(ExportPrefix.Length).TrimStart(' ', '-', '_');
            string clean = SanitizeName(stem);
            return clean.Length > 0 ? clean : ExportPrefix;
        }

        public static string UniqueTemplateName(string name, IEnumerable<string> existing)
        {
            name = SanitizeName(name);
            if (name.Length == 0) name = ExportPrefix;
            var taken = new HashSet<string>((existing ?? new string[0]).Select(n => (n ?? "").ToLowerInvariant()));
            if (!taken.Contains(name.ToLowerInvariant())) return name;
            int number = 2;
            while (taken.Contains((name + " (" + number + ")").ToLowerInvariant())) number++;
            return name + " (" + number + ")";
        }

        public static bool ExportTemplate(Dictionary<string, string> values, string templateName, string path)
        {
            var pairs = new List<KeyValuePair<string, string>>
            {
                Pair(ExportMarker, SettingsVersion.ToString(Inv)),
                Pair("template_name", SanitizeName(templateName)),
                Pair("settings_version", SettingsVersion.ToString(Inv)),
            };
            foreach (var def in TemplateDefaults)
            {
                if (def.Key == "settings_version") continue;
                pairs.Add(Pair(def.Key, values.Get(def.Key, def.Value)));
            }
            return WriteKv(path, pairs, ExportPrefix + ": " + SanitizeName(templateName) +
                                        " (exported from Model Cleanup " + Version + ")");
        }

        public static (Dictionary<string, string> Values, string Name, string Error) ImportTemplate(string path)
        {
            var raw = ReadKv(path);
            if (raw.Count == 0)
                return (null, "", "That file has nothing in it that Model Cleanup can read.");
            int known = TemplateDefaults.Count(d => raw.ContainsKey(d.Key));
            if (!raw.ContainsKey(ExportMarker) && known < 5)
                return (null, "", "That does not look like a Model Cleanup settings template. It carries " +
                                  known + " of this tool's settings.");
            var values = UpgradeTemplate(raw, MergeDefaults(raw, TemplateDefaults));
            string name = SanitizeName(raw.Get("template_name"));
            if (name.Length == 0) name = NameFromFile(path);
            return (values, name, "");
        }

        public static string PickTemplate(IList<string> names, string wanted)
        {
            if (names.Contains(wanted)) return wanted;
            foreach (string name in names)
                if (string.Equals(name, wanted, StringComparison.OrdinalIgnoreCase)) return name;
            return names.Count > 0 ? names[0] : "";
        }

        public static List<(string Key, string Label)> EnabledOps(Dictionary<string, string> template)
        {
            return CleanupOps.Where(op => AsBool(template.Get(op.Key), false)).ToList();
        }

        // ============================================================
        // the three steps
        // ============================================================

        public const string StepSync = "sync";
        public const string StepSaveAs = "save_as";
        public const string StepCleanup = "cleanup";

        /// <summary>Which step buttons are lit. Clean Up only lights once the model has been synced AND saved as.</summary>
        public static Dictionary<string, bool> StepStates(bool synced, bool savedAs, bool cleaned, bool busy, bool targetAlive = true)
        {
            return new Dictionary<string, bool>
            {
                { StepSync, !busy },
                { StepSaveAs, synced && !busy },
                { StepCleanup, synced && savedAs && targetAlive && !cleaned && !busy },
            };
        }

        public static string StepBadge(bool enabled, bool done, bool skipped = false)
        {
            if (skipped) return "Skipped";
            if (done) return "Done";
            return enabled ? "Ready" : "Locked";
        }

        public const string ConfirmWord = "CONFIRM";

        public static bool ConfirmTyped(string text) { return (text ?? "").Trim() == ConfirmWord; }

        public static (bool Synced, bool SavedAs) EffectiveSteps(bool synced, bool savedAs, bool skipped)
        {
            return (synced || skipped, savedAs || skipped);
        }

        public static bool CanSkip(bool synced, bool savedAs, bool skipped, bool cleaned, bool busy)
        {
            return !(synced || savedAs || skipped || cleaned || busy);
        }

        public static string SkipWarning(McuModelInfo info)
        {
            var lines = new List<string>
            {
                "Skipping steps 1 and 2 cleans THE MODEL THAT IS OPEN NOW. There is no detached copy: links, " +
                "views and purged elements are removed from this model.",
                "",
                "NEVER do this to a central model, or to a local file you will sync. Everything removed here " +
                "would reach the central, and everyone on the project, at the next sync.",
            };
            if (info.Workshared)
            {
                if (info.Central.Length > 0 && SamePath(info.Central, info.Path))
                {
                    lines.Add("");
                    lines.Add("WARNING: the open file IS the central model.");
                }
                else
                {
                    lines.Add("");
                    lines.Add("WARNING: the open model is workshared and still connected to its central" +
                              (info.Cloud ? " on ACC." : "."));
                }
            }
            lines.Add("");
            lines.Add("Only continue on a model you have already detached or copied yourself. The tool will not " +
                      "save or sync afterwards - check the result, then save it yourself. Revit's Undo reverses " +
                      "the whole clean up in one step.");
            lines.Add("");
            lines.Add("Type " + ConfirmWord + " to skip steps 1 and 2.");
            return string.Join("\n", lines);
        }

        public static string SyncLabel(bool workshared) { return workshared ? "Sync Current Model" : "Save Current Model"; }

        // ============================================================
        // naming the send copy
        // ============================================================

        public static string ActiveSuffix(Dictionary<string, string> template)
        {
            if (!AsBool(template.Get("add_suffix"), true)) return "";
            return template.Get("file_suffix").Trim();
        }

        public static string ModelStem(string pathOrTitle)
        {
            string text = (pathOrTitle ?? "").Replace("\\", "/").TrimEnd('/').Split('/').Last();
            if (text.ToLowerInvariant().EndsWith(".rvt")) text = text.Substring(0, text.Length - 4);
            return text;
        }

        public static string SendFileName(string source, string suffix, bool addDate, DateTime? today = null, string userName = null)
        {
            string stem = ModelStem(source);
            if (!string.IsNullOrEmpty(userName))
            {
                string tail = "_" + userName;
                if (stem.ToLowerInvariant().EndsWith(tail.ToLowerInvariant()) && stem.Length > tail.Length)
                    stem = stem.Substring(0, stem.Length - tail.Length);
            }
            suffix = (suffix ?? "").Trim();
            if (suffix.Length > 0 && !stem.EndsWith(suffix, StringComparison.Ordinal)) stem += suffix;
            if (addDate) stem += "_" + (today ?? DateTime.Today).ToString("yyyy-MM-dd", Inv);
            stem = SanitizeName(stem);
            if (stem.Length == 0) stem = "Model";
            return stem + ".rvt";
        }

        public static bool SamePath(string first, string second)
        {
            if (string.IsNullOrWhiteSpace(first) || string.IsNullOrWhiteSpace(second)) return false;
            try
            {
                return string.Equals(Path.GetFullPath(first.Trim()), Path.GetFullPath(second.Trim()),
                                     StringComparison.OrdinalIgnoreCase);
            }
            catch (Exception)
            {
                return string.Equals(first.Trim(), second.Trim(), StringComparison.OrdinalIgnoreCase);
            }
        }

        public const string RouteDetachedOpen = "detached_open"; // file-based central: open it detached, save
        public const string RouteFileCopy = "file_copy";         // not workshared: copy the file, open it
        public const string RouteSaveOpen = "save_open";         // ACC: the synced open model is saved as the copy

        public static string SaveAsRoute(McuModelInfo info)
        {
            if (!info.Workshared) return RouteFileCopy;
            return info.Cloud ? RouteSaveOpen : RouteDetachedOpen;
        }

        public static string SaveAsConfirmation(McuModelInfo info, string target, string detachMode)
        {
            string route = SaveAsRoute(info);
            string head = "This saves the DETACHED copy:\n" + target + "\n\n";
            string tail = "\n\nFrom here on, that copy is the detached model - Clean Up, the NWC export and Save and " +
                          "close all work on it, never on the live model.";
            string body;
            if (route == RouteSaveOpen)
            {
                body = "This model is on ACC. Revit cannot detach a cloud model while opening it, so the model open " +
                       "now - just synced - is saved as a new local central at that path. That saved file is the " +
                       "detached copy: it has no link back to ACC, and the model on ACC is not changed.\n\n" +
                       "This window then works in the copy. Worksets are kept.";
                if (detachMode == DetachDiscard)
                    body += " (The template asks to discard worksets, which is not possible for an ACC model.)";
            }
            else if (route == RouteFileCopy)
            {
                body = "This model is not workshared, so the saved file is copied to that path and the copy is " +
                       "opened in the background.";
            }
            else
            {
                body = "The central is opened again in the background, detached (" +
                       (detachMode == DetachDiscard ? "discarding" : "keeping") +
                       " worksets), and saved to that path. The model open now is not touched.";
            }
            return head + body + tail;
        }

        /// <summary>Null when the target is usable, otherwise the reason it is not.</summary>
        public static string CheckTargetPath(string target, IEnumerable<string> protectedPaths)
        {
            target = (target ?? "").Trim();
            if (target.Length == 0) return "Choose where the send copy is saved first.";
            if (!target.ToLowerInvariant().EndsWith(".rvt")) return "The send copy must be a .rvt file.";
            foreach (string path in protectedPaths)
                if (SamePath(target, path)) return "That is the live model. Choose a different file for the send copy.";
            string folder = Path.GetDirectoryName(target);
            if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder)) return "The folder does not exist: " + folder;
            return null;
        }

        // ============================================================
        // which views, schedules and legends go
        // ============================================================

        public static readonly HashSet<string> NeverDeleteKinds = new HashSet<string>
        {
            "DrawingSheet", "ProjectBrowser", "SystemBrowser", "Internal", "Undefined", "Report", "CostReport",
            "LoadsReport", "PresureLossReport", "PanelSchedule", "ColumnSchedule",
        };
        public static readonly HashSet<string> ScheduleKinds = new HashSet<string> { "Schedule" };
        public static readonly HashSet<string> LegendKinds = new HashSet<string> { "Legend" };

        public static bool HasKeepWord(string name, IEnumerable<string> keepWords)
        {
            string lower = (name ?? "").ToLowerInvariant();
            foreach (string word in keepWords)
                if (word.Length > 0 && lower.Contains(word.ToLowerInvariant())) return true;
            return false;
        }

        /// <summary>
        /// Returns (ids_to_delete, skipped) where skipped maps id -> reason. A primary view is kept whenever
        /// any of its dependents is kept, because deleting a primary view deletes its dependents with it.
        /// </summary>
        public static (List<long> Ids, Dictionary<long, string> Skipped) OffSheetCandidates(
            IEnumerable<McuViewItem> items, ICollection<long> onSheet, IEnumerable<string> keepWords,
            ICollection<long> protectedIds, HashSet<string> kinds = null, HashSet<string> excludeKinds = null,
            ICollection<string> retained = null, Dictionary<long, string> decisions = null)
        {
            var keep = (keepWords ?? new string[0]).ToList();
            var skipped = new Dictionary<long, string>();
            var chosen = new List<long>();
            var kept = new HashSet<long>();
            var byId = new Dictionary<long, McuViewItem>();
            var note = decisions ?? new Dictionary<long, string>();
            var list = items.ToList();
            foreach (McuViewItem item in list)
            {
                byId[item.Id] = item;
                if (kinds != null && !kinds.Contains(item.Kind)) continue;
                if (excludeKinds != null && excludeKinds.Contains(item.Kind)) continue;
                if (NeverDeleteKinds.Contains(item.Kind)) { note[item.Id] = "kept: Revit system view"; continue; }
                if (item.Template) { note[item.Id] = "kept: view template"; continue; }
                if (item.Internal)
                {
                    skipped[item.Id] = "title block revision or keynote schedule (goes with its sheet)";
                    kept.Add(item.Id);
                    continue;
                }
                if (onSheet.Contains(item.Id)) { note[item.Id] = "kept: placed on a sheet that stays"; kept.Add(item.Id); continue; }
                if (protectedIds.Contains(item.Id)) { skipped[item.Id] = "starting or active view"; kept.Add(item.Id); continue; }
                if (retained != null && retained.Count > 0 && retained.Contains(ViewKey(item.Kind, item.Name)))
                {
                    skipped[item.Id] = "retained in the template";
                    kept.Add(item.Id);
                    continue;
                }
                if (HasKeepWord(item.Name, keep)) { skipped[item.Id] = "name holds a keep word"; kept.Add(item.Id); continue; }
                chosen.Add(item.Id);
            }
            // dependents on sheets anywhere in the model protect their primary view
            foreach (McuViewItem item in list)
                if (onSheet.Contains(item.Id)) kept.Add(item.Id);
            var rescued = new HashSet<long>();
            bool changed = true;
            while (changed)
            {
                changed = false;
                foreach (long viewId in kept.ToList())
                {
                    McuViewItem item;
                    long parent = byId.TryGetValue(viewId, out item) ? item.Parent : 0;
                    if (parent != 0 && !kept.Contains(parent))
                    {
                        kept.Add(parent);
                        rescued.Add(parent);
                        changed = true;
                    }
                }
            }
            var output = new List<long>();
            foreach (long viewId in chosen)
            {
                if (rescued.Contains(viewId)) { skipped[viewId] = "a dependent of it is kept"; continue; }
                output.Add(viewId);
            }
            foreach (var pair in skipped) note[pair.Key] = "kept: " + pair.Value;
            foreach (long viewId in output) note[viewId] = "DELETE";
            return (output, skipped);
        }

        public delegate (List<long> Ids, Dictionary<long, string> Skipped) ViewRule(
            IEnumerable<McuViewItem> items, ICollection<long> onSheet, IEnumerable<string> keepWords,
            ICollection<long> protectedIds, ICollection<string> retained, Dictionary<long, string> decisions);

        public static (List<long>, Dictionary<long, string>) ViewsToDelete(IEnumerable<McuViewItem> items,
            ICollection<long> onSheet, IEnumerable<string> keepWords, ICollection<long> protectedIds,
            ICollection<string> retained = null, Dictionary<long, string> decisions = null)
        {
            var exclude = new HashSet<string>(ScheduleKinds.Concat(LegendKinds));
            return OffSheetCandidates(items, onSheet, keepWords, protectedIds, null, exclude, retained, decisions);
        }

        public static (List<long>, Dictionary<long, string>) SchedulesToDelete(IEnumerable<McuViewItem> items,
            ICollection<long> onSheet, IEnumerable<string> keepWords, ICollection<long> protectedIds,
            ICollection<string> retained = null, Dictionary<long, string> decisions = null)
        {
            return OffSheetCandidates(items, onSheet, keepWords, protectedIds, ScheduleKinds, null, retained, decisions);
        }

        public static (List<long>, Dictionary<long, string>) LegendsToDelete(IEnumerable<McuViewItem> items,
            ICollection<long> onSheet, IEnumerable<string> keepWords, ICollection<long> protectedIds,
            ICollection<string> retained = null, Dictionary<long, string> decisions = null)
        {
            return OffSheetCandidates(items, onSheet, keepWords, protectedIds, LegendKinds, null, retained, decisions);
        }

        /// <summary>Every sheet whose number is not retained goes, except the starting or active view.</summary>
        public static (List<long> Ids, Dictionary<long, string> Skipped) SheetsToDelete(IEnumerable<McuSheetItem> sheets,
            ICollection<string> retainedNumbers, ICollection<long> protectedIds, Dictionary<long, string> decisions = null)
        {
            var note = decisions ?? new Dictionary<long, string>();
            var output = new List<long>();
            var skipped = new Dictionary<long, string>();
            foreach (McuSheetItem sheet in sheets)
            {
                if (retainedNumbers.Contains(sheet.Number)) { note[sheet.Id] = "kept: retained in the template"; continue; }
                if (protectedIds.Contains(sheet.Id))
                {
                    skipped[sheet.Id] = "starting or active view";
                    note[sheet.Id] = "kept: starting or active view";
                    continue;
                }
                output.Add(sheet.Id);
                note[sheet.Id] = "DELETE";
            }
            return (output, skipped);
        }

        public static HashSet<long> SurvivingSheetIds(List<McuSheetItem> sheets, bool deleteSheets,
            ICollection<string> retainedNumbers, ICollection<long> protectedIds)
        {
            if (!deleteSheets) return new HashSet<long>(sheets.Select(s => s.Id));
            var gone = new HashSet<long>(SheetsToDelete(sheets, retainedNumbers, protectedIds).Ids);
            return new HashSet<long>(sheets.Where(s => !gone.Contains(s.Id)).Select(s => s.Id));
        }

        public static List<long> UnplacedImages(IEnumerable<long> imageTypeIds, ICollection<long> unusedIds)
        {
            return imageTypeIds.Where(unusedIds.Contains).ToList();
        }

        /// <summary>For the preview: images unused now, plus images whose every placement is on a view that is going.</summary>
        public static List<long> ImagesFreed(IEnumerable<long> imageTypeIds, IEnumerable<(long TypeId, long ViewId)> instances,
            ICollection<long> doomedViews, ICollection<long> unusedIds)
        {
            var owners = new Dictionary<long, HashSet<long>>();
            foreach (var instance in instances)
            {
                HashSet<long> set;
                if (!owners.TryGetValue(instance.TypeId, out set)) owners[instance.TypeId] = set = new HashSet<long>();
                set.Add(instance.ViewId);
            }
            var output = new List<long>();
            foreach (long value in imageTypeIds)
            {
                HashSet<long> views;
                owners.TryGetValue(value, out views);
                if (unusedIds.Contains(value) || (views != null && views.Count > 0 && views.IsSubsetOf(doomedViews)))
                    output.Add(value);
            }
            return output;
        }

        /// <summary>What a delete took that has to stay.</summary>
        public static List<long> CascadeHits(IEnumerable<long> deletedIds, ICollection<long> guard)
        {
            if (guard == null || guard.Count == 0) return new List<long>();
            return (deletedIds ?? new long[0]).Where(guard.Contains).Distinct().OrderBy(v => v).ToList();
        }

        public static (Dictionary<long, string> Refused, Dictionary<long, string> Kept) SplitRefusals(Dictionary<long, string> failures)
        {
            var refused = new Dictionary<long, string>();
            var kept = new Dictionary<long, string>();
            foreach (var pair in failures ?? new Dictionary<long, string>())
            {
                if ((pair.Value ?? "").StartsWith("kept - ")) kept[pair.Key] = pair.Value;
                else refused[pair.Key] = pair.Value;
            }
            return (refused, kept);
        }

        /// <summary>
        /// Every view and sheet the plan keeps, plus every view placed on a sheet that still exists.
        /// </summary>
        public static HashSet<long> ViewGuard(IEnumerable<long> allViewIds, ICollection<long> doomedIds, IEnumerable<long> placedIds)
        {
            var kept = new HashSet<long>(allViewIds.Where(v => !doomedIds.Contains(v)));
            foreach (long id in placedIds ?? new long[0]) kept.Add(id);
            return kept;
        }

        public static string CascadeReason(IEnumerable<string> hitNames)
        {
            var names = hitNames.Where(n => !string.IsNullOrEmpty(n)).ToList();
            if (names.Count == 0) return "kept - deleting it would also delete a view that stays";
            string text = string.Join(", ", names.Take(3).Select(n => "'" + n + "'"));
            if (names.Count > 3) text += " and " + (names.Count - 3) + " more";
            return "kept - deleting it would also delete " + text + ", which stays";
        }

        public static List<long> UnusedIds(IEnumerable<long> all, ICollection<long> used, ICollection<long> keep = null)
        {
            return all.Where(v => !used.Contains(v) && (keep == null || !keep.Contains(v))).ToList();
        }

        // ============================================================
        // views and sheets to retain
        // ============================================================

        public const char RetainSep = '\t';

        public static readonly Dictionary<string, string> ViewTypeLabels = new Dictionary<string, string>
        {
            { "FloorPlan", "Floor Plans" }, { "CeilingPlan", "Ceiling Plans" }, { "EngineeringPlan", "Structural Plans" },
            { "AreaPlan", "Area Plans" }, { "ThreeD", "3D Views" }, { "Section", "Sections" },
            { "Elevation", "Elevations" }, { "Detail", "Detail Views" }, { "DraftingView", "Drafting Views" },
            { "Rendering", "Renderings" }, { "Walkthrough", "Walkthroughs" }, { "Legend", "Legends" },
            { "Schedule", "Schedules/Quantities" },
        };

        // groups Revit puts at the top of the browser, outside the view organisation
        public static readonly HashSet<string> TopLevelKinds = new HashSet<string> { "Legend", "Schedule" };

        public static string ViewKey(string kind, string name) { return kind + "::" + name; }

        public static List<string> SplitRetain(string text)
        {
            return (text ?? "").Split(RetainSep).Where(p => p.Trim().Length > 0).ToList();
        }

        public static string JoinRetain(IEnumerable<string> keys)
        {
            var seen = new List<string>();
            foreach (string raw in keys)
            {
                string key = (raw ?? "").Replace("\t", " ").Replace("\n", " ");
                if (key.Trim().Length > 0 && !seen.Contains(key)) seen.Add(key);
            }
            seen.Sort(NaturalCompare);
            return string.Join(RetainSep.ToString(), seen);
        }

        /// <summary>P-9 before P-10, case-blind. Number parts sort before text parts.</summary>
        public static int NaturalCompare(string a, string b)
        {
            string[] left = Regex.Split((a ?? "").ToLowerInvariant(), "(\\d+)");
            string[] right = Regex.Split((b ?? "").ToLowerInvariant(), "(\\d+)");
            for (int i = 0; i < Math.Min(left.Length, right.Length); i++)
            {
                bool leftNum = left[i].Length > 0 && left[i].All(char.IsDigit);
                bool rightNum = right[i].Length > 0 && right[i].All(char.IsDigit);
                int result;
                if (leftNum && rightNum)
                {
                    result = CompareDigits(left[i], right[i]);
                }
                else if (leftNum != rightNum)
                {
                    result = leftNum ? -1 : 1;
                }
                else
                {
                    result = string.CompareOrdinal(left[i], right[i]);
                }
                if (result != 0) return result < 0 ? -1 : 1;
            }
            return left.Length.CompareTo(right.Length);
        }

        private static int CompareDigits(string a, string b)
        {
            a = a.TrimStart('0');
            b = b.TrimStart('0');
            if (a.Length != b.Length) return a.Length.CompareTo(b.Length);
            return string.CompareOrdinal(a, b);
        }

        public static string SplitCamel(string text)
        {
            return Regex.Replace(text ?? "", "(?<=[a-z0-9])(?=[A-Z])", " ");
        }

        public static List<string> ViewFolders(IEnumerable<string> orgFolders, string kind)
        {
            string label;
            if (!ViewTypeLabels.TryGetValue(kind, out label)) label = SplitCamel(kind);
            if (TopLevelKinds.Contains(kind)) return new List<string> { label };
            var folders = (orgFolders ?? new string[0]).Select(f => string.IsNullOrEmpty(f) ? "???" : f).ToList();
            folders.Add(label);
            return folders;
        }

        public static List<string> SheetFolders(IEnumerable<string> orgFolders)
        {
            var folders = (orgFolders ?? new string[0]).Select(f => string.IsNullOrEmpty(f) ? "???" : f).ToList();
            if (folders.Count == 0) folders.Add("Sheets");
            return folders;
        }

        private static bool Matches(List<string> words, McuRetainItem item)
        {
            if (words.Count == 0) return true;
            string haystack = (item.Label + " " + string.Join(" ", item.Folders)).ToLowerInvariant();
            return words.All(haystack.Contains);
        }

        public static string GroupState(IList<string> keys, ICollection<string> retained)
        {
            if (keys.Count == 0) return "none";
            int hits = keys.Count(retained.Contains);
            if (hits == keys.Count) return "all";
            return hits == 0 ? "none" : "some";
        }

        private static int CompareItems(McuRetainItem a, McuRetainItem b)
        {
            int count = Math.Min(a.Folders.Count, b.Folders.Count);
            for (int i = 0; i < count; i++)
            {
                int result = NaturalCompare(a.Folders[i], b.Folders[i]);
                if (result != 0) return result;
            }
            if (a.Folders.Count != b.Folders.Count) return a.Folders.Count.CompareTo(b.Folders.Count);
            return NaturalCompare(a.Label, b.Label);
        }

        /// <summary>
        /// The rows to draw, in browser order: a header each time a folder level changes, then the item.
        /// Headers carry the keys of every shown item beneath them, so ticking a header ticks exactly what
        /// the search is showing. A search opens every folder so a match is never hidden.
        /// </summary>
        public static List<McuRetainRow> RetainRows(IEnumerable<McuRetainItem> items, string search,
            ICollection<string> retained, ICollection<string> collapsedIn = null, bool onlyRetained = false)
        {
            var collapsed = (search ?? "").Trim().Length > 0 || collapsedIn == null
                ? new HashSet<string>() : new HashSet<string>(collapsedIn);
            var words = (search ?? "").ToLowerInvariant().Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries).ToList();
            var shown = items.Where(item => Matches(words, item) && (!onlyRetained || retained.Contains(item.Key))).ToList();
            // stable sort: List.Sort is not stable, so order by index as the final tie-break
            var indexed = shown.Select((item, index) => (item, index)).ToList();
            indexed.Sort((x, y) =>
            {
                int result = CompareItems(x.item, y.item);
                return result != 0 ? result : x.index.CompareTo(y.index);
            });
            shown = indexed.Select(p => p.item).ToList();

            var under = new Dictionary<string, List<string>>();
            foreach (McuRetainItem item in shown)
            {
                for (int level = 0; level < item.Folders.Count; level++)
                {
                    string path = string.Join("\x1f", item.Folders.Take(level + 1));
                    List<string> list;
                    if (!under.TryGetValue(path, out list)) under[path] = list = new List<string>();
                    list.Add(item.Key);
                }
            }
            var rows = new List<McuRetainRow>();
            var previous = new List<string>();
            foreach (McuRetainItem item in shown)
            {
                var folders = item.Folders;
                int common = 0;
                while (common < previous.Count && common < folders.Count && previous[common] == folders[common]) common++;
                bool hidden = false;
                for (int level = 0; level < folders.Count; level++)
                {
                    string pathText = string.Join("\x1f", folders.Take(level + 1));
                    if (level >= common)
                    {
                        var children = under[pathText];
                        rows.Add(new McuRetainRow
                        {
                            IsHeader = true, Level = level, Label = folders[level], Path = pathText,
                            Children = children, Count = children.Count, Collapsed = collapsed.Contains(pathText),
                            State = GroupState(children, retained),
                        });
                    }
                    if (collapsed.Contains(pathText)) { hidden = true; break; }
                }
                previous = folders;
                if (hidden) continue;
                rows.Add(new McuRetainRow
                {
                    IsHeader = false, Level = folders.Count, Key = item.Key, Label = item.Label,
                    Checked = retained.Contains(item.Key),
                });
            }
            return rows;
        }

        public static HashSet<string> AllFolderPaths(IEnumerable<McuRetainItem> items)
        {
            var paths = new HashSet<string>();
            foreach (McuRetainItem item in items)
                for (int level = 0; level < item.Folders.Count; level++)
                    paths.Add(string.Join("\x1f", item.Folders.Take(level + 1)));
            return paths;
        }

        /// <summary>The first candidate that stays and is not the current view. 0 when nothing qualifies.</summary>
        public static long ChooseSwitchView(IEnumerable<long> candidates, ICollection<long> doomed, long current)
        {
            foreach (long viewId in candidates)
                if (viewId != 0 && viewId != current && !doomed.Contains(viewId)) return viewId;
            return 0;
        }

        /// <summary>Where to move the active view before cleaning the open model. 0 means stay where you are.</summary>
        public static long ViewToOpen(long activeId, IList<long> retainedSheetIds, IList<long> retainedViewIds,
            ICollection<long> doomed, IEnumerable<long> fallbacks)
        {
            if (retainedSheetIds.Count == 0 && retainedViewIds.Count == 0)
                return doomed.Contains(activeId) ? ChooseSwitchView(fallbacks, doomed, activeId) : 0;
            if (retainedSheetIds.Contains(activeId) || retainedViewIds.Contains(activeId)) return 0;
            long target = ChooseSwitchView(retainedSheetIds.Concat(retainedViewIds), doomed, activeId);
            if (target == 0 && doomed.Contains(activeId)) target = ChooseSwitchView(fallbacks, doomed, activeId);
            return target;
        }

        // ============================================================
        // save and close at the end
        // ============================================================

        public const string SaveAs = "save_as";     // never saved: ask where
        public const string SavePlain = "save";     // not workshared
        public const string SaveSync = "sync";      // its own central: sync, relinquish, compact
        public const string SaveLocal = "local";    // a local of someone else's central: ask
        public const string SaveNone = "none";      // Clean Up already saved it and nothing changed since

        public static string SaveRoute(McuModelInfo info)
        {
            if (info.Path.Trim().Length == 0) return SaveAs;
            if (!info.Workshared) return SavePlain;
            if (info.Cloud) return SaveLocal;
            string central = info.Central.Trim();
            if (central.Length == 0 || SamePath(central, info.Path)) return SaveSync;
            return SaveLocal;
        }

        public static string LocalSaveMessage(McuModelInfo info)
        {
            return string.Format(Inv,
                "This is a local file of\n{0}\n\n" +
                "Relinquishing worksets needs a sync, and a sync would send the whole clean up to that central " +
                "model and everyone working in it.\n\n" +
                "Save local only: saves this file compact and keeps your worksets.\n" +
                "Sync and relinquish: only if that central is itself a throwaway copy - you will be asked to type {1}.",
                info.Central.Length > 0 ? info.Central : "its central model", ConfirmWord);
        }

        public static string FolderOf(string path)
        {
            path = (path ?? "").Trim();
            if (path.Length == 0 || path.Contains("://")) return "";
            return Path.GetDirectoryName(path) ?? "";
        }

        public static List<string> RetentionWarnings(Dictionary<string, string> template)
        {
            var output = new List<string>();
            bool sheets = SplitRetain(template.Get("retain_sheets")).Count > 0;
            bool views = SplitRetain(template.Get("retain_views")).Count > 0;
            bool deleteSheets = AsBool(template.Get("delete_sheets_not_retained"));
            bool deleteViews = AsBool(template.Get("delete_views_off_sheet"));
            if (sheets && !deleteSheets) output.Add("sheets");
            if (!deleteSheets && views && deleteViews) output.Add("placed_views");
            if (views && !deleteViews) output.Add("views");
            return output;
        }

        public static string RetentionMessage(Dictionary<string, string> template, IEnumerable<string> warnings)
        {
            var lines = new List<string>();
            foreach (string key in warnings)
            {
                string text;
                switch (key)
                {
                    case "sheets":
                        text = SplitRetain(template.Get("retain_sheets")).Count + " sheets are ticked to retain, but " +
                               "Delete sheets not retained is off, so no sheet will be removed.";
                        break;
                    case "placed_views":
                        text = "With Delete sheets not retained off, every sheet stays, so every view placed on a " +
                               "sheet stays too - retained or not.";
                        break;
                    default:
                        text = "Views are ticked to retain, but Delete views not retained or placed is off, so no " +
                               "view will be removed.";
                        break;
                }
                lines.Add("- " + text);
            }
            return string.Join("\n", lines);
        }

        public static Dictionary<string, string> FixRetention(Dictionary<string, string> template, ICollection<string> warnings)
        {
            var fixedTemplate = new Dictionary<string, string>(template);
            if (warnings.Contains("sheets") || warnings.Contains("placed_views")) fixedTemplate["delete_sheets_not_retained"] = "1";
            if (warnings.Contains("views")) fixedTemplate["delete_views_off_sheet"] = "1";
            return fixedTemplate;
        }

        private static readonly Dictionary<string, string> KeptLabels = new Dictionary<string, string>
        {
            { "PanelSchedule", "Panel Schedules" }, { "ColumnSchedule", "Graphical Column Schedules" },
            { "Report", "Reports" }, { "CostReport", "Cost Reports" }, { "LoadsReport", "Loads Reports" },
            { "PresureLossReport", "Pressure Loss Reports" },
        };

        /// <summary>Lines for the Clean Up confirmation: what stays that someone might expect to go.</summary>
        public static List<string> KeptSummary(IEnumerable<McuViewItem> views, Dictionary<long, string> decisions)
        {
            var counts = new SortedDictionary<string, int>(StringComparer.Ordinal);
            foreach (McuViewItem item in views)
            {
                string reason;
                decisions.TryGetValue(item.Id, out reason);
                reason = reason ?? "";
                string label;
                if (reason == "kept: its delete stage is off") label = "{0} (their delete stage is off)";
                else if (reason == "kept: Revit system view" &&
                         item.Kind != "ProjectBrowser" && item.Kind != "SystemBrowser" &&
                         item.Kind != "Internal" && item.Kind != "Undefined") label = "{0} (never deleted by this tool)";
                else continue;
                string name;
                if (!KeptLabels.TryGetValue(item.Kind, out name) && !ViewTypeLabels.TryGetValue(item.Kind, out name))
                    name = SplitCamel(item.Kind);
                string key = string.Format(Inv, label, name);
                int count;
                counts.TryGetValue(key, out count);
                counts[key] = count + 1;
            }
            return counts.Select(p => p.Value + " " + p.Key).ToList();
        }

        public static string RetainSummary(IEnumerable<McuRetainItem> items, ICollection<string> retained, string noun)
        {
            var keys = new HashSet<string>(items.Select(i => i.Key));
            int kept = keys.Count(retained.Contains);
            int missing = retained.Count(k => !keys.Contains(k));
            string text = kept + " of " + keys.Count + " " + noun + " retained";
            if (missing > 0) text += " (" + missing + " more listed in the template are not in this model)";
            return text;
        }

        // ============================================================
        // purge groups
        // ============================================================

        private static readonly Dictionary<string, string> ClassGroups = new Dictionary<string, string>
        {
            { "Material", "Materials" }, { "LinePatternElement", "Line Patterns" }, { "FillPatternElement", "Fill Patterns" },
            { "ParameterFilterElement", "View Filters" }, { "ViewFamilyType", "View Types" },
            { "AppearanceAssetElement", "Appearance Assets" }, { "PropertySetElement", "Physical and Thermal Assets" },
            { "ImageType", "Raster Images" }, { "GraphicsStyle", "Line Styles" }, { "TextNoteType", "Text Types" },
            { "DimensionType", "Dimension Types" }, { "SpotDimensionType", "Spot Dimension Types" },
            { "GroupType", "Group Types" }, { "WallType", "Walls" }, { "FloorType", "Floors" },
            { "CeilingType", "Ceilings" }, { "RoofType", "Roofs" }, { "PipeType", "Pipes" }, { "DuctType", "Ducts" },
            { "CableTrayType", "Cable Trays" }, { "ConduitType", "Conduits" }, { "FlexPipeType", "Flex Pipes" },
            { "FlexDuctType", "Flex Ducts" }, { "PipingSystemType", "Piping Systems" },
            { "MechanicalSystemType", "Duct Systems" }, { "PipeSegment", "Pipe Segments" },
            { "PipeScheduleType", "Pipe Schedule Types" }, { "MEPSystemType", "MEP Systems" },
            { "FilledRegionType", "Filled Region Types" }, { "ElementType", "Other Types" },
            { "Element", "Other Elements" }, { "LineAndTextAttrSymbol", "Line and Text Styles" },
            { "ElectricalLoadClassification", "Load Classifications" },
        };

        public const string OtherGroup = "Other";

        /// <summary>The name a purgeable element is listed and ticked under.</summary>
        public static string PurgeGroup(string categoryName, string className)
        {
            categoryName = (categoryName ?? "").Trim();
            if (categoryName.Length > 0) return categoryName;
            className = (className ?? "").Trim();
            string group;
            if (ClassGroups.TryGetValue(className, out group)) return group;
            return className.Length > 0 ? SplitCamel(className) : OtherGroup;
        }

        public static List<long> PurgeSelection(IEnumerable<(long Id, string Group)> entries, ICollection<string> excluded)
        {
            return entries.Where(e => !excluded.Contains(e.Group)).Select(e => e.Id).ToList();
        }

        public static List<(string Group, int Unused, int Used)> GroupCounts(IEnumerable<(long Id, string Group)> unused,
            IEnumerable<(long Id, string Group)> used)
        {
            var counts = new Dictionary<string, int[]>();
            foreach (var entry in unused)
            {
                int[] pair;
                if (!counts.TryGetValue(entry.Group, out pair)) counts[entry.Group] = pair = new int[2];
                pair[0]++;
            }
            foreach (var entry in used)
            {
                int[] pair;
                if (!counts.TryGetValue(entry.Group, out pair)) counts[entry.Group] = pair = new int[2];
                pair[1]++;
            }
            return counts.Select(p => (p.Key, p.Value[0], p.Value[1]))
                         .OrderBy(r => r.Key.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        public static List<(string Group, int Unused, int Used)> VisibleGroups(IEnumerable<(string Group, int Unused, int Used)> rows,
            bool showUsed, string search)
        {
            var words = (search ?? "").ToLowerInvariant().Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
            var output = new List<(string, int, int)>();
            foreach (var row in rows)
            {
                if (!showUsed && row.Unused == 0) continue;
                string lower = row.Group.ToLowerInvariant();
                if (words.Any(w => !lower.Contains(w))) continue;
                output.Add(row);
            }
            return output;
        }

        // ============================================================
        // deleting in chunks, and the purge passes
        // ============================================================

        public static IEnumerable<List<T>> Chunks<T>(IEnumerable<T> sequence, int size)
        {
            size = Math.Max(1, size);
            var items = sequence.ToList();
            for (int start = 0; start < items.Count; start += size)
                yield return items.Skip(start).Take(size).ToList();
        }

        /// <summary>
        /// A refused chunk is replayed one element at a time so only the element at fault is lost, and anything
        /// already removed alongside something else is not asked for twice. Progress is reported after every
        /// chunk and after every replayed element.
        /// </summary>
        public static (List<long> Deleted, Dictionary<long, string> Failures) DeleteInChunks(IEnumerable<long> ids,
            Func<List<long>, bool> deleteBatch, Func<long, (bool Ok, string Reason)> deleteOne, Func<long, bool> stillThere,
            int size = 25, Action<double> progress = null)
        {
            var deleted = new List<long>();
            var failures = new Dictionary<long, string>();
            var pending = ids.ToList();
            double total = Math.Max(1, pending.Count);
            int done = 0;
            Action<int> report = extra =>
            {
                if (progress == null) return;
                try { progress(Math.Min(1.0, (done + extra) / total)); } catch (Exception) { }
            };
            foreach (var chunk in Chunks(pending, size))
            {
                var live = chunk.Where(stillThere).ToList();
                var goneAlready = chunk.Where(v => !live.Contains(v)).ToList();
                deleted.AddRange(goneAlready);
                if (live.Count > 0)
                {
                    bool ok = false;
                    try { ok = deleteBatch(live); } catch (Exception) { ok = false; }
                    if (ok)
                    {
                        deleted.AddRange(live);
                    }
                    else
                    {
                        for (int position = 0; position < live.Count; position++)
                        {
                            long value = live[position];
                            if (!stillThere(value))
                            {
                                deleted.Add(value);
                            }
                            else
                            {
                                bool oneOk;
                                string reason;
                                try { (oneOk, reason) = deleteOne(value); }
                                catch (Exception error) { oneOk = false; reason = error.Message; }
                                if (oneOk) deleted.Add(value);
                                else failures[value] = string.IsNullOrEmpty(reason) ? "Revit refused" : reason;
                            }
                            report(goneAlready.Count + position + 1);
                        }
                    }
                }
                done += chunk.Count;
                report(0);
            }
            if (pending.Count == 0 && progress != null)
            {
                try { progress(1.0); } catch (Exception) { }
            }
            return (deleted, failures);
        }

        /// <summary>
        /// Purging frees more to purge, so it runs in passes, stopping early when a pass removes nothing.
        /// Ids that failed once are not retried.
        /// </summary>
        public static (List<long> Deleted, Dictionary<long, string> Failures, int Ran) PurgeLoop(
            Func<List<(long Id, string Group)>> scan,
            Func<List<long>, Action<double>, (List<long> Deleted, Dictionary<long, string> Failures)> delete,
            ICollection<string> excluded, int passes, Action<double> progress = null)
        {
            passes = Math.Max(1, passes);
            var totalDeleted = new List<long>();
            var failures = new Dictionary<long, string>();
            int ran = 0;
            Action<double> report = value =>
            {
                if (progress == null) return;
                try { progress(Math.Max(0.0, Math.Min(1.0, value))); } catch (Exception) { }
            };
            for (int index = 0; index < passes; index++)
            {
                double baseValue = (double)index / passes;
                report(baseValue);
                var ids = PurgeSelection(scan(), excluded).Where(v => !failures.ContainsKey(v)).ToList();
                if (ids.Count == 0) break;
                ran++;
                var (deleted, failed) = delete(ids, fraction => report(baseValue + fraction / passes));
                totalDeleted.AddRange(deleted);
                foreach (var pair in failed) failures[pair.Key] = pair.Value;
                if (deleted.Count == 0) break;
            }
            report(1.0);
            return (totalDeleted, failures, ran);
        }

        // ============================================================
        // progress: stage weights, percent and time left
        // ============================================================

        private static readonly Dictionary<string, double> StageWeights = new Dictionary<string, double>
        {
            { "remove_revit_links", 1.0 }, { "remove_cad", 1.5 }, { "remove_point_clouds", 1.0 },
            { "delete_unplaced_images", 0.5 }, { "export_nwc", 5.0 }, { "delete_views_off_sheet", 4.0 },
            { "delete_schedules_off_sheet", 1.5 }, { "delete_legends_off_sheet", 0.5 },
            { "delete_unused_templates", 1.0 }, { "delete_unused_filters", 1.0 }, { "purge", 6.0 },
            { "delete_sheets_not_retained", 2.0 }, { "save", 3.0 },
        };

        /// <summary>[(key, start, span)] covering 0..1 in order.</summary>
        public static List<(string Key, double Start, double Span)> StagePlan(IEnumerable<string> keys)
        {
            var weights = keys.Select(k => (Key: k, Weight: StageWeights.ContainsKey(k) ? StageWeights[k] : 1.0)).ToList();
            double total = weights.Sum(w => w.Weight);
            if (total <= 0) total = 1.0;
            var plan = new List<(string, double, double)>();
            double start = 0.0;
            foreach (var weight in weights)
            {
                double span = weight.Weight / total;
                plan.Add((weight.Key, start, span));
                start += span;
            }
            return plan;
        }

        public static double PlanFraction(List<(string Key, double Start, double Span)> plan, string key, double local)
        {
            foreach (var entry in plan)
            {
                if (entry.Key != key) continue;
                local = Math.Max(0.0, Math.Min(1.0, local));
                return Math.Min(1.0, entry.Start + entry.Span * local);
            }
            return 0.0;
        }

        /// <summary>Percent that never runs backwards, and a time-left estimate.</summary>
        public sealed class ProgressClock
        {
            private const double MinElapsed = 2.0, MinFraction = 0.02, SampleGap = 0.5, Smoothing = 0.3;
            private readonly Func<double> now;
            public double? Started;
            public double Fraction;
            private double? rate;
            private double lastTime;
            private double lastFraction;
            public double? FinishedAt;

            public ProgressClock(Func<double> clock = null)
            {
                now = clock ?? (() => (DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalSeconds);
            }

            public double Now() { return now(); }

            public void Start()
            {
                Started = now();
                Fraction = 0.0;
                rate = null;
                lastTime = Started.Value;
                lastFraction = 0.0;
                FinishedAt = null;
            }

            public double Update(double fraction)
            {
                if (Started == null) Start();
                fraction = Math.Max(Fraction, Math.Min(1.0, Math.Max(0.0, fraction)));
                double moment = now();
                double gap = moment - lastTime;
                double moved = fraction - lastFraction;
                if (gap >= SampleGap && moved > 0)
                {
                    double sample = moved / gap;
                    rate = rate == null ? sample : Smoothing * sample + (1.0 - Smoothing) * rate.Value;
                    lastTime = moment;
                    lastFraction = fraction;
                }
                Fraction = fraction;
                return fraction;
            }

            public void Finish()
            {
                Update(1.0);
                FinishedAt = now();
            }

            public double Elapsed()
            {
                if (Started == null) return 0.0;
                double end = FinishedAt ?? now();
                return Math.Max(0.0, end - Started.Value);
            }

            public int Percent()
            {
                if (Fraction >= 1.0) return 100;
                return Math.Min(99, (int)(Fraction * 100));
            }

            /// <summary>Seconds left, or null while there is not enough to go on.</summary>
            public double? Eta()
            {
                if (Fraction >= 1.0) return 0.0;
                double elapsed = Elapsed();
                if (elapsed < MinElapsed || Fraction < MinFraction) return null;
                double average = Fraction / elapsed;
                double r = rate == null ? average : 0.5 * average + 0.5 * rate.Value;
                if (r <= 0) return null;
                return (1.0 - Fraction) / r;
            }
        }

        public static string FormatDuration(double seconds)
        {
            int s = Math.Max(0, (int)Math.Round(seconds, MidpointRounding.AwayFromZero));
            if (s < 60) return s + " s";
            if (s < 3600) return (s / 60) + " min " + (s % 60).ToString("00", Inv) + " s";
            return (s / 3600) + " h " + ((s % 3600) / 60).ToString("00", Inv) + " min";
        }

        public static string FormatClock(double seconds)
        {
            int s = Math.Max(0, (int)seconds);
            if (s >= 3600)
                return (s / 3600) + ":" + ((s % 3600) / 60).ToString("00", Inv) + ":" + (s % 60).ToString("00", Inv);
            return (s / 60) + ":" + (s % 60).ToString("00", Inv);
        }

        public static string EtaText(double? eta)
        {
            if (eta == null) return "Estimating time left...";
            if (eta < 10) return "Under 10 s left";
            if (eta < 60) return "About " + (int)(5 * Math.Round(eta.Value / 5.0, MidpointRounding.AwayFromZero)) + " s left";
            return "About " + FormatDuration(eta.Value) + " left";
        }

        public static string ProgressLine(ProgressClock clock)
        {
            string elapsed = FormatClock(clock.Elapsed());
            if (clock.FinishedAt != null) return "Done in " + FormatDuration(clock.Elapsed());
            return EtaText(clock.Eta()) + "   |   " + elapsed + " elapsed";
        }

        public static bool ShouldRepaint(double? lastPaint, double now, int? lastPercent, int percent, double interval = 0.15)
        {
            if (lastPaint == null || percent != lastPercent) return true;
            return now - lastPaint.Value >= interval;
        }

        // ============================================================
        // theme
        // ============================================================

        public const string ThemeAuto = "auto", ThemeDark = "dark", ThemeLight = "light";
        public static readonly string[] ThemeCycle = { ThemeAuto, ThemeDark, ThemeLight };

        public static string NormaliseThemeMode(string mode)
        {
            mode = (mode ?? "").Trim().ToLowerInvariant();
            return ThemeCycle.Contains(mode) ? mode : ThemeAuto;
        }

        /// <summary>auto follows the Revit canvas; unknown canvas falls back to dark.</summary>
        public static string ResolveTheme(string mode, bool? canvasDark)
        {
            mode = NormaliseThemeMode(mode);
            if (mode == ThemeAuto)
            {
                if (canvasDark == null) return ThemeDark;
                return canvasDark.Value ? ThemeDark : ThemeLight;
            }
            return mode;
        }

        public static string NextThemeMode(string mode)
        {
            mode = NormaliseThemeMode(mode);
            return ThemeCycle[(Array.IndexOf(ThemeCycle, mode) + 1) % ThemeCycle.Length];
        }

        public static string ThemeChipLabel(string mode, string resolved)
        {
            mode = NormaliseThemeMode(mode);
            string shown = resolved == ThemeDark ? "Dark" : "Light";
            return mode == ThemeAuto ? "Auto " + shown : shown;
        }

        public static bool ColourIsDark(double red, double green, double blue)
        {
            return 0.2126 * red + 0.7152 * green + 0.0722 * blue < 128.0;
        }

        // ============================================================
        // modeless: the ExternalEvent queue
        // ============================================================

        public static bool RaiseKept(string status)
        {
            string text = (status ?? "").Trim();
            if (text.Contains(".")) text = text.Split('.').Last();
            return text == "Accepted" || text == "Pending";
        }

        public const string RaiseHelp = "Revit did not take the request ({0}). It is usually in the middle of something - " +
                                        "an edit mode, a sketch, or one of its own dialogs. Finish or cancel that in " +
                                        "Revit, then press the button again.";

        public const double WaitNoteSeconds = 20.0;

        public static string WaitingNote(double seconds)
        {
            if (seconds < WaitNoteSeconds) return "Waiting for Revit...";
            return "Still waiting for Revit after " + FormatDuration(seconds) + ". Finish or cancel what Revit is " +
                   "doing (an edit mode or a dialog), or press Esc here to cancel the request.";
        }

        // ============================================================
        // the shrink-to-bar drawer - pure arithmetic
        // ============================================================

        public const double DrawerSeconds = 0.28;
        public const int DrawerTickMs = 15;
        public const double DrawerGap = 8;        // clear of the taskbar
        public const double DrawerStackStep = 4;  // between stacked bars

        public static double EaseOut(double progress)
        {
            progress = Math.Max(0.0, Math.Min(1.0, progress));
            return 1.0 - Math.Pow(1.0 - progress, 3);
        }

        public static double Tween(double start, double end, double progress)
        {
            return start + (end - start) * EaseOut(progress);
        }

        /// <summary>Top of a parked bar on the work area (left, top, width, height).</summary>
        public static double ParkedTop((double Left, double Top, double Width, double Height) area, double barHeight, int stack = 0)
        {
            double bottom = area.Top + area.Height - DrawerGap;
            return bottom - barHeight - Math.Max(0, stack) * (barHeight + DrawerStackStep);
        }

        public static double ClampLeft((double Left, double Top, double Width, double Height) area, double left, double width)
        {
            double rightMost = area.Left + Math.Max(0.0, area.Width - width);
            return Math.Max(area.Left, Math.Min(left, rightMost));
        }

        public static bool BarMoved((double, double) parkedAt, (double, double) nowAt, double tolerance = 3.0)
        {
            return Math.Abs(parkedAt.Item1 - nowAt.Item1) > tolerance || Math.Abs(parkedAt.Item2 - nowAt.Item2) > tolerance;
        }

        public static (double Left, double Top, double Width, double Height) ReopenBounds(
            (double Left, double Top, double Width, double Height) restore, (double, double) parkedAt,
            (double, double) nowAt, double barHeight, (double Left, double Top, double Width, double Height) area)
        {
            if (!BarMoved(parkedAt, nowAt)) return restore;
            double newLeft = ClampLeft(area, nowAt.Item1, restore.Width);
            double newTop = nowAt.Item2 + barHeight - restore.Height;
            newTop = Math.Max(area.Top, Math.Min(newTop, area.Top + Math.Max(0.0, area.Height - restore.Height)));
            return (newLeft, newTop, restore.Width, restore.Height);
        }

        /// <summary>"toggle", "open", "swallow" or null (leave it to the window).</summary>
        public static string DrawerKeyAction(string key, bool ctrl, bool shift, bool parked, bool sliding)
        {
            if (sliding) return "swallow";
            if (ctrl && shift && key == "H") return "toggle";
            if (parked)
            {
                if (key == "Escape" || key == "Return" || key == "Enter" || key == "F11") return "open";
                return "swallow";
            }
            return null;
        }

        // ============================================================
        // debug report
        // ============================================================

        /// <summary>Everything worth knowing about a run, in one text file. Off: every call is a no-op.</summary>
        public sealed class DebugReport
        {
            public bool Enabled;
            public readonly List<string> Lines = new List<string>();
            public readonly string Path;
            public List<(string, object)> Pending = new List<(string, object)>();
            private readonly DateTime started = DateTime.Now;

            public DebugReport(bool enabled, string folder = null, string stamp = null)
            {
                Enabled = enabled;
                stamp = stamp ?? DateTime.Now.ToString("yyyyMMdd_HHmmss", Inv);
                Path = System.IO.Path.Combine(folder ?? AppDataDir(), "model_cleanup_debug_report_" + stamp + ".txt");
                if (Enabled)
                {
                    Line("RevoBIM " + ToolName + " v" + Version + " - debug report");
                    Line("Started " + started.ToString("yyyy-MM-dd HH:mm:ss", Inv));
                }
            }

            public void Line(string text = "")
            {
                if (Enabled) Lines.Add(text ?? "");
            }

            public void Section(string title)
            {
                if (!Enabled) return;
                Lines.Add("");
                Lines.Add(new string('=', 70));
                Lines.Add(title);
                Lines.Add(new string('=', 70));
            }

            public void Values(IEnumerable<(string, object)> pairs)
            {
                if (!Enabled) return;
                var list = pairs.ToList();
                int width = list.Count == 0 ? 0 : list.Max(p => p.Item1.Length);
                foreach (var pair in list) Lines.Add(pair.Item1.PadRight(width) + "  " + Show(pair.Item2));
            }

            public void Table(string[] headers, IEnumerable<object[]> rows, int limit = 20000)
            {
                if (!Enabled) return;
                var list = rows.ToList();
                Lines.Add(string.Join("\t", headers));
                foreach (var row in list.Take(limit))
                    Lines.Add(string.Join("\t", row.Select(c => Show(c).Replace("\t", " "))));
                if (list.Count > limit) Lines.Add("... " + (list.Count - limit) + " more rows");
            }

            public List<(string, object)> TakePending()
            {
                var items = Pending;
                Pending = new List<(string, object)>();
                return items;
            }

            public void Exception(string stage, string text)
            {
                if (!Enabled) return;
                Section("ERROR in " + stage);
                Lines.Add(text);
                Flush();
            }

            public bool Flush()
            {
                if (!Enabled) return false;
                try
                {
                    File.WriteAllText(Path, string.Join("\n", Lines) + "\n", new UTF8Encoding(false));
                    return true;
                }
                catch (Exception)
                {
                    return false;
                }
            }

            private static string Show(object value)
            {
                if (value == null) return "";
                if (value is bool) return (bool)value ? "True" : "False";
                var enumerable = value as System.Collections.IEnumerable;
                if (enumerable != null && !(value is string))
                    return "[" + string.Join(", ", enumerable.Cast<object>().Select(Show)) + "]";
                return Convert.ToString(value, Inv) ?? "";
            }
        }
    }

    /// <summary>What the tool knows about a model: read once, in API context, then passed around.</summary>
    public sealed class McuModelInfo
    {
        public string Title = "";
        public string Path = "";
        public bool Workshared;
        public bool Cloud;
        public string Central = "";
    }
}
