using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.BulkRename;

namespace RevoBIM.UI.BulkRename
{
    /// <summary>
    /// Palettes. Dark is Revit's own dark, sampled from its Project Browser. Port of brn_theme.py.
    /// </summary>
    internal static class BrnTheme
    {
        private static readonly Dictionary<string, string> Dark = new Dictionary<string, string>
        {
            { "Title", "#222933" }, { "Window", "#3C4454" }, { "Field", "#2D3441" },
            { "Card", "#323C48" }, { "Hover", "#444E5E" }, { "Selection", "#3A7392" },
            { "Edge", "#515C6B" }, { "Text", "#EEF0F4" }, { "Muted", "#A4AAB1" },
            { "Blue", "#5AAEEB" }, { "Orange", "#F0A040" }, { "Green", "#3FA75A" },
            { "GreenHover", "#4EC06D" }, { "Red", "#F07A76" }, { "OnAccent", "#FFFFFF" },
        };

        private static readonly Dictionary<string, string> Light = new Dictionary<string, string>
        {
            { "Title", "#E4E7EB" }, { "Window", "#F3F4F6" }, { "Field", "#FFFFFF" },
            { "Card", "#FFFFFF" }, { "Hover", "#E1E5EA" }, { "Selection", "#BBDDF3" },
            { "Edge", "#C4C9D0" }, { "Text", "#1E2227" }, { "Muted", "#5C6570" },
            { "Blue", "#1B72BE" }, { "Orange", "#B96A12" }, { "Green", "#2E8546" },
            { "GreenHover", "#37995A" }, { "Red", "#C73A36" }, { "OnAccent", "#FFFFFF" },
        };

        public static Dictionary<string, string> Palette(string name)
        {
            return name == "light" ? Light : Dark;
        }
    }

    /// <summary>
    /// Loads the pyRevit XAML layouts, unchanged, from the embedded copies in UI\BulkRename\Layouts.
    /// </summary>
    internal static class BrnXaml
    {
        private const string LayoutPrefix = "RevoBIM.UI.BulkRename.Layouts.";
        private const string IconName = "RevoBIM.Resources.BulkRename.icon.png";

        public static string ReadLayout(string file)
        {
            using (Stream stream = typeof(BrnXaml).Assembly.GetManifestResourceStream(LayoutPrefix + file))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + file + " was not found");
                using (var reader = new StreamReader(stream, System.Text.Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        public static T Load<T>(string file) where T : class
        {
            T loaded = XamlReader.Parse(ReadLayout(file)) as T;
            if (loaded == null) throw new InvalidCastException(file + " is not a " + typeof(T).Name);
            return loaded;
        }

        public static BitmapImage Logo()
        {
            using (Stream stream = typeof(BrnXaml).Assembly.GetManifestResourceStream(IconName))
            {
                if (stream == null) return null;
                var image = new BitmapImage();
                image.BeginInit();
                image.StreamSource = stream;
                image.CacheOption = BitmapCacheOption.OnLoad;
                image.EndInit();
                image.Freeze();
                return image;
            }
        }
    }

    /// <summary>
    /// Shrink to taskbar. Top is eased by hand on a timer, so no animation is left holding the window, and
    /// the window is cut to the bar only once it has landed. Port of brn_drawer.py.
    /// </summary>
    internal sealed class BrnDrawer
    {
        private static readonly List<BrnDrawer> Slots = new List<BrnDrawer>();
        private const double Frame = 2.0;

        private readonly Window window;
        private readonly FrameworkElement header;
        private readonly FrameworkElement root;
        private readonly UIElement shrinkGlyph;
        private readonly UIElement expandGlyph;
        private readonly UIElement grips;
        private readonly Func<Rect4> workArea;
        private readonly Stopwatch clock = new Stopwatch();

        private Rect4 saved;
        private double relaxedMinHeight;
        private SizeToContent relaxedSize;
        private List<KeyValuePair<UIElement, Visibility>> hidden = new List<KeyValuePair<UIElement, Visibility>>();
        private DispatcherTimer timer;
        private double parkedLeft, parkedTop;
        private int slot = -1;

        public BrnDrawer Owner;
        public bool Parked;
        public bool Sliding;

        public BrnDrawer(Window window, FrameworkElement header, FrameworkElement root, UIElement shrinkGlyph,
                         UIElement expandGlyph, UIElement grips, Func<Rect4> workArea)
        {
            this.window = window;
            this.header = header;
            this.root = root;
            this.shrinkGlyph = shrinkGlyph;
            this.expandGlyph = expandGlyph;
            this.grips = grips;
            this.workArea = workArea;
        }

        private double BarHeight()
        {
            return header.ActualHeight + 2 * Frame;
        }

        private double StackBelow()
        {
            double total = 0;
            for (int i = 0; i < slot && i < Slots.Count; i++)
            {
                if (Slots[i] != null) total += Slots[i].BarHeight() + BrnCore.StackGap;
            }
            return total;
        }

        public void Toggle()
        {
            if (Sliding) return;
            if (Parked) Expand();
            else Shrink();
        }

        // ---------- going down ----------
        public void Shrink(bool animate = true)
        {
            if (Parked || Sliding) return;
            if (Owner != null) Owner.Shrink(false);
            saved = new Rect4(window.Left, window.Top, window.ActualWidth, window.ActualHeight);
            relaxedMinHeight = window.MinHeight;
            relaxedSize = window.SizeToContent;
            window.SizeToContent = SizeToContent.Manual;
            window.Height = saved.Height;
            window.MinHeight = 0;
            root.Height = saved.Height;
            root.VerticalAlignment = VerticalAlignment.Top;
            grips.Visibility = Visibility.Collapsed;
            slot = BrnCore.FreeSlot(Slots);
            if (slot == Slots.Count) Slots.Add(this);
            else Slots[slot] = this;
            Rect4 area = workArea();
            double target = BrnCore.ParkedTop(area.Top, area.Height, BarHeight(), StackBelow());
            Slide(window.Top, target, Landed, animate);
        }

        private void Landed()
        {
            Parked = true;
            var parent = header.Parent as Panel;
            hidden = new List<KeyValuePair<UIElement, Visibility>>();
            if (parent != null)
            {
                foreach (UIElement child in parent.Children)
                {
                    if (ReferenceEquals(child, header)) continue;
                    hidden.Add(new KeyValuePair<UIElement, Visibility>(child, child.Visibility));
                    child.Visibility = Visibility.Collapsed;
                }
            }
            window.Height = BarHeight();
            root.Height = double.NaN;
            root.VerticalAlignment = VerticalAlignment.Stretch;
            parkedLeft = window.Left;
            parkedTop = window.Top;
            shrinkGlyph.Visibility = Visibility.Collapsed;
            expandGlyph.Visibility = Visibility.Visible;
        }

        // ---------- coming back ----------
        public void Expand(bool animate = true)
        {
            if (!Parked || Sliding) return;
            Tuple<double, double> target = BrnCore.ExpandRect(saved, window.Left, window.Top, parkedLeft, parkedTop, workArea());
            foreach (KeyValuePair<UIElement, Visibility> entry in hidden) entry.Key.Visibility = entry.Value;
            hidden = new List<KeyValuePair<UIElement, Visibility>>();
            window.Height = saved.Height;
            window.Left = target.Item1;
            Parked = false;
            shrinkGlyph.Visibility = Visibility.Visible;
            expandGlyph.Visibility = Visibility.Collapsed;
            if (slot >= 0 && slot < Slots.Count) Slots[slot] = null;
            slot = -1;
            Slide(window.Top, target.Item2, Opened, animate);
        }

        private void Opened()
        {
            window.MinHeight = relaxedMinHeight;
            window.SizeToContent = relaxedSize;
            grips.Visibility = Visibility.Visible;
            if (Owner != null) Owner.Expand(false);
        }

        /// <summary>Closing while parked: free the slot and bring the owner back.</summary>
        public void Settle()
        {
            if (slot >= 0 && slot < Slots.Count) Slots[slot] = null;
            slot = -1;
            if (Owner != null) Owner.Expand(false);
        }

        // ---------- the slide ----------
        private void Slide(double start, double end, Action done, bool animate)
        {
            if (!animate)
            {
                window.Top = end;
                done();
                return;
            }
            Sliding = true;
            clock.Restart();
            bool finished = false;

            Action finish = () =>
            {
                if (finished) return;
                finished = true;
                try
                {
                    timer.Stop();
                }
                catch (Exception)
                {
                }
                Sliding = false;
                window.Top = end;
                done();
            };

            try
            {
                timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(BrnCore.TickMs) };
                timer.Tick += (sender, args) =>
                {
                    try
                    {
                        double progress = clock.Elapsed.TotalSeconds / BrnCore.SlideSeconds;
                        if (progress >= 1) finish();
                        else window.Top = start + (end - start) * BrnCore.Ease(progress);
                    }
                    catch (Exception)
                    {
                        finish();
                    }
                };
                timer.Start();
            }
            catch (Exception)
            {
                finish();
            }
        }
    }

    /// <summary>
    /// The house chrome every Bulk Rename window is built on: themed, draggable, resizable by its grips,
    /// shrinkable to the taskbar. Port of brn_chrome.py.
    /// </summary>
    internal abstract class BrnThemedWindow
    {
        private static readonly string[] GripNames = { "GripL", "GripR", "GripT", "GripB", "GripTL", "GripTR", "GripBL", "GripBR" };
        private static readonly string[] GripEdges = { "L", "R", "T", "B", "TL", "TR", "BL", "BR" };

        protected readonly UIApplication Uiapp;
        protected readonly Dictionary<string, string> Settings;
        protected readonly BrnLog Log;
        internal readonly BrnThemedWindow OwnerWindow;
        internal readonly Window Win;
        internal readonly BrnDrawer Drawer;

        protected readonly FrameworkElement Root;
        protected readonly FrameworkElement Header;
        protected readonly Image Logo;
        protected readonly Button ThemeChip;
        protected readonly TextBlock ThemeLabel;
        protected readonly FrameworkElement Grips;
        protected readonly Button ShrinkBtn;
        protected readonly Button FullBtn;
        protected readonly Button CloseBtn;

        protected Rect4? FullBounds;
        protected string ThemeName;
        private string themeMode;

        protected BrnThemedWindow(UIApplication uiapp, Dictionary<string, string> settings, BrnLog log,
                                  string layout, BrnThemedWindow owner = null)
        {
            Uiapp = uiapp;
            Settings = settings;
            Log = log;
            OwnerWindow = owner;
            Win = BrnXaml.Load<Window>(layout);
            Win.Resources.MergedDictionaries.Add(BrnXaml.Load<ResourceDictionary>("Theme.xaml"));
            Root = (FrameworkElement)Win.FindName("Root");
            Header = (FrameworkElement)Win.FindName("Header");
            Logo = (Image)Win.FindName("Logo");
            ThemeChip = (Button)Win.FindName("ThemeChip");
            ThemeLabel = (TextBlock)Win.FindName("ThemeLabel");
            Grips = (FrameworkElement)Win.FindName("Grips");
            ShrinkBtn = (Button)Win.FindName("ShrinkBtn");
            FullBtn = (Button)Win.FindName("FullBtn");
            CloseBtn = (Button)Win.FindName("CloseBtn");
            ((TextBlock)Win.FindName("VersionText")).Text = "v" + BrnCore.Version;
            Drawer = new BrnDrawer(Win, Header, Root, (UIElement)Win.FindName("ShrinkGlyph"),
                                   (UIElement)Win.FindName("ExpandGlyph"), Grips, WorkArea);
            if (owner != null) Drawer.Owner = owner.Drawer;
            Wire();
            ApplyTheme();
            try
            {
                Logo.Source = BrnXaml.Logo();
            }
            catch (Exception err)
            {
                Log.Write("logo: " + err.Message);
            }
        }

        // ---------- plumbing ----------

        /// <summary>Runs a handler body so that an error is logged, never thrown into WPF.</summary>
        protected void Guard(string name, Action action)
        {
            try
            {
                action();
            }
            catch (Exception err)
            {
                Log.Write(name + ": " + err.Message);
            }
        }

        private void Wire()
        {
            Header.MouseLeftButtonDown += (s, a) => Guard("header", () => OnHeaderDown(a));
            ThemeChip.Click += (s, a) => Guard("theme", OnThemeChip);
            ShrinkBtn.Click += (s, a) => Guard("shrink", Drawer.Toggle);
            FullBtn.Click += (s, a) => Guard("full", ToggleFull);
            CloseBtn.Click += (s, a) => Guard("close", RequestClose);
            Win.PreviewKeyDown += (s, a) => Guard("key", () => OnKey(a));
            Win.Activated += (s, a) => Guard("activated", ApplyTheme);
            Win.Closed += (s, a) => Guard("closed", OnClosed);
            for (int i = 0; i < GripNames.Length; i++)
            {
                string edge = GripEdges[i];
                var grip = (Thumb)Win.FindName(GripNames[i]);
                grip.DragDelta += (s, a) => Guard("grip", () => OnGrip(edge, a));
            }
        }

        private void OnGrip(string edge, DragDeltaEventArgs args)
        {
            Rect4 rect = BrnCore.Resize(new Rect4(Win.Left, Win.Top, Win.ActualWidth, Win.ActualHeight),
                                        edge, args.HorizontalChange, args.VerticalChange, Win.MinWidth, Win.MinHeight);
            Win.SizeToContent = SizeToContent.Manual;
            Win.Left = rect.Left;
            Win.Top = rect.Top;
            Win.Width = rect.Width;
            Win.Height = rect.Height;
            FullBounds = null;
        }

        // ---------- theme ----------

        /// <summary>Revit's canvas. UIThemeManager.CurrentCanvasTheme, else the background colour it reports.</summary>
        private string CanvasTheme()
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
                var colour = Uiapp.Application.BackgroundColor;
                return BrnCore.CanvasFromRgb(colour.Red, colour.Green, colour.Blue);
            }
            catch (Exception)
            {
                return "dark";
            }
        }

        protected void ApplyTheme()
        {
            string mode;
            if (!Settings.TryGetValue("theme", out mode)) mode = "auto";
            string name = BrnCore.ResolveTheme(mode, CanvasTheme());
            if (name == ThemeName && mode == themeMode) return;
            ThemeName = name;
            themeMode = mode;
            foreach (KeyValuePair<string, string> entry in BrnTheme.Palette(name))
                Win.Resources[entry.Key] = new SolidColorBrush((Color)ColorConverter.ConvertFromString(entry.Value));
            ThemeLabel.Text = mode == "dark" ? "Dark" : mode == "light" ? "Light" : "Auto";
        }

        private void OnThemeChip()
        {
            string mode;
            if (!Settings.TryGetValue("theme", out mode)) mode = "auto";
            Settings["theme"] = BrnCore.NextTheme(mode);
            BrnCore.SaveSettings(Settings);
            ApplyTheme();
        }

        // ---------- header, keys ----------
        private void OnHeaderDown(MouseButtonEventArgs args)
        {
            if (args.ClickCount == 2)
            {
                if (Drawer.Parked) Drawer.Expand();
                else ToggleFull();
                return;
            }
            double left = Win.Left, top = Win.Top;
            try
            {
                Win.DragMove();
            }
            catch (Exception)
            {
            }
            if (left != Win.Left || top != Win.Top) FullBounds = null;
        }

        private void OnKey(KeyEventArgs args)
        {
            Key key = args.Key == Key.System ? args.SystemKey : args.Key;
            if (key == Key.H && Keyboard.Modifiers == (ModifierKeys.Control | ModifierKeys.Shift))
            {
                Drawer.Toggle();
                args.Handled = true;
            }
            else if (Drawer.Parked)
            {
                if (key == Key.Escape || key == Key.Enter || key == Key.F11) Drawer.Expand();
                args.Handled = true;
            }
            else if (key == Key.F11)
            {
                ToggleFull();
                args.Handled = true;
            }
            else if (key == Key.Escape)
            {
                RequestClose();
                args.Handled = true;
            }
        }

        // ---------- size ----------
        private double DpiScale()
        {
            try
            {
                PresentationSource source = PresentationSource.FromVisual(Win);
                return source.CompositionTarget.TransformToDevice.M11;
            }
            catch (Exception)
            {
                return 1.0;
            }
        }

        /// <summary>The working area of the screen the window is on, in WPF units.</summary>
        protected Rect4 WorkArea()
        {
            try
            {
                IntPtr handle = new WindowInteropHelper(Win).Handle;
                System.Drawing.Rectangle area = System.Windows.Forms.Screen.FromHandle(handle).WorkingArea;
                double scale = DpiScale();
                return new Rect4(area.Left / scale, area.Top / scale, area.Width / scale, area.Height / scale);
            }
            catch (Exception)
            {
                Rect area = SystemParameters.WorkArea;
                return new Rect4(area.Left, area.Top, area.Width, area.Height);
            }
        }

        private void ToggleFull()
        {
            if (Drawer.Parked)
            {
                Drawer.Expand();
                return;
            }
            Win.SizeToContent = SizeToContent.Manual;
            Rect4 bounds;
            if (FullBounds.HasValue)
            {
                bounds = FullBounds.Value;
                FullBounds = null;
            }
            else
            {
                FullBounds = new Rect4(Win.Left, Win.Top, Win.ActualWidth, Win.ActualHeight);
                bounds = WorkArea();
            }
            Win.Left = bounds.Left;
            Win.Top = bounds.Top;
            Win.Width = bounds.Width;
            Win.Height = bounds.Height;
        }

        // ---------- lifetime ----------
        protected void OwnToRevit()
        {
            try
            {
                new WindowInteropHelper(Win).Owner = Uiapp.MainWindowHandle;
            }
            catch (Exception err)
            {
                Log.Write("owner: " + err.Message);
            }
        }

        public virtual void RequestClose()
        {
            Win.Close();
        }

        protected virtual void OnClosed()
        {
            Drawer.Settle();
        }
    }
}
