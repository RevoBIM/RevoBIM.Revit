using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Xml;
using System.Xml.Linq;
using RevoBIM.Tools.BwicPenetration;

namespace RevoBIM.UI.BwicPenetration
{
    /// <summary>
    /// Window plumbing shared by every BWIC Penetration window. The pyRevit XAML is loaded verbatim; its handler names
    /// (Click="place_click") are lifted out before XamlReader sees them and wired afterwards to the handlers the window passes in.
    /// Every handler goes through <see cref="Guard"/>, so a failure names itself in the debug file instead of vanishing.
    /// </summary>
    internal static class BwiUi
    {
        private const string LayoutPrefix = "RevoBIM.UI.BwicPenetration.Layouts.";
        private const string IconName = "RevoBIM.Resources.BwicPenetration.icon.png";
        private static readonly XNamespace X = "http://schemas.microsoft.com/winfx/2006/xaml";
        private static readonly Regex HandlerName = new Regex("^[a-z][a-z0-9]*(_[a-z0-9]+)+$", RegexOptions.Compiled);

        private sealed class Hook
        {
            public string Element, Event, Handler;
        }

        public static string ReadLayout(string file)
        {
            using (Stream stream = typeof(BwiUi).Assembly.GetManifestResourceStream(LayoutPrefix + file))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + file + " was not found");
                using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        /// <summary>Parses a layout and wires its handler names to the given handlers.</summary>
        public static Window Load(string file, Dictionary<string, Action<object, RoutedEventArgs>> handlers)
        {
            XDocument doc = XDocument.Parse(ReadLayout(file), LoadOptions.PreserveWhitespace);
            var hooks = new List<Hook>();
            int counter = 0;
            string[] events = { "Click", "TextChanged", "MouseLeftButtonDown", "SelectionChanged", "DragDelta" };
            foreach (XElement element in doc.Descendants().ToList())
            {
                foreach (XAttribute attr in element.Attributes().ToList())
                {
                    string ev = attr.Name.LocalName;
                    if (!events.Contains(ev)) continue;
                    if (!HandlerName.IsMatch(attr.Value)) continue;
                    string name = (string)element.Attribute(X + "Name");
                    if (string.IsNullOrEmpty(name))
                    {
                        name = "bwiHook" + counter++;
                        element.SetAttributeValue(X + "Name", name);
                    }
                    hooks.Add(new Hook { Element = name, Event = ev, Handler = attr.Value });
                    attr.Remove();
                }
            }
            object loaded;
            using (XmlReader reader = XmlReader.Create(new StringReader(doc.ToString(SaveOptions.DisableFormatting))))
                loaded = XamlReader.Load(reader);
            var window = loaded as Window;
            if (window == null) throw new InvalidCastException(file + " is not a Window");

            foreach (Hook hook in hooks)
            {
                var target = window.FindName(hook.Element) as UIElement;
                Action<object, RoutedEventArgs> handler;
                if (target == null || !handlers.TryGetValue(hook.Handler, out handler))
                    throw new InvalidOperationException("could not wire " + hook.Handler + " (" + hook.Event + ") in " + file);
                switch (hook.Event)
                {
                    case "Click": target.AddHandler(ButtonBase.ClickEvent, new RoutedEventHandler((s, e) => handler(s, e))); break;
                    case "TextChanged": target.AddHandler(TextBoxBase.TextChangedEvent, new TextChangedEventHandler((s, e) => handler(s, e))); break;
                    case "SelectionChanged": target.AddHandler(Selector.SelectionChangedEvent, new SelectionChangedEventHandler((s, e) => handler(s, e))); break;
                    case "DragDelta": target.AddHandler(Thumb.DragDeltaEvent, new DragDeltaEventHandler((s, e) => handler(s, e))); break;
                    default: target.AddHandler(UIElement.MouseLeftButtonDownEvent, new MouseButtonEventHandler((s, e) => handler(s, e))); break;
                }
            }
            return window;
        }

        /// <summary>Wraps a handler so a throw is reported (debug file and the window's report) instead of swallowed.</summary>
        public static Action<object, RoutedEventArgs> Guard(string name, Action<object, RoutedEventArgs> body, Action<string> report)
        {
            return (s, e) =>
            {
                try { body(s, e); }
                catch (Exception err)
                {
                    try { BwicCore.DebugLog("HANDLER " + name + " FAILED\n" + err); } catch (Exception) { }
                    try { if (report != null) report(name.Replace('_', ' ') + " failed: " + err.Message); } catch (Exception) { }
                }
            };
        }

        public static BitmapImage LoadLogoImage()
        {
            try
            {
                using (Stream stream = typeof(BwiUi).Assembly.GetManifestResourceStream(IconName))
                {
                    if (stream == null) return null;
                    var bitmap = new BitmapImage();
                    bitmap.BeginInit();
                    bitmap.StreamSource = stream;
                    bitmap.CacheOption = BitmapCacheOption.OnLoad;
                    bitmap.EndInit();
                    bitmap.Freeze();
                    return bitmap;
                }
            }
            catch (Exception) { return null; }
        }

        /// <summary>Device pixels per WPF unit for the screen the window is on.</summary>
        public static double DpiScale(Window window)
        {
            try
            {
                PresentationSource source = PresentationSource.FromVisual(window);
                if (source != null)
                {
                    double scale = source.CompositionTarget.TransformToDevice.M22;
                    if (scale > 0) return scale;
                }
            }
            catch (Exception) { }
            return 1.0;
        }

        /// <summary>The primary screen's usable area in WPF units: left, top, width, height.</summary>
        public static double[] WorkingArea(double scale)
        {
            try
            {
                System.Drawing.Rectangle area = System.Windows.Forms.Screen.PrimaryScreen.WorkingArea;
                return new[] { area.Left / scale, area.Top / scale, area.Width / scale, area.Height / scale };
            }
            catch (Exception) { return new[] { 0.0, 0.0, 1920.0, 1040.0 }; }
        }

        /// <summary>A System.Drawing bitmap as a frozen WPF image (through a PNG stream, so no GDI handle leaks), or null.</summary>
        public static BitmapImage BitmapToImage(System.Drawing.Bitmap bitmap)
        {
            if (bitmap == null) return null;
            try
            {
                var stream = new MemoryStream();
                bitmap.Save(stream, System.Drawing.Imaging.ImageFormat.Png);
                stream.Position = 0;
                var image = new BitmapImage();
                image.BeginInit();
                image.StreamSource = stream;
                image.CacheOption = BitmapCacheOption.OnLoad;
                image.EndInit();
                image.Freeze();
                return image;
            }
            catch (Exception err)
            {
                BwicCore.DebugLog("preview could not be shown: " + err.Message);
                return null;
            }
            finally
            {
                try { bitmap.Dispose(); } catch (Exception) { }
            }
        }

        public static bool OwnToRevit(Window window)
        {
            try
            {
                if (BwicCore.CurrentApp == null) return false;
                new WindowInteropHelper(window).Owner = BwicCore.CurrentApp.MainWindowHandle;
                return true;
            }
            catch (Exception) { return false; }
        }
    }

    /// <summary>Base of every window: find elements by name, read resources, report and log.</summary>
    internal abstract class BwiWindowBase
    {
        public Window Win;
        public Drawer Drawer;

        protected T Find<T>(string name) where T : class
        {
            var found = Win.FindName(name) as T;
            if (found == null) throw new InvalidOperationException("layout element " + name + " (" + typeof(T).Name + ") was not found");
            return found;
        }

        protected object Res(string key) { return Win.FindResource(key); }

        protected Action<object, RoutedEventArgs> G(string name, Action<object, RoutedEventArgs> body)
        {
            return BwiUi.Guard(name, body, Report);
        }

        public virtual void Report(string message) { BwicCore.DebugLog("status: " + message); }

        protected void HeaderDown(object sender, RoutedEventArgs e)
        {
            var args = e as MouseButtonEventArgs;
            if (args != null && Drawer != null && Drawer.HeaderDown(args)) return;
            try { Win.DragMove(); } catch (Exception) { }
        }

        protected void KeyDownDrawer(KeyEventArgs args, bool closeOnEscape)
        {
            if (Drawer != null && Drawer.HandleKey(args)) return;
            if (closeOnEscape && args.Key == Key.Escape)
            {
                args.Handled = true;
                Win.Close();
            }
        }
    }
}
