using System;
using System.Collections.Generic;
using System.Globalization;

namespace RevoBIM.Arcade.Core
{
    /// <summary>
    /// RevoBIM.Arcade.exe --game &lt;key&gt; --theme &lt;light|dark&gt;
    ///                    [--owner-x n --owner-y n --owner-w n --owner-h n] [--selftest]
    /// Parsing never throws: bad input is dropped and recorded in <see cref="Warnings"/>.
    /// </summary>
    public sealed class LaunchOptions
    {
        public string? GameKey { get; private set; }
        public string Theme { get; private set; } = ThemeNames.Dark;
        public bool SelfTest { get; private set; }

        /// <summary>Owner rectangle in screen pixels, only when all four numbers were valid.</summary>
        public (int X, int Y, int W, int H)? Owner { get; private set; }

        public List<string> Warnings { get; } = new List<string>();

        public static LaunchOptions Parse(string[]? args)
        {
            var o = new LaunchOptions();
            if (args == null) return o;

            int? x = null, y = null, w = null, h = null;

            for (int i = 0; i < args.Length; i++)
            {
                var raw = args[i];
                if (raw == null) continue;
                string name = raw, value = null!;
                bool hasValue = false;

                int eq = raw.IndexOf('=');
                if (raw.StartsWith("--", StringComparison.Ordinal) && eq > 2)
                {
                    name = raw.Substring(0, eq);
                    value = raw.Substring(eq + 1);
                    hasValue = true;
                }
                name = name.ToLowerInvariant();

                string? Next()
                {
                    if (hasValue) return value;
                    if (i + 1 < args.Length && !(args[i + 1] ?? "").StartsWith("--", StringComparison.Ordinal))
                        return args[++i];
                    return null;
                }

                switch (name)
                {
                    case "--selftest": o.SelfTest = true; break;
                    case "--game":
                        var g = Next();
                        if (string.IsNullOrWhiteSpace(g)) o.Warnings.Add("--game needs a value");
                        else o.GameKey = g.Trim().ToLowerInvariant();
                        break;
                    case "--theme":
                        var t = Next();
                        if (ThemeNames.TryNormalise(t, out var theme)) o.Theme = theme;
                        else o.Warnings.Add($"--theme '{t}' is not light or dark; using dark");
                        break;
                    case "--owner-x": x = Int(Next(), name, o); break;
                    case "--owner-y": y = Int(Next(), name, o); break;
                    case "--owner-w": w = Int(Next(), name, o); break;
                    case "--owner-h": h = Int(Next(), name, o); break;
                    default:
                        o.Warnings.Add($"ignored argument '{raw}'");
                        break;
                }
            }

            if (x.HasValue || y.HasValue || w.HasValue || h.HasValue)
            {
                if (x.HasValue && y.HasValue && w.HasValue && h.HasValue && w > 0 && h > 0)
                    o.Owner = (x.Value, y.Value, w.Value, h.Value);
                else
                    o.Warnings.Add("owner rectangle needs --owner-x, -y, -w and -h (w and h above zero); centring on the screen");
            }
            return o;
        }

        static int? Int(string? text, string name, LaunchOptions o)
        {
            if (int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out var v)) return v;
            o.Warnings.Add($"{name} '{text}' is not a whole number");
            return null;
        }
    }

    public static class ThemeNames
    {
        public const string Dark = "dark";
        public const string Light = "light";

        public static bool TryNormalise(string? text, out string theme)
        {
            theme = Dark;
            if (string.IsNullOrWhiteSpace(text)) return false;
            switch (text.Trim().ToLowerInvariant())
            {
                case "dark": theme = Dark; return true;
                case "light": theme = Light; return true;
                default: return false;
            }
        }
    }
}
