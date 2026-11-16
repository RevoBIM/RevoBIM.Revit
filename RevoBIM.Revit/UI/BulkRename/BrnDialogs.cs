using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using Autodesk.Revit.UI;
using RevoBIM.Tools.BulkRename;

namespace RevoBIM.UI.BulkRename
{
    /// <summary>The themed prompt: nothing selected, unapplied changes, what went wrong.</summary>
    internal sealed class BrnPrompt : BrnThemedWindow
    {
        private bool answer;

        public BrnPrompt(UIApplication uiapp, Dictionary<string, string> settings, BrnLog log, string message,
                         string title, string detail, string yes, string no, BrnThemedWindow owner, bool wide = false)
            : base(uiapp, settings, log, "Prompt.xaml", owner)
        {
            ((TextBlock)Win.FindName("PromptTitle")).Text = title;
            ((TextBlock)Win.FindName("Message")).Text = message;
            if (!string.IsNullOrEmpty(detail))
            {
                var detailText = (TextBlock)Win.FindName("Detail");
                detailText.Text = detail;
                if (wide)
                {
                    // A table of results: fixed-width text, and a window wide enough for a line.
                    detailText.FontFamily = new System.Windows.Media.FontFamily("Consolas");
                    detailText.FontSize = 11.5;
                    Win.Width = Math.Min(SystemParameters.WorkArea.Width - 80, 900);
                }
                ((UIElement)Win.FindName("DetailBox")).Visibility = Visibility.Visible;
            }
            ((TextBlock)Win.FindName("YesText")).Text = yes ?? "OK";
            var noButton = (Button)Win.FindName("NoBtn");
            if (!string.IsNullOrEmpty(no))
            {
                ((TextBlock)Win.FindName("NoText")).Text = no;
                noButton.Click += (s, a) => Guard("no", Win.Close);
            }
            else
            {
                noButton.Visibility = Visibility.Collapsed;
            }
            ((Button)Win.FindName("YesBtn")).Click += (s, a) => Guard("yes", () =>
            {
                answer = true;
                Win.Close();
            });
            if (owner != null)
            {
                if (owner.Drawer.Parked) Win.WindowStartupLocation = WindowStartupLocation.CenterScreen;
                else Win.Owner = owner.Win;
            }
            else
            {
                Win.WindowStartupLocation = WindowStartupLocation.CenterScreen;
                OwnToRevit();
            }
        }

        public bool Run()
        {
            Win.ShowDialog();
            return answer;
        }
    }

    internal static class BrnDialogs
    {
        public static void Tell(UIApplication uiapp, Dictionary<string, string> settings, BrnLog log, string message,
                                string title = "Bulk Rename", string detail = null, BrnThemedWindow owner = null, bool wide = false)
        {
            new BrnPrompt(uiapp, settings, log, message, title, detail, null, null, owner, wide).Run();
        }

        public static bool Ask(UIApplication uiapp, Dictionary<string, string> settings, BrnLog log, string message,
                               string yes, string no, BrnThemedWindow owner = null)
        {
            return new BrnPrompt(uiapp, settings, log, message, "Bulk Rename", null, yes, no, owner).Run();
        }
    }
}
