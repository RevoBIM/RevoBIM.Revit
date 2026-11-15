using System;
using System.Reflection;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using RevoBIM.Tools.LegendCreator;
using static RevoBIM.Tools.LegendCreator.LgcCore;

namespace RevoBIM.UI.LegendCreator
{
    /// <summary>
    /// Legend Creator - palettes and window plumbing. Follows Revit's canvas
    /// theme and paints a palette onto an open window. Port of lgc_theme.py.
    /// </summary>
    public static class LgcTheme
    {
        /// <summary>The Revit main window, set by the command, owner of every tool window.</summary>
        public static IntPtr OwnerHandle = IntPtr.Zero;

        /// <summary>UIThemeManager's value, read by name so a missing member falls back rather than throws.</summary>
        public static object ThemeManagerValue(string property)
        {
            Type manager = typeof(Autodesk.Revit.UI.UIApplication).Assembly.GetType("Autodesk.Revit.UI.UIThemeManager");
            PropertyInfo info = manager?.GetProperty(property, BindingFlags.Public | BindingFlags.Static);
            if (info == null) throw new MissingMemberException("UIThemeManager", property);
            return info.GetValue(null);
        }

        /// <summary>Revit's own canvas theme as 'dark' or 'light', or null if unknown. The canvas wins.</summary>
        public static string RevitTheme()
        {
            foreach (string attribute in new[] { "CurrentCanvasTheme", "CurrentTheme" })
            {
                object value;
                try
                {
                    value = ThemeManagerValue(attribute);
                }
                catch (Exception err)
                {
                    Swallowed(err);
                    continue;
                }
                Log("theme: UIThemeManager." + attribute + " = " + value);
                string found = LgcLogic.ReadThemeText(value);
                if (found != null) return found;
            }
            return null;
        }

        /// <summary>Turn a saved mode into the palette actually used.</summary>
        public static string ResolveTheme(string mode)
        {
            return LgcLogic.PickTheme(mode, mode == "dark" || mode == "light" ? null : RevitTheme());
        }

        /// <summary>
        /// Write a palette straight onto window.Resources. Every colour in the
        /// layouts is a DynamicResource, and window.Resources sits in front of
        /// the merged theme, so this repaints an open window with no reload.
        /// </summary>
        public static System.Collections.Generic.Dictionary<string, string> ApplyPalette(Window window, string name)
        {
            if (!LgcLogic.Palettes.TryGetValue(name ?? "", out var palette)) palette = LgcLogic.Palettes["dark"];
            foreach (var pair in palette)
            {
                try
                {
                    window.Resources[pair.Key] = Brush(pair.Value);
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
            return palette;
        }

        /// <summary>A WPF brush from '#RRGGBB'. Never throws - a bad colour falls back to grey.</summary>
        public static SolidColorBrush Brush(string hex)
        {
            try
            {
                string text = (hex ?? "").TrimStart('#');
                if (text.Length != 6) throw new FormatException("expected six hex digits");
                return new SolidColorBrush(Color.FromRgb(
                    Convert.ToByte(text.Substring(0, 2), 16),
                    Convert.ToByte(text.Substring(2, 2), 16),
                    Convert.ToByte(text.Substring(4, 2), 16)));
            }
            catch (Exception)
            {
                return new SolidColorBrush(Color.FromRgb(154, 154, 158));
            }
        }

        /// <summary>Show a tool window modally over Revit.</summary>
        public static bool? ShowOverRevit(Window window)
        {
            try
            {
                if (OwnerHandle != IntPtr.Zero) new WindowInteropHelper(window).Owner = OwnerHandle;
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return window.ShowDialog();
        }
    }
}
