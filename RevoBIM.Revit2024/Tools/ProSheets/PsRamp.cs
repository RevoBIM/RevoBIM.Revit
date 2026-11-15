using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace RevoBIM.Tools.ProSheets
{
    /// <summary>
    /// Heading colours: Project Browser Pro's trade ramps, shared look.
    ///
    /// Project Browser Pro colours its main headings by trade, each a solid pill
    /// shaded along that trade's ramp: electrical greens, mechanical blues,
    /// plumbing browns, everything else violets - the same ramps on both themes.
    /// Headings of one trade under the same parent are placed dark to light in
    /// list order; the first level sits at the dark end of the ramp, the second
    /// level in the lighter part. Text on a pill is black or white, whichever has
    /// the better WCAG contrast.
    ///
    /// Kept in step with pbp_palette.RAMPS / LADDER by hand: they are two tools'
    /// constants, not a contract between them. Port of ps_ramp.py.
    /// </summary>
    public static partial class PsRamp
    {
        public const string Electrical = "electrical";
        public const string Mechanical = "mechanical";
        public const string Plumbing = "plumbing";
        public const string Other = "other";

        // Darkest to lightest, per trade.
        public static readonly Dictionary<string, (string Dark, string Light)> Ramps =
            new Dictionary<string, (string Dark, string Light)>(StringComparer.Ordinal)
            {
                { Electrical, ("#17572B", "#A9DFA6") },
                { Mechanical, ("#173F78", "#A9D0F4") },
                { Plumbing, ("#4F3220", "#D9B892") },
                { Other, ("#4B2A6E", "#CDB2EA") },
            };

        // Where on the ramp each heading level is placed, dark end first.
        public static readonly Dictionary<int, (double Low, double High)> Ladder =
            new Dictionary<int, (double Low, double High)>
            {
                { 1, (0.0, 0.3) },
                { 2, (0.38, 0.95) },
            };

        // One level of grouping only (the Selection tab): the whole ramp, so
        // neighbouring groups still differ.
        public static readonly Dictionary<int, (double Low, double High)> SingleLevel =
            new Dictionary<int, (double Low, double High)>
            {
                { 1, (0.0, 0.95) },
            };

        // The words that name a trade, matched as whole words; first match wins.
        // Fire protection is "other" as in Project Browser Pro, and comes before
        // fire alarm's electrical; mechanical comes before plumbing so chilled
        // water is a blue and hot water a brown.
        public static readonly List<(string Trade, string[] Words)> TradeWords =
            new List<(string Trade, string[] Words)>
            {
                (Other, new[] { "FIRE PROTECTION", "SPRINKLER", "SPRINKLERS", "SUPPRESSION",
                                "DRY RISER", "WET RISER" }),
                (Electrical, new[] { "FIRE ALARM", "FIRE ALARMS", "FIRE DETECTION", "SECURITY",
                                     "CCTV", "ACCESS CONTROL", "LIGHTING", "LIGHTNING",
                                     "EMERGENCY LIGHTING", "DATA", "COMMS", "COMMUNICATIONS",
                                     "TELECOMS", "CONTAINMENT", "POWER", "SMALL POWER",
                                     "ELECTRICAL", "ELECTRICS", "ELEC", "LV", "HV",
                                     "EARTHING", "CABLE", "CABLES", "CABLING" }),
                (Mechanical, new[] { "MECHANICAL", "MECH", "HVAC", "HEATING", "COOLING",
                                     "CHILLED", "CONDENSER", "PIPEWORK", "PIPES", "PIPING",
                                     "DUCTWORK", "DUCT", "DUCTS", "AIR", "VENTILATION",
                                     "REFRIGERATION", "REFRIGERANT", "FAN", "FANS", "LTHW",
                                     "CHW", "BMS" }),
                (Plumbing, new[] { "PLUMBING", "PUBLIC HEALTH", "PH", "PHE", "DRAINAGE",
                                   "DRAINS", "SOIL", "WASTE", "RAINWATER", "WATER SERVICES",
                                   "WATER", "SANITARY", "SANITARYWARE" }),
            };

        internal const string Separators = "_-/&,.()[]:;+";

        internal static string Words(object text)
        {
            string body;
            try
            {
                body = Convert.ToString(text ?? "", CultureInfo.InvariantCulture) ?? "";
            }
            catch (Exception)
            {
                return " ";
            }
            body = body.ToUpperInvariant();
            foreach (char mark in Separators)
                body = body.Replace(mark, ' ');
            // Python's str.split(): runs of whitespace, no empty parts.
            string[] parts = body.Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            return " " + string.Join(" ", parts) + " ";
        }

        /// <summary>The trade a heading's name speaks for, or null when it names none.</summary>
        public static string TradeOf(object text)
        {
            string padded = Words(text);
            foreach (var (trade, words) in TradeWords)
            {
                foreach (string word in words)
                {
                    if (padded.Contains(" " + word + " "))
                        return trade;
                }
            }
            return null;
        }

        internal static int[] Channels(string hexText)
        {
            string text = (hexText ?? "").TrimStart('#');
            if (text.Length == 8)
                text = text.Substring(2);                       // #AARRGGBB
            return new[]
            {
                int.Parse(text.Substring(0, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture),
                int.Parse(text.Substring(2, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture),
                int.Parse(text.Substring(4, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture),
            };
        }

        internal static string Hex(IList<double> channels)
        {
            // IronPython 2.7's round() goes half away from zero.
            var parts = channels.Select(value =>
                (int)Math.Round(Math.Max(0.0, Math.Min(255.0, value)), MidpointRounding.AwayFromZero)).ToArray();
            return string.Format(CultureInfo.InvariantCulture, "#{0:X2}{1:X2}{2:X2}", parts[0], parts[1], parts[2]);
        }

        /// <summary><paramref name="amount"/> of the way from dark to light, 0 to 1.</summary>
        public static string Mix(string dark, string light, double amount)
        {
            amount = Math.Max(0.0, Math.Min(1.0, amount));
            int[] low = Channels(dark);
            int[] high = Channels(light);
            var mixed = new double[3];
            for (int i = 0; i < 3; i++)
                mixed[i] = low[i] + (high[i] - low[i]) * amount;
            return Hex(mixed);
        }

        public static string Shade(string trade, double amount)
        {
            if (trade == null || !Ramps.TryGetValue(trade, out var ramp))
                ramp = Ramps[Other];
            return Mix(ramp.Dark, ramp.Light, amount);
        }

        internal static double Luminance(string hexText)
        {
            double total = 0.0;
            double[] weights = { 0.2126, 0.7152, 0.0722 };
            int[] channels = Channels(hexText);
            for (int i = 0; i < 3; i++)
            {
                double part = channels[i] / 255.0;
                part = part <= 0.03928 ? part / 12.92 : Math.Pow((part + 0.055) / 1.055, 2.4);
                total += weights[i] * part;
            }
            return total;
        }

        public static double Contrast(string first, string second)
        {
            double one = Luminance(first) + 0.05;
            double two = Luminance(second) + 0.05;
            return Math.Max(one, two) / Math.Min(one, two);
        }

        /// <summary>Black or white, whichever reads better on this colour.</summary>
        public static string TextOn(string hexText)
        {
            if (Contrast(hexText, "#000000") >= Contrast(hexText, "#FFFFFF"))
                return "#000000";
            return "#FFFFFF";
        }

        /// <summary>
        /// Every heading's colour: {id: hex}.
        ///
        /// <paramref name="headings"/> is (id, label, level, parent id) in list order. A heading
        /// whose name names no trade takes its parent's, then <paramref name="inherit"/> (the
        /// label of whatever the list sits under - a discipline's own tab), then "other". Per
        /// level, headings of one trade under the same parent are spread dark to light across
        /// that level's part of the ramp, in order. Ids are ints: every caller numbers its
        /// headings in list order; a null parent is "none".
        /// </summary>
        public static Dictionary<int, string> Plan(
            IEnumerable<(int Id, string Label, int Level, int? Parent)> headings,
            string inherit = null,
            Dictionary<int, (double Low, double High)> ladder = null)
        {
            if (ladder == null || ladder.Count == 0)
                ladder = Ladder;
            string fallback = !string.IsNullOrEmpty(inherit) ? TradeOf(inherit) : null;
            var trades = new Dictionary<int, string>();
            var order = new List<(int Level, int? Parent, string Trade)>();
            var runs = new Dictionary<(int Level, int? Parent, string Trade), List<int>>();
            foreach (var (hid, label, level, parent) in headings)
            {
                string parentTrade = null;
                if (parent.HasValue)
                    trades.TryGetValue(parent.Value, out parentTrade);
                string trade = TradeOf(label) ?? parentTrade ?? fallback ?? Other;
                trades[hid] = trade;
                var key = (level, parent, trade);
                if (!runs.ContainsKey(key))
                {
                    runs[key] = new List<int>();
                    order.Add(key);
                }
                runs[key].Add(hid);
            }
            var found = new Dictionary<int, string>();
            int top = ladder.Count > 0 ? ladder.Keys.Max() : 1;
            foreach (var key in order)
            {
                if (!ladder.TryGetValue(key.Level, out var span))
                    span = ladder[top];
                double low = span.Low, high = span.High;
                List<int> members = runs[key];
                int count = members.Count;
                for (int index = 0; index < count; index++)
                {
                    double amount = count == 1 ? low : low + (high - low) * index / (double)(count - 1);
                    found[members[index]] = Shade(key.Trade, amount);
                }
            }
            return found;
        }

        // ======================================================================
        // heading colour modes (1.52.0): the Document Register's headings can wear
        // the trade ramps, plain greys, or colours picked heading by heading
        // ======================================================================

        public const string Coloured = "colour";
        public const string Grey = "grey";
        public const string Custom = "custom";
        public static readonly List<string> HeadingModes = new List<string> { Coloured, Grey, Custom };
        public static readonly Dictionary<string, string> ModeLabels =
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                { Coloured, "Coloured headers" },
                { Grey, "Grey headers" },
                { Custom, "Custom headers" },
            };

        // Plain headings: darker for a discipline, lighter for a series - on dark,
        // a step either side of Revit's body; on light, two greys under white.
        public static readonly Dictionary<string, Dictionary<int, string>> Greys =
            new Dictionary<string, Dictionary<int, string>>(StringComparer.Ordinal)
            {
                { "dark", new Dictionary<int, string> { { 1, "#2B313C" }, { 2, "#4A5464" } } },
                { "light", new Dictionary<int, string> { { 1, "#8E97A3" }, { 2, "#C9CED6" } } },
            };

        // The swatches offered for a heading: each ramp's dark, middle and light,
        // then the house accents and two greys.
        public static readonly List<string> Swatches = new List<string>
        {
            "#17572B", "#4E8B5A", "#A9DFA6",
            "#173F78", "#4E76A7", "#A9D0F4",
            "#4F3220", "#83654B", "#D9B892",
            "#4B2A6E", "#7C5E9D", "#CDB2EA",
            "#8B1E1E", "#D9534F", "#E8912D",
            "#D9B23C", "#1F9C9C", "#2B313C",
        };

        /// <summary>A stored mode, or Coloured for anything unknown.</summary>
        public static string HeadingMode(string text)
        {
            text = (text ?? "").Trim().ToLowerInvariant();
            return HeadingModes.Contains(text) ? text : Coloured;
        }

        /// <summary>The mode the button moves on to: Coloured, Grey, Custom, round.</summary>
        public static string NextMode(string mode)
        {
            mode = HeadingMode(mode);
            return HeadingModes[(HeadingModes.IndexOf(mode) + 1) % HeadingModes.Count];
        }

        // ps_ramp.grey: named GreyCore because the Grey mode constant takes the plain name.
        public static string GreyCore(int? level, string themeName)
        {
            string key = (themeName ?? "None").ToLowerInvariant();
            if (!Greys.TryGetValue(key, out var shades))
                shades = Greys["dark"];
            int lvl = (level == null || level.Value == 0) ? 1 : level.Value;
            shades.TryGetValue(lvl <= 1 ? 1 : 2, out string found);
            return found;
        }

        /// <summary>
        /// The colour a heading wears in a mode. Custom starts from the greys
        /// (1.53.0): only the headings given a colour stand out.
        /// </summary>
        public static string ModeColour(string mode, string ramp, int? level, string themeName, string custom = null)
        {
            mode = HeadingMode(mode);
            if (mode == Grey)
                return GreyCore(level, themeName);
            if (mode == Custom)
                return !string.IsNullOrEmpty(custom) ? custom : GreyCore(level, themeName);
            return ramp;
        }

        /// <summary>'#RRGGBB' from what was typed ('3fa75a', '#3FA75A'), or null.</summary>
        public static string ParseHex(string text)
        {
            text = (text ?? "").Trim().TrimStart('#').ToUpperInvariant();
            if (text.Length != 6)
                return null;
            foreach (char c in text)
            {
                if ("0123456789ABCDEF".IndexOf(c) < 0)
                    return null;
            }
            return "#" + text;
        }
    }
}
