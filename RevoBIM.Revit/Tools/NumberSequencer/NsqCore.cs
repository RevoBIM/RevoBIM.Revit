using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

namespace RevoBIM.Tools.NumberSequencer
{
    /// <summary>One physical connector on a node (port of nsq_core.Conn).</summary>
    public class Conn
    {
        public int Cid;
        public double Area;
        public double[] Origin;
        public double[] Direction;
        public List<KeyValuePair<long, int>> Links = new List<KeyValuePair<long, int>>();
        public bool Equipment;
        public bool External;
    }

    public class Node
    {
        public long Key;
        public List<Conn> Conns = new List<Conn>();
        public bool IsEquipment;
        public string Label = "";

        public double Area()
        {
            double best = 0.0;
            foreach (Conn c in Conns) if (c.Area > best) best = c.Area;
            return best;
        }

        public Conn Conn(int cid)
        {
            foreach (Conn c in Conns) if (c.Cid == cid) return c;
            return null;
        }
    }

    /// <summary>One system in the system selector list (a dict in the Python).</summary>
    public class SysDef
    {
        public string Key = "";
        public string Name = "";
        public List<long> Keys = new List<long>();
        public List<long> Num = new List<long>();
        public long? Start;
        public bool On = true;
        public string Colour;
        public string Kind = "";
        public string Label = "";
        public string Type = "", Abbr = "", Cls = "";
        public List<Autodesk.Revit.DB.ElementId> Extras = new List<Autodesk.Revit.DB.ElementId>();
    }

    public class ViewRowData
    {
        public Dictionary<string, string> Cols = new Dictionary<string, string>();
        public string Id = "";
        public Autodesk.Revit.DB.ElementId Eid;
        public string Uid = "";
        public bool Locked = true;
        public string Name { get { return Get("name"); } }
        public string Get(string col) { string v; return Cols.TryGetValue(col, out v) ? v ?? "" : ""; }
    }

    public class SheetData
    {
        public string Uid = "";
        public Autodesk.Revit.DB.ElementId Eid;
        public int Placed;
        public string Number = "";
        public string Name = "";
        public List<long> Views = new List<long>();
    }

    public class TagChoice
    {
        public string TagCat = "";
        public string Label = "";
        public long TypeId;
        public Autodesk.Revit.DB.ElementId Id;
        public string Uid = "";
        public string Family = "";
        public string Type = "";
    }

    public class TypeNode { public string Name; public string Key; public List<long> Ids = new List<long>(); }
    public class FamilyNode { public string Name; public List<TypeNode> Types = new List<TypeNode>(); }
    public class CategoryNode { public string Name; public List<FamilyNode> Families = new List<FamilyNode>(); }

    public class NumberPlan
    {
        public List<KeyValuePair<long, KeyValuePair<int, string>>> Items = new List<KeyValuePair<long, KeyValuePair<int, string>>>();
    }

    public class ParamInfo
    {
        public bool Exists;
        public bool ReadOnly;
        public string Storage = "";   // text | integer
        public string Value = "";
        public bool ValueNull;
    }

    public class SlowClicks
    {
        private readonly int _need;
        private readonly double _floor;
        private readonly double _ceiling;
        private readonly List<double> _times = new List<double>();

        public SlowClicks(int need = 3, double floor = 0.25, double ceiling = 2.0)
        {
            _need = need; _floor = floor; _ceiling = ceiling;
        }

        public bool Click(double t)
        {
            if (_times.Count > 0)
            {
                double gap = t - _times[_times.Count - 1];
                if (gap < _floor) return false;
                if (gap > _ceiling) _times.Clear();
            }
            _times.Add(t);
            if (_times.Count >= _need) { _times.Clear(); return true; }
            return false;
        }
    }

    public class DebugLog
    {
        public bool Enabled;
        public List<string> Lines = new List<string>();

        public DebugLog(bool enabled = true) { Enabled = enabled; }

        public void Add(string msg)
        {
            if (!Enabled) return;
            Lines.Add(msg ?? "");
            if (Lines.Count > 20000) Lines = Lines.Skip(Lines.Count - 15000).ToList();
        }

        public string Text() { return string.Join("\n", Lines); }

        public bool Write(string path = null)
        {
            if (!Enabled) return false;
            try
            {
                path = path ?? NsqCore.DebugPath();
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                File.WriteAllText(path, Text(), new UTF8Encoding(false));
                return true;
            }
            catch (Exception) { return false; }
        }
    }

    /// <summary>
    /// Number Sequencer: every rule that needs no Revit. Port of nsq_core.py (version 1.13.2): settings,
    /// palettes, the walk order through a duct or pipe network, number formatting, the category / family /
    /// type tree, system groups and the plan of what gets written.
    /// </summary>
    public static class NsqCore
    {
        public const string Version = "1.15.0";
        public const string ToolName = "Number Sequencer";
        public const string SettingsFile = "number_sequencer.txt";
        public const string DebugFile = "number_sequencer_debug.txt";
        public const string SettingsVersion = "1";
        public const string SkipSep = "||";
        public const string NoneMark = "<none>";

        /// <summary>The add-in build: version, build date and the DLL's path, for the debug header.</summary>
        public static string BuildInfo()
        {
            try
            {
                Assembly assembly = typeof(NsqCore).Assembly;
                string path = assembly.Location;
                string written = "";
                try { written = File.GetLastWriteTime(path).ToString("yyyy-MM-dd HH:mm:ss"); } catch (Exception) { }
                string date = "";
                string revit = "";
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

        // ============================================================ Settings

        public static readonly Dictionary<string, string> Defaults = new Dictionary<string, string>
        {
            { "settings_version", "1" }, { "parameter", "" }, { "pad", "3" }, { "start", "1" },
            { "direction", "up" }, { "tag", "off" }, { "tag_type", "" }, { "skip", "" },
            { "theme", "auto" }, { "debug", "on" }, { "tab", "seq" }, { "sel_kind", "duct" },
            { "sel_skip", "" }, { "view_g1", "" }, { "view_g2", "" }, { "tag_views", "" },
            { "view_kinds_off", "" }, { "iso3d_view", "" }, { "collapsed", "" },
            { "tag_untagged", "on" }, { "tag_scope", "view" }, { "tag_leader", "off" }, { "tag_offx", "0" }, { "tag_offy", "0" }, { "tag_elbow", "off" }, { "tag_elbow_mm", "300" }, { "tag_remove", "off" }, { "tag_untangle", "off" }, { "pos_form", "0" }, { "tag_tab", "sheets" }, { "win_w", "" }, { "win_h", "" },
        };

        public static string SettingsDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }
        public static string SettingsPath() { return Path.Combine(SettingsDir(), SettingsFile); }
        public static string DebugPath() { return Path.Combine(SettingsDir(), DebugFile); }
        public static string ErrorPath() { return Path.Combine(SettingsDir(), "number_sequencer_last_error.txt"); }

        public static Dictionary<string, string> ParseSettings(string text)
        {
            var o = new Dictionary<string, string>(Defaults);
            if (!string.IsNullOrEmpty(text))
            {
                foreach (string raw in text.Split('\n'))
                {
                    string line = raw.Trim();
                    if (line.Length == 0 || line.StartsWith("#") || line.IndexOf('=') < 0) continue;
                    int cut = line.IndexOf('=');
                    string key = line.Substring(0, cut).Trim();
                    if (Defaults.ContainsKey(key)) o[key] = line.Substring(cut + 1).Trim();
                }
            }
            o["settings_version"] = SettingsVersion;
            return o;
        }

        public static string FormatSettings(Dictionary<string, string> values)
        {
            var lines = new List<string> { "# RevoBIM Number Sequencer settings" };
            foreach (string k in Defaults.Keys.OrderBy(x => x, StringComparer.Ordinal))
            {
                string v;
                if (!values.TryGetValue(k, out v) || v == null) v = Defaults[k];
                lines.Add(k + "=" + v.Replace("\r", " ").Replace("\n", " "));
            }
            return string.Join("\n", lines) + "\n";
        }

        public static Dictionary<string, string> LoadSettings()
        {
            string text = "";
            try { if (File.Exists(SettingsPath())) text = File.ReadAllText(SettingsPath()); } catch (Exception) { }
            return ParseSettings(text);
        }

        public static bool SaveSettings(Dictionary<string, string> values)
        {
            try
            {
                Directory.CreateDirectory(SettingsDir());
                File.WriteAllText(SettingsPath(), FormatSettings(values), new UTF8Encoding(false));
                return true;
            }
            catch (Exception) { return false; }
        }

        public static string Get(Dictionary<string, string> s, string key)
        {
            string v;
            if (s.TryGetValue(key, out v) && v != null) return v;
            return Defaults.TryGetValue(key, out v) ? v : "";
        }

        public static HashSet<string> SkipKeysFrom(string text)
        {
            var set = new HashSet<string>();
            if (string.IsNullOrEmpty(text)) return set;
            foreach (string s in text.Split(new[] { SkipSep }, StringSplitOptions.None)) if (s.Length > 0) set.Add(s);
            return set;
        }

        public static string SkipTextFrom(IEnumerable<string> keys)
        {
            return string.Join(SkipSep, keys.OrderBy(x => x, StringComparer.Ordinal));
        }

        // ============================================================ Palettes

        public static readonly Dictionary<string, string> Dark = new Dictionary<string, string>
        {
            { "Bg", "#232326" }, { "Card", "#2B2B2E" }, { "Field", "#1C1C1F" }, { "Bar", "#1C1C1F" },
            { "Edge", "#3E3E42" }, { "ChromeEdge", "#4A4A50" }, { "Text", "#E4E4E4" }, { "Muted", "#9A9A9E" },
            { "Blue", "#4FA3E3" }, { "Orange", "#E8912D" }, { "Green", "#3FA75A" }, { "GreenHover", "#4EC06D" },
            { "Red", "#D9534F" }, { "Sel", "#2B5473" }, { "Hover", "#34343A" }, { "OnAccent", "#FFFFFF" },
        };

        public static readonly Dictionary<string, string> Light = new Dictionary<string, string>
        {
            { "Bg", "#F3F3F5" }, { "Card", "#FFFFFF" }, { "Field", "#FAFAFB" }, { "Bar", "#E6E6EA" },
            { "Edge", "#C9C9CF" }, { "ChromeEdge", "#B4B4BC" }, { "Text", "#1E1E22" }, { "Muted", "#66666E" },
            { "Blue", "#1B72BE" }, { "Orange", "#B96A12" }, { "Green", "#2E8546" }, { "GreenHover", "#379C53" },
            { "Red", "#C03A36" }, { "Sel", "#CFE3F5" }, { "Hover", "#E9EEF4" }, { "OnAccent", "#FFFFFF" },
        };

        private static readonly string[] GroupDark = { "#4FA3E3", "#E8912D", "#3FA75A", "#B07CD8", "#D9C34F", "#4FC1C9", "#D96C8A", "#8FB04F", "#C98A5A", "#7F95E8" };
        private static readonly string[] GroupLight = { "#1B72BE", "#B96A12", "#2E8546", "#7C4BA8", "#9C8410", "#16858C", "#A8385A", "#5B7A1E", "#94582A", "#3F57B8" };

        public static Dictionary<string, string> PaletteFor(string mode) { return mode == "light" ? Light : Dark; }

        public static string GroupColour(int index, string mode)
        {
            string[] seq = mode == "light" ? GroupLight : GroupDark;
            return seq[((index % seq.Length) + seq.Length) % seq.Length];
        }

        public static readonly string[] ThemeCycle = { "auto", "dark", "light" };

        public static string NextTheme(string setting)
        {
            int i = Array.IndexOf(ThemeCycle, setting);
            if (i < 0) i = 0;
            return ThemeCycle[(i + 1) % ThemeCycle.Length];
        }

        /// <summary>auto follows Revit's canvas; canvasIsDark null means unreadable.</summary>
        public static string ResolveTheme(string setting, bool? canvasIsDark)
        {
            if (setting == "dark") return "dark";
            if (setting == "light") return "light";
            if (canvasIsDark == null) return "dark";
            return canvasIsDark.Value ? "dark" : "light";
        }

        public static string ThemeLabel(string setting)
        {
            if (setting == "dark") return "Dark";
            if (setting == "light") return "Light";
            return "Auto";
        }

        public static bool LuminanceIsDark(double r, double g, double b)
        {
            return (0.299 * r + 0.587 * g + 0.114 * b) < 128;
        }

        // ============================================================ Number formatting and the plan

        public static readonly KeyValuePair<int, string>[] PadChoices =
        {
            new KeyValuePair<int, string>(3, "001"), new KeyValuePair<int, string>(2, "01"), new KeyValuePair<int, string>(0, "1"),
        };

        public static int? ToInt(string value)
        {
            int n;
            if (value != null && int.TryParse(value.Trim(), out n)) return n;
            return null;
        }

        public static int ToInt(string value, int fallback)
        {
            int? n = ToInt(value);
            return n ?? fallback;
        }

        /// <summary>'045' -> 45, '7' -> 7. Anything else -> null.</summary>
        public static int? ParseStart(string text)
        {
            if (text == null) return null;
            string t = text.Trim();
            if (t.Length == 0 || !t.All(ch => ch >= '0' && ch <= '9')) return null;
            int n;
            return int.TryParse(t, out n) ? (int?)n : null;
        }

        public static string FormatNumber(int n, int pad)
        {
            string s = Math.Abs(n).ToString();
            if (pad > 0 && s.Length < pad) s = new string('0', pad - s.Length) + s;
            if (n < 0) s = "-" + s;
            return s;
        }

        public class PlanItem { public long Key; public int N; public string Text; }
        public class KeyMsg { public long Key; public string Msg; }

        /// <summary>Downwards never goes below 0; anything that would is an error.</summary>
        public static void PlanNumbers(IEnumerable<long> order, Func<long, bool> include, int start, string direction, int pad,
                                       out List<PlanItem> plan, out List<KeyMsg> errors)
        {
            int step = direction == "down" ? -1 : 1;
            plan = new List<PlanItem>();
            errors = new List<KeyMsg>();
            int n = start;
            foreach (long key in order)
            {
                if (!include(key)) continue;
                if (n < 0)
                {
                    errors.Add(new KeyMsg { Key = key, Msg = "Sequence ran below 0 counting down" });
                    continue;
                }
                plan.Add(new PlanItem { Key = key, N = n, Text = FormatNumber(n, pad) });
                n += step;
            }
        }

        public static string PreviewText(List<PlanItem> plan, List<KeyMsg> errors, int skipped, int pad)
        {
            if (plan.Count == 0) return "Nothing to number";
            string s = plan.Count + " numbered  " + plan[0].Text + " to " + plan[plan.Count - 1].Text;
            if (skipped > 0) s += "  |  " + skipped + " skipped";
            if (errors.Count > 0) s += "  |  " + errors.Count + " below 0";
            return s;
        }

        public class WriteItem { public long Key; public int IntValue; public string TextValue; public bool IsInt; }

        /// <summary>Decide what each planned element needs before any transaction.</summary>
        public static void PrepareWrites(List<PlanItem> plan, Func<long, ParamInfo> readParam,
                                         out List<WriteItem> writes, out List<long> same, out List<KeyMsg> errors)
        {
            writes = new List<WriteItem>();
            same = new List<long>();
            errors = new List<KeyMsg>();
            foreach (PlanItem p in plan)
            {
                ParamInfo info = readParam(p.Key);
                if (info == null || !info.Exists) { errors.Add(new KeyMsg { Key = p.Key, Msg = "Parameter not on this element" }); continue; }
                if (info.ReadOnly) { errors.Add(new KeyMsg { Key = p.Key, Msg = "Parameter is read-only here" }); continue; }
                if (info.Storage == "integer")
                {
                    int? cur = ToInt(info.Value);
                    if (cur != null && cur.Value == p.N && !string.IsNullOrEmpty(info.Value)) same.Add(p.Key);
                    else writes.Add(new WriteItem { Key = p.Key, IsInt = true, IntValue = p.N });
                }
                else if (info.Storage == "text")
                {
                    if ((info.Value ?? "") == p.Text) same.Add(p.Key);
                    else writes.Add(new WriteItem { Key = p.Key, IsInt = false, TextValue = p.Text });
                }
                else errors.Add(new KeyMsg { Key = p.Key, Msg = "Parameter is not text or integer" });
            }
        }

        public static bool ValueMatches(WriteItem expected, string got)
        {
            if (expected.IsInt) { int? v = ToInt(got); return v != null && v.Value == expected.IntValue; }
            return (got ?? "") == expected.TextValue;
        }

        // ============================================================ The network walk

        public const double AreaTol = 0.01;
        public const double OpenEndTolMm = 5.0;

        private static double Dot(double[] a, double[] b)
        {
            if (a == null || b == null) return 0.0;
            return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
        }

        public static double Dist(double[] a, double[] b)
        {
            if (a == null || b == null) return 0.0;
            return Math.Sqrt((a[0] - b[0]) * (a[0] - b[0]) + (a[1] - b[1]) * (a[1] - b[1]) + (a[2] - b[2]) * (a[2] - b[2]));
        }

        private struct Cell : IEquatable<Cell>
        {
            public int X, Y, Z;
            public Cell(int x, int y, int z) { X = x; Y = y; Z = z; }
            public bool Equals(Cell o) { return X == o.X && Y == o.Y && Z == o.Z; }
            public override bool Equals(object o) { return o is Cell && Equals((Cell)o); }
            public override int GetHashCode() { unchecked { return (X * 73856093) ^ (Y * 19349663) ^ (Z * 83492791); } }
        }

        private static Cell CellOf(double[] p, double tol)
        {
            return new Cell((int)Math.Floor(p[0] / tol), (int)Math.Floor(p[1] / tol), (int)Math.Floor(p[2] / tol));
        }

        /// <summary>Open connectors facing each other within tol (model units) are joined here. Returns the joins made.</summary>
        public static int LinkOpenEnds(Dictionary<long, Node> nodes, double tol)
        {
            if (tol <= 0) return 0;
            var opens = new List<KeyValuePair<long, Conn>>();
            foreach (long k in nodes.Keys.OrderBy(x => x))
                foreach (Conn c in nodes[k].Conns)
                {
                    if (c.Links.Count > 0 || c.External || c.Equipment || c.Origin == null) continue;
                    opens.Add(new KeyValuePair<long, Conn>(k, c));
                }
            var buckets = new Dictionary<Cell, List<KeyValuePair<long, Conn>>>();
            foreach (var kc in opens)
            {
                Cell cell = CellOf(kc.Value.Origin, tol);
                List<KeyValuePair<long, Conn>> list;
                if (!buckets.TryGetValue(cell, out list)) { list = new List<KeyValuePair<long, Conn>>(); buckets[cell] = list; }
                list.Add(kc);
            }
            var used = new HashSet<string>();
            int joins = 0;
            foreach (var kc in opens)
            {
                long k = kc.Key; Conn c = kc.Value;
                if (used.Contains(k + ":" + c.Cid)) continue;
                Cell cc = CellOf(c.Origin, tol);
                double bestD = 0; long bestK = 0; Conn bestC = null;
                for (int dx = -1; dx <= 1; dx++)
                    for (int dy = -1; dy <= 1; dy++)
                        for (int dz = -1; dz <= 1; dz++)
                        {
                            List<KeyValuePair<long, Conn>> list;
                            if (!buckets.TryGetValue(new Cell(cc.X + dx, cc.Y + dy, cc.Z + dz), out list)) continue;
                            foreach (var kc2 in list)
                            {
                                long k2 = kc2.Key; Conn c2 = kc2.Value;
                                if (k2 == k || used.Contains(k2 + ":" + c2.Cid)) continue;
                                double d = Dist(c.Origin, c2.Origin);
                                if (d > tol) continue;
                                if (c.Direction != null && c2.Direction != null && Dot(c.Direction, c2.Direction) > -0.5) continue;
                                if (bestC == null || d < bestD || (d == bestD && k2 < bestK)) { bestD = d; bestK = k2; bestC = c2; }
                            }
                        }
                if (bestC == null) continue;
                c.Links.Add(new KeyValuePair<long, int>(bestK, bestC.Cid));
                bestC.Links.Add(new KeyValuePair<long, int>(k, c.Cid));
                used.Add(k + ":" + c.Cid);
                used.Add(bestK + ":" + bestC.Cid);
                joins++;
            }
            return joins;
        }

        /// <summary>Does the element's box (corners in crop-box coordinates) overlap the crop box?</summary>
        public static bool BoxInCrop(List<double[]> corners, double[] mn, double[] mx, bool useZ = false, double tol = 0.0)
        {
            if (corners == null || corners.Count == 0) return true;
            int axes = useZ ? 3 : 2;
            for (int a = 0; a < axes; a++)
            {
                double lo = corners.Min(p => p[a]);
                double hi = corners.Max(p => p[a]);
                if (hi < mn[a] - tol || lo > mx[a] + tol) return false;
            }
            return true;
        }

        public static List<int> SystemsHolding(List<SysDef> systems, IEnumerable<long> idValues)
        {
            var want = new HashSet<long>(idValues ?? new long[0]);
            var o = new List<int>();
            for (int i = 0; i < systems.Count; i++) if (systems[i].Keys.Any(want.Contains)) o.Add(i);
            return o;
        }

        public static void GroupSummary(List<SysDef> systems, out int byId, out int byName, out int pieces, out int singles)
        {
            byId = systems.Count(sd => sd.Key.StartsWith("id:"));
            byName = systems.Count(sd => sd.Key.StartsWith("name:"));
            var p = systems.Where(sd => sd.Key.StartsWith("piece:")).ToList();
            pieces = p.Count;
            singles = p.Count(sd => sd.Keys.Count == 1);
        }

        private static List<KeyValuePair<long, int>> LiveLinks(Conn conn, Dictionary<long, Node> nodes, HashSet<long> visited)
        {
            return conn.Links.Where(l => nodes.ContainsKey(l.Key) && !visited.Contains(l.Key)).ToList();
        }

        private static int CompareLinks(KeyValuePair<long, int> a, KeyValuePair<long, int> b)
        {
            int c = a.Key.CompareTo(b.Key);
            return c != 0 ? c : a.Value.CompareTo(b.Value);
        }

        private static List<KeyValuePair<long, int>> SortedLinks(List<KeyValuePair<long, int>> l)
        {
            var r = new List<KeyValuePair<long, int>>(l);
            r.Sort(CompareLinks);
            return r;
        }

        private static Conn Biggest(IEnumerable<Conn> cs)
        {
            return cs.OrderBy(c => -c.Area).ThenBy(c => c.Cid).First();
        }

        /// <summary>Where the walk begins when nobody picked a start.</summary>
        public static long? ChooseStart(Dictionary<long, Node> nodes, IEnumerable<long> candidates)
        {
            List<long> keys = candidates.OrderBy(x => x).ToList();
            if (keys.Count == 0) return null;
            var cand = new HashSet<long>(keys);
            var visited = new HashSet<long>(nodes.Keys.Where(k => !cand.Contains(k)));
            Func<IEnumerable<long>, long> bySize = ks => ks.OrderBy(k => -nodes[k].Area()).ThenBy(k => k).First();

            var eq = keys.Where(k => nodes[k].IsEquipment).ToList();
            if (eq.Count > 0) return bySize(eq);
            var src = keys.Where(k => nodes[k].Conns.Any(c => c.Equipment)).ToList();
            if (src.Count > 0) return bySize(src);
            var ends = new List<long>();
            foreach (long k in keys)
            {
                int live = 0;
                foreach (Conn c in nodes[k].Conns) if (LiveLinks(c, nodes, visited).Count > 0) live++;
                if (live <= 1) ends.Add(k);
            }
            if (ends.Count > 0) return bySize(ends);
            return bySize(keys);
        }

        /// <summary>The connector the run comes in through at the start element.</summary>
        public static int? StartInlet(Node node, Dictionary<long, Node> nodes, HashSet<long> visited)
        {
            if (node.Conns.Count == 0) return null;
            var eq = node.Conns.Where(c => c.Equipment).ToList();
            if (eq.Count > 0) return Biggest(eq).Cid;
            var open = node.Conns.Where(c => LiveLinks(c, nodes, visited).Count == 0).ToList();
            if (open.Count > 0) return Biggest(open).Cid;
            return Biggest(node.Conns).Cid;
        }

        /// <summary>Neighbours to visit from node: every branch first (nearest the inlet first), then the main.</summary>
        public static List<KeyValuePair<long, int>> OrderChildren(Node node, int? inletCid, Dictionary<long, Node> nodes, HashSet<long> visited)
        {
            Conn inlet = inletCid != null ? node.Conn(inletCid.Value) : null;
            var outs = node.Conns.Where(c => (inletCid == null || c.Cid != inletCid.Value) && LiveLinks(c, nodes, visited).Count > 0).ToList();
            var seq = new List<KeyValuePair<long, int>>();
            if (outs.Count == 0) return seq;

            Func<Conn, double> straight = c =>
            {
                if (inlet == null || inlet.Direction == null || c.Direction == null) return 0.0;
                return -Dot(c.Direction, inlet.Direction);
            };
            double top = outs.Max(c => c.Area);
            var sized = outs.Where(c => c.Area >= top * (1.0 - AreaTol)).ToList();
            Conn main = sized.OrderBy(c => -straight(c)).ThenBy(c => c.Cid).First();
            var branches = outs.Where(c => !ReferenceEquals(c, main)).ToList();
            Func<Conn, double> d = c =>
            {
                double dd = 0.0;
                if (inlet != null && inlet.Origin != null && c.Origin != null) dd = Dist(inlet.Origin, c.Origin);
                return Math.Round(dd, 6);
            };
            branches = branches.OrderBy(c => d(c)).ThenBy(c => -straight(c)).ThenBy(c => c.Cid).ToList();
            foreach (Conn c in branches.Concat(new[] { main }))
                foreach (var link in SortedLinks(LiveLinks(c, nodes, visited)))
                    seq.Add(link);
            return seq;
        }

        /// <summary>Walk every node once. Branches are numbered before the main carries on. Iterative.</summary>
        public static List<long> SequenceOrder(Dictionary<long, Node> nodes, long? startKey, bool chain, out int pieces)
        {
            var order = new List<long>();
            var visited = new HashSet<long>();
            pieces = 0;
            bool first = true;
            while (visited.Count < nodes.Count)
            {
                var remaining = nodes.Keys.Where(k => !visited.Contains(k)).ToList();
                long? start;
                if (first && startKey != null && nodes.ContainsKey(startKey.Value)) start = startKey;
                else if (chain && order.Count > 0)
                {
                    start = NearestEnd(nodes, remaining, NodePoint(nodes[order[order.Count - 1]]), visited);
                    if (start == null) start = ChooseStart(nodes, remaining);
                }
                else start = ChooseStart(nodes, remaining);
                first = false;
                if (start == null) break;
                pieces++;
                int? inlet = StartInlet(nodes[start.Value], nodes, visited);
                var stack = new Stack<Tuple<long, int?, bool>>();
                stack.Push(Tuple.Create(start.Value, inlet, true));
                while (stack.Count > 0)
                {
                    var item = stack.Pop();
                    long key = item.Item1;
                    if (visited.Contains(key)) continue;
                    visited.Add(key);
                    order.Add(key);
                    Node node = nodes[key];
                    var kids = OrderChildren(node, item.Item2, nodes, visited);
                    if (item.Item3 && item.Item2 != null)
                    {
                        Conn back = node.Conn(item.Item2.Value);
                        if (back != null) foreach (var link in SortedLinks(LiveLinks(back, nodes, visited))) kids.Add(link);
                    }
                    for (int i = kids.Count - 1; i >= 0; i--)
                        if (!visited.Contains(kids[i].Key)) stack.Push(Tuple.Create(kids[i].Key, (int?)kids[i].Value, false));
                }
            }
            return order;
        }

        public static List<long> SequenceOrder(Dictionary<long, Node> nodes, long? startKey = null, bool chain = false)
        {
            int pieces;
            return SequenceOrder(nodes, startKey, chain, out pieces);
        }

        public static double[] NodePoint(Node node)
        {
            var pts = node.Conns.Where(c => c.Origin != null).Select(c => c.Origin).ToList();
            if (pts.Count == 0) return null;
            double n = pts.Count;
            return new[] { pts.Sum(p => p[0]) / n, pts.Sum(p => p[1]) / n, pts.Sum(p => p[2]) / n };
        }

        /// <summary>Split keys into connected systems. Equipment never joins two systems together.</summary>
        public static List<List<long>> Components(Dictionary<long, Node> nodes, IEnumerable<long> keysIn = null)
        {
            var keys = new HashSet<long>(keysIn ?? nodes.Keys);
            var plain = keys.Where(k => !nodes[k].IsEquipment).OrderBy(k => k).ToList();
            var owner = new Dictionary<long, int>();
            var comps = new List<List<long>>();
            foreach (long k in plain)
            {
                if (owner.ContainsKey(k)) continue;
                var comp = new List<long>();
                var queue = new Stack<long>();
                queue.Push(k);
                owner[k] = comps.Count;
                while (queue.Count > 0)
                {
                    long cur = queue.Pop();
                    comp.Add(cur);
                    foreach (Conn c in nodes[cur].Conns)
                        foreach (var l in c.Links)
                            if (keys.Contains(l.Key) && !owner.ContainsKey(l.Key) && !nodes[l.Key].IsEquipment)
                            {
                                owner[l.Key] = comps.Count;
                                queue.Push(l.Key);
                            }
                }
                comps.Add(comp);
            }
            foreach (long k in keys.Where(x => nodes[x].IsEquipment).OrderBy(x => x))
            {
                int? best = null;
                foreach (Conn c in nodes[k].Conns.OrderBy(c => -c.Area).ThenBy(c => c.Cid))
                {
                    foreach (var l in SortedLinks(c.Links))
                        if (owner.ContainsKey(l.Key)) { best = owner[l.Key]; break; }
                    if (best != null) break;
                }
                if (best == null) { owner[k] = comps.Count; comps.Add(new List<long> { k }); }
                else comps[best.Value].Add(k);
            }
            comps = comps.Select(c => c.OrderBy(x => x).ToList()).ToList();
            return comps.OrderBy(c => c[0]).ToList();
        }

        public static List<long> SystemOrder(Dictionary<long, Node> nodes, IEnumerable<long> keys, long? start = null)
        {
            var sub = new Dictionary<long, Node>();
            foreach (long k in keys) if (nodes.ContainsKey(k)) sub[k] = nodes[k];
            if (start != null && !sub.ContainsKey(start.Value)) start = null;
            return SequenceOrder(sub, start);
        }

        public static string SystemName(IEnumerable<long> keys, Dictionary<long, string> names, string fallback)
        {
            var count = new Dictionary<string, int>();
            foreach (long k in keys)
            {
                string n;
                if (names.TryGetValue(k, out n) && !string.IsNullOrEmpty(n)) count[n] = (count.ContainsKey(n) ? count[n] : 0) + 1;
            }
            if (count.Count == 0) return fallback;
            return count.OrderBy(kv => -kv.Value).ThenBy(kv => kv.Key, StringComparer.Ordinal).First().Key;
        }

        /// <summary>First and last number text each system gets, or null if it gets none.</summary>
        public static List<string[]> SystemRanges(List<PlanItem> plan, List<List<long>> systemsKeys)
        {
            var text = new Dictionary<long, string>();
            foreach (PlanItem p in plan) text[p.Key] = p.Text;
            var o = new List<string[]>();
            foreach (var keys in systemsKeys)
            {
                var got = keys.Where(text.ContainsKey).Select(k => text[k]).ToList();
                o.Add(got.Count > 0 ? new[] { got[0], got[got.Count - 1] } : null);
            }
            return o;
        }

        // ============================================================ System selector

        public class KindDef
        {
            public string Label;
            public string[] Walk;
            public string[] Through;
            public string[] Ends;
        }

        public static readonly Dictionary<string, KindDef> Kinds = new Dictionary<string, KindDef>
        {
            { "duct", new KindDef { Label = "Duct Systems",
                Walk = new[] { "OST_DuctCurves", "OST_DuctFitting", "OST_FlexDuctCurves", "OST_PlaceHolderDucts", "OST_FabricationDuctwork" },
                Through = new[] { "OST_DuctAccessory" }, Ends = new[] { "OST_DuctTerminal" } } },
            { "pipe", new KindDef { Label = "Pipe Systems",
                Walk = new[] { "OST_PipeCurves", "OST_PipeFitting", "OST_FlexPipeCurves", "OST_PlaceHolderPipes", "OST_FabricationPipework" },
                Through = new[] { "OST_PipeAccessory" }, Ends = new[] { "OST_PlumbingFixtures", "OST_Sprinklers" } } },
        };

        /// <summary>An element Revit gives no system takes the system of the nearest labelled element it is joined to.</summary>
        public static Dictionary<long, string> AssignSystems(Dictionary<long, Node> nodes, Dictionary<long, string> labels)
        {
            var o = new Dictionary<long, string>();
            foreach (long k in nodes.Keys.OrderBy(x => x))
            {
                string v;
                if (labels.TryGetValue(k, out v) && !string.IsNullOrEmpty(v)) o[k] = v;
            }
            List<long> frontier = o.Keys.OrderBy(x => x).ToList();
            while (frontier.Count > 0)
            {
                var nxt = new List<long>();
                foreach (long k in frontier)
                    foreach (Conn c in nodes[k].Conns)
                        foreach (var l in SortedLinks(c.Links))
                            if (nodes.ContainsKey(l.Key) && !o.ContainsKey(l.Key))
                            {
                                o[l.Key] = o[k];
                                nxt.Add(l.Key);
                            }
                frontier = nxt.OrderBy(x => x).ToList();
            }
            foreach (long k in nodes.Keys.OrderBy(x => x))
            {
                if (o.ContainsKey(k)) continue;
                string key = "piece:" + k;
                o[k] = key;
                var queue = new Stack<long>();
                queue.Push(k);
                while (queue.Count > 0)
                {
                    long cur = queue.Pop();
                    foreach (Conn c in nodes[cur].Conns)
                        foreach (var l in c.Links)
                            if (nodes.ContainsKey(l.Key) && !o.ContainsKey(l.Key)) { o[l.Key] = key; queue.Push(l.Key); }
                }
            }
            return o;
        }

        /// <summary>The open end (one live link or none) nearest the point, else the nearest element.</summary>
        public static long? NearestEnd(Dictionary<long, Node> nodes, IEnumerable<long> candidates, double[] point, HashSet<long> visited = null)
        {
            if (point == null) return null;
            visited = visited ?? new HashSet<long>();
            var keys = candidates.Where(k => nodes.ContainsKey(k) && !visited.Contains(k)).OrderBy(k => k).ToList();
            if (keys.Count == 0) return null;
            var ends = new List<long>();
            foreach (long k in keys)
            {
                int live = 0;
                foreach (Conn c in nodes[k].Conns) if (LiveLinks(c, nodes, visited).Count > 0) live++;
                if (live <= 1) ends.Add(k);
            }
            Func<long, double> dist = k => { double[] p = NodePoint(nodes[k]); return p != null ? Dist(p, point) : 1e30; };
            return (ends.Count > 0 ? ends : keys).OrderBy(dist).ThenBy(k => k).First();
        }

        /// <summary>Numbered in the system selector? Never an accessory, never one left out, never an unticked type.</summary>
        public static bool SelInclude(long key, HashSet<long> passthrough, HashSet<long> leftOut, Dictionary<long, string> typeOf, HashSet<string> skipped)
        {
            if (passthrough.Contains(key) || leftOut.Contains(key)) return false;
            string t;
            return !(typeOf.TryGetValue(key, out t) && skipped.Contains(t));
        }

        public class WalkResult
        {
            public List<long> Order;
            public long? Start;
            public string How;
            public double[] ExitPoint;
        }

        public static WalkResult WalkSystem(Dictionary<long, Node> nodes, SysDef sysd, double[] exitPoint, Func<long, bool> include)
        {
            var sub = new Dictionary<long, Node>();
            foreach (long k in sysd.Keys) if (nodes.ContainsKey(k)) sub[k] = nodes[k];
            long? st = sysd.Start;
            string how = "picked";
            if (st == null || !sub.ContainsKey(st.Value))
            {
                st = null;
                how = "auto";
                if (exitPoint != null && sub.Count > 0)
                {
                    st = NearestEnd(sub, sub.Keys.ToList(), exitPoint);
                    how = "nearest";
                }
            }
            List<long> order = SequenceOrder(sub, st, true);
            long? last = null;
            for (int i = order.Count - 1; i >= 0; i--)
                if (include == null || include(order[i])) { last = order[i]; break; }
            if (last == null && order.Count > 0) last = order[order.Count - 1];
            double[] newExit = exitPoint;
            if (last != null)
            {
                double[] p = NodePoint(nodes[last.Value]);
                if (p != null) newExit = p;
            }
            return new WalkResult { Order = order, Start = order.Count > 0 ? (long?)order[0] : null, How = how, ExitPoint = newExit };
        }

        /// <summary>Each system after the first starts at its open end nearest where the previous one finished numbering.</summary>
        public static List<long> SelectorOrder(Dictionary<long, Node> nodes, List<SysDef> systems, Func<long, bool> include,
                                               out List<KeyValuePair<int, int>> spans, out List<KeyValuePair<long?, string>> starts)
        {
            var order = new List<long>();
            spans = new List<KeyValuePair<int, int>>();
            starts = new List<KeyValuePair<long?, string>>();
            double[] exit = null;
            foreach (SysDef sd in systems)
            {
                WalkResult w = WalkSystem(nodes, sd, exit, include);
                exit = w.ExitPoint;
                int a = order.Count;
                order.AddRange(w.Order);
                spans.Add(new KeyValuePair<int, int>(a, order.Count));
                starts.Add(new KeyValuePair<long?, string>(w.Start, w.How));
            }
            return order;
        }

        public static double CompDistance(Dictionary<long, Node> nodes, IEnumerable<long> comp, double[] point)
        {
            double? best = null;
            foreach (long k in comp)
            {
                if (!nodes.ContainsKey(k)) continue;
                double[] p = NodePoint(nodes[k]);
                if (p == null) continue;
                double d = Dist(p, point);
                if (best == null || d < best.Value) best = d;
            }
            return best ?? 1e30;
        }

        /// <summary>Re-order: the system holding a picked start first, then each next the nearest to where the last finished.</summary>
        public static List<SysDef> AutoOrder(Dictionary<long, Node> nodes, List<SysDef> systems, Func<long, bool> include = null)
        {
            if (systems.Count < 2) return new List<SysDef>(systems);
            SysDef first = systems.FirstOrDefault(sd => sd.Start != null) ?? systems[0];
            var left = systems.Where(sd => !ReferenceEquals(sd, first)).ToList();
            var o = new List<SysDef> { first };
            double[] exit = WalkSystem(nodes, first, null, include).ExitPoint;
            while (left.Count > 0)
            {
                SysDef nxt;
                if (exit == null) nxt = left[0];
                else { double[] ex = exit; nxt = left.OrderBy(sd => CompDistance(nodes, sd.Keys, ex)).ThenBy(sd => left.IndexOf(sd)).First(); }
                left.Remove(nxt);
                o.Add(nxt);
                exit = WalkSystem(nodes, nxt, exit, include).ExitPoint;
            }
            return o;
        }

        public static double[] ExitAfter(Dictionary<long, Node> nodes, List<SysDef> systems, int upto, Func<long, bool> include = null)
        {
            double[] exit = null;
            for (int i = 0; i <= upto && i < systems.Count; i++) exit = WalkSystem(nodes, systems[i], exit, include).ExitPoint;
            return exit;
        }

        /// <summary>Auto next: of the systems not yet placed, the one whose start is closest to where systems[lastIndex] finishes. Returns index and distance, or null.</summary>
        public static KeyValuePair<int, double>? NextNearest(Dictionary<long, Node> nodes, List<SysDef> systems, int lastIndex, HashSet<string> placed, Func<long, bool> include = null)
        {
            double[] point = ExitAfter(nodes, systems, lastIndex, include);
            KeyValuePair<int, double>? best = null;
            for (int i = 0; i < systems.Count; i++)
            {
                SysDef sd = systems[i];
                if (placed.Contains(sd.Key)) continue;
                var sub = new Dictionary<long, Node>();
                foreach (long k in sd.Keys) if (nodes.ContainsKey(k)) sub[k] = nodes[k];
                double d = 1e30;
                if (point != null && sub.Count > 0)
                {
                    long? k = NearestEnd(sub, sub.Keys.ToList(), point);
                    double[] p = k != null ? NodePoint(nodes[k.Value]) : null;
                    if (p != null) d = Dist(p, point);
                }
                if (best == null || d < best.Value.Value || (d == best.Value.Value && i < best.Value.Key))
                    best = new KeyValuePair<int, double>(i, d);
            }
            return best;
        }

        // ---------------------------------------------------- list moves

        public static List<T> MoveItem<T>(List<T> items, int src, int dst, out int newDst)
        {
            var l = new List<T>(items);
            newDst = src;
            if (src < 0 || src >= l.Count) return l;
            dst = Math.Max(0, Math.Min(l.Count - 1, dst));
            T it = l[src];
            l.RemoveAt(src);
            l.Insert(dst, it);
            newDst = dst;
            return l;
        }

        /// <summary>A row dragged onto target lands above it. Moving down, removing the dragged row first shifts target by one.</summary>
        public static int DropIndex(int src, int target) { return src < target ? target - 1 : target; }

        public static HashSet<int> ClickSelection(HashSet<int> selected, int? anchor, int index, bool ctrl, bool shift, out int? newAnchor)
        {
            var sel = new HashSet<int>(selected ?? new HashSet<int>());
            if (shift && anchor != null)
            {
                int lo = Math.Min(anchor.Value, index), hi = Math.Max(anchor.Value, index);
                var rng = new HashSet<int>();
                for (int i = lo; i <= hi; i++) rng.Add(i);
                newAnchor = anchor;
                if (ctrl) { sel.UnionWith(rng); return sel; }
                return rng;
            }
            if (ctrl)
            {
                if (sel.Contains(index) && sel.Count > 1) sel.Remove(index); else sel.Add(index);
                newAnchor = index;
                return sel;
            }
            newAnchor = index;
            return new HashSet<int> { index };
        }

        /// <summary>Up / Down through n rows, wrapping round at the ends.</summary>
        public static int? StepIndex(int n, int? current, int delta)
        {
            if (n <= 0) return null;
            if (current == null) return delta > 0 ? 0 : n - 1;
            return (((current.Value + delta) % n) + n) % n;
        }

        /// <summary>Move every selected row one place up (-1) or down (+1); rows already at the end stay.</summary>
        public static List<T> MoveBlock<T>(List<T> items, IEnumerable<int> selected, int delta, out HashSet<int> newSelected)
        {
            var l = new List<T>(items);
            var sel = new HashSet<int>(selected.Where(i => i >= 0 && i < l.Count));
            var order = delta < 0 ? sel.OrderBy(i => i).ToList() : sel.OrderByDescending(i => i).ToList();
            foreach (int i in order)
            {
                int j = i + delta;
                if (j >= 0 && j < l.Count && !sel.Contains(j))
                {
                    T tmp = l[i]; l[i] = l[j]; l[j] = tmp;
                    sel.Remove(i);
                    sel.Add(j);
                }
            }
            newSelected = sel;
            return l;
        }

        /// <summary>Move the selected rows, keeping their order, so they sit just before the row that was at insertBefore.</summary>
        public static List<T> MoveMany<T>(List<T> items, IEnumerable<int> selected, int insertBefore, out HashSet<int> newSelected)
        {
            var l = new List<T>(items);
            var sel = selected.Where(i => i >= 0 && i < l.Count).Distinct().OrderBy(i => i).ToList();
            var selSet = new HashSet<int>(sel);
            var moving = sel.Select(i => l[i]).ToList();
            var keep = l.Where((it, i) => !selSet.Contains(i)).ToList();
            int at = insertBefore - sel.Count(i => i < insertBefore);
            at = Math.Max(0, Math.Min(keep.Count, at));
            var o = keep.Take(at).Concat(moving).Concat(keep.Skip(at)).ToList();
            newSelected = new HashSet<int>(Enumerable.Range(at, moving.Count));
            return o;
        }

        /// <summary>Systems whose every numberable element has been removed leave the list. batch: (key of the row it followed or null, system).</summary>
        public static List<SysDef> SplitGone(List<SysDef> systems, HashSet<long> leftOut, out List<KeyValuePair<string, SysDef>> batch)
        {
            var kept = new List<SysDef>();
            batch = new List<KeyValuePair<string, SysDef>>();
            string before = null;
            foreach (SysDef sd in systems)
            {
                if (sd.Num.Count > 0 && sd.Num.All(leftOut.Contains)) batch.Add(new KeyValuePair<string, SysDef>(before, sd));
                else kept.Add(sd);
                before = sd.Key;
            }
            return kept;
        }

        /// <summary>Undo the drops newest batch first, each system going back straight after the row it followed.</summary>
        public static List<SysDef> BringBack(List<SysDef> systems, List<List<KeyValuePair<string, SysDef>>> batches)
        {
            var o = new List<SysDef>(systems);
            for (int b = batches.Count - 1; b >= 0; b--)
                foreach (var pair in batches[b])
                {
                    int at;
                    if (pair.Key == null) at = 0;
                    else
                    {
                        int idx = o.FindIndex(x => x.Key == pair.Key);
                        at = idx >= 0 ? idx + 1 : o.Count;
                    }
                    o.Insert(at, pair.Value);
                }
            return o;
        }

        /// <summary>The sequence number (#) of items[index]: rows up to and including it that count, plus any in always.</summary>
        public static int PositionOf<T>(List<T> items, int index, Func<T, bool> counted, IEnumerable<T> always = null) where T : class
        {
            var keep = always != null ? new List<T>(always) : new List<T>();
            int n = 0;
            for (int i = 0; i <= index && i < items.Count; i++)
                if (counted(items[i]) || keep.Any(a => ReferenceEquals(a, items[i]))) n++;
            return n;
        }

        /// <summary>Move the selected rows as a block so the first becomes number position (1 = first).</summary>
        public static List<T> MoveToPosition<T>(List<T> items, IEnumerable<int> selected, int position, Func<T, bool> counted,
                                                out HashSet<int> newSelected, out int lastNumber) where T : class
        {
            var l = new List<T>(items);
            var sel = selected.Where(i => i >= 0 && i < l.Count).Distinct().OrderBy(i => i).ToList();
            lastNumber = 0;
            newSelected = new HashSet<int>();
            if (sel.Count == 0) return l;
            var selSet = new HashSet<int>(sel);
            var moving = sel.Select(i => l[i]).ToList();
            var rest = l.Where((it, i) => !selSet.Contains(i)).ToList();
            int want = Math.Max(1, position) - 1;
            int at = rest.Count;
            int n = 0;
            for (int i = 0; i < rest.Count; i++)
            {
                if (n >= want) { at = i; break; }
                if (counted(rest[i])) n++;
            }
            var o = rest.Take(at).Concat(moving).Concat(rest.Skip(at)).ToList();
            newSelected = new HashSet<int>(Enumerable.Range(at, moving.Count));
            lastNumber = PositionOf(o, at + moving.Count - 1, counted, moving);
            return o;
        }

        // ---------------------------------------------------- views table

        private static bool Passes(ViewRowData v, Dictionary<string, string> filters, Dictionary<string, HashSet<string>> excluded, string skipCol = null)
        {
            if (filters != null)
                foreach (var kv in filters)
                    if (kv.Key != skipCol && !Matches(v.Get(kv.Key), kv.Value)) return false;
            if (excluded != null)
                foreach (var kv in excluded)
                    if (kv.Key != skipCol && kv.Value.Contains(v.Get(kv.Key))) return false;
            return true;
        }

        public static List<ViewRowData> ViewRows(List<ViewRowData> views, Dictionary<string, string> filters, string sortCol, bool descending,
                                                 HashSet<string> only = null, Dictionary<string, HashSet<string>> excluded = null)
        {
            var o = new List<ViewRowData>();
            foreach (ViewRowData v in views)
            {
                if (only != null && !only.Contains(v.Id)) continue;
                if (Passes(v, filters, excluded)) o.Add(v);
            }
            var cmp = new NaturalKeyComparer();
            o = o.OrderBy(v => v.Get(sortCol) == "" ? 1 : 0)
                 .ThenBy(v => NaturalKey(v.Get(sortCol)), cmp)
                 .ThenBy(v => NaturalKey(v.Name), cmp).ToList();
            if (descending)
            {
                var blanks = o.Where(v => v.Get(sortCol) == "").ToList();
                var filled = o.Where(v => v.Get(sortCol) != "").ToList();
                filled.Reverse();
                o = filled.Concat(blanks).ToList();
            }
            return o;
        }

        /// <summary>The value list for a column heading, Excel style, with counts, natural order, blank last.</summary>
        public static List<KeyValuePair<string, int>> ColumnValues(List<ViewRowData> views, string col, Dictionary<string, string> filters,
                                                                   Dictionary<string, HashSet<string>> excluded, HashSet<string> only = null)
        {
            var counts = new Dictionary<string, int>();
            foreach (ViewRowData v in views)
            {
                if (only != null && !only.Contains(v.Id)) continue;
                if (!Passes(v, filters, excluded, col)) continue;
                string val = v.Get(col);
                counts[val] = (counts.ContainsKey(val) ? counts[val] : 0) + 1;
            }
            return counts.OrderBy(kv => kv.Key == "" ? 1 : 0).ThenBy(kv => NaturalKey(kv.Key), new NaturalKeyComparer()).ToList();
        }

        public static HashSet<string> TickValues(HashSet<string> excluded, IEnumerable<string> values, bool on)
        {
            var o = new HashSet<string>(excluded ?? new HashSet<string>());
            foreach (string val in values) { if (on) o.Remove(val); else o.Add(val); }
            return o;
        }

        public static readonly Dictionary<string, string> TagViewKinds = new Dictionary<string, string>
        {
            { "FloorPlan", "Floor plan" }, { "Section", "Section" }, { "ThreeD", "3D" },
        };
        public static readonly string[] KindOrder = { "Floor plan", "Section", "3D" };

        public static string KindText(string kind, bool locked = true)
        {
            return kind != "3D" || locked ? kind : "3D (unlocked)";
        }

        public static string DefaultGroupParam(List<string> names, string saved, int n)
        {
            if (saved == NoneMark) return "";
            if (!string.IsNullOrEmpty(saved) && names.Contains(saved)) return saved;
            var hits = names.Where(x => new[] { "group", "discipline", "series" }.Any(w => x.ToLowerInvariant().Contains(w))).ToList();
            return hits.Count > n ? hits[n] : "";
        }

        public static int? ParsePosition(string text, int lo, int hi)
        {
            string t = (text ?? "").Trim().TrimStart('#');
            if (t.Length == 0 || !t.All(ch => ch >= '0' && ch <= '9')) return null;
            int n;
            if (!int.TryParse(t, out n)) return null;
            return n >= lo && n <= hi ? (int?)n : null;
        }

        public static int DropBefore(int target, bool below) { return below ? target + 1 : target; }

        /// <summary>Elements the user picked in Revit that are in the sequence - none when it is the selection the tool just made.</summary>
        public static List<long> UserSelection(IEnumerable<long> eventIds, IEnumerable<long> ownIds, IEnumerable<long> sequenceKeys)
        {
            var ids = new HashSet<long>(eventIds ?? new long[0]);
            if (ownIds != null && ids.SetEquals(ownIds)) return new List<long>();
            var seq = new HashSet<long>(sequenceKeys);
            return ids.Where(seq.Contains).OrderBy(x => x).ToList();
        }

        /// <summary>Elements drawn in the start colour: the first element numbered, and every start picked by hand.</summary>
        public static HashSet<long> StartKeys(List<long> order, List<SysDef> systems)
        {
            var o = new HashSet<long>();
            if (order.Count > 0) o.Add(order[0]);
            foreach (SysDef sd in systems) if (sd.Start != null) o.Add(sd.Start.Value);
            return o;
        }

        // ---------------------------------------------------- natural order

        public struct NatPart
        {
            public int Kind; public string Word; public System.Numerics.BigInteger Num;
        }

        /// <summary>'SA 10' sorts after 'SA 9'.</summary>
        public static List<NatPart> NaturalKey(string text)
        {
            var o = new List<NatPart>();
            var num = new StringBuilder();
            var word = new StringBuilder();
            foreach (char ch in text ?? "")
            {
                if (char.IsDigit(ch))
                {
                    if (word.Length > 0) { o.Add(new NatPart { Kind = 1, Word = word.ToString().ToLowerInvariant() }); word.Clear(); }
                    num.Append(ch);
                }
                else
                {
                    if (num.Length > 0) { o.Add(new NatPart { Kind = 0, Word = "", Num = System.Numerics.BigInteger.Parse(num.ToString()) }); num.Clear(); }
                    word.Append(ch);
                }
            }
            if (word.Length > 0) o.Add(new NatPart { Kind = 1, Word = word.ToString().ToLowerInvariant() });
            if (num.Length > 0) o.Add(new NatPart { Kind = 0, Word = "", Num = System.Numerics.BigInteger.Parse(num.ToString()) });
            return o;
        }

        public class NaturalKeyComparer : IComparer<List<NatPart>>
        {
            public int Compare(List<NatPart> a, List<NatPart> b)
            {
                int n = Math.Min(a.Count, b.Count);
                for (int i = 0; i < n; i++)
                {
                    int c = a[i].Kind.CompareTo(b[i].Kind);
                    if (c != 0) return c;
                    c = string.CompareOrdinal(a[i].Word, b[i].Word);
                    if (c != 0) return c;
                    c = a[i].Num.CompareTo(b[i].Num);
                    if (c != 0) return c;
                }
                return a.Count.CompareTo(b.Count);
            }
        }

        public static int NaturalCompare(string a, string b)
        {
            return new NaturalKeyComparer().Compare(NaturalKey(a), NaturalKey(b));
        }

        // ---------------------------------------------------- colours

        private static string HsvHex(double h, double s, double v)
        {
            int i = (int)(h * 6.0) % 6;
            double f = h * 6.0 - (int)(h * 6.0);
            double p = v * (1.0 - s);
            double q = v * (1.0 - s * f);
            double t = v * (1.0 - s * (1.0 - f));
            double r, g, b;
            switch (i)
            {
                case 0: r = v; g = t; b = p; break;
                case 1: r = q; g = v; b = p; break;
                case 2: r = p; g = v; b = t; break;
                case 3: r = p; g = q; b = v; break;
                case 4: r = t; g = p; b = v; break;
                default: r = v; g = p; b = q; break;
            }
            return "#" + ((int)(r * 255 + 0.5)).ToString("X2") + ((int)(g * 255 + 0.5)).ToString("X2") + ((int)(b * 255 + 0.5)).ToString("X2");
        }

        public const string StartColour = "#FF00FF";
        public const double StartGap = 110;
        public const int StartWeight = 12;
        public const int ColourMark = 1;

        /// <summary>n colours, every one different: hues stepped by the golden angle, saturation and brightness alternating.</summary>
        public static List<string> DistinctColours(int n)
        {
            var o = new List<string>();
            var seen = new HashSet<string>();
            int i = 0;
            double[] sat = { 0.80, 0.55, 0.95 };
            double[] val = { 0.95, 0.75, 0.60 };
            while (o.Count < n)
            {
                double h = (i * 0.618033988749895 + 0.07) % 1.0;
                string c = HsvHex(h, sat[i % 3], val[(i / 3) % 3]);
                if (!seen.Contains(c) && ColourDistance(c, StartColour) >= StartGap)
                {
                    seen.Add(c);
                    o.Add(c);
                }
                i++;
            }
            return o;
        }

        private static HashSet<string> _palette;

        public static string RgbHex(int r, int g, int b)
        {
            return "#" + r.ToString("X2") + g.ToString("X2") + b.ToString("X2");
        }

        /// <summary>Every colour the tool has ever given a system (and the start).</summary>
        public static HashSet<string> ToolPalette()
        {
            if (_palette == null)
            {
                _palette = new HashSet<string>(DistinctColours(1000));
                _palette.Add(StartColour);
            }
            return _palette;
        }

        /// <summary>colours: (r,g,b) or null for projection line, cut line, surface pattern and cut pattern.</summary>
        public static bool IsToolColouring(List<int[]> colours, int transparency)
        {
            if (colours == null || colours.Count == 0 || colours[0] == null) return false;
            foreach (int[] c in colours)
                if (c == null || c[0] != colours[0][0] || c[1] != colours[0][1] || c[2] != colours[0][2]) return false;
            if (transparency == ColourMark) return true;
            return ToolPalette().Contains(RgbHex(colours[0][0], colours[0][1], colours[0][2]));
        }

        public static void HexRgb(string hex, out int r, out int g, out int b)
        {
            string t = (hex ?? "#000000").TrimStart('#');
            r = Convert.ToInt32(t.Substring(0, 2), 16);
            g = Convert.ToInt32(t.Substring(2, 2), 16);
            b = Convert.ToInt32(t.Substring(4, 2), 16);
        }

        public static double ColourDistance(string a, string b)
        {
            int ra, ga, ba, rb, gb, bb;
            HexRgb(a, out ra, out ga, out ba);
            HexRgb(b, out rb, out gb, out bb);
            return Math.Sqrt((ra - rb) * (ra - rb) + (ga - gb) * (ga - gb) + (ba - bb) * (ba - bb));
        }

        /// <summary>After a refresh: keep the user's order, ticks, starts and colours for systems still there; new systems go on the end.</summary>
        public static List<SysDef> MergeSystems(List<SysDef> old, List<SysDef> nw)
        {
            var byKey = new Dictionary<string, SysDef>();
            foreach (SysDef sd in nw) byKey[sd.Key] = sd;
            var o = new List<SysDef>();
            foreach (SysDef sd in old)
            {
                SysDef n;
                if (!byKey.TryGetValue(sd.Key, out n)) continue;
                byKey.Remove(sd.Key);
                n.On = sd.On;
                if (!string.IsNullOrEmpty(sd.Colour)) n.Colour = sd.Colour;
                if (sd.Start != null && n.Keys.Contains(sd.Start.Value)) n.Start = sd.Start;
                o.Add(n);
            }
            foreach (SysDef sd in nw) if (byKey.ContainsKey(sd.Key)) o.Add(sd);
            return o;
        }

        // ============================================================ Category > family > type tree

        public static string TypeKey(string cat, string fam, string typ) { return cat + "|" + fam + "|" + typ; }

        private static string Lk(string s) { return (s ?? "").ToLowerInvariant(); }

        public class TreeRow { public long ElementKey; public string Category; public string Family; public string Type; }

        /// <summary>Sorted by category, then family, then type, case-insensitive.</summary>
        public static List<CategoryNode> BuildTree(IEnumerable<TreeRow> rows)
        {
            var cats = new Dictionary<string, Dictionary<string, Dictionary<string, List<long>>>>();
            foreach (TreeRow r in rows)
            {
                string cat = string.IsNullOrEmpty(r.Category) ? "(no category)" : r.Category;
                string fam = string.IsNullOrEmpty(r.Family) ? "(no family)" : r.Family;
                string typ = string.IsNullOrEmpty(r.Type) ? "(no type)" : r.Type;
                if (!cats.ContainsKey(cat)) cats[cat] = new Dictionary<string, Dictionary<string, List<long>>>();
                if (!cats[cat].ContainsKey(fam)) cats[cat][fam] = new Dictionary<string, List<long>>();
                if (!cats[cat][fam].ContainsKey(typ)) cats[cat][fam][typ] = new List<long>();
                cats[cat][fam][typ].Add(r.ElementKey);
            }
            Func<string, string, int> cmp = (a, b) => { int c = string.CompareOrdinal(Lk(a), Lk(b)); return c != 0 ? c : string.CompareOrdinal(a, b); };
            var o = new List<CategoryNode>();
            var catKeys = cats.Keys.ToList(); catKeys.Sort((a, b) => cmp(a, b));
            foreach (string cat in catKeys)
            {
                var cn = new CategoryNode { Name = cat };
                var famKeys = cats[cat].Keys.ToList(); famKeys.Sort((a, b) => cmp(a, b));
                foreach (string fam in famKeys)
                {
                    var fn = new FamilyNode { Name = fam };
                    var typKeys = cats[cat][fam].Keys.ToList(); typKeys.Sort((a, b) => cmp(a, b));
                    foreach (string typ in typKeys)
                        fn.Types.Add(new TypeNode { Name = typ, Key = TypeKey(cat, fam, typ), Ids = cats[cat][fam][typ] });
                    cn.Families.Add(fn);
                }
                o.Add(cn);
            }
            return o;
        }

        public static int TreeCount(CategoryNode c) { return c.Families.Sum(f => TreeCount(f)); }
        public static int TreeCount(FamilyNode f) { return f.Types.Sum(t => t.Ids.Count); }

        /// <summary>true all included, false none, null mixed.</summary>
        public static bool? GroupState(IList<string> typeKeys, HashSet<string> skipped)
        {
            int inc = typeKeys.Count(k => !skipped.Contains(k));
            if (inc == typeKeys.Count) return true;
            if (inc == 0) return false;
            return null;
        }

        public static bool Matches(string text, string query)
        {
            string q = (query ?? "").Trim().ToLowerInvariant();
            if (q.Length == 0) return true;
            string t = (text ?? "").ToLowerInvariant();
            foreach (string word in q.Split((char[])null, StringSplitOptions.RemoveEmptyEntries))
                if (!t.Contains(word)) return false;
            return true;
        }

        // ============================================================ Parameters and tags

        public static readonly string[] ParamPreference = { "Item Number", "BGL_Item Number", "Mark", "BGL_Sequence Number", "Comments" };

        public class ParamRow { public string Name; public string Storage; public int Count; }

        public static List<ParamRow> ParamList(Dictionary<string, string> storages, Dictionary<long, List<string>> perElem, IEnumerable<long> keys)
        {
            var count = new Dictionary<string, int>();
            foreach (long k in keys)
            {
                List<string> names;
                if (!perElem.TryGetValue(k, out names)) continue;
                foreach (string n in names) count[n] = (count.ContainsKey(n) ? count[n] : 0) + 1;
            }
            var o = count.Select(kv => new ParamRow { Name = kv.Key, Storage = storages.ContainsKey(kv.Key) ? storages[kv.Key] : "text", Count = kv.Value }).ToList();
            o.Sort((a, b) => { int c = string.CompareOrdinal(a.Name.ToLowerInvariant(), b.Name.ToLowerInvariant()); return c != 0 ? c : string.CompareOrdinal(a.Name, b.Name); });
            return o;
        }

        public static List<ParamRow> FilterParams(List<ParamRow> ps, string typed)
        {
            string t = (typed ?? "").Trim().ToLowerInvariant();
            if (t.Length == 0) return new List<ParamRow>(ps);
            var starts = ps.Where(p => p.Name.ToLowerInvariant().StartsWith(t)).ToList();
            var inside = ps.Where(p => p.Name.ToLowerInvariant().Contains(t) && !p.Name.ToLowerInvariant().StartsWith(t)).ToList();
            return starts.Concat(inside).ToList();
        }

        public static string ExactParam(List<ParamRow> ps, string typed)
        {
            string t = (typed ?? "").Trim().ToLowerInvariant();
            foreach (ParamRow p in ps) if (p.Name.ToLowerInvariant() == t) return p.Name;
            return null;
        }

        public static string DefaultParameter(List<string> names, string saved)
        {
            if (!string.IsNullOrEmpty(saved) && names.Contains(saved)) return saved;
            foreach (string p in ParamPreference) if (names.Contains(p)) return p;
            return names.Count > 0 ? names[0] : "";
        }

        /// <summary>tag category -> host categories it can tag (null = anything).</summary>
        public static readonly Dictionary<string, string[]> TagHosts = new Dictionary<string, string[]>
        {
            { "OST_DuctTags", new[] { "OST_DuctCurves", "OST_PlaceHolderDucts" } },
            { "OST_DuctFittingTags", new[] { "OST_DuctFitting" } },
            { "OST_DuctAccessoryTags", new[] { "OST_DuctAccessory" } },
            { "OST_DuctTerminalTags", new[] { "OST_DuctTerminal" } },
            { "OST_FlexDuctTags", new[] { "OST_FlexDuctCurves" } },
            { "OST_FabricationDuctworkTags", new[] { "OST_FabricationDuctwork" } },
            { "OST_MechanicalEquipmentTags", new[] { "OST_MechanicalEquipment" } },
            { "OST_PipeTags", new[] { "OST_PipeCurves", "OST_PlaceHolderPipes" } },
            { "OST_PipeFittingTags", new[] { "OST_PipeFitting" } },
            { "OST_PipeAccessoryTags", new[] { "OST_PipeAccessory" } },
            { "OST_FlexPipeTags", new[] { "OST_FlexPipeCurves" } },
            { "OST_FabricationPipeworkTags", new[] { "OST_FabricationPipework" } },
            { "OST_MultiCategoryTags", null },
        };

        /// <summary>Which tab a tag type is offered on (null = both).</summary>
        public static readonly Dictionary<string, string> TagKind = new Dictionary<string, string>
        {
            { "OST_DuctTags", "duct" }, { "OST_DuctFittingTags", "duct" }, { "OST_DuctAccessoryTags", "duct" },
            { "OST_DuctTerminalTags", "duct" }, { "OST_FlexDuctTags", "duct" }, { "OST_FabricationDuctworkTags", "duct" },
            { "OST_MechanicalEquipmentTags", null },
            { "OST_PipeTags", "pipe" }, { "OST_PipeFittingTags", "pipe" }, { "OST_PipeAccessoryTags", "pipe" },
            { "OST_FlexPipeTags", "pipe" }, { "OST_FabricationPipeworkTags", "pipe" },
            { "OST_MultiCategoryTags", null },
        };

        public static List<TagChoice> TagsForKind(List<TagChoice> tags, string kind)
        {
            return tags.Where(t => { string k; TagKind.TryGetValue(t.TagCat, out k); return k == null || k == kind; }).ToList();
        }

        public static readonly string[] PlanViews = { "FloorPlan", "CeilingPlan", "EngineeringPlan", "AreaPlan" };
        public static readonly string[] TaggableViews = { "FloorPlan", "CeilingPlan", "EngineeringPlan", "AreaPlan", "Section", "Elevation", "Detail" };

        /// <summary>(ok, why) for placing tags in a view of this type.</summary>
        public static bool TagViewOk(string viewType, out string why, bool isTemplate = false, bool locked3d = false, bool plansOnly = false)
        {
            why = "";
            if (isTemplate) { why = "The active view is a template"; return false; }
            if (plansOnly)
            {
                if (PlanViews.Contains(viewType)) return true;
                why = "tags go on plan views only (the active view is " + viewType + ")";
                return false;
            }
            if (TaggableViews.Contains(viewType)) return true;
            if (viewType == "ThreeD")
            {
                if (locked3d) return true;
                why = "Lock the 3D view to tag in it";
                return false;
            }
            why = "The active view (" + viewType + ") cannot take tags";
            return false;
        }

        public static bool TagCanHost(string tagCat, string hostCat)
        {
            string[] hosts;
            if (!TagHosts.TryGetValue(tagCat, out hosts)) return false;
            if (hosts == null) return true;
            return hosts.Contains(hostCat);
        }

        /// <summary>The chosen tag where it can take that category, else the first loaded tag made for it, else a multi-category tag.</summary>
        public static Dictionary<string, TagChoice> TagForHosts(List<TagChoice> tags, TagChoice chosen, IEnumerable<string> hostCats)
        {
            TagChoice multi = tags.FirstOrDefault(t => t.TagCat == "OST_MultiCategoryTags");
            var o = new Dictionary<string, TagChoice>();
            foreach (string h in hostCats.Distinct())
            {
                if (chosen != null && TagCanHost(chosen.TagCat, h)) { o[h] = chosen; continue; }
                TagChoice own = tags.FirstOrDefault(t => t.TagCat != "OST_MultiCategoryTags" && TagCanHost(t.TagCat, h));
                o[h] = own ?? multi;
            }
            return o;
        }

        public static void TagPlanNote(Dictionary<string, TagChoice> byHost, TagChoice chosen, IEnumerable<string> hostCats,
                                       out int yes, out int no, out List<KeyValuePair<string, int>> others)
        {
            yes = 0; no = 0;
            var d = new Dictionary<string, int>();
            foreach (string h in hostCats)
            {
                TagChoice t;
                if (!byHost.TryGetValue(h, out t) || t == null) { no++; continue; }
                yes++;
                if (chosen == null || !ReferenceEquals(t, chosen)) d[t.Label] = (d.ContainsKey(t.Label) ? d[t.Label] : 0) + 1;
            }
            others = d.OrderBy(kv => kv.Key, StringComparer.Ordinal).ToList();
        }

        /// <summary>Untagged only: any tag there means leave it; otherwise only the same tag again is left.</summary>
        public static bool SkipTagging(ICollection<long> have, long tagType, bool untaggedOnly)
        {
            if (untaggedOnly) return have.Count > 0;
            return have.Contains(tagType);
        }

        public static void TagCoverage(string tagCat, IEnumerable<string> planHostCats, out int yes, out int no)
        {
            yes = 0; no = 0;
            foreach (string h in planHostCats) { if (TagCanHost(tagCat, h)) yes++; else no++; }
        }

        // ============================================================ Isolate in 3D

        public static List<string> Default3dNames(string user)
        {
            var names = new List<string>();
            if (!string.IsNullOrEmpty(user)) names.Add("{3D - " + user + "}");
            names.Add("{3D}");
            return names;
        }

        public static string PickDefault3d(IEnumerable<string> viewNames, IEnumerable<string> wanted)
        {
            var have = new HashSet<string>(viewNames);
            foreach (string n in wanted) if (have.Contains(n)) return n;
            var others = have.Where(n => n.StartsWith("{3D")).ToList();
            others.Sort(NaturalCompare);
            return others.Count > 0 ? others[0] : null;
        }

        /// <summary>Items for the 3D view picker: Default first, then each 3D view. A chosen view no longer in the model falls back to Default.</summary>
        public static List<KeyValuePair<string, string>> Combo3dItems(IEnumerable<KeyValuePair<string, string>> views, string chosen, out int index)
        {
            var items = new List<KeyValuePair<string, string>> { new KeyValuePair<string, string>("", "Default 3D view") };
            items.AddRange(views);
            index = 0;
            for (int i = 0; i < items.Count; i++) if (!string.IsNullOrEmpty(chosen) && items[i].Key == chosen) index = i;
            return items;
        }

        // ============================================================ System groups

        public const double GroupBand = 0.08;
        public const double MagentaHue = 300.0 / 360.0;
        public const double MagentaGap = 0.09;

        /// <summary>Hue 0..1 of a colour, null for a grey.</summary>
        public static double? HexHue(string hex)
        {
            int ri, gi, bi;
            HexRgb(hex, out ri, out gi, out bi);
            double r = ri / 255.0, g = gi / 255.0, b = bi / 255.0;
            double mx = Math.Max(r, Math.Max(g, b)), mn = Math.Min(r, Math.Min(g, b));
            if (mx - mn < 1e-6) return null;
            double d = mx - mn, h;
            if (mx == r) { h = ((g - b) / d) % 6.0; if (h < 0) h += 6.0; }
            else if (mx == g) h = (b - r) / d + 2.0;
            else h = (r - g) / d + 4.0;
            double res = (h / 6.0) % 1.0;
            return res < 0 ? res + 1.0 : res;
        }

        public static double HueGap(double a, double b)
        {
            double d = Math.Abs(a - b) % 1.0;
            return Math.Min(d, 1.0 - d);
        }

        public static Dictionary<string, string> CleanGroups(Dictionary<string, string> groups, IEnumerable<string> keys)
        {
            var keySet = new HashSet<string>(keys);
            var g = (groups ?? new Dictionary<string, string>()).Where(kv => keySet.Contains(kv.Key)).ToDictionary(kv => kv.Key, kv => kv.Value);
            var counts = new Dictionary<string, int>();
            foreach (string v in g.Values) counts[v] = (counts.ContainsKey(v) ? counts[v] : 0) + 1;
            return g.Where(kv => counts[kv.Value] >= 2).ToDictionary(kv => kv.Key, kv => kv.Value);
        }

        private static string GidOf(Dictionary<string, string> groups, string key)
        {
            string v;
            return groups.TryGetValue(key, out v) ? v : null;
        }

        /// <summary>Each group's members together, where its first member is, in their order.</summary>
        public static List<SysDef> GatherGroups(List<SysDef> systems, Dictionary<string, string> groups)
        {
            var o = new List<SysDef>();
            var done = new HashSet<string>();
            foreach (SysDef sd in systems)
            {
                string gid = GidOf(groups, sd.Key);
                if (gid == null) o.Add(sd);
                else if (!done.Contains(gid))
                {
                    done.Add(gid);
                    o.AddRange(systems.Where(x => GidOf(groups, x.Key) == gid));
                }
            }
            return o;
        }

        /// <summary>The list as moving parts: each group one unit, each lone system one.</summary>
        public static List<List<SysDef>> Units(List<SysDef> systems, Dictionary<string, string> groups)
        {
            var o = new List<List<SysDef>>();
            foreach (SysDef sd in GatherGroups(systems, groups))
            {
                string gid = GidOf(groups, sd.Key);
                if (o.Count > 0 && gid != null && GidOf(groups, o[o.Count - 1][0].Key) == gid) o[o.Count - 1].Add(sd);
                else o.Add(new List<SysDef> { sd });
            }
            return o;
        }

        /// <summary>Group these systems (two or more) as gid; they sit together where the first of them is.</summary>
        public static List<SysDef> MakeGroup(List<SysDef> systems, Dictionary<string, string> groups, IEnumerable<string> keys, string gid,
                                             out Dictionary<string, string> newGroups, IEnumerable<string> keep = null)
        {
            var ks = new HashSet<string>(keys);
            var g = (groups ?? new Dictionary<string, string>()).Where(kv => !ks.Contains(kv.Key)).ToDictionary(kv => kv.Key, kv => kv.Value);
            foreach (string k in ks) g[k] = gid;
            g = CleanGroups(g, systems.Select(sd => sd.Key).Concat(keep ?? new string[0]));
            newGroups = g;
            return GatherGroups(systems, g);
        }

        /// <summary>Break up every group any of these systems is in.</summary>
        public static Dictionary<string, string> Ungroup(Dictionary<string, string> groups, IEnumerable<string> keys, IEnumerable<string> listed)
        {
            var gone = new HashSet<string>();
            foreach (string k in keys) { string v = GidOf(groups, k); if (v != null) gone.Add(v); }
            var g = groups.Where(kv => !gone.Contains(kv.Value)).ToDictionary(kv => kv.Key, kv => kv.Value);
            return CleanGroups(g, listed);
        }

        /// <summary>After a drag or a move to a place (systems already in the new order): tidy the groups.</summary>
        public static List<SysDef> TidyGroups(List<SysDef> systemsIn, Dictionary<string, string> groups, IEnumerable<string> movedIn,
                                              out Dictionary<string, string> newGroups, IEnumerable<string> keep = null)
        {
            var moved = new HashSet<string>(movedIn);
            var g = new Dictionary<string, string>(groups ?? new Dictionary<string, string>());
            var systems = new List<SysDef>(systemsIn);
            var keys = systems.Select(sd => sd.Key).ToList();
            int n = keys.Count;
            var whole = new HashSet<string>();
            foreach (string gid in g.Values.Distinct())
            {
                var members = keys.Where(k => GidOf(g, k) == gid).ToList();
                if (members.Count > 0 && members.All(moved.Contains)) whole.Add(gid);
            }
            int i = 0;
            while (i < n)
            {
                if (!moved.Contains(keys[i])) { i++; continue; }
                int j = i;
                while (j < n && moved.Contains(keys[j])) j++;
                string before = i > 0 ? GidOf(g, keys[i - 1]) : null;
                string after = j < n ? GidOf(g, keys[j]) : null;
                if (before != null && before == after)
                {
                    bool anyWhole = false;
                    for (int x = i; x < j; x++) { string gg = GidOf(g, keys[x]); if (gg != null && whole.Contains(gg)) anyWhole = true; }
                    if (anyWhole)
                    {
                        var block = systems.Skip(i).Take(j - i).ToList();
                        var rest = systems.Take(i).Concat(systems.Skip(j)).ToList();
                        int end = 0;
                        for (int x = 0; x < rest.Count; x++) if (GidOf(g, rest[x].Key) == before) end = x + 1;
                        systems = rest.Take(end).Concat(block).Concat(rest.Skip(end)).ToList();
                        keys = systems.Select(sd => sd.Key).ToList();
                        i = 0;
                        continue;
                    }
                    for (int x = i; x < j; x++) g[keys[x]] = before;
                }
                i = j;
            }
            foreach (string gid in g.Values.Distinct().OrderBy(x => x, StringComparer.Ordinal).ToList())
            {
                var runs = new List<List<string>>();
                bool prev = false;
                foreach (string k in keys)
                {
                    bool inside = GidOf(g, k) == gid;
                    if (inside && prev) runs[runs.Count - 1].Add(k);
                    else if (inside) runs.Add(new List<string> { k });
                    prev = inside;
                }
                if (runs.Count > 1)
                {
                    int best = 0; int bestScore = int.MinValue; int bestTie = int.MinValue;
                    for (int ri = 0; ri < runs.Count; ri++)
                    {
                        int score = runs[ri].Count(k => !moved.Contains(k));
                        int tie = -ri;
                        if (score > bestScore || (score == bestScore && tie > bestTie)) { best = ri; bestScore = score; bestTie = tie; }
                    }
                    for (int ri = 0; ri < runs.Count; ri++)
                        if (ri != best) foreach (string k in runs[ri]) g.Remove(k);
                }
            }
            newGroups = CleanGroups(g, keys.Concat(keep ?? new string[0]));
            return systems;
        }

        /// <summary>Shift+Up / Shift+Down with groups.</summary>
        public static List<SysDef> StepUnits(List<SysDef> systemsIn, Dictionary<string, string> groups, IEnumerable<int> selected, int delta,
                                             out Dictionary<string, string> newGroups, out HashSet<int> newSelected, IEnumerable<string> keep = null)
        {
            var systems = GatherGroups(systemsIn, groups);
            var selKeys = new HashSet<string>(selected.Where(i => i >= 0 && i < systems.Count).Select(i => systems[i].Key));
            newGroups = new Dictionary<string, string>(groups);
            newSelected = new HashSet<int>();
            if (selKeys.Count == 0) return systems;
            var gids = new HashSet<string>(selKeys.Select(k => GidOf(groups, k) ?? "\u0000none"));
            if (gids.Count == 1 && !gids.Contains("\u0000none"))
            {
                string gid = gids.First();
                var members = systems.Where(sd => GidOf(groups, sd.Key) == gid).Select(sd => sd.Key).ToList();
                if (selKeys.Count < members.Count)
                {
                    var idx = new List<int>();
                    for (int i = 0; i < systems.Count; i++) if (GidOf(groups, systems[i].Key) == gid) idx.Add(i);
                    int lo = idx[0], hi = idx[idx.Count - 1];
                    var selIdx = new HashSet<int>(idx.Where(i => selKeys.Contains(systems[i].Key)));
                    bool edge = delta < 0 ? selIdx.Min() == lo : selIdx.Max() == hi;
                    if (!edge)
                    {
                        HashSet<int> ns;
                        var res = MoveBlock(systems, selIdx, delta, out ns);
                        newSelected = ns;
                        return res;
                    }
                    var g = groups.Where(kv => !selKeys.Contains(kv.Key)).ToDictionary(kv => kv.Key, kv => kv.Value);
                    var moving = systems.Where(sd => selKeys.Contains(sd.Key)).ToList();
                    var rest = systems.Where(sd => !selKeys.Contains(sd.Key)).ToList();
                    var restIdx = new List<int>();
                    for (int i = 0; i < rest.Count; i++) if (GidOf(g, rest[i].Key) == gid) restIdx.Add(i);
                    int at;
                    if (restIdx.Count > 0) at = delta < 0 ? restIdx[0] : restIdx[restIdx.Count - 1] + 1;
                    else at = delta < 0 ? lo : lo + 1;
                    var o = rest.Take(at).Concat(moving).Concat(rest.Skip(at)).ToList();
                    newGroups = CleanGroups(g, o.Select(sd => sd.Key).Concat(keep ?? new string[0]));
                    newSelected = new HashSet<int>(Enumerable.Range(at, moving.Count));
                    return o;
                }
            }
            var us = Units(systems, groups);
            var picked = new HashSet<int>();
            for (int ui = 0; ui < us.Count; ui++) if (us[ui].Any(sd => selKeys.Contains(sd.Key))) picked.Add(ui);
            HashSet<int> newUnits;
            var movedUnits = MoveBlock(us, picked, delta, out newUnits);
            var res2 = movedUnits.SelectMany(u => u).ToList();
            int pos = 0;
            for (int ui = 0; ui < movedUnits.Count; ui++)
            {
                if (newUnits.Contains(ui)) for (int x = 0; x < movedUnits[ui].Count; x++) newSelected.Add(pos + x);
                pos += movedUnits[ui].Count;
            }
            return res2;
        }

        /// <summary>The colour's hue from darkest (t=0) to lightest (t=1): deep, then full brightness, then pale.</summary>
        public static string Shade(string hex, double t)
        {
            double h = HexHue(hex) ?? 0.0;
            t = Math.Max(0.0, Math.Min(1.0, t));
            double s, v;
            if (t <= 0.6) { s = 0.95; v = 0.38 + 0.62 * (t / 0.6); }
            else { s = 0.95 - 0.65 * ((t - 0.6) / 0.4); v = 1.0; }
            return HsvHex(h, s, v);
        }

        public static List<string> GroupShades(string baseColour, int n)
        {
            var o = new List<string>();
            if (n <= 0) return o;
            if (n == 1) { o.Add(Shade(baseColour, 0.5)); return o; }
            for (int i = 0; i < n; i++) o.Add(Shade(baseColour, i / (double)(n - 1)));
            return o;
        }

        /// <summary>A lone system its own colour; a grouped one its group's hue, darkest first to lightest last.</summary>
        public static Dictionary<string, string> SystemColours(List<SysDef> systems, Dictionary<string, string> groups, Dictionary<string, string> hues)
        {
            var o = new Dictionary<string, string>();
            var members = new Dictionary<string, List<string>>();
            var order = new List<string>();
            foreach (SysDef sd in systems)
            {
                string gid = GidOf(groups, sd.Key);
                if (gid == null || !hues.ContainsKey(gid)) o[sd.Key] = sd.Colour;
                else
                {
                    if (!members.ContainsKey(gid)) { members[gid] = new List<string>(); order.Add(gid); }
                    members[gid].Add(sd.Key);
                }
            }
            foreach (string gid in order)
            {
                var shades = GroupShades(hues[gid], members[gid].Count);
                for (int i = 0; i < members[gid].Count; i++) o[members[gid][i]] = shades[i];
            }
            return o;
        }

        /// <summary>The hue (0..1) furthest round the wheel from every hue taken, never near the start's magenta.</summary>
        public static double FarHue(List<double> taken)
        {
            double? bestGap = null; double bestH = 0;
            for (int i = 0; i < 72; i++)
            {
                double h = i / 72.0;
                if (HueGap(h, MagentaHue) < MagentaGap) continue;
                double gap = taken.Count > 0 ? taken.Min(t => HueGap(h, t)) : 1.0;
                if (bestGap == null || gap > bestGap.Value + 1e-9) { bestGap = gap; bestH = h; }
            }
            return bestH;
        }

        /// <summary>Each group without a colour gets one; lone systems close to a group's hue take a fresh clear colour. Returns the hues and the changed system colours.</summary>
        public static Dictionary<string, string> ColourGroups(List<SysDef> systems, Dictionary<string, string> groups, Dictionary<string, string> huesIn,
                                                              out Dictionary<string, string> changed)
        {
            var live = new HashSet<string>(groups.Values);
            var hues = (huesIn ?? new Dictionary<string, string>()).Where(kv => live.Contains(kv.Key)).ToDictionary(kv => kv.Key, kv => kv.Value);
            foreach (string gid in live.OrderBy(x => x, Comparer<string>.Create(NaturalCompare)))
            {
                if (hues.ContainsKey(gid)) continue;
                var taken = hues.Values.Select(c => HexHue(c)).Where(t => t != null).Select(t => t.Value).ToList();
                double? own = null;
                foreach (SysDef sd in systems)
                    if (GidOf(groups, sd.Key) == gid)
                    {
                        own = !string.IsNullOrEmpty(sd.Colour) ? HexHue(sd.Colour) : null;
                        break;
                    }
                double h;
                if (own != null && HueGap(own.Value, MagentaHue) >= MagentaGap && taken.All(t => HueGap(own.Value, t) >= 2 * GroupBand)) h = own.Value;
                else h = FarHue(taken);
                hues[gid] = HsvHex(h, 0.95, 0.80);
            }
            var groupH = hues.Values.Select(c => HexHue(c)).ToList();
            Func<string, bool> clash = c =>
            {
                double? h = !string.IsNullOrEmpty(c) ? HexHue(c) : null;
                return h == null || groupH.Any(gh => gh != null && HueGap(h.Value, gh.Value) < GroupBand);
            };
            changed = new Dictionary<string, string>();
            var need = systems.Where(sd => groupH.Count > 0 && GidOf(groups, sd.Key) == null && clash(sd.Colour)).ToList();
            if (need.Count > 0)
            {
                var used = new HashSet<string>(systems.Select(sd => sd.Colour));
                var pool = DistinctColours(systems.Count * 4 + 50).Where(c => !used.Contains(c) && !clash(c)).ToList();
                foreach (SysDef sd in need)
                    if (pool.Count > 0) { changed[sd.Key] = pool[0]; pool.RemoveAt(0); }
            }
            return hues;
        }

        private static List<SysDef> Ticked(List<SysDef> unit) { return unit.Where(sd => sd.On).ToList(); }

        private static double Near(Dictionary<long, Node> nodes, SysDef sd, double[] point)
        {
            return CompDistance(nodes, sd.Keys.Where(nodes.ContainsKey), point);
        }

        /// <summary>Auto order with groups: a group moves as one, in its own order.</summary>
        public static List<SysDef> AutoOrderUnits(Dictionary<long, Node> nodes, List<SysDef> systems, Dictionary<string, string> groups, Func<long, bool> include = null)
        {
            var us = Units(systems, groups);
            var live = us.Where(u => Ticked(u).Count > 0).ToList();
            var dead = us.Where(u => Ticked(u).Count == 0).ToList();
            if (live.Count < 2) return live.Concat(dead).SelectMany(u => u).ToList();
            List<SysDef> first = live.FirstOrDefault(u => Ticked(u).Any(sd => sd.Start != null)) ?? live[0];
            var left = live.Where(u => !ReferenceEquals(u, first)).ToList();
            var o = new List<List<SysDef>> { first };
            double[] exit = null;
            foreach (SysDef sd in Ticked(first)) exit = WalkSystem(nodes, sd, exit, include).ExitPoint;
            while (left.Count > 0)
            {
                List<SysDef> nxt;
                if (exit == null) nxt = left[0];
                else { double[] ex = exit; nxt = left.OrderBy(u => Near(nodes, Ticked(u)[0], ex)).ThenBy(u => left.IndexOf(u)).First(); }
                left.Remove(nxt);
                o.Add(nxt);
                foreach (SysDef sd in Ticked(nxt)) exit = WalkSystem(nodes, sd, exit, include).ExitPoint;
            }
            return o.Concat(dead).SelectMany(u => u).ToList();
        }

        /// <summary>Re-order one group nearest-next. Unticked members go to the end of the group.</summary>
        public static List<SysDef> ReorderGroup(Dictionary<long, Node> nodes, List<SysDef> systemsIn, Dictionary<string, string> groups, string gid, Func<long, bool> include = null)
        {
            var systems = GatherGroups(systemsIn, groups);
            var idx = new List<int>();
            for (int i = 0; i < systems.Count; i++) if (GidOf(groups, systems[i].Key) == gid) idx.Add(i);
            if (idx.Count < 2) return systems;
            var members = idx.Select(i => systems[i]).ToList();
            var on = Ticked(members);
            var off = members.Where(sd => !on.Contains(sd)).ToList();
            var beforeList = Ticked(systems.Take(idx[0]).ToList());
            double[] entry = beforeList.Count > 0 ? ExitAfter(nodes, beforeList, beforeList.Count - 1, include) : null;
            var nw = new List<SysDef>();
            if (on.Count > 0)
            {
                SysDef first = on.FirstOrDefault(sd => sd.Start != null);
                if (first == null && entry != null) { double[] en = entry; first = on.OrderBy(sd => Near(nodes, sd, en)).ThenBy(sd => on.IndexOf(sd)).First(); }
                if (first == null) first = on[0];
                var rest = on.Where(sd => !ReferenceEquals(sd, first)).ToList();
                nw.Add(first);
                double[] exit = WalkSystem(nodes, first, entry, include).ExitPoint;
                while (rest.Count > 0)
                {
                    SysDef nxt;
                    if (exit == null) nxt = rest[0];
                    else { double[] ex = exit; nxt = rest.OrderBy(sd => Near(nodes, sd, ex)).ThenBy(sd => rest.IndexOf(sd)).First(); }
                    rest.Remove(nxt);
                    nw.Add(nxt);
                    exit = WalkSystem(nodes, nxt, exit, include).ExitPoint;
                }
            }
            return systems.Take(idx[0]).Concat(nw).Concat(off).Concat(systems.Skip(idx[idx.Count - 1] + 1)).ToList();
        }

        /// <summary>The Group cell: 'G2  1/3' - the group and the place in it.</summary>
        public static string GroupLabel(Dictionary<string, string> groups, string key, List<SysDef> systems)
        {
            string gid = GidOf(groups, key);
            if (gid == null) return "";
            var keys = systems.Where(sd => GidOf(groups, sd.Key) == gid).Select(sd => sd.Key).ToList();
            return gid + "  " + (keys.IndexOf(key) + 1) + "/" + keys.Count;
        }

        /// <summary>A group id not in use: G1, G2 ... counting on from n.</summary>
        public static string NextGroupId(Dictionary<string, string> groups, ref int n)
        {
            var used = new HashSet<string>(groups.Values);
            while (true)
            {
                n++;
                string gid = "G" + n;
                if (!used.Contains(gid)) return gid;
            }
        }

        // ============================================================ Tag in views: sheets

        public static List<SheetData> SheetRows(List<SheetData> sheets, string text)
        {
            var o = sheets.Where(sh => Matches(sh.Number + " " + sh.Name, text)).ToList();
            var cmp = new NaturalKeyComparer();
            return o.OrderBy(sh => NaturalKey(sh.Number), cmp).ThenBy(sh => NaturalKey(sh.Name), cmp).ToList();
        }

        public static HashSet<long> SheetViews(List<SheetData> sheets, HashSet<string> uids)
        {
            var o = new HashSet<long>();
            foreach (SheetData sh in sheets) if (uids.Contains(sh.Uid)) o.UnionWith(sh.Views);
            return o;
        }

        /// <summary>The sheet's tick box: true every listed view ticked, false none (or it holds none), null some.</summary>
        public static bool? SheetState(SheetData sheet, HashSet<long> tickedIds)
        {
            int n = sheet.Views.Count(v => tickedIds.Contains(v));
            if (sheet.Views.Count == 0 || n == 0) return false;
            return n == sheet.Views.Count ? (bool?)true : null;
        }

        /// <summary>After a run that tagged in ticked views: sheets whose every view is ticked open as the sheet; other ticked views open alone.</summary>
        public static List<SheetData> OpenList(List<SheetData> sheets, HashSet<long> tickedIds, out List<long> views)
        {
            var full = sheets.Where(sh => SheetState(sh, tickedIds) == true).ToList();
            var onSheets = new HashSet<long>(full.SelectMany(sh => sh.Views));
            var cmp = new NaturalKeyComparer();
            full = full.OrderBy(sh => NaturalKey(sh.Number), cmp).ThenBy(sh => NaturalKey(sh.Name), cmp).ToList();
            views = tickedIds.Where(v => !onSheets.Contains(v)).OrderBy(v => v).ToList();
            return full;
        }

        // ============================================================ Order by position

        public const int SnakeVariants = 4;

        /// <summary>
        /// Elements in a snake across the view. uv: u right, v up. leftRight: rows across, each back the other way;
        /// otherwise columns down, each back up. variant (0-3) picks the start corner and first direction. Within a row
        /// each next element is the nearest one ahead in the direction of travel.
        /// </summary>
        public static List<long> SnakeOrder(Dictionary<long, double[]> uv, bool leftRight, int variant, long? first = null)
        {
            var keys = uv.Keys.OrderBy(k => k).ToList();
            if (keys.Count <= 1) return keys;
            double tSign = (variant & 1) != 0 ? -1.0 : 1.0;
            double sSign = (variant & 2) != 0 ? -1.0 : 1.0;
            // t runs along the travel, s across the rows; the default is left-to-right / top-to-bottom
            Func<long, double> t = k => tSign * (leftRight ? uv[k][0] : -uv[k][1]);
            Func<long, double> s = k => sSign * (leftRight ? -uv[k][1] : uv[k][0]);
            // how far apart neighbours sit: the typical nearest-neighbour distance
            var nn = new List<double>();
            foreach (long a in keys)
            {
                double best = double.MaxValue;
                foreach (long b in keys)
                {
                    if (a == b) continue;
                    double dx = uv[a][0] - uv[b][0], dy = uv[a][1] - uv[b][1];
                    double d = Math.Sqrt(dx * dx + dy * dy);
                    if (d < best) best = d;
                }
                if (best < double.MaxValue) nn.Add(best);
            }
            nn.Sort();
            double spacing = nn.Count > 0 ? nn[nn.Count / 2] : 1.0;
            double tol = Math.Max(spacing * 0.6, 1e-6);
            var bySide = keys.OrderBy(s).ThenBy(t).ThenBy(k => k).ToList();
            var rows = new List<List<long>>();
            double prev = 0;
            foreach (long k in bySide)
            {
                double sv = s(k);
                if (rows.Count == 0 || sv - prev > tol) rows.Add(new List<long>());
                rows[rows.Count - 1].Add(k);
                prev = sv;
            }
            var sorted = rows.Select(r => r.OrderBy(t).ThenBy(k => k).ToList()).ToList();
            var o = new List<long>();
            int r0 = 0;
            var behind = new List<long>();
            if (first != null)
            {
                int hit = sorted.FindIndex(r => r.Contains(first.Value));
                if (hit >= 0)
                {
                    r0 = hit;
                    double tf = t(first.Value);
                    behind = sorted[hit].Where(k => t(k) < tf).ToList();
                    sorted[hit] = sorted[hit].Where(k => t(k) >= tf).ToList();
                }
            }
            // the rows from the picked one onward, then the rows before it, each row back the other way
            var seq = new List<List<long>>();
            for (int i = r0; i < sorted.Count; i++) seq.Add(sorted[i]);
            for (int i = r0 - 1; i >= 0; i--) seq.Add(sorted[i]);
            for (int i = 0; i < seq.Count; i++)
            {
                var row = new List<long>(seq[i]);
                if (i % 2 == 1) row.Reverse();
                o.AddRange(row);
            }
            o.AddRange(behind);
            return o;
        }

        /// <summary>"Left to right snake from the top left (1 of 4)".</summary>
        public static string SnakeText(bool leftRight, int variant)
        {
            bool rev = (variant & 1) != 0, other = (variant & 2) != 0;
            string start = leftRight
                ? (other ? "bottom" : "top") + " " + (rev ? "right" : "left")
                : (other ? "right" : "left") + " " + (rev ? "bottom" : "top");
            return (leftRight ? "Left to right" : "Top to bottom") + " snake from the " + start + " (" + (variant + 1) + " of " + SnakeVariants + ")";
        }
    }
}






