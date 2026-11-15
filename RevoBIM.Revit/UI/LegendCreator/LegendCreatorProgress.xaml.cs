using System;
using System.Windows;
using System.Windows.Threading;
using RevoBIM.Tools.LegendCreator;
using static RevoBIM.Tools.LegendCreator.LgcCore;
using static RevoBIM.Tools.LegendCreator.LgcLogic;

namespace RevoBIM.UI.LegendCreator
{
    /// <summary>
    /// "Legend n of m" with Cancel, shown modeless while the build runs on
    /// Revit's thread. Each update pumps the dispatcher so the bar repaints and
    /// a Cancel click is seen. Stands in for pyRevit's forms.ProgressBar.
    /// </summary>
    public partial class LegendCreatorProgress : Window, ILegendProgress
    {
        public bool Cancelled { get; private set; }

        public LegendCreatorProgress(string themeName)
        {
            InitializeComponent();
            LgcTheme.ApplyPalette(this, themeName);
            cancel_btn.Click += (s, e) =>
            {
                Cancelled = true;
                cancel_btn.IsEnabled = false;
                cancel_btn.Content = "Stopping";
                Log("progress: cancel pressed");
            };
        }

        public void ShowOverRevit()
        {
            try
            {
                if (LgcTheme.OwnerHandle != IntPtr.Zero)
                    new System.Windows.Interop.WindowInteropHelper(this).Owner = LgcTheme.OwnerHandle;
                Show();
                Pump();
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        public void Update(int value, int max)
        {
            try
            {
                title_tb.Text = string.Format(Inv, "Legend {0} of {1}", value, max);
                double fraction = max > 0 ? (double)value / max : 1.0;
                fill_bar.Width = Math.Max(0.0, track.ActualWidth * fraction);
                Pump();
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        /// <summary>Let WPF repaint and take input once, then return to the build.</summary>
        private static void Pump()
        {
            var frame = new DispatcherFrame();
            Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.Background,
                new Action(() => frame.Continue = false));
            Dispatcher.PushFrame(frame);
        }
    }
}
