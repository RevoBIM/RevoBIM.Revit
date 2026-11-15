// Port of ps_config.py (Pro Sheets Exporter).
//
// Settings and per-project export profiles.
//
// Everything persists as plain key=value text under %APPDATA%\RevoBIM\, not
// JSON: the files stay readable and hand-editable, and the pyRevit and C#
// versions of the tool share them.
//
// A missing or damaged file falls back to the defaults KEY BY KEY, and keys
// from an older version are ignored rather than breaking the load. That is the
// whole reliability story here - a profile written by v1.0.0 must still open in
// v1.4.0 and vice versa.
//
// Two stores:
// * settings - one file, global to the user. Theme, the default printer, how
//   the window opens. Things that are a house standard rather than a job.
// * profiles - the whole export configuration, saved by name AGAINST THE
//   PROJECT, so each job keeps its own list and they are all still there next
//   time the model opens. This is the "template for the session" from the top
//   right of the window.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.ProSheets
{
    public static partial class PsConfig
    {
        private static readonly UTF8Encoding Utf8NoBom = new UTF8Encoding(false);
        private static readonly UTF8Encoding Utf8Strict = new UTF8Encoding(false, true);

        // ==================================================================
        // where things live
        // ==================================================================

        /// <summary>%APPDATA%\RevoBIM, created if it is not there yet.</summary>
        public static string AppdataRoot()
        {
            string bas;
            try
            {
                bas = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                if (string.IsNullOrEmpty(bas))
                    throw new InvalidOperationException();
            }
            catch (Exception)
            {
                bas = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            }
            string folder = Path.Combine(bas, "RevoBIM");
            try
            {
                if (!Directory.Exists(folder))
                    Directory.CreateDirectory(folder);
            }
            catch (Exception) { }
            return folder;
        }

        public static string SettingsPath()
        {
            return Path.Combine(AppdataRoot(), "pro_sheets_exporter.txt");
        }

        public static string ProfilesRoot()
        {
            string folder = Path.Combine(AppdataRoot(), "pro_sheets_profiles");
            try
            {
                if (!Directory.Exists(folder))
                    Directory.CreateDirectory(folder);
            }
            catch (Exception) { }
            return folder;
        }

        public static string ErrorPath()
        {
            string folder = Path.Combine(AppdataRoot(), "logs");
            try
            {
                if (!Directory.Exists(folder))
                    Directory.CreateDirectory(folder);
            }
            catch (Exception)
            {
                folder = AppdataRoot();
            }
            return Path.Combine(folder, "pro_sheets_exporter_last_error.txt");
        }

        internal static readonly Regex Unsafe = new Regex(@"[^A-Za-z0-9 _.\-]+");
        private static readonly Regex Whitespace = new Regex(@"\s+");

        /// <summary>A string that is safe as a file or folder name on Windows.</summary>
        public static string SafeName(string text, string fallback = "unnamed")
        {
            string cleaned = Unsafe.Replace(text ?? "", "_").Trim().Trim('.');
            cleaned = Whitespace.Replace(cleaned, " ");
            if (cleaned.Length == 0)
                return fallback;
            return cleaned.Length > 96 ? cleaned.Substring(0, 96) : cleaned;
        }

        /// <summary>
        /// A folder name identifying this project, so profiles do not mix.
        /// The model's file name is used where there is one; an unsaved model falls
        /// back to its title, and something with no title at all lands in a shared
        /// _unsaved bucket rather than failing.
        /// </summary>
        public static string ProjectKey(Document doc)
        {
            try
            {
                string path = doc?.PathName ?? "";
                if (path.Length > 0)
                    return SafeName(PsPaths.OsPathSplitExt(PsPaths.OsPathBaseName(path)).Root, "_unsaved");
            }
            catch (Exception) { }
            try
            {
                string title = doc?.Title ?? "";
                if (title.Length > 0)
                    return SafeName(title, "_unsaved");
            }
            catch (Exception) { }
            return "_unsaved";
        }

        public static string ProjectFolder(Document doc)
        {
            string folder = Path.Combine(ProfilesRoot(), ProjectKey(doc));
            try
            {
                if (!Directory.Exists(folder))
                    Directory.CreateDirectory(folder);
            }
            catch (Exception) { }
            return folder;
        }

        // ==================================================================
        // the key=value store
        // ==================================================================

        internal static string Encode(object value)
        {
            string text = value == null ? "" : PsModel.ToText(value);
            return text.Replace("\\", "\\\\").Replace("\r", "").Replace("\n", "\\n");
        }

        internal static string Decode(string text)
        {
            var output = new StringBuilder(text.Length);
            int index = 0;
            int length = text.Length;
            while (index < length)
            {
                char ch = text[index];
                if (ch == '\\' && index + 1 < length)
                {
                    char nxt = text[index + 1];
                    if (nxt == 'n')
                    {
                        output.Append('\n');
                        index += 2;
                        continue;
                    }
                    if (nxt == '\\')
                    {
                        output.Append('\\');
                        index += 2;
                        continue;
                    }
                }
                output.Append(ch);
                index++;
            }
            return output.ToString();
        }

        /// <summary>A file's text: UTF-8, falling back to latin-1 (as the Python reads it).</summary>
        internal static string ReadText(string path)
        {
            byte[] raw = File.ReadAllBytes(path);
            try
            {
                return Utf8Strict.GetString(raw);
            }
            catch (Exception)
            {
                return Encoding.GetEncoding(28591).GetString(raw);
            }
        }

        /// <summary>
        /// Every key=value pair in a file, as a dictionary. Never throws.
        /// A line with no = is a comment or damage and is skipped; the rest of
        /// the file still loads. That is deliberate - one bad line must not cost the
        /// user their whole profile.
        /// </summary>
        public static Dictionary<string, string> ReadStore(string path)
        {
            var found = new Dictionary<string, string>(StringComparer.Ordinal);
            try
            {
                if (string.IsNullOrEmpty(path) || !File.Exists(path))
                    return found;
                string text = ReadText(path);
                foreach (string raw in text.Replace("\r\n", "\n").Split('\n'))
                {
                    string line = raw.Trim();
                    if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal))
                        continue;
                    int eq = line.IndexOf('=');
                    if (eq < 0)
                        continue;
                    found[line.Substring(0, eq).Trim()] = Decode(line.Substring(eq + 1));
                }
            }
            catch (Exception) { }
            return found;
        }

        /// <summary>Write a dictionary out as key=value text. True when it landed.</summary>
        public static bool WriteStore(string path, IDictionary<string, string> values, string banner = null)
        {
            try
            {
                string folder = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder))
                    Directory.CreateDirectory(folder);
                var lines = new List<string>();
                if (!string.IsNullOrEmpty(banner))
                {
                    foreach (string line in banner.Split('\n'))
                        lines.Add("# " + line);
                }
                foreach (string key in values.Keys.OrderBy(k => k, StringComparer.Ordinal))
                    lines.Add(string.Format("{0}={1}", key, Encode(values[key])));
                string body = string.Join("\n", lines) + "\n";
                File.WriteAllBytes(path, Utf8NoBom.GetBytes(body));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ==================================================================
        // Python float()/int(float()) parsing, shared by the typed reads
        // ==================================================================

        /// <summary>Python float(text): surrounding whitespace allowed, inf/nan spelled out.</summary>
        public static bool TryPyFloat(string text, out double value)
        {
            string body = (text ?? "").Trim();
            string lower = body.ToLowerInvariant();
            string unsigned = lower.TrimStart('+', '-');
            bool negative = lower.StartsWith("-", StringComparison.Ordinal);
            if (lower.Length - unsigned.Length <= 1)
            {
                if (unsigned == "inf" || unsigned == "infinity")
                {
                    value = negative ? double.NegativeInfinity : double.PositiveInfinity;
                    return true;
                }
                if (unsigned == "nan")
                {
                    value = double.NaN;
                    return true;
                }
            }
            if (body.Length == 0)
            {
                value = 0.0;
                return false;
            }
            return double.TryParse(body, NumberStyles.Float, CultureInfo.InvariantCulture, out value);
        }

        /// <summary>Python int(float(text.strip())). Throws FormatException/OverflowException where Python raises.</summary>
        public static int PyInt(string text)
        {
            if (!TryPyFloat(text, out double number))
                throw new FormatException("could not convert string to float: " + text);
            if (double.IsNaN(number) || double.IsInfinity(number))
                throw new OverflowException("cannot convert float to integer");
            return checked((int)Math.Truncate(number));
        }

        // ==================================================================
        // typed reads, each falling back on its own
        // ==================================================================

        public static string GetText(IDictionary<string, string> store, string key, string @default = "")
        {
            if (store == null || !store.TryGetValue(key, out string value) || value == null)
                return @default;
            return value;
        }

        public static bool GetBool(IDictionary<string, string> store, string key, bool @default = false)
        {
            if (store == null || !store.TryGetValue(key, out string value) || value == null)
                return @default;
            string text = value.Trim().ToLowerInvariant();
            return text == "1" || text == "true" || text == "yes" || text == "on";
        }

        public static int GetInt(IDictionary<string, string> store, string key, int @default = 0)
        {
            if (store == null || !store.TryGetValue(key, out string value) || value == null)
                return @default;
            try
            {
                return PyInt(value.Trim());
            }
            catch (Exception)
            {
                return @default;
            }
        }

        public static double GetFloat(IDictionary<string, string> store, string key, double @default = 0.0)
        {
            if (store == null || !store.TryGetValue(key, out string value) || value == null)
                return @default;
            if (TryPyFloat(value.Trim(), out double number))
                return number;
            return @default;
        }

        /// <summary>A list written as a tab-separated value. Empty means an empty list.</summary>
        public static List<string> GetList(IDictionary<string, string> store, string key, IEnumerable<string> @default = null)
        {
            if (store == null || !store.TryGetValue(key, out string value) || value == null)
                return new List<string>(@default ?? Enumerable.Empty<string>());
            if (value.Trim().Length == 0)
                return new List<string>();
            return value.Split('\t').ToList();
        }

        public static string PutList<T>(IEnumerable<T> values)
        {
            return string.Join("\t", values.Select(v => PsModel.ToText(v)));
        }

        // ==================================================================
        // global settings
        // ==================================================================

        /// <summary>Where this project's hand-ticked register selection is kept.</summary>
        public static string RegisterPath(Document doc)
        {
            return Path.Combine(AppdataRoot(), "prosheets_register", ProjectKey(doc) + ".txt");
        }

        /// <summary>
        /// The sheet keys left out of the register by hand, or null if never set.
        /// Keys stay as the text they were written as (element id numbers).
        /// Kept as the ones left OUT, so a sheet added to the model after the
        /// list was saved starts included - a register that quietly misses new
        /// drawings is the failure worth designing against.
        /// </summary>
        public static HashSet<string> ReadRegisterExcluded(Document doc)
        {
            var store = ReadStore(RegisterPath(doc));
            if (!store.ContainsKey("excluded"))
                return null;
            return new HashSet<string>(GetList(store, "excluded").Where(key => key.Length > 0), StringComparer.Ordinal);
        }

        public static bool WriteRegisterExcluded(Document doc, IEnumerable<string> keys)
        {
            return WriteRegisterValue(doc, "excluded", keys.OrderBy(k => k, StringComparer.Ordinal).ToList());
        }

        /// <summary>Overload for element keys held as numbers; sorted numerically as Python sorts ints.</summary>
        public static bool WriteRegisterExcluded(Document doc, IEnumerable<long> keys)
        {
            return WriteRegisterValue(doc, "excluded",
                keys.OrderBy(k => k).Select(k => k.ToString(CultureInfo.InvariantCulture)).ToList());
        }

        /// <summary>The disciplines unticked on the register's tab strip, by name.</summary>
        public static HashSet<string> ReadRegisterSkipped(Document doc)
        {
            var store = ReadStore(RegisterPath(doc));
            return new HashSet<string>(GetList(store, "skip_tabs").Where(name => name.Length > 0), StringComparer.Ordinal);
        }

        public static bool WriteRegisterSkipped(Document doc, IEnumerable<string> names)
        {
            return WriteRegisterValue(doc, "skip_tabs", names.OrderBy(n => n, StringComparer.Ordinal).ToList());
        }

        /// <summary>{heading: "#RRGGBB"} as list entries, "heading=#RRGGBB".</summary>
        public static List<string> EncodeHeadingColours(IDictionary<string, string> colours)
        {
            if (colours == null)
                return new List<string>();
            return colours.OrderBy(item => item.Key, StringComparer.Ordinal)
                          .ThenBy(item => item.Value, StringComparer.Ordinal)
                          .Where(item => !string.IsNullOrEmpty(item.Key) && !string.IsNullOrEmpty(item.Value))
                          .Select(item => string.Format("{0}={1}", item.Key, item.Value))
                          .ToList();
        }

        /// <summary>
        /// The other way. A heading may itself hold "=": the colour is
        /// whatever follows the last one.
        /// </summary>
        public static Dictionary<string, string> DecodeHeadingColours(IEnumerable<string> entries)
        {
            var found = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (string entry in entries ?? Enumerable.Empty<string>())
            {
                string text = entry ?? "None";
                int mark = text.LastIndexOf('=');
                if (mark < 0)
                    continue;
                string name = text.Substring(0, mark);
                string colour = text.Substring(mark + 1);
                if (name.Length > 0 && colour.StartsWith("#", StringComparison.Ordinal) && colour.Length == 7)
                    found[name] = colour.ToUpperInvariant();
            }
            return found;
        }

        /// <summary>
        /// The colours picked for the register's headings in this project
        /// (1.52.0), by heading name.
        /// </summary>
        public static Dictionary<string, string> ReadHeadingColours(Document doc)
        {
            var store = ReadStore(RegisterPath(doc));
            return DecodeHeadingColours(GetList(store, "heading_colours"));
        }

        public static bool WriteHeadingColours(Document doc, IDictionary<string, string> colours)
        {
            return WriteRegisterValue(doc, "heading_colours", EncodeHeadingColours(colours));
        }

        /// <summary>One list in the project's register file, keeping the others.</summary>
        internal static bool WriteRegisterValue(Document doc, string key, IEnumerable<string> values)
        {
            string path = RegisterPath(doc);
            var store = ReadStore(path);
            store[key] = PutList(values);
            return WriteStore(path, store,
                              "RevoBIM PY - Pro Sheets Exporter\nDocument Register "
                              + "choices for this project: sheets left out by hand "
                              + "(element ids) and disciplines left out of the Excel "
                              + "export.");
        }

        /// <summary>
        /// The settings key holding where a driver saves.
        /// Per printer, because it is a fact about the driver and not about the
        /// job. Lives here rather than in a window so the setup dialog and the
        /// Format tab cannot drift into writing different keys.
        /// </summary>
        public static string StagingKey(string printer)
        {
            return "staging." + SafeName(printer, "printer");
        }

        // The BGL TIDP register's status legend, from 1.44.0: the suitability codes
        // the Issue Status row carries.
        public static readonly List<string> RegLegend = new List<string>
        {
            "S0 = WIP", "S1 = Coordination", "S2 = Information",
            "S3 = Review/Comment", "S4 = Stage Approval", "S5 = Authorisation",
        };

        // What they were from 1.24.0 to 1.43.0 (the RD9 sheet's), so the migration
        // can tell a default nobody touched from a list somebody typed.
        public static readonly List<string> Rd9Legend = new List<string>
        {
            "Pro = Proposal", "D = Draft", "P = Preliminary",
            "PL = Planning", "T = Tender", "CN = Contract",
            "C = Construction", "AB = As Built", "SK = Sketch",
        };

        public const string Rd9Title = "RD9 - Document Register & Issue Sheet";
        // 1.44.0's title. The form went back to the RD9 name in 1.45.0.
        public const string TidpTitle = "TIDP - Task Information Delivery Plan";
        public const string RegTitle = Rd9Title;
        // Where a sheet's scale comes from in the register: a text parameter on the
        // sheet or its title block, or Revit's own viewport scales.
        public const string ScaleParameter = "parameter";
        public const string ScaleRevit = "revit";

        public static readonly List<string> RegIssuedTo = new List<string>
        {
            "Client", "Architect", "Principal Designer",
            "Project Manager", "Structural Engineer", "Fire Engineer",
            "Main Contractor",
        };

        public static readonly Dictionary<string, string> SettingsDefaults = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            // 'theme' is the pre-1.10.0 key. The chip used to write the resolved
            // palette into it, so a value there cannot be told apart from a
            // deliberate pin - which is why 1.10.0 reads a new key instead and
            // lets everybody start on follow again.
            { "theme", "follow" },          // legacy, no longer written
            { "theme_mode", "follow" },     // follow | dark | light
            { "default_printer", "" },      // blank means Revit's own PDF export
            { "window_width", "1240" },
            { "window_height", "820" },
            { "last_profile", "" },
            { "remember_last_profile", "1" },
            { "open_folder_after_export", "1" },
            { "report_always", "1" },
            { "debug", "0" },
            { "suppress_dialogs", "1" },
            { "settle_ms", "250" },
            { "column_widths", "" },
            // First run. Until this is set the setup window opens with the tool:
            // every setting it asks about is per machine, and a template that
            // works on one desk fails on the next with nothing to show for it.
            { "setup_done", "0" },
            { "default_root", "" },
            // Revit's own exporter is the house default from 1.16.0. A print
            // driver is opt in, per machine, and a template asking for one does
            // not override this.
            { "prefer_native_pdf", "1" },
            // What this office calls the two parameters the Selection page
            // shows by default and sorts by. Names, not ids, because they are
            // shared parameters and a different client's model calls them
            // something else. Setup asks; blank means "this project has none".
            { "param_series", "BGL_Sheet Series" },
            { "param_discipline", "BGL_Sheet Discipline" },
            // The Document Register's Excel form. Lists are tab separated, one
            // entry per line in the settings window. The logo is copied into
            // %APPDATA%\RevoBIM when it is chosen, so the form keeps it after the
            // original is moved or the network drive is not there.
            { "reg_title", RegTitle },
            { "reg_logo", "" },
            { "reg_client_logo", "" },
            { "reg_legend", string.Join("\t", RegLegend) },
            { "reg_issued_to", string.Join("\t", RegIssuedTo) },
            { "reg_footer", "" },
            { "reg_paper", "A4 portrait" },
            // The heading of the register's current revision column - orange, just
            // before the issues from 1.44.0. Blank leaves the column off.
            { "reg_snapshot", "Current Rev" },
            // 1.44.0: the sheet parameter each issue's status is filled from (the
            // Revision Manager's Issue Status column), and where the Scale column
            // comes from - a text parameter, read from the sheet then its title
            // block, or Revit's own viewport scales.
            { "reg_status_param", "BGL_Sheet Status" },
            { "reg_scale_mode", ScaleParameter },
            { "reg_scale_param", "BGL_Title Block Scale Text" },
            // The Revision Manager, opened from its own button, opens again after
            // Apply so the next change can follow straight on.
            { "rev_reopen", "1" },
            // The order the manager's columns were last dragged into: fields,
            // comma separated. Blank is the first order.
            { "rev_column_order", "" },
            // 1.34.0: every Sheet series cell opens expanded, listing them all
            { "rev_series_open", "1" },
            // 1.38.0: the modeless manager follows the selection in Revit - pick a
            // revision cloud in a view and the list goes to its revision.
            { "rev_follow_selection", "1" },
            // 1.39.0: the Pro Sheets window's size, - and + in its header.
            { "ui_scale", "1" },
            // The register tab's own state between sessions.
            { "reg_add_to_export", "0" },
            { "reg_last_set", "" },
            { "reg_show", "all" },
            // Show only the revision columns the drawings on screen carry, and
            // write only those a worksheet's drawings carry. On by default.
            { "reg_hide_unused", "1" },
            // Bumped when a default changes in a way an existing settings file
            // would otherwise keep overriding. See Migrate().
            { "settings_version", "6" },
        };

        // The version this build's defaults belong to.
        public const int SettingsVersion = 6;

        // What the register defaults were before 1.24.0, so the migration can tell
        // a default nobody touched from a list somebody typed.
        public static readonly Dictionary<string, string> OldRegDefaults = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "reg_title", "Document Register & Issue Sheet" },
            { "reg_legend", string.Join("\t", new[] { "P - Preliminary", "I - Information",
                                                       "T - Tender", "C - Construction",
                                                       "AB - As Built" }) },
            { "reg_issued_to", string.Join("\t", new[] { "Client", "Architect",
                                                          "Structural Engineer",
                                                          "Main Contractor", "File" }) },
            { "reg_paper", "A3" },
        };

        /// <summary>The global settings, loaded once and saved on change.</summary>
        public class Settings
        {
            public Dictionary<string, string> Store { get; set; }
            public bool Migrated { get; set; }

            public Settings()
            {
                Store = new Dictionary<string, string>(SettingsDefaults, StringComparer.Ordinal);
                foreach (var entry in ReadStore(SettingsPath()))
                    Store[entry.Key] = entry.Value;
                Migrated = Migrate();
            }

            /// <summary>
            /// Bring an older settings file up to this build's defaults.
            /// A default only applies where the file says nothing, so changing
            /// one does nothing for anybody who already has the tool - and a
            /// machine that was pointed at a print driver back when the tool
            /// chose one for itself would keep going to that driver forever.
            /// That is the whole reason this exists.
            /// Returns whether anything changed, so the caller can save.
            /// </summary>
            public bool Migrate()
            {
                int found;
                string raw = GetText(Store, "settings_version", "1");
                if (string.IsNullOrEmpty(raw))
                    raw = "1";
                if (!int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out found))
                    found = 1;
                if (found >= SettingsVersion)
                    return false;

                // To 2: Revit's own exporter becomes the default, and a driver
                // chosen automatically by 1.9.1 to 1.13.0 is let go of. Nobody
                // picked those deliberately; the tool picked them, and on every
                // machine they were tried on they wrote nothing.
                if (found < 2)
                {
                    Store["default_printer"] = "";
                    Store["prefer_native_pdf"] = "1";
                }

                // To 3: runs are quiet by default. Anybody who had turned this
                // on already keeps it on; the change is for everybody who never
                // touched it and was getting a confirmation every export.
                if (found < 3)
                    Store["suppress_dialogs"] = "1";

                // To 4: Revit's own PDF exporter again, for everybody. Setup wrote a
                // driver into default_printer whenever a driver option was clicked
                // and from then on every run went to it. And the register's
                // defaults become the RD9 issue sheet's, where they were never
                // changed: a list somebody typed is kept as typed.
                if (found < 4)
                {
                    Store["default_printer"] = "";
                    Store["prefer_native_pdf"] = "1";
                    foreach (var entry in OldRegDefaults)
                    {
                        if (GetText(Store, entry.Key, entry.Value) == entry.Value)
                            Store[entry.Key] = SettingsDefaults[entry.Key];
                    }
                    string paper = GetText(Store, "reg_paper", "").Trim();
                    if (paper.Length > 0
                        && paper.Split((char[])null, StringSplitOptions.RemoveEmptyEntries).Length == 1)
                        Store["reg_paper"] = string.Format("{0} portrait", paper);
                }

                // To 5: the register becomes the BGL TIDP form - its title, the S0
                // to S5 legend, and the current revision column called Current Rev.
                // Each only where the RD9 default was never changed.
                if (found < 5)
                {
                    var swaps = new[]
                    {
                        ("reg_title", Rd9Title, TidpTitle),
                        ("reg_legend", string.Join("\t", Rd9Legend), string.Join("\t", RegLegend)),
                        ("reg_snapshot", "Asite Snapshot", "Current Rev"),
                    };
                    foreach (var (key, old, @new) in swaps)
                    {
                        if (GetText(Store, key, old) == old)
                            Store[key] = @new;
                    }
                }

                // To 6: the title back to the RD9 name, where 1.44.0 set it and
                // nobody has changed it since.
                if (found < 6)
                {
                    if (GetText(Store, "reg_title", TidpTitle) == TidpTitle)
                        Store["reg_title"] = Rd9Title;
                }

                Store["settings_version"] = SettingsVersion.ToString(CultureInfo.InvariantCulture);
                return true;
            }

            public string Text(string key, string @default = null)
            {
                if (@default == null)
                    @default = SettingsDefaults.TryGetValue(key, out string fallback) ? fallback : "";
                return GetText(Store, key, @default);
            }

            public bool Flag(string key, bool? @default = null)
            {
                bool fallback = @default ?? GetBool(SettingsDefaults, key, false);
                return GetBool(Store, key, fallback);
            }

            public int Number(string key, int? @default = null)
            {
                int fallback = @default ?? GetInt(SettingsDefaults, key, 0);
                return GetInt(Store, key, fallback);
            }

            /// <summary>Stores the value as text (Python u'{0}'.format: True/False for bools).</summary>
            public void Set(string key, object value)
            {
                Store[key] = PsModel.ToText(value);
            }

            public bool Save()
            {
                return WriteStore(SettingsPath(), Store,
                                  "RevoBIM PY - Pro Sheets Exporter\nGlobal settings. Safe to edit by hand.");
            }
        }

        // ==================================================================
        // profiles
        // ==================================================================

        public static readonly Dictionary<string, string> ProfileDefaults = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            // what is being exported
            { "mode", "sheets" },                 // sheets | views
            { "formats", "pdf" },                 // tab separated: pdf dwg nwc ifc
            { "selected", "" },                   // tab separated sheet numbers / view names

            // PDF
            { "pdf.printer", "" },                // blank = Revit's own PDF export
            { "pdf.staging", "" },                // a driver that saves where it likes
            { "pdf.placement", "center" },        // center | offset
            { "pdf.margin", "nomargin" },         // nomargin | printerlimit | usermargin
            { "pdf.offset_x", "0.0" },
            { "pdf.offset_y", "0.0" },
            { "pdf.zoom_mode", "zoom" },          // fit | zoom
            { "pdf.zoom", "100" },
            { "pdf.hidden_line", "vector" },      // vector | raster
            { "pdf.raster_quality", "high" },     // low | medium | high | presentation
            { "pdf.colors", "color" },            // color | grayscale | blackline
            { "pdf.view_links_blue", "1" },
            { "pdf.hide_ref_planes", "1" },
            { "pdf.hide_unreferenced_tags", "1" },
            { "pdf.hide_scope_boxes", "1" },
            { "pdf.hide_crop_boundaries", "1" },
            { "pdf.replace_halftone", "0" },
            { "pdf.mask_coincident", "0" },
            { "pdf.combine", "0" },
            { "pdf.keep_paper_size", "1" },
            { "pdf.order", "" },                  // tab separated keys, the combine order

            // DWG
            { "dwg.setup", "" },                  // an export setup saved in the model
            { "dwg.external_refs", "0" },         // off = links bound into the DWG
            { "dwg.shared_coords", "1" },
            { "dwg.version", "default" },
            { "dwg.export_views_on_sheet", "0" },

            // NWC. The defaults are Revit's own Navisworks export defaults, which
            // are also what the reference screenshots show.
            { "nwc.parts", "0" },
            { "nwc.element_ids", "1" },
            { "nwc.parameters", "all" },          // all | elements | none
            { "nwc.properties", "0" },
            { "nwc.linked_files", "0" },
            { "nwc.room_as_attribute", "1" },
            { "nwc.urls", "1" },
            { "nwc.coordinates", "shared" },      // shared | internal
            { "nwc.divide_levels", "1" },
            { "nwc.room_geometry", "1" },
            { "nwc.find_materials", "1" },
            { "nwc.linked_cad", "1" },
            { "nwc.lights", "0" },
            { "nwc.faceting", "1" },

            // IFC
            { "ifc.version", "IFC2x3CV2" },
            { "ifc.file_type", "ifc" },           // ifc | ifcxml | ifczip | ifcxmlzip
            { "ifc.phase", "" },                  // blank = the default phase
            // The phase's element id, resolved against this model when the run
            // starts. The name above is what travels in a template; an id from
            // another model would point at whatever happens to share the number.
            { "ifc.phase_id", "" },
            { "ifc.space_boundaries", "0" },      // 0 | 1 | 2
            { "ifc.origin", "shared" },           // shared | project | internal | survey
            { "ifc.split_by_level", "0" },
            { "ifc.steel", "1" },
            { "ifc.linked_files", "none" },       // none | separate
            { "ifc.export_2d", "0" },
            { "ifc.visible_only", "1" },
            { "ifc.rooms_in_3d", "0" },
            { "ifc.detail", "low" },              // extralow | low | medium | high
            { "ifc.revit_psets", "0" },
            { "ifc.common_psets", "1" },
            { "ifc.base_quantities", "0" },
            { "ifc.material_psets", "0" },
            { "ifc.schedule_psets", "0" },
            { "ifc.specific_schedules", "0" },
            { "ifc.user_psets", "0" },
            { "ifc.type_properties", "0" },
            { "ifc.user_psets_file", "" },
            { "ifc.parameter_map", "0" },
            { "ifc.parameter_map_file", "" },
            { "ifc.parts_as_elements", "0" },
            { "ifc.solid_model", "0" },
            { "ifc.active_view_geometry", "0" },
            { "ifc.family_type_reference", "0" },
            { "ifc.room_boundary_2d", "0" },
            { "ifc.site_elevation", "0" },
            { "ifc.store_guid", "0" },
            { "ifc.bounding_box", "0" },
            { "ifc.triangulation", "0" },
            { "ifc.type_name_only", "0" },
            { "ifc.visible_name", "0" },

            // naming
            { "name.rule_count", "2" },
            { "name.rule.1.param", "Sheet Number" },
            { "name.rule.1.prefix", "" },
            { "name.rule.1.suffix", "" },
            { "name.rule.1.sep", "-" },
            { "name.rule.2.param", "Sheet Name" },
            { "name.rule.2.prefix", "" },
            { "name.rule.2.suffix", "" },
            { "name.rule.2.sep", "" },

            // where it goes
            { "out.root", "" },
            // The house layout: project, then a stamp for this issue, then the
            // sheet series. A token that resolves to nothing becomes _unset
            // rather than collapsing the level, so a model without
            // BGL_Sheet Series still lands somewhere findable.
            { "out.tokens", "{Project Name}\\{Year}-{Month}-{Day}_{Hour}_{Minute}\\{BGL_Sheet Series}" },
            { "out.folder_per_format", "1" },
            { "out.overwrite", "1" },

            // filters
            { "filter.sheet_set", "" },
            { "filter.active_only", "0" },
            { "filter.search", "" },
            { "cols", "" },                       // the whole Selection column order
            { "sort.stack", "" },
            { "sort.grouped", "1" },              // colour and collapse runs of matching values
            { "colwidths", "" },
            { "win.width", "" },
            { "win.height", "" },

            // How the run behaves. Kept in the template as well as globally: the
            // global value is the default when no template is loaded, the template
            // wins once one is. Quiet by default.
            { "run.suppress_dialogs", "1" },
            { "run.open_folder", "1" },
            { "run.debug", "0" },
        };

        // ==================================================================
        // template bundles
        //
        // One file, any number of templates, so a house standard can be handed round
        // rather than rebuilt per machine. Same plain key=value text as everything
        // else, with a banner line starting each template.
        // ==================================================================

        public const string BundleExtension = ".rbtpl";
        public const string BundleMarker = "@template=";
        public const string BundleHeader = "RevoBIM PY - Pro Sheets Exporter template bundle\n"
                                           + "One or more templates. Each begins with a line reading\n"
                                           + "@template=<name>. Safe to edit by hand.";

        /// <summary>Write {name: values} out as one file. True when it landed.</summary>
        public static bool WriteBundle(string path, IDictionary<string, Dictionary<string, string>> templates)
        {
            try
            {
                var lines = new List<string>();
                foreach (string line in BundleHeader.Split('\n'))
                    lines.Add("# " + line);
                foreach (string name in templates.Keys.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal))
                {
                    var values = templates[name];
                    lines.Add("");
                    lines.Add(string.Format("{0}{1}", BundleMarker, name));
                    foreach (string key in values.Keys.OrderBy(k => k, StringComparer.Ordinal))
                        lines.Add(string.Format("{0}={1}", key, Encode(values[key])));
                }
                string body = string.Join("\n", lines) + "\n";
                File.WriteAllBytes(path, Utf8NoBom.GetBytes(body));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Read a bundle back as {name: values}. Never throws.
        /// A file with no @template line at all is treated as a single template
        /// named after the file, so a plain profile saved from %APPDATA% can be
        /// handed to somebody and still load.
        /// </summary>
        public static Dictionary<string, Dictionary<string, string>> ReadBundle(string path)
        {
            var found = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
            try
            {
                if (string.IsNullOrEmpty(path) || !File.Exists(path))
                    return found;
                string text = ReadText(path);

                string current = null;
                var loose = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (string raw in text.Replace("\r\n", "\n").Split('\n'))
                {
                    string line = raw.Trim();
                    if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal))
                        continue;
                    if (line.StartsWith(BundleMarker, StringComparison.Ordinal))
                    {
                        current = line.Substring(BundleMarker.Length).Trim();
                        if (current.Length == 0)
                            current = "Unnamed";
                        if (!found.ContainsKey(current))
                            found[current] = new Dictionary<string, string>(StringComparer.Ordinal);
                        continue;
                    }
                    int eq = line.IndexOf('=');
                    if (eq < 0)
                        continue;
                    var target = current != null ? found[current] : loose;
                    target[line.Substring(0, eq).Trim()] = Decode(line.Substring(eq + 1));
                }

                if (found.Count == 0 && loose.Count > 0)
                {
                    string name = SafeName(PsPaths.OsPathSplitExt(PsPaths.OsPathBaseName(path)).Root, "Imported");
                    found[name] = loose;
                }
            }
            catch (Exception) { }
            return found;
        }

        /// <summary>
        /// A name nothing else is using, adding (1), (2) and so on.
        /// Merging is the common case and a clash is not an error - somebody has
        /// two versions of "Standard issue" and wants both, or they would have
        /// chosen to replace.
        /// </summary>
        public static string UniqueTemplateName(IEnumerable<string> taken, string name)
        {
            var lowered = new HashSet<string>((taken ?? Enumerable.Empty<string>()).Select(n => (n ?? "None").ToLowerInvariant()),
                                              StringComparer.Ordinal);
            string bas = (name ?? "None").Trim();
            if (bas.Length == 0)
                bas = "Unnamed";
            if (!lowered.Contains(bas.ToLowerInvariant()))
                return bas;
            int index = 1;
            while (index < 500)
            {
                string candidate = string.Format("{0} ({1})", bas, index);
                if (!lowered.Contains(candidate.ToLowerInvariant()))
                    return candidate;
                index++;
            }
            return bas;
        }

        /// <summary>Every profile saved against this project, alphabetically.</summary>
        public static List<string> ProfileNames(Document doc)
        {
            var names = new List<string>();
            try
            {
                string folder = ProjectFolder(doc);
                foreach (string full in Directory.GetFileSystemEntries(folder))
                {
                    string entry = Path.GetFileName(full);
                    if (entry.ToLowerInvariant().EndsWith(".txt", StringComparison.Ordinal))
                        names.Add(PsPaths.OsPathSplitExt(entry).Root);
                }
            }
            catch (Exception) { }
            return names.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        public static string ProfilePath(Document doc, string name)
        {
            return Path.Combine(ProjectFolder(doc), SafeName(name, "profile") + ".txt");
        }

        /// <summary>A profile merged over the defaults, so missing keys never bite.</summary>
        public static Dictionary<string, string> LoadProfile(Document doc, string name)
        {
            var values = new Dictionary<string, string>(ProfileDefaults, StringComparer.Ordinal);
            if (!string.IsNullOrEmpty(name))
            {
                foreach (var entry in ReadStore(ProfilePath(doc, name)))
                    values[entry.Key] = entry.Value;
            }
            return values;
        }

        public static bool SaveProfile(Document doc, string name, IDictionary<string, string> values)
        {
            string banner = string.Format("RevoBIM PY - Pro Sheets Exporter\n"
                                          + "Export profile \"{0}\" for project \"{1}\".\n"
                                          + "Safe to edit by hand. Unknown keys are ignored on load.",
                                          name, ProjectKey(doc));
            return WriteStore(ProfilePath(doc, name), values, banner);
        }

        // ==================================================================
        // IFC setups
        //
        // Kept apart from the templates and not per project. An IFC setup is a
        // house standard - the same one is wanted on every job - whereas a
        // template is about one project's folders and sheet list.
        // ==================================================================

        public const string IfcSetupExtension = ".rbifc";

        public static string IfcSetupsRoot()
        {
            string folder = Path.Combine(AppdataRoot(), "ifc_setups");
            try
            {
                if (!Directory.Exists(folder))
                    Directory.CreateDirectory(folder);
            }
            catch (Exception) { }
            return folder;
        }

        public static List<string> IfcSetupNames()
        {
            var names = new List<string>();
            try
            {
                foreach (string full in Directory.GetFileSystemEntries(IfcSetupsRoot()))
                {
                    string entry = Path.GetFileName(full);
                    if (entry.ToLowerInvariant().EndsWith(IfcSetupExtension, StringComparison.Ordinal))
                        names.Add(PsPaths.OsPathSplitExt(entry).Root);
                }
            }
            catch (Exception) { }
            return names.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        public static string IfcSetupPath(string name)
        {
            return Path.Combine(IfcSetupsRoot(), SafeName(name, "setup") + IfcSetupExtension);
        }

        /// <summary>The ifc.* keys held in a setup file (the caller merges them over the defaults).</summary>
        public static Dictionary<string, string> ReadIfcSetup(string path)
        {
            var values = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var entry in ReadStore(path))
            {
                if (entry.Key.StartsWith("ifc.", StringComparison.Ordinal))
                    values[entry.Key] = entry.Value;
            }
            return values;
        }

        public static bool WriteIfcSetup(string path, IDictionary<string, string> values)
        {
            var keep = values.Where(entry => (entry.Key ?? "").StartsWith("ifc.", StringComparison.Ordinal))
                             .ToDictionary(entry => entry.Key, entry => entry.Value, StringComparer.Ordinal);
            string banner = "RevoBIM PY - Pro Sheets Exporter\n"
                            + "IFC export setup. Safe to edit by hand.\n"
                            + "Unknown keys are ignored on load.";
            return WriteStore(path, keep, banner);
        }

        public static bool DeleteProfile(Document doc, string name)
        {
            try
            {
                string path = ProfilePath(doc, name);
                if (File.Exists(path))
                {
                    File.Delete(path);
                    return true;
                }
            }
            catch (Exception) { }
            return false;
        }

        /// <summary>A fresh profile dictionary, untouched by anything on disk.</summary>
        public static Dictionary<string, string> Defaults()
        {
            return new Dictionary<string, string>(ProfileDefaults, StringComparer.Ordinal);
        }
    }
}
