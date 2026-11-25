using System;
using System.Collections.Generic;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using Autodesk.Revit.UI;
using RevoBIM.Tools.AddinManager;

using ContextMenu = System.Windows.Controls.ContextMenu;

namespace RevoBIM.UI.AddinManager
{
    /// <summary>Palettes and following Revit. Port of rba_theme.py.</summary>
    internal static class AmTheme
    {
        private static readonly Dictionary<string, string> Dark = new Dictionary<string, string>
        {
            { "BgWindow", "#3B4453" }, { "BgCard", "#333B49" }, { "BgField", "#2C3440" }, { "BgBar", "#222933" },
            { "BgHover", "#414B5A" }, { "BrdEdge", "#515C6B" }, { "BrdWindow", "#515C6B" }, { "FgText", "#F5F5F5" },
            { "FgMuted", "#9DA5B0" }, { "AccBlue", "#4FA3E3" }, { "AccOrange", "#E8912D" }, { "AccGreen", "#3FA75A" },
            { "AccGreenHover", "#4EC06D" }, { "AccRed", "#D9534F" }, { "AccStar", "#F5C542" }, { "ShadowColor", "#000000" },
            { "SelHighlight", "#2D5B80" },
        };

        private static readonly Dictionary<string, string> Light = new Dictionary<string, string>
        {
            { "BgWindow", "#F2F2F4" }, { "BgCard", "#FFFFFF" }, { "BgField", "#FFFFFF" }, { "BgBar", "#E8E8EC" },
            { "BgHover", "#E3E9F0" }, { "BrdEdge", "#C7C7CC" }, { "BrdWindow", "#B4B4BC" }, { "FgText", "#1F1F22" },
            { "FgMuted", "#6A6A70" }, { "AccBlue", "#1B72BE" }, { "AccOrange", "#B96A12" }, { "AccGreen", "#2E8546" },
            { "AccGreenHover", "#3C9B57" }, { "AccRed", "#B5403C" }, { "AccStar", "#D49B00" }, { "ShadowColor", "#5A6070" },
            { "SelHighlight", "#CBDDEE" },
        };

        private static readonly string[] Modes = { "auto", "dark", "light" };

        /// <summary>"dark", "light", or null where Revit will not say. The canvas is asked first, the ribbon theme second.</summary>
        public static string RevitTheme()
        {
            try { return UIThemeManager.CurrentCanvasTheme == UITheme.Dark ? "dark" : "light"; } catch (Exception) { }
            try { return UIThemeManager.CurrentTheme == UITheme.Dark ? "dark" : "light"; } catch (Exception) { }
            return null;
        }

        public static string Resolve(string mode)
        {
            mode = (mode ?? "").Trim().ToLowerInvariant();
            if (mode == "dark" || mode == "light") return mode;
            return RevitTheme() ?? "dark";
        }

        public static string NextMode(string mode)
        {
            int at = Array.IndexOf(Modes, (mode ?? "").Trim().ToLowerInvariant());
            return at < 0 ? "dark" : Modes[(at + 1) % Modes.Length];
        }

        public static Dictionary<string, string> Palette(string name) { return name == "light" ? Light : Dark; }

        /// <summary>Writes the palette onto the element's own Resources, in front of the merged Theme.xaml.</summary>
        public static void Apply(FrameworkElement element, string name)
        {
            foreach (KeyValuePair<string, string> entry in Palette(name))
            {
                try
                {
                    Color color = (Color)ColorConverter.ConvertFromString(entry.Value);
                    if (entry.Key.EndsWith("Color", StringComparison.Ordinal)) element.Resources[entry.Key] = color;
                    else element.Resources[entry.Key] = new SolidColorBrush(color);
                }
                catch (Exception)
                {
                }
            }
        }

        public static Brush Brush(string hex)
        {
            return new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
        }
    }

    /// <summary>Loads the pyRevit XAML layouts, unchanged, from UI\AddinManager\Layouts. Theme.xaml is merged after parsing, so layouts use DynamicResource only.</summary>
    internal static class AmXaml
    {
        private const string Prefix = "RevoBIM.UI.AddinManager.Layouts.";

        public static string ReadLayout(string file)
        {
            using (Stream stream = typeof(AmXaml).Assembly.GetManifestResourceStream(Prefix + file))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + Prefix + file + " was not found");
                using (var reader = new StreamReader(stream, System.Text.Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        public static T Load<T>(string file, string palette) where T : FrameworkElement
        {
            var element = XamlReader.Parse(ReadLayout(file)) as T;
            if (element == null) throw new InvalidCastException(file + " is not a " + typeof(T).Name);
            MergeTheme(element);
            AmTheme.Apply(element, palette);
            return element;
        }

        public static void MergeTheme(FrameworkElement element)
        {
            var dictionary = XamlReader.Parse(ReadLayout("Theme.xaml")) as ResourceDictionary;
            if (dictionary == null) throw new InvalidCastException("Theme.xaml did not parse as a ResourceDictionary");
            element.Resources.MergedDictionaries.Add(dictionary);
        }

        public static void MergeTheme(ContextMenu menu)
        {
            var dictionary = XamlReader.Parse(ReadLayout("Theme.xaml")) as ResourceDictionary;
            if (dictionary != null) menu.Resources.MergedDictionaries.Add(dictionary);
        }

        /// <summary>Writes the palette onto a context menu, which sits outside the panel's resource tree and inherits none of it.</summary>
        public static void ApplyMenuTheme(ContextMenu menu, string palette)
        {
            foreach (KeyValuePair<string, string> entry in AmTheme.Palette(palette))
            {
                try
                {
                    Color color = (Color)ColorConverter.ConvertFromString(entry.Value);
                    if (entry.Key.EndsWith("Color", StringComparison.Ordinal)) menu.Resources[entry.Key] = color;
                    else menu.Resources[entry.Key] = new SolidColorBrush(color);
                }
                catch (Exception)
                {
                }
            }
        }
    }

    internal static class AmUi
    {
        /// <summary>Owned windows float above Revit instead of slipping behind it.</summary>
        public static void Own(Window window, Window owner)
        {
            if (owner != null)
            {
                try { window.Owner = owner; return; } catch (Exception) { }
            }
            try
            {
                UIApplication app = AmRibbon.UiApp;
                if (app != null) new WindowInteropHelper(window).Owner = app.MainWindowHandle;
            }
            catch (Exception err)
            {
                AmCore.LogException("own", err);
            }
        }

        /// <summary>A drawn stand-in for a button with no icon: a Border and a TextBlock, so it can never be an empty font box.</summary>
        public static FrameworkElement InitialGlyph(string text, double size, Brush background, Brush foreground)
        {
            string letter = (text ?? "").Trim();
            letter = letter.Length > 0 ? letter.Substring(0, 1).ToUpperInvariant() : "?";
            var border = new Border
            {
                Width = size,
                Height = size,
                CornerRadius = new CornerRadius(3),
                Background = background,
            };
            border.Child = new TextBlock
            {
                Text = letter,
                Foreground = foreground,
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = Math.Max(9, size * 0.5),
                FontWeight = FontWeights.SemiBold,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
            };
            return border;
        }

        public static string RevitVersion()
        {
            try
            {
                UIApplication app = AmRibbon.UiApp;
                if (app != null) return app.Application.VersionNumber;
            }
            catch (Exception)
            {
            }
            return "";
        }

        /// <summary>Working area of the screen the window is on, in WPF units, or null.</summary>
        public static double[] WorkArea(Window window)
        {
            try
            {
                System.Windows.Forms.Screen screen = System.Windows.Forms.Screen.FromHandle(new WindowInteropHelper(window).Handle);
                System.Drawing.Rectangle area = screen.WorkingArea;
                double sx, sy;
                DipScale(window, out sx, out sy);
                return new[] { area.Left / sx, area.Top / sy, area.Width / sx, area.Height / sy };
            }
            catch (Exception err)
            {
                AmCore.LogException("work_area", err);
                return null;
            }
        }

        public static void DipScale(Window window, out double x, out double y)
        {
            x = 1.0; y = 1.0;
            try
            {
                PresentationSource source = PresentationSource.FromVisual(window);
                if (source != null && source.CompositionTarget != null)
                {
                    Matrix m = source.CompositionTarget.TransformToDevice;
                    if (m.M11 > 0 && m.M22 > 0) { x = m.M11; y = m.M22; }
                }
            }
            catch (Exception)
            {
            }
        }
    }
}
