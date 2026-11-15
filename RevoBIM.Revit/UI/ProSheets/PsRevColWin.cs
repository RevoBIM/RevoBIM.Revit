using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// Add or edit one of the Revision Manager's extra columns. Port of ps_revcolwin.py.
    ///
    /// Name, type of data, the choices for a choice list, and the parameter it is
    /// pushed into. Modal; Show() returns what to do, or null.
    /// </summary>
    public static partial class PsRevColWin
    {
        /// <summary>
        /// The Python's {'action': 'remove'} or {'action': 'save', 'name', 'kind',
        /// 'choices', 'target', 'parameter', 'group'}. Only Action is set for "remove".
        /// </summary>
        public class ColumnAnswer
        {
            public string Action;
            public string Name;
            public string Kind;
            public List<string> Choices;
            public string Target;
            public string Parameter;
            public string Group;
        }

        /// <summary>Show() -> null, Action "remove", or Action "save" with the rest.</summary>
        public class ColumnDialog
        {
            /// <summary>
            /// The three types of column: Custom - a column of its own, any type of
            /// data - then the two Yes/No groups the Excel plots.
            /// </summary>
            public const string NoGroup = "Custom";

            public List<PsRevData.Column> Columns;
            public PsRevData.Column Column;
            /// <summary>The group a new column starts in - the + on a group's band.</summary>
            public string StartGroup;
            /// <summary>target -> [(name, storage)] the parameter combo offers.</summary>
            public Func<string, IEnumerable<(string Name, string Data)>> Lookup;
            public ColumnAnswer Result;
            internal Dictionary<string, List<(string Name, string Data)>> Parameters =
                new Dictionary<string, List<(string Name, string Data)>>(StringComparer.Ordinal);

            public Window Window;
            public PsUi.Chrome Chrome;
            public TextBox NameBox;
            public ComboBox GroupCombo;
            public ComboBox KindCombo;
            public TextBlock KindNote;
            public FrameworkElement ChoicesPanel;
            public TextBox ChoicesBox;
            public ComboBox TargetCombo;
            public ComboBox ParameterCombo;
            public TextBlock ParameterNote;
            public TextBlock Status;

            public ColumnDialog(IEnumerable<PsRevData.Column> columns, PsRevData.Column column = null,
                Func<string, IEnumerable<(string Name, string Data)>> parameterLookup = null,
                string themeName = "dark", Window owner = null, string group = "")
            {
                Columns = columns != null ? columns.ToList() : new List<PsRevData.Column>();
                Column = column;
                StartGroup = column != null ? column.Group : group;
                Lookup = parameterLookup;
                Result = null;

                Window = PsUi.LoadWindow("ProSheetsRevColumn.xaml", themeName);
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

                NameBox = PsUi.Find<TextBox>(Window, "ColumnNameBox");
                GroupCombo = PsUi.Find<ComboBox>(Window, "ColumnGroupCombo");
                KindCombo = PsUi.Find<ComboBox>(Window, "ColumnKindCombo");
                KindNote = PsUi.Find<TextBlock>(Window, "ColumnKindNote");
                ChoicesPanel = PsUi.Find<FrameworkElement>(Window, "ChoicesPanel");
                ChoicesBox = PsUi.Find<TextBox>(Window, "ColumnChoicesBox");
                TargetCombo = PsUi.Find<ComboBox>(Window, "ColumnTargetCombo");
                ParameterCombo = PsUi.Find<ComboBox>(Window, "ColumnParameterCombo");
                ParameterNote = PsUi.Find<TextBlock>(Window, "ColumnParameterNote");
                Status = PsUi.Find<TextBlock>(Window, "StatusText");

                Fill();
                Wire();
            }

            // ------------------------------------------------------------------
            internal void Fill()
            {
                var column = Column;
                PsUi.SetText(PsUi.Find(Window, "SubtitleText"),
                    column != null ? string.Format("Edit \"{0}\"", column.Name) : "New revision column");
                PsUi.SetText(NameBox, column != null ? column.Name : "");
                var kindLabels = PsRevData.Kinds.Select(k => k.Label).ToList();
                PsUi.FillCombo(KindCombo, kindLabels,
                    selected: column != null ? PsRevData.KindLabels[column.Kind] : kindLabels[0]);
                if (column != null)
                {
                    try
                    {
                        KindCombo.IsEnabled = false;
                    }
                    catch (Exception)
                    {
                    }
                    PsUi.SetVisible(PsUi.Find(Window, "RemoveColumnButton"), true);
                }
                else
                {
                    PsUi.SetText(KindNote, "Text, Yes/No, Number, Date or a " +
                                           "list of choices. It cannot be " +
                                           "changed once the column exists.");
                }
                PsUi.SetText(ChoicesBox, column != null ? string.Join("\n", column.Choices) : "");
                bool status = StartGroup == PsRevData.Status;
                var groups = new List<string> { NoGroup };
                groups.AddRange(PsRevData.Groups.Select(g => g.Label));
                if (status)
                    groups = new List<string> { PsRevData.GroupLabels[PsRevData.Status] };
                string startLabel = StartGroup != null && PsRevData.GroupLabels.TryGetValue(StartGroup, out string found)
                    ? found : null;
                PsUi.FillCombo(GroupCombo, groups, selected: !string.IsNullOrEmpty(startLabel) ? startLabel : NoGroup);
                if (status || (column != null && column.Kind != "yesno"))
                {
                    // Issue Status stays itself; a column that is not Yes/No cannot
                    // join a group of ticks.
                    try
                    {
                        GroupCombo.IsEnabled = false;
                    }
                    catch (Exception)
                    {
                    }
                }
                var targetLabels = PsRevData.Targets.Select(t => t.Label).ToList();
                PsUi.FillCombo(TargetCombo, targetLabels,
                    selected: column != null ? PsRevData.TargetLabels[column.Target] : targetLabels[0]);
                GroupChanged();
                TargetChanged(keep: column != null ? column.Parameter : "");
            }

            internal void Wire()
            {
                foreach (var (name, handler) in new (string, RoutedEventHandler)[]
                         {
                             ("OkButton", Ok),
                             ("CancelButton", (sender, args) => Cancel()),
                             ("RemoveColumnButton", Remove),
                         })
                {
                    if (PsUi.Find(Window, name) is System.Windows.Controls.Primitives.ButtonBase button)
                    {
                        try
                        {
                            button.Click += handler;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
                foreach (var (combo, handler) in new (ComboBox, SelectionChangedEventHandler)[]
                         {
                             (GroupCombo, (sender, args) => GroupChanged()),
                             (KindCombo, (sender, args) => KindChanged()),
                             (TargetCombo, (sender, args) => TargetChanged()),
                             (ParameterCombo, (sender, args) => ParameterChanged()),
                         })
                {
                    if (combo != null)
                    {
                        try
                        {
                            combo.SelectionChanged += handler;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
            }

            // ------------------------------------------------------------------
            public string Kind()
            {
                string label = PsUi.ComboText(KindCombo);
                foreach (var (kind, text) in PsRevData.Kinds)
                {
                    if (text == label) return kind;
                }
                return "text";
            }

            public string Group()
            {
                string label = PsUi.ComboText(GroupCombo);
                foreach (var pair in PsRevData.GroupLabels)
                {
                    if (!string.IsNullOrEmpty(pair.Key) && pair.Value == label) return pair.Key;
                }
                return "";
            }

            /// <summary>A grouped column is Yes/No: the type follows the group.</summary>
            internal void GroupChanged()
            {
                string group = Group();
                bool grouped = group == PsRevData.IssuedTo || group == PsRevData.Method;
                if (grouped)
                {
                    PsUi.FillCombo(KindCombo, PsRevData.Kinds.Select(k => k.Label).ToList(),
                        selected: PsRevData.KindLabels["yesno"]);
                }
                if (Column == null)
                {
                    try
                    {
                        KindCombo.IsEnabled = !grouped;
                    }
                    catch (Exception)
                    {
                    }
                }
                KindChanged();
            }

            public string Target()
            {
                string label = PsUi.ComboText(TargetCombo);
                foreach (var (target, text) in PsRevData.Targets)
                {
                    if (text == label) return target;
                }
                return "";
            }

            public string Parameter()
            {
                try
                {
                    return (ParameterCombo.Text ?? "").Trim();
                }
                catch (Exception)
                {
                    return PsUi.ComboText(ParameterCombo);
                }
            }

            public List<string> Choices()
            {
                string text;
                try
                {
                    text = ChoicesBox.Text ?? "";
                }
                catch (Exception)
                {
                    text = "";
                }
                return text.Replace("\r", "").Split('\n')
                    .Where(line => line.Trim().Length > 0)
                    .Select(line => line.Trim())
                    .ToList();
            }

            internal void KindChanged()
            {
                PsUi.SetVisible(ChoicesPanel, Kind() == "choice");
                ParameterChanged();
            }

            internal void TargetChanged(string keep = null)
            {
                string target = Target();
                var names = new List<string>();
                if (!string.IsNullOrEmpty(target))
                {
                    if (!Parameters.ContainsKey(target))
                    {
                        try
                        {
                            Parameters[target] = Lookup != null
                                ? Lookup(target).ToList()
                                : new List<(string Name, string Data)>();
                        }
                        catch (Exception)
                        {
                            Parameters[target] = new List<(string Name, string Data)>();
                        }
                    }
                    names = Parameters[target].Select(one => one.Name).ToList();
                }
                string wanted = keep ?? Parameter();
                PsUi.FillCombo(ParameterCombo, names, selected: names.Contains(wanted) ? wanted : null);
                try
                {
                    ParameterCombo.IsEnabled = !string.IsNullOrEmpty(target);
                    if (!string.IsNullOrEmpty(wanted) && !names.Contains(wanted))
                        ParameterCombo.Text = wanted;
                }
                catch (Exception)
                {
                }
                ParameterChanged();
            }

            public string StorageOf(string name)
            {
                if (Parameters.TryGetValue(Target(), out var found))
                {
                    foreach (var (one, storage) in found)
                    {
                        if (one == name) return storage;
                    }
                }
                return "";
            }

            /// <summary>Why the mapping will not work, or "".</summary>
            public string Problem()
            {
                string target = Target();
                string name = Parameter();
                if (string.IsNullOrEmpty(target)) return "";
                if (string.IsNullOrEmpty(name)) return "Choose the parameter to push into.";
                string storage = StorageOf(name);
                if (string.IsNullOrEmpty(storage))
                {
                    return Parameters.ContainsKey(target) && Parameters[target] != null
                        ? string.Format("No sheet or cloud in the model has a writable \"{0}\". " +
                                        "Add it as a project or shared parameter first; until " +
                                        "then nothing is pushed.", name)
                        : "";
                }
                string kind = Kind();
                string[] accepted = PsRevData.Accepts.TryGetValue(kind, out var a) ? a : new string[0];
                if (!accepted.Contains(storage))
                {
                    return string.Format("\"{0}\" holds {1}; a {2} column needs {3}.",
                        name, StorageWords(storage), PsRevData.KindLabels[kind],
                        string.Join(" or ", PsRevData.Accepts[kind].Select(StorageWords)));
                }
                return "";
            }

            internal static string StorageWords(string storage)
            {
                switch (storage)
                {
                    case "String": return "text";
                    case "Integer": return "a whole number or Yes/No";
                    case "Double": return "a number";
                    default: return storage;
                }
            }

            internal void ParameterChanged()
            {
                string problem = Problem();
                string storage = StorageOf(Parameter());
                if (!string.IsNullOrEmpty(problem))
                {
                    PsUi.SetText(ParameterNote, problem);
                }
                else if (!string.IsNullOrEmpty(Target()) && !string.IsNullOrEmpty(storage))
                {
                    PsUi.SetText(ParameterNote, string.Format("A {0} parameter - each {1} takes the value on Apply.",
                        StorageWords(storage), Target() == "sheets" ? "sheet" : "cloud"));
                }
                else
                {
                    PsUi.SetText(ParameterNote, "");
                }
            }

            // ------------------------------------------------------------------
            internal void Ok(object sender, RoutedEventArgs args)
            {
                string name;
                try
                {
                    name = NameBox.Text ?? "";
                }
                catch (Exception)
                {
                    name = "";
                }
                string reason = PsRevData.ColumnProblem(name, Kind(), Choices(), Columns,
                    Column != null ? Column.Id : null);
                string problem = Problem();
                if (string.IsNullOrEmpty(reason) && !string.IsNullOrEmpty(problem)
                    && !string.IsNullOrEmpty(StorageOf(Parameter())))
                    reason = problem;         // the wrong type of parameter
                if (!string.IsNullOrEmpty(reason))
                {
                    PsUi.SetText(Status, reason);
                    return;
                }
                Result = new ColumnAnswer
                {
                    Action = "save",
                    Name = name.Trim(),
                    Kind = Kind(),
                    Choices = Choices(),
                    Target = Target(),
                    Parameter = !string.IsNullOrEmpty(Target()) ? Parameter() : "",
                    Group = Group(),
                };
                Close(true);
            }

            internal void Remove(object sender, RoutedEventArgs args)
            {
                Result = new ColumnAnswer { Action = "remove" };
                Close(true);
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

            public ColumnAnswer Show()
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
