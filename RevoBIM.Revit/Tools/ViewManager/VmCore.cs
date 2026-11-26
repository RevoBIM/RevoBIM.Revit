using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ViewManager
{
    /// <summary>
    /// View Manager - the rules that need no Revit: abbreviations and naming, the settings file, palettes, the
    /// View Reference Manager's rows, staged edits, filter and sort. Port of the top of script.py (version 1.13.1).
    /// </summary>
    public static class VmCore
    {
        public const string Version = "1.13.1";
        public const string ToolName = "View Manager";

        public const string NamePrefix = "DEP_";
        public const string NameSeparator = "_";
        public const int ChunkSize = 25;
        public const string CreateSeparator = "_";
        public const string DefaultTemplateFamily = "FloorPlan";

        // ---------------------------------------------------------------- build / files --

        public static string BuildInfo()
        {
            try
            {
                Assembly assembly = typeof(VmCore).Assembly;
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
                return "View Manager " + Version + " | add-in " + info + " | built " + date + " | Revit " + revit + " build | " + path + " (written " + written + ")";
            }
            catch (Exception err)
            {
                return "build info unavailable: " + err.Message;
            }
        }

        /// <summary>House settings are global - an abbreviation is a standard, not a job.</summary>
        public static string SettingsDir()
        {
            string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
            try { Directory.CreateDirectory(folder); } catch (Exception) { }
            return folder;
        }

        public static string LogDir()
        {
            string folder = Path.Combine(SettingsDir(), "logs");
            try { Directory.CreateDirectory(folder); } catch (Exception) { }
            return folder;
        }

        public static string SettingsPath() { return Path.Combine(SettingsDir(), "view_manager_settings.txt"); }
        public static string ErrorPath() { return Path.Combine(LogDir(), "view_manager_last_error.txt"); }
        public static string DebugPath() { return Path.Combine(LogDir(), "view_manager_debug.txt"); }
        public static string RulesetsPath() { return Path.Combine(SettingsDir(), "view_manager_title_rulesets.txt"); }

        public static string Describe(Exception ex)
        {
            if (ex == null) return "Exception: <no message>";
            string text = (ex.Message ?? "").Trim().Replace("\r", " ").Replace("\n", " ");
            return ex.GetType().Name + ": " + (text.Length == 0 ? "<no message>" : text);
        }

        public static string PrettyTime(double milliseconds)
        {
            double seconds = milliseconds / 1000.0;
            if (seconds < 1.0) return milliseconds.ToString("0") + "ms";
            if (seconds < 60.0) return seconds.ToString("0.0") + "s";
            return ((int)(seconds / 60)).ToString() + "m " + (seconds % 60).ToString("0") + "s";
        }

        // ---------------------------------------------------------------- abbreviations --

        private static readonly KeyValuePair<string[], string>[] TemplateAbbreviations =
        {
            Kw("FA", "fire alarm", "firealarm"),
            Kw("LTG-EXT", "ext lighting", "external lighting"),
            Kw("LTG", "lighting"),
            Kw("DOM", "water service", "domestic", "dhw", "mcws"),
            Kw("HTG", "hvac pipework", "heating", "lthw", "mthw"),
            Kw("CONT", "containment", "cable tray", "trunking"),
            Kw("VENT", "ventilation", "hvac", "ducting", "ductwork"),
            Kw("DRN", "drainage", "soil", "waste"),
            Kw("PWR", "power", "small power"),
            Kw("SEC", "security", "cctv"),
        };

        private static KeyValuePair<string[], string> Kw(string abbr, params string[] words)
        {
            return new KeyValuePair<string[], string>(words, abbr);
        }

        private static readonly string[][] LevelAliases =
        {
            new[] { "roof", "RF" }, new[] { "ground", "00" }, new[] { "mezzanine", "MZ" },
            new[] { "basement", "B1" }, new[] { "podium", "PD" }, new[] { "plant", "PL" },
        };

        /// <summary>One name&lt;TAB&gt;abbreviation file. Template abbreviations are global; level and scope box ones are per project.</summary>
        public sealed class AbbrevStore
        {
            public readonly string FileName;
            public readonly bool PerProject;
            public readonly Dictionary<string, string> Items = new Dictionary<string, string>();
            public readonly string What;

            public AbbrevStore(string fileName, bool perProject, string what)
            {
                FileName = fileName;
                PerProject = perProject;
                What = what;
            }

            public string Path()
            {
                string folder = SettingsDir();
                if (PerProject)
                {
                    folder = System.IO.Path.Combine(folder, "view_manager_projects", ProjectKey());
                    try { Directory.CreateDirectory(folder); } catch (Exception) { }
                }
                return System.IO.Path.Combine(folder, FileName);
            }

            public void Load()
            {
                Items.Clear();
                try
                {
                    string path = Path();
                    if (!File.Exists(path)) return;
                    foreach (string raw in File.ReadAllLines(path, Encoding.UTF8))
                    {
                        string line = raw.TrimEnd('\r', '\n');
                        if (line.Length == 0 || line.StartsWith("#") || line.IndexOf('\t') < 0) continue;
                        int tab = line.IndexOf('\t');
                        string name = line.Substring(0, tab).Trim();
                        string abbr = line.Substring(tab + 1).Trim();
                        if (name.Length > 0 && abbr.Length > 0) Items[name] = abbr;
                    }
                }
                catch (Exception)
                {
                }
            }

            /// <summary>(saved, note) - the caller says so rather than failing quietly.</summary>
            public bool Save(out string note)
            {
                note = "";
                try
                {
                    var sb = new StringBuilder();
                    sb.Append("# RevoBIM PY - View Manager\n");
                    sb.Append("# " + What + "<TAB>abbreviation. Edited from the tool's Settings window.\n");
                    var names = Items.Keys.ToList();
                    names.Sort(string.CompareOrdinal);
                    foreach (string name in names) sb.Append(name + "\t" + Items[name] + "\n");
                    File.WriteAllText(Path(), sb.ToString(), new UTF8Encoding(false));
                    return true;
                }
                catch (Exception ex)
                {
                    note = Describe(ex);
                    return false;
                }
            }
        }

        /// <summary>Set by the window: the central file name (or the file name) of the project being worked on.</summary>
        public static Func<string> ProjectKeyProvider;

        public static string ProjectKey()
        {
            string name = "";
            try { if (ProjectKeyProvider != null) name = ProjectKeyProvider() ?? ""; } catch (Exception) { }
            name = name.Replace("/", "\\");
            int slash = name.LastIndexOf('\\');
            if (slash >= 0) name = name.Substring(slash + 1);
            try { name = Path.GetFileNameWithoutExtension(name); } catch (Exception) { }
            name = Regex.Replace(name, "[<>:\"/\\\\|?*]+", "-").Trim(' ', '.');
            return name.Length == 0 ? "Untitled" : name;
        }

        public static readonly AbbrevStore TemplateStore = new AbbrevStore("view_manager_abbreviations.txt", false, "View template name");
        public static readonly AbbrevStore LevelStore = new AbbrevStore("level_abbreviations.txt", true, "Level name");
        public static readonly AbbrevStore BoxStore = new AbbrevStore("scope_box_abbreviations.txt", true, "Scope box name");

        public static Dictionary<string, string> Overrides { get { return TemplateStore.Items; } }
        public static Dictionary<string, string> LevelOverrides { get { return LevelStore.Items; } }
        public static Dictionary<string, string> BoxOverrides { get { return BoxStore.Items; } }

        public static void LoadOverrides()
        {
            TemplateStore.Load();
            LevelStore.Load();
            BoxStore.Load();
        }

        // ---------------------------------------------------------------- naming --

        private static readonly char[] InvalidChars = "{}[]|;<>?`~:\\/*\"".ToCharArray();

        public static string Sanitise(string name)
        {
            string output = name ?? "";
            foreach (char ch in InvalidChars) output = output.Replace(ch, '-');
            output = output.Trim();
            return output.Length == 0 ? "View" : output;
        }

        /// <summary>Longest alphabetic word, used when nothing in the table matches.</summary>
        public static string FallbackAbbr(string name)
        {
            string best = null;
            foreach (Match m in Regex.Matches(name ?? "", "[A-Za-z]{3,}"))
                if (best == null || m.Value.Length > best.Length) best = m.Value;
            if (best != null) return (best.Length > 4 ? best.Substring(0, 4) : best).ToUpperInvariant();
            string letters = Regex.Replace(name ?? "", "[^A-Za-z]", "");
            string four = letters.Length > 4 ? letters.Substring(0, 4) : letters;
            return four.Length == 0 ? "VIEW" : four.ToUpperInvariant();
        }

        /// <summary>(abbreviation, true when it came from a rule rather than the fallback).</summary>
        public static string AbbreviateTemplate(string name, out bool matched)
        {
            string source;
            string abbr = AbbreviateDetail(name, out source);
            matched = source != "fallback";
            return abbr;
        }

        public static string AbbreviateTemplate(string name)
        {
            bool matched;
            return AbbreviateTemplate(name, out matched);
        }

        /// <summary>The abbreviation and its source: override, keyword or fallback. A hand-set one beats the keywords.</summary>
        public static string AbbreviateDetail(string name, out string source)
        {
            string key = (name ?? "").Trim();
            string over;
            if (Overrides.TryGetValue(key, out over))
            {
                source = "override";
                return over;
            }
            string low = key.ToLowerInvariant();
            foreach (KeyValuePair<string[], string> row in TemplateAbbreviations)
                foreach (string kw in row.Key)
                    if (low.Contains(kw))
                    {
                        source = "keyword";
                        return row.Value;
                    }
            source = "fallback";
            return FallbackAbbr(name);
        }

        public static string AbbreviateLevel(string name)
        {
            string source;
            return LevelAbbrDetail(name, out source);
        }

        public static string LevelAbbrDetail(string name, out string source)
        {
            string key = (name ?? "").Trim();
            string over;
            if (LevelOverrides.TryGetValue(key, out over))
            {
                source = "override";
                return over;
            }
            source = "rule";
            return LevelRule(name);
        }

        public static string BoxAbbrDetail(string name, out string source)
        {
            string key = (name ?? "").Trim();
            string over;
            if (BoxOverrides.TryGetValue(key, out over))
            {
                source = "override";
                return over;
            }
            source = "name";
            return key;
        }

        public static string BoxAbbr(string name)
        {
            string source;
            return BoxAbbrDetail(name, out source);
        }

        /// <summary>Level 0 -> L00, Level 1 -> L01, Roof -> LRF, 41AM_F02A -> L02A. An explicit floor token wins over any other number.</summary>
        public static string LevelRule(string name)
        {
            string raw = (name ?? "").Trim();

            Match match = Regex.Match(raw, "(?:^|[^A-Za-z0-9])[FL](\\d{1,2})([A-Za-z]?)(?![A-Za-z0-9])", RegexOptions.IgnoreCase);
            if (match.Success)
                return "L" + int.Parse(match.Groups[1].Value).ToString("00") + match.Groups[2].Value.ToUpperInvariant();

            match = Regex.Match(raw, "(?:^|[^A-Za-z0-9])(?:level|lvl|floor)[\\s_]*(-?\\d{1,2})([A-Za-z]?)(?![A-Za-z0-9])", RegexOptions.IgnoreCase);
            if (match.Success)
            {
                int number = int.Parse(match.Groups[1].Value);
                if (number < 0) return "LB" + Math.Abs(number);
                return "L" + number.ToString("00") + match.Groups[2].Value.ToUpperInvariant();
            }

            string low = raw.ToLowerInvariant();
            foreach (string[] alias in LevelAliases)
                if (low.Contains(alias[0])) return "L" + alias[1];

            MatchCollection numbers = Regex.Matches(raw, "-?\\d+");
            if (numbers.Count > 0)
            {
                int number;
                if (int.TryParse(numbers[numbers.Count - 1].Value, out number))
                {
                    if (number < 0) return "LB" + Math.Abs(number);
                    return "L" + number.ToString("00");
                }
            }

            string letters = Regex.Replace(raw, "[^A-Za-z]", "");
            string consonants = Regex.Replace(letters, "[AEIOUaeiou]", "");
            if (consonants.Length == 0) consonants = letters;
            if (consonants.Length == 0) return "LXX";
            return "L" + (consonants.Length > 2 ? consonants.Substring(0, 2) : consonants).ToUpperInvariant();
        }

        public static string UniqueName(string baseName, ICollection<string> taken)
        {
            string candidate = baseName;
            int counter = 2;
            while (taken.Contains(candidate))
            {
                candidate = baseName + " (" + counter + ")";
                counter++;
            }
            return candidate;
        }

        // ---------------------------------------------------------------- view type labels --

        public static readonly string[] ExcludedViewTypes = { "DrawingSheet", "ProjectBrowser", "SystemBrowser", "Internal", "Undefined" };

        public static readonly string[][] ViewTypeLabels =
        {
            new[] { "FloorPlan", "Floor Plan" }, new[] { "CeilingPlan", "Ceiling Plan" }, new[] { "EngineeringPlan", "Structural Plan" },
            new[] { "AreaPlan", "Area Plan" }, new[] { "Section", "Section" }, new[] { "Elevation", "Elevation" },
            new[] { "Detail", "Detail View" }, new[] { "ThreeD", "3D View" }, new[] { "DraftingView", "Drafting View" },
            new[] { "Legend", "Legend" }, new[] { "Schedule", "Schedule" }, new[] { "PanelSchedule", "Panel Schedule" },
            new[] { "ColumnSchedule", "Column Schedule" }, new[] { "Walkthrough", "Walkthrough" }, new[] { "Rendering", "Rendering" },
        };

        /// <summary>The characters Revit refuses in a view name.</summary>
        public static readonly char[] RevitNameBad = "{}[]|;<>?`~:\\".ToCharArray();

        public static string Spaced(string name)
        {
            return Regex.Replace(name ?? "", "(?<=[a-z0-9])(?=[A-Z])", " ");
        }

        public static string ViewTypeLabel(string typeName)
        {
            foreach (string[] pair in ViewTypeLabels) if (pair[0] == typeName) return pair[1];
            string spaced = Spaced(typeName);
            return spaced.Length == 0 ? "Other" : spaced;
        }

        public static int ViewTypeRank(string typeName)
        {
            for (int i = 0; i < ViewTypeLabels.Length; i++) if (ViewTypeLabels[i][0] == typeName) return i;
            return ViewTypeLabels.Length;
        }

        /// <summary>P-9, P-10, P-100 in that order: digits padded so strings sort right.</summary>
        public static string NaturalKey(string text)
        {
            return Regex.Replace((text ?? "").ToLowerInvariant(), "\\d+", m => m.Value.PadLeft(12, '0'));
        }

        // ---------------------------------------------------------------- fields and rows --

        /// <summary>One column of the reference grid. Kind says where its value comes from.</summary>
        public sealed class Field
        {
            public readonly string Key, Label, Kind, Param;
            public readonly bool Writable;
            public readonly double Width;

            public Field(string key, string label, string kind, bool writable, double width = 150, string param = null)
            {
                Key = key; Label = label; Kind = kind; Writable = writable; Width = width; Param = param;
            }
        }

        public static readonly Field FieldName = new Field("name", "View name", "name", true, 280);
        public static readonly Field FieldLevel = new Field("level", "Associated Level", "level", false, 170);
        public static readonly Field FieldTitle = new Field("title", "Title on sheet", "title", true, 280);
        public static readonly Field FieldDetail = new Field("detail", "Detail number", "detail", true, 120);
        public static readonly Field FieldType = new Field("vtype", "View type", "vtype", false, 130);
        public static readonly Field FieldSheetNo = new Field("sheetno", "Sheet number", "sheetno", false, 120);
        public static readonly Field FieldSheetName = new Field("sheetname", "Sheet name", "sheetname", false, 200);
        public static readonly Field FieldId = new Field("vid", "Element ID", "vid", false, 100);
        public static readonly Field FieldTemplate = new Field("template", "View template", "template", true, 200);
        public static readonly Field FieldVpType = new Field("vptype", "Viewport type", "vptype", true, 170);
        public static readonly Field FieldPreview = new Field("preview", "Preview", "preview", false, 300);

        public static readonly Field[] DefaultFields = { FieldName, FieldLevel, FieldTitle, FieldDetail, FieldTemplate, FieldVpType };
        public static readonly Field[] ExtraFields = { FieldType, FieldSheetNo, FieldSheetName, FieldId };
        public const string ParamPrefix = "p:";

        public static Field ParamField(string name)
        {
            return new Field(ParamPrefix + name, name, "param", true, 150, name);
        }

        /// <summary>Back from a saved key to a Field, or null for one this version lacks.</summary>
        public static Field FieldFromKey(string key)
        {
            foreach (Field f in DefaultFields) if (f.Key == key) return f;
            foreach (Field f in ExtraFields) if (f.Key == key) return f;
            if (key.StartsWith(ParamPrefix) && key.Length > ParamPrefix.Length) return ParamField(key.Substring(ParamPrefix.Length));
            return null;
        }

        /// <summary>Names the parameter list must not offer again - they are columns already.</summary>
        public static HashSet<string> FixedLabels()
        {
            var set = new HashSet<string>();
            foreach (Field f in DefaultFields) set.Add(f.Label.ToLowerInvariant());
            foreach (Field f in ExtraFields) set.Add(f.Label.ToLowerInvariant());
            foreach (string s in new[] { "view name", "title on sheet", "detail number", "associated level", "sheet number", "sheet name" }) set.Add(s);
            return set;
        }

        public sealed class RefRow
        {
            public long ViewId;
            public string TypeName, TypeLabel;
            public Dictionary<string, string> Values = new Dictionary<string, string>();   // field key -> the text Revit holds
            public Dictionary<string, string> Locked = new Dictionary<string, string>();   // field key -> why this cell cannot be edited
            public long SheetId;                                                            // the sheet it sits on, 0 when none
            public long ViewportId;

            public RefRow(long viewId, string typeName)
            {
                ViewId = viewId;
                TypeName = typeName;
                TypeLabel = ViewTypeLabel(typeName);
            }

            public string Get(string key)
            {
                string v;
                return Values.TryGetValue(key, out v) ? v : "";
            }
        }

        /// <summary>One line, no stray ends: what a cell holds once it is staged.</summary>
        public static string CleanValue(string text)
        {
            return Regex.Replace(text ?? "", "\\s*[\\r\\n]+\\s*", " ").Trim();
        }

        public struct CellKey : IEquatable<CellKey>
        {
            public readonly long View;
            public readonly string Key;
            public CellKey(long view, string key) { View = view; Key = key; }
            public bool Equals(CellKey o) { return View == o.View && Key == o.Key; }
            public override bool Equals(object obj) { return obj is CellKey && Equals((CellKey)obj); }
            public override int GetHashCode() { return View.GetHashCode() * 397 ^ (Key == null ? 0 : Key.GetHashCode()); }
        }

        /// <summary>What Apply will do for one staged cell.</summary>
        public sealed class EditItem
        {
            public long ViewId;
            public string Key, Kind, Param, Text, Old, Name;
            public long Viewport, Sheet;
        }

        /// <summary>Staged edits keyed by (view, field) - never by where a cell sits. Nothing reaches Revit until Apply.</summary>
        public sealed class EditStore
        {
            public Dictionary<long, RefRow> Rows = new Dictionary<long, RefRow>();
            public Dictionary<CellKey, string> Edits = new Dictionary<CellKey, string>();
            /// <summary>field key -> the values it may take (a view template, a viewport type). A blank in the list means "none" is allowed.</summary>
            public Dictionary<string, List<string>> Choices = new Dictionary<string, List<string>>();

            public EditStore(IEnumerable<RefRow> rows = null)
            {
                if (rows != null) Load(rows);
            }

            /// <summary>The listed spelling of a choice, or null when it is not listed.</summary>
            public string Canonical(string key, string text)
            {
                List<string> list;
                if (!Choices.TryGetValue(key, out list)) return null;
                foreach (string choice in list)
                    if (string.Equals(choice, text, StringComparison.OrdinalIgnoreCase)) return choice;
                return null;
            }

            /// <summary>Take a fresh read. Edits that no longer change anything are dropped.</summary>
            public void Load(IEnumerable<RefRow> rows)
            {
                Rows = new Dictionary<long, RefRow>();
                foreach (RefRow r in rows) Rows[r.ViewId] = r;
                foreach (CellKey k in Edits.Keys.ToList())
                {
                    RefRow row;
                    if (!Rows.TryGetValue(k.View, out row) || row.Get(k.Key) == Edits[k]) Edits.Remove(k);
                    else if (row.Locked.ContainsKey(k.Key) && !string.IsNullOrEmpty(row.Locked[k.Key])) Edits.Remove(k);
                }
            }

            public string Effective(long viewId, string key)
            {
                string v;
                if (Edits.TryGetValue(new CellKey(viewId, key), out v)) return v;
                RefRow row;
                return Rows.TryGetValue(viewId, out row) ? row.Get(key) : "";
            }

            public string Original(long viewId, string key)
            {
                RefRow row;
                return Rows.TryGetValue(viewId, out row) ? row.Get(key) : "";
            }

            /// <summary>The rules a single cell can break on its own. Returns "" when fine.</summary>
            public string BasicCheck(long viewId, string key, string text)
            {
                RefRow row;
                if (!Rows.TryGetValue(viewId, out row)) return "That view is no longer in the list.";
                string why;
                if (row.Locked.TryGetValue(key, out why) && !string.IsNullOrEmpty(why)) return why;
                if (key == "name")
                {
                    if (text.Length == 0) return "A view needs a name.";
                    var bad = RevitNameBad.Where(c => text.IndexOf(c) >= 0).Select(c => c.ToString()).ToList();
                    if (bad.Count > 0) return "Revit does not allow " + string.Join(" ", bad) + " in a view name.";
                }
                if (Choices.ContainsKey(key) && Canonical(key, text) == null)
                    return "'" + text + "' is not one of the available values for this column.";
                return "";
            }

            /// <summary>(ok, text as held, message). Putting back the original clears it.</summary>
            public bool Stage(long viewId, string key, string text, out string held, out string message)
            {
                text = CleanValue(text);
                message = BasicCheck(viewId, key, text);
                if (message.Length > 0)
                {
                    held = Effective(viewId, key);
                    return false;
                }
                if (Choices.ContainsKey(key)) text = Canonical(key, text);
                var k = new CellKey(viewId, key);
                if (text == Original(viewId, key)) Edits.Remove(k);
                else Edits[k] = text;
                held = text;
                return true;
            }

            public void Revert()
            {
                Edits.Clear();
            }

            public void Revert(long viewId, string key)
            {
                Edits.Remove(new CellKey(viewId, key));
            }

            /// <summary>Edited cells that would leave two views with the same name, or two views on one sheet with the same detail number.</summary>
            public Dictionary<CellKey, string> Conflicts()
            {
                var found = new Dictionary<CellKey, string>();
                var names = new Dictionary<string, List<long>>();
                var details = new Dictionary<string, List<long>>();
                foreach (KeyValuePair<long, RefRow> kv in Rows)
                {
                    long viewId = kv.Key;
                    RefRow row = kv.Value;
                    string name = Effective(viewId, "name").Trim().ToLowerInvariant();
                    if (name.Length > 0)
                    {
                        List<long> l;
                        if (!names.TryGetValue(name, out l)) names[name] = l = new List<long>();
                        l.Add(viewId);
                    }
                    if (row.SheetId != 0)
                    {
                        string detail = Effective(viewId, "detail").Trim().ToLowerInvariant();
                        if (detail.Length > 0)
                        {
                            string pair = row.SheetId + "\u0001" + detail;
                            List<long> l;
                            if (!details.TryGetValue(pair, out l)) details[pair] = l = new List<long>();
                            l.Add(viewId);
                        }
                    }
                }
                foreach (KeyValuePair<string, List<long>> kv in names)
                {
                    if (kv.Value.Count <= 1) continue;
                    foreach (long viewId in kv.Value)
                    {
                        var k = new CellKey(viewId, "name");
                        if (Edits.ContainsKey(k)) found[k] = kv.Value.Count + " views would be called '" + Edits[k] + "'.";
                    }
                }
                foreach (KeyValuePair<string, List<long>> kv in details)
                {
                    if (kv.Value.Count <= 1) continue;
                    foreach (long viewId in kv.Value)
                    {
                        var k = new CellKey(viewId, "detail");
                        if (Edits.ContainsKey(k))
                            found[k] = "Detail number " + Edits[k] + " would be used " + kv.Value.Count + " times on sheet " + Rows[viewId].Get("sheetno") + ".";
                    }
                }
                return found;
            }

            /// <summary>What Apply will do, as plain items the Revit side can walk.</summary>
            public List<EditItem> Items(ICollection<CellKey> only = null)
            {
                var keys = Edits.Keys.ToList();
                keys.Sort((a, b) =>
                {
                    int c = a.View.CompareTo(b.View);
                    return c != 0 ? c : string.CompareOrdinal(a.Key, b.Key);
                });
                var output = new List<EditItem>();
                foreach (CellKey k in keys)
                {
                    if (only != null && !only.Contains(k)) continue;
                    RefRow row;
                    if (!Rows.TryGetValue(k.View, out row)) continue;
                    var item = new EditItem { ViewId = k.View, Key = k.Key, Text = Edits[k], Old = row.Get(k.Key), Viewport = row.ViewportId, Sheet = row.SheetId, Name = row.Get("name") };
                    if (k.Key.StartsWith(ParamPrefix))
                    {
                        item.Kind = "param";
                        item.Param = k.Key.Substring(ParamPrefix.Length);
                    }
                    else item.Kind = k.Key;
                    output.Add(item);
                }
                return output;
            }
        }

        /// <summary>'' normal, 'e' staged, 'x' refused or clashing, 'r' read-only here.</summary>
        public static string CellFlag(EditStore store, ICollection<CellKey> failed, IDictionary<CellKey, string> conflicts, long viewId, Field field)
        {
            var k = new CellKey(viewId, field.Key);
            if ((failed != null && failed.Contains(k)) || (conflicts != null && conflicts.ContainsKey(k))) return "x";
            if (store.Edits.ContainsKey(k)) return "e";
            RefRow row;
            store.Rows.TryGetValue(viewId, out row);
            if (!field.Writable || (row != null && row.Locked.ContainsKey(field.Key))) return "r";
            return "";
        }

        /// <summary>The values a column holds across the views of a type, natural order.</summary>
        public static List<string> DistinctValues(IEnumerable<RefRow> rows, EditStore store, string key, string typeName)
        {
            var seen = new HashSet<string>();
            foreach (RefRow row in rows)
            {
                if (!string.IsNullOrEmpty(typeName) && row.TypeName != typeName) continue;
                seen.Add(store.Effective(row.ViewId, key));
            }
            var list = seen.ToList();
            list.Sort((a, b) => string.CompareOrdinal(NaturalKey(a), NaturalKey(b)));
            return list;
        }

        /// <summary>The rows the grid shows, in order. Search needs every word somewhere in a visible column; the order is natural.</summary>
        public static List<RefRow> FilterAndSort(IEnumerable<RefRow> rows, EditStore store, IList<Field> fields, string typeName, string search,
                                                 string sortKey, bool descending, string colKey = null, string colValue = null, string sheetMode = "any")
        {
            string[] words = (search ?? "").ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            var shown = new List<RefRow>();
            foreach (RefRow row in rows)
            {
                if (!string.IsNullOrEmpty(typeName) && row.TypeName != typeName) continue;
                if (sheetMode == "on" && row.SheetId == 0) continue;
                if (sheetMode == "off" && row.SheetId != 0) continue;
                if (colKey != null && colValue != null && store.Effective(row.ViewId, colKey) != colValue) continue;
                if (words.Length > 0)
                {
                    string haystack = string.Join("\t", fields.Select(f => store.Effective(row.ViewId, f.Key))).ToLowerInvariant();
                    bool all = true;
                    foreach (string w in words) if (!haystack.Contains(w)) { all = false; break; }
                    if (!all) continue;
                }
                shown.Add(row);
            }
            var keyed = shown.Select((r, i) => new
            {
                A = NaturalKey(store.Effective(r.ViewId, sortKey)),
                B = NaturalKey(store.Effective(r.ViewId, "name")),
                Row = r,
                Index = i,
            }).ToList();
            keyed.Sort((x, y) =>
            {
                int c = string.CompareOrdinal(x.A, y.A);
                if (c == 0) c = string.CompareOrdinal(x.B, y.B);
                if (descending) c = -c;
                return c != 0 ? c : x.Index.CompareTo(y.Index);
            });
            return keyed.Select(t => t.Row).ToList();
        }

        public sealed class TypeOption
        {
            public string Name, Label;
            public int Count;
        }

        /// <summary>The dropdown's view types, in dropdown order, with a count each.</summary>
        public static List<TypeOption> TypeOptions(IEnumerable<RefRow> rows)
        {
            var counts = new Dictionary<string, int>();
            foreach (RefRow row in rows)
            {
                int c;
                counts.TryGetValue(row.TypeName, out c);
                counts[row.TypeName] = c + 1;
            }
            var names = counts.Keys.ToList();
            names.Sort((a, b) =>
            {
                int c = ViewTypeRank(a).CompareTo(ViewTypeRank(b));
                return c != 0 ? c : string.CompareOrdinal(ViewTypeLabel(a), ViewTypeLabel(b));
            });
            return names.Select(n => new TypeOption { Name = n, Label = ViewTypeLabel(n), Count = counts[n] }).ToList();
        }

        // ---------------------------------------------------------------- general settings --

        public static readonly Dictionary<string, string> SettingsDefaults = new Dictionary<string, string>
        {
            { "theme_mode", "follow" },
            { "room_tags_on", "1" },
            { "room_tag_type", "" },
            { "room_tags_links", "1" },
            { "ref_columns", "" },
            { "ref_type", "" },
        };

        public static readonly Dictionary<string, string> Settings = new Dictionary<string, string>(SettingsDefaults);
        public static readonly string[] ThemeModes = { "follow", "dark", "light" };
        public static readonly Dictionary<string, string> ThemeLabels = new Dictionary<string, string> { { "follow", "Auto" }, { "dark", "Dark" }, { "light", "Light" } };
        public static string ThemeMode = "follow";
        public static string ThemeName = "dark";
        public static string ThemeReadAs = "";

        public static void LoadSettings()
        {
            Settings.Clear();
            foreach (KeyValuePair<string, string> kv in SettingsDefaults) Settings[kv.Key] = kv.Value;
            try
            {
                string path = SettingsPath();
                if (File.Exists(path))
                {
                    foreach (string raw in File.ReadAllLines(path, Encoding.UTF8))
                    {
                        string line = raw.Trim();
                        if (line.Length == 0 || line.StartsWith("#") || line.IndexOf('=') < 0) continue;
                        int eq = line.IndexOf('=');
                        Settings[line.Substring(0, eq).Trim()] = line.Substring(eq + 1).Trim();
                    }
                }
            }
            catch (Exception)
            {
            }
            string mode = Get("theme_mode");
            ThemeMode = Array.IndexOf(ThemeModes, mode) >= 0 ? mode : "follow";
        }

        public static bool SaveSettings(out string note)
        {
            note = "";
            try
            {
                var sb = new StringBuilder("# RevoBIM PY - View Manager settings\n");
                var keys = Settings.Keys.ToList();
                keys.Sort(string.CompareOrdinal);
                foreach (string k in keys) sb.Append(k + "=" + Settings[k] + "\n");
                File.WriteAllText(SettingsPath(), sb.ToString(), new UTF8Encoding(false));
                return true;
            }
            catch (Exception ex)
            {
                note = Describe(ex);
                return false;
            }
        }

        public static string Get(string key)
        {
            string v;
            if (Settings.TryGetValue(key, out v)) return v;
            return SettingsDefaults.TryGetValue(key, out v) ? v : "";
        }

        public static bool SettingOn(string key)
        {
            string v = (Get(key) ?? "").Trim();
            return v == "1" || v == "true" || v == "True" || v == "yes";
        }

        // ---------------------------------------------------------------- palettes --

        public static readonly Dictionary<string, string> Dark = new Dictionary<string, string>
        {
            { "WindowBg", "#3C4454" }, { "Panel", "#343C4A" }, { "Sunken", "#3C4454" }, { "Input", "#2D3441" }, { "HeadBar", "#212932" },
            { "Strip", "#1B1F24" }, { "TabHover", "#2D3441" }, { "Scrim", "#D81B1F24" }, { "Track", "#2D3441" }, { "Thumb", "#5A6476" },
            { "ThumbHover", "#6C778A" }, { "Line", "#4E586A" }, { "Edge", "#8790A0" }, { "EdgeHover", "#A4ADBC" }, { "Text", "#EBF5FF" },
            { "Muted", "#9DA4B2" }, { "Disabled", "#7B8290" }, { "OnAccent", "#FFFFFF" }, { "OnBlue", "#0E2233" }, { "Btn", "#465063" },
            { "BtnHover", "#535E73" }, { "BtnDisabled", "#343C4A" }, { "Hover", "#465063" }, { "Selection", "#2B5473" }, { "Blue", "#3D9BE9" },
            { "Orange", "#F07C10" }, { "OrangeWash", "#3A2A14" }, { "Green", "#3FA75A" }, { "GreenHover", "#4EC06D" }, { "GreenPress", "#33843F" },
            { "GreenEdge", "#2E7D42" }, { "Red", "#C0392B" }, { "RedHover", "#E04B39" }, { "RedPress", "#9E2E22" }, { "RedEdge", "#8E2A20" },
            { "RedDisabled", "#5A3833" }, { "RedDisabledText", "#A9A9A9" }, { "StagedWash", "#23405A" }, { "ErrorWash", "#5A2A26" },
        };

        public static readonly Dictionary<string, string> Light = new Dictionary<string, string>
        {
            { "WindowBg", "#E8ECF1" }, { "Panel", "#F4F6F9" }, { "Sunken", "#FFFFFF" }, { "Input", "#FFFFFF" }, { "HeadBar", "#DCE1E8" },
            { "Strip", "#CDD4DD" }, { "TabHover", "#DCE1E8" }, { "Scrim", "#8C2A3038" }, { "Track", "#E8ECF1" }, { "Thumb", "#B5BECA" },
            { "ThumbHover", "#97A1AF" }, { "Line", "#C3CBD6" }, { "Edge", "#8A94A3" }, { "EdgeHover", "#5E6878" }, { "Text", "#1C2330" },
            { "Muted", "#55606F" }, { "Disabled", "#8C95A3" }, { "OnAccent", "#FFFFFF" }, { "OnBlue", "#FFFFFF" }, { "Btn", "#E2E7EE" },
            { "BtnHover", "#D3DAE3" }, { "BtnDisabled", "#EDF0F4" }, { "Hover", "#DCE3EC" }, { "Selection", "#CFE2F6" }, { "Blue", "#1B72BE" },
            { "Orange", "#B96A12" }, { "OrangeWash", "#F8E8D4" }, { "Green", "#2E8546" }, { "GreenHover", "#379A53" }, { "GreenPress", "#256C39" },
            { "GreenEdge", "#22663A" }, { "Red", "#B5342A" }, { "RedHover", "#C9473B" }, { "RedPress", "#962A20" }, { "RedEdge", "#8E2A20" },
            { "RedDisabled", "#E5C9C5" }, { "RedDisabledText", "#8C6F6B" }, { "StagedWash", "#D6E8F8" }, { "ErrorWash", "#F6D3CF" },
        };

        public static readonly Dictionary<string, Dictionary<string, string>> Palettes = new Dictionary<string, Dictionary<string, string>>
        {
            { "dark", Dark }, { "light", Light },
        };

        // ---------------------------------------------------------------- title rewrite rules --

        public static readonly string[][] RuleModes = { new[] { "text", "Text" }, new[] { "word", "Whole word" }, new[] { "regex", "Regex" }, new[] { "extract", "Extract" } };
        public static readonly string[][] CaseModes =
        {
            new[] { "none", "Leave as is" }, new[] { "title", "Title Case" }, new[] { "upper", "UPPER CASE" },
            new[] { "lower", "lower case" }, new[] { "sentence", "Sentence case" },
        };
        public static readonly string[][] SourceModes = { new[] { "view", "View name" }, new[] { "title", "Current title on sheet" } };

        private static readonly HashSet<string> SmallWords = new HashSet<string> { "a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with" };

        public sealed class Rule
        {
            public bool On = true;
            public string Find = "", Replace = "", Mode = "text";
            public bool MatchCase;

            public Rule Copy() { return (Rule)MemberwiseClone(); }
        }

        public static Rule NewRule(string find = "", string replace = "", string mode = "text", bool matchCase = false, bool on = true)
        {
            return new Rule { Find = find, Replace = replace, Mode = mode, MatchCase = matchCase, On = on };
        }

        /// <summary>(compiled pattern, "") or (null, why). An empty find is skipped quietly.</summary>
        public static Regex CompileRule(Rule rule, out string problem)
        {
            problem = "";
            string find = rule.Find ?? "";
            if (find.Length == 0) return null;
            string pattern;
            if (rule.Mode == "regex" || rule.Mode == "extract") pattern = find;
            else if (rule.Mode == "word") pattern = "(?<![A-Za-z0-9])" + Regex.Escape(find) + "(?![A-Za-z0-9])";
            else pattern = Regex.Escape(find);
            try
            {
                return new Regex(pattern, rule.MatchCase ? RegexOptions.None : RegexOptions.IgnoreCase);
            }
            catch (Exception ex)
            {
                problem = "'" + find + "' is not a valid pattern (" + ex.Message + ")";
                return null;
            }
        }

        /// <summary>Python's match.expand: \1, \g&lt;1&gt;, \g&lt;name&gt;, \n \t \r \\ in a replacement.</summary>
        public static string ExpandTemplate(Match m, string template)
        {
            var sb = new StringBuilder();
            int i = 0;
            while (i < template.Length)
            {
                char ch = template[i];
                if (ch != '\\' || i + 1 >= template.Length)
                {
                    sb.Append(ch);
                    i++;
                    continue;
                }
                char next = template[i + 1];
                if (char.IsDigit(next))
                {
                    int j = i + 1;
                    int len = 0;
                    while (j < template.Length && char.IsDigit(template[j]) && len < 2) { j++; len++; }
                    int n = int.Parse(template.Substring(i + 1, len));
                    if (n < m.Groups.Count) sb.Append(m.Groups[n].Value);
                    i = j;
                }
                else if (next == 'g' && i + 2 < template.Length && template[i + 2] == '<')
                {
                    int close = template.IndexOf('>', i + 3);
                    if (close < 0)
                    {
                        sb.Append(ch);
                        i++;
                        continue;
                    }
                    string name = template.Substring(i + 3, close - i - 3);
                    Group g = m.Groups[name];
                    sb.Append(g.Value);
                    i = close + 1;
                }
                else
                {
                    switch (next)
                    {
                        case 'n': sb.Append('\n'); break;
                        case 't': sb.Append('\t'); break;
                        case 'r': sb.Append('\r'); break;
                        case '\\': sb.Append('\\'); break;
                        default: sb.Append(ch).Append(next); break;
                    }
                    i += 2;
                }
            }
            return sb.ToString();
        }

        /// <summary>(new text, problem). A broken rule leaves the text as it was.</summary>
        public static string ApplyRule(string text, Rule rule, out string problem)
        {
            problem = "";
            if (!rule.On) return text;
            string why;
            Regex compiled = CompileRule(rule, out why);
            if (compiled == null)
            {
                problem = why;
                return text;
            }
            string replace = rule.Replace ?? "";
            try
            {
                if (rule.Mode == "extract")
                {
                    Match found = compiled.Match(text);
                    if (!found.Success) return "";
                    if (replace.Length > 0) return ExpandTemplate(found, replace);
                    if (found.Groups.Count > 1) return found.Groups[1].Value;
                    return found.Value;
                }
                if (rule.Mode == "regex") return compiled.Replace(text, m => ExpandTemplate(m, replace));
                return compiled.Replace(text, m => replace);
            }
            catch (Exception ex)
            {
                problem = "'" + rule.Find + "' could not be replaced (" + ex.Message + ")";
                return text;
            }
        }

        private static string CapitalisePart(string part)
        {
            for (int i = 0; i < part.Length; i++)
                if (char.IsLetter(part[i]))
                    return part.Substring(0, i) + char.ToUpperInvariant(part[i]) + part.Substring(i + 1).ToLowerInvariant();
            return part;
        }

        private static bool HasDigit(string word)
        {
            foreach (char c in word) if (char.IsDigit(c)) return true;
            return false;
        }

        /// <summary>Capitalise each word; small words stay lower mid-title; a word that carries a digit is left exactly as it is.</summary>
        public static string TitleCase(string text)
        {
            string[] words = text.Split(' ');
            var output = new List<string>();
            for (int i = 0; i < words.Length; i++)
            {
                string word = words[i];
                if (word.Length == 0 || HasDigit(word)) output.Add(word);
                else if (i > 0 && SmallWords.Contains(word.ToLowerInvariant())) output.Add(word.ToLowerInvariant());
                else output.Add(string.Join("-", word.Split('-').Select(CapitalisePart)));
            }
            return string.Join(" ", output);
        }

        public static string SentenceCase(string text)
        {
            var words = new List<string>();
            foreach (string word in text.Split(' ')) words.Add(HasDigit(word) ? word : word.ToLowerInvariant());
            string result = string.Join(" ", words);
            for (int i = 0; i < result.Length; i++)
                if (char.IsLetter(result[i])) return result.Substring(0, i) + char.ToUpperInvariant(result[i]) + result.Substring(i + 1);
            return result;
        }

        public static string TidyText(string text)
        {
            return Regex.Replace(text, "\\s+", " ").Trim();
        }

        /// <summary>Run the rules top to bottom, then tidy the spaces, then the case.</summary>
        public static string Rewrite(string text, IEnumerable<Rule> rules, string caseMode, bool tidy, List<string> problems)
        {
            string result = text ?? "";
            foreach (Rule rule in rules)
            {
                string problem;
                result = ApplyRule(result, rule, out problem);
                if (problem.Length > 0 && problems != null && !problems.Contains(problem)) problems.Add(problem);
            }
            if (tidy) result = TidyText(result);
            if (caseMode == "title") result = TitleCase(result);
            else if (caseMode == "upper") result = result.ToUpperInvariant();
            else if (caseMode == "lower") result = result.ToLowerInvariant();
            else if (caseMode == "sentence") result = SentenceCase(result);
            return result;
        }

        public sealed class Ruleset
        {
            public string Name, Source = "view", Case = "none", Target = "title";
            public bool Tidy = true;
            public List<Rule> Rules = new List<Rule>();

            public Ruleset(string name) { Name = name; }

            public Ruleset Copy()
            {
                var copy = new Ruleset(Name) { Source = Source, Case = Case, Tidy = Tidy, Target = Target };
                foreach (Rule r in Rules) copy.Rules.Add(r.Copy());
                return copy;
            }
        }

        private static string Escape(string text)
        {
            return (text ?? "").Replace("\\", "\\\\").Replace("\t", "\\t").Replace("\n", "\\n").Replace("\r", "");
        }

        private static string Unescape(string text)
        {
            var sb = new StringBuilder();
            int i = 0;
            while (i < text.Length)
            {
                char ch = text[i];
                if (ch == '\\' && i + 1 < text.Length)
                {
                    char next = text[i + 1];
                    sb.Append(next == 't' ? '\t' : next == 'n' ? '\n' : next);
                    i += 2;
                }
                else
                {
                    sb.Append(ch);
                    i++;
                }
            }
            return sb.ToString();
        }

        public static string FormatRulesets(IEnumerable<Ruleset> rulesets)
        {
            var lines = new List<string>
            {
                "# RevoBIM PY - View Manager title rulesets",
                "# [name] then source / case / tidy, then one rule= line each:",
                "# rule=on<TAB>mode<TAB>match case<TAB>find<TAB>replace with",
            };
            foreach (Ruleset rs in rulesets)
            {
                lines.Add("[" + rs.Name.Replace("[", "(").Replace("]", ")") + "]");
                lines.Add("target=" + rs.Target);
                lines.Add("source=" + rs.Source);
                lines.Add("case=" + rs.Case);
                lines.Add("tidy=" + (rs.Tidy ? "1" : "0"));
                foreach (Rule rule in rs.Rules)
                    lines.Add("rule=" + (rule.On ? "1" : "0") + "\t" + rule.Mode + "\t" + (rule.MatchCase ? "1" : "0") + "\t" + Escape(rule.Find) + "\t" + Escape(rule.Replace));
                lines.Add("");
            }
            return string.Join("\n", lines) + "\n";
        }

        /// <summary>Back from the file. Anything it cannot read is skipped, not fatal.</summary>
        public static List<Ruleset> ParseRulesets(string text)
        {
            var modes = RuleModes.Select(m => m[0]).ToList();
            var cases = CaseModes.Select(c => c[0]).ToList();
            var sources = SourceModes.Select(s => s[0]).ToList();
            var found = new List<Ruleset>();
            Ruleset current = null;
            foreach (string raw in (text ?? "").Replace("\r\n", "\n").Split('\n'))
            {
                string line = raw.TrimEnd('\r', '\n');
                if (line.Trim().Length == 0 || line.TrimStart().StartsWith("#")) continue;
                if (line.StartsWith("[") && line.TrimEnd().EndsWith("]"))
                {
                    string t = line.Trim();
                    current = new Ruleset(t.Substring(1, t.Length - 2));
                    found.Add(current);
                    continue;
                }
                if (current == null || line.IndexOf('=') < 0) continue;
                int eq = line.IndexOf('=');
                string key = line.Substring(0, eq).Trim();
                string value = line.Substring(eq + 1);
                if (key == "source" && sources.Contains(value.Trim())) current.Source = value.Trim();
                else if (key == "target" && (value.Trim() == "title" || value.Trim() == "detail")) current.Target = value.Trim();
                else if (key == "case" && cases.Contains(value.Trim())) current.Case = value.Trim();
                else if (key == "tidy") current.Tidy = value.Trim() == "1" || value.Trim() == "true" || value.Trim() == "yes";
                else if (key == "rule")
                {
                    string[] parts = value.Split('\t');
                    if (parts.Length < 5) continue;
                    string mode = modes.Contains(parts[1]) ? parts[1] : "text";
                    current.Rules.Add(NewRule(Unescape(parts[3]), Unescape(parts[4]), mode, parts[2] == "1", parts[0] != "0"));
                }
            }
            return found;
        }

        /// <summary>Pulls the trailing number out of a name: VENT_L01_03 gives 03.</summary>
        public static Ruleset StarterDetailRuleset()
        {
            var rs = new Ruleset("Example - last number in the name") { Target = "detail" };
            rs.Rules.Add(NewRule("(\\d+)\\D*$", "\\1", "extract"));
            return rs;
        }

        /// <summary>One worked example, so the first run shows what a ruleset is: VENT_L01 becomes 'Ventilation - Level 01'.</summary>
        public static Ruleset StarterRuleset()
        {
            var rs = new Ruleset("Example - VENT_L01 to Ventilation - Level 01");
            rs.Rules.Add(NewRule("(?<![A-Za-z0-9])L(\\d+)(?![A-Za-z0-9])", "Level \\1", "regex"));
            rs.Rules.Add(NewRule("LRF", "Roof", "word"));
            rs.Rules.Add(NewRule("LTG-EXT", "External Lighting", "word"));
            rs.Rules.Add(NewRule("LTG", "Lighting", "word"));
            rs.Rules.Add(NewRule("VENT", "Ventilation", "word"));
            rs.Rules.Add(NewRule("HTG", "Heating", "word"));
            rs.Rules.Add(NewRule("DOM", "Domestic Water", "word"));
            rs.Rules.Add(NewRule("DRN", "Drainage", "word"));
            rs.Rules.Add(NewRule("PWR", "Power", "word"));
            rs.Rules.Add(NewRule("SEC", "Security", "word"));
            rs.Rules.Add(NewRule("CONT", "Containment", "word"));
            rs.Rules.Add(NewRule("FA", "Fire Alarm", "word"));
            rs.Rules.Add(NewRule("_", " - ", "text"));
            return rs;
        }

        // ---------------------------------------------------------------- room geometry --

        public const double RoomZTolerance = 0.01;
        public const double DefaultCutOffset = 4.0;
        public const int TagViewsPerTransaction = 10;

        /// <summary>Does a horizontal plane at cutZ pass through zMin..zMax?</summary>
        public static bool ZSpanCut(double? zMin, double? zMax, double? cutZ, double tol = RoomZTolerance)
        {
            if (zMin == null || zMax == null || cutZ == null) return false;
            double low = Math.Min(zMin.Value, zMax.Value), high = Math.Max(zMin.Value, zMax.Value);
            return (low - tol) <= cutZ.Value && cutZ.Value <= (high + tol);
        }

        /// <summary>rect is {minX, minY, maxX, maxY} or null for no crop at all.</summary>
        public static bool PointInRect(double x, double y, double[] rect)
        {
            if (rect == null) return true;
            return rect[0] <= x && x <= rect[2] && rect[1] <= y && y <= rect[3];
        }

        public static double[] RectOfPoints(IList<double[]> points)
        {
            if (points.Count == 0) return null;
            return new[] { points.Min(p => p[0]), points.Min(p => p[1]), points.Max(p => p[0]), points.Max(p => p[1]) };
        }

        public sealed class RoomRecord
        {
            public object Link;          // the RevitLinkInstance, or null for this model
            public object Id;            // the room's ElementId
            public double X, Y, ZMin, ZMax;
        }

        public static List<RoomRecord> RoomsInPlan(IEnumerable<RoomRecord> rooms, double? cutZ, double[] cropRect)
        {
            var picked = new List<RoomRecord>();
            foreach (RoomRecord room in rooms)
            {
                if (!ZSpanCut(room.ZMin, room.ZMax, cutZ)) continue;
                if (!PointInRect(room.X, room.Y, cropRect)) continue;
                picked.Add(room);
            }
            return picked;
        }
    }
}
