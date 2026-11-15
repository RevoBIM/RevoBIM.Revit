// Excel for Revit: palette, theme state, brush cache and generic helpers.
// Port of efr_core.py lines 1-460 (module header, palette, helpers).
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.ExcelForRevit
{
    public static partial class Efr
    {
        /// <summary>Tool version (efr_core.__version__).</summary>
        public const string Version = "1.20.0";

        /// <summary>Why the Excel layer could not load (Python EXCEL_ERROR). Empty when it loaded.
        /// Nothing in the C# port can fail to load that layer, so this stays empty.</summary>
        public static string ExcelError = "";

        // ------------------------------------------------------------ resources ----
        //
        // The XAML, the logo and the toolbar icons are embedded resources, not files next to a script.
        //   XAML:   RevoBIM.UI.ExcelForRevit.Layouts.<file>          (e.g. ExcelForRevit.xaml)
        //   Icons:  RevoBIM.Resources.ExcelForRevit.<name>.png       (logo: icon.png; toolbar: icons.filldown.png ...)

        /// <summary>Manifest resource prefix of the XAML layouts.</summary>
        public const string LayoutResourcePrefix = "RevoBIM.UI.ExcelForRevit.Layouts.";

        /// <summary>Manifest resource prefix of the images.</summary>
        public const string ImageResourcePrefix = "RevoBIM.Resources.ExcelForRevit.";

        /// <summary>The logo shown in the window header (Python ICON_PATH).</summary>
        public const string IconResource = "RevoBIM.Resources.ExcelForRevit.icon.png";

        /// <summary>The main window layout (Python XAML_PATH).</summary>
        public const string XamlResource = "ExcelForRevit.xaml";

        // ---------------------------------------------------------------- palette ----
        //
        // Two themes with identical keys.  SetTheme() writes the chosen one into the C_* fields,
        // so every C_* reference picks the new value up on its next read - which is why nothing
        // reads a colour at startup.
        //
        // Dark follows Revit's own dark UI (2024 and later), as the shared RevoBIM "Revit dark"
        // palette: #3C4454 body, #222933 title bar, #1B1F24 toolbar, #2D3441 fields, #323C48
        // headings, #444E5E hover, #3A7392 selection, #EEF0F4 text, with muted text and blue lifted
        // for the lighter body.  Two additions of this tool's own: red is lifted to #FA8880 so
        // read-only column names stay readable on the headings, and the cell-state washes are
        // lifted so each stands clearly off the field rather than relying on hue alone.

        // ---- current palette (mutable; rewritten by SetTheme). Initial values = dark theme ----
        public static string C_WINDOW = "#3C4454";
        public static string C_CARD = "#1B1F24";
        public static string C_FIELD = "#2D3441";
        public static string C_BAR = "#222933";
        public static string C_EDGE = "#4A5364";
        public static string C_EDGE_SOFT = "#515C6B";
        public static string C_TEXT = "#EEF0F4";
        public static string C_MUTED = "#A4AAB1";
        public static string C_BLUE = "#5AAEEB";
        public static string C_ORANGE = "#E8912D";
        public static string C_GREEN = "#3FA75A";
        public static string C_GREEN_HI = "#4EC06D";
        public static string C_RED = "#FA8880";
        public static string C_SEL = "#3A7392";
        public static string C_SEL_FG = "#FFFFFF";
        public static string C_TYPE_BG = "#5E4018";
        public static string C_TYPE_FG = "#F7C384";
        public static string C_INST_BG = "#24527A";
        public static string C_INST_FG = "#B2DBF8";
        public static string C_RO_BG = "#5E3639";
        public static string C_RO_FG = "#F2B9B6";
        public static string C_EDIT_BG = "#2E6040";
        public static string C_EDIT_FG = "#93EBB0";
        public static string C_FAIL_BG = "#A3302B";
        public static string C_FAIL_FG = "#FFECEA";
        public static string C_TEST_BG = "#493C68";
        public static string C_TEST_FG = "#D3C6F7";
        public static string C_IMP_BG = "#165A62";
        public static string C_IMP_FG = "#93E7EF";
        public static string C_CLEAR = "#00000000";
        public static string C_COPY_BG = "#585020";
        public static string C_COPY_FG = "#F0E5A2";
        public static string C_INDEX_BG = "#283039";
        public static string C_HEADER_BG = "#323C48";
        public static string C_BTN_BG = "#2D3441";
        public static string C_BTN_EDGE = "#4A5364";
        public static string C_SCROLL_BG = "#2D3441";
        public static string C_SCROLL_THUMB = "#56606F";
        public static string C_EDITOR_BG = "#1B1F24";
        public static string C_EDITOR_FG = "#FFFFFF";
        public static string C_BTN_HOVER = "#444E5E";
        public static string C_BTN_OFF = "#262D37";
        public static string C_TEXT_OFF = "#6E7785";
        public static string C_GRIDLINE = "#3C4454";
        public static string C_ROW_HOVER = "#444E5E";
        public static string C_RED_SOFT = "#4D2B2E";
        public static string C_ORANGE_SOFT = "#3A2E1C";
        public static string C_ORANGE_SOFT_HI = "#4C3A20";
        public static string C_GREEN_OFF = "#2F4736";
        public static string C_GREEN_OFF_FG = "#7E8F84";

        public static readonly Dictionary<string, string> DARK_THEME = new Dictionary<string, string>
        {
            { "C_WINDOW", "#3C4454" },
            { "C_CARD", "#1B1F24" },
            { "C_FIELD", "#2D3441" },
            { "C_BAR", "#222933" },
            { "C_EDGE", "#4A5364" },
            { "C_EDGE_SOFT", "#515C6B" },
            { "C_TEXT", "#EEF0F4" },
            { "C_MUTED", "#A4AAB1" },
            { "C_BLUE", "#5AAEEB" },
            { "C_ORANGE", "#E8912D" },
            { "C_GREEN", "#3FA75A" },
            { "C_GREEN_HI", "#4EC06D" },
            { "C_RED", "#FA8880" },
            { "C_SEL", "#3A7392" },
            { "C_SEL_FG", "#FFFFFF" },
            { "C_TYPE_BG", "#5E4018" },
            { "C_TYPE_FG", "#F7C384" },
            { "C_INST_BG", "#24527A" },
            { "C_INST_FG", "#B2DBF8" },
            { "C_RO_BG", "#5E3639" },
            { "C_RO_FG", "#F2B9B6" },
            { "C_EDIT_BG", "#2E6040" },
            { "C_EDIT_FG", "#93EBB0" },
            { "C_FAIL_BG", "#A3302B" },
            { "C_FAIL_FG", "#FFECEA" },
            { "C_TEST_BG", "#493C68" },
            { "C_TEST_FG", "#D3C6F7" },
            { "C_IMP_BG", "#165A62" },
            { "C_IMP_FG", "#93E7EF" },
            { "C_CLEAR", "#00000000" },
            { "C_COPY_BG", "#585020" },
            { "C_COPY_FG", "#F0E5A2" },
            { "C_INDEX_BG", "#283039" },
            { "C_HEADER_BG", "#323C48" },
            { "C_BTN_BG", "#2D3441" },
            { "C_BTN_EDGE", "#4A5364" },
            { "C_SCROLL_BG", "#2D3441" },
            { "C_SCROLL_THUMB", "#56606F" },
            { "C_EDITOR_BG", "#1B1F24" },
            { "C_EDITOR_FG", "#FFFFFF" },
            { "C_BTN_HOVER", "#444E5E" },
            { "C_BTN_OFF", "#262D37" },
            { "C_TEXT_OFF", "#6E7785" },
            { "C_GRIDLINE", "#3C4454" },
            { "C_ROW_HOVER", "#444E5E" },
            { "C_RED_SOFT", "#4D2B2E" },
            { "C_ORANGE_SOFT", "#3A2E1C" },
            { "C_ORANGE_SOFT_HI", "#4C3A20" },
            { "C_GREEN_OFF", "#2F4736" },
            { "C_GREEN_OFF_FG", "#7E8F84" },
        };

        public static readonly Dictionary<string, string> LIGHT_THEME = new Dictionary<string, string>
        {
            { "C_WINDOW", "#F2F2F5" },
            { "C_CARD", "#FFFFFF" },
            { "C_FIELD", "#FFFFFF" },
            { "C_BAR", "#E7E7EC" },
            { "C_EDGE", "#D2D2D9" },
            { "C_EDGE_SOFT", "#BFBFC7" },
            { "C_TEXT", "#1F1F23" },
            { "C_MUTED", "#67676E" },
            { "C_BLUE", "#1E6FB8" },
            { "C_ORANGE", "#B96A0C" },
            { "C_GREEN", "#2E8B48" },
            { "C_GREEN_HI", "#37A455" },
            { "C_RED", "#C0392B" },
            { "C_SEL", "#BCD9F2" },
            { "C_SEL_FG", "#10243A" },
            { "C_TYPE_BG", "#FBE7CC" },
            { "C_TYPE_FG", "#8A4E07" },
            { "C_INST_BG", "#D9E9F8" },
            { "C_INST_FG", "#13507F" },
            { "C_RO_BG", "#F8DAD8" },
            { "C_RO_FG", "#8E3733" },
            { "C_EDIT_BG", "#D8F0DF" },
            { "C_EDIT_FG", "#1B6634" },
            { "C_FAIL_BG", "#C0392B" },
            { "C_FAIL_FG", "#FFFFFF" },
            { "C_TEST_BG", "#E7E1F8" },
            { "C_TEST_FG", "#4B3A86" },
            { "C_IMP_BG", "#D2EFF2" },
            { "C_IMP_FG", "#0F5158" },
            { "C_CLEAR", "#00000000" },
            { "C_COPY_BG", "#FBF3C9" },
            { "C_COPY_FG", "#6B5A12" },
            { "C_INDEX_BG", "#EDEDF1" },
            { "C_HEADER_BG", "#E2E2E8" },
            { "C_BTN_BG", "#FFFFFF" },
            { "C_BTN_EDGE", "#C9C9D1" },
            { "C_SCROLL_BG", "#EDEDF1" },
            { "C_SCROLL_THUMB", "#B6B6BE" },
            { "C_EDITOR_BG", "#FFFFFF" },
            { "C_EDITOR_FG", "#101014" },
            { "C_BTN_HOVER", "#EBEBF1" },
            { "C_BTN_OFF", "#EFEFF3" },
            { "C_TEXT_OFF", "#A8A8B0" },
            { "C_GRIDLINE", "#E3E3E8" },
            { "C_ROW_HOVER", "#EFF4FA" },
            { "C_RED_SOFT", "#FADCDA" },
            { "C_ORANGE_SOFT", "#FBEAD3" },
            { "C_ORANGE_SOFT_HI", "#F6DFC0" },
            { "C_GREEN_OFF", "#DCEDE1" },
            { "C_GREEN_OFF_FG", "#8AA491" },
        };

        /// <summary>Write one palette into the C_* fields. Every C_* reference follows.</summary>
        static void ApplyPalette(Dictionary<string, string> t)
        {
            C_WINDOW = t["C_WINDOW"];
            C_CARD = t["C_CARD"];
            C_FIELD = t["C_FIELD"];
            C_BAR = t["C_BAR"];
            C_EDGE = t["C_EDGE"];
            C_EDGE_SOFT = t["C_EDGE_SOFT"];
            C_TEXT = t["C_TEXT"];
            C_MUTED = t["C_MUTED"];
            C_BLUE = t["C_BLUE"];
            C_ORANGE = t["C_ORANGE"];
            C_GREEN = t["C_GREEN"];
            C_GREEN_HI = t["C_GREEN_HI"];
            C_RED = t["C_RED"];
            C_SEL = t["C_SEL"];
            C_SEL_FG = t["C_SEL_FG"];
            C_TYPE_BG = t["C_TYPE_BG"];
            C_TYPE_FG = t["C_TYPE_FG"];
            C_INST_BG = t["C_INST_BG"];
            C_INST_FG = t["C_INST_FG"];
            C_RO_BG = t["C_RO_BG"];
            C_RO_FG = t["C_RO_FG"];
            C_EDIT_BG = t["C_EDIT_BG"];
            C_EDIT_FG = t["C_EDIT_FG"];
            C_FAIL_BG = t["C_FAIL_BG"];
            C_FAIL_FG = t["C_FAIL_FG"];
            C_TEST_BG = t["C_TEST_BG"];
            C_TEST_FG = t["C_TEST_FG"];
            C_IMP_BG = t["C_IMP_BG"];
            C_IMP_FG = t["C_IMP_FG"];
            C_CLEAR = t["C_CLEAR"];
            C_COPY_BG = t["C_COPY_BG"];
            C_COPY_FG = t["C_COPY_FG"];
            C_INDEX_BG = t["C_INDEX_BG"];
            C_HEADER_BG = t["C_HEADER_BG"];
            C_BTN_BG = t["C_BTN_BG"];
            C_BTN_EDGE = t["C_BTN_EDGE"];
            C_SCROLL_BG = t["C_SCROLL_BG"];
            C_SCROLL_THUMB = t["C_SCROLL_THUMB"];
            C_EDITOR_BG = t["C_EDITOR_BG"];
            C_EDITOR_FG = t["C_EDITOR_FG"];
            C_BTN_HOVER = t["C_BTN_HOVER"];
            C_BTN_OFF = t["C_BTN_OFF"];
            C_TEXT_OFF = t["C_TEXT_OFF"];
            C_GRIDLINE = t["C_GRIDLINE"];
            C_ROW_HOVER = t["C_ROW_HOVER"];
            C_RED_SOFT = t["C_RED_SOFT"];
            C_ORANGE_SOFT = t["C_ORANGE_SOFT"];
            C_ORANGE_SOFT_HI = t["C_ORANGE_SOFT_HI"];
            C_GREEN_OFF = t["C_GREEN_OFF"];
            C_GREEN_OFF_FG = t["C_GREEN_OFF_FG"];
        }


        // Highlight swatches, resolved by name at paint time so a highlight survives a theme switch
        // instead of being burnt in as a hex value.  Each value is (background, foreground).
        public static readonly string[] HIGHLIGHT_COLOURS =
            { "Yellow", "Orange", "Blue", "Green", "Purple", "Red", "Teal", "Grey" };

        public static readonly Dictionary<string, (string Bg, string Fg)> HIGHLIGHT_DARK =
            new Dictionary<string, (string Bg, string Fg)>
            {
                { "Yellow", ("#5C4A16", "#F5D783") },
                { "Orange", ("#5A3413", "#F5B27A") },
                { "Blue", ("#173F5E", "#8FC8F2") },
                { "Green", ("#1E4A2C", "#8BE0A6") },
                { "Purple", ("#3C2C5C", "#C3AAF0") },
                { "Red", ("#552322", "#F0A19D") },
                { "Teal", ("#12474A", "#84D8DC") },
                { "Grey", ("#3A3A40", "#C8C8CE") },
            };

        public static readonly Dictionary<string, (string Bg, string Fg)> HIGHLIGHT_LIGHT =
            new Dictionary<string, (string Bg, string Fg)>
            {
                { "Yellow", ("#FBF0C4", "#6B5410") },
                { "Orange", ("#FBE0C6", "#8A4A0C") },
                { "Blue", ("#D5E8FA", "#11527F") },
                { "Green", ("#D6F1DE", "#1B6634") },
                { "Purple", ("#E6DEF8", "#4A3785") },
                { "Red", ("#FADCDA", "#8E322D") },
                { "Teal", ("#D2EFF1", "#0F5155") },
                { "Grey", ("#E4E4E9", "#4A4A52") },
            };

        /// <summary>"dark" or "light" (Python THEME_NAME).</summary>
        public static string ThemeName = "dark";

        /// <summary>Write one palette into the C_* fields. Every C_* read follows.</summary>
        public static void SetTheme(string name)
        {
            ThemeName = name == "light" ? "light" : "dark";
            ApplyPalette(ThemeName == "light" ? LIGHT_THEME : DARK_THEME);
        }

        /// <summary>(background, foreground) of a highlight swatch for the current theme; unknown names give Yellow.</summary>
        public static (string Bg, string Fg) HighlightColours(string name)
        {
            var table = ThemeName == "light" ? HIGHLIGHT_LIGHT : HIGHLIGHT_DARK;
            (string Bg, string Fg) found;
            if (name != null && table.TryGetValue(name, out found)) return found;
            return table["Yellow"];
        }

        static readonly Dictionary<string, SolidColorBrush> _brushes = new Dictionary<string, SolidColorBrush>();

        /// <summary>Cached frozen SolidColorBrush from a hex string ("#RRGGBB" or "#AARRGGBB").
        /// An unparsable string gives an (unfrozen, uncached-by-meaning) default brush, like the Python.</summary>
        public static SolidColorBrush Brush(string hexstr)
        {
            lock (_brushes)
            {
                SolidColorBrush b;
                if (hexstr != null && _brushes.TryGetValue(hexstr, out b)) return b;
                try
                {
                    b = new SolidColorBrush((System.Windows.Media.Color)ColorConverter.ConvertFromString(hexstr));
                    b.Freeze();
                }
                catch (Exception)
                {
                    b = new SolidColorBrush();
                }
                if (hexstr != null) _brushes[hexstr] = b;
                return b;
            }
        }

        // ---------------------------------------------------------------- helpers ----

        /// <summary>ElementId -> long (0 for null).</summary>
        public static long EidValue(ElementId elementId)
        {
            if (elementId == null) return 0;
            return elementId.Value;
        }

        /// <summary>ElementId from a number.</summary>
        public static ElementId MakeEid(long value)
        {
            try { return new ElementId(value); }
            catch (Exception) { return ElementId.InvalidElementId; }
        }

        /// <summary>Stable key for a ScheduleFieldId.</summary>
        public static string FieldIdKey(ScheduleFieldId fieldId)
        {
            try { return ToText(fieldId.IntegerValue); }
            catch (Exception)
            {
                try { return ToText(fieldId.GetHashCode()); }
                catch (Exception) { return ToText(fieldId); }
            }
        }

        /// <summary>Not null, not -1 (InvalidElementId) and not 0.</summary>
        public static bool IsValidId(ElementId elementId)
        {
            return elementId != null && EidValue(elementId) != -1 && EidValue(elementId) != 0;
        }

        /// <summary>The element's name, "" for null or a name that cannot be read.</summary>
        public static string ElemName(Element elem)
        {
            if (elem == null) return "";
            try { return elem.Name ?? ""; }
            catch (Exception) { return ""; }
        }

        /// <summary>Python u'{0}'.format(value): null is "", numbers use the invariant culture,
        /// bool is "True"/"False", a float keeps ".0" when whole, an exception gives its message.</summary>
        public static string ToText(object value)
        {
            if (value == null) return "";
            try
            {
                string s = value as string;
                if (s != null) return s;
                if (value is bool) return (bool)value ? "True" : "False";
                if (value is double) return FloatText((double)value);
                if (value is float) return FloatText((float)value);
                if (value is Exception) return ((Exception)value).Message;
                if (value is ElementId) return ((ElementId)value).Value.ToString(CultureInfo.InvariantCulture);
                var fmt = value as IFormattable;
                if (fmt != null) return fmt.ToString(null, CultureInfo.InvariantCulture);
                return value.ToString() ?? "";
            }
            catch (Exception)
            {
                return value.ToString() ?? "";
            }
        }

        /// <summary>Python's str(float): shortest round-trip digits, ".0" on whole numbers.</summary>
        static string FloatText(double d)
        {
            if (double.IsNaN(d)) return "nan";
            if (double.IsPositiveInfinity(d)) return "inf";
            if (double.IsNegativeInfinity(d)) return "-inf";
            string s = d.ToString("R", CultureInfo.InvariantCulture);
            if (s.IndexOf('E') >= 0) return s.Replace("E+", "e+").Replace("E-", "e-");
            if (s.IndexOf('.') < 0) s += ".0";
            return s;
        }

        // ------------------------------------------------------------ natural sort ----

        /// <summary>Sort key that treats digit runs as numbers, so P10 follows P9 (Python natural_key).
        /// A list of parts, each (kind, number, text): text parts (0, 0, lower-case text),
        /// digit runs (1, number, ""). Compared part by part like Python's list of tuples.</summary>
        public sealed class NaturalKeyValue : IComparable<NaturalKeyValue>
        {
            internal readonly List<int> Kinds = new List<int>();
            internal readonly List<string> Numbers = new List<string>();   // digit runs without leading zeros
            internal readonly List<string> Texts = new List<string>();

            public int CompareTo(NaturalKeyValue other)
            {
                if (other == null) return 1;
                int n = Math.Min(Kinds.Count, other.Kinds.Count);
                for (int i = 0; i < n; i++)
                {
                    int c = Kinds[i].CompareTo(other.Kinds[i]);
                    if (c != 0) return c;
                    c = CompareNumbers(Numbers[i], other.Numbers[i]);
                    if (c != 0) return c;
                    c = string.CompareOrdinal(Texts[i], other.Texts[i]);
                    if (c != 0) return c;
                }
                return Kinds.Count.CompareTo(other.Kinds.Count);
            }

            static int CompareNumbers(string a, string b)
            {
                if (a.Length != b.Length) return a.Length < b.Length ? -1 : 1;
                int c = string.CompareOrdinal(a, b);
                return c < 0 ? -1 : (c > 0 ? 1 : 0);
            }
        }

        static bool IsAsciiDigit(char c) { return c >= '0' && c <= '9'; }

        /// <summary>The natural-sort key of a text (see <see cref="NaturalKeyValue"/>). Use with OrderBy
        /// (stable, like Python's sorted) or <see cref="NaturalCompare"/>.</summary>
        public static NaturalKeyValue NaturalKey(string text)
        {
            string s = ToText(text);
            var key = new NaturalKeyValue();
            int i = 0;
            // Python re.split(r'(\d+)', s): text, digits, text, ... and always ends with a text part
            // (possibly empty), so the parts alternate starting with text.
            while (true)
            {
                int start = i;
                while (i < s.Length && !IsAsciiDigit(s[i])) i++;
                key.Kinds.Add(0); key.Numbers.Add("0"); key.Texts.Add(s.Substring(start, i - start).ToLowerInvariant());
                if (i >= s.Length) break;
                int ds = i;
                while (i < s.Length && IsAsciiDigit(s[i])) i++;
                string digits = s.Substring(ds, i - ds).TrimStart('0');
                if (digits.Length == 0) digits = "0";
                key.Kinds.Add(1); key.Numbers.Add(digits); key.Texts.Add("");
            }
            return key;
        }

        /// <summary>Compare two texts by natural order.</summary>
        public static int NaturalCompare(string a, string b)
        {
            return NaturalKey(a).CompareTo(NaturalKey(b));
        }

        /// <summary>IComparer for natural order (note: List.Sort is not stable; use OrderBy where Python's stable sort mattered).</summary>
        public static readonly IComparer<string> NaturalComparer = new NaturalStringComparer();

        sealed class NaturalStringComparer : IComparer<string>
        {
            public int Compare(string x, string y) { return NaturalCompare(x, y); }
        }

        // ------------------------------------------------------- images and XAML ----

        /// <summary>Load a frozen BitmapImage from a file path (read into memory first, so the file is not locked).</summary>
        public static BitmapImage LoadImage(string path)
        {
            return LoadImage(new MemoryStream(File.ReadAllBytes(path)));
        }

        /// <summary>Load a frozen BitmapImage from a stream (cached fully on load; the stream may be closed after).</summary>
        public static BitmapImage LoadImage(Stream stream)
        {
            var bi = new BitmapImage();
            bi.BeginInit();
            bi.StreamSource = stream;
            bi.CacheOption = BitmapCacheOption.OnLoad;
            bi.EndInit();
            try { bi.Freeze(); } catch (Exception) { }
            return bi;
        }

        /// <summary>Resolve a short or full logical name to a manifest resource name of this assembly.
        /// A name starting with "RevoBIM." is used as is; anything else gets
        /// <see cref="ImageResourcePrefix"/> in front (so "icons.filldown.png" and "icon.png" work).
        /// Returns null when no such resource exists.</summary>
        public static string FindImageResourceName(string logicalName)
        {
            if (string.IsNullOrEmpty(logicalName)) return null;
            string full = logicalName.StartsWith("RevoBIM.", StringComparison.Ordinal)
                ? logicalName : ImageResourcePrefix + logicalName;
            foreach (string n in typeof(Efr).Assembly.GetManifestResourceNames())
                if (string.Equals(n, full, StringComparison.Ordinal)) return n;
            return null;
        }

        /// <summary>Load a frozen BitmapImage from an embedded resource (full manifest name, or short name
        /// as described at <see cref="FindImageResourceName"/>). Throws when the resource does not exist,
        /// like the Python load_image on a missing file (callers that wrapped it in try/except still do).</summary>
        public static BitmapImage LoadImageResource(string logicalName)
        {
            string name = FindImageResourceName(logicalName);
            if (name == null) throw new FileNotFoundException("Embedded image not found: " + logicalName);
            using (Stream s = typeof(Efr).Assembly.GetManifestResourceStream(name))
            {
                if (s == null) throw new FileNotFoundException("Embedded image not found: " + logicalName);
                var ms = new MemoryStream();
                s.CopyTo(ms);
                ms.Position = 0;
                return LoadImage(ms);
            }
        }

        /// <summary>Parse XAML from a stream (XamlReader.Load). The root is returned (a Window for the main layout).</summary>
        public static object LoadXaml(Stream stream)
        {
            return XamlReader.Load(stream);
        }

        /// <summary>Load a XAML layout embedded as RevoBIM.UI.ExcelForRevit.Layouts.&lt;fileName&gt;
        /// (e.g. "ExcelForRevit.xaml"). Controls are found afterwards with FindName.</summary>
        public static object LoadXamlResource(string fileName)
        {
            string name = fileName.StartsWith("RevoBIM.", StringComparison.Ordinal)
                ? fileName : LayoutResourcePrefix + fileName;
            using (Stream s = typeof(Efr).Assembly.GetManifestResourceStream(name))
            {
                if (s == null) throw new FileNotFoundException("Embedded layout not found: " + name);
                return XamlReader.Load(s);
            }
        }

        /// <summary>Typed form of <see cref="LoadXamlResource(string)"/>.</summary>
        public static T LoadXamlResource<T>(string fileName) where T : class
        {
            return (T)LoadXamlResource(fileName);
        }

        /// <summary>Rename an element; true when it carries the new name afterwards.</summary>
        public static bool SetName(Element elem, string newName)
        {
            try { elem.Name = newName; }
            catch (Exception) { }
            return ElemName(elem) == newName;
        }
    }
}
