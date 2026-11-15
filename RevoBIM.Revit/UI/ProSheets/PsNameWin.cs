using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// The Custom File Name dialog. Port of ps_namewin.py.
    ///
    /// Parameters on the left, the name being built on the right, pushed across
    /// with the arrow buttons. The preview under the table updates on every
    /// keystroke and shows two lines: the shape of the name in parameter names, and
    /// what it actually comes out as on the first ticked sheet. The second line is
    /// what catches an empty parameter before four hundred files are named after it.
    ///
    /// The grid is backed by a DataTable rather than by objects, as the Python was
    /// (WPF binding to IronPython attributes was not dependable; a table of typed
    /// columns is what the rest of the tool uses).
    /// </summary>
    public static partial class PsNameWin
    {
        public static readonly string[] Columns = { "pname", "prefix", "sample", "suffix", "sep" };

        /// <summary>u'{0}'.format(row[name] or u'') for a DataRow cell.</summary>
        internal static string Cell(DataRow row, string name)
        {
            object value = row[name];
            if (value == null || value is DBNull) return "";
            return Convert.ToString(value) ?? "";
        }

        /// <summary>Modal. Show() returns the finished rule list, or null when cancelled.</summary>
        public class CustomNameWindow
        {
            public string Mode;
            public List<(string Name, string Group)> Catalogue;
            public Func<string, string> SampleLookup;
            public string ThemeName;
            public List<PsNaming.Rule> Result;
            internal bool Suspend;

            public Window Window;
            public PsUi.Chrome Chrome;
            public ListBox AvailableList;
            public ComboBox GroupCombo;
            public TextBox SearchBox;
            public DataGrid Grid;
            public TextBlock PreviewText;
            public TextBlock RealPreview;
            public TextBlock Status;
            public DataTable Table;

            public CustomNameWindow(IEnumerable<(string Name, string Group)> catalogue, Func<string, string> sampleLookup,
                IEnumerable<PsNaming.Rule> rules, string themeName = "dark", Window owner = null,
                string sampleLabel = "", string mode = "sheets")
            {
                Mode = mode == "views" ? "views" : "sheets";
                Catalogue = catalogue != null ? catalogue.ToList() : new List<(string Name, string Group)>();
                SampleLookup = sampleLookup;
                ThemeName = themeName;
                Result = null;
                Suspend = false;

                Window = PsUi.LoadWindow("ProSheetsCustomName.xaml", themeName);
                Chrome = new PsUi.Chrome(Window, onClose: Cancel);
                // The egg is armed on the main window only; see PsUi.AttachEgg.
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

                AvailableList = PsUi.Find<ListBox>(Window, "AvailableList");
                GroupCombo = PsUi.Find<ComboBox>(Window, "GroupCombo");
                SearchBox = PsUi.Find<TextBox>(Window, "ParamSearchBox");
                Grid = PsUi.Find<DataGrid>(Window, "RuleGrid");
                PreviewText = PsUi.Find<TextBlock>(Window, "PreviewText");
                RealPreview = PsUi.Find<TextBlock>(Window, "RealPreviewText");
                Status = PsUi.Find<TextBlock>(Window, "StatusText");

                // Sheets and views keep separate names, so say which one this is.
                PsUi.SetText(PsUi.Find(Window, "NameModeText"),
                    string.Format("Custom File Name - {0}", Mode == "views" ? "Views" : "Sheets"));
                if (!string.IsNullOrEmpty(sampleLabel))
                    PsUi.SetText(PsUi.Find(Window, "SampleNote"),
                        string.Format("Sample values are from {0}.", sampleLabel));

                Table = MakeTable();
                try
                {
                    Grid.ItemsSource = Table.DefaultView;
                }
                catch (Exception)
                {
                }

                FillGroups();
                FillAvailable();
                var start = rules != null ? rules.ToList() : null;
                LoadRules(start != null && start.Count > 0 ? start : PsNaming.DefaultRules(Mode));
                Wire();
                RefreshPreview();
            }

            // ------------------------------------------------------------ the table
            internal DataTable MakeTable()
            {
                var table = new DataTable("rules");
                foreach (string name in Columns)
                    table.Columns.Add(name, typeof(string));
                try
                {
                    table.ColumnChanged += CellChanged;
                }
                catch (Exception)
                {
                }
                return table;
            }

            internal void CellChanged(object sender, DataColumnChangeEventArgs args)
            {
                if (Suspend) return;
                RefreshPreview();
            }

            // -------------------------------------------------------- the left list
            internal void FillGroups()
            {
                var groups = PsModel.CatalogueGroups(Catalogue);
                PsUi.FillCombo(GroupCombo, groups, selected: "All");
            }

            internal void FillAvailable()
            {
                if (AvailableList == null) return;
                string group = PsUi.ComboText(GroupCombo);
                if (string.IsNullOrEmpty(group)) group = "All";
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
                    AvailableList.Items.Clear();
                    foreach (var (name, owningGroup) in Catalogue)
                    {
                        if (group != "All" && owningGroup != group) continue;
                        if (needle.Length > 0 && !(name ?? "").ToLowerInvariant().Contains(needle)) continue;
                        AvailableList.Items.Add(name);
                    }
                }
                catch (Exception)
                {
                }
            }

            // ------------------------------------------------------------- the rules
            internal void LoadRules(IEnumerable<PsNaming.Rule> rules)
            {
                Suspend = true;
                try
                {
                    Table.Rows.Clear();
                    foreach (var rule in rules)
                        AddRow(rule.Param, rule.Prefix, rule.Suffix, rule.Separator);
                }
                finally
                {
                    Suspend = false;
                }
            }

            internal DataRow AddRow(string param, string prefix = "", string suffix = "", string separator = "-")
            {
                DataRow row = Table.NewRow();
                row["pname"] = PsUi.PyStr(param);
                row["prefix"] = prefix ?? "";
                row["suffix"] = suffix ?? "";
                row["sep"] = separator ?? "";
                row["sample"] = SampleFor(param);
                Table.Rows.Add(row);
                return row;
            }

            internal string SampleFor(string param)
            {
                if (SampleLookup == null) return "";
                string value;
                try
                {
                    value = SampleLookup(param);
                }
                catch (Exception)
                {
                    value = "";
                }
                string text = value ?? "";
                if (text.Length == 0) return "(empty)";
                return text.Length <= 48 ? text : text.Substring(0, 45) + "...";
            }

            /// <summary>The current table, as an ordered list of Rule objects.</summary>
            public List<PsNaming.Rule> Rules()
            {
                var output = new List<PsNaming.Rule>();
                try
                {
                    foreach (DataRow row in Table.Rows)
                    {
                        string name = Cell(row, "pname").Trim();
                        if (name.Length == 0) continue;
                        output.Add(new PsNaming.Rule(name, Cell(row, "prefix"), Cell(row, "suffix"), Cell(row, "sep")));
                    }
                }
                catch (Exception)
                {
                }
                return output;
            }

            // ------------------------------------------------------------- preview
            internal void RefreshPreview()
            {
                var rules = Rules();
                PsUi.SetText(PreviewText, PsNaming.Preview(rules));
                if (SampleLookup != null)
                {
                    string real;
                    try
                    {
                        real = PsNaming.BuildName(rules, SampleLookup);
                    }
                    catch (Exception)
                    {
                        real = "";
                    }
                    PsUi.SetText(RealPreview, !string.IsNullOrEmpty(real) ? real + ".pdf" : "");
                }
                if (rules.Count == 0)
                    PsUi.SetText(Status, "With nothing chosen the sheet number is used.");
                else
                    PsUi.SetText(Status, string.Format("{0} parameter{1} in the name.",
                        rules.Count, rules.Count == 1 ? "" : "s"));
            }

            // -------------------------------------------------------------- wiring
            internal void Wire()
            {
                var pairs = new (string Name, RoutedEventHandler Handler)[]
                {
                    ("PushRightButton", PushRight),
                    ("PushLeftButton", PushLeft),
                    ("MoveTopButton", MoveTop),
                    ("MoveUpButton", MoveUp),
                    ("MoveDownButton", MoveDown),
                    ("MoveBottomButton", MoveBottom),
                    ("ResetButton", Reset),
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
                        GroupCombo.SelectionChanged += GroupChanged;
                    }
                    catch (Exception)
                    {
                    }
                }
                if (SearchBox != null)
                {
                    try
                    {
                        SearchBox.TextChanged += SearchChanged;
                    }
                    catch (Exception)
                    {
                    }
                }
                if (AvailableList != null)
                {
                    try
                    {
                        AvailableList.MouseDoubleClick += (sender, args) => PushRight(sender, args);
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal void GroupChanged(object sender, SelectionChangedEventArgs args)
            {
                FillAvailable();
            }

            internal void SearchChanged(object sender, TextChangedEventArgs args)
            {
                FillAvailable();
            }

            // ------------------------------------------------------------- actions
            internal void PushRight(object sender, RoutedEventArgs args)
            {
                if (AvailableList == null) return;
                var chosen = new List<string>();
                try
                {
                    foreach (object item in AvailableList.SelectedItems)
                        chosen.Add(PsUi.PyStr(item));
                }
                catch (Exception)
                {
                    return;
                }
                if (chosen.Count == 0) return;
                Suspend = true;
                try
                {
                    foreach (string name in chosen)
                        AddRow(name);
                }
                finally
                {
                    Suspend = false;
                }
                RefreshPreview();
            }

            /// <summary>Which table rows the grid has selected, as table row indexes.</summary>
            internal List<int> SelectedIndices()
            {
                var found = new List<int>();
                if (Grid == null) return found;
                try
                {
                    foreach (object item in Grid.SelectedItems)
                    {
                        DataRow row = (item as DataRowView)?.Row;
                        if (row == null) continue;
                        int index = Table.Rows.IndexOf(row);
                        if (index >= 0) found.Add(index);
                    }
                }
                catch (Exception)
                {
                    return new List<int>();
                }
                found.Sort();
                return found;
            }

            /// <summary>Rebuild the table in a new order, keeping every value.</summary>
            internal void Rewrite(IList<int> order)
            {
                var snapshot = new List<(string Pname, string Prefix, string Suffix, string Separator, string Sample)>();
                foreach (int index in order)
                {
                    DataRow row = Table.Rows[index];
                    snapshot.Add((Cell(row, "pname"), Cell(row, "prefix"), Cell(row, "suffix"),
                        Cell(row, "sep"), Cell(row, "sample")));
                }
                Suspend = true;
                try
                {
                    Table.Rows.Clear();
                    foreach (var (pname, prefix, suffix, separator, sample) in snapshot)
                    {
                        DataRow row = Table.NewRow();
                        row["pname"] = pname;
                        row["prefix"] = prefix;
                        row["suffix"] = suffix;
                        row["sep"] = separator;
                        row["sample"] = sample;
                        Table.Rows.Add(row);
                    }
                }
                finally
                {
                    Suspend = false;
                }
                RefreshPreview();
            }

            internal void PushLeft(object sender, RoutedEventArgs args)
            {
                var picked = new HashSet<int>(SelectedIndices());
                if (picked.Count == 0) return;
                var keep = Enumerable.Range(0, Table.Rows.Count).Where(i => !picked.Contains(i)).ToList();
                Rewrite(keep);
            }

            internal void MoveUp(object sender, RoutedEventArgs args)
            {
                Shift(-1);
            }

            internal void MoveDown(object sender, RoutedEventArgs args)
            {
                Shift(1);
            }

            internal void Shift(int step)
            {
                var picked = SelectedIndices();
                if (picked.Count == 0) return;
                int count = Table.Rows.Count;
                var order = Enumerable.Range(0, count).ToList();
                var sequence = step < 0 ? picked : Enumerable.Reverse(picked).ToList();
                var moved = new List<int>();
                foreach (int index in sequence)
                {
                    int position = order.IndexOf(index);
                    int target = position + step;
                    if (target < 0 || target >= count) continue;
                    int swap = order[position];
                    order[position] = order[target];
                    order[target] = swap;
                    moved.Add(index);
                }
                if (moved.Count == 0) return;
                Rewrite(order);
                Reselect(moved, step);
            }

            internal void MoveTop(object sender, RoutedEventArgs args)
            {
                var picked = SelectedIndices();
                if (picked.Count == 0) return;
                var rest = Enumerable.Range(0, Table.Rows.Count).Where(i => !picked.Contains(i)).ToList();
                Rewrite(picked.Concat(rest).ToList());
                SelectRange(0, picked.Count);
            }

            internal void MoveBottom(object sender, RoutedEventArgs args)
            {
                var picked = SelectedIndices();
                if (picked.Count == 0) return;
                var rest = Enumerable.Range(0, Table.Rows.Count).Where(i => !picked.Contains(i)).ToList();
                Rewrite(rest.Concat(picked).ToList());
                SelectRange(rest.Count, picked.Count);
            }

            internal void Reselect(IEnumerable<int> moved, int step)
            {
                try
                {
                    Grid.SelectedItems.Clear();
                    DataView view = Table.DefaultView;
                    foreach (int index in moved)
                    {
                        int target = index + step;
                        if (target >= 0 && target < view.Count)
                            Grid.SelectedItems.Add(view[target]);
                    }
                }
                catch (Exception)
                {
                }
            }

            internal void SelectRange(int start, int count)
            {
                try
                {
                    Grid.SelectedItems.Clear();
                    DataView view = Table.DefaultView;
                    for (int index = start; index < start + count; index++)
                    {
                        if (index >= 0 && index < view.Count)
                            Grid.SelectedItems.Add(view[index]);
                    }
                }
                catch (Exception)
                {
                }
            }

            internal void Reset(object sender, RoutedEventArgs args)
            {
                LoadRules(PsNaming.DefaultRules(Mode ?? "sheets"));
                RefreshPreview();
            }

            // --------------------------------------------------------------- closing
            internal void Ok(object sender, RoutedEventArgs args)
            {
                Result = Rules();
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

            public List<PsNaming.Rule> Show()
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
    }
}
