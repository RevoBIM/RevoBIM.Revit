using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using Autodesk.Revit.UI;
using RevoBIM.Tools.BulkRename;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.BulkRename
{
    /// <summary>The themed prompt: nothing selected, unapplied changes, what went wrong.</summary>
    internal sealed class BrnPrompt : BrnThemedWindow
    {
        private bool answer;

        public BrnPrompt(UIApplication uiapp, Dictionary<string, string> settings, BrnLog log, string message,
                         string title, string detail, string yes, string no, BrnThemedWindow owner)
            : base(uiapp, settings, log, "Prompt.xaml", owner)
        {
            ((TextBlock)Win.FindName("PromptTitle")).Text = title;
            ((TextBlock)Win.FindName("Message")).Text = message;
            if (!string.IsNullOrEmpty(detail))
            {
                ((TextBlock)Win.FindName("Detail")).Text = detail;
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

    /// <summary>
    /// Settings: which three sheet parameters "Write Sheet names" fills, and the delimiter that splits the name.
    /// </summary>
    internal sealed class BrnSettingsWindow : BrnThemedWindow
    {
        private const string None = "(none)";

        private readonly string sample;
        private readonly TextBlock example;
        private readonly TextBox delimiter;
        private readonly List<KeyValuePair<string, ComboBox>> combos = new List<KeyValuePair<string, ComboBox>>();
        private bool saved;

        public BrnSettingsWindow(UIApplication uiapp, Dictionary<string, string> settings, BrnLog log,
                                 BrnThemedWindow owner, List<string> parameters, string sample)
            : base(uiapp, settings, log, "Settings.xaml", owner)
        {
            this.sample = sample;
            ((TextBlock)Win.FindName("PromptTitle")).Text = "Settings";
            example = (TextBlock)Win.FindName("Example");
            delimiter = (TextBox)Win.FindName("DelimiterBox");
            string current;
            delimiter.Text = settings.TryGetValue("sheet_delimiter", out current) ? current : "";
            for (int index = 0; index < BrnCore.ParamKeys.Length; index++)
            {
                string key = BrnCore.ParamKeys[index];
                var combo = (ComboBox)Win.FindName("Param" + (index + 1));
                string value;
                settings.TryGetValue(key, out value);
                value = value ?? "";
                combo.Items.Add(None);
                var names = new List<string>(parameters);
                if (value.Length > 0 && !names.Contains(value)) names.Insert(0, value);
                foreach (string name in names) combo.Items.Add(name);
                combo.SelectedItem = value.Length > 0 ? value : None;
                combo.SelectionChanged += (s, a) => Guard("changed", OnChanged);
                combos.Add(new KeyValuePair<string, ComboBox>(key, combo));
            }
            delimiter.TextChanged += (s, a) => Guard("changed", OnChanged);
            ((Button)Win.FindName("SaveBtn")).Click += (s, a) => Guard("save", OnSave);
            ((Button)Win.FindName("CancelBtn")).Click += (s, a) => Guard("cancel", Win.Close);
            OnChanged();
            if (owner.Drawer.Parked) Win.WindowStartupLocation = WindowStartupLocation.CenterScreen;
            else Win.Owner = owner.Win;
        }

        private Dictionary<string, string> Picked()
        {
            var output = new Dictionary<string, string> { { "sheet_delimiter", delimiter.Text ?? "" } };
            foreach (KeyValuePair<string, ComboBox> entry in combos)
            {
                string value = entry.Value.SelectedItem as string ?? "";
                output[entry.Key] = value == None ? "" : value;
            }
            return output;
        }

        private void OnChanged()
        {
            var lines = new List<string> { sample };
            foreach (KeyValuePair<string, string> write in BrnCore.SheetWrites(sample, Picked()))
                lines.Add(write.Key + ":  " + (write.Value.Length > 0 ? write.Value : "(blank)"));
            example.Text = string.Join("\n", lines);
        }

        private void OnSave()
        {
            foreach (KeyValuePair<string, string> entry in Picked()) Settings[entry.Key] = entry.Value;
            BrnCore.SaveSettings(Settings);
            saved = true;
            Win.Close();
        }

        public bool Run()
        {
            Win.ShowDialog();
            return saved;
        }
    }

    internal static class BrnDialogs
    {
        public static void Tell(UIApplication uiapp, Dictionary<string, string> settings, BrnLog log, string message,
                                string title = "Bulk Rename", string detail = null, BrnThemedWindow owner = null)
        {
            new BrnPrompt(uiapp, settings, log, message, title, detail, null, null, owner).Run();
        }

        public static bool Ask(UIApplication uiapp, Dictionary<string, string> settings, BrnLog log, string message,
                               string yes, string no, BrnThemedWindow owner = null)
        {
            return new BrnPrompt(uiapp, settings, log, message, "Bulk Rename", null, yes, no, owner).Run();
        }
    }
}
