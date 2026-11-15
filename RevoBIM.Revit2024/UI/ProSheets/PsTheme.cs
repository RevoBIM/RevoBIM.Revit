using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Media;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// The dark and light palettes, and applying one to a live window. Port of theme.py.
    ///
    /// Both palettes carry exactly the same keys. The light palette is not the
    /// dark one inverted - the accents are darkened, because the dark palette's
    /// accents are chosen to sit on near-black and wash out on white.
    ///
    /// Apply writes the brushes straight onto window.Resources, which sits in
    /// front of a merged dictionary in WPF's lookup order. That is what lets the
    /// palette be swapped on an open window with no reload and no loss of state.
    /// </summary>
    public static class PsTheme
    {
        // Revit's own dark theme (1.50.0), measured from Revit's dark Project
        // Browser: title bar #222933, body #3C4454, search field #2D3441, hover
        // #444E5E, selection Revit's active blue #3A7392. Blue is a step brighter
        // than the house blue so it still reads on the lighter body.
        public static readonly Dictionary<string, string> Dark = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["WindowBg"] = "#3C4454",
            ["CardBg"] = "#353D4B",
            ["FieldBg"] = "#2D3441",
            ["BarBg"] = "#222933",
            ["HeaderBg"] = "#323C48",
            ["TabActiveBg"] = "#353D4B",
            ["TabInactiveBg"] = "#2B313C",
            ["EdgeBrush"] = "#4A5464",
            ["WindowEdgeBrush"] = "#515C6B",
            ["GridLineBrush"] = "#46505F",
            ["HoverBrush"] = "#444E5E",
            ["TextBrush"] = "#EEF0F4",
            ["MutedBrush"] = "#A4AAB1",
            ["DisabledBrush"] = "#6E7684",
            ["BlueBrush"] = "#5AAEEB",
            ["OrangeBrush"] = "#E8912D",
            ["GreenBrush"] = "#3FA75A",
            ["GreenHoverBrush"] = "#4EC06D",
            // Text sitting on a solid orange fill: near-black on the bright dark-mode
            // orange, white on the deeper light-mode one.
            ["OnOrangeBrush"] = "#1E1E20",
            // A faint wash of green behind the Export to Excel button.
            ["GreenWashBrush"] = "#3D5855",
            // A faint wash of orange down a revision column picked on the register.
            ["PickWashBrush"] = "#5E534C",
            ["RedBrush"] = "#D9534F",
            ["SelectionBrush"] = "#3A7392",
            ["RowAltBrush"] = "#394151",
            ["ChipBg"] = "#323C48",
            // One colour per sort level, so which column is first and which is
            // third is readable without counting the badges.
            ["SortL1"] = "#E8912D",
            ["SortL2"] = "#4FA3E3",
            ["SortL3"] = "#3FA75A",
            ["SortL4"] = "#A98BE8",
            ["SortL5"] = "#46BFBF",
            ["SortL6"] = "#D9B23C",
            // One colour per export format, so a glance at the Format tab says
            // which formats are ticked without reading the labels.
            ["DoneRowBrush"] = "#3D5D56",
            ["FailedRowBrush"] = "#634853",
            ["FmtPdf"] = "#D0443A",
            ["FmtDwg"] = "#2C6FC4",
            ["FmtDwf"] = "#6E7684",
            ["FmtNwc"] = "#1F9C9C",
            ["FmtIfc"] = "#5A6BD6",
            ["FmtDwgInk"] = "#F2B417",
            ["FmtNwcInk"] = "#6FD8D8",
            ["FmtIfcInk"] = "#C3CBF5",
        };

        public static readonly Dictionary<string, string> Light = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["WindowBg"] = "#F2F2F4",
            ["CardBg"] = "#FFFFFF",
            ["FieldBg"] = "#FFFFFF",
            ["BarBg"] = "#E4E4E8",
            ["HeaderBg"] = "#EAEAEE",
            ["TabActiveBg"] = "#FFFFFF",
            ["TabInactiveBg"] = "#DEDEE4",
            ["EdgeBrush"] = "#C8C8CE",
            ["WindowEdgeBrush"] = "#B4B4BC",
            ["GridLineBrush"] = "#DCDCE2",
            ["HoverBrush"] = "#E8E8EC",
            ["TextBrush"] = "#1E1E20",
            ["MutedBrush"] = "#6A6A70",
            ["DisabledBrush"] = "#A8A8AE",
            ["BlueBrush"] = "#1B72BE",
            ["OrangeBrush"] = "#B96A12",
            ["GreenBrush"] = "#2E8546",
            ["GreenHoverBrush"] = "#3A9C56",
            ["OnOrangeBrush"] = "#FFFFFF",
            ["GreenWashBrush"] = "#E3F2E7",
            ["PickWashBrush"] = "#FBEAD6",
            ["RedBrush"] = "#B5342F",
            ["SelectionBrush"] = "#CADEF0",
            ["RowAltBrush"] = "#F7F7F9",
            ["ChipBg"] = "#DCDCE2",
            ["SortL1"] = "#B96A12",
            ["SortL2"] = "#1B72BE",
            ["SortL3"] = "#2E8546",
            ["SortL4"] = "#6E4CC4",
            ["SortL5"] = "#1E8C8C",
            ["SortL6"] = "#96760F",
            ["DoneRowBrush"] = "#DCEFE0",
            ["FailedRowBrush"] = "#F6DDDE",
            ["FmtPdf"] = "#B8322A",
            ["FmtDwg"] = "#1B5FB4",
            ["FmtDwf"] = "#8A8A90",
            ["FmtNwc"] = "#14807F",
            ["FmtIfc"] = "#4353BE",
            ["FmtDwgInk"] = "#E5A80C",
            ["FmtNwcInk"] = "#5FC6C6",
            ["FmtIfcInk"] = "#B6BFF0",
        };

        public static readonly Dictionary<string, Dictionary<string, string>> Palettes =
            new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal)
            {
                ["dark"] = Dark,
                ["light"] = Light,
            };

        /// <summary>The sort level colours in order, for code that needs the nth one.</summary>
        public static readonly string[] SortLevelKeys = { "SortL1", "SortL2", "SortL3", "SortL4", "SortL5", "SortL6" };

        /// <summary>The palette key for sort level 0, 1, 2... wrapping past the sixth.</summary>
        public static string SortLevelKey(int level)
        {
            return SortLevelKeys[PyMod(level, SortLevelKeys.Length)];
        }

        // ==================================================================
        // a colour per group
        //
        // The six sort level colours are a fixed list because there are only
        // ever six sort levels. Groups are not like that: a column of
        // disciplines has as many groups as it has values. So they are
        // generated - evenly spaced hues at a fixed saturation and lightness,
        // tuned per theme so the text on top stays readable. Starting at the
        // house orange means the first group looks like the rest of the window.
        // ==================================================================

        public const int GroupHues = 12;
        public const double GroupStartHue = 28.0;

        /// <summary>
        /// Saturation, lightness for a cell, lightness for a heading band. The
        /// heading is the quieter of the two: its text is blue, and blue on a
        /// saturated band cannot be read, so the band is a dark tint in dark mode
        /// and a pale one in light mode. Cells a step lighter from 1.50.0, so a
        /// chip stands off Revit's lighter dark body.
        /// </summary>
        public static readonly Dictionary<string, (double Saturation, double Cell, double Head)> GroupTone =
            new Dictionary<string, (double Saturation, double Cell, double Head)>(StringComparer.Ordinal)
            {
                ["dark"] = (0.42, 0.36, 0.17),
                ["light"] = (0.72, 0.78, 0.945),
            };

        internal static double HueToChannel(double p, double q, double t)
        {
            if (t < 0) t += 1.0;
            if (t > 1) t -= 1.0;
            if (t < 1.0 / 6.0) return p + (q - p) * 6.0 * t;
            if (t < 0.5) return q;
            if (t < 2.0 / 3.0) return p + (q - p) * (2.0 / 3.0 - t) * 6.0;
            return p;
        }

        /// <summary>An HSL triple as a #RRGGBB string. Hue in degrees.</summary>
        public static string Hsl(double hue, double saturation, double lightness)
        {
            double h = PyFloatMod(hue, 360.0) / 360.0;
            double s = Math.Max(0.0, Math.Min(1.0, saturation));
            double l = Math.Max(0.0, Math.Min(1.0, lightness));
            double red, green, blue;
            if (s == 0)
            {
                red = green = blue = l;
            }
            else
            {
                double q = l < 0.5 ? l * (1.0 + s) : l + s - l * s;
                double p = 2.0 * l - q;
                red = HueToChannel(p, q, h + 1.0 / 3.0);
                green = HueToChannel(p, q, h);
                blue = HueToChannel(p, q, h - 1.0 / 3.0);
            }
            return "#" + Channel(red) + Channel(green) + Channel(blue);
        }

        private static string Channel(double value)
        {
            // Python 2 round(): half away from zero.
            int number = (int)Math.Round(value * 255, MidpointRounding.AwayFromZero);
            return number.ToString("X2", CultureInfo.InvariantCulture);
        }

        /// <summary>
        /// The nth group's colour, as a hex string. Cycles after GroupHues, which
        /// is as many distinct hues as can be told apart at this saturation.
        /// </summary>
        public static string GroupColour(int index, string themeName, bool heading = false)
        {
            if (!GroupTone.TryGetValue(PyStrLower(themeName), out var tone)) tone = GroupTone["dark"];
            double hue = GroupStartHue + PyMod(index, GroupHues) * (360.0 / GroupHues);
            return Hsl(hue, tone.Saturation, heading ? tone.Head : tone.Cell);
        }

        private static readonly Dictionary<string, SolidColorBrush> BrushCache =
            new Dictionary<string, SolidColorBrush>(StringComparer.Ordinal);

        /// <summary>The palette dictionary for 'dark' or 'light'; dark for anything else.</summary>
        public static Dictionary<string, string> Palette(string name)
        {
            return Palettes.TryGetValue(PyStrLower(name).Trim(), out var found) ? found : Dark;
        }

        /// <summary>A frozen SolidColorBrush for a hex string, cached and shared. Throws on a bad colour, as the Python does.</summary>
        public static SolidColorBrush Brush(string hexText)
        {
            string key = hexText ?? "None";
            if (BrushCache.TryGetValue(key, out var found)) return found;
            var made = new SolidColorBrush((Color)ColorConverter.ConvertFromString(key));
            try
            {
                made.Freeze();
            }
            catch (Exception)
            {
            }
            BrushCache[key] = made;
            return made;
        }

        /// <summary>
        /// The same colour at a fraction of its strength. Used for the rows under
        /// a group heading: full strength on the heading, a wash on its members.
        /// </summary>
        public static SolidColorBrush Tinted(string hexText, double alpha)
        {
            try
            {
                var colour = (Color)ColorConverter.ConvertFromString(hexText ?? "None");
                var faded = Color.FromArgb((byte)(int)Math.Max(0, Math.Min(255, alpha)), colour.R, colour.G, colour.B);
                var made = new SolidColorBrush(faded);
                try
                {
                    made.Freeze();
                }
                catch (Exception)
                {
                }
                return made;
            }
            catch (Exception)
            {
                return Brush(hexText);
            }
        }

        /// <summary>The hex string for a palette key, falling back to the dark palette.</summary>
        public static string Colour(string themeName, string key)
        {
            var pal = Palette(themeName);
            if (pal.TryGetValue(key, out var value)) return value;
            return Dark.TryGetValue(key, out var dark) ? dark : "#FF00FF";
        }

        /// <summary>
        /// Write every brush of the named palette onto the window's own resources.
        /// Local resources sit in front of the merged Theme.xaml, so every
        /// DynamicResource re-resolves to these and the open window repaints.
        /// </summary>
        public static Dictionary<string, string> Apply(FrameworkElement window, string themeName)
        {
            var pal = Palette(themeName);
            foreach (string key in pal.Keys.OrderBy(k => k, StringComparer.Ordinal))
            {
                try
                {
                    window.Resources[key] = Brush(pal[key]);
                }
                catch (Exception)
                {
                }
            }
            ApplySystemColours(window, pal);
            return pal;
        }

        /// <summary>
        /// Put the palette behind Windows' own selection brushes too. Anything
        /// that falls back to a default control template paints its selection
        /// with SystemColors, and the inactive one is near white - so a selected
        /// row in a grid that lost focus comes out as a white bar across a dark
        /// window. Keyed by the SystemColors key objects; each written on its own.
        /// </summary>
        public static void ApplySystemColours(FrameworkElement window, Dictionary<string, string> pal)
        {
            var wanted = new (ResourceKey Key, string PaletteKey)[]
            {
                (SystemColors.HighlightBrushKey, "SelectionBrush"),
                (SystemColors.HighlightTextBrushKey, "TextBrush"),
                (SystemColors.InactiveSelectionHighlightBrushKey, "SelectionBrush"),
                (SystemColors.InactiveSelectionHighlightTextBrushKey, "TextBrush"),
                (SystemColors.ControlBrushKey, "CardBg"),
                (SystemColors.WindowBrushKey, "WindowBg"),
            };
            foreach (var (key, paletteKey) in wanted)
            {
                try
                {
                    if (key == null) continue;
                    window.Resources[key] = Brush(pal[paletteKey]);
                }
                catch (Exception)
                {
                }
            }
        }

        /// <summary>
        /// Whatever light/dark mode Revit's own canvas is set to right now.
        /// UIThemeManager arrived in Revit 2024 and is the only honest source -
        /// the registry lags the live setting. Anything unexpected falls back to
        /// the caller's default, because this is only ever a starting guess.
        /// The canvas theme is read first (as the docstring intends and the
        /// Legend Creator port does), then the UI theme.
        /// </summary>
        public static string DetectRevitTheme(string @default = "dark")
        {
            try
            {
                Autodesk.Revit.UI.UITheme canvas = Autodesk.Revit.UI.UIThemeManager.CurrentCanvasTheme;
                if (canvas == Autodesk.Revit.UI.UITheme.Light) return "light";
                if (canvas == Autodesk.Revit.UI.UITheme.Dark) return "dark";
            }
            catch (Exception)
            {
            }
            try
            {
                Autodesk.Revit.UI.UITheme current = Autodesk.Revit.UI.UIThemeManager.CurrentTheme;
                if (current == Autodesk.Revit.UI.UITheme.Light) return "light";
                if (current == Autodesk.Revit.UI.UITheme.Dark) return "dark";
            }
            catch (Exception)
            {
            }
            return @default;
        }

        public static readonly string[] Modes = { "follow", "dark", "light" };

        /// <summary>
        /// The saved setting as one of the three modes. Anything unrecognised -
        /// including a blank first run and the palette names older versions wrote
        /// here by mistake - comes back as 'follow', the house standard.
        /// </summary>
        public static string Mode(string settingValue)
        {
            string text = (settingValue ?? "").Trim().ToLowerInvariant();
            return Modes.Contains(text) ? text : "follow";
        }

        /// <summary>
        /// Turn a saved theme setting into an actual palette name. 'follow' takes
        /// Revit's current canvas theme; 'dark' and 'light' pin it.
        /// </summary>
        public static string Resolve(string settingValue, string @default = "dark")
        {
            string text = (settingValue ?? "").Trim().ToLowerInvariant();
            if (text == "dark" || text == "light") return text;
            return DetectRevitTheme(@default);
        }

        // ---------------------------------------------------------------- helpers

        /// <summary>Python str(x).lower(): None becomes 'none'.</summary>
        private static string PyStrLower(string text)
        {
            return (text ?? "None").ToLowerInvariant();
        }

        /// <summary>Python's integer % (result takes the divisor's sign).</summary>
        internal static int PyMod(int value, int divisor)
        {
            int result = value % divisor;
            return result < 0 ? result + divisor : result;
        }

        internal static double PyFloatMod(double value, double divisor)
        {
            double result = value % divisor;
            return result < 0 ? result + divisor : result;
        }
    }
}
