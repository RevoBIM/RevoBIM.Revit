using System;

namespace RevoBIM.Tools.FilterManager
{
    /// <summary>
    /// Colour maths for the picker. Hue, saturation and luminosity use the same 0-239 / 0-240 ranges Windows and
    /// Revit's own colour dialog use. Port of fm_colour.py.
    /// </summary>
    public static class FmColour
    {
        public const double HueMax = 239.0;
        public const double SatMax = 240.0;
        public const double LumMax = 240.0;

        public static double Clamp(double value, double low, double high) { return Math.Max(low, Math.Min(high, value)); }

        private static int Round(double v) { return (int)Math.Round(v, MidpointRounding.AwayFromZero); }

        /// <summary>(0-255, 0-255, 0-255) to (hue 0-239, sat 0-240, lum 0-240).</summary>
        public static int[] RgbToHsl(int r, int g, int b)
        {
            double rf = r / 255.0, gf = g / 255.0, bf = b / 255.0;
            double high = Math.Max(rf, Math.Max(gf, bf));
            double low = Math.Min(rf, Math.Min(gf, bf));
            double lum = (high + low) / 2.0;

            if (high == low) return new[] { 0, 0, Round(lum * LumMax) };

            double delta = high - low;
            double sat = lum < 0.5 ? delta / (high + low) : delta / (2.0 - high - low);
            double hue;
            if (high == rf)
            {
                hue = (gf - bf) / delta;
                if (gf < bf) hue += 6.0;
            }
            else if (high == gf) hue = 2.0 + (bf - rf) / delta;
            else hue = 4.0 + (rf - gf) / delta;
            hue = hue / 6.0;

            return new[] { Round(hue * HueMax), Round(sat * SatMax), Round(lum * LumMax) };
        }

        /// <summary>(hue 0-239, sat 0-240, lum 0-240) to (0-255, 0-255, 0-255).</summary>
        public static int[] HslToRgb(double hue, double sat, double lum)
        {
            double h = Clamp(hue, 0.0, HueMax) / HueMax;
            double s = Clamp(sat, 0.0, SatMax) / SatMax;
            double l = Clamp(lum, 0.0, LumMax) / LumMax;

            if (s == 0)
            {
                int v = Round(l * 255);
                return new[] { v, v, v };
            }

            double q = l < 0.5 ? l * (1.0 + s) : l + s - (l * s);
            double p = 2.0 * l - q;
            return new[]
            {
                Round(Channel(p, q, h + 1.0 / 3.0) * 255),
                Round(Channel(p, q, h) * 255),
                Round(Channel(p, q, h - 1.0 / 3.0) * 255),
            };
        }

        private static double Channel(double p, double q, double t)
        {
            if (t < 0) t += 1.0;
            if (t > 1) t -= 1.0;
            if (t < 1.0 / 6.0) return p + (q - p) * 6.0 * t;
            if (t < 1.0 / 2.0) return q;
            if (t < 2.0 / 3.0) return p + (q - p) * (2.0 / 3.0 - t) * 6.0;
            return p;
        }

        public static string ToHex(int[] rgb)
        {
            return ((int)Clamp(rgb[0], 0, 255)).ToString("X2") + ((int)Clamp(rgb[1], 0, 255)).ToString("X2") +
                   ((int)Clamp(rgb[2], 0, 255)).ToString("X2");
        }

        public static int[] FromHex(string text)
        {
            if (text == null) return null;
            string s = text.Trim().TrimStart('#');
            if (s.Length != 6) return null;
            try
            {
                return new[] { Convert.ToInt32(s.Substring(0, 2), 16), Convert.ToInt32(s.Substring(2, 2), 16), Convert.ToInt32(s.Substring(4, 2), 16) };
            }
            catch (Exception) { return null; }
        }

        /// <summary>The 48 swatches Windows and Revit both open with.</summary>
        public static readonly string[] BasicColours =
        {
            "FF8080", "FFFF80", "80FF80", "00FF80", "80FFFF", "0080FF", "FF80C0", "FF80FF",
            "FF0000", "FFFF00", "80FF00", "00FF40", "00FFFF", "0080C0", "8080C0", "FF00FF",
            "804040", "FF8040", "00FF00", "008080", "004080", "8080FF", "800040", "FF0080",
            "800000", "FF8000", "008000", "008040", "0000FF", "0000A0", "800080", "8000FF",
            "400000", "804000", "004000", "004040", "000080", "000040", "400040", "400080",
            "000000", "808000", "808040", "808080", "408080", "C0C0C0", "400040", "FFFFFF",
        };
    }
}
