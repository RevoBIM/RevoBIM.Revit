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
        // ---- the family list: drag its grip to show more or fewer families
        private void ListDrag(object sender, DragDeltaEventArgs e)
        {
            try
            {
                var lst = C<ListBox>("LstFamilies");
                double old = lst.Height;
                double nu = ListHeight(old + e.VerticalChange);
                if (Math.Abs(nu - old) > 0.1)
                {
                    lst.Height = nu;
                    listGrow += nu - old;
                }
            }
            catch (Exception)
            {
            }
        }

        private void ListDropped(object sender, DragCompletedEventArgs e)
        {
            double grow = listGrow;
            listGrow = 0.0;
            try
            {
                if (Math.Abs(grow) > 0.5) O.ResizeForFold(grow);   // the window follows, like opening a tool
            }
            catch (Exception)
            {
            }
        }

        private TextChangedEventHandler Mirror(string src, string dst)
        {
            return (sender, e) =>
            {
                if (mirroring || loading) return;
                mirroring = true;
                try
                {
                    C<TextBox>(dst).Text = C<TextBox>(src).Text;
                }
                catch (Exception)
                {
                }
                finally
                {
                    mirroring = false;
                }
            };
        }

        private SelectionChangedEventHandler MirrorSel(string src, string dst)
        {
            return (sender, e) =>
            {
                if (mirroring || loading) return;
                mirroring = true;
                try
                {
                    C<ComboBox>(dst).SelectedIndex = C<ComboBox>(src).SelectedIndex;
                }
                catch (Exception)
                {
                }
                finally
                {
                    mirroring = false;
                }
            };
        }

        // ---- folding tools
        private void ToggleAll(object sender, RoutedEventArgs e)
        {
            try
            {
                fold.SetAll(!fold.AllOpen());
            }
            catch (Exception)
            {
            }
        }

        private void FoldChanged()
        {
            try
            {
                C<TextBlock>("FamToggleAllTxt").Text = fold.AllOpen() ? "Collapse all" : "Expand all";
            }
            catch (Exception)
            {
            }
        }

        private void RulesClick(object sender, RoutedEventArgs e)
        {
            try
            {
                var dlg = new RulesDialog(O, O.Settings);
                if (dlg.Show())
                {
                    foreach (KeyValuePair<string, string> kv in dlg.Result) O.Settings[kv.Key] = kv.Value;
                    O.Save();
                    O.Status("Hanger rules saved");
                }
            }
            catch (Exception ex)
            {
                O.Status("Hanger rules failed: " + ex.Message);
            }
        }

        public void SetBusy(bool isBusy)
        {
            busy = isBusy;
            foreach (string n in buttons)
            {
                try
                {
                    ((UIElement)C(n)).IsEnabled = !isBusy;
                }
                catch (Exception)
                {
                }
            }
            SetViewOk(ViewOk);
        }

        /// <summary>The dimension placer only lights up in a floor plan.</summary>
        public void SetViewOk(bool ok)
        {
            ViewOk = ok;
            try
            {
                ((UIElement)C("BtnFamDims")).IsEnabled = ViewOk && !busy;
                ((UIElement)C("FamDimHint")).Visibility = ViewOk ? Visibility.Collapsed : Visibility.Visible;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Family settings and the chosen type, for Copy debug.</summary>
        public string DebugText()
        {
            FamTypeItem it = Current();
            var lines = new List<string>
            {
                "[" + (Floor ? "Family Floor Support" : "Family Hangers") + "]",
                "Chosen: " + (it != null ? it.Key + " (" + it.CatLabel + ")" : "(none)"),
                "Families listed: " + Items.Count,
                "Floor plan active: " + (ViewOk ? "True" : "False"),
            };
            if (it != null)
            {
                FamConfig cfg = CfgFor(it);
                var keys = HfamCore.FamKeys.ToList();
                keys.Sort(StringComparer.Ordinal);
                lines.Add("Chosen family settings: " + string.Join(" | ", keys.Select(k => k + "=" + cfg[k])));
                FamParams p;
                if (!Params.TryGetValue(it.Family, out p)) p = new FamParams(new List<string>(), "not read yet");
                lines.Add("Parameters (" + p.Source + "): " + string.Join(", ", p.Names));
            }
            lines.Add(HfamCore.DumpFamilies(Fams));
            return string.Join("\n", lines);
        }
    }
}
