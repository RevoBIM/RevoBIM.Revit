using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using RevoBIM.Tools.ViewManager;

namespace RevoBIM.UI.ViewManager
{
    /// <summary>The debug report window: Copy, and Save to file.</summary>
    internal sealed class VmDebugWindow
    {
        private readonly Window window;
        private readonly TextBox textBox;
        private readonly TextBlock status;

        public VmDebugWindow(Window owner, string text)
        {
            window = VmUi.LoadLayout("Debug.xaml");
            textBox = (TextBox)window.FindName("DbgText");
            status = (TextBlock)window.FindName("DbgStatus");
            textBox.Text = text;
            try { window.Owner = owner; } catch (Exception) { }
            var header = (Border)window.FindName("DbgHeader");
            header.MouseLeftButtonDown += (s, e) => VmUi.DragMove(window);
            new VmChrome(window, header, (Button)window.FindName("DbgShrink"));
            new VmThemed(window);
            ((Button)window.FindName("DbgClose")).Click += (s, e) => window.Close();
            ((Button)window.FindName("DbgCopy")).Click += (s, e) =>
            {
                try
                {
                    Clipboard.SetText(textBox.Text);
                    status.Text = "Copied. Paste it into the chat.";
                }
                catch (Exception ex)
                {
                    status.Text = "Copy failed (" + VmCore.Describe(ex) + ") - select the text and press Ctrl+C.";
                }
            };
            ((Button)window.FindName("DbgSave")).Click += (s, e) =>
            {
                try
                {
                    string path = VmCore.DebugPath();
                    File.WriteAllText(path, textBox.Text, new System.Text.UTF8Encoding(false));
                    status.Text = "Saved to " + path;
                }
                catch (Exception ex)
                {
                    status.Text = "Save failed - " + VmCore.Describe(ex);
                }
            };
        }

        /// <summary>Show, never ShowDialog: a modal child would disable Revit's own window too.</summary>
        public void Show() { window.Show(); }
    }

    /// <summary>Level, template and scope box abbreviations, and the tag settings (port of SettingsWindow).</summary>
    internal sealed class VmSettingsWindow
    {
        private const string IconLevel = @"<Path Stretch=""None"" Stroke=""{DynamicResource Blue}"" StrokeThickness=""1.4""
                  Data=""M 1,3 L 15,3 M 1,8 L 15,8 M 1,13 L 15,13 M 12,0.5 L 14,3 L 12,5.5""/>";
        private const string IconTemplate = @"<Path Stretch=""None"" Stroke=""{DynamicResource Green}"" StrokeThickness=""1.3""
                  Data=""M 2,1 L 11,1 L 14,4 L 14,15 L 2,15 Z M 5,6 L 11,6 M 5,9 L 11,9 M 5,12 L 9,12""/>";
        private const string IconBox = @"<Path Stretch=""None"" Stroke=""{DynamicResource Orange}"" StrokeThickness=""1.3""
                  StrokeDashArray=""2 1.4""
                  Data=""M 2,2 L 14,2 L 14,14 L 2,14 Z M 5,5 L 11,5 L 11,11 L 5,11 Z""/>";
        private const string IconTag = @"<Path Stretch=""None"" Stroke=""{DynamicResource Text}"" StrokeThickness=""1.3""
                  Data=""M 1,8 L 5,3 L 15,3 L 15,13 L 5,13 Z M 7.4,8 A 1.2,1.2 0 1 0 7.39,8""/>";

        private static string TabHeader(string icon, string label)
        {
            return @"<TabItem.Header>
          <StackPanel Orientation=""Horizontal"">
            <Grid Width=""16"" Height=""16"" Margin=""0,0,7,0"" VerticalAlignment=""Center"">
              " + icon + @"
            </Grid>
            <TextBlock Text=""" + label + @""" VerticalAlignment=""Center""/>
          </StackPanel>
        </TabItem.Header>";
        }

        private static string AbbrevTabXaml(string p, string icon, string label, string intro, string defaultButton)
        {
            return @"
      <TabItem>
        {header}
        <Grid Margin=""14,12,14,10"">
          <Grid.RowDefinitions>
            <RowDefinition Height=""Auto""/>
            <RowDefinition Height=""Auto""/>
            <RowDefinition Height=""*""/>
            <RowDefinition Height=""Auto""/>
          </Grid.RowDefinitions>
          <TextBlock Grid.Row=""0"" TextWrapping=""Wrap"" Foreground=""{DynamicResource Muted}""
                     Text=""{intro}""/>
          <TextBox x:Name=""{p}Search"" Grid.Row=""1"" Margin=""0,10,0,8""/>
          <Border Grid.Row=""2"" Background=""{DynamicResource Sunken}""
                  BorderBrush=""{DynamicResource Line}"" BorderThickness=""1"">
            <ScrollViewer VerticalScrollBarVisibility=""Auto""
                          HorizontalScrollBarVisibility=""Disabled"">
              <StackPanel x:Name=""{p}List"" Margin=""2,4,2,4""/>
            </ScrollViewer>
          </Border>
          <Border Grid.Row=""3"" Margin=""0,10,0,0"" Background=""{DynamicResource Panel}""
                  BorderBrush=""{DynamicResource Line}"" BorderThickness=""1"">
            <Grid Margin=""12,10,12,10"">
              <Grid.RowDefinitions>
                <RowDefinition Height=""Auto""/>
                <RowDefinition Height=""Auto""/>
              </Grid.RowDefinitions>
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width=""*""/>
                <ColumnDefinition Width=""Auto""/>
                <ColumnDefinition Width=""Auto""/>
                <ColumnDefinition Width=""Auto""/>
              </Grid.ColumnDefinitions>
              <TextBlock x:Name=""{p}Chosen"" Grid.Row=""0"" Grid.ColumnSpan=""4""
                         Text=""Nothing selected"" Foreground=""{DynamicResource Muted}""
                         Margin=""0,0,0,8"" TextTrimming=""CharacterEllipsis""/>
              <TextBox x:Name=""{p}Abbrev"" Grid.Row=""1"" Grid.Column=""0"" IsEnabled=""False""
                       Margin=""0,0,8,0"" MaxLength=""16""/>
              <Button x:Name=""{p}Apply"" Grid.Row=""1"" Grid.Column=""1"" Content=""Set""
                      Style=""{StaticResource GoSmall}"" IsEnabled=""False"" Margin=""0,0,6,0""/>
              <Button x:Name=""{p}Clear"" Grid.Row=""1"" Grid.Column=""2"" Content=""{default}""
                      Style=""{StaticResource Ghost}"" IsEnabled=""False"" Margin=""0,0,10,0""/>
              <Button x:Name=""{p}Reset"" Grid.Row=""1"" Grid.Column=""3"" Content=""Clear all""
                      Style=""{StaticResource Flat}""/>
            </Grid>
          </Border>
        </Grid>
      </TabItem>".Replace("{header}", TabHeader(icon, label)).Replace("{p}", p).Replace("{intro}", intro).Replace("{default}", defaultButton);
        }

        private static string TagTabXaml()
        {
            return @"
      <TabItem>
        {header}
        <StackPanel Margin=""18,16,18,10"">
          <TextBlock Text=""ROOM TAGS"" Style=""{StaticResource Head}"" Margin=""0,0,0,8""/>
          <TextBlock TextWrapping=""Wrap"" Foreground=""{DynamicResource Muted}"" Margin=""0,0,0,14""
                     Text=""With Add room tags ticked, every new view gets a tag on each room its cut plane passes through, inside its crop. Dependent views show their parent's tags, so they are not tagged separately.""/>

          <TextBlock Text=""Room tag"" Margin=""0,0,0,5""/>
          <ComboBox x:Name=""TagType"" Height=""26"" HorizontalAlignment=""Stretch"" Margin=""0,0,0,4""/>
          <TextBlock x:Name=""TagDefaultNote"" Foreground=""{DynamicResource Muted}"" FontSize=""11""
                     TextWrapping=""Wrap"" Margin=""0,0,0,16""/>

          <CheckBox x:Name=""TagOn"" Content=""Tick Add room tags when the tool opens"" Margin=""0,0,0,8""/>
          <CheckBox x:Name=""TagLinks"" Content=""Tag rooms in loaded linked models too"" Margin=""0,0,0,4""/>
          <TextBlock Foreground=""{DynamicResource Muted}"" FontSize=""11"" TextWrapping=""Wrap""
                     Margin=""23,0,0,0""
                     Text=""Rooms usually live in the architect's model. Untick to tag only rooms in this model.""/>
        </StackPanel>
      </TabItem>".Replace("{header}", TabHeader(IconTag, "Tag settings"));
        }

        private static string SettingsXaml()
        {
            string head = @"
<Window xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
        xmlns:x=""http://schemas.microsoft.com/winfx/2006/xaml""
        xmlns:shell=""clr-namespace:System.Windows.Shell;assembly=PresentationFramework""
        Title=""RevoBIM - View Manager settings""
        Height=""660"" Width=""780"" MinHeight=""460"" MinWidth=""600""
        WindowStartupLocation=""CenterOwner""
        WindowStyle=""None"" ResizeMode=""CanResize"" Background=""{DynamicResource WindowBg}"">

  <shell:WindowChrome.WindowChrome>
    <shell:WindowChrome CaptionHeight=""0"" CornerRadius=""0""
                        GlassFrameThickness=""0"" ResizeBorderThickness=""6""/>
  </shell:WindowChrome.WindowChrome>

  <Window.Resources>
    <!--SHARED_RESOURCES-->
  </Window.Resources>

  <Border BorderBrush=""{DynamicResource Line}"" BorderThickness=""1""
          Background=""{DynamicResource WindowBg}"">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height=""38""/>
        <RowDefinition Height=""*""/>
        <RowDefinition Height=""Auto""/>
      </Grid.RowDefinitions>

      <Border x:Name=""SetHeader"" Grid.Row=""0"" Background=""{DynamicResource HeadBar}"">
        <Grid>
          <StackPanel Orientation=""Horizontal"" VerticalAlignment=""Center"" Margin=""12,0,0,0"">
            <TextBlock Text=""RevoBIM"" Foreground=""{DynamicResource Blue}""
                       FontSize=""13"" FontWeight=""Bold""/>
            <TextBlock Text=""  View Manager settings"" FontSize=""13""/>
          </StackPanel>
          <StackPanel Orientation=""Horizontal"" HorizontalAlignment=""Right"">
            <Button x:Name=""ThemeChip"" Style=""{StaticResource ChipButton}"">
              <StackPanel Orientation=""Horizontal"">
                <Grid Width=""12"" Height=""12"" Margin=""0,0,6,0"" VerticalAlignment=""Center"">
                  <Ellipse Stroke=""{DynamicResource Text}"" StrokeThickness=""1.2""/>
                  <Path Fill=""{DynamicResource Text}"" Data=""M 6,0.6 A 5.4,5.4 0 0 0 6,11.4 Z""/>
                </Grid>
                <TextBlock x:Name=""ThemeChipText"" Text=""Auto"" VerticalAlignment=""Center""
                           FontSize=""11""/>
              </StackPanel>
            </Button>
            <Button x:Name=""SetShrink"" Content="""" Style=""{StaticResource ShrinkBtn}"" Height=""38""/>
            <Button x:Name=""SetClose"" Content=""&#x2715;"" Style=""{StaticResource Close}"" Height=""38""/>
          </StackPanel>
        </Grid>
      </Border>

      <TabControl x:Name=""SetTabs"" Grid.Row=""1"">";
            string tail = @"
      </TabControl>

      <Border Grid.Row=""2"" Background=""{DynamicResource HeadBar}""
              BorderBrush=""{DynamicResource Line}"" BorderThickness=""0,1,0,0"">
        <Grid Margin=""14,10,14,10"">
          <TextBlock x:Name=""SetStatus"" Text="""" Foreground=""{DynamicResource Muted}""
                     VerticalAlignment=""Center"" TextTrimming=""CharacterEllipsis""/>
          <Button x:Name=""SetDone"" Content=""Done"" Style=""{StaticResource Ghost}""
                  HorizontalAlignment=""Right""/>
        </Grid>
      </Border>
    </Grid>
  </Border>
</Window>
";
            return head
                + AbbrevTabXaml("Lvl", IconLevel, "Level abbreviations",
                    "Pick a level and give it an abbreviation for view names. Anything not set here follows the rule - F01 and Level 1 read L01, Roof reads LRF. Kept for this project.", "Use rule")
                + AbbrevTabXaml("Tpl", IconTemplate, "Template abbreviations",
                    "Pick a view template and give it an abbreviation. What is set here beats the built-in keywords. Kept for every project on this machine.", "Use keyword")
                + AbbrevTabXaml("Box", IconBox, "Scope box abbreviations",
                    "Pick a scope box and give it an abbreviation. Dependent views are named DEP_host_abbreviation; anything not set here uses the scope box's own name. Kept for this project.", "Use name")
                + TagTabXaml() + tail;
        }

        // ---------------------------------------------------------------- one abbreviation tab --

        private sealed class AbbrevTab
        {
            private readonly VmSettingsWindow owner;
            private readonly List<string> names;
            private readonly Func<string, string[]> detail;       // name -> [abbreviation, source]
            private readonly VmCore.AbbrevStore store;
            private readonly string kind;
            private string chosen;
            private readonly List<KeyValuePair<string, Border>> rows = new List<KeyValuePair<string, Border>>();
            private readonly TextBox search, abbrevBox;
            private readonly StackPanel listPanel;
            private readonly TextBlock chosenLabel;
            private readonly Button btnApply, btnClear;

            public AbbrevTab(VmSettingsWindow owner, string prefix, List<string> names, Func<string, string[]> detail, VmCore.AbbrevStore store, string kind)
            {
                this.owner = owner;
                this.names = names;
                this.detail = detail;
                this.store = store;
                this.kind = kind;
                Window w = owner.window;
                search = (TextBox)w.FindName(prefix + "Search");
                listPanel = (StackPanel)w.FindName(prefix + "List");
                chosenLabel = (TextBlock)w.FindName(prefix + "Chosen");
                abbrevBox = (TextBox)w.FindName(prefix + "Abbrev");
                btnApply = (Button)w.FindName(prefix + "Apply");
                btnClear = (Button)w.FindName(prefix + "Clear");

                search.TextChanged += (s, e) => { try { Build(); } catch (Exception) { } };
                abbrevBox.KeyDown += (s, e) => { try { if (e.Key == Key.Enter) OnApply(); } catch (Exception) { } };
                btnApply.Click += (s, e) => { try { OnApply(); } catch (Exception) { } };
                btnClear.Click += (s, e) => { try { OnClear(); } catch (Exception) { } };
                ((Button)w.FindName(prefix + "Reset")).Click += (s, e) => { try { OnReset(); } catch (Exception) { } };
                Build();
            }

            private Brush BrushOf(string key) { return (Brush)owner.window.Resources[key]; }

            public string CountText()
            {
                int count = store.Items.Count;
                if (count > 0) return count + " " + kind + " abbreviation(s) set by hand - saved to " + store.Path();
                return "No " + kind + " abbreviations set by hand.";
            }

            private static string Note(string source)
            {
                if (source == "override") return "   set by hand";
                if (source == "fallback") return "   no keyword";
                return "";
            }

            public void Build()
            {
                listPanel.Children.Clear();
                rows.Clear();
                string kw = "";
                try { kw = (search.Text ?? "").ToLowerInvariant().Trim(); } catch (Exception) { }
                int shown = 0;
                foreach (string name in names)
                {
                    string[] d = detail(name);
                    string abbr = d[0], source = d[1];
                    if (kw.Length > 0 && !name.ToLowerInvariant().Contains(kw) && !(abbr ?? "").ToLowerInvariant().Contains(kw)) continue;

                    var row = new Border { Background = Brushes.Transparent, Padding = new Thickness(8, 4, 8, 4) };       // or it is not hit testable
                    var panel = new StackPanel { Orientation = Orientation.Horizontal };
                    var chip = new TextBlock
                    {
                        Text = abbr,
                        Width = 96,
                        FontFamily = new FontFamily("Consolas"),
                        FontSize = 11.5,
                        VerticalAlignment = VerticalAlignment.Center,
                        TextTrimming = TextTrimming.CharacterEllipsis,
                    };
                    if (source == "override")
                    {
                        chip.Foreground = BrushOf("Orange");
                        chip.FontWeight = FontWeights.SemiBold;
                    }
                    else if (source == "fallback") chip.Foreground = BrushOf("Muted");
                    else chip.Foreground = BrushOf("Text");
                    var label = new TextBlock { Text = name, VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis };
                    var note = new TextBlock { Text = Note(source), Foreground = BrushOf("Muted"), FontSize = 10.5, VerticalAlignment = VerticalAlignment.Center };
                    panel.Children.Add(chip);
                    panel.Children.Add(label);
                    panel.Children.Add(note);
                    row.Child = panel;

                    int index = rows.Count;
                    rows.Add(new KeyValuePair<string, Border>(name, row));
                    row.MouseLeftButtonDown += (s, e) => Select(index);
                    listPanel.Children.Add(row);
                    shown++;
                }
                if (shown == 0) listPanel.Children.Add(new TextBlock { Text = "  Nothing matches.", Foreground = BrushOf("Muted") });
                if (chosen != null)
                {
                    for (int i = 0; i < rows.Count; i++)
                        if (rows[i].Key == chosen) { Paint(i); break; }
                }
            }

            private void Paint(int index)
            {
                for (int i = 0; i < rows.Count; i++)
                {
                    try { rows[i].Value.Background = i == index ? BrushOf("Selection") : Brushes.Transparent; } catch (Exception) { }
                }
            }

            private void Select(int index)
            {
                if (index >= rows.Count) return;
                chosen = rows[index].Key;
                Paint(index);
                string[] d = detail(chosen);
                chosenLabel.Text = chosen;
                chosenLabel.Foreground = BrushOf("Text");
                abbrevBox.Text = d[0];
                abbrevBox.IsEnabled = true;
                btnApply.IsEnabled = true;
                btnClear.IsEnabled = d[1] == "override";
                try
                {
                    abbrevBox.Focus();
                    abbrevBox.SelectAll();
                }
                catch (Exception) { }
            }

            private bool Commit(string message)
            {
                string note;
                if (!store.Save(out note))
                {
                    owner.Say("Could not save - " + note);
                    return false;
                }
                Build();
                owner.Changed();
                owner.Say(message);
                return true;
            }

            private void OnApply()
            {
                if (chosen == null) return;
                string value = "";
                try { value = VmCore.Sanitise((abbrevBox.Text ?? "").Trim()); } catch (Exception) { }
                if (value.Length == 0)
                {
                    owner.Say("Type an abbreviation first, or press " + btnClear.Content + ".");
                    return;
                }
                store.Items[chosen] = value;
                if (Commit(chosen + "  ->  " + value)) btnClear.IsEnabled = true;
            }

            private void OnClear()
            {
                if (chosen == null || !store.Items.ContainsKey(chosen)) return;
                string name = chosen;
                store.Items.Remove(name);
                string abbr = detail(name)[0];
                if (Commit(name + " is back to the default  ->  " + abbr))
                {
                    abbrevBox.Text = abbr;
                    btnClear.IsEnabled = false;
                }
            }

            private void OnReset()
            {
                if (store.Items.Count == 0)
                {
                    owner.Say("No " + kind + " abbreviations set by hand to clear.");
                    return;
                }
                int count = store.Items.Count;
                store.Items.Clear();
                if (Commit("Cleared " + count + " " + kind + " abbreviation(s)."))
                {
                    btnClear.IsEnabled = false;
                    if (chosen != null) abbrevBox.Text = detail(chosen)[0];
                }
            }
        }

        // ---------------------------------------------------------------- the window --

        private readonly Window window;
        private readonly VmWindow main;
        private readonly Action onChanged;
        private readonly TextBlock status;
        private readonly TabControl tabs;
        private readonly List<AbbrevTab> pages = new List<AbbrevTab>();
        private readonly ComboBox tagCombo;
        private readonly TextBlock tagNote;
        private readonly CheckBox tagOn, tagLinks;
        private readonly List<Autodesk.Revit.DB.Element> tagTypes;
        private bool loading = true;

        public VmSettingsWindow(VmWindow main, Window ownerWindow, List<Autodesk.Revit.DB.View> templates, List<Autodesk.Revit.DB.Level> levels,
                                List<Autodesk.Revit.DB.Element> boxes, Action onChanged, int startTab)
        {
            this.main = main;
            this.onChanged = onChanged;
            window = VmUi.LoadWindow(SettingsXaml());
            status = (TextBlock)window.FindName("SetStatus");
            tabs = (TabControl)window.FindName("SetTabs");
            try { window.Owner = ownerWindow; } catch (Exception) { }

            var header = (Border)window.FindName("SetHeader");
            header.MouseLeftButtonDown += (s, e) => VmUi.DragMove(window);
            ((Button)window.FindName("SetClose")).Click += (s, e) => window.Close();
            ((Button)window.FindName("SetDone")).Click += (s, e) => window.Close();
            new VmChrome(window, header, (Button)window.FindName("SetShrink"));

            VmThemed themed = null;
            pages.Add(new AbbrevTab(this, "Lvl", levels.Select(l => l.Name).ToList(), n => { string src; string a = VmCore.LevelAbbrDetail(n, out src); return new[] { a, src }; }, VmCore.LevelStore, "level"));
            pages.Add(new AbbrevTab(this, "Tpl", templates.Select(t => t.Name).ToList(), n => { string src; string a = VmCore.AbbreviateDetail(n, out src); return new[] { a, src }; }, VmCore.TemplateStore, "template"));
            pages.Add(new AbbrevTab(this, "Box", boxes.Select(b => b.Name).ToList(), n => { string src; string a = VmCore.BoxAbbrDetail(n, out src); return new[] { a, src }; }, VmCore.BoxStore, "scope box"));
            themed = new VmThemed(window, OnTheme);

            tagCombo = (ComboBox)window.FindName("TagType");
            tagNote = (TextBlock)window.FindName("TagDefaultNote");
            tagOn = (CheckBox)window.FindName("TagOn");
            tagLinks = (CheckBox)window.FindName("TagLinks");
            tagTypes = VmRevit.CollectRoomTagTypes(main.Doc);
            FillTagTypes();
            tagOn.IsChecked = VmCore.SettingOn("room_tags_on");
            tagLinks.IsChecked = VmCore.SettingOn("room_tags_links");
            tagCombo.SelectionChanged += (s, e) => { try { OnTagType(); } catch (Exception) { } };
            RoutedEventHandler flags = (s, e) => { try { OnTagFlags(); } catch (Exception) { } };
            tagOn.Checked += flags;
            tagOn.Unchecked += flags;
            tagLinks.Checked += flags;
            tagLinks.Unchecked += flags;
            tabs.SelectionChanged += (s, e) => { try { OnTab(s); } catch (Exception) { } };
            try { tabs.SelectedIndex = startTab; } catch (Exception) { }
            loading = false;
            OnTab(tabs);
        }

        private void Say(string text)
        {
            try { status.Text = text; } catch (Exception) { }
        }

        private void Changed()
        {
            if (onChanged == null) return;
            try { onChanged(); } catch (Exception) { }
        }

        private void OnTheme()
        {
            foreach (AbbrevTab page in pages)
            {
                try { page.Build(); } catch (Exception) { }
            }
        }

        private void OnTab(object sender)
        {
            if (!ReferenceEquals(sender, tabs)) return;
            int index = tabs.SelectedIndex;
            if (index >= 0 && index < pages.Count) Say(pages[index].CountText());
            else Say("Saved to " + VmCore.SettingsPath());
        }

        private void FillTagTypes()
        {
            tagCombo.Items.Clear();
            ElementIdHolder defaultHolder = new ElementIdHolder(VmRevit.DefaultRoomTagId(main.Doc));
            string defaultLabel = "";
            if (defaultHolder.Id != null)
            {
                Autodesk.Revit.DB.Element element = main.Doc.GetElement(defaultHolder.Id);
                if (element != null) defaultLabel = VmRevit.RoomTagLabel(element);
            }
            string first = defaultLabel.Length > 0 ? "<Project default>  (" + defaultLabel + ")" : "<Project default>";
            tagCombo.Items.Add(first);
            string wanted = (VmCore.Get("room_tag_type") ?? "").Trim();
            int index = 0;
            for (int i = 0; i < tagTypes.Count; i++)
            {
                string label = VmRevit.RoomTagLabel(tagTypes[i]);
                tagCombo.Items.Add(label);
                if (label == wanted) index = i + 1;
            }
            tagCombo.SelectedIndex = index;
            if (tagTypes.Count == 0) tagNote.Text = "No room tag family is loaded in this project.";
            else if (wanted.Length > 0 && index == 0) tagNote.Text = "'" + wanted + "' is not loaded in this project, so the project default is used here.";
            else tagNote.Text = "Kept for every project on this machine.";
        }

        private sealed class ElementIdHolder
        {
            public readonly Autodesk.Revit.DB.ElementId Id;
            public ElementIdHolder(Autodesk.Revit.DB.ElementId id) { Id = id; }
        }

        private void OnTagType()
        {
            if (loading) return;
            int index = tagCombo.SelectedIndex;
            string label;
            if (index <= 0)
            {
                VmCore.Settings["room_tag_type"] = "";
                label = "the project default";
            }
            else
            {
                label = VmRevit.RoomTagLabel(tagTypes[index - 1]);
                VmCore.Settings["room_tag_type"] = label;
            }
            string note;
            bool saved = VmCore.SaveSettings(out note);
            Say(saved ? "Room tag: " + label : "Could not save - " + note);
            tagNote.Text = "Kept for every project on this machine.";
            Changed();
        }

        private void OnTagFlags()
        {
            if (loading) return;
            VmCore.Settings["room_tags_on"] = tagOn.IsChecked == true ? "1" : "0";
            VmCore.Settings["room_tags_links"] = tagLinks.IsChecked == true ? "1" : "0";
            string note;
            bool saved = VmCore.SaveSettings(out note);
            Say(saved ? "Tag settings saved." : "Could not save - " + note);
            Changed();
        }

        /// <summary>Show, never ShowDialog: a modal child disables Revit's own window.</summary>
        public void Show() { window.Show(); }
    }
}
