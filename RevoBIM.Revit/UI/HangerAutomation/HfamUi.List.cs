using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using RevoBIM.Tools.HangerAutomation;

namespace RevoBIM.UI.HangerAutomation
{
    public sealed partial class FamTab
    {
        // ---- the list
        public string CategoryKey()
        {
            int i = C<ComboBox>("CmbFamCategory").SelectedIndex;
            return i >= 0 && i < HfamCore.Categories.Count ? HfamCore.Categories[i].Key : "all";
        }

        /// <summary>One line of the grouped list: a family header (Item null) or one of its types.</summary>
        private sealed class Ent
        {
            public FamTypeItem Item;
            public string Family;
            public FamRow Row;
        }

        private List<Ent> ents = new List<Ent>();
        private readonly HashSet<string> expanded = new HashSet<string>(StringComparer.Ordinal);
        private string chosenKey = "";

        /// <summary>
        /// The list is grouped by family: a header per family (click it to open or close its types), the types
        /// below, each line led by a symbol for the family's hanger style (rectangle or circle, from Family settings).
        /// reveal opens the chosen type's family; a header click passes false so it can close again.
        /// </summary>
        public void Refill(string keepKey = null, bool reveal = true)
        {
            if (keepKey == null) keepKey = chosenKey;
            loading = true;
            try
            {
                shown = HfamCore.FilterTypes(Items, CategoryKey(), C<TextBox>("TxtFamSearch").Text ?? "");
                if (C<ToggleButton>("ChkFamSetOnly").IsChecked == true)
                    shown = shown.Where(it => HfamCore.Configured(Fams, it.Family)).ToList();
                FamTypeItem keep = shown.FirstOrDefault(x => x.Key == keepKey);
                if (keep == null && shown.Count == 1) keep = shown[0];
                chosenKey = keep != null ? keep.Key : "";
                bool searching = !string.IsNullOrWhiteSpace(C<TextBox>("TxtFamSearch").Text);
                if (reveal && keep != null) expanded.Add(keep.Family);
                var order = new List<string>();
                var groups = new Dictionary<string, List<FamTypeItem>>(StringComparer.Ordinal);
                foreach (FamTypeItem it in shown)
                {
                    List<FamTypeItem> g;
                    if (!groups.TryGetValue(it.Family, out g))
                    {
                        g = new List<FamTypeItem>();
                        groups[it.Family] = g;
                        order.Add(it.Family);
                    }
                    g.Add(it);
                }
                var lst = C<ListBox>("LstFamilies");
                lst.Items.Clear();
                ents = new List<Ent>();
                int pick = -1;
                foreach (string fam in order)
                {
                    List<FamTypeItem> g = groups[fam];
                    bool open = searching || expanded.Contains(fam);
                    bool setUp = HfamCore.Configured(Fams, fam);
                    string style = CfgFor(g[0]).Style;
                    FamRow head = BuildRow(fam + "  (" + g.Count + ")", setUp, style, open ? "▾" : "▸", false);
                    ents.Add(new Ent { Family = fam, Row = head });
                    lst.Items.Add(head.Root);
                    if (!open) continue;
                    foreach (FamTypeItem it in g)
                    {
                        FamRow row = BuildRow(it.Type, setUp, style, "", true);
                        ents.Add(new Ent { Family = fam, Item = it, Row = row });
                        lst.Items.Add(row.Root);
                        if (it.Key == chosenKey) pick = ents.Count - 1;
                    }
                }
                lst.SelectedIndex = pick;
                if (pick >= 0) lst.ScrollIntoView(lst.Items[pick]);
            }
            catch (Exception)
            {
            }
            finally
            {
                loading = false;
            }
            PaintRows();
            ChosenChanged();
        }

        /// <summary>A list line: arrow column, style symbol column, then the text.</summary>
        private static FamRow BuildRow(string text, bool setUp, string style, string arrow, bool indent)
        {
            var g = new Grid();
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(14) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(22) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            if (indent) g.Margin = new Thickness(14, 0, 0, 0);
            var a = new TextBlock { Text = arrow, FontSize = 10, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
            a.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush");
            Grid.SetColumn(a, 0);
            g.Children.Add(a);
            bool circ = style == "circ";
            var sym = new TextBlock
            {
                Text = circ ? "◯" : "▭", FontFamily = new System.Windows.Media.FontFamily("Segoe UI Symbol"), FontSize = 13,
                HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center,
                ToolTip = circ ? "Circular hanger" : "Rectangular hanger",
            };
            Grid.SetColumn(sym, 1);
            g.Children.Add(sym);
            FamRow r = FamilyRow(text, setUp);
            r.Tb.TextTrimming = TextTrimming.CharacterEllipsis;
            Grid.SetColumn(r.Tb, 2);
            g.Children.Add(r.Tb);
            r.Root = g;
            return r;
        }

        /// <summary>
        /// Set-up families in bold green - the selected row in the normal text colour, so it still reads on the
        /// selection highlight.
        /// </summary>
        public void PaintRows()
        {
            int sel;
            try
            {
                sel = C<ListBox>("LstFamilies").SelectedIndex;
            }
            catch (Exception)
            {
                sel = -1;
            }
            for (int i = 0; i < ents.Count; i++)
            {
                FamRow row = ents[i].Row;
                if (row.SetUp)
                {
                    try
                    {
                        row.Tb.SetResourceReference(TextBlock.ForegroundProperty, i == sel ? "TextBrush" : "SetTextBrush");
                    }
                    catch (Exception)
                    {
                    }
                }
            }
        }

        public FamTypeItem Current()
        {
            return string.IsNullOrEmpty(chosenKey) ? null : shown.FirstOrDefault(x => x.Key == chosenKey);
        }

        private void FilterChanged(object sender, RoutedEventArgs e)
        {
            if (!loading) Refill();
        }

        private void Picked(object sender, SelectionChangedEventArgs e)
        {
            if (loading) return;
            int i = C<ListBox>("LstFamilies").SelectedIndex;
            if (i < 0 || i >= ents.Count) return;
            Ent en = ents[i];
            if (en.Item == null)   // a family header: open or close its types, whole line clickable
            {
                if (!expanded.Remove(en.Family)) expanded.Add(en.Family);
                C<ListBox>("LstFamilies").Dispatcher.BeginInvoke(new Action(() => Refill(chosenKey, false)));
                return;
            }
            chosenKey = en.Item.Key;
            PaintRows();
            ChosenChanged();
        }

        public FamConfig CfgFor(FamTypeItem it)
        {
            FamParams p;
            List<string> names = Params.TryGetValue(it.Family, out p) ? p.Names : new List<string>();
            return HfamCore.FamConfigFor(Fams, it.Family, names);
        }

        private void ChosenChanged()
        {
            FamTypeItem it = Current();
            var txt = C<TextBlock>("FamChosenTxt");
            if (it == null)
            {
                txt.Text = Items.Count > 0 ? "Choose the " + Noun + " family and type" :
                    "No Generic Model, MEP Ancillary Framing or Duct Accessory families in the project";
                ShowPreview(null);
                return;
            }
            FamConfig cfg = CfgFor(it);
            string width;
            if (cfg.Left.Length > 0 && cfg.Right.Length > 0) width = "width: " + cfg.Left + " / " + cfg.Right;
            else width = "width parameters not set - open Family settings";
            string setup = HfamCore.Configured(Fams, it.Family) ? "" : "  |  not set up yet";
            if (Floor && cfg.Style == "circ")
            {
                txt.Text = it.CatLabel + "  |  Circular System Based  |  diameter: " + Or(cfg.Dia, "(none)") +
                           "  |  height: " + Or(cfg.CircHeight, "(none)") + setup;
            }
            else if (Floor)
            {
                txt.Text = it.CatLabel + "  |  Rectangular Floor Based  |  " + width + "  |  first bar: " + Or(cfg.FirstBar, "(none)") +
                           "  |  height: " + Or(cfg.Height, "(none)") + setup;
            }
            else if (cfg.Style == "circ")
            {
                txt.Text = it.CatLabel + "  |  Circular System Based  |  diameter: " + Or(cfg.Dia, "(none)") +
                           "  |  rod: " + Or(cfg.Rod, "(none)") + setup;
            }
            else
            {
                txt.Text = it.CatLabel + "  |  " + width + "  |  rod: " + Or(cfg.Rod, "(none)") + setup;
            }
            if (previews.ContainsKey(it.Key)) ShowPreview(previews[it.Key]);
            else
            {
                ShowPreview(null, "Loading...");
                RequestPreview(it);
            }
        }

        /// <summary>Python's "x or y" on strings.</summary>
        private static string Or(string a, string b)
        {
            return !string.IsNullOrEmpty(a) ? a : b;
        }

        // ---- preview (read through the ExternalEvent)
        public void RequestPreview(FamTypeItem it)
        {
            wantPreview = it.Key;
            string key = it.Key;
            if (OpenDoc != null)   // opening the tool: the preview is read once the window is on screen (FhaWindow.ContentRendered)
            {
                ShowPreview(null, "Loading...");
                return;
            }
            bool started = O.StartQuiet(HfamRevit.PreviewJobFor(it.Id), (res, err) => GotPreview(key, res as byte[]));
            if (!started)   // Revit busy with another read: try again when it finishes (RetryPreview)
                ShowPreview(null, "Loading...");
        }

        /// <summary>A read has finished: fetch the chosen type's preview if it is still missing.</summary>
        public void RetryPreview()
        {
            FamTypeItem it = Current();
            if (it != null && !previews.ContainsKey(it.Key) && !O.Busy) RequestPreview(it);
        }

        private void GotPreview(string key, byte[] data)
        {
            previews[key] = data;
            FamTypeItem it = Current();
            if (it == null) return;
            if (it.Key == key) ShowPreview(data);
            else if (!previews.ContainsKey(it.Key)) RequestPreview(it);   // the selection moved on while we were reading
        }

        public void ShowPreview(byte[] data, string hint = "No preview")
        {
            var img = C<Image>("FamPreview");
            var lab = C<TextBlock>("FamPreviewHint");
            try
            {
                if (data != null && data.Length > 0)
                {
                    img.Source = FhaUi.BitmapFromBytes(data);
                    lab.Visibility = Visibility.Collapsed;
                }
                else
                {
                    img.Source = null;
                    lab.Text = hint;
                    lab.Visibility = Visibility.Visible;
                }
            }
            catch (Exception)
            {
            }
        }
    }
}
