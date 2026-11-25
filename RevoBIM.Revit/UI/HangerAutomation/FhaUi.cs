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
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using RevoBIM.Helpers;
using RevoBIM.Tools.HangerAutomation;

namespace RevoBIM.UI.HangerAutomation
{
    /// <summary>
    /// What the window object (FhaWindow, written separately) offers to this UI code: the Python <c>owner</c> that
    /// fha_ui's classes and hview_ui received. Everything here and in HviewUi depends on this interface only.
    /// Used by: dialogs (place_dialog, dialog_drawer, Prompt, DimViewsDialog read Win / Drawer / Mode) and by the
    /// tab classes (Collapser's on_resize = ResizeForFold, Status for the status line, Fit, ThemeName for the egg).
    /// </summary>
    public interface IFhaHost
    {
        /// <summary>The WPF main window (Python <c>owner.win</c>).</summary>
        Window Win { get; }

        /// <summary>Its Chrome (grips, drag, full screen, work area, fit).</summary>
        FhaChrome Chrome { get; }

        /// <summary>Its shrink-to-taskbar Drawer; null while the window is still being built (Python <c>owner.drawer</c>).</summary>
        FhaDrawer Drawer { get; }

        /// <summary>The theme mode: "auto", "dark" or "light" (Python <c>owner.mode</c>).</summary>
        string Mode { get; }

        /// <summary>The resolved palette name, "dark" or "light" (what the egg is handed).</summary>
        string ThemeName { get; }

        /// <summary>Sets the status line text (Python <c>owner.status</c>).</summary>
        void Status(string text);

        /// <summary>Grows or shrinks the window to show every tool on the open tab (Python <c>owner.fit</c>).</summary>
        void Fit(bool growOnly);

        /// <summary>A tool is opening or folding by <paramref name="delta"/> px: slide the window with it (Python <c>owner.resize_for_fold</c>).</summary>
        void ResizeForFold(double delta);
    }

    /// <summary>
    /// XAML loading, palette, window chrome, icon and easter egg for the window. Port of fha_ui.py.
    ///
    /// The Python note about IronPython (no new attributes on WPF objects) does not apply in C#; the state still lives
    /// on plain objects (FhaChrome, FhaDrawer, Collapser), exactly as in the Python.
    /// </summary>
    public static partial class FhaUi
    {
        private const string LayoutPrefix = "RevoBIM.UI.HangerAutomation.Layouts.";
        private const string IconPrefix = "RevoBIM.Resources.HangerAutomation.";

        // ------------------------------------------------------------------ loading
        /// <summary>Python read_text(name): the text of an embedded layout ("Theme.xaml", "HangerPrompt.xaml" ...).</summary>
        public static string ReadText(string name)
        {
            using (Stream stream = typeof(FhaUi).Assembly.GetManifestResourceStream(LayoutPrefix + name))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + name + " was not found");
                using (var reader = new StreamReader(stream, System.Text.Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        /// <summary>Parse a layout, then merge Theme.xaml (layouts only use DynamicResource).</summary>
        public static Window LoadXamlWindow(string name)
        {
            var win = (Window)XamlReader.Parse(ReadText(name));
            var theme = (ResourceDictionary)XamlReader.Parse(ReadText("Theme.xaml"));
            win.Resources.MergedDictionaries.Add(theme);
            return win;
        }

        public static Window LoadWindow()
        {
            return LoadXamlWindow("HangerAutomation.xaml");
        }

        /// <summary>PNG bytes -> BitmapImage, from a stream (never a Uri - it moved assembly in 2025).</summary>
        public static BitmapImage BitmapFromBytes(byte[] data)
        {
            var bi = new BitmapImage();
            bi.BeginInit();
            bi.StreamSource = new MemoryStream(data);
            bi.CacheOption = BitmapCacheOption.OnLoad;
            bi.EndInit();
            try { bi.Freeze(); } catch (Exception) { }
            return bi;
        }

        /// <summary>Swap a control's style by key; re-resolves when the palette changes.</summary>
        public static void SetStyle(FrameworkElement el, string key)
        {
            try
            {
                el.SetResourceReference(FrameworkElement.StyleProperty, key);
            }
            catch (Exception)
            {
            }
        }

        // ================================================================ theme
        /// <summary>
        /// Revit's canvas theme: true / false, null when it cannot be read. The Python tried CurrentCanvasTheme then
        /// CurrentTheme (by getattr); the first is present in every supported Revit, so only it is read. UITheme.Dark
        /// is compared by value, never tested for truth.
        /// </summary>
        public static bool? CanvasIsDark()
        {
            try
            {
                return RevoBIM.Helpers.RevitCompat.CanvasTheme() == Autodesk.Revit.UI.UITheme.Dark;
            }
            catch (Exception)
            {
            }
            return null;
        }

        /// <summary>Write the resolved palette onto window.Resources; returns "dark" / "light".</summary>
        public static string ApplyPalette(Window win, string mode)
        {
            string name = FhaCore.ResolveTheme(mode, CanvasIsDark());
            foreach (KeyValuePair<string, string> entry in FhaCore.Palettes[name])
                win.Resources[entry.Key + "Brush"] = new SolidColorBrush((Color)ColorConverter.ConvertFromString(entry.Value));
            return name;
        }

        // ============================================================ decoration
        /// <summary>
        /// Decorative only: never allowed to take the tool down. The Python read icon.png from disk; here it is the
        /// embedded resource RevoBIM.Resources.HangerAutomation.&lt;imageName&gt;.
        /// </summary>
        public static void SetIcon(Window win, string imageName = "icon.png")
        {
            try
            {
                byte[] data;
                using (Stream stream = typeof(FhaUi).Assembly.GetManifestResourceStream(IconPrefix + imageName))
                {
                    if (stream == null) return;
                    using (var ms = new MemoryStream())
                    {
                        stream.CopyTo(ms);
                        data = ms.ToArray();
                    }
                }
                BitmapImage bi = BitmapFromBytes(data);
                ((Image)win.FindName("Logo")).Source = bi;
                win.Icon = bi;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// The logo easter egg: three slow clicks on the corner logo - and nowhere else. The Python looked for the
        /// shared revobim.egg package (attach / attach_to_window / launch, matched by signature) with a local
        /// EggClicks fallback; the add-in has one implementation, Helpers\EggHook, armed on the logo only.
        /// Returns the route used, for the debug log ("EggHook", "no logo", "no entry point").
        /// </summary>
        public static string AttachEgg(Window win, FrameworkElement logo, Func<string> theme = null)
        {
            if (logo == null) return "no logo";
            try
            {
                if (EggHook.Attach(win, theme, logo)) return "EggHook";
            }
            catch (Exception)
            {
            }
            return "no entry point";
        }

        /// <summary>Own the window to Revit so a modeless window cannot slip behind it.</summary>
        public static void OwnWindow(Window win, Autodesk.Revit.UI.UIApplication uiapp)
        {
            try
            {
                new WindowInteropHelper(win).Owner = uiapp.MainWindowHandle;
            }
            catch (Exception)
            {
            }
        }

        // =========================================================== live window
        // The Python kept the window in AppDomain data (to survive an engine reload); one add-in DLL per Revit
        // session needs only a static field.
        private static Window parkedWindow;

        /// <summary>The open window from an earlier click, or null.</summary>
        public static Window Parked()
        {
            try
            {
                Window w = parkedWindow;
                if (w != null && w.IsVisible) return w;
            }
            catch (Exception)
            {
            }
            return null;
        }

        public static void Park(Window win)
        {
            try
            {
                parkedWindow = win;
            }
            catch (Exception)
            {
            }
        }

        // ========================================================== collapsible
        public const double SlideMs = 260;
        public const double MaxScreen = 0.97;   // never taller than this share of the screen's working area

        internal static DoubleAnimation Eased(double from, double to, double ms)
        {
            var a = new DoubleAnimation();
            a.From = from;
            a.To = to;
            a.Duration = new Duration(TimeSpan.FromMilliseconds(ms));
            var ease = new CubicEase();
            ease.EasingMode = EasingMode.EaseInOut;
            a.EasingFunction = ease;
            return a;
        }

        /// <summary>Slide a window to a new height on the fold curve, then hold it there.</summary>
        public static void AnimateHeight(Window win, double height, Action done = null)
        {
            DoubleAnimation a = Eased(win.ActualHeight, height, SlideMs);
            a.Completed += (sender, e) =>
            {
                try
                {
                    win.BeginAnimation(FrameworkElement.HeightProperty, null);
                    win.Height = height;
                }
                catch (Exception)
                {
                }
                if (done != null) done();
            };
            win.BeginAnimation(FrameworkElement.HeightProperty, a);
        }

        // ================================================================ drawer
        public const double DrawerMs = 320;
        public const double BarGap = 8.0;   // px between a parked bar and the bottom of the working area
        public const string ShrinkTip = "Shrink to the taskbar - see Revit (Ctrl+Shift+H)";
        public const string ExpandTip = "Open the window again (Ctrl+Shift+H, Enter or Esc)";

        public static Thickness MakeThickness(double l, double t, double r, double b)
        {
            return new Thickness(l, t, r, b);
        }

        /// <summary>Everything laid out beside the title bar in its parent grid (the body).</summary>
        public static List<UIElement> HeaderSiblings(FrameworkElement header)
        {
            var o = new List<UIElement>();
            try
            {
                foreach (UIElement ch in ((Panel)header.Parent).Children)
                    if (!ReferenceEquals(ch, header)) o.Add(ch);
            }
            catch (Exception)
            {
            }
            return o;
        }

        public static bool OwnerParked(IFhaHost owner)
        {
            try
            {
                return owner.Drawer != null && owner.Drawer.Shrunk;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Own a dialog to the tool window - centred on the screen instead when the window is parked (centred on a
        /// 50 px bar it would be half off the screen).
        /// </summary>
        public static void PlaceDialog(Window dlgWin, IFhaHost owner)
        {
            try
            {
                dlgWin.Owner = owner.Win;
            }
            catch (Exception)
            {
            }
            if (OwnerParked(owner))
            {
                try
                {
                    dlgWin.WindowStartupLocation = WindowStartupLocation.CenterScreen;
                }
                catch (Exception)
                {
                }
            }
        }

        /// <summary>
        /// The drawer for a modal dialog: wired to its shrink button, its keys and its closing, parking its owner
        /// beneath it. The Python took the dialog object (<c>dlg.win</c>); here the dialog's Window.
        /// </summary>
        public static FhaDrawer DialogDrawer(Window dlgWin, IFhaHost owner, FrameworkElement header, ButtonBase button,
                                             UIElement shrinkIcon, UIElement expandIcon)
        {
            FhaDrawer ownerDrawer = null;
            try { ownerDrawer = owner.Drawer; } catch (Exception) { }
            var d = new FhaDrawer(dlgWin, new FhaChrome(dlgWin), header, button, shrinkIcon, expandIcon, owner: ownerDrawer);
            button.Click += (s, e) => d.Toggle();
            dlgWin.PreviewKeyDown += (sender, e) =>
            {
                if (d.Key(e)) e.Handled = true;
            };
            dlgWin.Closed += (s, e) => d.Closing();
            return d;
        }

        // ================================================================ worksets
        /// <summary>
        /// Fill a tab's workset combo (FhaCore.WsOptions + the model's worksets) and select the saved choice.
        /// Returns the values in item order.
        /// </summary>
        public static List<string> FillWorksetCombo(ComboBox combo, IEnumerable<string> names, string value)
        {
            List<string> nameList = names == null ? new List<string>() : names.ToList();
            WorksetItems r = FhaCore.WorksetItemsFor(nameList, value);
            try
            {
                combo.Items.Clear();
            }
            catch (Exception)
            {
            }
            foreach (string lab in r.Labels) combo.Items.Add(lab);
            combo.SelectedIndex = r.Index;
            if (nameList.Count == 0)
                combo.ToolTip = "This model is not workshared (or has no user worksets): nothing to set.";
            return r.Values;
        }
    }
}
