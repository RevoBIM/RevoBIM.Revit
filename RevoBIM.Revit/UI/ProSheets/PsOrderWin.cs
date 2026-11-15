using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// Page order for a combined PDF. Port of ps_orderwin.py.
    ///
    /// Only reachable when "Combine multiple views/sheets into a single file" is on,
    /// because it is the only time the order is a decision rather than a side effect
    /// of how the table happens to be sorted.
    /// </summary>
    public static partial class PsOrderWin
    {
        /// <summary>Modal. Show() returns the reordered list of keys, or null when cancelled.</summary>
        public class OrderWindow
        {
            /// <summary>(key, label), already in the current order.</summary>
            public List<(string Key, string Label)> Entries;
            public List<string> Result;
            public Window Window;
            public PsUi.Chrome Chrome;
            public ListBox ListBox;

            public OrderWindow(IEnumerable<(string Key, string Label)> entries, string themeName = "dark", Window owner = null)
            {
                Entries = entries != null ? entries.ToList() : new List<(string Key, string Label)>();
                Result = null;

                Window = PsUi.LoadWindow("ProSheetsOrder.xaml", themeName);
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

                ListBox = PsUi.Find<ListBox>(Window, "OrderList");
                Fill();
                Wire();
                SayCount();
            }

            internal void Fill()
            {
                if (ListBox == null) return;
                try
                {
                    ListBox.Items.Clear();
                    foreach (var (_, label) in Entries)
                        ListBox.Items.Add(label);
                }
                catch (Exception)
                {
                }
            }

            internal void SayCount()
            {
                PsUi.SetText(PsUi.Find(Window, "StatusText"),
                    string.Format("{0} page{1}, top to bottom.", Entries.Count, Entries.Count == 1 ? "" : "s"));
            }

            internal void Wire()
            {
                var pairs = new (string Name, RoutedEventHandler Handler)[]
                {
                    ("MoveTopButton", MoveTop),
                    ("MoveUpButton", MoveUp),
                    ("MoveDownButton", MoveDown),
                    ("MoveBottomButton", MoveBottom),
                    ("SortButton", Sort),
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
            }

            internal List<int> Selected()
            {
                var found = new List<int>();
                if (ListBox == null) return found;
                try
                {
                    for (int index = 0; index < ListBox.Items.Count; index++)
                    {
                        if (ListBox.SelectedItems.Contains(ListBox.Items[index]))
                            found.Add(index);
                    }
                }
                catch (Exception)
                {
                    return new List<int>();
                }
                return found;
            }

            internal void Apply(IList<int> order, IList<int> reselect = null)
            {
                Entries = order.Select(index => Entries[index]).ToList();
                Fill();
                if (reselect != null && reselect.Count > 0)
                {
                    try
                    {
                        ListBox.SelectedItems.Clear();
                        foreach (int index in reselect)
                        {
                            if (index >= 0 && index < ListBox.Items.Count)
                                ListBox.SelectedItems.Add(ListBox.Items[index]);
                        }
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal void Shift(int step)
            {
                var picked = Selected();
                if (picked.Count == 0) return;
                int count = Entries.Count;
                var order = Enumerable.Range(0, count).ToList();
                var sequence = step < 0 ? picked : Enumerable.Reverse(picked).ToList();
                var landed = new List<int>();
                foreach (int index in sequence)
                {
                    int position = order.IndexOf(index);
                    int target = position + step;
                    if (target < 0 || target >= count)
                    {
                        landed.Add(position);
                        continue;
                    }
                    int swap = order[position];
                    order[position] = order[target];
                    order[target] = swap;
                    landed.Add(target);
                }
                Apply(order, landed);
            }

            internal void MoveUp(object sender, RoutedEventArgs args)
            {
                Shift(-1);
            }

            internal void MoveDown(object sender, RoutedEventArgs args)
            {
                Shift(1);
            }

            internal void MoveTop(object sender, RoutedEventArgs args)
            {
                var picked = Selected();
                if (picked.Count == 0) return;
                var rest = Enumerable.Range(0, Entries.Count).Where(i => !picked.Contains(i)).ToList();
                Apply(picked.Concat(rest).ToList(), Enumerable.Range(0, picked.Count).ToList());
            }

            internal void MoveBottom(object sender, RoutedEventArgs args)
            {
                var picked = Selected();
                if (picked.Count == 0) return;
                var rest = Enumerable.Range(0, Entries.Count).Where(i => !picked.Contains(i)).ToList();
                Apply(rest.Concat(picked).ToList(), Enumerable.Range(rest.Count, picked.Count).ToList());
            }

            internal void Sort(object sender, RoutedEventArgs args)
            {
                var order = Enumerable.Range(0, Entries.Count)
                    .OrderBy(i => PsModel.NaturalKey(Entries[i].Label))
                    .ToList();
                Apply(order);
            }

            internal void Ok(object sender, RoutedEventArgs args)
            {
                Result = Entries.Select(entry => entry.Key).ToList();
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
    }
}
