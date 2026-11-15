using System;
using System.Windows;
using System.Windows.Input;
using RevoBIM.Tools.LegendCreator;
using static RevoBIM.Tools.LegendCreator.LgcLogic;

namespace RevoBIM.UI.LegendCreator
{
    /// <summary>
    /// Completion prompt, and the one question the run asks: open the new
    /// legend now? The headline pulses via a storyboard in the XAML.
    /// Port of lgc_windows.DoneWindow.
    /// </summary>
    public partial class LegendCreatorDone : Window
    {
        private readonly WindowDrawer drawer;

        public bool OpenRequested { get; private set; }

        public LegendCreatorDone(int legends, int components, int skipped, int scale,
                                 string themeName, string firstName, bool debug)
        {
            InitializeComponent();
            version_tb.Text = "v" + LgcCore.Version;
            LgcTheme.ApplyPalette(this, themeName);
            drawer = new WindowDrawer(this, header_bar, shrink_btn);

            header_bar.MouseLeftButtonDown += DragWindow;
            shrink_btn.Click += (s, e) => drawer.Toggle();
            close_btn.Click += (s, e) => Dismiss(true);
            done_btn.Click += (s, e) => Dismiss(false);
            open_btn.Click += OpenClicked;

            string where = debug ? "see the debug log in %APPDATA%\\RevoBIM."
                                 : "tick Debug and run again to see why.";
            string summary;
            if (legends == 0)
            {
                summary = "Nothing was drawn - " + where;
                flash_tb.Text = "That one needs a look.";
            }
            else
            {
                summary = string.Format(Inv, "{0} legend{1} and {2} row{3} at 1:{4}.",
                                        legends, legends == 1 ? "" : "s",
                                        components, components == 1 ? "" : "s", scale);
            }
            if (skipped > 0) summary += string.Format(Inv, "  {0} skipped - {1}", skipped, where);
            summary_tb.Text = summary;

            if (legends > 0 && !string.IsNullOrEmpty(firstName))
            {
                ask_tb.Text = "Open " + firstName + (legends > 1 ? ", the first of them," : "") + " now?";
                open_btn.Content = "Open legend";
                done_btn.Content = "Not now";
            }
            else
            {
                // nothing to open - one plain way out
                ask_tb.Text = "";
                open_btn.Visibility = Visibility.Collapsed;
                done_btn.Content = "Close";
                done_btn.IsDefault = true;
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

        private void OpenClicked(object sender, RoutedEventArgs args)
        {
            if (drawer.Intercept()) return;
            OpenRequested = true;
            Close();
        }

        private void Dismiss(bool fromCloseButton)
        {
            if (!fromCloseButton && drawer.Intercept()) return;
            OpenRequested = false;
            Close();
        }
    }
}
