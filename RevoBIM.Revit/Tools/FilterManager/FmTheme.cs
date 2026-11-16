using System;
using System.Collections.Generic;
using System.Linq;

namespace RevoBIM.Tools.FilterManager
{
    /// <summary>
    /// The dark and light palettes. Every colour in the tool is a key in here. The layouts reference them with
    /// DynamicResource so the palette can be swapped on an open window with no reload, and code-built elements
    /// read them through Get(). Port of fm_theme.py.
    /// </summary>
    public static class FmTheme
    {
        public static readonly Dictionary<string, string> Dark = new Dictionary<string, string>
        {
            // Revit's own dark theme (2024+): slate blue-greys rather than neutral greys.
            { "WindowBg", "#FF323A47" }, { "Head", "#FF222931" }, { "Panel", "#FF3C4454" }, { "PanelAlt", "#FF363E4C" },
            { "HeaderRow", "#FF323C48" }, { "Field", "#FF2D3441" }, { "FieldDeep", "#FF262C37" },

            { "Edge", "#FF4A5364" }, { "EdgeWindow", "#FF1B1F24" }, { "EdgeSoft", "#FF434C5B" }, { "EdgeFaint", "#FF3A4352" },
            { "EdgeStrong", "#FF5A6372" }, { "BoxEdge", "#FF6A7384" }, { "EdgeHover", "#FF7B8290" },

            { "Txt", "#FFE6EEF7" }, { "Label", "#FFBAC0C8" }, { "Dim", "#FFACB4C2" }, { "TabIdle", "#FFACB2B9" },
            { "TabActiveTxt", "#FFFFFFFF" }, { "Disabled", "#FF6E7584" }, { "Glyph", "#FFACB2B9" }, { "OnAccent", "#FFF2F2F2" },
            { "OnOrange", "#FF1B1F24" },

            { "Blue", "#FF3D9BE9" }, { "Orange", "#FFE8862D" }, { "OrangeEdge", "#FFC96F1E" }, { "OrangeHover", "#FFF39A45" },
            { "Green", "#FF3FA75A" }, { "GreenHover", "#FF4EC06D" }, { "GreenEdge", "#FF2E8546" }, { "Red", "#FFF07A75" },
            { "RedDeep", "#FFB03A36" }, { "RedEdge", "#FF8E2C29" }, { "CloseHover", "#FFC0392B" },

            { "Btn", "#FF2D3441" }, { "BtnHover", "#FF39424F" }, { "BtnPress", "#FF222931" }, { "GlyphHover", "#FF2D3441" },

            { "Sel", "#FF4B5669" }, { "Hover", "#FF39414F" }, { "Thumb", "#FF5A6372" }, { "ThumbHover", "#FF7B8290" },

            { "ChangedBg", "#FF4A3A20" }, { "ChangedEdge", "#FFE8862D" },

            { "ArrowBg", "#FF1B1F24" }, { "ArrowHover", "#FF12151A" }, { "ArrowPress", "#FF2D3441" },
        };

        public static readonly Dictionary<string, string> Light = new Dictionary<string, string>
        {
            { "WindowBg", "#FFF4F4F6" }, { "Head", "#FFE7E7EC" }, { "Panel", "#FFFFFFFF" }, { "PanelAlt", "#FFF1F1F5" },
            { "HeaderRow", "#FFEBEBF0" }, { "Field", "#FFFFFFFF" }, { "FieldDeep", "#FFFAFAFC" },

            { "Edge", "#FFC6C6CE" }, { "EdgeWindow", "#FFB4B4BE" }, { "EdgeSoft", "#FFCFCFD6" }, { "EdgeFaint", "#FFDCDCE2" },
            { "EdgeStrong", "#FFAEAEB8" }, { "BoxEdge", "#FFA6A6B0" }, { "EdgeHover", "#FF96969E" },

            { "Txt", "#FF1E1E22" }, { "Label", "#FF5A5A62" }, { "Dim", "#FF5E5E66" }, { "TabIdle", "#FF6A6A72" },
            { "TabActiveTxt", "#FF16161A" }, { "Disabled", "#FFA2A2AA" }, { "Glyph", "#FF3A3A40" }, { "OnAccent", "#FFFFFFFF" },
            { "OnOrange", "#FF1E1E1E" },

            { "Blue", "#FF1B72BE" }, { "Orange", "#FFB96A12" }, { "OrangeEdge", "#FF95560E" }, { "OrangeHover", "#FFD07C1C" },
            { "Green", "#FF2E8546" }, { "GreenHover", "#FF3FA75A" }, { "GreenEdge", "#FF24693A" }, { "Red", "#FFC0392B" },
            { "RedDeep", "#FFB03A36" }, { "RedEdge", "#FF8E2C29" }, { "CloseHover", "#FFC0392B" },

            { "Btn", "#FFE4E4EA" }, { "BtnHover", "#FFD6D6DE" }, { "BtnPress", "#FFC6C6D0" }, { "GlyphHover", "#FFDCDCE4" },

            { "Sel", "#FFCBDCEC" }, { "Hover", "#FFE3EAF2" }, { "Thumb", "#FFB6B6C0" }, { "ThumbHover", "#FF90909A" },

            { "ChangedBg", "#FFFFF0D2" }, { "ChangedEdge", "#FFB96A12" },

            { "ArrowBg", "#FF1E1E24" }, { "ArrowHover", "#FF000000" }, { "ArrowPress", "#FF34343A" },
        };

        private static string _current = "dark";

        /// <summary>"dark" or "light": the palette in force.</summary>
        public static string Name { get { return _current; } }

        public static string SetPalette(string paletteName)
        {
            _current = string.Equals(paletteName, "light", StringComparison.OrdinalIgnoreCase) ? "light" : "dark";
            return _current;
        }

        public static string Toggle() { return SetPalette(_current == "light" ? "dark" : "light"); }

        // Mode: what the user picked. "auto" follows Revit's canvas theme, so the palette is a consequence of
        // the mode rather than the setting itself.
        public static readonly string[] Modes = { "auto", "dark", "light" };
        public static readonly Dictionary<string, string> ModeLabels = new Dictionary<string, string>
        {
            { "auto", "Auto" }, { "dark", "Dark" }, { "light", "Light" },
        };

        private static string _mode = "auto";
        public static string Mode { get { return _mode; } }

        /// <summary>A saved value back to a mode. Anything unknown is auto.</summary>
        public static string ParseMode(string value)
        {
            string text = (value ?? "").Trim().ToLowerInvariant();
            if (text == "follow" || text == "auto" || text == "revit" || text == "system") return "auto";
            return Array.IndexOf(Modes, text) >= 0 ? text : "auto";
        }

        /// <summary>Set the mode and the palette it implies. detected is what Revit is showing ("dark"/"light"/null).</summary>
        public static string SetMode(string value, string detected = null)
        {
            _mode = ParseMode(value);
            return SetPalette(Resolve(_mode, detected));
        }

        public static string Resolve(string modeValue, string detected = null)
        {
            string m = ParseMode(modeValue);
            if (m == "auto") return string.Equals(detected ?? "", "light", StringComparison.OrdinalIgnoreCase) ? "light" : "dark";
            return m;
        }

        /// <summary>Auto, Dark, Light, Auto: the order the header chip cycles.</summary>
        public static string NextMode(string modeValue)
        {
            string m = ParseMode(modeValue);
            return Modes[(Array.IndexOf(Modes, m) + 1) % Modes.Length];
        }

        public static Dictionary<string, string> Current { get { return _current == "light" ? Light : Dark; } }

        public static string Get(string key, string fallback = "#FF808080")
        {
            string value;
            if (Current.TryGetValue(key, out value)) return value;
            return Dark.TryGetValue(key, out value) ? value : fallback;
        }
    }
}
