using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using RevoBIM.Helpers;
using RevoBIM.Tools.CircuitManager;

using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using Orientation = System.Windows.Controls.Orientation;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.CircuitManager
{
    /// <summary>The tool's chrome configuration and palettes (cm_theme.py). Dark is Revit's own dark theme.</summary>
    internal static class CmUi
    {
        private static readonly Dictionary<string, string> Dark = new Dictionary<string, string>
        {
            { "TitleBg", "#222933" }, { "BodyBg", "#3C4454" }, { "FieldBg", "#2D3441" },
            { "ToolbarBg", "#1B1F24" }, { "HeadingBg", "#323C48" }, { "CardBg", "#343C4A" },
            { "HoverBg", "#444E5E" }, { "PressBg", "#323C48" }, { "SelBg", "#3A7392" },
            { "RowHlBg", "#36485A" }, { "Edge", "#515C6B" }, { "FrameEdge", "#5A6372" },
            { "Text", "#EEF0F4" }, { "Muted", "#A4AAB1" }, { "Hint", "#7B8290" },
            { "Blue", "#5AAEEB" }, { "Orange", "#E8912D" }, { "Green", "#3FA75A" },
            { "GreenHover", "#4EC06D" }, { "Red", "#D9534F" }, { "OnAccent", "#FFFFFF" },
            { "ButtonBg", "#46505F" }, { "ButtonHover", "#55606F" },
            { "StagedBg", "#2F5E3B" }, { "StagedText", "#D8F5DF" },
            { "BadBg", "#8E2A27" }, { "BadText", "#FFE3E1" },
            { "CopyBg", "#6B5420" }, { "ReadOnlyBg", "#4A3E45" },
        };

        private static readonly Dictionary<string, string> Light = new Dictionary<string, string>
        {
            { "TitleBg", "#E4E7EB" }, { "BodyBg", "#F3F4F6" }, { "FieldBg", "#FFFFFF" },
            { "ToolbarBg", "#EAECEF" }, { "HeadingBg", "#E1E5EA" }, { "CardBg", "#FFFFFF" },
            { "HoverBg", "#E3E8EE" }, { "PressBg", "#D2D9E1" }, { "SelBg", "#BFDCF4" },
            { "RowHlBg", "#E3EFFA" }, { "Edge", "#C5CAD1" }, { "FrameEdge", "#AEB4BC" },
            { "Text", "#1E2329" }, { "Muted", "#5F6670" }, { "Hint", "#8A9099" },
            { "Blue", "#1B72BE" }, { "Orange", "#B96A12" }, { "Green", "#2E8546" },
            { "GreenHover", "#379A52" }, { "Red", "#C0392B" }, { "OnAccent", "#FFFFFF" },
            { "ButtonBg", "#E1E5EA" }, { "ButtonHover", "#D2D9E1" },
            { "StagedBg", "#CDEFD6" }, { "StagedText", "#14401F" },
            { "BadBg", "#F5B7B1" }, { "BadText", "#5C0F09" },
            { "CopyBg", "#FBE3A6" }, { "ReadOnlyBg", "#F6E1E1" },
        };

        public static readonly ChromeConfig Config = new ChromeConfig
        {
            LayoutPrefix = "RevoBIM.UI.CircuitManager.Layouts.",
            IconResource = "RevoBIM.Resources.CircuitManager.icon.png",
            Version = CmLogic.Version,
            ThemeSetting = () => CmSettings.Get("theme"),
            SetThemeSetting = s => CmSettings.Set("theme", s),
            Palette = resolved => resolved == "light" ? Light : Dark,
            Log = CmSettings.Log,
        };
    }

    /// <summary>A message or choice box in the house chrome. Shrinking it takes the main window down with it.</summary>
    internal sealed class CmMessageWindow : ThemedWindow
    {
        private string choice;

        public CmMessageWindow(ThemedWindow owner, string title, string body, List<KeyValuePair<string, string>> buttons)
            : base(CmUi.Config, "Message.xaml", owner)
        {
            SetText("title_text", title);
            var bodyBox = Find<TextBox>("body_text");
            if (bodyBox != null) bodyBox.Text = body;
            var panel = Find<Panel>("buttons_panel");
            for (int i = 0; i < buttons.Count; i++)
            {
                string label = buttons[i].Key;
                var btn = new Button { Content = new TextBlock { Text = label }, Margin = new Thickness(8, 0, 0, 0) };
                if (!string.IsNullOrEmpty(buttons[i].Value)) btn.SetResourceReference(FrameworkElement.StyleProperty, buttons[i].Value);
                btn.Click += (s, a) =>
                {
                    choice = label;
                    Win.Close();
                };
                panel.Children.Add(btn);
                if (i == buttons.Count - 1) btn.IsDefault = true;
            }
        }

        protected override void OnKey(KeyEventArgs args, Key key, bool ctrl, bool shift)
        {
            if (key == Key.Escape)
            {
                choice = null;
                Win.Close();
                args.Handled = true;
            }
        }

        public string ShowChoice()
        {
            Win.ShowDialog();
            return choice;
        }
    }

    internal static class CmDialogs
    {
        /// <summary>buttons: (label, style key or null) - the last is the default. Returns the label pressed, or null.</summary>
        public static string Ask(ThemedWindow owner, string title, string body, params string[][] buttons)
        {
            var list = buttons.Select(b => new KeyValuePair<string, string>(b[0], b.Length > 1 ? b[1] : null)).ToList();
            return new CmMessageWindow(owner, title, body, list).ShowChoice();
        }

        public static void Tell(ThemedWindow owner, string title, string body)
        {
            Ask(owner, title, body, new[] { "OK", "GreenBtn" });
        }
    }

    /// <summary>Tick the circuit parameters to show as columns.</summary>
    internal sealed class CmParamPicker : ThemedWindow
    {
        private readonly List<KeyValuePair<string, CheckBox>> items = new List<KeyValuePair<string, CheckBox>>();
        private List<string> result;

        public CmParamPicker(ThemedWindow owner, List<ParamInfo> parameters, List<string> shown)
            : base(CmUi.Config, "ParamPicker.xaml", owner)
        {
            var list = Find<ListBox>("list");
            foreach (ParamInfo p in parameters)
            {
                var cb = new CheckBox { IsChecked = shown.Contains(p.Name), Margin = new Thickness(2) };
                var row = new StackPanel { Orientation = Orientation.Horizontal };
                row.Children.Add(new TextBlock { Text = p.Name });
                var hint = new TextBlock { Text = p.Writable ? "  editable" : "  read only", FontSize = 11 };
                hint.SetResourceReference(TextBlock.ForegroundProperty, p.Writable ? "Green" : "Hint");
                row.Children.Add(hint);
                cb.Content = row;
                cb.Checked += (s, a) => Count();
                cb.Unchecked += (s, a) => Count();
                list.Items.Add(cb);
                items.Add(new KeyValuePair<string, CheckBox>(p.Name, cb));
            }
            Find<TextBox>("search_box").TextChanged += OnSearch;
            Find<Button>("all_btn").Click += (s, a) => TickShown(true);
            Find<Button>("none_btn").Click += (s, a) => TickShown(false);
            Find<Button>("ok_btn").Click += (s, a) =>
            {
                result = items.Where(i => i.Value.IsChecked == true).Select(i => i.Key).ToList();
                Win.Close();
            };
            Find<Button>("cancel_btn").Click += (s, a) => Win.Close();
            Count();
        }

        private void OnSearch(object sender, TextChangedEventArgs args)
        {
            string term = Find<TextBox>("search_box").Text;
            foreach (var i in items)
                i.Value.Visibility = CmLogic.MatchesText(i.Key, term) ? Visibility.Visible : Visibility.Collapsed;
        }

        /// <summary>Acts on what the search is showing, the way Excel's list does.</summary>
        private void TickShown(bool value)
        {
            foreach (var i in items)
                if (i.Value.Visibility == Visibility.Visible) i.Value.IsChecked = value;
        }

        private void Count()
        {
            int n = items.Count(i => i.Value.IsChecked == true);
            SetText("count_text", n + " of " + items.Count + " ticked");
        }

        protected override void OnKey(KeyEventArgs args, Key key, bool ctrl, bool shift)
        {
            if (key == Key.Escape)
            {
                Win.Close();
                args.Handled = true;
            }
        }

        public List<string> ShowPicker()
        {
            Win.ShowDialog();
            return result;
        }
    }
}
