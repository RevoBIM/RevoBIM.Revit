using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.FamilyThumbnail;

using Button = System.Windows.Controls.Button;
using Panel = System.Windows.Controls.Panel;
using Color = System.Windows.Media.Color;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.FamilyThumbnail
{
    /// <summary>Loads the pyRevit XAML layouts, unchanged, from the embedded copies in UI\FamilyThumbnail\Layouts.</summary>
    internal static class FtXaml
    {
        private const string LayoutPrefix = "RevoBIM.UI.FamilyThumbnail.Layouts.";
        private const string IconName = "RevoBIM.Resources.FamilyThumbnailHeader.icon.png";

        public static string ReadLayout(string file)
        {
            using (Stream stream = typeof(FtXaml).Assembly.GetManifestResourceStream(LayoutPrefix + file))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + file + " was not found");
                using (var reader = new StreamReader(stream, System.Text.Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        /// <summary>
        /// Parses a layout, then merges Theme.xaml in behind it. Theme.xaml is merged AFTER the layout has been parsed, which is
        /// why a layout may only ever ask for brushes and styles with DynamicResource.
        /// </summary>
        public static Window LoadWindow(string file)
        {
            var window = XamlReader.Parse(ReadLayout(file)) as Window;
            if (window == null) throw new InvalidCastException(file + " is not a Window");
            var theme = XamlReader.Parse(ReadLayout("Theme.xaml")) as ResourceDictionary;
            if (theme == null) throw new InvalidCastException("Theme.xaml did not parse as a ResourceDictionary");
            window.Resources.MergedDictionaries.Add(theme);
            return window;
        }

        /// <summary>Decorative: any failure is swallowed, cosmetics can never take a tool down.</summary>
        public static void LoadIcon(Image image)
        {
            try
            {
                if (image == null) return;
                using (Stream stream = typeof(FtXaml).Assembly.GetManifestResourceStream(IconName))
                {
                    if (stream == null) return;
                    var bitmap = new BitmapImage();
                    bitmap.BeginInit();
                    bitmap.StreamSource = stream;
                    bitmap.CacheOption = BitmapCacheOption.OnLoad;
                    bitmap.EndInit();
                    bitmap.Freeze();
                    image.Source = bitmap;
                }
            }
            catch (Exception err)
            {
                FtCore.Swallowed("chrome.icon", err);
            }
        }
    }

    internal static class FtUi
    {
        public static Brush BrushFromHex(string hex)
        {
            return new SolidColorBrush(ColorFromHex(hex));
        }

        public static Color ColorFromHex(string hex)
        {
            int r, g, b;
            if (!FtLogic.ParseHex(hex, out r, out g, out b)) { r = g = b = 255; }
            return Color.FromRgb((byte)r, (byte)g, (byte)b);
        }

        /// <summary>Follows Revit's canvas theme (Revit 2023: the UI theme), then the canvas background colour.</summary>
        public static bool RevitIsDark(UIApplication uiapp)
        {
            try
            {
                return RevitCompat.CanvasTheme() == UITheme.Dark;
            }
            catch (Exception err)
            {
                FtCore.Swallowed("revit_is_dark.canvas", err);
            }
            try
            {
                Autodesk.Revit.DB.Color color = uiapp.Application.BackgroundColor;
                if (color != null) return 0.299 * color.Red + 0.587 * color.Green + 0.114 * color.Blue < 128;
            }
            catch (Exception err)
            {
                FtCore.Swallowed("revit_is_dark.background", err);
            }
            return true;
        }

        /// <summary>Opens Explorer with the saved file selected (or just the folder).</summary>
        public static void OpenFolder(string path)
        {
            if (File.Exists(path)) Process.Start("explorer.exe", "/select,\"" + path + "\"");
            else Process.Start("explorer.exe", "\"" + path + "\"");
        }
    }

    /// <summary>Shared window chrome: Theme.xaml, the palette, the theme chip, the version, the shrink drawer and the close button.</summary>
    internal abstract class FtChromeWindow
    {
        public static readonly Dictionary<string, string> ThemeLabels = new Dictionary<string, string>
            { { "auto", "Auto" }, { "dark", "Dark" }, { "light", "Light" } };

        private static readonly Dictionary<string, string> NextMode = new Dictionary<string, string>
            { { "auto", "dark" }, { "dark", "light" }, { "light", "auto" } };

        protected readonly UIApplication Uiapp;
        public readonly Window Win;
        protected string Mode;
        protected readonly Border Header;
        protected readonly Panel RootPanel;
        protected readonly TextBlock ThemeText;
        protected readonly Button ShrinkButton;
        protected readonly FtDrawer Drawer;
        protected readonly Image HeaderIcon;

        protected FtChromeWindow(UIApplication uiapp, string layout, string mode, bool armEgg)
        {
            Uiapp = uiapp;
            Mode = ThemeLabels.ContainsKey(mode ?? "") ? mode : "auto";
            Win = FtXaml.LoadWindow(layout);
            Header = (Border)Find("Header");
            RootPanel = (Panel)Find("Root");
            ThemeText = (TextBlock)Find("tbTheme");
            ShrinkButton = (Button)Find("btnShrink");
            ((TextBlock)Find("tbVersion")).Text = "v" + FtCore.Version;
            HeaderIcon = (Image)Find("HeaderIcon");
            FtXaml.LoadIcon(HeaderIcon);

            Drawer = new FtDrawer(Win, Header, RootPanel, ShrinkButton);
            ((Button)Find("btnCloseX")).Click += (s, a) => RequestClose();
            ((Button)Find("btnTheme")).Click += OnTheme;
            Header.MouseLeftButtonDown += (s, a) =>
            {
                if (Drawer.OnHeaderDown(a)) return;
                try
                {
                    Win.DragMove();
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("chrome.dragmove", err);
                }
            };
            Win.Activated += (s, a) =>
            {
                if (Mode == "auto") ApplyTheme(); // Revit's theme may have changed while this was open
            };
            // three slow clicks on the logo open the RevoBIM Arcade; the logo only, never the whole window
            if (armEgg) EggHook.Attach(Win, () => IsDark() ? "dark" : "light", HeaderIcon);
            ApplyTheme();
        }

        public object Find(string name)
        {
            object element = Win.FindName(name);
            if (element == null) throw new InvalidOperationException("Layout has no element named " + name);
            return element;
        }

        protected T Get<T>(string name) where T : class
        {
            return (T)Find(name);
        }

        protected bool IsDark()
        {
            if (Mode == "dark") return true;
            if (Mode == "light") return false;
            return FtUi.RevitIsDark(Uiapp);
        }

        protected void ApplyTheme()
        {
            Dictionary<string, string> palette = FtCore.Palettes[IsDark() ? "dark" : "light"];
            foreach (KeyValuePair<string, string> pair in palette) Win.Resources[pair.Key] = FtUi.BrushFromHex(pair.Value);
            ThemeText.Text = ThemeLabels[Mode];
        }

        private void OnTheme(object sender, RoutedEventArgs args)
        {
            Mode = NextMode[Mode];
            ApplyTheme();
            try
            {
                FtSettings.SaveThemeMode(Mode);
            }
            catch (Exception err)
            {
                FtCore.Swallowed("chrome.save_theme", err);
            }
        }

        public virtual void RequestClose()
        {
            Win.Close();
        }

        public void Show(Window owner)
        {
            if (owner != null) Win.Owner = owner;
            else
            {
                try
                {
                    new WindowInteropHelper(Win).Owner = Uiapp.MainWindowHandle;
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("chrome.owner", err);
                }
            }
            Win.ShowDialog();
        }
    }

    /// <summary>The small result / info prompt.</summary>
    internal sealed class FtPromptWindow : FtChromeWindow
    {
        private readonly string path;

        private FtPromptWindow(UIApplication uiapp, string mode, string heading, string message, string path, IList<string> notes, bool canOpen)
            : base(uiapp, "PromptWindow.xaml", mode, false)
        {
            this.path = path;
            Get<TextBlock>("tbHeading").Text = heading;
            Get<TextBlock>("tbMessage").Text = message;
            Get<TextBlock>("tbPath").Text = path ?? "";
            Get<TextBlock>("tbNotes").Text = notes == null ? "" : string.Join("; ", notes);
            var open = Get<Button>("btnOpen");
            if (!(canOpen && !string.IsNullOrEmpty(path))) open.Visibility = Visibility.Collapsed;
            open.Click += (s, a) =>
            {
                try
                {
                    FtUi.OpenFolder(this.path);
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("prompt.open_folder", err);
                }
                Win.Close();
            };
            Get<Button>("btnClose").Click += (s, a) => Win.Close();
        }

        public static void ShowMessage(UIApplication uiapp, string heading, string message, string path, IList<string> notes, bool canOpen, Window owner)
        {
            string mode = "auto";
            try
            {
                mode = FtSettings.Load().ThemeMode;
            }
            catch (Exception err)
            {
                FtCore.Swallowed("prompt.theme", err);
            }
            try
            {
                new FtPromptWindow(uiapp, mode, heading, message, path, notes, canOpen).Show(owner);
            }
            catch (Exception err)
            {
                FtCore.Log("prompt: themed window failed (" + err.Message + "), used a TaskDialog");
                new TaskDialog("RevoBIM Family Thumbnail")
                {
                    MainInstruction = heading,
                    MainContent = message + (path == null ? "" : "\n\n" + path)
                                  + (notes == null || notes.Count == 0 ? "" : "\n\n" + string.Join("; ", notes)),
                }.Show();
            }
        }
    }
}
