using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// Revision Manager settings: the model's own columns and their mapping.
    /// Port of ps_revsetwin.py.
    ///
    /// A table, one row per column the user has added: its name, type, where its
    /// values are pushed (Sheets / Revision clouds / nowhere) and into which
    /// parameter. Only instance parameters bound to that category, holding data the
    /// column can be written as, are offered - PsRevData.Usable decides, and
    /// PsRevData.WhyNot says why a mapped name no longer fits.
    ///
    /// Modal. Show() returns null, or {Action 'save' | 'project_parameters',
    /// Columns [(id, name, target, parameter)]}. Nothing is written here; the
    /// manager stages it and Apply writes it.
    /// </summary>
    public static partial class PsRevSetWin
    {
        /// <summary>target, as the table words it.</summary>
        public static readonly List<(string Target, string Label)> Targets = new List<(string, string)>
        {
            ("", "Nowhere"), ("sheets", "Sheets"), ("clouds", "Revision clouds"),
        };
        public static readonly int[] Widths = { 190, 84, 130, 280, 0 };
        public static readonly string[] Headings = { "Column", "Type", "Push to", "Parameter", "Status" };
        public const string ParameterTip =
            "Type part of the parameter's name - the list narrows to " +
            "the names containing it (\"rev note\" finds Revision " +
            "Notes). The caret shows the whole list.";

        /// <summary>The Python's {'action': ..., 'columns': [(id, name, target, parameter)]}.</summary>
        public class SettingsAnswer
        {
            public string Action;
            public List<(string Id, string Name, string Target, string Parameter)> Columns;
        }

        /// <summary>One table row: the Python's (column, name box, target combo, parameter picker, status).</summary>
        public class Row
        {
            public PsRevData.Column Column;
            public TextBox Name;
            public ComboBox Target;
            public PsUi.SearchPicker Parameter;
            public TextBlock Status;
        }

        public static string TargetOf(string label)
        {
            foreach (var (target, text) in Targets)
            {
                if (text == label) return target;
            }
            return "";
        }

        public static string LabelOf(string target)
        {
            foreach (var (one, text) in Targets)
            {
                if (one == target) return text;
            }
            return Targets[0].Label;
        }

        /// <summary>(ok, words) for one row - what the Status cell says.</summary>
        public static (bool Ok, string Words) StatusOf(IEnumerable<PsRevData.BoundParameter> parameters, string columnKind,
            string target, string parameter)
        {
            if (string.IsNullOrEmpty(target)) return (true, "Kept in the model only");
            if (string.IsNullOrEmpty(parameter)) return (false, "Choose a parameter");
            string problem = PsRevData.WhyNot(parameters, target, columnKind, parameter);
            if (!string.IsNullOrEmpty(problem)) return (false, problem);
            return (true, string.Format("Pushed into \"{0}\" on every Apply", parameter));
        }

        public class SettingsDialog
        {
            public List<PsRevData.Column> Columns;
            public Func<IEnumerable<PsRevData.BoundParameter>> Reader;
            public List<PsRevData.BoundParameter> Parameters = new List<PsRevData.BoundParameter>();
            public List<Row> Rows = new List<Row>();
            public SettingsAnswer Result;
            internal bool Suspend;

            public Window Window;
            public PsUi.Chrome Chrome;
            public Panel Table;
            public TextBlock Status;

            public SettingsDialog(IEnumerable<PsRevData.Column> columns,
                Func<IEnumerable<PsRevData.BoundParameter>> parameterReader = null,
                string themeName = "dark", Window owner = null)
            {
                Columns = (columns ?? Enumerable.Empty<PsRevData.Column>()).Select(column => column.Copy()).ToList();
                Reader = parameterReader;
                Result = null;
                Suspend = false;

                Window = PsUi.LoadWindow("ProSheetsRevSettings.xaml", themeName);
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
                Table = PsUi.Find<Panel>(Window, "MappingTable");
                Status = PsUi.Find<TextBlock>(Window, "StatusText");
                try
                {
                    ((FrameworkElement)PsUi.Find(Window, "MappingHelp")).ToolTip = PsRevData.MappingHelp;
                }
                catch (Exception)
                {
                }
                ReadParameters();
                Build();
                Wire();
            }

            // ------------------------------------------------------------------
            internal void ReadParameters()
            {
                try
                {
                    Parameters = Reader != null ? Reader().ToList() : new List<PsRevData.BoundParameter>();
                }
                catch (Exception)
                {
                    Parameters = new List<PsRevData.BoundParameter>();
                }
            }

            internal Grid Line()
            {
                var line = new Grid();
                line.Margin = new Thickness(0, 0, 0, 6);
                foreach (int width in Widths)
                {
                    var definition = new ColumnDefinition();
                    if (width != 0)
                        definition.Width = new GridLength(width);
                    line.ColumnDefinitions.Add(definition);
                }
                return line;
            }

            internal void Place(Grid line, FrameworkElement element, int index)
            {
                Grid.SetColumn(element, index);
                element.Margin = new Thickness(0, 0, 8, 0);
                line.Children.Add(element);
            }

            internal void Build()
            {
                if (Table == null) return;
                Suspend = true;
                try
                {
                    Table.Children.Clear();
                    Rows = new List<Row>();
                    PsUi.SetVisible(PsUi.Find(Window, "MappingEmpty"), Columns.Count == 0);
                    if (Columns.Count == 0) return;
                    var head = Line();
                    for (int index = 0; index < Headings.Length; index++)
                    {
                        string text = Headings[index];
                        var label = new TextBlock();
                        label.Text = text;
                        label.SetResourceReference(FrameworkElement.StyleProperty, "FieldLabel");
                        if (text == "Push to")
                            label.ToolTip = PsRevData.MappingHelp;
                        else if (text == "Parameter")
                            label.ToolTip = ParameterTip;
                        Place(head, label, index);
                    }
                    Table.Children.Add(head);
                    foreach (var column in Columns)
                        AddRow(column);
                }
                finally
                {
                    Suspend = false;
                }
                foreach (var row in Rows)
                    Paint(row);
            }

            internal void AddRow(PsRevData.Column column)
            {
                var line = Line();
                var name = new TextBox();
                name.Text = column.Name;
                name.Height = 28;
                Place(line, name, 0);
                var kind = new TextBlock();
                kind.Text = PsRevData.KindLabels.TryGetValue(column.Kind ?? "", out string kindLabel) ? kindLabel : column.Kind;
                kind.VerticalAlignment = VerticalAlignment.Center;
                Place(line, kind, 1);
                var target = new ComboBox();
                target.Height = 28;
                target.ToolTip = PsRevData.MappingHelp;
                PsUi.FillCombo(target, Targets.Select(one => one.Label).ToList(), selected: LabelOf(column.Target));
                Place(line, target, 2);
                // Type into the Parameter box itself: the list under it narrows to
                // the names containing what is typed.
                var parameter = new PsUi.SearchPicker(hint: "Type to search parameters", matcher: PsRevData.Matching);
                Place(line, parameter.Element, 3);
                var status = new TextBlock();
                status.TextWrapping = TextWrapping.Wrap;
                status.VerticalAlignment = VerticalAlignment.Center;
                Place(line, status, 4);
                Table.Children.Add(line);
                var row = new Row { Column = column, Name = name, Target = target, Parameter = parameter, Status = status };
                Rows.Add(row);
                FillParameters(row, column.Parameter);
                target.SelectionChanged += MakeChanged(row, true);
                parameter.OnChange = MakePicked(row);
            }

            /// <summary>
            /// The parameters this row may use - plus the mapped one if it no
            /// longer qualifies, so the user can see what it was and why not.
            /// </summary>
            internal void FillParameters(Row row, string keep)
            {
                string where = TargetOf(PsUi.ComboText(row.Target));
                var names = !string.IsNullOrEmpty(where)
                    ? PsRevData.Usable(Parameters, where, row.Column.Kind).Select(one => one.Name).ToList()
                    : new List<string>();
                var items = new List<string>(names);
                if (!string.IsNullOrEmpty(keep) && !items.Contains(keep))
                    items.Add(keep);
                Suspend = true;
                try
                {
                    row.Parameter.SetItems(items, !string.IsNullOrEmpty(where) ? keep : "");
                    row.Parameter.SetEnabled(!string.IsNullOrEmpty(where));
                }
                catch (Exception)
                {
                }
                finally
                {
                    Suspend = false;
                }
            }

            /// <summary>Typed into, or a name picked: say what the row will do.</summary>
            internal Action<PsUi.SearchPicker> MakePicked(Row row)
            {
                return picker =>
                {
                    if (!Suspend) Paint(row);
                };
            }

            internal SelectionChangedEventHandler MakeChanged(Row row, bool targetChanged)
            {
                return (sender, args) =>
                {
                    if (Suspend) return;
                    if (targetChanged)
                        FillParameters(row, ParameterOf(row));
                    Paint(row);
                };
            }

            /// <summary>The Python's _parameter(row): the picked name.</summary>
            internal string ParameterOf(Row row)
            {
                return row.Parameter.Value;
            }

            internal void Paint(Row row)
            {
                var (ok, words) = StatusOf(Parameters, row.Column.Kind, TargetOf(PsUi.ComboText(row.Target)), ParameterOf(row));
                string typed = row.Parameter.Text().Trim();
                if (typed.Length > 0 && string.IsNullOrEmpty(ParameterOf(row)))
                {
                    ok = false;
                    words = PsUi.SearchPicker.Shown(row.Parameter.Items, typed, "", row.Parameter.Matcher).Count == 0
                        ? string.Format("No parameter here contains \"{0}\"", typed)
                        : string.Format("Pick one of the matches for \"{0}\"", typed);
                }
                PsUi.SetText(row.Status, words);
                try
                {
                    row.Status.SetResourceReference(TextBlock.ForegroundProperty, ok ? "GreenBrush" : "OrangeBrush");
                    row.Status.ToolTip = words;
                }
                catch (Exception)
                {
                }
            }

            internal void Wire()
            {
                foreach (var (name, handler) in new (string, RoutedEventHandler)[]
                         {
                             ("OkButton", (sender, args) => Finish("save")),
                             ("CancelButton", (sender, args) => Cancel()),
                             ("ProjectParamsButton", (sender, args) => Finish("project_parameters")),
                             ("RefreshParamsButton", Refresh),
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
            }

            internal void Refresh(object sender, RoutedEventArgs args)
            {
                ReadParameters();
                foreach (var row in Rows)
                {
                    FillParameters(row, ParameterOf(row));
                    Paint(row);
                }
                // The plural follows the count of all parameters, not of the usable
                // ones, exactly as the Python words it.
                PsUi.SetText(Status, string.Format("{0} usable parameter{1} on Sheets and Revision Clouds.",
                    PsRevData.Usable(Parameters, "sheets").Count + PsRevData.Usable(Parameters, "clouds").Count,
                    Parameters.Count == 1 ? "" : "s"));
            }

            /// <summary>[(id, name, target, parameter)] as the table stands.</summary>
            public List<(string Id, string Name, string Target, string Parameter)> Answers()
            {
                var output = new List<(string Id, string Name, string Target, string Parameter)>();
                foreach (var row in Rows)
                {
                    string text;
                    try
                    {
                        text = (row.Name.Text ?? "").Trim();
                    }
                    catch (Exception)
                    {
                        text = row.Column.Name;
                    }
                    string where = TargetOf(PsUi.ComboText(row.Target));
                    output.Add((row.Column.Id, text, where, !string.IsNullOrEmpty(where) ? ParameterOf(row) : ""));
                }
                return output;
            }

            internal void Finish(string action)
            {
                var answers = Answers();
                foreach (var (columnId, name, target, parameter) in answers)
                {
                    var column = Columns.Where(one => one.Id == columnId).First();
                    var others = Columns.Where(one => one.Id != columnId).ToList();
                    var renamed = answers.Where(one => one.Id != columnId)
                        .Select(one => new PsRevData.Column(one.Id, one.Name)).ToList();
                    var choices = column.Choices != null && column.Choices.Count > 0
                        ? column.Choices : new List<string> { "-" };
                    string problem = PsRevData.ColumnProblem(name, column.Kind, choices,
                        renamed.Count > 0 ? renamed : others);
                    if (!string.IsNullOrEmpty(problem))
                    {
                        PsUi.SetText(Status, problem);
                        return;
                    }
                    // A parameter that exists but holds the wrong data would push
                    // nothing but errors; one not added yet is allowed, and says so.
                    string reason = !string.IsNullOrEmpty(target)
                        ? PsRevData.WhyNot(Parameters, target, column.Kind, parameter) : "";
                    if (!string.IsNullOrEmpty(reason) && Parameters.Any(one => one.Name == parameter))
                    {
                        PsUi.SetText(Status, reason);
                        return;
                    }
                }
                Result = new SettingsAnswer { Action = action, Columns = answers };
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

            public SettingsAnswer Show()
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
