using System;
using System.Windows;
using System.Windows.Input;
using RevoBIM.Tools.LegendCreator;

namespace RevoBIM.UI.LegendCreator
{
    /// <summary>The debug report, in one selectable block with a Copy button. Port of lgc_report.DebugWindow.</summary>
    public partial class LegendCreatorDebug : Window
    {
        private readonly WindowDrawer drawer;
        private readonly string report;

        public LegendCreatorDebug(string report, string themeName, bool copied, string savedTo, bool crashed)
        {
            InitializeComponent();
            version_tb.Text = "v" + LgcCore.Version;
            LgcTheme.ApplyPalette(this, themeName);
            drawer = new WindowDrawer(this, header_bar, shrink_btn);
            this.report = report;

            header_bar.MouseLeftButtonDown += DragWindow;
            shrink_btn.Click += (s, e) => drawer.Toggle();
            close_btn.Click += (s, e) => Close();
            done_btn.Click += (s, e) =>
            {
                if (!drawer.Intercept()) Close();
            };
            copy_btn.Click += CopyClicked;

            title_tb.Text = crashed ? "Legend Creator stopped with an error" : "Debug report";
            hint_tb.Text = copied
                ? "Already copied to your clipboard - paste it straight into the chat."
                : "Click Copy report, then paste it into the chat.";
            where_tb.Text = string.IsNullOrEmpty(savedTo) ? "" : "Also saved to " + savedTo;
            report_tb.Text = report;
        }

        private void CopyClicked(object sender, RoutedEventArgs args)
        {
            if (drawer.Intercept()) return;
            if (LgcReport.CopyToClipboard(report))
            {
                copy_btn.Content = "Copied";
            }
            else
            {
                // select it all so Ctrl+C works when the clipboard is busy
                report_tb.Focus();
                report_tb.SelectAll();
                copy_btn.Content = "Press Ctrl+C";
            }
        }

        private void DragWindow(object sender, MouseButtonEventArgs args)
        {
            if (drawer.HeaderDown(args)) return;
            try
            {
                DragMove();
            }
            catch (Exception)
            {
            }
        }
    }
}
