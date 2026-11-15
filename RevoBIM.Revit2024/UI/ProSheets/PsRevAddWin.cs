using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// Add revision: everything about a new revision, and where it goes.
    /// Port of ps_revaddwin.py.
    ///
    /// Opened by the Revision Manager's Add. The first thing asked - washed and
    /// edged in orange so it is the first thing looked at - is the sequence it
    /// takes, defaulting to last. The revision already at that sequence, and every
    /// one after it, moves down a slot. Then every property Revit holds for a
    /// revision, and the manager's own columns.
    ///
    /// Modal. Show() returns null, or an Answer {Position, Fields {field: value},
    /// Custom {column id: stored value}}. Nothing is written here: the manager
    /// stages it, green, and Apply creates it.
    /// </summary>
    public static partial class PsRevAddWin
    {
        /// <summary>field, label, kind - the revision's own properties, as the grid orders them.</summary>
        public static readonly List<(string Field, string Label, string Kind)> Fields = new List<(string, string, string)>
        {
            ("numbering", "Numbering", "numbering"),
            ("date", "Date", "text"),
            ("desc", "Description", "text"),
            ("issued_to", "Issued to", "text"),
            ("issued_by", "Issued by", "text"),
            ("show", "Show", "show"),
            ("issued", "Issued", "check"),
        };

        /// <summary>
        /// The Python's {'position': int, 'fields': {field: value}, 'custom': {column id: stored value}}.
        /// Fields hold strings, except "issued" which is a bool - as PsRevisions.Staging.Add and Edit take them.
        /// </summary>
        public class Answer
        {
            public int Position;
            public Dictionary<string, object> Fields = new Dictionary<string, object>(StringComparer.Ordinal);
            public Dictionary<string, string> Custom = new Dictionary<string, string>(StringComparer.Ordinal);
        }

        // ------------------------------------------------------------ python-ish helpers

        /// <summary>Python truthiness, for "value or u''" and bool(value).</summary>
        internal static bool Truthy(object value)
        {
            switch (value)
            {
                case null: return false;
                case string s: return s.Length > 0;
                case bool b: return b;
                case int i: return i != 0;
                case long l: return l != 0;
                case double d: return d != 0.0;
                default: return true;
            }
        }

        /// <summary>u'{0}'.format(value or u'').</summary>
        internal static string Or(object value)
        {
            return Truthy(value) ? PsUi.PyStr(value) : "";
        }

        /// <summary>
        /// (ok, sequence, why not) for what is typed in the Sequence box. The Python
        /// returned (ok, sequence or why not); the two meanings are split here.
        /// count live revisions, so 1 to count + 1 - one past the end is last.
        /// </summary>
        public static (bool Ok, int Value, string Why) ReadPosition(string text, int count)
        {
            int value;
            if (!int.TryParse((text ?? "").Trim(), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out value))
                return (false, 0, string.Format("The sequence is a whole number, 1 to {0}.", count + 1));
            if (value < 1 || value > count + 1)
                return (false, 0, string.Format("The sequence has to be 1 to {0}.", count + 1));
            return (true, value, "");
        }

        /// <summary>
        /// What a sequence will do, in words. rows is [(sequence, label)] for the
        /// live revisions in order.
        /// </summary>
        public static string PositionNote(int position, IList<(int? Sequence, string Label)> rows)
        {
            int count = rows.Count;
            if (position > count)
                return string.Format("Goes in last, as sequence {0}.", count + 1);
            var (sequence, label) = rows[position - 1];
            int moved = count - position + 1;
            return string.Format("Goes in at sequence {0}. {1} moves down to {2}{3}.",
                position,
                !string.IsNullOrEmpty(label) ? label : string.Format("Sequence {0}", PsUi.PyStr(sequence)),
                position + 1,
                moved == 1 ? "" : string.Format(", and the {0} after it each move down one", moved - 1));
        }

        /// <summary>Select the item reading text, if there is one.</summary>
        internal static bool Pick(ComboBox combo, object text)
        {
            try
            {
                string wanted = Or(text);
                for (int index = 0; index < combo.Items.Count; index++)
                {
                    if (PsUi.PyStr(combo.Items[index]) == wanted)
                    {
                        combo.SelectedIndex = index;
                        return true;
                    }
                }
            }
            catch (Exception)
            {
            }
            return false;
        }

        /// <summary>
        /// Where the sequence box starts: the position asked for, kept to 1 to
        /// count + 1 - one past the end being last.
        /// </summary>
        public static int StartingPosition(int? position, int count)
        {
            if (position == null) return count + 1;
            return Math.Max(1, Math.Min(count + 1, position.Value));
        }

        public static string RowLabel(PsRevisions.Staging staging, string key)
        {
            var entry = staging.Entries[key];
            object descValue, dateValue;
            entry.Fields.TryGetValue("desc", out descValue);
            entry.Fields.TryGetValue("date", out dateValue);
            string desc = Or(descValue);
            string date = Or(dateValue);
            var parts = new[] { date, desc }.Where(part => part.Length > 0).ToList();
            return parts.Count > 0
                ? string.Format("\"{0}\"", string.Join(" - ", parts))
                : string.Format("Sequence {0}", PsUi.PyStr(staging.StagedSequence(key)));
        }

        public class AddDialog
        {
            public PsRevisions.Staging Staging;
            public string EditKey;
            public List<(int? Sequence, string Label)> Rows;
            public int Count;
            public Answer Result;
            /// <summary>field or 'x_&lt;id&gt;' -> its control.</summary>
            public Dictionary<string, Control> Controls = new Dictionary<string, Control>(StringComparer.Ordinal);

            public Window Window;
            public PsUi.Chrome Chrome;
            public StackPanel Form;
            public TextBox Box;
            public TextBlock Note;
            public TextBlock Status;

            /// <summary>
            /// position is the sequence to start on - last when null, kept to
            /// 1 .. last. note goes in the footer: what happens once it is made,
            /// when that is more than "it is created on Apply".
            ///
            /// editKey makes it the Edit revision window instead: the fields filled
            /// in from that revision, the sequence shown but fixed - moving a
            /// revision is the Revision Manager's Move up and Move down - and Apply
            /// in place of Add.
            /// </summary>
            public AddDialog(PsRevisions.Staging staging, string themeName = "dark", Window owner = null,
                int? position = null, string note = "", string editKey = null)
            {
                Staging = staging;
                EditKey = editKey;
                Rows = staging.LiveOrder().Select(key => (staging.StagedSequence(key), RowLabel(staging, key))).ToList();
                Count = Rows.Count;
                Result = null;

                Window = PsUi.LoadWindow("ProSheetsRevAdd.xaml", themeName);
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
                Form = PsUi.Find<StackPanel>(Window, "AddForm");
                Box = PsUi.Find<TextBox>(Window, "SequenceBox");
                Note = PsUi.Find<TextBlock>(Window, "SequenceNote");
                Status = PsUi.Find<TextBlock>(Window, "StatusText");
                PsUi.SetText(PsUi.Find(Window, "SequenceRange"), string.Format("of {0}  (1 is the top)", Count + 1));
                Build();
                PsUi.SetText(Box, (Count + 1).ToString(CultureInfo.InvariantCulture));
                if (editKey != null)
                    AsEdit(editKey);
                else if (position != null)
                    PsUi.SetText(Box, StartingPosition(position, Count).ToString(CultureInfo.InvariantCulture));
                if (!string.IsNullOrEmpty(note))
                    PsUi.SetText(Status, note);
                Wire();
                PaintNote();
                try
                {
                    Box.Focus();
                    Box.SelectAll();
                }
                catch (Exception)
                {
                }
            }

            // ------------------------------------------------------------------
            internal void AsEdit(string key)
            {
                var entry = Staging.Entries[key];
                int sequence = Staging.StagedSequence(key) ?? 1;
                PsUi.SetText(PsUi.Find(Window, "DialogSubtitle"), "Edit revision");
                PsUi.SetContent(PsUi.Find(Window, "OkButton"), "Apply");
                PsUi.SetText(Box, sequence.ToString(CultureInfo.InvariantCulture));
                try
                {
                    Box.IsReadOnly = true;
                }
                catch (Exception)
                {
                }
                foreach (string name in new[] { "SequenceDownButton", "SequenceUpButton" })
                    PsUi.SetVisible(PsUi.Find(Window, name), false);
                PsUi.SetText(PsUi.Find(Window, "SequenceRange"), string.Format("of {0}", Count));
                foreach (var (field, _, kind) in Fields)
                {
                    if (!Controls.TryGetValue(field, out Control control) || control == null) continue;
                    entry.Fields.TryGetValue(field, out object value);
                    if (kind == "check")
                        ((CheckBox)control).IsChecked = Truthy(value);
                    else if (kind == "numbering" || kind == "show")
                        Pick((ComboBox)control, value);
                    else
                        ((TextBox)control).Text = Or(value);
                }
                foreach (var column in Staging.Columns)
                {
                    if (!Controls.TryGetValue("x_" + column.Id, out Control control) || control == null) continue;
                    string stored = PsRevisions.Staging.CustomValue(entry, column);
                    if (column.Kind == "yesno")
                        ((CheckBox)control).IsChecked = stored == "1";
                    else if (column.Kind == "choice")
                        Pick((ComboBox)control, stored);
                    else
                        ((TextBox)control).Text = stored;
                }
                entry.Fields.TryGetValue("issued", out object issued);
                PsUi.SetText(Status, Truthy(issued)
                    ? "Issued: Revit keeps it as it is. Untick Issued to change the " +
                      "rest - your own columns can change either way."
                    : "Written to the model on Apply.");
            }

            internal Grid Line(string labelText)
            {
                var line = new Grid();
                line.Margin = new Thickness(0, 0, 0, 8);
                foreach (double? width in new double?[] { 130, null })
                {
                    var definition = new ColumnDefinition();
                    if (width != null)
                        definition.Width = new GridLength(width.Value);
                    line.ColumnDefinitions.Add(definition);
                }
                var label = new TextBlock();
                label.Text = labelText;
                label.VerticalAlignment = VerticalAlignment.Center;
                label.SetResourceReference(FrameworkElement.StyleProperty, "FieldLabel");
                Grid.SetColumn(label, 0);
                line.Children.Add(label);
                Form.Children.Add(line);
                return line;
            }

            internal void Place(Grid line, Control control)
            {
                Grid.SetColumn(control, 1);
                line.Children.Add(control);
            }

            internal void Build()
            {
                if (Form == null) return;
                var live = Staging.LiveOrder();
                object numbering;
                if (live.Count > 0)
                    Staging.Entries[live[live.Count - 1]].Fields.TryGetValue("numbering", out numbering);
                else
                    numbering = Staging.Sequences.Count > 0 ? Staging.Sequences[0] : "";
                foreach (var (field, label, kind) in Fields)
                {
                    if (kind == "numbering" && Staging.Sequences.Count == 0)
                        continue;            // Revit 2021: no numbering sequences
                    var line = Line(label);
                    Control control;
                    if (kind == "numbering")
                    {
                        var combo = new ComboBox();
                        PsUi.FillCombo(combo, Staging.Sequences, selected: numbering);
                        control = combo;
                    }
                    else if (kind == "show")
                    {
                        var combo = new ComboBox();
                        PsUi.FillCombo(combo, PsRevisions.ShowLabels, selected: PsRevisions.DefaultShow);
                        control = combo;
                    }
                    else if (kind == "check")
                    {
                        var check = new CheckBox();
                        check.IsChecked = false;
                        check.Content = "Issued once created - Revit then locks it";
                        control = check;
                    }
                    else
                    {
                        var box = new TextBox();
                        box.Height = 28;
                        control = box;
                    }
                    Place(line, control);
                    Controls[field] = control;
                }
                foreach (var column in Staging.Columns)
                {
                    var line = Line(column.Name);
                    Control control;
                    if (column.Kind == "yesno")
                    {
                        var check = new CheckBox();
                        check.IsChecked = false;
                        control = check;
                    }
                    else if (column.Kind == "choice")
                    {
                        var combo = new ComboBox();
                        var choices = new List<string> { "" };
                        choices.AddRange(column.Choices ?? new List<string>());
                        PsUi.FillCombo(combo, choices, selected: "");
                        control = combo;
                    }
                    else
                    {
                        var box = new TextBox();
                        box.Height = 28;
                        box.Tag = PsRevData.KindLabels.TryGetValue(column.Kind ?? "", out string kindLabel) ? kindLabel : "";
                        control = box;
                    }
                    Place(line, control);
                    Controls["x_" + column.Id] = control;
                }
            }

            internal void Wire()
            {
                foreach (var (name, step) in new[] { ("SequenceDownButton", -1), ("SequenceUpButton", 1) })
                {
                    if (PsUi.Find(Window, name) is System.Windows.Controls.Primitives.ButtonBase button)
                    {
                        try
                        {
                            button.Click += MakeStep(step);
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
                if (Box != null)
                {
                    try
                    {
                        Box.TextChanged += (sender, args) => PaintNote();
                    }
                    catch (Exception)
                    {
                    }
                }
                foreach (var (name, handler) in new (string, RoutedEventHandler)[]
                         {
                             ("OkButton", Ok),
                             ("CancelButton", (sender, args) => Cancel()),
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
                try
                {
                    Window.PreviewKeyDown += KeyPressed;
                }
                catch (Exception)
                {
                }
            }

            internal RoutedEventHandler MakeStep(int step)
            {
                return (sender, args) =>
                {
                    var (ok, read, _) = ReadPosition(Typed(), Count);
                    int value = ok ? read : Count + 1;
                    value = Math.Max(1, Math.Min(Count + 1, value + step));
                    PsUi.SetText(Box, value.ToString(CultureInfo.InvariantCulture));
                };
            }

            internal string Typed()
            {
                try
                {
                    return Box.Text ?? "";
                }
                catch (Exception)
                {
                    return "";
                }
            }

            internal void PaintNote()
            {
                if (EditKey != null)
                {
                    PsUi.SetText(Note, string.Format(
                        "Sequence {0}. To move it, use Move up and Move down in the Revision Manager.", Typed()));
                    return;
                }
                var (ok, value, why) = ReadPosition(Typed(), Count);
                PsUi.SetText(Note, ok ? PositionNote(value, Rows) : why);
            }

            internal void KeyPressed(object sender, KeyEventArgs args)
            {
                try
                {
                    if (args.Key == Key.Escape)
                    {
                        Cancel();
                        args.Handled = true;
                    }
                }
                catch (Exception)
                {
                }
            }

            // ------------------------------------------------------------------
            /// <summary>(ok, the result, or why not).</summary>
            public (bool Ok, Answer Result, string Why) Answers()
            {
                var (ok, position, why) = ReadPosition(Typed(), Count);
                if (!ok) return (false, null, why);
                var fields = new Dictionary<string, object>(StringComparer.Ordinal);
                foreach (var (field, _, kind) in Fields)
                {
                    if (!Controls.TryGetValue(field, out Control control) || control == null) continue;
                    if (kind == "check")
                        fields[field] = ((CheckBox)control).IsChecked == true;
                    else if (kind == "numbering" || kind == "show")
                        fields[field] = PsUi.ComboText((ComboBox)control, blankText: "");
                    else
                        fields[field] = (((TextBox)control).Text ?? "").Trim();
                }
                var custom = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var column in Staging.Columns)
                {
                    if (!Controls.TryGetValue("x_" + column.Id, out Control control) || control == null) continue;
                    object value;
                    if (column.Kind == "yesno")
                        value = ((CheckBox)control).IsChecked == true;
                    else if (column.Kind == "choice")
                        value = PsUi.ComboText((ComboBox)control, blankText: "");
                    else
                        value = ((TextBox)control).Text ?? "";
                    var (good, stored) = PsRevData.Normalise(column, value);
                    if (!good) return (false, null, stored);
                    custom[column.Id] = stored;
                }
                return (true, new Answer { Position = position, Fields = fields, Custom = custom }, "");
            }

            internal void Ok(object sender, RoutedEventArgs args)
            {
                var (ok, answer, why) = Answers();
                if (!ok)
                {
                    PsUi.SetText(Status, why);
                    return;
                }
                Result = answer;
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

            public Answer Show()
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

        public static Answer Ask(PsRevisions.Staging staging, string themeName = "dark", Window owner = null,
            int? position = null, string note = "")
        {
            return new AddDialog(staging, themeName, owner, position, note).Show();
        }

        /// <summary>The Edit revision window for one revision, or null if cancelled.</summary>
        public static Answer AskEdit(PsRevisions.Staging staging, string key, string themeName = "dark", Window owner = null)
        {
            return new AddDialog(staging, themeName, owner, null, "", editKey: key).Show();
        }
    }
}
