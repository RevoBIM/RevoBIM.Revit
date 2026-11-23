using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using Autodesk.Revit.UI;
using RevoBIM.Tools.MatchOffset;

using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using Grid = System.Windows.Controls.Grid;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.MatchOffset
{
    /// <summary>
    /// The results window. Opened only when something needs a look, which is the default: a clean run finishes with no
    /// dialog at all, because the whole point of a pick-driven tool is that it does not interrupt. Port of results_window.py.
    /// </summary>
    internal static class MoResultsWindow
    {
        /// <summary>
        /// One reported line. A Grid, not a horizontal StackPanel: a horizontal StackPanel measures its children with
        /// infinite width, so a TextBlock inside one never wraps and the end of the sentence is lost.
        /// </summary>
        private static Border Row(string text, string brushKey)
        {
            var shell = new Border { CornerRadius = new CornerRadius(4), Margin = new Thickness(0, 0, 0, 6), Padding = new Thickness(10, 7, 10, 7) };
            shell.SetResourceReference(Border.BackgroundProperty, "CardBrush");

            var inner = new Grid();
            inner.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            inner.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1.0, GridUnitType.Star) });

            var tick = new Border { Width = 4, CornerRadius = new CornerRadius(2), Margin = new Thickness(0, 0, 9, 0) };
            tick.SetResourceReference(Border.BackgroundProperty, brushKey);
            Grid.SetColumn(tick, 0);

            var label = new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap };
            Grid.SetColumn(label, 1);

            inner.Children.Add(tick);
            inner.Children.Add(label);
            shell.Child = inner;
            return shell;
        }

        public static void Show(MoReport report, Dictionary<string, string> settings, string anchorLabel, UIApplication uiapp)
        {
            Window window = MoUi.LoadWindow("MatchOffsetResults.xaml", MoCore.Get(settings, "theme"));
            MoUi.WireHeader(window, settings);
            MoUi.AddResizeGrips(window);
            MoUi.OwnToRevit(window, uiapp);

            ((TextBlock)window.FindName("SummaryLine")).Text = report.Problems.Count > 0
                ? report.Matched + " matched, " + report.Problems.Count + " to look at"
                : report.Matched + " matched";
            ((TextBlock)window.FindName("DatumLine")).Text = report.DatumText.Length > 0 ? report.DatumText : anchorLabel;

            var panel = (StackPanel)window.FindName("ReportPanel");
            foreach (string text in report.Problems) panel.Children.Add(Row(text, "RedBrush"));
            foreach (string text in report.Notes) panel.Children.Add(Row(text, "MutedBrush"));
            if (report.Problems.Count == 0 && report.Notes.Count == 0) panel.Children.Add(Row("Nothing needed a look.", "GreenBrush"));

            var status = (TextBlock)window.FindName("StatusText");
            status.Text = report.Debug != null
                ? "Each element is its own undo step. The debug report opens next."
                : "Each element is its own undo step.";

            ((Button)window.FindName("DoneButton")).Click += (s, a) => window.Close();
            window.ShowDialog();
        }
    }

    /// <summary>
    /// The debug report window. Opens after a run while the debug tick is on: the whole report in a selectable box with
    /// a Copy button, and written to disk as well so closing the window does not throw it away. Port of debug_window.py.
    /// </summary>
    internal static class MoDebugWindow
    {
        public static void Show(MoRecorder recorder, Dictionary<string, string> settings, UIApplication uiapp)
        {
            if (recorder == null) return;
            string text = recorder.Text();
            string path = recorder.Save();

            Window window = MoUi.LoadWindow("MatchOffsetDebug.xaml", MoCore.Get(settings, "theme"));
            MoUi.WireHeader(window, settings);
            MoUi.AddResizeGrips(window);
            MoUi.OwnToRevit(window, uiapp);

            ((TextBox)window.FindName("DebugText")).Text = text;
            ((TextBlock)window.FindName("DebugLead")).Text = recorder.Tool + " ran, " + recorder.Matched + " matched, " + recorder.Problems +
                " to look at. Press Copy and paste the lot into the chat - it carries the build, the settings, the geometry and Revit's own words. " +
                "Turn it off under Settings > Picking and shortcuts > Diagnostics.";
            var status = (TextBlock)window.FindName("StatusText");
            status.Text = path.Length > 0 ? path : "the report could not be written to disk";

            ((Button)window.FindName("CopyButton")).Click += (s, a) =>
            {
                try
                {
                    Clipboard.SetDataObject(text, true);
                    status.Text = "Copied. Paste it anywhere.";
                }
                catch (Exception err)
                {
                    status.Text = "The clipboard refused it: " + err.Message + ". The file is at " + path;
                }
            };

            ((Button)window.FindName("SaveButton")).Click += (s, a) =>
            {
                try
                {
                    Process.Start(new ProcessStartInfo(MoCore.AppDataDir()) { UseShellExecute = true });
                }
                catch (Exception)
                {
                    status.Text = path.Length > 0 ? path : MoCore.AppDataDir();
                }
            };

            ((Button)window.FindName("DoneButton")).Click += (s, a) => window.Close();

            MoCore.Log("debug report shown, " + recorder.Lines.Count + " lines");
            window.ShowDialog();
        }
    }
}
