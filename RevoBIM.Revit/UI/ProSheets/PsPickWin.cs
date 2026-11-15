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
    /// A plain multi-select parameter picker. Port of ps_pickwin.py.
    ///
    /// Used by the Selection grid's "Add column" and by anything else that needs
    /// the answer to "which parameters?" and nothing more. The naming dialog and
    /// the subfolder dialog both ask richer questions - a name has prefixes and
    /// separators, a path has levels - so they keep their own windows. This one
    /// returns a list of names and that is all.
    ///
    /// Each row shows what the parameter resolves to on a real sheet, because
    /// "BGL_Sheet Stage" tells you nothing about whether it is filled in and
    /// "(empty)" tells you everything.
    /// </summary>
    public static partial class PsPickWin
    {
        public const string AllGroups = "All";

        /// <summary>Modal. Show() returns a list of parameter names, or null when cancelled.</summary>
        public class PickWindow
        {
            public List<(string Name, string Group)> Catalogue;
            public Func<string, string> SampleLookup;
            public HashSet<string> Already;
            public List<string> Result;

            public Window Window;
            public PsUi.Chrome Chrome;
            public DataGrid Grid;
            public ComboBox GroupCombo;
            public TextBox SearchBox;
            public DataTable Table;

            public PickWindow(IEnumerable<(string Name, string Group)> catalogue, Func<string, string> sampleLookup,
                string themeName = "dark", Window owner = null, string subtitle = "Choose parameters",
                IEnumerable<string> already = null, string sampleLabel = "")
            {
                Catalogue = catalogue != null ? catalogue.ToList() : new List<(string Name, string Group)>();
                SampleLookup = sampleLookup;
                Already = new HashSet<string>(already ?? Enumerable.Empty<string>(), StringComparer.Ordinal);
                Result = null;

                Window = PsUi.LoadWindow("ProSheetsPick.xaml", themeName);
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

                PsUi.SetText(PsUi.Find(Window, "SubtitleText"), subtitle);

                Grid = PsUi.Find<DataGrid>(Window, "PickGrid");
                GroupCombo = PsUi.Find<ComboBox>(Window, "PickGroupCombo");
                SearchBox = PsUi.Find<TextBox>(Window, "PickSearchBox");

                Table = new DataTable("pick");
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
                    PsUi.SetText(PsUi.Find(Window, "StatusText"),
                        string.Format("Values are from {0}. Ctrl and Shift work as usual.", sampleLabel));

                FillGroups();
                FillRows();
                Wire();
            }

            internal void FillGroups()
            {
                var groups = PsModel.CatalogueGroups(Catalogue);
                PsUi.FillCombo(GroupCombo, groups, selected: AllGroups);
            }

            internal string SampleFor(string name)
            {
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
                    foreach (var (name, owningGroup) in Catalogue)
                    {
                        // Something already on the grid is not worth offering twice.
                        if (Already.Contains(name)) continue;
                        if (group != AllGroups && owningGroup != group) continue;
                        if (needle.Length > 0 && !(name ?? "").ToLowerInvariant().Contains(needle)) continue;
                        DataRow row = Table.NewRow();
                        row["pname"] = name;
                        row["pgroup"] = owningGroup;
                        row["sample"] = SampleFor(name);
                        Table.Rows.Add(row);
                    }
                }
                catch (Exception)
                {
                }
            }

            internal void Wire()
            {
                var pairs = new (string Name, RoutedEventHandler Handler)[]
                {
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
                if (Grid != null)
                {
                    try
                    {
                        Grid.MouseDoubleClick += (sender, args) => DoubleClicked(sender, args);
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

            internal void DoubleClicked(object sender, RoutedEventArgs args)
            {
                Ok(sender, args);
            }

            public List<string> Chosen()
            {
                var found = new List<string>();
                if (Grid == null) return found;
                try
                {
                    foreach (object item in Grid.SelectedItems)
                    {
                        DataRow row = (item as DataRowView)?.Row;
                        if (row == null) continue;
                        string name = PsNameWin.Cell(row, "pname");
                        if (name.Length > 0 && !found.Contains(name))
                            found.Add(name);
                    }
                }
                catch (Exception)
                {
                    return new List<string>();
                }
                return found;
            }

            internal void Ok(object sender, RoutedEventArgs args)
            {
                var picked = Chosen();
                if (picked.Count == 0)
                {
                    PsUi.SetText(PsUi.Find(Window, "StatusText"), "Nothing picked yet.");
                    return;
                }
                Result = picked;
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

            public List<string> Show()
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

        public static List<string> Pick(IEnumerable<(string Name, string Group)> catalogue, Func<string, string> sampleLookup,
            string themeName = "dark", Window owner = null, string subtitle = "Choose parameters",
            IEnumerable<string> already = null, string sampleLabel = "")
        {
            return new PickWindow(catalogue, sampleLookup, themeName, owner, subtitle, already, sampleLabel).Show();
        }
    }
}
