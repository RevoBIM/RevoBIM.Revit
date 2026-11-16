using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using System.Xml;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.ModelCleanup;
using static RevoBIM.Tools.ModelCleanup.McuCore;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.ModelCleanup
{
    /// <summary>The dark and light palettes, and which one Revit's canvas is using. Port of mcu_theme.py.</summary>
    public static class McuTheme
    {
        // Dark follows Revit's own dark theme, which is Autodesk's slate blue-grey rather than a neutral grey.
        public static readonly Dictionary<string, string> Dark = new Dictionary<string, string>
        {
            { "BgBrush", "#2D3440" }, { "CardBrush", "#3B4453" }, { "FieldBrush", "#262D38" }, { "BarBrush", "#222933" },
            { "EdgeBrush", "#4F596C" }, { "WindowEdgeBrush", "#5B667B" }, { "TextBrush", "#F2F4F7" }, { "MutedBrush", "#B2BAC6" },
            { "BlueBrush", "#4FA3E3" }, { "OrangeBrush", "#E8912D" }, { "GreenBrush", "#3FA75A" }, { "GreenHoverBrush", "#4EC06D" },
            { "RedBrush", "#EE7A75" }, { "SelectBrush", "#2E5A80" }, { "HoverBrush", "#4A5468" }, { "OnAccentBrush", "#FFFFFF" },
            { "LockedBrush", "#333A47" }, { "BlueSoftBrush", "#2A4A66" }, { "GreenSoftBrush", "#2B4636" }, { "OrangeSoftBrush", "#4D3D2A" },
        };

        // The light palette is not the dark one inverted: the accents are darkened because the dark ones wash out on white.
        public static readonly Dictionary<string, string> Light = new Dictionary<string, string>
        {
            { "BgBrush", "#F3F3F5" }, { "CardBrush", "#FFFFFF" }, { "FieldBrush", "#FAFAFB" }, { "BarBrush", "#E6E6EA" },
            { "EdgeBrush", "#CDCDD3" }, { "WindowEdgeBrush", "#B5B5BC" }, { "TextBrush", "#1E1E22" }, { "MutedBrush", "#6A6A72" },
            { "BlueBrush", "#1B72BE" }, { "OrangeBrush", "#B96A12" }, { "GreenBrush", "#2E8546" }, { "GreenHoverBrush", "#36A055" },
            { "RedBrush", "#C23B37" }, { "SelectBrush", "#CFE3F5" }, { "HoverBrush", "#ECECF0" }, { "OnAccentBrush", "#FFFFFF" },
            { "LockedBrush", "#EDEDF0" }, { "BlueSoftBrush", "#E3EEF8" }, { "GreenSoftBrush", "#E2F1E6" }, { "OrangeSoftBrush", "#F7ECDF" },
        };

        public static Dictionary<string, string> Palette(string resolved)
        {
            return resolved == ThemeLight ? Light : Dark;
        }

        public static Brush MakeBrush(string hex)
        {
            var brush = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
            try { brush.Freeze(); } catch (Exception) { }
            return brush;
        }

        /// <summary>
        /// The palette is written straight onto window.Resources, which sits in front of the merged Theme.xaml
        /// in WPF's lookup order, so a switch on an open window needs no reload.
        /// </summary>
        public static void Apply(Window window, string resolved)
        {
            foreach (var pair in Palette(resolved))
            {
                try { window.Resources[pair.Key] = MakeBrush(pair.Value); }
                catch (Exception) { Log("theme: could not set " + pair.Key); }
            }
        }

        private static bool? ThemeIsDark(object value)
        {
            string text = (Convert.ToString(value) ?? "").ToLowerInvariant();
            if (text.Contains("dark")) return true;
            if (text.Contains("light")) return false;
            return null;
        }

        /// <summary>True / False from Revit's own settings, None when nothing answers. Every route is looked up late.</summary>
        public static bool? CanvasIsDark(UIApplication uiapp)
        {
            Type manager = typeof(UIApplication).Assembly.GetType("Autodesk.Revit.UI.UIThemeManager");
            foreach (string property in new[] { "CurrentCanvasTheme" })
            {
                try
                {
                    var info = manager?.GetProperty(property, BindingFlags.Public | BindingFlags.Static);
                    bool? answer = info == null ? null : ThemeIsDark(info.GetValue(null, null));
                    if (answer != null) return answer;
                }
                catch (Exception) { }
            }
            try
            {
                var colour = uiapp.Application.BackgroundColor;
                return ColourIsDark(colour.Red, colour.Green, colour.Blue);
            }
            catch (Exception) { }
            try
            {
                var info = manager?.GetProperty("CurrentTheme", BindingFlags.Public | BindingFlags.Static);
                bool? answer = info == null ? null : ThemeIsDark(info.GetValue(null, null));
                if (answer != null) return answer;
            }
            catch (Exception) { }
            return null;
        }
    }

    /// <summary>Theme state - one per run, shared by every open window. Auto follows the Revit canvas; the chip cycles Auto, Dark, Light.</summary>
    public sealed class McuThemeState
    {
        private readonly Dictionary<string, string> settings;
        public string Mode;
        public bool? CanvasDark;
        private readonly List<(Window Window, Button Chip, TextBlock ChipText)> windows = new List<(Window, Button, TextBlock)>();

        public McuThemeState(UIApplication uiapp, Dictionary<string, string> settings)
        {
            this.settings = settings;
            Mode = NormaliseThemeMode(settings.Get("theme_mode"));
            try { CanvasDark = McuTheme.CanvasIsDark(uiapp); }
            catch (Exception) { CanvasDark = null; }
        }

        public string Resolved { get { return ResolveTheme(Mode, CanvasDark); } }
        public Dictionary<string, string> Palette() { return McuTheme.Palette(Resolved); }

        public void Register(Window window, Button chip, TextBlock chipText)
        {
            windows.Add((window, chip, chipText));
            McuTheme.Apply(window, Resolved);
            Label(chip, chipText);
            if (chip != null) chip.Click += McuUi.Safe(window, (s, a) => OnChip(), this, "theme chip");
            window.Closed += (s, a) => windows.RemoveAll(w => ReferenceEquals(w.Window, window));
        }

        private void OnChip()
        {
            Mode = NextThemeMode(Mode);
            settings["theme_mode"] = Mode;
            SaveGlobal(settings);
            ApplyAll();
        }

        public void ApplyAll()
        {
            foreach (var entry in windows.ToList())
            {
                try
                {
                    McuTheme.Apply(entry.Window, Resolved);
                    Label(entry.Chip, entry.ChipText);
                }
                catch (Exception) { Log("theme: could not repaint a window"); }
            }
        }

        private void Label(Button chip, TextBlock chipText)
        {
            string label = ThemeChipLabel(Mode, Resolved);
            if (chipText != null) chipText.Text = label;
            if (chip == null) return;
            if (Mode == ThemeAuto)
            {
                string canvas = CanvasDark == null ? "unknown" : CanvasDark.Value ? "dark" : "light";
                chip.ToolTip = "Following the Revit canvas (" + canvas + "). Click to fix it to Dark.";
            }
            else
            {
                chip.ToolTip = Mode == ThemeDark ? "Dark. Click for Light." : "Light. Click to follow the Revit canvas again.";
            }
        }
    }

    /// <summary>Looks an element up by name and fails loudly, naming the window and the element.</summary>
    public sealed class McuFinder
    {
        private readonly Window window;
        public McuFinder(Window window) { this.window = window; }

        public T Get<T>(string name) where T : class
        {
            object element = window.FindName(name);
            if (element == null) throw new KeyNotFoundException(window.Title + " has no element named " + name);
            return (T)element;
        }

        public FrameworkElement this[string name] { get { return Get<FrameworkElement>(name); } }
        public Button Button(string name) { return Get<Button>(name); }
        public TextBlock Text(string name) { return Get<TextBlock>(name); }
        public TextBox Box(string name) { return Get<TextBox>(name); }
        public CheckBox Check(string name) { return Get<CheckBox>(name); }
        public ComboBox Combo(string name) { return Get<ComboBox>(name); }
    }

    /// <summary>Window plumbing shared by every Model Cleanup window. Port of mcu_ui.py.</summary>
    public static class McuUi
    {
        private const string LayoutPrefix = "RevoBIM.UI.ModelCleanup.Layouts.";
        private const string IconResource = "RevoBIM.Resources.ModelCleanup.icon.png";

        public static object LoadXaml(string fileName)
        {
            try
            {
                using (Stream stream = typeof(McuUi).Assembly.GetManifestResourceStream(LayoutPrefix + fileName))
                {
                    if (stream == null) throw new FileNotFoundException("embedded resource " + LayoutPrefix + fileName + " was not found");
                    using (XmlReader reader = XmlReader.Create(stream)) return XamlReader.Load(reader);
                }
            }
            catch (Exception error)
            {
                throw new Exception(fileName + " would not parse: " + error.Message, error);
            }
        }

        public static Window LoadWindow(string fileName, McuThemeState theme = null)
        {
            var window = (Window)LoadXaml(fileName);
            var dictionary = (ResourceDictionary)LoadXaml("Theme.xaml");
            window.Resources.MergedDictionaries.Add(dictionary);
            if (theme != null) McuTheme.Apply(window, theme.Resolved);
            return window;
        }

        public static void LoadIcon(Image image)
        {
            try
            {
                using (Stream stream = typeof(McuUi).Assembly.GetManifestResourceStream(IconResource))
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
            catch (Exception) { }
        }

        public static void SetVersion(TextBlock block)
        {
            try { block.Text = "v" + McuCore.Version; }
            catch (Exception) { }
        }

        // ============================================================
        // no silent handlers
        // ============================================================

        /// <summary>Every button goes through this: an exception is logged, shown, and never swallowed.</summary>
        public static RoutedEventHandler Safe(Window window, Action<object, RoutedEventArgs> handler, McuThemeState theme, string stage = null)
        {
            return (sender, args) =>
            {
                try { handler(sender, args); }
                catch (Exception error)
                {
                    string text = FormatException(error);
                    try { ShowError(window, stage ?? "a button", text, theme); }
                    catch (Exception) { WriteError(stage ?? "a button", text); }
                }
            };
        }

        public static SelectionChangedEventHandler SafeSelection(Window window, Action<object, SelectionChangedEventArgs> handler,
                                                                 McuThemeState theme, string stage = null)
        {
            return (sender, args) =>
            {
                try { handler(sender, args); }
                catch (Exception error)
                {
                    string text = FormatException(error);
                    try { ShowError(window, stage ?? "a list", text, theme); }
                    catch (Exception) { WriteError(stage ?? "a list", text); }
                }
            };
        }

        public static EventHandler SafeTick(Window window, Action handler, McuThemeState theme, string stage = null)
        {
            return (sender, args) =>
            {
                try { handler(); }
                catch (Exception error)
                {
                    string text = FormatException(error);
                    try { ShowError(window, stage ?? "a timer", text, theme); }
                    catch (Exception) { WriteError(stage ?? "a timer", text); }
                }
            };
        }

        public static void ShowError(Window owner, string stage, string text, McuThemeState theme)
        {
            WriteError(stage, text);
            string tail = text.Length > 1500 ? text.Substring(text.Length - 1500) : text;
            Prompt(owner, "Something went wrong", stage + " failed.\n\n" + tail + "\n\nThe full text is in " + ErrorPath(),
                   new List<McuButton> { new McuButton("OK", true, "BaseButton") }, theme);
        }

        // ============================================================
        // geometry and Revit's own window
        // ============================================================

        [DllImport("user32.dll")] private static extern bool EnableWindow(IntPtr hWnd, bool enable);
        [DllImport("user32.dll")] private static extern IntPtr MonitorFromWindow(IntPtr hwnd, uint flags);

        [StructLayout(LayoutKind.Sequential)]
        private struct Rect { public int Left, Top, Right, Bottom; }

        [StructLayout(LayoutKind.Sequential)]
        private struct MonitorInfo { public int Size; public Rect Monitor; public Rect Work; public uint Flags; }

        [DllImport("user32.dll")] private static extern bool GetMonitorInfo(IntPtr monitor, ref MonitorInfo info);

        private static double DpiScale(Window window)
        {
            try
            {
                PresentationSource source = PresentationSource.FromVisual(window);
                double scale = source.CompositionTarget.TransformToDevice.M11;
                return scale > 0 ? scale : 1.0;
            }
            catch (Exception) { return 1.0; }
        }

        /// <summary>The working area of the screen the window is on, in WPF units.</summary>
        public static (double Left, double Top, double Width, double Height) WorkArea(Window window)
        {
            try
            {
                IntPtr handle = new WindowInteropHelper(window).Handle;
                IntPtr monitor = MonitorFromWindow(handle, 2);
                var info = new MonitorInfo { Size = Marshal.SizeOf(typeof(MonitorInfo)) };
                if (monitor == IntPtr.Zero || !GetMonitorInfo(monitor, ref info)) throw new InvalidOperationException();
                double scale = DpiScale(window);
                return (info.Work.Left / scale, info.Work.Top / scale,
                        (info.Work.Right - info.Work.Left) / scale, (info.Work.Bottom - info.Work.Top) / scale);
            }
            catch (Exception)
            {
                var work = SystemParameters.WorkArea;
                return (work.Left, work.Top, work.Width, work.Height);
            }
        }

        /// <summary>Revit's main window handle, or zero.</summary>
        public static IntPtr RevitHandle(UIApplication uiapp)
        {
            try
            {
                IntPtr handle = uiapp.MainWindowHandle;
                if (handle != IntPtr.Zero) return handle;
            }
            catch (Exception) { }
            try { return System.Diagnostics.Process.GetCurrentProcess().MainWindowHandle; }
            catch (Exception) { return IntPtr.Zero; }
        }

        /// <summary>
        /// An owned window always sits above its owner, so a sync or a save that hands focus back to Revit
        /// cannot bury it - and it still goes behind other applications like any Revit dialog.
        /// </summary>
        public static bool OwnToRevit(Window window, UIApplication uiapp)
        {
            IntPtr handle = RevitHandle(uiapp);
            if (handle == IntPtr.Zero) return false;
            try
            {
                new WindowInteropHelper(window).Owner = handle;
                return true;
            }
            catch (Exception) { return false; }
        }

        /// <summary>Backstop after a long Revit call: restore, raise and focus. Topmost is only pulsed.</summary>
        public static void BringToFront(Window window)
        {
            try { if (window.WindowState == WindowState.Minimized) window.WindowState = WindowState.Normal; }
            catch (Exception) { }
            try
            {
                window.Activate();
                window.Topmost = true;
                window.Topmost = false;
                window.Focus();
            }
            catch (Exception) { }
        }

        /// <summary>
        /// A job pumps the dispatcher to move the progress bar, and that pumps Revit's window too. Revit is
        /// switched off for the length of a job so a click on the ribbon cannot start a command in the middle.
        /// </summary>
        public static bool SetRevitEnabled(IntPtr handle, bool enabled)
        {
            if (handle == IntPtr.Zero) return false;
            try
            {
                EnableWindow(handle, enabled);
                return true;
            }
            catch (Exception) { return false; }
        }

        /// <summary>Let the window repaint. Never call this inside an open transaction.</summary>
        public static void Pump(Window window)
        {
            try { window.Dispatcher.Invoke(new Action(() => { }), DispatcherPriority.Background); }
            catch (Exception) { }
        }

        public static void SetOwner(Window dialog, Window owner)
        {
            if (owner == null) return;
            try { dialog.Owner = owner; }
            catch (Exception) { return; }
            McuDrawer ownerDrawer = McuDrawer.For(owner);
            if (ownerDrawer != null && ownerDrawer.Parked) dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen;
            McuDrawer own = McuDrawer.For(dialog);
            if (own != null) own.LinkOwner(owner);
        }

        // ============================================================
        // the standard window
        // ============================================================

        public sealed class Standard
        {
            public Window Window;
            public McuFinder Find;
            public McuChrome Chrome;
            public McuDrawer Drawer;
        }

        /// <summary>Load, theme, chrome, version, icon, chip and egg in one go.</summary>
        public static Standard StandardWindow(string fileName, McuThemeState theme, Func<bool> isBusy)
        {
            Window window = LoadWindow(fileName, theme);
            var find = new McuFinder(window);
            // the drawer goes first: its key handler has to see a key before the window's own
            var drawer = new McuDrawer(window, find.Get<Border>("HeaderBar"), find.Get<Grid>("RootGrid"),
                                       find.Button("ShrinkButton"), TryFind<FrameworkElement>(find, "GripLayer"), isBusy);
            var chrome = new McuChrome(window, find, isBusy, drawer);
            SetVersion(find.Text("VersionText"));
            LoadIcon(find.Get<Image>("HeaderIcon"));
            theme.Register(window, find.Button("ThemeChip"), find.Text("ThemeChipText"));
            // the logo easter egg: three slow clicks on the RevoBIM logo open the RevoBIM Arcade
            EggHook.Attach(window, () => theme.Resolved, find["LogoText"]);
            return new Standard { Window = window, Find = find, Chrome = chrome, Drawer = drawer };
        }

        private static T TryFind<T>(McuFinder find, string name) where T : class
        {
            try { return find.Get<T>(name); }
            catch (Exception) { return null; }
        }

        // ============================================================
        // prompts
        // ============================================================

        /// <summary>Revit's own dialog, used only if the themed one cannot open. Every button except the first becomes a command link.</summary>
        private static object FallbackPrompt(string title, string message, List<McuButton> buttons)
        {
            try
            {
                var dialog = new TaskDialog("RevoBIM " + title) { MainContent = message };
                if (buttons.Count <= 1)
                {
                    dialog.Show();
                    return buttons.Count > 0 ? buttons[0].Value : null;
                }
                var choices = buttons.Skip(1).Take(4).ToList();
                var links = new[] { TaskDialogCommandLinkId.CommandLink1, TaskDialogCommandLinkId.CommandLink2,
                                    TaskDialogCommandLinkId.CommandLink3, TaskDialogCommandLinkId.CommandLink4 };
                var results = new[] { TaskDialogResult.CommandLink1, TaskDialogResult.CommandLink2,
                                      TaskDialogResult.CommandLink3, TaskDialogResult.CommandLink4 };
                for (int i = 0; i < choices.Count; i++) dialog.AddCommandLink(links[i], choices[i].Label);
                TaskDialogResult answer = dialog.Show();
                for (int i = 0; i < choices.Count; i++) if (answer == results[i]) return choices[i].Value;
                return buttons[0].Value;
            }
            catch (Exception) { return buttons.Count > 0 ? buttons[0].Value : null; }
        }

        /// <summary>
        /// buttons are left to right; the last is the default. Returns the value of the button pressed. Falls
        /// back to Revit's own dialog if the themed one cannot open - a confirm step that fails must never
        /// read as a silent no.
        /// </summary>
        public static object Prompt(Window owner, string title, string message, List<McuButton> buttons, McuThemeState theme)
        {
            return PromptCore(owner, title, message, buttons, theme, null, "").Value;
        }

        /// <summary>The same with a text box. Returns (value, text).</summary>
        public static (object Value, string Text) PromptInput(Window owner, string title, string message,
            List<McuButton> buttons, McuThemeState theme, string inputText, string inputHint)
        {
            return PromptCore(owner, title, message, buttons, theme, inputText ?? "", inputHint);
        }

        public static bool Confirm(Window owner, string title, string message, string yesLabel, string style, McuThemeState theme)
        {
            return Prompt(owner, title, message,
                          new List<McuButton> { new McuButton("Cancel", false, "BaseButton"), new McuButton(yesLabel, true, style) },
                          theme) as bool? == true;
        }

        public static void Tell(Window owner, string title, string message, McuThemeState theme)
        {
            Prompt(owner, title, message, new List<McuButton> { new McuButton("OK", true, "BaseButton") }, theme);
        }

        private static (object Value, string Text) PromptCore(Window owner, string title, string message,
            List<McuButton> buttons, McuThemeState theme, string inputText, string inputHint)
        {
            if (buttons == null || buttons.Count == 0) buttons = new List<McuButton> { new McuButton("OK", true, "GreenButton") };
            try
            {
                Window window = LoadWindow("McuPrompt.xaml", theme);
                var find = new McuFinder(window);
                SetVersion(find.Text("VersionText"));
                LoadIcon(find.Get<Image>("HeaderIcon"));
                find.Text("PromptTitle").Text = title;
                find.Text("MessageText").Text = message;
                TextBox box = find.Box("InputBox");
                if (inputText != null)
                {
                    box.Visibility = Visibility.Visible;
                    box.Text = inputText;
                    box.Tag = inputHint;
                }
                var drawer = new McuDrawer(window, find.Get<Border>("HeaderBar"), find.Get<Grid>("RootGrid"),
                                           find.Button("ShrinkButton"), null, null);
                SetOwner(window, owner);
                object result = buttons[0].Value;
                Panel panel = find.Get<Panel>("ButtonPanel");
                for (int index = 0; index < buttons.Count; index++)
                {
                    McuButton spec = buttons[index];
                    var button = new Button { Content = spec.Label, Margin = new Thickness(8, 0, 0, 0) };
                    try { button.Style = (Style)window.FindResource(spec.Style ?? "BaseButton"); }
                    catch (Exception) { }
                    button.Click += (s, a) =>
                    {
                        result = spec.Value;
                        try { window.Close(); } catch (Exception) { }
                    };
                    if (index == buttons.Count - 1) button.IsDefault = true;
                    if (index == 0 && buttons.Count > 1) button.IsCancel = true;
                    panel.Children.Add(button);
                }
                panel.HorizontalAlignment = HorizontalAlignment.Right;
                find.Get<Border>("HeaderBar").MouseLeftButtonDown += (s, a) =>
                {
                    try
                    {
                        if (a.ClickCount == 2 && drawer.Parked) { drawer.Expand(); return; }
                        window.DragMove();
                    }
                    catch (Exception) { }
                };
                if (inputText != null)
                {
                    box.Focus();
                    box.SelectAll();
                }
                window.ShowDialog();
                return (result, inputText != null ? box.Text : "");
            }
            catch (Exception error)
            {
                Log("prompt fell back to TaskDialog: " + FormatException(error));
                return (FallbackPrompt(title, message, buttons), inputText ?? "");
            }
        }
    }

    public sealed class McuButton
    {
        public string Label;
        public object Value;
        public string Style;

        public McuButton(string label, object value, string style)
        {
            Label = label;
            Value = value;
            Style = style;
        }
    }

    /// <summary>Borderless window: header drag, eight resize grips, full screen by bounds (F11, the button, or a double click on the header).</summary>
    public sealed class McuChrome
    {
        private static readonly string[] Grips = { "GripN", "GripS", "GripW", "GripE", "GripNW", "GripNE", "GripSW", "GripSE" };
        private readonly Window window;
        private readonly Func<bool> isBusy;
        private readonly McuDrawer drawer;
        private bool full;
        private (double Left, double Top, double Width, double Height)? saved;

        public McuChrome(Window window, McuFinder find, Func<bool> isBusy, McuDrawer drawer)
        {
            this.window = window;
            this.isBusy = isBusy ?? (() => false);
            this.drawer = drawer;
            find.Get<Border>("HeaderBar").MouseLeftButtonDown += OnHeaderDown;
            find.Button("FullScreenButton").Click += (s, a) =>
            {
                if (Parked) drawer.Expand();
                else ToggleFull();
            };
            find.Button("CloseButton").Click += (s, a) => window.Close();
            foreach (string name in Grips)
            {
                string grip = name;
                find.Get<Thumb>(name).DragDelta += (s, a) =>
                {
                    try { Resize(grip, a.HorizontalChange, a.VerticalChange); } catch (Exception) { }
                };
            }
            window.PreviewKeyDown += (s, a) =>
            {
                try
                {
                    if (a.Handled || Parked) return;
                    if (a.Key == Key.F11) { ToggleFull(); a.Handled = true; }
                }
                catch (Exception) { }
            };
        }

        private bool Parked { get { return drawer != null && drawer.Parked; } }

        private void OnHeaderDown(object sender, MouseButtonEventArgs args)
        {
            try
            {
                if (args.ClickCount == 2)
                {
                    if (Parked) drawer.Expand(); else ToggleFull();
                    return;
                }
                // DragMove is a modal message loop; never start one mid-job
                if (isBusy()) return;
                if (full && !Parked) LeaveFull();
                window.DragMove();
            }
            catch (Exception) { }
        }

        public void ToggleFull()
        {
            if (full) LeaveFull(); else EnterFull();
        }

        private void EnterFull()
        {
            saved = (window.Left, window.Top, window.Width, window.Height);
            var area = McuUi.WorkArea(window);
            window.Left = area.Left;
            window.Top = area.Top;
            window.Width = area.Width;
            window.Height = area.Height;
            full = true;
        }

        private void LeaveFull()
        {
            if (saved != null)
            {
                window.Left = saved.Value.Left;
                window.Top = saved.Value.Top;
                window.Width = saved.Value.Width;
                window.Height = saved.Value.Height;
            }
            full = false;
        }

        private void Resize(string name, double dx, double dy)
        {
            full = false;
            string edge = name.Substring(4);
            if (edge.Contains("E"))
            {
                double width = window.Width + dx;
                if (width >= window.MinWidth) window.Width = width;
            }
            if (edge.Contains("W"))
            {
                double width = window.Width - dx;
                if (width >= window.MinWidth) { window.Left += dx; window.Width = width; }
            }
            if (edge.Contains("S"))
            {
                double height = window.Height + dy;
                if (height >= window.MinHeight) window.Height = height;
            }
            if (edge.Contains("N"))
            {
                double height = window.Height - dy;
                if (height >= window.MinHeight) { window.Top += dy; window.Height = height; }
            }
        }
    }

    /// <summary>
    /// The shrink button top right. Pressed, the window slides down to the bottom of its screen like a drawer
    /// closing, leaving only its header bar floating clear of the taskbar so Revit can be seen; the button
    /// turns into a green up arrow that slides it back. Ctrl+Shift+H works both ways. The slide is eased by
    /// hand on a timer - plain assignments every frame, never a Storyboard. Port of the mcu_ui.py WindowDrawer.
    /// </summary>
    public sealed class McuDrawer
    {
        private static readonly Dictionary<Window, McuDrawer> Drawers = new Dictionary<Window, McuDrawer>();

        private readonly Window window;
        private readonly Border header;
        private readonly Grid root;
        private readonly Button button;
        private readonly FrameworkElement grips;
        private McuDrawer owner;
        private bool tookOwnerDown;
        public bool Parked { get; private set; }
        public bool Sliding { get; private set; }
        private (double Left, double Top, double Width, double Height) restore;
        private (double, double) parkedAt;
        private double bar;
        private double rootHeight;
        private double savedMin;
        private SizeToContent savedSizeTo;
        private CornerRadius? savedCorner;
        private List<(UIElement Child, Visibility Was)> hidden = new List<(UIElement, Visibility)>();
        private DispatcherTimer timer;
        private (double, double, double) start, end;
        private Action done;
        private DateTime t0;

        public McuDrawer(Window window, Border header, Grid root, Button button, FrameworkElement grips, Func<bool> isBusy)
        {
            this.window = window;
            this.header = header;
            this.root = root;
            this.button = button;
            this.grips = grips;
            button.Click += (s, a) => Guarded("shrink to taskbar", () => Toggle());
            window.PreviewKeyDown += OnKey;
            window.Closed += OnClosed;
            Drawers[window] = this;
            Dress();
        }

        public static McuDrawer For(Window window)
        {
            McuDrawer drawer;
            return window != null && Drawers.TryGetValue(window, out drawer) ? drawer : null;
        }

        public void LinkOwner(Window ownerWindow) { owner = For(ownerWindow); }

        private static void Guarded(string stage, Action action)
        {
            try { action(); }
            catch (Exception error) { WriteError(stage, FormatException(error)); }
        }

        private void OnKey(object sender, KeyEventArgs args)
        {
            try
            {
                bool ctrl = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control;
                bool shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift;
                string action = DrawerKeyAction(args.Key.ToString(), ctrl, shift, Parked, Sliding);
                if (action == null) return;
                args.Handled = true;
                if (action == "toggle") Toggle();
                else if (action == "open") Expand();
            }
            catch (Exception error) { Log("drawer key: " + FormatException(error)); }
        }

        private void OnClosed(object sender, EventArgs args)
        {
            Drawers.Remove(window);
            try { if (timer != null) timer.Stop(); } catch (Exception) { }
            if (tookOwnerDown && owner != null && owner.Parked) owner.Expand(true, false);
        }

        public bool Toggle() { return Parked ? Expand() : Shrink(); }

        private void Dress()
        {
            try
            {
                if (Parked)
                {
                    button.Tag = "shrunk";
                    button.ToolTip = "Open the window again (Ctrl+Shift+H)";
                }
                else
                {
                    button.Tag = null;
                    button.ToolTip = "Shrink to a bar so Revit can be seen (Ctrl+Shift+H)";
                }
            }
            catch (Exception) { }
        }

        private double BarHeight()
        {
            double offset;
            try { offset = header.TranslatePoint(new Point(0, 0), window).Y; }
            catch (Exception) { offset = 1.0; }
            offset = Math.Max(0.0, Math.Min(4.0, offset));
            return header.ActualHeight + 2.0 * offset;
        }

        private double CurrentHeight()
        {
            double height = window.Height;
            if (double.IsNaN(height)) height = window.ActualHeight;
            return height;
        }

        private int Stack() { return Drawers.Values.Count(d => d != this && d.Parked); }

        private void Release()
        {
            foreach (DependencyProperty prop in new[] { Window.TopProperty, Window.HeightProperty, Window.LeftProperty })
            {
                try { window.BeginAnimation(prop, null); } catch (Exception) { }
            }
        }

        private void Apply((double Left, double Top, double Height) frame)
        {
            window.Left = frame.Left;
            window.Top = frame.Top;
            window.Height = Math.Max(1.0, frame.Height);
        }

        public bool Shrink(bool instant = false)
        {
            if (Parked || Sliding) return false;
            if (owner != null && !owner.Parked)
            {
                owner.Shrink(true);
                tookOwnerDown = true;
            }
            Release();
            double height = CurrentHeight();
            restore = (window.Left, window.Top, window.Width, height);
            savedMin = window.MinHeight;
            savedSizeTo = window.SizeToContent;
            rootHeight = root.ActualHeight;
            bar = BarHeight();
            var area = McuUi.WorkArea(window);
            double top = ParkedTop(area, bar, Stack());
            double left = ClampLeft(area, window.Left, window.Width);
            window.SizeToContent = SizeToContent.Manual;
            window.MinHeight = 0;
            // pinned, so the grid is clipped by the shrinking window rather than re-measured every frame
            root.Height = rootHeight;
            root.VerticalAlignment = VerticalAlignment.Top;
            if (grips != null) grips.Visibility = Visibility.Collapsed;
            parkedAt = (left, top);
            Parked = true;
            Dress();
            Slide((window.Left, window.Top, height), (left, top, bar), LandedParked, instant);
            return true;
        }

        private void LandedParked()
        {
            hidden = new List<(UIElement, Visibility)>();
            try
            {
                foreach (UIElement child in root.Children.Cast<UIElement>().ToList())
                {
                    if (ReferenceEquals(child, header)) continue;
                    hidden.Add((child, child.Visibility));
                    child.Visibility = Visibility.Collapsed;
                }
            }
            catch (Exception) { }
            root.Height = double.NaN;
            root.VerticalAlignment = VerticalAlignment.Stretch;
            window.Height = bar;
            try
            {
                savedCorner = header.CornerRadius;
                header.CornerRadius = new CornerRadius(5);
            }
            catch (Exception) { savedCorner = null; }
        }

        public bool Expand(bool instant = false, bool activate = true)
        {
            if (!Parked || Sliding) return false;
            // only an owner this drawer took down - one the user parked stays put
            if (tookOwnerDown && owner != null && owner.Parked) owner.Expand(true, false);
            tookOwnerDown = false;
            Release();
            var nowAt = (window.Left, window.Top);
            var target = ReopenBounds(restore, parkedAt, nowAt, bar, McuUi.WorkArea(window));
            foreach (var entry in hidden)
            {
                // only what is still as the drawer left it: something shown while parked keeps its new state
                try { if (entry.Child.Visibility == Visibility.Collapsed) entry.Child.Visibility = entry.Was; }
                catch (Exception) { }
            }
            hidden = new List<(UIElement, Visibility)>();
            if (savedCorner != null)
            {
                try { header.CornerRadius = savedCorner.Value; } catch (Exception) { }
            }
            if (rootHeight > 0)
            {
                root.Height = rootHeight;
                root.VerticalAlignment = VerticalAlignment.Top;
            }
            window.Width = target.Width;
            Slide((nowAt.Left, nowAt.Top, CurrentHeight()), (target.Left, target.Top, target.Height), LandedOpen, instant);
            if (activate)
            {
                try { window.Activate(); } catch (Exception) { }
            }
            return true;
        }

        private void LandedOpen()
        {
            root.Height = double.NaN;
            root.VerticalAlignment = VerticalAlignment.Stretch;
            try { window.MinHeight = savedMin; } catch (Exception) { }
            try { window.SizeToContent = savedSizeTo; } catch (Exception) { }
            if (grips != null) grips.Visibility = Visibility.Visible;
            Parked = false;
            Dress();
        }

        private void Slide((double, double, double) from, (double, double, double) to, Action landed, bool instant)
        {
            Sliding = true;
            if (instant)
            {
                Land(to, landed);
                return;
            }
            start = from;
            end = to;
            done = landed;
            t0 = DateTime.UtcNow;
            try
            {
                timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(DrawerTickMs) };
                timer.Tick += (s, a) => Guarded("shrink to taskbar (frame)", Tick);
                timer.Start();
            }
            catch (Exception) { Land(to, landed); }
        }

        private void Tick()
        {
            try
            {
                double progress = (DateTime.UtcNow - t0).TotalSeconds / DrawerSeconds;
                if (progress >= 1.0)
                {
                    timer.Stop();
                    Land(end, done);
                    return;
                }
                Apply((Tween(start.Item1, end.Item1, progress), Tween(start.Item2, end.Item2, progress),
                       Tween(start.Item3, end.Item3, progress)));
            }
            catch (Exception)
            {
                // a frame that throws lands the window at the end state, so the drawer is never left half way
                try { timer.Stop(); } catch (Exception) { }
                Land(end, done);
            }
        }

        private void Land((double Left, double Top, double Height) to, Action landed)
        {
            try { Release(); } catch (Exception) { }
            try { Apply(to); } catch (Exception) { }
            try { landed(); } catch (Exception) { }
            Sliding = false;
        }
    }

    /// <summary>
    /// The thick bar along the bottom: percent in the bar, the stage on the left, time left and time elapsed on
    /// the right. Revit runs on the same thread as this window, so the bar can only move between API calls.
    /// </summary>
    public sealed class McuProgressBar
    {
        private readonly Window window;
        private readonly McuFinder find;
        private readonly ProgressClock clock = new ProgressClock();
        private string stage = "";
        private double? lastPaint;
        private int? lastPercent;
        private bool running;

        public McuProgressBar(Window window, McuFinder find)
        {
            this.window = window;
            this.find = find;
            try { find.Get<FrameworkElement>("ProgressTrack").SizeChanged += (s, a) => { try { PaintFill(); } catch (Exception) { } }; }
            catch (Exception) { }
        }

        public void Begin(string text)
        {
            clock.Start();
            stage = text ?? "";
            running = true;
            find["ProgressPanel"].Visibility = Visibility.Visible;
            Colour("run");
            lastPaint = null;
            Paint();
        }

        public void Update(double fraction, string text = null)
        {
            if (!running) Begin(text ?? stage);
            bool changed = false;
            if (text != null && text != stage)
            {
                stage = text;
                changed = true;
            }
            clock.Update(fraction);
            double now = clock.Now();
            int percent = clock.Percent();
            if (changed || ShouldRepaint(lastPaint, now, lastPercent, percent)) Paint();
        }

        public void Finish(string message, string state = "ok")
        {
            if (state == "fail") clock.FinishedAt = clock.Now();
            else clock.Finish();
            running = false;
            stage = message ?? "";
            Colour(state);
            Paint();
        }

        public void Hide()
        {
            running = false;
            find["ProgressPanel"].Visibility = Visibility.Collapsed;
        }

        private void Colour(string state)
        {
            string key = state == "ok" ? "GreenBrush" : state == "warn" ? "OrangeBrush" : state == "fail" ? "RedBrush" : "BlueBrush";
            find.Get<Border>("ProgressFill").SetResourceReference(Border.BackgroundProperty, key);
        }

        private void PaintFill()
        {
            var track = find.Get<FrameworkElement>("ProgressTrack");
            var fill = find.Get<Border>("ProgressFill");
            double width = track.ActualWidth * clock.Fraction;
            if (clock.Fraction > 0) width = Math.Max(width, track.ActualHeight);   // a round end needs room
            fill.Width = Math.Min(track.ActualWidth, width);
        }

        public void Paint()
        {
            try
            {
                PaintFill();
                find.Text("ProgressPercent").Text = clock.Percent() + "%";
                find.Text("ProgressStage").Text = stage;
                find.Text("ProgressEta").Text = ProgressLine(clock);
            }
            catch (Exception error) { Log("progress paint: " + FormatException(error)); }
            lastPaint = clock.Now();
            lastPercent = clock.Percent();
            McuUi.Pump(window);
        }
    }
}

