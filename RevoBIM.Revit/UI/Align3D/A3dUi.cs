using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
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
using RevoBIM.Tools.Align3D;

using Grid = System.Windows.Controls.Grid;
using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.Align3D
{
    /// <summary>Palettes and which one Revit is showing (port of theme.py). Written onto window.Resources, in front of the merged Theme.xaml.</summary>
    internal static class A3dTheme
    {
        private static readonly Dictionary<string, string> Dark = new Dictionary<string, string>
        {
            { "BgWindow", "#232326" }, { "BgCard", "#2B2B2E" }, { "BgField", "#1C1C1F" }, { "BgBar", "#1C1C1F" }, { "Edge", "#3E3E42" },
            { "EdgeWindow", "#4A4A50" }, { "Text", "#E4E4E4" }, { "TextMuted", "#9A9A9E" }, { "Blue", "#4FA3E3" }, { "Orange", "#E8912D" },
            { "Green", "#3FA75A" }, { "GreenHover", "#4EC06D" }, { "Red", "#D9534F" }, { "Selection", "#2B5473" }, { "Hover", "#38383D" },
            { "OnAccent", "#FFFFFF" }, { "RowOk", "#1F3326" }, { "RowWarn", "#3A2C1A" }, { "RowBad", "#3A2020" }, { "RowQuiet", "#29292D" },
        };

        private static readonly Dictionary<string, string> Light = new Dictionary<string, string>
        {
            { "BgWindow", "#F3F3F5" }, { "BgCard", "#FFFFFF" }, { "BgField", "#FAFAFB" }, { "BgBar", "#E4E4E8" }, { "Edge", "#C8C8CE" },
            { "EdgeWindow", "#A9A9B0" }, { "Text", "#1E1E22" }, { "TextMuted", "#5F5F67" }, { "Blue", "#1B72BE" }, { "Orange", "#B96A12" },
            { "Green", "#2E8546" }, { "GreenHover", "#379B53" }, { "Red", "#C0392B" }, { "Selection", "#CFE3F5" }, { "Hover", "#E2E2E8" },
            { "OnAccent", "#FFFFFF" }, { "RowOk", "#E3F2E7" }, { "RowWarn", "#FBEEDC" }, { "RowBad", "#F8E0DE" }, { "RowQuiet", "#ECECF0" },
        };

        public static string RevitTheme()
        {
            try { return RevoBIM.Helpers.RevitCompat.CanvasTheme() == UITheme.Dark ? "dark" : "light"; } catch (Exception) { }
            try { return UIThemeManager.CurrentTheme == UITheme.Dark ? "dark" : "light"; } catch (Exception) { return null; }
        }

        /// <summary>The palette to draw: a pinned choice, else Revit's canvas, else dark.</summary>
        public static string Resolve(string mode)
        {
            if (mode == "dark" || mode == "light") return mode;
            return RevitTheme() ?? "dark";
        }

        public static string ChipLabel(string mode, string resolved)
        {
            if (mode == "dark" || mode == "light") return resolved == "dark" ? "Dark" : "Light";
            return "Auto";
        }

        public static string ChipTooltip(string mode, string resolved)
        {
            if (mode == "dark" || mode == "light") return ChipLabel(mode, resolved) + " theme, pinned. Click to change.";
            return "Following Revit's canvas - " + resolved + " at the moment. Click to pin dark, then light, then back to following.";
        }

        public static void Apply(Window window, string name)
        {
            foreach (KeyValuePair<string, string> entry in name == "light" ? Light : Dark)
            {
                try
                {
                    var brush = new SolidColorBrush((Color)ColorConverter.ConvertFromString(entry.Value));
                    brush.Freeze();
                    window.Resources[entry.Key] = brush;
                }
                catch (Exception)
                {
                }
            }
        }
    }

    /// <summary>The house chrome: drag, close, theme chip, version, logo, full screen and resize grips.</summary>
    internal sealed class A3dChrome
    {
        private readonly Window window;
        private readonly Dictionary<string, string> settings;
        private readonly bool allowFull;
        private readonly Action<string> onTheme;
        private bool full;
        private double[] savedBounds;

        public string Mode = "dark";

        public A3dChrome(Window window, Dictionary<string, string> settings, bool allowFull, Action<string> onTheme, bool egg)
        {
            this.window = window;
            this.settings = settings;
            this.allowFull = allowFull;
            this.onTheme = onTheme;
            ApplyTheme();
            Wire(egg);
        }

        private T Find<T>(string name) where T : class { return window.FindName(name) as T; }

        public void ApplyTheme()
        {
            string choice = A3dSettings.Get(settings, "theme");
            Mode = A3dTheme.Resolve(choice);
            A3dTheme.Apply(window, Mode);
            var label = Find<TextBlock>("ThemeLabel");
            if (label != null) label.Text = A3dTheme.ChipLabel(choice, Mode);
            var chip = Find<Button>("ThemeChip");
            if (chip != null) chip.ToolTip = A3dTheme.ChipTooltip(choice, Mode);
            if (onTheme != null) onTheme(Mode);
        }

        /// <summary>Repaints after the theme was changed elsewhere (the settings window) without saving it again.</summary>
        public void ReloadTheme(string choice)
        {
            settings["theme"] = choice;
            ApplyTheme();
        }

        public void SetTheme(string choice)
        {
            settings["theme"] = choice;
            A3dSettings.SaveTheme(choice);
            ApplyTheme();
        }

        private void Wire(bool egg)
        {
            var version = Find<TextBlock>("VersionText");
            if (version != null) version.Text = "v" + A3dSettings.Version;
            var logo = Find<Image>("Logo");
            if (logo != null) A3dXaml.LoadLogo(logo);
            var chip = Find<Button>("ThemeChip");
            if (chip != null) chip.Click += (s, a) => Guard(() => SetTheme(A3dSettings.NextTheme(A3dSettings.Get(settings, "theme"))));
            var close = Find<Button>("CloseBtn");
            if (close != null) close.Click += (s, a) => Guard(window.Close);
            var header = Find<Border>("Header");
            if (header != null) header.MouseLeftButtonDown += (s, a) => Guard(() => OnHeaderDown(a));
            var fullBtn = Find<Button>("FullBtn");
            if (fullBtn != null) fullBtn.Click += (s, a) => Guard(ToggleFull);
            window.PreviewKeyDown += (s, a) => Guard(() => OnKey(a));
            WireGrips();
            if (egg && logo != null)
            {
                try { EggHook.Attach(window, () => Mode, logo); } catch (Exception) { }
            }
        }

        private static void Guard(Action fn)
        {
            try
            {
                fn();
            }
            catch (Exception err)
            {
                try
                {
                    Directory.CreateDirectory(A3dSettings.DataDir());
                    File.WriteAllText(A3dSettings.ErrorPath(), err.ToString());
                }
                catch (Exception)
                {
                }
            }
        }

        private void OnHeaderDown(MouseButtonEventArgs args)
        {
            if (args.ClickCount == 2 && allowFull)
            {
                ToggleFull();
                return;
            }
            if (full) LeaveFull();
            try { window.DragMove(); } catch (Exception) { }
        }

        private void OnKey(KeyEventArgs args)
        {
            if (args.Key == Key.Escape)
            {
                args.Handled = true;
                if (full) LeaveFull(); else window.Close();
            }
            else if (args.Key == Key.F11 && allowFull)
            {
                args.Handled = true;
                ToggleFull();
            }
        }

        private double[] WorkArea()
        {
            try
            {
                System.Drawing.Rectangle area = System.Windows.Forms.Screen.FromHandle(new WindowInteropHelper(window).Handle).WorkingArea;
                Matrix m = PresentationSource.FromVisual(window).CompositionTarget.TransformToDevice;
                double sx = m.M11 != 0 ? m.M11 : 1.0, sy = m.M22 != 0 ? m.M22 : 1.0;
                return new[] { area.X / sx, area.Y / sy, area.Width / sx, area.Height / sy };
            }
            catch (Exception)
            {
                Rect area = SystemParameters.WorkArea;
                return new[] { area.X, area.Y, area.Width, area.Height };
            }
        }

        private void ToggleFull()
        {
            if (full)
            {
                LeaveFull();
                return;
            }
            savedBounds = new[] { window.Left, window.Top, window.Width, window.Height };
            double[] a = WorkArea();
            window.Left = a[0];
            window.Top = a[1];
            window.Width = a[2];
            window.Height = a[3];
            full = true;
        }

        private void LeaveFull()
        {
            if (full && savedBounds != null)
            {
                window.Left = savedBounds[0];
                window.Top = savedBounds[1];
                window.Width = savedBounds[2];
                window.Height = savedBounds[3];
            }
            full = false;
        }

        private void WireGrips()
        {
            // name -> left, top, right, bottom
            var sides = new Dictionary<string, int[]>
            {
                { "GripL", new[] { 1, 0, 0, 0 } }, { "GripR", new[] { 0, 0, 1, 0 } }, { "GripT", new[] { 0, 1, 0, 0 } },
                { "GripB", new[] { 0, 0, 0, 1 } }, { "GripTL", new[] { 1, 1, 0, 0 } }, { "GripTR", new[] { 0, 1, 1, 0 } },
                { "GripBL", new[] { 1, 0, 0, 1 } }, { "GripBR", new[] { 0, 0, 1, 1 } },
            };
            foreach (KeyValuePair<string, int[]> pair in sides)
            {
                var grip = Find<Thumb>(pair.Key);
                if (grip == null) continue;
                int[] e = pair.Value;
                grip.DragDelta += (s, a) => Guard(() =>
                {
                    full = false;
                    double dx = a.HorizontalChange, dy = a.VerticalChange;
                    if (e[2] == 1) window.Width = Math.Max(window.MinWidth, window.Width + dx);
                    if (e[3] == 1) window.Height = Math.Max(window.MinHeight, window.Height + dy);
                    if (e[0] == 1)
                    {
                        double width = Math.Max(window.MinWidth, window.Width - dx);
                        window.Left = window.Left + (window.Width - width);
                        window.Width = width;
                    }
                    if (e[1] == 1)
                    {
                        double height = Math.Max(window.MinHeight, window.Height - dy);
                        window.Top = window.Top + (window.Height - height);
                        window.Height = height;
                    }
                });
            }
        }
    }

    internal static class A3dXaml
    {
        private const string LayoutPrefix = "RevoBIM.UI.Align3D.Layouts.";
        private const string IconName = "RevoBIM.Resources.Align3D.icon.png";

        private static string ReadLayout(string file)
        {
            using (Stream stream = typeof(A3dXaml).Assembly.GetManifestResourceStream(LayoutPrefix + file))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + file + " was not found");
                using (var reader = new StreamReader(stream, System.Text.Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        public static Window Load(string file)
        {
            var window = XamlReader.Parse(ReadLayout(file)) as Window;
            if (window == null) throw new InvalidCastException(file + " is not a Window");
            var theme = XamlReader.Parse(ReadLayout("Theme.xaml")) as ResourceDictionary;
            if (theme != null) window.Resources.MergedDictionaries.Add(theme);
            return window;
        }

        public static void LoadLogo(Image image)
        {
            try
            {
                using (Stream stream = typeof(A3dXaml).Assembly.GetManifestResourceStream(IconName))
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
            catch (Exception)
            {
            }
        }

        public static void OwnToRevit(Window window, UIApplication uiapp)
        {
            try { new WindowInteropHelper(window).Owner = uiapp.MainWindowHandle; } catch (Exception) { }
        }
    }

    /// <summary>The results window and the settings window (port of a3d_ui.py). Both are modal.</summary>
    public static class A3dWindows
    {
        private sealed class Kind
        {
            public string Label, Colour, Tint;
            public Kind(string label, string colour, string tint) { Label = label; Colour = colour; Tint = tint; }
        }

        private static readonly Dictionary<string, Kind> Kinds = new Dictionary<string, Kind>
        {
            { "ok", new Kind("ALIGNED", "Green", "RowOk") },
            { "already", new Kind("ALREADY", "TextMuted", "RowQuiet") },
            { "warn", new Kind("CHECK", "Orange", "RowWarn") },
            { "refused", new Kind("REFUSED", "Red", "RowBad") },
            { "failed", new Kind("FAILED", "Red", "RowBad") },
        };

        // heading, star weight, minimum px
        private static readonly object[][] Columns =
        {
            new object[] { "", 0, 84.0 }, new object[] { "First (align to)", 2, 150.0 }, new object[] { "Moved", 2, 150.0 },
            new object[] { "How", 2, 160.0 }, new object[] { "Distance", 0, 76.0 }, new object[] { "Result", 3, 200.0 },
        };

        private static TextBlock Text(string text, string key = "Text", bool bold = false, bool wrap = true)
        {
            var block = new TextBlock { Text = text, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 10, 0) };
            if (wrap) block.TextWrapping = TextWrapping.Wrap;
            if (bold) block.FontWeight = FontWeights.SemiBold;
            block.SetResourceReference(TextBlock.ForegroundProperty, key);
            return block;
        }

        private static Grid ColumnGrid()
        {
            var grid = new Grid();
            foreach (object[] c in Columns)
            {
                int weight = (int)c[1];
                double minimum = (double)c[2];
                grid.ColumnDefinitions.Add(new ColumnDefinition
                {
                    Width = weight > 0 ? new GridLength(weight, GridUnitType.Star) : new GridLength(minimum),
                    MinWidth = minimum,
                });
            }
            return grid;
        }

        private static void Place(Grid grid, UIElement element, int index)
        {
            Grid.SetColumn(element, index);
            grid.Children.Add(element);
        }

        private static Border Pill(string kind)
        {
            Kind k;
            if (!Kinds.TryGetValue(kind, out k)) k = Kinds["failed"];
            var border = new Border
            {
                CornerRadius = new CornerRadius(3),
                Padding = new Thickness(6, 1, 6, 1),
                Margin = new Thickness(0, 0, 10, 0),
                HorizontalAlignment = HorizontalAlignment.Left,
                VerticalAlignment = VerticalAlignment.Center,
            };
            border.SetResourceReference(Border.BackgroundProperty, k.Colour);
            TextBlock text = Text(k.Label, "OnAccent", true, false);
            text.Margin = new Thickness(0);
            text.FontSize = 10.5;
            border.Child = text;
            return border;
        }

        private static void BuildRows(Window window, List<A3dRow> rows)
        {
            Grid heading = ColumnGrid();
            for (int i = 0; i < Columns.Length; i++) Place(heading, Text((string)Columns[i][0], "TextMuted", true, false), i);
            ((Border)window.FindName("HeadingRow")).Child = heading;

            var panel = (StackPanel)window.FindName("Rows");
            foreach (A3dRow row in rows)
            {
                Kind k;
                if (!Kinds.TryGetValue(row.Kind, out k)) k = Kinds["failed"];
                Grid grid = ColumnGrid();
                Place(grid, Pill(row.Kind), 0);
                Place(grid, Text(row.First), 1);
                Place(grid, Text(row.Second), 2);
                Place(grid, Text(string.IsNullOrEmpty(row.Mode) ? "-" : row.Mode, "TextMuted"), 3);
                Place(grid, Text(row.MovedMm == null ? "-" : row.MovedMm.Value.ToString("0.0") + " mm", "Text", false, false), 4);
                Place(grid, Text(row.Note), 5);
                var border = new Border { Padding = new Thickness(8, 6, 8, 6), BorderThickness = new Thickness(0, 0, 0, 1), Child = grid };
                border.SetResourceReference(Border.BackgroundProperty, k.Tint);
                border.SetResourceReference(Border.BorderBrushProperty, "Edge");
                panel.Children.Add(border);
            }
        }

        private static string Summary(List<A3dRow> rows)
        {
            var parts = new List<string>();
            foreach (var pair in new[]
            {
                Tuple.Create("ok", "aligned"), Tuple.Create("warn", "aligned - check"), Tuple.Create("already", "already aligned"),
                Tuple.Create("refused", "refused"), Tuple.Create("failed", "failed"),
            })
            {
                int n = rows.Count(r => r.Kind == pair.Item1);
                if (n > 0) parts.Add(n + " " + pair.Item2);
            }
            return parts.Count > 0 ? string.Join(", ", parts) : "Nothing aligned";
        }

        public static void ShowResults(List<A3dRow> rows, Dictionary<string, string> settings, UIApplication uiapp)
        {
            Window window = A3dXaml.Load("Align3DResults.xaml");
            var chrome = new A3dChrome(window, settings, true, null, true);
            BuildRows(window, rows);
            ((TextBlock)window.FindName("StatusText")).Text = Summary(rows) + ". Debug log: " + A3dSettings.DebugPath();
            ((Button)window.FindName("OkBtn")).Click += (s, a) => window.Close();
            ((Button)window.FindName("SettingsChip")).Click += (s, a) =>
            {
                ShowSettings(uiapp, null);
                chrome.SetThemeFromFile();
            };
            A3dXaml.OwnToRevit(window, uiapp);
            window.ShowDialog();
        }

        internal static void SetThemeFromFile(this A3dChrome chrome)
        {
            // settings may have changed the theme while the results window was open: re-read it and repaint
            Dictionary<string, string> stored = A3dSettings.Load();
            chrome.ReloadTheme(A3dSettings.Get(stored, "theme"));
        }

        private static readonly string[][][] Radios =
        {
            new[] { new[] { "keep_running" }, new[] { "on", "KeepOn" }, new[] { "off", "KeepOff" } },
            new[] { new[] { "show_results" }, new[] { "needs_look", "ShowLook" }, new[] { "always", "ShowAlways" }, new[] { "never", "ShowNever" } },
            new[] { new[] { "on_refusal" }, new[] { "detach", "RefDetach" }, new[] { "leave", "RefLeave" } },
            new[] { new[] { "theme" }, new[] { "follow", "ThemeFollow" }, new[] { "dark", "ThemeDark" }, new[] { "light", "ThemeLight" } },
        };

        private static void SetStatus(Window window, string text)
        {
            var status = (TextBlock)window.FindName("StatusText");
            status.Text = text;
            status.SetResourceReference(TextBlock.ForegroundProperty, "Red");
        }

        /// <summary>Modal. True if Apply saved them.</summary>
        public static bool ShowSettings(UIApplication uiapp, Dictionary<string, string> given)
        {
            Dictionary<string, string> settings = new Dictionary<string, string>(given ?? A3dSettings.Load());
            Window window = A3dXaml.Load("Align3DSettings.xaml");
            bool loading = true, saved = false;

            Action<string> pushRadios = key =>
            {
                foreach (string[][] group in Radios)
                {
                    string setting = group[0][0];
                    if (key != null && setting != key) continue;
                    foreach (string[] option in group.Skip(1))
                        ((RadioButton)window.FindName(option[1])).IsChecked = A3dSettings.Get(settings, setting) == option[0];
                }
            };

            A3dChrome chrome = null;
            chrome = new A3dChrome(window, settings, false, mode =>
            {
                if (loading) return;
                loading = true;
                try { pushRadios("theme"); } finally { loading = false; }
            }, false);
            pushRadios(null);
            ((TextBox)window.FindName("MaxMove")).Text = A3dSettings.Get(settings, "max_move_mm");
            ((CheckBox)window.FindName("DebugTick")).IsChecked = A3dSettings.IsOn(settings, "debug");
            loading = false;

            foreach (string[] option in Radios[3].Skip(1))
            {
                string value = option[0];
                ((RadioButton)window.FindName(option[1])).Checked += (s, a) =>
                {
                    if (!loading && A3dSettings.Get(settings, "theme") != value) chrome.SetTheme(value);
                };
            }

            ((Button)window.FindName("ApplyBtn")).Click += (s, a) =>
            {
                var chosen = new Dictionary<string, string>(settings);
                foreach (string[][] group in Radios)
                    foreach (string[] option in group.Skip(1))
                        if (((RadioButton)window.FindName(option[1])).IsChecked == true) chosen[group[0][0]] = option[0];
                string limit = A3dSettings.CleanValue("max_move_mm", ((TextBox)window.FindName("MaxMove")).Text);
                if (limit == null)
                {
                    SetStatus(window, "The largest move has to be a number of millimetres, 0 or more.");
                    return;
                }
                chosen["max_move_mm"] = limit;
                chosen["debug"] = ((CheckBox)window.FindName("DebugTick")).IsChecked == true ? "on" : "off";
                if (A3dSettings.Save(chosen))
                {
                    saved = true;
                    window.Close();
                }
                else SetStatus(window, "Could not write " + A3dSettings.SettingsPath());
            };
            ((Button)window.FindName("CancelBtn")).Click += (s, a) => window.Close();
            A3dXaml.OwnToRevit(window, uiapp);
            window.ShowDialog();
            return saved;
        }
    }
}
