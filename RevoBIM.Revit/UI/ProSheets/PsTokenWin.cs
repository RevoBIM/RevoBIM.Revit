using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// The subfolder parameter picker. Port of ps_tokenwin.py.
    ///
    /// The Create tab used to borrow the Custom File Name dialog for this, which
    /// was wrong in a way that is obvious once you see it: naming a file and
    /// building a folder tree are different jobs. A file name is one string with
    /// prefixes, suffixes and separators; a folder path is a stack of levels.
    ///
    /// So this is its own window: a searchable list of every sheet and project
    /// parameter plus the date and time tokens, and two buttons - add as a folder
    /// level, or add to the level being built.
    ///
    /// The preview underneath is resolved against a real sheet, so an empty
    /// parameter shows up here rather than as a folder called "_unset" after two
    /// hundred files have gone into it.
    /// </summary>
    public static partial class PsTokenWin
    {
        public const string AllGroups = "All";

        /// <summary>Modal. Show() returns the finished token string, or null when cancelled.</summary>
        public class TokenWindow
        {
            public List<(string Name, string Group)> Catalogue;
            public Func<string, string> SampleLookup;
            public string Result;

            public Window Window;
            public PsUi.Chrome Chrome;
            public DataGrid Grid;
            public ComboBox GroupCombo;
            public TextBox SearchBox;
            public TextBox StringBox;
            public TextBlock Preview;
            public List<(string Name, string Group, string Sample)> Entries;
            public DataTable Table;

            public TokenWindow(IEnumerable<(string Name, string Group)> catalogue, Func<string, string> sampleLookup,
                string current = "", string themeName = "dark", Window owner = null, string sampleLabel = "")
            {
                Catalogue = catalogue != null ? catalogue.ToList() : new List<(string Name, string Group)>();
                SampleLookup = sampleLookup;
                Result = null;

                Window = PsUi.LoadWindow("ProSheetsTokens.xaml", themeName);
                Chrome = new PsUi.Chrome(Window, onClose: Cancel);
                if (owner != null)
                {
                    try
                    {
                        Window.Owner = owner;
                    }
                    catch (Exception)
                    {
                    }
                }

                Grid = PsUi.Find<DataGrid>(Window, "TokenGrid");
                GroupCombo = PsUi.Find<ComboBox>(Window, "TokenGroupCombo");
                SearchBox = PsUi.Find<TextBox>(Window, "TokenSearchBox");
                StringBox = PsUi.Find<TextBox>(Window, "TokenStringBox");
                Preview = PsUi.Find<TextBlock>(Window, "TokenPreview");

                Entries = PsPaths.TokenCatalogue(Catalogue);

                Table = new DataTable("tokens");
                foreach (string name in new[] { "pname", "pgroup", "sample" })
                    Table.Columns.Add(name, typeof(string));
                try
                {
                    Grid.ItemsSource = Table.DefaultView;
                }
                catch (Exception)
                {
                }

                if (!string.IsNullOrEmpty(sampleLabel))
                    PsUi.SetText(PsUi.Find(Window, "TokenHint"),
                        string.Format("Values shown are from {0}. Double click a row to add it as a folder level.",
                            sampleLabel));

                try
                {
                    StringBox.Text = current ?? "";
                }
                catch (Exception)
                {
                }

                FillGroups();
                FillRows();
                Wire();
                RefreshPreview();
            }

            // ------------------------------------------------------------- the list
            internal void FillGroups()
            {
                var groups = new List<string>();
                foreach (var (_, group, _) in Entries)
                {
                    if (!groups.Contains(group)) groups.Add(group);
                }
                groups = groups.OrderBy(g => g != "Date and time")
                    .ThenBy(g => (g ?? "").ToLowerInvariant(), StringComparer.Ordinal)
                    .ToList();
                var offered = new List<string> { AllGroups };
                offered.AddRange(groups);
                PsUi.FillCombo(GroupCombo, offered, selected: AllGroups);
            }

            internal string SampleFor(string name, string canned)
            {
                if (!string.IsNullOrEmpty(canned)) return canned;
                string stamped = PsPaths.TimeToken(name);
                if (stamped != null) return stamped;
                if (SampleLookup == null) return "";
                string value;
                try
                {
                    value = SampleLookup(name);
                }
                catch (Exception)
                {
                    value = "";
                }
                string text = value ?? "";
                if (text.Length == 0) return "(empty)";
                return text.Length <= 40 ? text : text.Substring(0, 37) + "...";
            }

            internal void FillRows()
            {
                string group = PsUi.ComboText(GroupCombo);
                if (string.IsNullOrEmpty(group)) group = AllGroups;
                string needle;
                try
                {
                    needle = (SearchBox.Text ?? "").Trim().ToLowerInvariant();
                }
                catch (Exception)
                {
                    needle = "";
                }
                try
                {
                    Table.Rows.Clear();
                    foreach (var (name, owningGroup, canned) in Entries)
                    {
                        if (group != AllGroups && owningGroup != group) continue;
                        if (needle.Length > 0 && !(name ?? "").ToLowerInvariant().Contains(needle)) continue;
                        DataRow row = Table.NewRow();
                        row["pname"] = name;
                        row["pgroup"] = owningGroup;
                        row["sample"] = SampleFor(name, canned);
                        Table.Rows.Add(row);
                    }
                }
                catch (Exception)
                {
                }
                PsUi.SetText(PsUi.Find(Window, "StatusText"), string.Format("{0} showing", Table.Rows.Count));
            }

            // ------------------------------------------------------------- the string
            internal List<string> ChosenNames()
            {
                var found = new List<string>();
                if (Grid == null) return found;
                try
                {
                    foreach (object item in Grid.SelectedItems)
                    {
                        DataRow row = (item as DataRowView)?.Row;
                        if (row == null) continue;
                        found.Add(PsNameWin.Cell(row, "pname"));
                    }
                }
                catch (Exception)
                {
                    return new List<string>();
                }
                return found;
            }

            internal string Current()
            {
                try
                {
                    return StringBox.Text ?? "";
                }
                catch (Exception)
                {
                    return "";
                }
            }

            internal void SetCurrent(string text)
            {
                try
                {
                    StringBox.Text = text;
                }
                catch (Exception)
                {
                }
                RefreshPreview();
            }

            internal void Add(bool asLevel)
            {
                var names = ChosenNames();
                if (names.Count == 0)
                {
                    PsUi.SetText(PsUi.Find(Window, "StatusText"), "Pick a parameter first.");
                    return;
                }
                var wrapped = names.Select(name => "{" + name + "}");
                string tokens = !asLevel ? string.Join("", wrapped) : string.Join("\\", wrapped);
                string current = Current().TrimEnd();
                if (current.Length == 0)
                {
                    SetCurrent(tokens);
                    return;
                }
                if (asLevel)
                    SetCurrent(current.TrimEnd('\\', '/') + "\\" + tokens);
                else
                    SetCurrent(current + tokens);
            }

            internal void RefreshPreview()
            {
                string text = Current();
                if (text.Trim().Length == 0)
                {
                    PsUi.SetText(Preview, "(everything in the root folder)");
                    return;
                }
                string expanded;
                try
                {
                    expanded = PsPaths.Expand(text, SampleLookup ?? (n => ""));
                }
                catch (Exception)
                {
                    expanded = "";
                }
                PsUi.SetText(Preview, string.IsNullOrEmpty(expanded) ? "(nothing)" : expanded);
            }

            // -------------------------------------------------------------- wiring
            internal void Wire()
            {
                var pairs = new (string Name, RoutedEventHandler Handler)[]
                {
                    ("AddLevelButton", (s, a) => Add(true)),
                    ("AppendButton", (s, a) => Add(false)),
                    ("ClearTokensButton", (s, a) => SetCurrent("")),
                    ("OkButton", Ok),
                    ("CancelButton", CancelClicked),
                };
                foreach (var (name, handler) in pairs)
                {
                    if (!(PsUi.Find(Window, name) is System.Windows.Controls.Primitives.ButtonBase button)) continue;
                    try
                    {
                        button.Click += handler;
                    }
                    catch (Exception)
                    {
                    }
                }

                if (GroupCombo != null)
                {
                    try
                    {
                        GroupCombo.SelectionChanged += (sender, args) => FilterChanged(sender, args);
                    }
                    catch (Exception)
                    {
                    }
                }
                if (SearchBox != null)
                {
                    try
                    {
                        SearchBox.TextChanged += (sender, args) => FilterChanged(sender, args);
                    }
                    catch (Exception)
                    {
                    }
                }
                if (StringBox != null)
                {
                    try
                    {
                        StringBox.TextChanged += (sender, args) => StringChanged(sender, args);
                    }
                    catch (Exception)
                    {
                    }
                }
                if (Grid != null)
                {
                    try
                    {
                        Grid.MouseDoubleClick += (s, a) => Add(true);
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal void FilterChanged(object sender, RoutedEventArgs args)
            {
                FillRows();
            }

            internal void StringChanged(object sender, RoutedEventArgs args)
            {
                RefreshPreview();
            }

            // -------------------------------------------------------------- closing
            internal void Ok(object sender, RoutedEventArgs args)
            {
                Result = Current().Trim();
                Close(true);
            }

            internal void CancelClicked(object sender, RoutedEventArgs args)
            {
                Cancel();
            }

            internal void Cancel()
            {
                Result = null;
                Close(false);
            }

            internal void Close(bool ok)
            {
                try
                {
                    Window.DialogResult = ok;
                }
                catch (Exception)
                {
                }
                try
                {
                    Window.Close();
                }
                catch (Exception)
                {
                }
            }

            public string Show()
            {
                try
                {
                    Window.ShowDialog();
                }
                catch (Exception)
                {
                }
                return Result;
            }
        }

        public static string Pick(IEnumerable<(string Name, string Group)> catalogue, Func<string, string> sampleLookup,
            string current = "", string themeName = "dark", Window owner = null, string sampleLabel = "")
        {
            return new TokenWindow(catalogue, sampleLookup, current, themeName, owner, sampleLabel).Show();
        }
    }
}
