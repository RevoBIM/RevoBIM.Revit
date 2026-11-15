using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// Change revision on sheet: which revision the picked cells become.
    /// Port of ps_revswapwin.py.
    ///
    /// Opened from the Document Register once one or more revision cells are
    /// picked. Lists every revision in the project; issued ones are shown but
    /// cannot be chosen, because Revit will not put an issued revision on a sheet
    /// or move a cloud onto one. Modal. Show() returns the chosen revision's
    /// element key (as text), or null.
    ///
    /// Nothing is written here. The register puts the change through the external
    /// event - see PsRevisions.SwapOnSheets.
    /// </summary>
    public static partial class PsRevSwapWin
    {
        /// <summary>One line for a revision in the list: sequence, date, description.</summary>
        public static string Describe(PsRegister.RevisionColumn revision)
        {
            var parts = new List<string> { string.Format("Seq {0}", PsUi.PyStr(revision.Sequence)) };
            if (!string.IsNullOrEmpty(revision.Date))
                parts.Add(revision.Date);
            if (!string.IsNullOrEmpty(revision.Description))
                parts.Add(revision.Description);
            return string.Join("  ·  ", parts);
        }

        /// <summary>Every word typed appears in the line, any case.</summary>
        public static bool Matches(PsRegister.RevisionColumn revision, string text)
        {
            string[] words = (text ?? "").ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            string line = Describe(revision).ToLowerInvariant();
            return words.All(word => line.Contains(word));
        }

        /// <summary>
        /// (can it be chosen, why not). Issued is locked; choosing what every
        /// picked cell already is would change nothing.
        /// </summary>
        public static (bool Ok, string Why) Choosable(PsRegister.RevisionColumn revision, IList<string> olds)
        {
            if (revision.Issued)
                return (false, "issued - Revit keeps it locked");
            string key = PsUi.PyStr(revision.ElementKey);
            if (olds != null && olds.Count > 0 && olds.All(old => old == key))
                return (false, "every picked cell is this already");
            return (true, "");
        }

        public class SwapDialog
        {
            public List<PsRegister.RevisionColumn> Revisions;
            public List<string> Olds;
            /// <summary>Show() result: the chosen revision's element key, as text.</summary>
            public string Result;
            /// <summary>(revision, ListBoxItem, can choose).</summary>
            public List<(PsRegister.RevisionColumn Revision, ListBoxItem Item, bool Ok)> Items =
                new List<(PsRegister.RevisionColumn, ListBoxItem, bool)>();

            public Window Window;
            public PsUi.Chrome Chrome;
            public ListBox List;
            public TextBox Search;
            public Button OkButton;
            public TextBlock Status;

            /// <summary>
            /// revisions are PsRegister.RevisionColumn; olds the element keys the
            /// picked cells are now (any type - each is compared as text). The
            /// wording can be replaced for another use of the same list - Assign
            /// revision to selected.
            /// </summary>
            public SwapDialog(IEnumerable<PsRegister.RevisionColumn> revisions, IEnumerable olds, int sheetCount, int cellCount,
                string themeName = "dark", Window owner = null, string headline = null,
                string fromText = null, string note = null, string okText = null)
            {
                Revisions = (revisions ?? Enumerable.Empty<PsRegister.RevisionColumn>())
                    .OrderBy(one => one.Sequence).ToList();
                Olds = new List<string>();
                if (olds != null)
                {
                    foreach (object one in olds)
                        Olds.Add(PsUi.PyStr(one));
                }
                Result = null;

                Window = PsUi.LoadWindow("ProSheetsRevSwap.xaml", themeName);
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
                List = PsUi.Find<ListBox>(Window, "SwapList");
                Search = PsUi.Find<TextBox>(Window, "SwapSearch");
                OkButton = PsUi.Find<Button>(Window, "OkButton");
                Status = PsUi.Find<TextBlock>(Window, "StatusText");

                PsUi.SetText(PsUi.Find(Window, "SwapHeadline"), !string.IsNullOrEmpty(headline)
                    ? headline
                    : string.Format("{0} revision cell{1} on {2} sheet{3}",
                        cellCount, cellCount == 1 ? "" : "s",
                        sheetCount, sheetCount == 1 ? "" : "s"));
                var byKey = new Dictionary<string, PsRegister.RevisionColumn>(StringComparer.Ordinal);
                foreach (var one in Revisions)
                    byKey[PsUi.PyStr(one.ElementKey)] = one;
                if (string.IsNullOrEmpty(fromText))
                {
                    string now = string.Join(";  ", Olds.Where(key => byKey.ContainsKey(key))
                        .Select(key => Describe(byKey[key])));
                    fromText = "Now: " + (now.Length > 0 ? now : "-");
                }
                PsUi.SetText(PsUi.Find(Window, "SwapFrom"), fromText);
                if (!string.IsNullOrEmpty(note))
                    PsUi.SetText(PsUi.Find(Window, "SwapNote"), note);
                if (!string.IsNullOrEmpty(okText))
                    PsUi.SetContent(OkButton, okText);
                Fill();
                Wire();
            }

            internal void Fill()
            {
                if (List == null) return;
                List.Items.Clear();
                Items = new List<(PsRegister.RevisionColumn, ListBoxItem, bool)>();
                foreach (var revision in Revisions)
                {
                    var (ok, why) = Choosable(revision, Olds);
                    var item = new ListBoxItem();
                    var row = new StackPanel();
                    row.Orientation = Orientation.Horizontal;
                    var line = new TextBlock();
                    line.Text = Describe(revision);
                    row.Children.Add(line);
                    if (!ok)
                    {
                        var note = new TextBlock();
                        note.Text = string.Format("  ({0})", why);
                        note.Margin = new Thickness(4, 0, 0, 0);
                        note.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush");
                        row.Children.Add(note);
                        item.IsEnabled = false;
                        item.Opacity = 0.55;
                    }
                    if (Olds.Contains(PsUi.PyStr(revision.ElementKey)))
                        line.SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush");
                    item.Content = row;
                    item.ToolTip = revision.Describe();
                    List.Items.Add(item);
                    Items.Add((revision, item, ok));
                }
            }

            internal void Wire()
            {
                if (List != null)
                {
                    try
                    {
                        List.SelectionChanged += (sender, args) => Picked(sender, args);
                        List.MouseDoubleClick += (sender, args) => Double(sender, args);
                    }
                    catch (Exception)
                    {
                    }
                }
                if (Search != null)
                {
                    try
                    {
                        Search.TextChanged += (sender, args) => Searched(sender, args);
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

            public PsRegister.RevisionColumn Chosen()
            {
                object item;
                try
                {
                    item = List.SelectedItem;
                }
                catch (Exception)
                {
                    return null;
                }
                foreach (var (revision, one, ok) in Items)
                {
                    if (ReferenceEquals(one, item) && ok) return revision;
                }
                return null;
            }

            internal void Picked(object sender, RoutedEventArgs args)
            {
                var revision = Chosen();
                try
                {
                    OkButton.IsEnabled = revision != null;
                }
                catch (Exception)
                {
                }
                PsUi.SetText(Status, revision != null
                    ? string.Format("Change to: {0}", Describe(revision))
                    : "Pick the revision to change them to.");
            }

            internal void Searched(object sender, RoutedEventArgs args)
            {
                string text;
                try
                {
                    text = Search.Text ?? "";
                }
                catch (Exception)
                {
                    text = "";
                }
                foreach (var (revision, item, _) in Items)
                    PsUi.SetVisible(item, Matches(revision, text));
            }

            internal void Double(object sender, RoutedEventArgs args)
            {
                if (Chosen() != null) Ok(sender, args);
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

            internal void Ok(object sender, RoutedEventArgs args)
            {
                var revision = Chosen();
                if (revision == null) return;
                Result = PsUi.PyStr(revision.ElementKey);
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

        /// <summary>The Python's choose(..., **wording): headline, from_text, note, ok_text.</summary>
        public static string Choose(IEnumerable<PsRegister.RevisionColumn> revisions, IEnumerable olds, int sheetCount,
            int cellCount, string themeName = "dark", Window owner = null, string headline = null,
            string fromText = null, string note = null, string okText = null)
        {
            return new SwapDialog(revisions, olds, sheetCount, cellCount, themeName, owner,
                headline, fromText, note, okText).Show();
        }
    }
}
