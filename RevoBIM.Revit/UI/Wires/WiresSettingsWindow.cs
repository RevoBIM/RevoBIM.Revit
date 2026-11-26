using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.Wires;

using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using Control = System.Windows.Controls.Control;
using Grid = System.Windows.Controls.Grid;
using Orientation = System.Windows.Controls.Orientation;
using Panel = System.Windows.Controls.Panel;
using Visibility = System.Windows.Visibility;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.Wires
{
    /// <summary>
    /// The settings window (settings_window.py). Every control is built from the settings schema, so adding a setting - the power rules still to come, above all -
    /// means adding one row to that table and nothing else. Standalone and modal, tabbed so each section fits without scrolling.
    /// </summary>
    internal sealed class WiresSettingsWindow
    {
        private sealed class Control_
        {
            public string Kind;
            public object Control;     // CheckBox, TextBox, ComboBox or List<KeyValuePair<string, CheckBox>>
            public string Extra;
            public List<string> Values = new List<string>();   // a dropdown's values, parallel to its items
        }

        private readonly UIApplication uiapp;
        private readonly Document doc;
        private readonly Window window;
        private readonly Dictionary<string, Control_> controls = new Dictionary<string, Control_>();
        private readonly Dictionary<string, object> cache = new Dictionary<string, object>();
        private readonly List<string> lookupNotes = new List<string>();
        private readonly Dictionary<string, Button> tabButtons = new Dictionary<string, Button>();
        private readonly Dictionary<string, UIElement> tabPanels = new Dictionary<string, UIElement>();
        private List<string> cachedWireTypes, cachedLineStyles, cachedParameters;
        private List<Tuple<string, string, FamilySymbol>> cachedTags;

        public WiresSettingsWindow(UIApplication uiapp)
        {
            this.uiapp = uiapp;
            try { doc = uiapp.ActiveUIDocument.Document; } catch (Exception) { doc = null; }
            window = WiresUi.LoadWindow("WiresSettings.xaml");
            WiresUi.DressHeader(window, true);
            WiresUi.OwnedByRevit(window, uiapp);
            Build();
            Fill(WiresSettings.Load());
            WireButtons();
            LinkTagDropdowns();
            ShowTab(WiresSettings.Tabs[0]);
            if (lookupNotes.Count > 0) Status(string.Join(" ", lookupNotes));
        }

        // -- lists that come out of the model. Each keeps the reason it came back empty, so the dialog can say "no wire tag family is loaded" rather than a flatly wrong "none".
        private void Remember(string note)
        {
            if (!string.IsNullOrEmpty(note) && !lookupNotes.Contains(note)) lookupNotes.Add(note);
        }

        private List<string> WireTypeLabels()
        {
            if (doc == null)
            {
                Remember("No document is open, so wire types cannot be read.");
                return new List<string>();
            }
            if (cachedWireTypes == null)
            {
                string note;
                List<KeyValuePair<string, Element>> pairs = WiresModel.WireTypes(doc, out note);
                cachedWireTypes = pairs.Select(p => p.Key).ToList();
                if (pairs.Count == 0) Remember("Wire types: " + note + ".");
            }
            return cachedWireTypes;
        }

        private List<Tuple<string, string, FamilySymbol>> TagRows()
        {
            if (doc == null) return new List<Tuple<string, string, FamilySymbol>>();
            if (cachedTags == null)
            {
                string note;
                cachedTags = WiresModel.WireTagTypes(doc, out note);
                if (cachedTags.Count == 0) Remember("Wire tags: " + note + ".");
            }
            return cachedTags;
        }

        private List<string> TagFamilyLabels()
        {
            var names = new List<string>();
            foreach (var row in TagRows()) if (!names.Contains(row.Item1)) names.Add(row.Item1);
            return names;
        }

        private List<string> TagTypeLabels(string family)
        {
            List<Tuple<string, string, FamilySymbol>> rows = TagRows();
            if (!string.IsNullOrEmpty(family))
            {
                List<string> names = rows.Where(r => r.Item1 == family).Select(r => r.Item2).ToList();
                if (names.Count > 0) return names;
            }
            return rows.Select(r => r.Item2).ToList();
        }

        private List<string> LineStyleLabels()
        {
            if (cachedLineStyles == null)
            {
                var labels = new List<string>();
                if (doc != null)
                {
                    string note;
                    List<KeyValuePair<string, GraphicsStyle>> pairs = WiresModel.LineStyles(doc, out note);
                    if (pairs.Count == 0) Remember("Line styles: " + note + ".");
                    labels = pairs.Select(p => p.Key).ToList();
                }
                cachedLineStyles = labels;
            }
            return cachedLineStyles.ToList();
        }

        /// <summary>
        /// Parameters carried by the lighting fittings in this model. The saved value is always offered even when nothing in the model carries it - the parameter may
        /// simply not have been added yet, and a dropdown that silently dropped the house standard would be worse.
        /// </summary>
        private List<string> ParameterLabels()
        {
            if (cachedParameters == null)
            {
                var names = new List<string>();
                if (doc != null)
                {
                    Dictionary<string, string> settings = WiresSettings.Load();
                    List<BuiltInCategory> categories = WiresSettings.CategoriesFrom(WiresSettings.Get(settings, "lighting_categories", "lighting_fixtures"), null);
                    names = WiresModel.FittingParameterNames(doc, categories);
                    if (names.Count == 0) Remember("No lighting fitting parameters could be read - is there a lighting fixture in this model?");
                }
                cachedParameters = names;
            }
            List<string> result = cachedParameters.ToList();
            foreach (string wanted in new[] { WiresSettings.Get(WiresSettings.Load(), "emergency_parameter"), WiresSettings.Defaults()["emergency_parameter"] })
                if (!string.IsNullOrEmpty(wanted) && !result.Contains(wanted)) result.Insert(0, wanted);
            return result;
        }

        /// <summary>The value a dropdown is sitting on right now.</summary>
        private string Current(string key)
        {
            Control_ entry;
            if (!controls.TryGetValue(key, out entry)) return "";
            try
            {
                int index = ((ComboBox)entry.Control).SelectedIndex;
                if (index >= 0 && index < entry.Values.Count) return entry.Values[index];
            }
            catch (Exception)
            {
            }
            return "";
        }

        // -- building
        private void Build()
        {
            var strip = window.FindName("TabStrip") as Panel;
            var body = window.FindName("TabBody") as Panel;
            if (strip == null || body == null) return;
            foreach (string tab in WiresSettings.Tabs)
            {
                var button = new Button { Content = tab, Tag = tab };
                try { button.Style = (Style)window.FindResource("TabBtn"); } catch (Exception) { }
                string name = tab;
                button.Click += (s, a) => ShowTab(name);
                strip.Children.Add(button);
                tabButtons[tab] = button;
                UIElement panel = BuildTab(tab);
                panel.Visibility = Visibility.Collapsed;
                body.Children.Add(panel);
                tabPanels[tab] = panel;
            }
        }

        /// <summary>Two columns of sections, balanced by how many rows each holds.</summary>
        private UIElement BuildTab(string tab)
        {
            var sections = new List<KeyValuePair<string, List<SettingRow>>>();
            foreach (SettingRow row in WiresSettings.Schema)
            {
                if (row.Tab != tab) continue;
                if (sections.Count == 0 || sections[sections.Count - 1].Key != row.Section)
                    sections.Add(new KeyValuePair<string, List<SettingRow>>(row.Section, new List<SettingRow>()));
                sections[sections.Count - 1].Value.Add(row);
            }
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(14) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var columns = new[] { new StackPanel(), new StackPanel() };
            var weights = new[] { 0, 0 };
            foreach (var section in sections)
            {
                int side = weights[0] <= weights[1] ? 0 : 1;
                weights[side] += section.Value.Count + 2;
                columns[side].Children.Add(BuildSection(section.Key, section.Value, side));
            }
            for (int i = 0; i < columns.Length; i++)
            {
                Grid.SetColumn(columns[i], i == 0 ? 0 : 2);
                grid.Children.Add(columns[i]);
            }
            return grid;
        }

        private UIElement BuildSection(string name, List<SettingRow> rows, int side)
        {
            var card = new Border { BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(4), Padding = new Thickness(12, 10, 12, 10), Margin = new Thickness(0, 0, 0, 12) };
            WiresUi.Paint(card, Border.BackgroundProperty, "Card");
            WiresUi.Paint(card, Border.BorderBrushProperty, "Edge");
            var stack = new StackPanel();
            var heading = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 6) };
            var tick = new Border { Width = 4, Height = 16, CornerRadius = new CornerRadius(2), Margin = new Thickness(0, 0, 8, 0) };
            WiresUi.Paint(tick, Border.BackgroundProperty, side == 0 ? "Blue" : "Orange");
            heading.Children.Add(tick);
            var label = new TextBlock { Text = name, FontSize = 13 };
            WiresUi.Paint(label, TextBlock.ForegroundProperty, "Fg");
            heading.Children.Add(label);
            stack.Children.Add(heading);
            foreach (SettingRow row in rows)
                foreach (UIElement child in BuildRow(row)) stack.Children.Add(child);
            card.Child = stack;
            return card;
        }

        private TextBlock LabelBlock(string text)
        {
            var block = new TextBlock { Text = text, FontSize = 12, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 8, 0) };
            WiresUi.Paint(block, TextBlock.ForegroundProperty, "Fg");
            return block;
        }

        private UIElement Pair(string label, UIElement control, double width)
        {
            var grid = new Grid { Margin = new Thickness(0, 3, 0, 3) };
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(width) });
            TextBlock block = LabelBlock(label);
            Grid.SetColumn(block, 0);
            grid.Children.Add(block);
            Grid.SetColumn(control, 1);
            grid.Children.Add(control);
            return grid;
        }

        private List<UIElement> BuildRow(SettingRow row)
        {
            var made = new List<UIElement>();
            string kind = row.Kind;
            if (kind == "note")
            {
                made.Add(WiresUi.Hint(row.Extra));
                return made;
            }
            if (kind == "check" || kind == "warn")
            {
                var box = new CheckBox { Content = row.Label };
                if (kind == "warn")
                {
                    try { box.Style = (Style)window.FindResource("CheckWarn"); } catch (Exception) { }
                }
                controls[row.Key] = new Control_ { Kind = kind, Control = box, Extra = row.Extra };
                made.Add(box);
            }
            else if (kind == "number" || kind == "text")
            {
                var field = new TextBox();
                controls[row.Key] = new Control_ { Kind = kind, Control = field, Extra = row.Extra };
                made.Add(Pair(row.Label, field, kind == "number" ? 90 : 150));
            }
            else if (kind == "choice" || kind == "wiretype" || kind == "tagfamily" || kind == "tagtype" || kind == "parameter" || kind == "linestyle")
            {
                var combo = new ComboBox();
                controls[row.Key] = new Control_ { Kind = kind, Control = combo, Extra = row.Extra };
                made.Add(Pair(row.Label, combo, 200));
            }
            else if (kind == "categories")
            {
                made.Add(LabelBlock(row.Label));
                var frame = new Border { BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(3), Height = 116, Margin = new Thickness(0, 3, 0, 3) };
                WiresUi.Paint(frame, Border.BackgroundProperty, "Field");
                WiresUi.Paint(frame, Border.BorderBrushProperty, "Edge");
                var viewer = new ScrollViewer { Padding = new Thickness(8, 6, 8, 6) };
                var panel = new StackPanel();
                var boxes = new List<KeyValuePair<string, CheckBox>>();
                foreach (CategoryDef def in WiresSettings.CategoryDefs)
                {
                    bool available = WiresSettings.BuiltinCategory(def.BicName) != null;
                    var box = new CheckBox { Content = available ? def.Label : def.Label + "  (not on this release)", IsEnabled = available };
                    boxes.Add(new KeyValuePair<string, CheckBox>(def.Key, box));
                    panel.Children.Add(box);
                }
                viewer.Content = panel;
                frame.Child = viewer;
                controls[row.Key] = new Control_ { Kind = kind, Control = boxes, Extra = row.Extra };
                made.Add(frame);
            }
            if (!string.IsNullOrEmpty(row.Extra) && kind != "note")
            {
                if (kind != "choice" || row.Extra.IndexOf('=') < 0) made.Add(WiresUi.Hint(row.Extra));
            }
            return made;
        }

        // -- choice options
        /// <summary>(value, label) pairs for a dropdown.</summary>
        private List<KeyValuePair<string, string>> OptionsFor(string kind, string extra)
        {
            Func<IEnumerable<string>, List<KeyValuePair<string, string>>> same = labels => labels.Select(l => new KeyValuePair<string, string>(l, l)).ToList();
            if (kind == "wiretype")
            {
                List<string> labels = WireTypeLabels();
                return labels.Count == 0 ? new List<KeyValuePair<string, string>> { new KeyValuePair<string, string>("", "None found - see the note below") } : same(labels);
            }
            if (kind == "tagfamily")
            {
                List<string> labels = TagFamilyLabels();
                return labels.Count == 0 ? new List<KeyValuePair<string, string>> { new KeyValuePair<string, string>("", "No wire tag family loaded") } : same(labels);
            }
            if (kind == "tagtype")
            {
                List<string> labels = TagTypeLabels(Current("wire_tag_family"));
                return labels.Count == 0 ? new List<KeyValuePair<string, string>> { new KeyValuePair<string, string>("", "No wire tag family loaded") } : same(labels);
            }
            if (kind == "parameter") return same(ParameterLabels());
            if (kind == "linestyle")
            {
                List<string> labels = LineStyleLabels();
                if (labels.Count == 0) return new List<KeyValuePair<string, string>> { new KeyValuePair<string, string>("", "No line styles found") };
                var list = new List<KeyValuePair<string, string>> { new KeyValuePair<string, string>("", "<the view default>") };
                list.AddRange(same(labels));
                return list;
            }
            var options = new List<KeyValuePair<string, string>>();
            foreach (string raw in (extra ?? "").Split('|'))
            {
                string part = raw.Trim();
                if (part.Length == 0) continue;
                int eq = part.IndexOf('=');
                if (eq >= 0) options.Add(new KeyValuePair<string, string>(part.Substring(0, eq).Trim(), part.Substring(eq + 1).Trim()));
                else options.Add(new KeyValuePair<string, string>(part, part));
            }
            return options;
        }

        private void FillCombo(Control_ entry, string kind, string value)
        {
            var combo = (ComboBox)entry.Control;
            List<KeyValuePair<string, string>> options = OptionsFor(kind, entry.Extra);
            combo.Items.Clear();
            entry.Values = options.Select(o => o.Key).ToList();
            foreach (var option in options) combo.Items.Add(option.Value);
            int index = 0;
            for (int i = 0; i < options.Count; i++)
            {
                if (options[i].Key == value)
                {
                    index = i;
                    break;
                }
            }
            combo.SelectedIndex = index;
        }

        // -- filling and reading
        private void Fill(Dictionary<string, string> settings)
        {
            Dictionary<string, string> defaults = WiresSettings.Defaults();
            foreach (var entry in controls)
            {
                Control_ c = entry.Value;
                string d;
                string value = WiresSettings.Get(settings, entry.Key, defaults.TryGetValue(entry.Key, out d) ? d : "");
                try
                {
                    if (c.Kind == "check" || c.Kind == "warn")
                    {
                        string v = value.Trim().ToLowerInvariant();
                        ((CheckBox)c.Control).IsChecked = v == "yes" || v == "true" || v == "1" || v == "on";
                    }
                    else if (c.Kind == "number" || c.Kind == "text") ((TextBox)c.Control).Text = value;
                    else if (c.Kind == "categories")
                    {
                        var wanted = value.Split(',').Select(k => k.Trim()).Where(k => k.Length > 0).ToList();
                        foreach (var pair in (List<KeyValuePair<string, CheckBox>>)c.Control) pair.Value.IsChecked = wanted.Contains(pair.Key);
                    }
                    else FillCombo(c, c.Kind, value);
                }
                catch (Exception)
                {
                }
            }
        }

        private static string Number(string text, string fallback)
        {
            double value;
            if (double.TryParse((text ?? "").Trim(), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out value) && value >= 0)
                return value.ToString("0.######", System.Globalization.CultureInfo.InvariantCulture);
            return fallback;
        }

        private Dictionary<string, string> Collect()
        {
            Dictionary<string, string> settings = WiresSettings.Load();
            Dictionary<string, string> defaults = WiresSettings.Defaults();
            foreach (var entry in controls)
            {
                Control_ c = entry.Value;
                string key = entry.Key;
                try
                {
                    if (c.Kind == "check" || c.Kind == "warn") settings[key] = ((CheckBox)c.Control).IsChecked == true ? "yes" : "no";
                    else if (c.Kind == "number")
                    {
                        string d;
                        settings[key] = Number(((TextBox)c.Control).Text, defaults.TryGetValue(key, out d) ? d : "0");
                    }
                    else if (c.Kind == "text") settings[key] = (((TextBox)c.Control).Text ?? "").Trim();
                    else if (c.Kind == "categories")
                    {
                        var ticked = ((List<KeyValuePair<string, CheckBox>>)c.Control).Where(p => p.Value.IsChecked == true && p.Value.IsEnabled).Select(p => p.Key).ToList();
                        if (ticked.Count > 0) settings[key] = string.Join(",", ticked);
                    }
                    else
                    {
                        int index = ((ComboBox)c.Control).SelectedIndex;
                        if (index >= 0 && index < c.Values.Count) settings[key] = c.Values[index];
                    }
                }
                catch (Exception)
                {
                }
            }
            return settings;
        }

        // -- behaviour
        private void ShowTab(string tab)
        {
            foreach (var entry in tabPanels)
            {
                try { entry.Value.Visibility = entry.Key == tab ? Visibility.Visible : Visibility.Collapsed; } catch (Exception) { }
            }
            foreach (var entry in tabButtons)
            {
                try
                {
                    if (entry.Key == tab)
                    {
                        WiresUi.Paint(entry.Value, Control.BorderBrushProperty, "Blue");
                        WiresUi.Paint(entry.Value, Control.ForegroundProperty, "Fg");
                    }
                    else
                    {
                        // back to the TabBtn style: no underline, muted text
                        entry.Value.ClearValue(Control.BorderBrushProperty);
                        entry.Value.ClearValue(Control.ForegroundProperty);
                    }
                }
                catch (Exception)
                {
                }
            }
        }

        /// <summary>The type list follows the family - they are not independent.</summary>
        private void LinkTagDropdowns()
        {
            Control_ entry;
            if (!controls.TryGetValue("wire_tag_family", out entry)) return;
            try
            {
                ((ComboBox)entry.Control).SelectionChanged += (s, a) =>
                {
                    Control_ typeEntry;
                    if (!controls.TryGetValue("wire_tag_type", out typeEntry)) return;
                    string wanted = Current("wire_tag_type");
                    try { FillCombo(typeEntry, "tagtype", wanted); } catch (Exception) { }
                };
            }
            catch (Exception)
            {
            }
        }

        private void Status(string text)
        {
            WiresUi.SetText(window, "StatusText", text);
        }

        private void WireButtons()
        {
            Action<string, Action> wire = (name, action) =>
            {
                try
                {
                    var button = window.FindName(name) as Button;
                    if (button != null) button.Click += (s, a) => action();
                }
                catch (Exception)
                {
                }
            };
            wire("ApplyButton", () =>
            {
                if (WiresSettings.Save(Collect()))
                {
                    try { window.Close(); } catch (Exception) { }
                }
                else Status("Could not write " + WiresSettings.SettingsPath());
            });
            wire("CancelButton", () => { try { window.Close(); } catch (Exception) { } });
            wire("DefaultsButton", () =>
            {
                Fill(WiresSettings.Defaults());
                Status("Defaults loaded on every tab. Apply to keep them.");
            });
            wire("ShortcutsButton", () =>
            {
                // close first, then post - a posted command waits on the modal
                try { window.Close(); } catch (Exception) { }
                try
                {
                    RevitCommandId command = RevitCommandId.LookupPostableCommandId(PostableCommand.KeyboardShortcuts);
                    if (command != null) uiapp.PostCommand(command);
                }
                catch (Exception)
                {
                }
            });
        }

        public void Show()
        {
            try
            {
                window.ShowDialog();
            }
            catch (Exception)
            {
            }
        }
    }
}
