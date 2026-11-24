using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.FamilyFindReplace;

using Button = System.Windows.Controls.Button;
using Panel = System.Windows.Controls.Panel;
using Visibility = System.Windows.Visibility;
using RadioButton = System.Windows.Controls.RadioButton;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.FamilyFindReplace
{
    /// <summary>
    /// Orientation and height, set afterwards on the whole set at once. Both numbers are absolute, measured from
    /// where the replacements landed; only the difference is written to the model. Modeless, so Revit stays usable.
    /// </summary>
    internal sealed class FfrAdjustWindow
    {
        private readonly Window parent;
        private readonly FfrJobHandler handler;
        private readonly ExternalEvent externalEvent;
        private readonly List<ElementId> ids;
        private readonly bool drafting;
        private readonly bool aboutCentre;
        private readonly FfrDrawer drawer;
        private double appliedDegrees;
        private double appliedZ;

        public Window Window { get; private set; }

        public FfrAdjustWindow(Window parent, FfrJobHandler handler, ExternalEvent externalEvent, IEnumerable<ElementId> ids, bool drafting, bool aboutCentre)
        {
            this.parent = parent;
            this.handler = handler;
            this.externalEvent = externalEvent;
            this.ids = ids.ToList();
            this.drafting = drafting;
            this.aboutCentre = drafting && aboutCentre;

            Window = FfrXaml.LoadWindow("FamilyFindReplaceAdjust.xaml");
            Window.Owner = parent;
            var header = (Border)Find("AdjHeaderBar");
            drawer = new FfrDrawer(Window, header, (Panel)header.Parent, (Button)Find("AdjShrinkBtn"));
            FfrXaml.LoadIcon((Image)Find("AdjIconImage"));
            ((TextBlock)Find("AdjVersionText")).Text = "v" + FfrCore.Version;
            var count = (TextBlock)Find("AdjCountText");
            if (drafting)
            {
                // detail items in a drafting view: no depth to offset into, and each turns about its own centre so it stays on its import's
                Find("AdjHeightCard").Visibility = Visibility.Collapsed;
                count.Text = this.ids.Count + " detail item(s). Each one turns about its own " + (this.aboutCentre ? "centre" : "insertion point") +
                             ", so it stays exactly where its import symbol was.";
            }
            else
            {
                count.Text = this.ids.Count + " replacement(s). Each one turns about its own insertion point, so a bank of devices keeps its setting out.";
            }

            header.MouseLeftButtonDown += (s, a) =>
            {
                // a double click on a parked bar opens it; anything else drags
                if (drawer.OnHeaderDown(a)) return;
                try
                {
                    Window.DragMove();
                }
                catch (Exception)
                {
                }
            };
            ((Button)Find("AdjCloseBtn")).Click += (s, a) =>
            {
                try
                {
                    Window.Close();
                }
                catch (Exception)
                {
                }
            };
            ((Button)Find("AdjApplyBtn")).Click += Apply;
            ((Button)Find("AdjResetBtn")).Click += Reset;
            ((Button)Find("AdjSelectBtn")).Click += SelectInModel;
            foreach (string name in new[] { "Rot0", "Rot90", "Rot180", "Rot270", "RotCustom" })
                ((RadioButton)Find(name)).Checked += (s, a) =>
                {
                    try
                    {
                        Find("RotCustomBox").IsEnabled = ((RadioButton)Find("RotCustom")).IsChecked == true;
                    }
                    catch (Exception)
                    {
                    }
                };
        }

        private FrameworkElement Find(string name) { return (FrameworkElement)Window.FindName(name); }

        public void Show() { Window.Show(); }

        private double? TargetDegrees()
        {
            foreach (KeyValuePair<string, double> pair in new[]
                     {
                         new KeyValuePair<string, double>("Rot0", 0.0), new KeyValuePair<string, double>("Rot90", 90.0),
                         new KeyValuePair<string, double>("Rot180", 180.0), new KeyValuePair<string, double>("Rot270", 270.0),
                     })
            {
                if (((RadioButton)Find(pair.Key)).IsChecked == true) return pair.Value;
            }
            return ParseNumber(((TextBox)Find("RotCustomBox")).Text);
        }

        private double? TargetZ()
        {
            if (drafting) return 0.0;
            return ParseNumber(((TextBox)Find("ZOffsetBox")).Text);
        }

        private static double? ParseNumber(string text)
        {
            text = (text ?? "").Trim();
            if (text.Length == 0) return 0.0;
            double value;
            if (double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out value)) return value;
            if (double.TryParse(text, NumberStyles.Float, CultureInfo.CurrentCulture, out value)) return value;
            return null;
        }

        private void Status(string text)
        {
            try
            {
                ((TextBlock)Find("AdjStatusText")).Text = text;
            }
            catch (Exception)
            {
            }
        }

        private void Reset(object sender, RoutedEventArgs args)
        {
            ((RadioButton)Find("Rot0")).IsChecked = true;
            ((TextBox)Find("RotCustomBox")).Text = "0";
            ((TextBox)Find("ZOffsetBox")).Text = "0";
            Apply(sender, args);
        }

        private void SelectInModel(object sender, RoutedEventArgs args)
        {
            handler.Queue(uiapp =>
            {
                FfrCore.SelectElements(uiapp.ActiveUIDocument, ids);
                Status(ids.Count + " element(s) selected.");
            });
            externalEvent.Raise();
        }

        private void Apply(object sender, RoutedEventArgs args)
        {
            double? degrees = TargetDegrees();
            double? offset = TargetZ();
            if (degrees == null)
            {
                Status("The custom angle is not a number.");
                return;
            }
            if (offset == null)
            {
                Status("The Z offset is not a number.");
                return;
            }
            double deltaDegrees = degrees.Value - appliedDegrees;
            double deltaZ = offset.Value - appliedZ;
            if (Math.Abs(deltaDegrees) < 1.0e-9 && Math.Abs(deltaZ) < 1.0e-9)
            {
                Status("Already there - nothing to apply.");
                return;
            }
            handler.Queue(uiapp =>
            {
                Document doc = uiapp.ActiveUIDocument.Document;
                var problems = new List<string>();
                int moved = FfrCore.AdjustElements(doc, ids, deltaDegrees, deltaZ, aboutCentre, problems);
                appliedDegrees = degrees.Value;
                appliedZ = offset.Value;
                FfrLog.Write("adjust: " + ids.Count + " element(s), turn " + deltaDegrees.ToString("0.###", CultureInfo.InvariantCulture) + " deg, z " +
                             deltaZ.ToString("0.###", CultureInfo.InvariantCulture) + "mm, about " + (aboutCentre ? "centre" : "insertion point") +
                             "; moved " + moved + ", " + problems.Count + " problem(s)" +
                             (problems.Count > 0 ? " [" + string.Join(" | ", problems) + "]" : ""));
                if (problems.Count > 0)
                    Status(moved + " adjusted at " + degrees.Value + " degrees, " + offset.Value + "mm. " + problems.Count + " would not move.");
                else
                    Status(moved + " adjusted - " + degrees.Value + " degrees, " + offset.Value + "mm.");
            });
            externalEvent.Raise();
        }
    }
}
