using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Markup;
using System.Windows.Media;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.Wires;

using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using Color = System.Windows.Media.Color;
using Grid = System.Windows.Controls.Grid;
using Orientation = System.Windows.Controls.Orientation;

namespace RevoBIM.UI.Wires
{
    /// <summary>The two palettes and which one is in force (wires_theme.py). The setting is stored as follow / dark / light, so following Revit is a state rather than the absence of one.</summary>
    internal static class WiresTheme
    {
        public const string Follow = "follow", Dark = "dark", Light = "light";
        public static readonly string[] Modes = { Follow, Dark, Light };

        // Both palettes carry exactly the same keys - a key missing from one is a brush left behind at its dark default after a swap.
        private static readonly Dictionary<string, string> DarkPalette = new Dictionary<string, string>
        {
            { "Shell", "#232326" }, { "Card", "#2B2B2E" }, { "Field", "#1C1C1F" }, { "Bar", "#1C1C1F" }, { "Edge", "#3E3E42" }, { "Rim", "#4A4A50" },
            { "Fg", "#E4E4E4" }, { "Muted", "#9A9A9E" }, { "Blue", "#4FA3E3" }, { "Orange", "#E8912D" }, { "Green", "#3FA75A" }, { "GreenHi", "#4EC06D" },
            { "Red", "#D9534F" }, { "Sel", "#2B5473" }, { "Ghost", "#33333A" }, { "Disabled", "#3A3A3E" }, { "DisabledFg", "#77777B" }, { "OnAccent", "#FFFFFF" },
            // what sits on a blue fill - dark navy on the pale dark-mode blue, white on the deeper light-mode one
            { "OnBlue", "#0E2233" },
        };

        private static readonly Dictionary<string, string> LightPalette = new Dictionary<string, string>
        {
            { "Shell", "#F3F3F5" }, { "Card", "#FFFFFF" }, { "Field", "#FAFAFB" }, { "Bar", "#E6E6EA" }, { "Edge", "#C8C8CE" }, { "Rim", "#B4B4BC" },
            { "Fg", "#1E1E22" }, { "Muted", "#6A6A72" },
            // the accents are darkened, not inverted - the dark ones are chosen to sit on near-black and wash out on white
            { "Blue", "#1B72BE" }, { "Orange", "#B96A12" }, { "Green", "#2E8546" }, { "GreenHi", "#38A055" }, { "Red", "#C0392B" }, { "Sel", "#CFE3F5" },
            { "Ghost", "#E1E1E6" }, { "Disabled", "#DCDCE0" }, { "DisabledFg", "#9A9AA0" }, { "OnAccent", "#FFFFFF" }, { "OnBlue", "#FFFFFF" },
        };

        public static Dictionary<string, string> Palette(string name)
        {
            return name == Light ? LightPalette : DarkPalette;
        }

        public static string Hex(string name, string key)
        {
            string v;
            if (Palette(name).TryGetValue(key, out v)) return v;
            return DarkPalette.TryGetValue(key, out v) ? v : "#9A9A9E";
        }

        public static string Normalise(string mode)
        {
            string text = (mode ?? "").Trim().ToLowerInvariant();
            if (Modes.Contains(text)) return text;
            return Follow;   // auto / revit / canvas and anything unreadable follow Revit
        }

        /// <summary>The chip's cycle: Auto, then Dark, then Light, then back to Auto.</summary>
        public static string NextMode(string mode)
        {
            mode = Normalise(mode);
            return Modes[(Array.IndexOf(Modes, mode) + 1) % Modes.Length];
        }

        /// <summary>The palette in force for a stored mode and what Revit says. Following with nothing to follow lands on dark, the house default.</summary>
        public static string Resolve(string mode, bool? canvasDark)
        {
            mode = Normalise(mode);
            if (mode == Dark || mode == Light) return mode;
            return canvasDark == false ? Light : Dark;
        }

        private static string ChipWord(string name)
        {
            return name == Follow ? "Auto" : name == Dark ? "Dark" : "Light";
        }

        /// <summary>"Auto · Dark" while following, so the chip says what it is showing.</summary>
        public static string ChipText(string mode, string resolved)
        {
            mode = Normalise(mode);
            if (mode == Follow) return "Auto · " + (resolved == Light ? "Light" : "Dark");
            return ChipWord(mode);
        }

        public static string ChipTip(string mode, string resolved)
        {
            mode = Normalise(mode);
            if (mode == Follow) return "Following Revit's canvas (" + resolved + "). Click for Dark, then Light, then back to following Revit.";
            return ChipWord(mode) + " theme, whatever Revit is using. Click to change.";
        }
    }

    /// <summary>
    /// Wires shared window plumbing (wires_ui.py): XAML loading with the theme merged in, the RevoBIM header (theme chip, shrink to taskbar, close), and the
    /// palette in force. Nothing in the tool paints a colour by value: code-built elements take theirs through Paint(), a resource reference, so a theme swap
    /// repaints them with the rest.
    /// </summary>
    internal static class WiresUi
    {
        private const string LayoutPrefix = "RevoBIM.UI.Wires.Layouts.";
        private const string IconResource = "RevoBIM.Resources.Wires.icon.png";

        public static readonly ChromeConfig Config = new ChromeConfig
        {
            IconResource = IconResource,
            Version = WiresSettings.Version,
            Log = s => { },
        };

        public static string CurrentMode = WiresTheme.Follow;
        public static string CurrentName = WiresTheme.Dark;
        private static readonly List<Window> OpenWindows = new List<Window>();

        public static SolidColorBrush Brush(string hex)
        {
            try
            {
                var b = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
                b.Freeze();
                return b;
            }
            catch (Exception)
            {
                return new SolidColorBrush(Color.FromRgb(154, 154, 158));
            }
        }

        /// <summary>Has a code-built element follow a palette key, live. A brush assigned by value is invisible to a theme swap; a resource reference re-resolves with everything else.</summary>
        public static void Paint(FrameworkElement element, DependencyProperty property, string key)
        {
            try
            {
                element.SetResourceReference(property, key);
                return;
            }
            catch (Exception)
            {
            }
            try
            {
                element.SetValue(property, Brush(WiresTheme.Hex(CurrentName, key)));
            }
            catch (Exception)
            {
            }
        }

        public static bool? RevitCanvasDark()
        {
            return ChromeConfig.CanvasIsDark();
        }

        private static string StoredMode()
        {
            try
            {
                return WiresTheme.Normalise(WiresSettings.Get(WiresSettings.Load(), "theme", WiresTheme.Follow));
            }
            catch (Exception)
            {
                return WiresTheme.Follow;
            }
        }

        private static void StoreMode(string mode)
        {
            try
            {
                Dictionary<string, string> settings = WiresSettings.Load();
                settings["theme"] = mode;
                WiresSettings.Save(settings);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Writes the palette onto window.Resources, which WPF looks in before the merged Theme.xaml, so every DynamicResource re-resolves in place.</summary>
        public static void ApplyTheme(Window window, string name)
        {
            foreach (var entry in WiresTheme.Palette(name))
            {
                try
                {
                    window.Resources[entry.Key] = Brush(entry.Value);
                }
                catch (Exception)
                {
                }
            }
            DressChip(window);
        }

        /// <summary>Re-reads the setting and Revit's canvas, and repaints every open window.</summary>
        public static string RefreshTheme(string mode = null)
        {
            if (mode == null) mode = StoredMode();
            CurrentMode = WiresTheme.Normalise(mode);
            CurrentName = WiresTheme.Resolve(CurrentMode, RevitCanvasDark());
            foreach (Window w in OpenWindows.ToList()) ApplyTheme(w, CurrentName);
            return CurrentName;
        }

        private static void DressChip(Window window)
        {
            try
            {
                var text = window.FindName("ThemeText") as TextBlock;
                if (text != null) text.Text = WiresTheme.ChipText(CurrentMode, CurrentName);
                var chip = window.FindName("ThemeChip") as FrameworkElement;
                if (chip != null) chip.ToolTip = WiresTheme.ChipTip(CurrentMode, CurrentName);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Parses a layout into a themed Window. The theme is merged after the parse, which is why layouts may only use DynamicResource.</summary>
        public static Window LoadWindow(string file)
        {
            Window window = XamlLoader.Load<Window>(LayoutPrefix + file, null);
            try
            {
                window.Resources.MergedDictionaries.Add((ResourceDictionary)XamlReader.Parse(XamlLoader.ReadResource(LayoutPrefix + "Theme.xaml")));
            }
            catch (Exception)
            {
            }
            OpenWindows.Add(window);
            window.Closed += (s, a) => OpenWindows.Remove(window);
            RefreshTheme();
            return window;
        }

        /// <summary>
        /// Icon, version, theme chip, shrink to taskbar, drag and close - what every RevoBIM window's header does. Returns the window's drawer. Every step swallows its own
        /// failure: cosmetics must never be able to take a tool down. egg arms the logo easter egg (main windows only).
        /// </summary>
        public static WindowDrawer DressHeader(Window window, bool egg = false)
        {
            try
            {
                var label = window.FindName("VersionText") as TextBlock;
                if (label != null) label.Text = "v" + WiresSettings.Version;
            }
            catch (Exception)
            {
            }
            var image = window.FindName("HeaderIcon") as Image;
            ThemedWindow.LoadIcon(image, IconResource);
            if (egg) EggHook.Attach(window, () => CurrentName, image);
            try
            {
                var chip = window.FindName("ThemeChip") as Button;
                if (chip != null)
                {
                    chip.Click += (s, a) =>
                    {
                        // Auto, Dark, Light, Auto. Saved straight away, every window repainted.
                        string mode = WiresTheme.NextMode(CurrentMode);
                        StoreMode(mode);
                        RefreshTheme(mode);
                    };
                }
            }
            catch (Exception)
            {
            }
            DressChip(window);

            WindowDrawer drawer = null;
            try
            {
                var header = (FrameworkElement)window.FindName("HeaderBar");
                drawer = new WindowDrawer(Config, window, header, window.FindName("Chrome") as FrameworkElement, window.FindName("ShrinkButton") as Button,
                                          window.FindName("ShrinkGlyph") as UIElement, window.FindName("ExpandGlyph") as UIElement, null,
                                          WindowDrawer.ChildrenOf(window.FindName("RootGrid") as Panel, header, null));
                window.PreviewKeyDown += (s, a) =>
                {
                    try
                    {
                        Key key = a.Key == Key.System ? a.SystemKey : a.Key;
                        if (drawer.OnKey(key, RevoChrome.CtrlDown(), RevoChrome.ShiftDown())) a.Handled = true;
                    }
                    catch (Exception)
                    {
                    }
                };
            }
            catch (Exception)
            {
                drawer = null;
            }
            try
            {
                var bar = window.FindName("HeaderBar") as FrameworkElement;
                if (bar != null)
                {
                    WindowDrawer d = drawer;
                    bar.MouseLeftButtonDown += (s, a) =>
                    {
                        try
                        {
                            // a double-click while parked reopens; anything else drags, parked or not
                            if (d != null && a.ClickCount >= 2 && d.OnHeaderDoubleClick())
                            {
                                a.Handled = true;
                                return;
                            }
                            window.DragMove();
                        }
                        catch (Exception)
                        {
                        }
                    };
                }
            }
            catch (Exception)
            {
            }
            try
            {
                var close = window.FindName("CloseButton") as Button;
                if (close != null) close.Click += (s, a) => { try { window.Close(); } catch (Exception) { } };
            }
            catch (Exception)
            {
            }
            return drawer;
        }

        public static void OwnedByRevit(Window window, UIApplication uiapp)
        {
            if (uiapp != null) RevoChrome.OwnToRevit(window, uiapp);
        }

        /// <summary>Sits the window out of the way of the drawing it is asking about.</summary>
        public static void ParkBottomRight(Window window, double margin = 40)
        {
            try
            {
                Rect area = SystemParameters.WorkArea;
                window.Left = area.Left + area.Width - window.Width - margin;
                window.Top = area.Top + area.Height - 260 - margin;
            }
            catch (Exception)
            {
            }
        }

        private static string TickFor(string kind)
        {
            switch (kind)
            {
                case Report.Ok: return "Green";
                case Report.Note: return "Orange";
                case Report.Skip: return "Red";
                default: return "Muted";
            }
        }

        /// <summary>One line of the results list, built in code rather than bound.</summary>
        public static UIElement ReportRow(string kind, string text)
        {
            var grid = new Grid { Margin = new Thickness(0, 3, 0, 3) };
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var tick = new Border { Width = 4, CornerRadius = new CornerRadius(2), Margin = new Thickness(0, 1, 9, 1) };
            Paint(tick, Border.BackgroundProperty, TickFor(kind));
            Grid.SetColumn(tick, 0);
            grid.Children.Add(tick);
            var label = new TextBlock { Text = text, FontSize = 12, TextWrapping = TextWrapping.Wrap };
            Paint(label, TextBlock.ForegroundProperty, kind == Report.Skip || kind == Report.Info ? "Muted" : "Fg");
            Grid.SetColumn(label, 1);
            grid.Children.Add(label);
            return grid;
        }

        /// <summary>The muted note that sits under a setting.</summary>
        public static TextBlock Hint(string text)
        {
            var block = new TextBlock { Text = text, FontSize = 11, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 2, 0, 6) };
            Paint(block, TextBlock.ForegroundProperty, "Muted");
            return block;
        }

        public static void SetText(Window window, string name, string text)
        {
            try
            {
                var tb = window.FindName(name) as TextBlock;
                if (tb != null) tb.Text = text;
            }
            catch (Exception)
            {
            }
        }
    }

    /// <summary>
    /// Hands work to Revit and tells the window when it is done: the external event behind a modeless Shuffle (wire_events.py). A modeless window is not in the
    /// command's API context, so any transaction has to be opened from inside an ExternalEvent. Nothing is queued: a second request while one is in flight is dropped.
    /// </summary>
    public sealed class WiresEventBridge : IExternalEventHandler
    {
        private Action<UIApplication> action;
        private Action after;
        private readonly ExternalEvent ev;

        public bool Busy;

        public WiresEventBridge()
        {
            ev = ExternalEvent.Create(this);
        }

        public bool Run(Action<UIApplication> work, Action afterwards = null)
        {
            if (Busy) return false;
            Busy = true;
            action = work;
            after = () =>
            {
                Busy = false;
                if (afterwards != null) afterwards();
            };
            try
            {
                ev.Raise();
            }
            catch (Exception)
            {
                Busy = false;
                return false;
            }
            return true;
        }

        public void Execute(UIApplication app)
        {
            Action<UIApplication> work = action;
            action = null;
            if (work == null) return;
            try
            {
                work(app);
            }
            catch (Exception)
            {
            }
            try
            {
                if (after != null) after();
            }
            catch (Exception)
            {
            }
        }

        public string GetName()
        {
            return "RevoBIM Wires";
        }
    }
}
