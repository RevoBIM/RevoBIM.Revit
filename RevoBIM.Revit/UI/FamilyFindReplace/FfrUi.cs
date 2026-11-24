using System;
using System.Collections.Generic;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Autodesk.Revit.UI;
using RevoBIM.Tools.FamilyFindReplace;

using Button = System.Windows.Controls.Button;
using Grid = System.Windows.Controls.Grid;
using Panel = System.Windows.Controls.Panel;
using TextBox = System.Windows.Controls.TextBox;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.FamilyFindReplace
{
    /// <summary>Loads the pyRevit XAML layouts, unchanged, from the embedded copies in UI\FamilyFindReplace\Layouts.</summary>
    internal static class FfrXaml
    {
        private const string LayoutPrefix = "RevoBIM.UI.FamilyFindReplace.Layouts.";
        private const string IconName = "RevoBIM.Resources.FamilyFindReplace.icon.png";

        public static string ReadLayout(string file)
        {
            using (Stream stream = typeof(FfrXaml).Assembly.GetManifestResourceStream(LayoutPrefix + file))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + file + " was not found");
                using (var reader = new StreamReader(stream, System.Text.Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        /// <summary>
        /// Parses a layout, then merges Theme.xaml in behind it. Theme.xaml is merged AFTER the layout has been
        /// parsed, which is why a layout may only ever ask for brushes and styles with DynamicResource.
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
                using (Stream stream = typeof(FfrXaml).Assembly.GetManifestResourceStream(IconName))
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

    /// <summary>Runs queued closures inside Revit's API context. The one place the Revit API is in context.</summary>
    internal sealed class FfrJobHandler : IExternalEventHandler
    {
        private readonly Queue<Action<UIApplication>> jobs = new Queue<Action<UIApplication>>();
        public Action<string> OnError;
        public Action OnFinish;

        public void Queue(Action<UIApplication> job) { jobs.Enqueue(job); }

        public void Execute(UIApplication uiapp)
        {
            while (jobs.Count > 0)
            {
                Action<UIApplication> job = jobs.Dequeue();
                try
                {
                    job(uiapp);
                }
                catch (Exception err)
                {
                    FfrLog.Write("error: " + err);
                    if (OnError != null)
                    {
                        try
                        {
                            OnError(err.ToString());
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
                finally
                {
                    // The window is made hit-test-invisible while a job runs. A job that throws part way through
                    // must not leave it that way, or the tool reads as frozen with no way back.
                    if (OnFinish != null)
                    {
                        try
                        {
                            OnFinish();
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
            }
        }

        public string GetName() { return "RevoBIM Family Find and Replace"; }
    }

    internal static class FfrUi
    {
        /// <summary>Owned windows float above Revit instead of slipping behind it.</summary>
        public static void OwnToRevit(Window window, UIApplication uiapp)
        {
            try
            {
                new WindowInteropHelper(window).Owner = uiapp.MainWindowHandle;
            }
            catch (Exception)
            {
            }
        }

        public static Brush BrushOf(FrameworkElement scope, string key)
        {
            try
            {
                return scope.TryFindResource(key) as Brush;
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static Style StyleOf(FrameworkElement scope, string key)
        {
            try
            {
                return scope.TryFindResource(key) as Style;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>A list row: label on the left, a small note on the right. The note's style turns it to the body colour on a selected row.</summary>
        public static ListBoxItem MakeRow(FrameworkElement scope, string text, string rightText, object tag)
        {
            var item = new ListBoxItem();
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var label = new TextBlock { Text = text, TextTrimming = TextTrimming.CharacterEllipsis };
            Grid.SetColumn(label, 0);
            grid.Children.Add(label);

            if (!string.IsNullOrEmpty(rightText))
            {
                var note = new TextBlock { Text = rightText, FontSize = 10, Margin = new Thickness(8, 0, 0, 0) };
                Style style = StyleOf(scope, "RowNote");
                if (style != null) note.Style = style;
                Grid.SetColumn(note, 1);
                grid.Children.Add(note);
            }
            item.Content = grid;
            item.Tag = tag;
            return item;
        }

        /// <summary>
        /// Themed modal question. True only on a real yes. With an owner the prompt sits over it, and shrinking
        /// the prompt takes the main window down with it. Falls back to Revit's own dialog rather than returning
        /// a silent no if the themed one will not open: a confirm that answers itself is indistinguishable from
        /// a button that does nothing.
        /// </summary>
        public static bool Ask(string headline, string body, string okText, string cancelText, Window owner)
        {
            try
            {
                Window window = FfrXaml.LoadWindow("FamilyFindReplacePrompt.xaml");
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
                var header = (Border)window.FindName("PromptHeaderBar");
                var drawer = new FfrDrawer(window, header, (Panel)header.Parent, (Button)window.FindName("PromptShrinkBtn"));
                ((TextBlock)window.FindName("PromptVersion")).Text = "v" + FfrCore.Version;
                ((TextBlock)window.FindName("PromptHeadline")).Text = headline;
                ((TextBlock)window.FindName("PromptBody")).Text = body;
                var ok = (Button)window.FindName("PromptOkBtn");
                var cancel = (Button)window.FindName("PromptCancelBtn");
                ok.Content = okText;
                bool answer = false;
                ok.Click += (s, a) =>
                {
                    answer = true;
                    window.DialogResult = true;
                };
                if (cancelText == null) cancel.Visibility = Visibility.Collapsed;
                else
                {
                    cancel.Content = cancelText;
                    cancel.Click += (s, a) => window.DialogResult = false;
                }
                header.MouseLeftButtonDown += (s, a) =>
                {
                    if (drawer.OnHeaderDown(a)) return;
                    try
                    {
                        window.DragMove();
                    }
                    catch (Exception)
                    {
                    }
                };
                window.ShowDialog();
                return answer;
            }
            catch (Exception err)
            {
                FfrLog.Write("prompt: themed window failed (" + err.Message + "), used a TaskDialog");
            }
            try
            {
                var dialog = new TaskDialog("RevoBIM Family Find & Replace") { MainInstruction = headline, MainContent = body };
                if (cancelText == null)
                {
                    dialog.CommonButtons = TaskDialogCommonButtons.Ok;
                    dialog.Show();
                    return true;
                }
                dialog.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No;
                return dialog.Show() == TaskDialogResult.Yes;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Themed modal statement, one button.</summary>
        public static void Tell(string headline, string body, Window owner)
        {
            Ask(headline, body, "OK", null, owner);
        }
    }
}
