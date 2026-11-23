using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.FindInView
{
    /// <summary>
    /// Find in View: version, settings and the pure helpers (tiling arithmetic, zoom arithmetic, theme
    /// choice, drawer arithmetic, id parsing, text helpers). Port of fiv_core.py. Nothing here touches
    /// Revit, so it can be read and reasoned about on its own.
    /// </summary>
    public static class FivCore
    {
        public const string Version = "1.17.0";
        public const string ToolName = "Find in View";

        /// <summary>The add-in build: version, build date and the DLL's path, for the debug header.</summary>
        public static string BuildInfo()
        {
            try
            {
                Assembly assembly = typeof(FivCore).Assembly;
                string path = assembly.Location;
                string written = "";
                try
                {
                    written = File.GetLastWriteTime(path).ToString("yyyy-MM-dd HH:mm:ss");
                }
                catch (Exception)
                {
                }
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

        // ---------------------------------------------------------------- settings --

        public const string SettingsVersion = "1";

        public static string SettingsDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string SettingsPath() { return Path.Combine(SettingsDir(), "find_in_view.txt"); }
        public static string ErrorPath() { return Path.Combine(SettingsDir(), "find_in_view_last_error.txt"); }
        public static string DebugPath() { return Path.Combine(SettingsDir(), "find_in_view_debug.txt"); }

        public static readonly Dictionary<string, string> Defaults = new Dictionary<string, string>
        {
            { "settings_version", SettingsVersion },
            { "theme_mode", "follow" },          // follow Revit's canvas, or dark / light
            { "view_types", "" },                // blank = all view types ticked
            { "remember_search", "0" },
            { "search", "" },
            { "last_view", "" },
            { "last_view_id", "" },
            { "window_width", "1040" },
            { "window_height", "860" },
            { "panel_width", "300" },
            { "where_open", "0" },
            { "zoom_padding_pct", "15" },
            { "zoom_min_padding_mm", "300" },
            { "reselect_after_zoom", "1" },
            { "zoom_here", "1" },
            { "zoom_here_needs_all", "1" },
            { "unhide_categories", "1" },
            { "unhide_mode", "auto" },           // auto | temporary | permanent
            { "open_tiled", "0" },
            { "reuse_tile", "1" },
            { "tile_zoom_extra_pct", "35" },
            { "warn_tile_failure", "1" },
            { "zoom_attempts", "3" },
        };

        /// <summary>Reads the settings, falling back to the defaults key by key. A missing or damaged file is not an error.</summary>
        public static Dictionary<string, string> LoadSettings()
        {
            var data = new Dictionary<string, string>(Defaults);
            try
            {
                string path = SettingsPath();
                if (File.Exists(path))
                {
                    foreach (string raw in File.ReadAllText(path).Split('\n'))
                    {
                        string line = raw.Trim();
                        if (line.Length == 0 || line.StartsWith("#") || line.IndexOf('=') < 0) continue;
                        int cut = line.IndexOf('=');   // the FIRST '=' only: values may contain '='
                        string key = line.Substring(0, cut).Trim();
                        if (Defaults.ContainsKey(key)) data[key] = line.Substring(cut + 1).Trim();
                    }
                }
            }
            catch (Exception)
            {
            }
            data["settings_version"] = SettingsVersion;
            return data;
        }

        /// <summary>Writes the settings as plain key=value text. Failure is never fatal.</summary>
        public static bool SaveSettings(Dictionary<string, string> data)
        {
            try
            {
                Directory.CreateDirectory(SettingsDir());
                var lines = new List<string>();
                foreach (string key in Defaults.Keys.OrderBy(k => k, StringComparer.Ordinal))
                {
                    string value;
                    lines.Add(key + "=" + (data.TryGetValue(key, out value) ? value : Defaults[key]));
                }
                File.WriteAllText(SettingsPath(), string.Join("\n", lines), new UTF8Encoding(false));
                return true;
            }
            catch (Exception)
            {
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

        public static int AsInt(string value, int fallback = 0)
        {
            double number;
            if (double.TryParse((value ?? "").Trim(), System.Globalization.NumberStyles.Float,
                                System.Globalization.CultureInfo.InvariantCulture, out number))
                return (int)number;
            return fallback;
        }

        public static string Get(Dictionary<string, string> settings, string key)
        {
            string value;
            if (settings.TryGetValue(key, out value)) return value ?? "";
            return Defaults.TryGetValue(key, out value) ? value : "";
        }

        /// <summary>A list of strings in one key=value line.</summary>
        public static string PackList(IEnumerable<string> values)
        {
            var cleaned = new List<string>();
            foreach (string value in values ?? new string[0])
            {
                string text = (value ?? "").Replace('|', ' ').Trim();
                if (text.Length > 0) cleaned.Add(text);
            }
            return string.Join("|", cleaned);
        }

        public static List<string> UnpackList(string text)
        {
            var output = new List<string>();
            foreach (string part in (text ?? "").Split('|'))
            {
                string trimmed = part.Trim();
                if (trimmed.Length > 0) output.Add(trimmed);
            }
            return output;
        }

        // ------------------------------------------------------- window tiling arithmetic --

        public const double OverlapTolerance = 0.20;

        public const string TileNever = "never";     // leave the windows exactly as they are
        public const string TileAlways = "always";   // the view you came from is the only one open: tile them

        /// <summary>One open view window: (view id, left, top, right, bottom).</summary>
        public struct WinRect
        {
            public long ViewId;
            public double Left, Top, Right, Bottom;

            public WinRect(long viewId, double left, double top, double right, double bottom)
            {
                ViewId = viewId; Left = left; Top = top; Right = right; Bottom = bottom;
            }
        }

        public static double RectArea(WinRect rect)
        {
            return Math.Max(0, rect.Right - rect.Left) * Math.Max(0, rect.Bottom - rect.Top);
        }

        /// <summary>Shared area as a share of the smaller of the two rectangles.</summary>
        public static double OverlapRatio(WinRect first, WinRect second)
        {
            double left = Math.Max(first.Left, second.Left);
            double top = Math.Max(first.Top, second.Top);
            double right = Math.Min(first.Right, second.Right);
            double bottom = Math.Min(first.Bottom, second.Bottom);
            if (right <= left || bottom <= top) return 0.0;
            double shared = (right - left) * (bottom - top);
            double smallest = Math.Min(RectArea(first), RectArea(second));
            return smallest <= 0 ? 0.0 : shared / smallest;
        }

        /// <summary>Is Revit already showing these windows side by side? Tiled windows do not overlap.</summary>
        public static bool LooksTiled(IList<WinRect> rects)
        {
            if (rects == null || rects.Count < 2) return false;
            for (int i = 0; i < rects.Count; i++)
                for (int j = i + 1; j < rects.Count; j++)
                    if (OverlapRatio(rects[i], rects[j]) > OverlapTolerance) return false;
            return true;
        }

        /// <summary>The first tile (top left on screen) that is neither the one started in nor the one wanted. Null if none.</summary>
        public static long? PickTileToReuse(IList<WinRect> rects, long? hostId, long targetId)
        {
            var candidates = new List<WinRect>();
            foreach (WinRect rect in rects ?? new WinRect[0])
            {
                if ((hostId.HasValue && rect.ViewId == hostId.Value) || rect.ViewId == targetId) continue;
                candidates.Add(rect);
            }
            if (candidates.Count == 0) return null;
            candidates.Sort((a, b) => a.Top != b.Top ? a.Top.CompareTo(b.Top) : a.Left.CompareTo(b.Left));
            return candidates[0].ViewId;
        }

        // -------------------------------------------------- dark, light, or what Revit shows --

        public static readonly string[] ThemeModes = { "follow", "dark", "light" };

        public static string ThemeChip(string mode)
        {
            string clean = CleanThemeMode(mode);
            return clean == "follow" ? "Auto" : clean == "dark" ? "Dark" : "Light";
        }

        public static string CleanThemeMode(string mode)
        {
            string text = (mode ?? "").Trim().ToLowerInvariant();
            return ThemeModes.Contains(text) ? text : "follow";
        }

        /// <summary>The chip cycles Auto, Dark, Light, the same order as the other tools.</summary>
        public static string NextThemeMode(string mode)
        {
            int index = Array.IndexOf(ThemeModes, CleanThemeMode(mode));
            return ThemeModes[(index + 1) % ThemeModes.Length];
        }

        /// <summary>The palette to paint with. revitReading is "dark", "light" or null where nothing answered.</summary>
        public static string ResolvePalette(string mode, string revitReading, string fallback = "dark")
        {
            string current = CleanThemeMode(mode);
            if (current != "follow") return current;
            if (revitReading == "dark" || revitReading == "light") return revitReading;
            return fallback;
        }

        // ---------------------------------------------------------------- the shrink drawer --

        public const double DrawerMs = 280.0;
        public const double DrawerTickMs = 15.0;
        public const double CopyFlashMs = 1500.0;
        public const int OldWindowHeight = 700;   // the default before 1.17.0: a saved 700 was never a choice
        public const string CopyIcon = "M 4.5,4.5 L 4.5,1.5 L 12.5,1.5 L 12.5,9.5 L 9.5,9.5 M 1.5,4.5 L 9.5,4.5 L 9.5,12.5 L 1.5,12.5 Z";
        public const string CopiedIcon = "M 2,7.5 L 5.5,11 L 12,3.5";
        public const string NotCopiedIcon = "M 3,3 L 11,11 M 11,3 L 3,11";
        public const double DrawerGap = 8.0;
        public const double DrawerStack = 4.0;

        /// <summary>1-(1-p)^3: quick away, gentle in.</summary>
        public static double EaseOut(double progress)
        {
            double step = Math.Min(1.0, Math.Max(0.0, progress));
            return 1.0 - Math.Pow(1.0 - step, 3);
        }

        public static double DrawerFrame(double start, double end, double progress)
        {
            return start + (end - start) * EaseOut(progress);
        }

        /// <summary>The parked bar: the header, plus the window border above AND below it.</summary>
        public static double BarHeight(double headerHeight, double headerOffset)
        {
            return Math.Max(1.0, headerHeight + 2.0 * headerOffset);
        }

        /// <summary>Where a parked bar lands. areaTop is signed: a monitor above the primary one has a negative top.</summary>
        public static double ShrunkTop(double areaTop, double areaHeight, double bar, int slot = 0)
        {
            double bottom = areaTop + areaHeight;
            double step = bar + DrawerStack;
            return bottom - bar - DrawerGap - (Math.Max(0, slot) * step);
        }

        /// <summary>Where the window goes when it opens from a bar that has been dragged: it grows UPWARD out of the bar.</summary>
        public static double ExpandTop(double parkedTop, double height, double bar, double areaTop, double areaHeight)
        {
            double top = parkedTop + bar - height;
            double bottom = areaTop + areaHeight;
            if (top + height > bottom) top = bottom - height;
            if (top < areaTop) top = areaTop;
            return top;
        }

        /// <summary>The lowest parking slot nobody is in, so a freed one is reused.</summary>
        public static int FreeSlot(IEnumerable<int> taken)
        {
            var used = new HashSet<int>(taken ?? new int[0]);
            int slot = 0;
            while (used.Contains(slot)) slot++;
            return slot;
        }

        // ------------------------------------------------ is it already in the view you are in? --

        public const string HereZoom = "zoom";
        public const string HereWindow = "window";

        /// <summary>
        /// Zoom where you are, or open the window and pick a view. Only a plan takes the shortcut; and by
        /// default every selected element has to be drawn there before the window is skipped.
        /// </summary>
        public static string ZoomHereDecision(bool enabled, bool viewCanZoom, int selected, int drawn, bool needsAll, bool inPlan = true)
        {
            if (!enabled || !viewCanZoom || !inPlan) return HereWindow;
            if (selected <= 0 || drawn <= 0) return HereWindow;
            if (needsAll && drawn < selected) return HereWindow;
            return HereZoom;
        }

        // ---------------------------------------------------------------- which box takes the caret --

        public const string FieldId = "id";
        public const string FieldSearch = "search";

        public static string FirstField(bool hasSelection)
        {
            return hasSelection ? FieldSearch : FieldId;
        }

        // ------------------------------------------------------------------------------ levels --

        public const double LevelToleranceFt = 0.01;

        /// <summary>The level a point belongs to: the level BELOW wins; only with nothing below does the lowest above stand in.</summary>
        public static string NearestLevel(IList<KeyValuePair<string, double>> levels, double elevation)
        {
            if (levels == null || levels.Count == 0) return null;
            var below = levels.Where(l => l.Value <= elevation + LevelToleranceFt).OrderBy(l => l.Value).ToList();
            if (below.Count > 0) return below[below.Count - 1].Key;
            return levels.OrderBy(l => l.Value).First().Key;
        }

        /// <summary>"L01 (3), L02" - the most used first, then alphabetically.</summary>
        public static string SummariseLevels(IEnumerable<string> names)
        {
            var counts = new Dictionary<string, int>();
            foreach (string name in names ?? new string[0])
            {
                string key = string.IsNullOrEmpty(name) ? "no level" : name;
                int count;
                counts.TryGetValue(key, out count);
                counts[key] = count + 1;
            }
            var entries = counts.ToList();
            entries.Sort((a, b) => a.Value != b.Value ? b.Value.CompareTo(a.Value) : NaturalCompare(a.Key, b.Key));
            return string.Join(", ", entries.Select(e => e.Value == 1 ? e.Key : e.Key + " (" + e.Value + ")"));
        }

        /// <summary>"101;102;103": the form Revit's own Select Elements by ID takes.</summary>
        public static string JoinIds(IEnumerable<long> values)
        {
            return string.Join(";", (values ?? new long[0]).Select(v => v.ToString()));
        }

        /// <summary>"101, 102 + 5 more": a few ids and a count, for a narrow panel.</summary>
        public static string IdPreview(IList<long> values, int limit = 2)
        {
            var shown = (values ?? new long[0]).Select(v => v.ToString()).ToList();
            if (shown.Count <= limit) return string.Join(", ", shown);
            return string.Join(", ", shown.Take(limit)) + " + " + (shown.Count - limit) + " more";
        }

        /// <summary>"2 of 3 on": what is inside the shut Where it opens drop down.</summary>
        public static string WhereSummary(IList<bool> switches)
        {
            return switches.Count(s => s) + " of " + switches.Count + " on";
        }

        // --------------------------------------------------------------- turning a category back on --

        public const string UnhideNone = "none";
        public const string UnhideTemporary = "temporary";
        public const string UnhidePermanent = "permanent";

        /// <summary>
        /// How to make the selection visible in the view it is about to open in. Temporary view properties
        /// need a view template, so temporary on a view with none lands on permanent.
        /// </summary>
        public static string PlanUnhide(bool enabled, string mode, int hiddenCategories, int hiddenElements, bool hasTemplate)
        {
            if (!enabled) return UnhideNone;
            if (hiddenCategories == 0 && hiddenElements == 0) return UnhideNone;
            if (mode == UnhidePermanent) return UnhidePermanent;
            return hasTemplate ? UnhideTemporary : UnhidePermanent;
        }

        // ------------------------------------------------------------------------ did the zoom land? --

        public const double ZoomSpanLimit = 4.0;    // showing more than this much of what was asked for is a zoom to fit
        public const double ZoomSpanFloor = 0.80;   // showing less than this cuts the selection off

        public struct Pt3
        {
            public double X, Y, Z;
            public Pt3(double x, double y, double z) { X = x; Y = y; Z = z; }
            public double this[int axis] { get { return axis == 0 ? X : axis == 1 ? Y : Z; } }
        }

        /// <summary>Is the view actually framed on what was asked for? Everything is in the view's own (u, v) frame.</summary>
        public static bool ZoomLanded(Pt3 wantedLow, Pt3 wantedHigh, Pt3 visibleLow, Pt3 visibleHigh, out string reason)
        {
            reason = "";
            for (int axis = 0; axis < 2; axis++)
            {
                double centre = (wantedLow[axis] + wantedHigh[axis]) / 2.0;
                double lo = Math.Min(visibleLow[axis], visibleHigh[axis]);
                double hi = Math.Max(visibleLow[axis], visibleHigh[axis]);
                if (!(lo <= centre && centre <= hi))
                {
                    reason = "the selection is not in the middle of the view";
                    return false;
                }
            }
            for (int axis = 0; axis < 2; axis++)
            {
                double wantedSpan = Math.Abs(wantedHigh[axis] - wantedLow[axis]);
                double visibleSpan = Math.Abs(visibleHigh[axis] - visibleLow[axis]);
                if (wantedSpan <= 0) continue;
                double ratio = visibleSpan / wantedSpan;
                if (ratio > ZoomSpanLimit)
                {
                    reason = "the view is showing about " + (int)Math.Round(ratio) + " times the selection rather than framing it";
                    return false;
                }
                if (ratio < ZoomSpanFloor)
                {
                    reason = "the view is cutting the selection off";
                    return false;
                }
            }
            return true;
        }

        // ------------------------------------------------------------- element ids typed by hand --

        /// <summary>
        /// Splits what was typed into id tokens. Semicolons, commas, spaces and new lines all separate;
        /// duplicates are dropped, keeping the order typed.
        /// </summary>
        public static List<string> ParseIds(string text)
        {
            var output = new List<string>();
            var seen = new HashSet<string>();
            var buffer = new StringBuilder();
            Action flush = () =>
            {
                string token = buffer.ToString().Trim();
                buffer.Clear();
                if (token.Length > 0 && seen.Add(token)) output.Add(token);
            };
            foreach (char c in text ?? "")
            {
                if (char.IsDigit(c) || c == '-' || char.IsLetter(c)) buffer.Append(c);
                else flush();
            }
            flush();
            return output;
        }

        // ---------------------------------------------------------------------------- text helpers --

        private static readonly Regex Num = new Regex(@"(\d+)");

        /// <summary>Compares reading numbers as numbers, so L10 follows L9.</summary>
        public static int NaturalCompare(string a, string b)
        {
            string[] pa = Num.Split(a ?? "");
            string[] pb = Num.Split(b ?? "");
            int n = Math.Min(pa.Length, pb.Length);
            for (int i = 0; i < n; i++)
            {
                if (i % 2 == 1)
                {
                    long x, y;
                    if (long.TryParse(pa[i], out x) && long.TryParse(pb[i], out y))
                    {
                        if (x != y) return x.CompareTo(y);
                        continue;
                    }
                }
                int c = string.Compare(pa[i], pb[i], StringComparison.OrdinalIgnoreCase);
                if (c != 0) return c;
            }
            return pa.Length.CompareTo(pb.Length);
        }

        /// <summary>Every whitespace separated word in query must appear in haystack. Case insensitive, any order.</summary>
        public static bool MatchesKeywords(string haystack, string query)
        {
            string text = (haystack ?? "").ToLowerInvariant();
            foreach (string word in (query ?? "").ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries))
                if (text.IndexOf(word, StringComparison.Ordinal) < 0) return false;
            return true;
        }

        public static string Plural(int count, string singular, string many = null)
        {
            return count + " " + (count == 1 ? singular : (many ?? singular + "s"));
        }

        // ------------------------------------------------------------------------- zoom arithmetic --

        public const double MmPerFoot = 304.8;

        public static double MmToFeet(double mm) { return mm / MmPerFoot; }

        /// <summary>Grows a (min, max) box by a percentage of its own extent, per axis, never less than minPaddingFt.</summary>
        public static void PaddedBox(Pt3 minimum, Pt3 maximum, double paddingPct, double minPaddingFt, out Pt3 low, out Pt3 high)
        {
            double pct = Math.Max(0.0, paddingPct) / 100.0;
            double floorPad = Math.Max(0.0, minPaddingFt);
            var lows = new double[3];
            var highs = new double[3];
            for (int axis = 0; axis < 3; axis++)
            {
                double lo = Math.Min(minimum[axis], maximum[axis]);
                double hi = Math.Max(minimum[axis], maximum[axis]);
                double pad = Math.Max((hi - lo) * pct, floorPad);
                lows[axis] = lo - pad;
                highs[axis] = hi + pad;
            }
            low = new Pt3(lows[0], lows[1], lows[2]);
            high = new Pt3(highs[0], highs[1], highs[2]);
        }

        public static List<Pt3> BoxCorners(Pt3 low, Pt3 high)
        {
            var corners = new List<Pt3>();
            foreach (double x in new[] { low.X, high.X })
                foreach (double y in new[] { low.Y, high.Y })
                    foreach (double z in new[] { low.Z, high.Z })
                        corners.Add(new Pt3(x, y, z));
            return corners;
        }

        /// <summary>A model point in the view's own right / up / depth coordinates.</summary>
        public static Pt3 ToFrame(Pt3 p, Pt3 origin, Pt3 right, Pt3 up, Pt3 normal)
        {
            double ox = p.X - origin.X, oy = p.Y - origin.Y, oz = p.Z - origin.Z;
            return new Pt3(ox * right.X + oy * right.Y + oz * right.Z,
                           ox * up.X + oy * up.Y + oz * up.Z,
                           ox * normal.X + oy * normal.Y + oz * normal.Z);
        }

        public static Pt3 FromFrame(Pt3 p, Pt3 origin, Pt3 right, Pt3 up, Pt3 normal)
        {
            return new Pt3(origin.X + right.X * p.X + up.X * p.Y + normal.X * p.Z,
                           origin.Y + right.Y * p.X + up.Y * p.Y + normal.Y * p.Z,
                           origin.Z + right.Z * p.X + up.Z * p.Y + normal.Z * p.Z);
        }

        /// <summary>
        /// The two model points to hand to ZoomAndCenterRectangle. All eight corners of the box are projected
        /// into the view's own frame and the extent taken there, because Revit fits the rectangle spanned by
        /// the two points as seen in the view; the padding is applied in the view frame too.
        /// </summary>
        public static void ZoomRectangle(Pt3 low, Pt3 high, Pt3 origin, Pt3 right, Pt3 up, Pt3 normal,
                                         double paddingPct, double minPaddingFt, out Pt3 a, out Pt3 b)
        {
            List<Pt3> frame = BoxCorners(low, high).Select(c => ToFrame(c, origin, right, up, normal)).ToList();
            var fl = new Pt3(frame.Min(p => p.X), frame.Min(p => p.Y), frame.Min(p => p.Z));
            var fh = new Pt3(frame.Max(p => p.X), frame.Max(p => p.Y), frame.Max(p => p.Z));
            Pt3 pl, ph;
            PaddedBox(fl, fh, paddingPct, minPaddingFt, out pl, out ph);
            a = FromFrame(pl, origin, right, up, normal);
            b = FromFrame(ph, origin, right, up, normal);
        }

        /// <summary>Union of boxes. Returns false when there are none.</summary>
        public static bool UnionBox(IEnumerable<KeyValuePair<Pt3, Pt3>> boxes, out Pt3 low, out Pt3 high)
        {
            double[] lo = { double.MaxValue, double.MaxValue, double.MaxValue };
            double[] hi = { double.MinValue, double.MinValue, double.MinValue };
            bool any = false;
            foreach (var box in boxes ?? new KeyValuePair<Pt3, Pt3>[0])
            {
                any = true;
                for (int axis = 0; axis < 3; axis++)
                {
                    lo[axis] = Math.Min(lo[axis], Math.Min(box.Key[axis], box.Value[axis]));
                    hi[axis] = Math.Max(hi[axis], Math.Max(box.Key[axis], box.Value[axis]));
                }
            }
            low = new Pt3(lo[0], lo[1], lo[2]);
            high = new Pt3(hi[0], hi[1], hi[2]);
            return any;
        }
    }
}
