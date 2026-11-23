using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using Autodesk.Revit.DB;
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
    /// <summary>
    /// Revit's Select Elements by ID, in the house style, for a run started with nothing selected. Find
    /// selects nothing in the model itself: it hands the elements to the caller, which selects them and goes
    /// on to the main window. Port of FindByIdWindow in fiv_window.py.
    /// </summary>
    internal sealed class FivByIdWindow
    {
        private readonly UIDocument uidoc;
        private readonly UIApplication uiapp;
        private readonly Window window;
        private readonly FivChrome chrome;
        private readonly FivDrawer drawer;

        public List<Element> Elements = new List<Element>();
        public List<ElementId> ElementIds = new List<ElementId>();
        public bool Skipped;

        public FivByIdWindow(UIDocument uidoc, UIApplication uiapp, Dictionary<string, string> settings)
        {
            this.uidoc = uidoc;
            this.uiapp = uiapp;
            string palette = FivUi.PaletteFor(settings);
            window = FivXaml.LoadWindow("FindById.xaml", palette);
            ((TextBlock)window.FindName("VersionText")).Text = "v" + FivCore.Version;
            var icon = (Image)window.FindName("HeaderIcon");
            FivXaml.LoadIcon(icon);
            EggHook.Attach(window, () => palette, icon);
            var header = (Border)window.FindName("HeaderBar");
            chrome = new FivChrome(window, header);
            drawer = new FivDrawer(window, header, (Panel)window.FindName("RootGrid"), (Button)window.FindName("ShrinkBtn"),
                                   (UIElement)window.FindName("PathShrink"), (UIElement)window.FindName("PathExpand"),
                                   (Border)window.FindName("RootBorder"), null);
            chrome.Drawer = drawer;

            ((Button)window.FindName("CloseBtn")).Click += (s, a) => Cancel();
            ((Button)window.FindName("CancelBtn")).Click += (s, a) => Cancel();
            ((Button)window.FindName("FindBtn")).Click += (s, a) => Find();
            ((Button)window.FindName("SkipBtn")).Click += (s, a) => Skip();
            ((TextBox)window.FindName("IdBox")).TextChanged += (s, a) => Typed();
            window.PreviewKeyDown += OnKey;
            window.Loaded += (s, a) =>
            {
                try
                {
                    ((TextBox)window.FindName("IdBox")).Focus();
                }
                catch (Exception)
                {
                }
            };
        }

        private T F<T>(string name) where T : class
        {
            return (T)window.FindName(name);
        }

        private List<string> Tokens()
        {
            return FivCore.ParseIds(F<TextBox>("IdBox").Text);
        }

        private void Typed()
        {
            int count = Tokens().Count;
            F<Button>("FindBtn").IsEnabled = count > 0;
            F<TextBlock>("CountText").Text = count == 0 ? "" : FivCore.Plural(count, "id") + " typed";
        }

        private void OnKey(object sender, KeyEventArgs args)
        {
            try
            {
                if (drawer.Shrunk)
                {
                    if (args.Key == Key.Escape || args.Key == Key.Enter || args.Key == Key.F11 || FivUi.IsShrinkKey(args))
                    {
                        drawer.Expand();
                        args.Handled = true;
                    }
                    return;
                }
                if (FivUi.IsShrinkKey(args))
                {
                    drawer.Toggle();
                    args.Handled = true;
                }
                else if (args.Key == Key.Escape) Cancel();
                else if (args.Key == Key.Enter && args.KeyboardDevice.Modifiers == ModifierKeys.Control)
                {
                    if (F<Button>("FindBtn").IsEnabled) Find();
                }
            }
            catch (Exception)
            {
            }
        }

        private void Find()
        {
            List<string> tokens = Tokens();
            if (tokens.Count == 0) return;
            List<Element> elements;
            List<ElementId> ids;
            List<string> missing;
            FivModel.FindByIds(uidoc.Document, tokens, out elements, out ids, out missing);
            FivLog.Write("by-id: typed " + tokens.Count + ", found " + elements.Count + ", missing [" + string.Join(", ", missing) + "]");

            if (elements.Count == 0)
            {
                F<TextBlock>("StatusText").Text = "Nothing in this model has " + (tokens.Count == 1 ? "that id" : "those ids") +
                                                  ". Check the ids, and that they belong to this model rather than a link.";
                return;
            }
            Elements = elements;
            ElementIds = ids;
            if (missing.Count > 0)
            {
                // found some: say which were not, then carry on with what there is
                F<TextBlock>("StatusText").Text = "Found " + FivCore.Plural(elements.Count, "element") + ". Not in this model: " +
                                                  string.Join(", ", missing.GetRange(0, Math.Min(8, missing.Count))) + (missing.Count > 8 ? "..." : "");
                F<TextBlock>("CountText").Text = "opening with " + FivCore.Plural(elements.Count, "element");
            }
            window.Close();
        }

        /// <summary>Straight to the view list with nothing selected. Show Me still opens the view; there is nothing to frame it on.</summary>
        private void Skip()
        {
            Skipped = true;
            Elements = new List<Element>();
            ElementIds = new List<ElementId>();
            window.Close();
        }

        private void Cancel()
        {
            Skipped = false;
            Elements = new List<Element>();
            ElementIds = new List<ElementId>();
            window.Close();
        }

        public void Show()
        {
            FivUi.OwnToRevit(window, uiapp);
            window.ShowDialog();
        }
    }
}
