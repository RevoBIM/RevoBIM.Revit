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
using System.Windows.Shapes;
using System.Windows.Threading;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.FindInView;

using Binding = System.Windows.Data.Binding;
using Grid = System.Windows.Controls.Grid;
using Panel = System.Windows.Controls.Panel;
using TextBox = System.Windows.Controls.TextBox;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.FindInView
{
    /// <summary>Palettes. Dark is Revit's own dark, sampled from its Project Browser. Port of theme.py.</summary>
    internal static class FivTheme
    {
        private static readonly Dictionary<string, string> Dark = new Dictionary<string, string>
        {
            { "WindowBg", "#3C4454" }, { "CardBg", "#343C4A" }, { "FieldBg", "#2D3441" }, { "BarBg", "#222933" },
            { "EdgeBrush", "#4E5665" }, { "ChromeEdge", "#515C6B" }, { "TextBrush", "#EEF0F4" }, { "MutedBrush", "#A4AAB1" },
            { "BlueBrush", "#5AAEEB" }, { "OrangeBrush", "#E8912D" }, { "GreenBrush", "#3FA75A" }, { "GreenHover", "#4EC06D" },
            { "RedBrush", "#D9534F" }, { "SelectionBg", "#3A7392" }, { "HoverBg", "#444E5E" }, { "DisabledBg", "#323C48" },
            { "DisabledText", "#7B8290" },
        };

        private static readonly Dictionary<string, string> Light = new Dictionary<string, string>
        {
            { "WindowBg", "#F2F2F4" }, { "CardBg", "#FFFFFF" }, { "FieldBg", "#FFFFFF" }, { "BarBg", "#E4E4E8" },
            { "EdgeBrush", "#C6C6CC" }, { "ChromeEdge", "#B4B4BA" }, { "TextBrush", "#1F1F22" }, { "MutedBrush", "#63636A" },
            { "BlueBrush", "#1B72BE" }, { "OrangeBrush", "#B96A12" }, { "GreenBrush", "#2E8546" }, { "GreenHover", "#3FA75A" },
            { "RedBrush", "#B4302C" }, { "SelectionBg", "#BCD8F0" }, { "HoverBg", "#E8E8EC" }, { "DisabledBg", "#DEDEE2" },
            { "DisabledText", "#9A9AA0" },
        };

        /// <summary>Writes every palette brush onto the window's own resources, which sit in front of the merged Theme.xaml.</summary>
        public static void Apply(Window window, string name)
        {
            foreach (KeyValuePair<string, string> entry in name == "light" ? Light : Dark)
            {
                try
                {
                    window.Resources[entry.Key] = new SolidColorBrush((Color)ColorConverter.ConvertFromString(entry.Value));
                }
                catch (Exception)
                {
                }
            }
        }
    }

    /// <summary>Loads the pyRevit XAML layouts, unchanged, from the embedded copies in UI\FindInView\Layouts.</summary>
    internal static class FivXaml
    {
        private const string LayoutPrefix = "RevoBIM.UI.FindInView.Layouts.";
        private const string IconName = "RevoBIM.Resources.FindInView.icon.png";

        public static string ReadLayout(string file)
        {
            using (Stream stream = typeof(FivXaml).Assembly.GetManifestResourceStream(LayoutPrefix + file))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + file + " was not found");
                using (var reader = new StreamReader(stream, System.Text.Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        /// <summary>
        /// Parses a layout, merges Theme.xaml into it, then writes the palette on top. Theme.xaml is merged
        /// AFTER the layout has been parsed, which is why a layout may only ever use DynamicResource.
        /// </summary>
        public static Window LoadWindow(string file, string palette)
        {
            var window = XamlReader.Parse(ReadLayout(file)) as Window;
            if (window == null) throw new InvalidCastException(file + " is not a Window");
            var dictionary = XamlReader.Parse(ReadLayout("Theme.xaml")) as ResourceDictionary;
            if (dictionary == null) throw new InvalidCastException("Theme.xaml did not parse as a ResourceDictionary");
            window.Resources.MergedDictionaries.Add(dictionary);
            FivTheme.Apply(window, palette);
            return window;
        }

        /// <summary>Decorative: any failure is swallowed, cosmetics can never take a tool down.</summary>
        public static void LoadIcon(Image image)
        {
            try
            {
                using (Stream stream = typeof(FivXaml).Assembly.GetManifestResourceStream(IconName))
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
    }

    /// <summary>Theme choice, ownership, the clipboard and the message window.</summary>
    internal static class FivUi
    {
        /// <summary>"dark", "light", or null where Revit will not say. The canvas is asked first, the ribbon theme second.</summary>
        public static string RevitTheme()
        {
            try
            {
                return UIThemeManager.CurrentCanvasTheme == UITheme.Dark ? "dark" : "light";
            }
            catch (Exception)
            {
            }
            try
            {
                return UIThemeManager.CurrentTheme == UITheme.Dark ? "dark" : "light";
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static string PaletteFor(Dictionary<string, string> settings)
        {
            return FivCore.ResolvePalette(FivCore.Get(settings, "theme_mode"), RevitTheme());
        }

        /// <summary>Owned windows float above Revit instead of slipping behind it.</summary>
        public static bool OwnToRevit(Window window, UIApplication uiapp)
        {
            try
            {
                new WindowInteropHelper(window).Owner = uiapp.MainWindowHandle;
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Puts text on the clipboard; false when it could not be. Another program can hold the clipboard for a moment.</summary>
        public static bool CopyText(string text, int attempts = 3)
        {
            for (int i = 0; i < attempts; i++)
            {
                try
                {
                    Clipboard.SetDataObject(text, true);
                    return true;
                }
                catch (Exception)
                {
                    System.Threading.Thread.Sleep(50);
                }
            }
            return false;
        }

        /// <summary>Ctrl+Shift+H, the shortcut the whole suite uses for the shrink.</summary>
        public static bool IsShrinkKey(KeyEventArgs args)
        {
            return args.Key == Key.H && (Keyboard.Modifiers & (ModifierKeys.Control | ModifierKeys.Shift)) == (ModifierKeys.Control | ModifierKeys.Shift);
        }

        /// <summary>Themed message or Yes/No confirm. Any failure falls back to Revit's own TaskDialog.</summary>
        public static bool Message(string text, string palette, UIApplication uiapp, bool confirm = false, string title = null,
                                   Window ownerWindow = null)
        {
            try
            {
                Window window = FivXaml.LoadWindow("FindInViewMessage.xaml", palette);
                var icon = (Image)window.FindName("HeaderIcon");
                FivXaml.LoadIcon(icon);
                EggHook.Attach(window, () => palette, icon);
                ((TextBlock)window.FindName("MessageText")).Text = text;
                var header = (Border)window.FindName("HeaderBar");
                var chrome = new FivChrome(window, header);
                chrome.Drawer = new FivDrawer(window, header, (Panel)window.FindName("RootGrid"), (Button)window.FindName("ShrinkBtn"),
                                              (UIElement)window.FindName("PathShrink"), (UIElement)window.FindName("PathExpand"),
                                              (Border)window.FindName("RootBorder"), null);
                ((TextBlock)window.FindName("VersionText")).Text = "v" + FivCore.Version;
                if (!string.IsNullOrEmpty(title)) ((TextBlock)window.FindName("TitleTool")).Text = title;

                bool result = false;
                var ok = (Button)window.FindName("OkBtn");
                var no = (Button)window.FindName("NoBtn");
                if (confirm)
                {
                    ok.Content = "Yes";
                    no.Visibility = Visibility.Visible;
                }
                Action sayYes = () => { result = true; window.Close(); };
                Action sayNo = () => { result = false; window.Close(); };
                ok.Click += (s, a) => sayYes();
                no.Click += (s, a) => sayNo();
                ((Button)window.FindName("CloseBtn")).Click += (s, a) => sayNo();

                window.PreviewKeyDown += (s, args) =>
                {
                    if (chrome.Drawer.Shrunk)
                    {
                        // a key press must not answer a prompt that is out of sight
                        if (args.Key == Key.Escape || args.Key == Key.Enter || args.Key == Key.F11)
                        {
                            chrome.Drawer.Expand();
                            args.Handled = true;
                        }
                        return;
                    }
                    if (IsShrinkKey(args))
                    {
                        chrome.Drawer.Toggle();
                        args.Handled = true;
                    }
                    else if (args.Key == Key.Escape) sayNo();
                    else if (args.Key == Key.Enter) sayYes();
                };

                bool owned = false;
                if (ownerWindow != null)
                {
                    // a confirm raised from the tool's own modal window belongs to that window, or it can
                    // open behind it and read as a hang
                    try
                    {
                        window.Owner = ownerWindow;
                        owned = true;
                    }
                    catch (Exception)
                    {
                        owned = false;
                    }
                }
                if (!owned && uiapp != null) OwnToRevit(window, uiapp);
                window.ShowDialog();
                return result;
            }
            catch (Exception err)
            {
                FivLog.Write("message: themed window failed (" + err.Message + "), used a TaskDialog");
                return TaskDialogFallback(text, confirm);
            }
        }

        private static bool TaskDialogFallback(string text, bool confirm)
        {
            try
            {
                var dialog = new TaskDialog("RevoBIM " + FivCore.ToolName)
                {
                    MainInstruction = FivCore.ToolName,
                    MainContent = text,
                };
                if (confirm)
                {
                    dialog.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No;
                    return dialog.Show() == TaskDialogResult.Yes;
                }
                dialog.Show();
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }
    }

    /// <summary>
    /// The shrink drawer every window carries. Top and Height are eased by hand on a timer (a Storyboard on a
    /// borderless window's Top and Height fights the layout pass, and one that is never released leaves a
    /// window that can never be moved again). Port of WindowDrawer in fiv_ui.py.
    /// </summary>
    internal sealed class FivDrawer
    {
        // every drawer alive, so two parked bars do not land on top of each other
        private static readonly List<FivDrawer> Parked = new List<FivDrawer>();

        private readonly Window window;
        private readonly Border header;
        private readonly Panel root;
        private readonly Button button;
        private readonly UIElement shrinkPath;
        private readonly UIElement expandPath;
        private readonly Border shell;
        private readonly UIElement grips;

        private int slot;
        private DispatcherTimer timer;
        private double[] saved;   // left, top, width, height, minHeight
        private SizeToContent savedSize;
        private ResizeMode savedResize;
        private Dictionary<UIElement, Visibility> wasVisible = new Dictionary<UIElement, Visibility>();

        public bool Shrunk;
        public bool Sliding;

        public FivDrawer(Window window, Border header, Panel root, Button button, UIElement shrinkPath,
                         UIElement expandPath, Border shell, UIElement grips)
        {
            this.window = window;
            this.header = header;
            this.root = root;
            this.button = button;
            this.shrinkPath = shrinkPath;
            this.expandPath = expandPath;
            this.shell = shell;
            this.grips = grips;
            if (button != null) button.Click += (s, a) => Toggle();
        }

        public void Toggle()
        {
            if (Sliding) return;
            if (Shrunk) Expand();
            else Shrink();
        }

        /// <summary>(top, height) of the working area of the screen the window is on, in WPF units. Top is signed.</summary>
        private void ScreenArea(out double top, out double height)
        {
            try
            {
                var helper = new WindowInteropHelper(window);
                System.Drawing.Rectangle bounds = System.Windows.Forms.Screen.FromHandle(helper.Handle).WorkingArea;
                double scale = 1.0;
                PresentationSource source = PresentationSource.FromVisual(window);
                if (source != null && source.CompositionTarget != null && source.CompositionTarget.TransformToDevice.M22 != 0)
                    scale = source.CompositionTarget.TransformToDevice.M22;
                top = bounds.Y / scale;
                height = bounds.Height / scale;
            }
            catch (Exception)
            {
                top = 0.0;
                height = SystemParameters.WorkArea.Height;
            }
        }

        private double Bar()
        {
            double offset = 7.0;
            try
            {
                offset = Math.Max(0.0, header.TranslatePoint(new Point(0, 0), window).Y);
            }
            catch (Exception)
            {
            }
            double height = 0.0;
            try
            {
                height = header.ActualHeight;
            }
            catch (Exception)
            {
            }
            return FivCore.BarHeight(height, offset);
        }

        private void Animate(double topTo, double heightTo, Action done)
        {
            double topFrom = topTo, heightFrom = heightTo;
            try
            {
                topFrom = window.Top;
                heightFrom = window.Height;
            }
            catch (Exception)
            {
            }

            double elapsed = 0.0;
            Sliding = true;
            var local = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(FivCore.DrawerTickMs) };
            timer = local;

            Action land = () =>
            {
                try
                {
                    local.Stop();
                }
                catch (Exception)
                {
                }
                timer = null;
                Sliding = false;
                try
                {
                    window.Top = topTo;
                    window.Height = heightTo;
                }
                catch (Exception)
                {
                }
                try
                {
                    done();
                }
                catch (Exception)
                {
                }
            };

            local.Tick += (s, a) =>
            {
                // a frame that throws still has to land the window, or it is left half shut with no way back
                try
                {
                    elapsed += FivCore.DrawerTickMs;
                    double progress = elapsed / FivCore.DrawerMs;
                    if (progress >= 1.0)
                    {
                        land();
                        return;
                    }
                    window.Top = FivCore.DrawerFrame(topFrom, topTo, progress);
                    window.Height = FivCore.DrawerFrame(heightFrom, heightTo, progress);
                }
                catch (Exception)
                {
                    land();
                }
            };
            try
            {
                local.Start();
            }
            catch (Exception)
            {
                land();
            }
        }

        public void Shrink()
        {
            if (Shrunk || Sliding) return;
            // A window sized to its content has Height = NaN until something sets it
            try
            {
                if (double.IsNaN(window.Height)) window.Height = window.ActualHeight;
            }
            catch (Exception)
            {
            }
            try
            {
                saved = new[] { window.Left, window.Top, window.Width, window.Height, window.MinHeight };
                savedSize = window.SizeToContent;
                savedResize = window.ResizeMode;
            }
            catch (Exception)
            {
                return;
            }
            if (double.IsNaN(saved[3]) || saved[3] <= 0) return;

            // MinHeight and SizeToContent both veto a Height change, and a vetoed one leaves the window half shut
            try
            {
                window.MinHeight = 0;
                window.SizeToContent = SizeToContent.Manual;
                window.ResizeMode = ResizeMode.NoResize;
            }
            catch (Exception)
            {
            }
            // pin the body, or the grid re-measures on every frame
            try
            {
                root.Height = root.ActualHeight;
                root.VerticalAlignment = VerticalAlignment.Top;
            }
            catch (Exception)
            {
            }
            try
            {
                if (shell != null) shell.ClipToBounds = true;
            }
            catch (Exception)
            {
            }

            double bar = Bar();
            double areaTop, areaHeight;
            ScreenArea(out areaTop, out areaHeight);
            var taken = new List<int>();
            foreach (FivDrawer other in Parked) taken.Add(other.slot);
            slot = FivCore.FreeSlot(taken);
            if (!Parked.Contains(this)) Parked.Add(this);
            double target = FivCore.ShrunkTop(areaTop, areaHeight, bar, slot);
            Shrunk = true;
            SetGlyph(true);
            Animate(target, bar, Landed);
        }

        /// <summary>Hide the body only once the bar is down.</summary>
        private void Landed()
        {
            wasVisible = new Dictionary<UIElement, Visibility>();
            foreach (UIElement child in root.Children)
            {
                if (ReferenceEquals(child, header)) continue;
                try
                {
                    wasVisible[child] = child.Visibility;
                    child.Visibility = Visibility.Collapsed;   // a panel already hidden stays hidden when it comes back
                }
                catch (Exception)
                {
                }
            }
            ParkGrips(true);
            try
            {
                header.CornerRadius = new CornerRadius(5);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>The grip overlay spans every row, so left visible it lines the bar with invisible drag handles.</summary>
        private void ParkGrips(bool parked)
        {
            if (grips == null) return;
            try
            {
                grips.Visibility = parked ? Visibility.Collapsed : Visibility.Visible;
                grips.IsHitTestVisible = !parked;
            }
            catch (Exception)
            {
            }
        }

        public void Expand()
        {
            if (!Shrunk || Sliding || saved == null) return;
            double left = saved[0], height = saved[3], minHeight = saved[4];

            // show the body before the slide back, not after
            foreach (var entry in wasVisible)
            {
                try
                {
                    entry.Key.Visibility = entry.Value;
                }
                catch (Exception)
                {
                }
            }
            wasVisible = new Dictionary<UIElement, Visibility>();
            try
            {
                header.CornerRadius = new CornerRadius(5, 5, 0, 0);
            }
            catch (Exception)
            {
            }

            double bar = Bar();
            double areaTop, areaHeight;
            ScreenArea(out areaTop, out areaHeight);
            double parkedTop = saved[1];
            try
            {
                parkedTop = window.Top;
            }
            catch (Exception)
            {
            }
            double targetTop = FivCore.ExpandTop(parkedTop, height, bar, areaTop, areaHeight);
            try
            {
                window.Left = left;
            }
            catch (Exception)
            {
            }

            Shrunk = false;
            SetGlyph(false);
            Parked.Remove(this);

            Animate(targetTop, height, () =>
            {
                // unpin, and put back everything the slide had to relax
                try
                {
                    root.Height = double.NaN;
                    root.VerticalAlignment = VerticalAlignment.Stretch;
                }
                catch (Exception)
                {
                }
                try
                {
                    window.MinHeight = minHeight;
                    window.SizeToContent = savedSize;
                    window.ResizeMode = savedResize;
                }
                catch (Exception)
                {
                }
                ParkGrips(false);
                try
                {
                    window.Activate();
                }
                catch (Exception)
                {
                }
            });
        }

        /// <summary>Puts the window back with no slide, for closing while parked.</summary>
        public void RestoreNow()
        {
            if (!Shrunk || saved == null) return;
            foreach (var entry in wasVisible)
            {
                try
                {
                    entry.Key.Visibility = entry.Value;
                }
                catch (Exception)
                {
                }
            }
            try
            {
                root.Height = double.NaN;
                root.VerticalAlignment = VerticalAlignment.Stretch;
                window.MinHeight = saved[4];
                window.SizeToContent = savedSize;
                window.ResizeMode = savedResize;
                window.Left = saved[0];
                window.Top = saved[1];
                window.Width = saved[2];
                window.Height = saved[3];
            }
            catch (Exception)
            {
            }
            ParkGrips(false);
            Shrunk = false;
            SetGlyph(false);
            Parked.Remove(this);
        }

        /// <summary>The real height while parked, so closing shrunk saves a size worth reopening at rather than a 60 pixel bar.</summary>
        public double TrueHeight()
        {
            if (Shrunk && saved != null) return saved[3];
            try
            {
                return window.Height;
            }
            catch (Exception)
            {
                return 0.0;
            }
        }

        private void SetGlyph(bool parked)
        {
            try
            {
                if (shrinkPath != null) shrinkPath.Visibility = parked ? Visibility.Collapsed : Visibility.Visible;
                if (expandPath != null) expandPath.Visibility = parked ? Visibility.Visible : Visibility.Collapsed;
            }
            catch (Exception)
            {
            }
            try
            {
                button.Tag = parked ? "shrunk" : "";
                button.ToolTip = parked ? "Open the window again (Ctrl+Shift+H)"
                                        : "Shrink to the taskbar so Revit can be seen (Ctrl+Shift+H)";
            }
            catch (Exception)
            {
            }
        }
    }

    /// <summary>Dragging, the resize grips and full screen, for a borderless window. Port of Chrome in fiv_ui.py.</summary>
    internal sealed class FivChrome
    {
        private readonly Window window;
        private double[] saved;

        public FivDrawer Drawer;
        public bool FullScreen;

        public FivChrome(Window window, FrameworkElement header)
        {
            this.window = window;
            header.MouseLeftButtonDown += OnHeaderDown;
        }

        private void OnHeaderDown(object sender, MouseButtonEventArgs args)
        {
            try
            {
                // while parked, a double click opens the window and a single click drags the bar - it must
                // never maximise something nobody can see
                if (Drawer != null && Drawer.Shrunk)
                {
                    if (args.ClickCount == 2) Drawer.Expand();
                    else window.DragMove();
                    return;
                }
                if (args.ClickCount == 2)
                {
                    ToggleFullScreen();
                    return;
                }
                if (FullScreen) ToggleFullScreen();
                window.DragMove();
            }
            catch (Exception)
            {
            }
        }

        /// <summary>names are N/S/E/W/NE/NW/SE/SW.</summary>
        public void AttachGrips(Dictionary<string, Thumb> grips)
        {
            foreach (var entry in grips)
            {
                if (entry.Value == null) continue;
                string name = entry.Key;
                entry.Value.DragDelta += (s, a) => Grip(name, a);
            }
        }

        private void Grip(string name, DragDeltaEventArgs args)
        {
            try
            {
                if (FullScreen) return;
                double h = args.HorizontalChange, v = args.VerticalChange;
                if (name.Contains("W"))
                {
                    double width = window.Width - h;
                    if (width >= window.MinWidth)
                    {
                        window.Left = window.Left + h;
                        window.Width = width;
                    }
                }
                if (name.Contains("E"))
                {
                    double width = window.Width + h;
                    if (width >= window.MinWidth) window.Width = width;
                }
                if (name.Contains("N"))
                {
                    double height = window.Height - v;
                    if (height >= window.MinHeight)
                    {
                        window.Top = window.Top + v;
                        window.Height = height;
                    }
                }
                if (name.Contains("S"))
                {
                    double height = window.Height + v;
                    if (height >= window.MinHeight) window.Height = height;
                }
            }
            catch (Exception)
            {
            }
        }

        public bool ToggleFullScreen()
        {
            // filling the screen with a window that is parked out of sight helps nobody: open it instead
            if (Drawer != null && Drawer.Shrunk)
            {
                Drawer.Expand();
                return false;
            }
            try
            {
                if (FullScreen)
                {
                    if (saved != null)
                    {
                        window.Left = saved[0];
                        window.Top = saved[1];
                        window.Width = saved[2];
                        window.Height = saved[3];
                    }
                    FullScreen = false;
                    return false;
                }
                saved = new[] { window.Left, window.Top, window.Width, window.Height };
                double[] area = WorkingArea();
                if (area != null)
                {
                    window.Left = area[0];
                    window.Top = area[1];
                    window.Width = area[2];
                    window.Height = area[3];
                }
                FullScreen = true;
                return true;
            }
            catch (Exception)
            {
                return FullScreen;
            }
        }

        /// <summary>
        /// Bounds, not WindowState.Maximized: maximising a borderless AllowsTransparency window covers the
        /// task bar and lands on the wrong monitor. The area is in device pixels, so it is divided by the DPI scale.
        /// </summary>
        private double[] WorkingArea()
        {
            try
            {
                var helper = new WindowInteropHelper(window);
                System.Drawing.Rectangle bounds = System.Windows.Forms.Screen.FromHandle(helper.Handle).WorkingArea;
                double sx = 1.0, sy = 1.0;
                PresentationSource source = PresentationSource.FromVisual(window);
                if (source != null && source.CompositionTarget != null)
                {
                    Matrix m = source.CompositionTarget.TransformToDevice;
                    if (m.M11 != 0) sx = m.M11;
                    if (m.M22 != 0) sy = m.M22;
                }
                return new[] { bounds.X / sx, bounds.Y / sy, bounds.Width / sx, bounds.Height / sy };
            }
            catch (Exception)
            {
                Rect area = SystemParameters.WorkArea;
                return new[] { 0.0, 0.0, area.Width, area.Height };
            }
        }
    }
}
