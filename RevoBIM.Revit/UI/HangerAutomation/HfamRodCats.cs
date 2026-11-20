using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using RevoBIM.Tools.HangerAutomation;

namespace RevoBIM.UI.HangerAutomation
{
    // Hanger Automation - the "Rod target categories" window. New in the C# add-in (no pyRevit original).
    //
    // When "Extend drop rod up to soffit" is used, a drop rod runs up to the structure categories ticked on the FAB
    // tab (Floors / Structural framing / Roofs) and to the extra categories in the setting ext_extra (a
    // comma-separated list of BuiltInCategory names, FhaRevit.ExtraCategories). This window lists every model
    // category of the open project with a tick; OK writes the ticked ones back to ext_extra.

    /// <summary>The rod target categories window: a search box, every model category with a tick, ticked ones first.</summary>
    public sealed class RodCatsDialog
    {
        /// <summary>The setting that holds the extra categories.</summary>
        public const string Key = "ext_extra";

        private sealed class Row
        {
            public string Name;        // what is listed
            public string Bic;         // BuiltInCategory name, what is saved
            public bool InModel;       // false: saved in ext_extra but the project has no such category
            public bool Ticked;        // the state: the CheckBoxes in the list are made afresh on every search
        }

        public readonly IFhaHost O;
        public bool Ok;
        public string Result;          // the new ext_extra value (comma-separated BuiltInCategory names)
        public int Count;              // how many are ticked in Result
        public readonly Window Win;
        public readonly FhaDrawer Drawer;
        private readonly List<Row> rows = new List<Row>();
        private bool loading;

        /// <summary>
        /// <paramref name="model"/> is the project's categories (FhaRevit.ModelCategories); <paramref name="extra"/> the
        /// current ext_extra value. A category stored in <paramref name="extra"/> that the project does not contain is
        /// kept, ticked, and shown as "(not in this model)" - saving never loses it unless it is unticked.
        /// </summary>
        public RodCatsDialog(IFhaHost owner, IEnumerable<FhaRevit.CategoryChoice> model, string extra)
        {
            O = owner;
            Ok = false;
            Result = null;
            Win = FhaUi.LoadXamlWindow("HangerRodCats.xaml");
            FhaUi.ApplyPalette(Win, owner.Mode);
            FhaUi.PlaceDialog(Win, owner);
            Drawer = FhaUi.DialogDrawer(Win, owner, (FrameworkElement)C("RodCatsHeader"), (ButtonBase)C("RodCatsShrinkBtn"),
                                        (UIElement)C("RodCatsShrinkIcon"), (UIElement)C("RodCatsExpandIcon"));
            ((TextBlock)C("RodCatsVerTxt")).Text = "v" + FhaCore.Version;

            var stored = new List<string>();
            foreach (string raw in (extra ?? "").Split(new[] { ',', ';' }, StringSplitOptions.RemoveEmptyEntries))
            {
                string b = raw.Trim();
                if (b.Length > 0 && !stored.Contains(b)) stored.Add(b);
            }
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (FhaRevit.CategoryChoice c in model ?? Enumerable.Empty<FhaRevit.CategoryChoice>())
            {
                if (c == null || string.IsNullOrEmpty(c.Bic) || !seen.Add(c.Bic)) continue;
                rows.Add(new Row { Name = c.Name ?? c.Bic, Bic = c.Bic, InModel = true });
            }
            foreach (string b in stored)
            {
                if (!seen.Add(b)) continue;
                rows.Add(new Row { Name = (b.StartsWith("OST_", StringComparison.Ordinal) ? b.Substring(4) : b) + "  (not in this model)", Bic = b, InModel = false });
            }
            foreach (Row r in rows) r.Ticked = stored.Contains(r.Bic);
            Refill();
            ((TextBoxBase)C("RodCatsSearch")).TextChanged += SearchChanged;
            ((ButtonBase)C("RodCatsOk")).Click += Save;
            ((ButtonBase)C("RodCatsCancel")).Click += Cancel;
            ((ButtonBase)C("RodCatsCloseBtn")).Click += Cancel;
            ((UIElement)C("RodCatsHeader")).MouseLeftButtonDown += Drag;
        }

        public object C(string name)
        {
            return Win.FindName(name);
        }

        private void Drag(object sender, MouseButtonEventArgs e)
        {
            try
            {
                Win.DragMove();
            }
            catch (Exception)
            {
            }
        }

        private int NumTicked()
        {
            return rows.Count(r => r.Ticked);
        }

        /// <summary>The list for the search words: ticked categories first, then by name (the order is set here, not on each tick).</summary>
        private void Refill()
        {
            string query = "";
            try
            {
                query = ((TextBox)C("RodCatsSearch")).Text ?? "";
            }
            catch (Exception)
            {
            }
            loading = true;
            try
            {
                var lst = (ListBox)C("RodCatsList");
                lst.Items.Clear();
                List<Row> shown = rows.Where(r => FhaCore.MatchWords(r.Name, query))
                                      .OrderBy(r => r.Ticked ? 0 : 1)
                                      .ThenBy(r => r.Name, StringComparer.OrdinalIgnoreCase).ToList();
                foreach (Row r in shown)
                {
                    var cb = new CheckBox();
                    cb.Content = r.Name;
                    cb.Margin = new Thickness(0, 2, 0, 2);
                    cb.IsChecked = r.Ticked;
                    cb.Tag = r;
                    cb.ToolTip = r.Bic;
                    if (!r.InModel) cb.SetResourceReference(Control.ForegroundProperty, "MutedBrush");
                    cb.Checked += Ticked;
                    cb.Unchecked += Ticked;
                    lst.Items.Add(cb);
                }
                ((TextBlock)C("RodCatsCount")).Text = CountText(shown.Count);
            }
            catch (Exception)
            {
            }
            finally
            {
                loading = false;
            }
        }

        private string CountText(int shown)
        {
            return NumTicked() + " ticked  |  " + shown + " of " + rows.Count + " categories shown";
        }

        private void SearchChanged(object sender, TextChangedEventArgs e)
        {
            if (!loading) Refill();
        }

        private void Ticked(object sender, RoutedEventArgs e)
        {
            if (loading) return;
            try
            {
                var cb = sender as CheckBox;
                var row = cb != null ? cb.Tag as Row : null;
                if (row != null) row.Ticked = cb.IsChecked == true;
                ((TextBlock)C("RodCatsCount")).Text = CountText(((ListBox)C("RodCatsList")).Items.Count);
            }
            catch (Exception)
            {
            }
        }

        private void Save(object sender, RoutedEventArgs e)
        {
            try
            {
                List<string> ticked = rows.Where(r => r.Ticked).Select(r => r.Bic).ToList();
                ticked.Sort(StringComparer.Ordinal);
                Result = string.Join(",", ticked);
                Count = ticked.Count;
                Ok = true;
            }
            catch (Exception)
            {
                Ok = false;
            }
            Win.Close();
        }

        private void Cancel(object sender, RoutedEventArgs e)
        {
            Win.Close();
        }

        public bool Show()
        {
            Win.ShowDialog();
            return Ok;
        }

        // ---- opening it
        /// <summary>
        /// The "Rod targets..." buttons: read the project's model categories as a quiet job (through the window's
        /// ExternalEvent), then show the window; OK stores the ticked list in <c>Settings["ext_extra"]</c> and saves.
        /// </summary>
        public static void Run(IFamOwner o)
        {
            try
            {
                bool started = o.StartQuiet((u, s, l) => FhaRevit.ModelCategories(u.Document), (res, err) =>
                {
                    var list = res as List<FhaRevit.CategoryChoice>;
                    if (!string.IsNullOrEmpty(err) || list == null)
                    {
                        o.Status("Could not read the model categories - see Copy debug");
                        return;
                    }
                    try
                    {
                        // after the read has finished (the window is free again), not inside its callback
                        o.Win.Dispatcher.BeginInvoke(new Action(() => Open(o, list)));
                    }
                    catch (Exception)
                    {
                        Open(o, list);
                    }
                }, "Reading the model categories...");
                if (!started) o.Status("Revit is busy - try again in a moment");
            }
            catch (Exception ex)
            {
                o.Status("Rod targets failed: " + ex.Message);
            }
        }

        private static void Open(IFamOwner o, List<FhaRevit.CategoryChoice> list)
        {
            try
            {
                var dlg = new RodCatsDialog(o, list, FhaCore.Get(o.Settings, Key, ""));
                if (dlg.Show())
                {
                    o.Settings[Key] = dlg.Result;
                    o.Save();
                    o.Status("Rod target categories saved (" + dlg.Count + " ticked)");
                }
            }
            catch (Exception ex)
            {
                o.Status("Rod targets failed: " + ex.Message);
            }
        }
    }
}
