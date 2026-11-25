using System;
using System.Collections.Generic;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.MatchOffset;

using Button = System.Windows.Controls.Button;
using Grid = System.Windows.Controls.Grid;

namespace RevoBIM.UI.MatchOffset
{
    /// <summary>
    /// The dark and light palettes. The light palette is not the dark one inverted: the accents are darkened, because
    /// the dark palette's blue, orange and green are chosen to sit on near-black and wash out on white.
    /// </summary>
    internal static class MoTheme
    {
        public const string Auto = "auto", Dark = "dark", Light = "light";

        private static readonly Dictionary<string, string> DarkPalette = new Dictionary<string, string>
        {
            { "WindowBrush", "#232326" }, { "CardBrush", "#2B2B2E" }, { "FieldBrush", "#1C1C1F" }, { "BarBrush", "#1C1C1F" },
            { "EdgeBrush", "#3E3E42" }, { "TextBrush", "#E4E4E4" }, { "MutedBrush", "#9A9A9E" }, { "BlueBrush", "#4FA3E3" },
            { "OrangeBrush", "#E8912D" }, { "GreenBrush", "#3FA75A" }, { "GreenHoverBrush", "#4EC06D" }, { "RedBrush", "#D9534F" },
            { "SelectBrush", "#2B5473" }, { "HoverBrush", "#33333A" }, { "DisabledBrush", "#55555C" },
        };

        private static readonly Dictionary<string, string> LightPalette = new Dictionary<string, string>
        {
            { "WindowBrush", "#F2F2F4" }, { "CardBrush", "#FFFFFF" }, { "FieldBrush", "#FFFFFF" }, { "BarBrush", "#E6E6EA" },
            { "EdgeBrush", "#C6C6CC" }, { "TextBrush", "#1E1E20" }, { "MutedBrush", "#63636A" }, { "BlueBrush", "#1B72BE" },
            { "OrangeBrush", "#B96A12" }, { "GreenBrush", "#2E8546" }, { "GreenHoverBrush", "#3A9E56" }, { "RedBrush", "#B23430" },
            { "SelectBrush", "#BFD8EE" }, { "HoverBrush", "#E4E4EA" }, { "DisabledBrush", "#A8A8B0" },
        };

        public static string Label(string mode)
        {
            switch ((mode ?? "").ToLowerInvariant())
            {
                case Dark: return "Dark";
                case Light: return "Light";
                default: return "Auto";
            }
        }

        /// <summary>The chip cycles Auto, then Dark, then Light, then back to Auto.</summary>
        public static string Next(string current)
        {
            switch ((current ?? "").Trim().ToLowerInvariant())
            {
                case Auto: return Dark;
                case Dark: return Light;
                case Light: return Auto;
                default: return Dark;
            }
        }

        /// <summary>Whichever way Revit's own canvas is set, dark or light.</summary>
        public static string RevitTheme()
        {
            try
            {
                return RevoBIM.Helpers.RevitCompat.CanvasTheme() == UITheme.Dark ? Dark : Light;
            }
            catch (Exception)
            {
            }
            try
            {
                return UIThemeManager.CurrentTheme == UITheme.Dark ? Dark : Light;
            }
            catch (Exception)
            {
                return Dark;
            }
        }

        /// <summary>The palette name a setting of auto, dark or light actually means.</summary>
        public static string Resolve(string mode)
        {
            string chosen = (mode ?? "").Trim().ToLowerInvariant();
            if (chosen == Light) return Light;
            if (chosen == Dark) return Dark;
            return RevitTheme();
        }

        /// <summary>
        /// Write the palette straight onto window.Resources, which sits in front of a merged dictionary in WPF's lookup
        /// order, so the palette can be swapped on an open window with no reload and no loss of state.
        /// </summary>
        public static string Apply(Window window, string mode)
        {
            string resolved = Resolve(mode);
            foreach (KeyValuePair<string, string> entry in resolved == Light ? LightPalette : DarkPalette)
            {
                try
                {
                    window.Resources[entry.Key] = new SolidColorBrush((Color)ColorConverter.ConvertFromString(entry.Value));
                }
                catch (Exception)
                {
                }
            }
            return resolved;
        }
    }

    /// <summary>XAML loading, window chrome and the easter egg. Port of mo_ui.py.</summary>
    internal static class MoUi
    {
        private const string LayoutPrefix = "RevoBIM.UI.MatchOffset.Layouts.";

        private static string ReadLayout(string file)
        {
            using (Stream stream = typeof(MoUi).Assembly.GetManifestResourceStream(LayoutPrefix + file))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + file + " was not found");
                using (var reader = new StreamReader(stream, System.Text.Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        /// <summary>
        /// Parse a layout, merge Theme.xaml into it afterwards, apply the palette. Theme.xaml is merged after the layout
        /// has been parsed, which is why the layouts may only use DynamicResource.
        /// </summary>
        public static Window LoadWindow(string file, string themeMode)
        {
            var window = XamlReader.Parse(ReadLayout(file)) as Window;
            if (window == null) throw new InvalidCastException(file + " is not a Window");
            try
            {
                var dictionary = XamlReader.Parse(ReadLayout("Theme.xaml")) as ResourceDictionary;
                if (dictionary != null) window.Resources.MergedDictionaries.Add(dictionary);
            }
            catch (Exception err)
            {
                MoCore.Log("Theme.xaml would not merge: " + err.Message);
            }
            MoTheme.Apply(window, themeMode);
            try
            {
                window.WindowStartupLocation = WindowStartupLocation.CenterScreen;
            }
            catch (Exception)
            {
            }
            return window;
        }

        public static T Find<T>(Window window, string name) where T : class
        {
            return window.FindName(name) as T;
        }

        /// <summary>Anything decorative is in a try/catch: cosmetics never take a tool down.</summary>
        private static BitmapImage LoadLogo()
        {
            foreach (string name in new[] { "RevoBIM.Resources.MatchOffset.logo.png", "RevoBIM.Resources.MatchOffset.icon.png" })
            {
                try
                {
                    using (Stream stream = typeof(MoUi).Assembly.GetManifestResourceStream(name))
                    {
                        if (stream == null) continue;
                        var bitmap = new BitmapImage();
                        bitmap.BeginInit();
                        bitmap.StreamSource = stream;
                        bitmap.CacheOption = BitmapCacheOption.OnLoad;
                        bitmap.EndInit();
                        bitmap.Freeze();
                        return bitmap;
                    }
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        private static void SetIcon(Window window)
        {
            try
            {
                BitmapImage source = LoadLogo();
                if (source == null) return;
                var image = window.FindName("LogoImage") as Image;
                if (image != null) image.Source = source;
                try
                {
                    window.Icon = source;
                }
                catch (Exception)
                {
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Drag by the header, close, and the Auto/Dark/Light chip. The logo easter egg is armed only on a tool's main
        /// window (armEgg); secondary dialogs do not get it.
        /// </summary>
        public static void WireHeader(Window window, Dictionary<string, string> settings, Action<string> onThemeChanged = null, bool armEgg = false)
        {
            var header = window.FindName("HeaderBar") as UIElement;
            if (header != null)
            {
                header.MouseLeftButtonDown += (s, a) =>
                {
                    try
                    {
                        if (a.ButtonState == MouseButtonState.Pressed) window.DragMove();
                    }
                    catch (Exception)
                    {
                    }
                };
            }

            var close = window.FindName("CloseButton") as Button;
            if (close != null)
            {
                close.Click += (s, a) =>
                {
                    try
                    {
                        window.Close();
                    }
                    catch (Exception)
                    {
                    }
                };
            }

            var chip = window.FindName("ThemeChip") as Button;
            if (chip != null)
            {
                chip.Content = MoTheme.Label(MoCore.Get(settings, "theme"));
                chip.Click += (s, a) =>
                {
                    string mode = MoTheme.Next(MoCore.Get(settings, "theme"));
                    settings["theme"] = mode;
                    chip.Content = MoTheme.Label(mode);
                    MoTheme.Apply(window, mode);
                    if (onThemeChanged != null)
                    {
                        try
                        {
                            onThemeChanged(mode);
                        }
                        catch (Exception)
                        {
                        }
                    }
                };
            }

            var version = window.FindName("VersionLabel") as TextBlock;
            if (version != null) version.Text = "v" + MoCore.Version;

            SetIcon(window);

            if (armEgg)
            {
                try
                {
                    UIElement logo = window.FindName("LogoArea") as UIElement;
                    EggHook.Attach(window, () => MoTheme.Resolve(MoCore.Get(settings, "theme")), logo);
                }
                catch (Exception)
                {
                }
            }
        }

        private static readonly object[][] GripSpecs =
        {
            new object[] { "n", HorizontalAlignment.Stretch, VerticalAlignment.Top, Cursors.SizeNS },
            new object[] { "s", HorizontalAlignment.Stretch, VerticalAlignment.Bottom, Cursors.SizeNS },
            new object[] { "w", HorizontalAlignment.Left, VerticalAlignment.Stretch, Cursors.SizeWE },
            new object[] { "e", HorizontalAlignment.Right, VerticalAlignment.Stretch, Cursors.SizeWE },
            new object[] { "nw", HorizontalAlignment.Left, VerticalAlignment.Top, Cursors.SizeNWSE },
            new object[] { "se", HorizontalAlignment.Right, VerticalAlignment.Bottom, Cursors.SizeNWSE },
            new object[] { "ne", HorizontalAlignment.Right, VerticalAlignment.Top, Cursors.SizeNESW },
            new object[] { "sw", HorizontalAlignment.Left, VerticalAlignment.Bottom, Cursors.SizeNESW },
        };

        private const double GripPx = 6.0;

        /// <summary>
        /// Eight thumbs round the edge, because WPF cannot resize a borderless AllowsTransparency window: nothing in its
        /// transparent frame is hit testable. The overlay has no Background of its own, so everything underneath stays clickable.
        /// </summary>
        public static void AddResizeGrips(Window window, string hostName = "RootGrid")
        {
            var host = window.FindName(hostName) as Panel;
            if (host == null) return;
            var overlay = new Grid();
            Grid.SetRowSpan(overlay, 99);
            Grid.SetColumnSpan(overlay, 99);
            foreach (object[] spec in GripSpecs)
            {
                string name = (string)spec[0];
                var halign = (HorizontalAlignment)spec[1];
                var valign = (VerticalAlignment)spec[2];
                var thumb = new Thumb
                {
                    HorizontalAlignment = halign,
                    VerticalAlignment = valign,
                    Opacity = 0.0,
                    Cursor = (Cursor)spec[3],
                };
                if (halign != HorizontalAlignment.Stretch) thumb.Width = GripPx;
                if (valign != VerticalAlignment.Stretch) thumb.Height = GripPx;
                thumb.DragDelta += (s, a) => Resize(window, name, a.HorizontalChange, a.VerticalChange);
                overlay.Children.Add(thumb);
            }
            host.Children.Add(overlay);
        }

        private static void Resize(Window window, string name, double dx, double dy)
        {
            try
            {
                if (name.Contains("w"))
                {
                    double width = window.Width - dx;
                    if (width >= window.MinWidth)
                    {
                        window.Left += dx;
                        window.Width = width;
                    }
                }
                if (name.Contains("e"))
                {
                    double width = window.Width + dx;
                    if (width >= window.MinWidth) window.Width = width;
                }
                if (name.Contains("n"))
                {
                    double height = window.Height - dy;
                    if (height >= window.MinHeight)
                    {
                        window.Top += dy;
                        window.Height = height;
                    }
                }
                if (name.Contains("s"))
                {
                    double height = window.Height + dy;
                    if (height >= window.MinHeight) window.Height = height;
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Owned windows float above Revit instead of slipping behind it.</summary>
        public static void OwnToRevit(Window window, UIApplication uiapp)
        {
            try
            {
                if (uiapp != null) new WindowInteropHelper(window).Owner = uiapp.MainWindowHandle;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// A themed message or yes/no/cancel. Returns true for the primary button, false for the alternative, and null for
        /// cancel or for the window being closed. A window that will not open falls back to Revit's own dialog rather than
        /// quietly answering no.
        /// </summary>
        public static bool? Message(string title, string body, string themeMode, Window owner, string okText = "OK", string altText = "",
                                    string cancelText = "")
        {
            Window window;
            try
            {
                window = LoadWindow("MatchOffsetMessage.xaml", themeMode);
            }
            catch (Exception err)
            {
                MoCore.Log("Message window would not load: " + err.Message);
                return FallbackDialog(title, body, altText.Length > 0 || cancelText.Length > 0);
            }

            bool? answer = null;
            try
            {
                ((TextBlock)window.FindName("MessageTitle")).Text = title;
                ((TextBlock)window.FindName("MessageBody")).Text = body;
                WireHeader(window, new Dictionary<string, string> { { "theme", themeMode } });

                var primary = (Button)window.FindName("PrimaryButton");
                primary.Content = okText;
                primary.Click += (s, a) =>
                {
                    answer = true;
                    window.Close();
                };

                var alt = (Button)window.FindName("AltButton");
                if (altText.Length > 0)
                {
                    alt.Content = altText;
                    alt.Visibility = Visibility.Visible;
                    alt.Click += (s, a) =>
                    {
                        answer = false;
                        window.Close();
                    };
                }
                else alt.Visibility = Visibility.Collapsed;

                var cancel = (Button)window.FindName("CancelButton");
                if (cancelText.Length > 0)
                {
                    cancel.Content = cancelText;
                    cancel.Visibility = Visibility.Visible;
                    cancel.Click += (s, a) =>
                    {
                        answer = null;
                        window.Close();
                    };
                }
                else cancel.Visibility = Visibility.Collapsed;

                if (owner != null)
                {
                    try
                    {
                        window.Owner = owner;
                    }
                    catch (Exception)
                    {
                    }
                }
                window.ShowDialog();
            }
            catch (Exception err)
            {
                MoCore.Log("Message window failed: " + err.Message);
                return FallbackDialog(title, body, altText.Length > 0 || cancelText.Length > 0);
            }
            return answer;
        }

        private static bool? FallbackDialog(string title, string body, bool ask)
        {
            try
            {
                var dialog = new TaskDialog(title) { MainInstruction = title, MainContent = body };
                if (ask)
                {
                    dialog.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No;
                    return dialog.Show() == TaskDialogResult.Yes;
                }
                dialog.CommonButtons = TaskDialogCommonButtons.Close;
                dialog.Show();
                return true;
            }
            catch (Exception)
            {
                return null;
            }
        }
    }
}
