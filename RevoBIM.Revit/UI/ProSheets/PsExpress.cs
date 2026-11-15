using System;
using System.Collections.Generic;
using System.Data;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;
using RevoBIM.Tools.ProSheets;
using UIApplication = Autodesk.Revit.UI.UIApplication;
using WpfWindow = System.Windows.Window;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// Express Export from the right-click menu (Revit 2025+): the sheets selected in
    /// the Project Browser, written with the last Pro Sheets template, with no
    /// question asked. A small progress strip floats at the bottom middle of the
    /// screen while it runs, and the folder opens when it is done.
    ///
    /// Built on the same route as ps_express.py's headless run: the Pro Sheets window
    /// is built hidden, which loads the last template exactly as opening the tool
    /// does, the selected sheets are ticked, and its own export runs straight away -
    /// so an Express Export and a full Export can never write different files.
    /// </summary>
    public static class PsExpress
    {
        public const string LogName = "pro_sheets_express.txt";
        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        /// <summary>Run it. Called from ExpressExportCommand, inside Revit's API context.</summary>
        public static void Run(UIApplication uiapp)
        {
            var settings = new PsConfig.Settings();
            string theme = PsTheme.Resolve(PsTheme.Mode(settings.Text("theme_mode")));
            var progress = new ExpressProgress(theme, uiapp.MainWindowHandle);
            progress.Begin("Reading the model and the last template...");
            LogReset("RevoBIM Pro Sheets Exporter - Express Export");

            // The modeless window's own export runs through an ExternalEvent, which
            // cannot overlap this command; this is for a window mid-run all the same.
            var running = PsWindow.Window;
            if (running != null && running.Exporting)
            {
                progress.Finish(false, "Pro Sheets is already exporting. Try again when it has finished.");
                return;
            }

            PsWindow.ProSheetsWindow win = null;
            try
            {
                // The first-run setup window is the one thing the constructor can put
                // on screen. Held off for the build, and always put back.
                PsWindow.ProSheetsWindow.SkipFirstRunSetup = true;
                try
                {
                    win = new PsWindow.ProSheetsWindow(uiapp);
                }
                finally
                {
                    PsWindow.ProSheetsWindow.SkipFirstRunSetup = false;
                }
                Express(uiapp, win, progress);
            }
            catch (Exception err)
            {
                Log(err.ToString());
                progress.Finish(false, "Express Export stopped: " + err.Message);
            }
            finally
            {
                CloseQuietly(win);
            }
        }

        private static void Express(UIApplication uiapp, PsWindow.ProSheetsWindow win, ExpressProgress progress)
        {
            StopTimers(win);
            ForceSheets(win);

            var keys = new HashSet<string>(
                PsModel.PreselectedRows(win.Uidoc, win.Rows).Where(row => row.IsSheet)
                       .Select(row => row.Key.ToString(Inv)),
                StringComparer.Ordinal);
            if (keys.Count == 0)
            {
                progress.Finish(false, "Select one or more sheets in the Project Browser first.");
                return;
            }
            TickExactly(win, keys);

            List<string> formats = win.ChosenFormats();
            if (formats.Count == 0)
            {
                progress.Finish(false, "The last Pro Sheets template has no format ticked. Open Pro Sheets, tick " +
                                       "PDF or DWG and save it.");
                return;
            }
            var (jobs, _) = win.PlanJobs();
            if (jobs.Count == 0)
            {
                progress.Finish(false, "Nothing to export.");
                return;
            }

            // A print driver with no "Driver saves to" folder cannot write a single
            // file. The window would ask; Express has nobody to ask, so it takes the
            // answer the window recommends.
            if (!string.IsNullOrEmpty(win.PdfBlocker(formats)))
            {
                Log("\"" + PsUi.ComboText(win.C<ComboBox>("PrinterCombo")) + "\" has no staging folder - using " +
                    "Revit's own PDF exporter");
                PsUi.FillCombo(win.C<ComboBox>("PrinterCombo"), win.PrinterList, selected: PsWindow.RevitPdf);
                win.PrinterChanged(null, null);
            }

            string root = win.TextOf("RootFolderBox");
            if (string.IsNullOrEmpty(root))
            {
                progress.Finish(false, "The last template has no root folder. Set one on the Create tab in Pro Sheets.");
                return;
            }
            var (ok, error) = PsPaths.Writable(root);
            if (!ok)
            {
                progress.Finish(false, "The export folder cannot be written to: " + root + " (" + error + ")");
                return;
            }

            Dictionary<string, string> profile = win.CollectProfile();
            int total = win.FileCount(jobs, formats);
            Log(string.Format(Inv, "{0} sheet(s), formats {1}, {2} file(s), root {3}, template \"{4}\"",
                              jobs.Count, string.Join("+", formats), total, root,
                              win.Settings.Text("last_profile")));

            win.HuntedFolder = "";
            try
            {
                win.IssueFolderCore = win.IssueFolder(jobs, formats);
            }
            catch (Exception)
            {
                win.IssueFolderCore = "";
            }

            // No report window: the report comes back here.
            var reports = new List<PsExport.Report>();
            win.ExpressRun = true;
            win.ReportHook = report => reports.Add(report);
            win.ProgressHook = (done, count, label) => progress.Update(done, count, label);
            progress.StopRequested = () => win.StopWanted = true;

            PsExport.DebugReset();
            PsExport.BeginSuppression(uiapp);
            try
            {
                win.BeginProgress(total);
                progress.Update(0, total, "Starting...");
                win.DoExport(uiapp, jobs, formats, profile);
            }
            finally
            {
                // DoExport hands suppression back itself; this is for a run that threw
                // before it got there.
                PsExport.EndSuppression();
            }

            PsExport.Report done = reports.Count > 0 ? reports[reports.Count - 1] : win.LastReport;
            if (done == null)
            {
                progress.Finish(false, "The export finished without a report.");
                return;
            }
            List<PsExport.Outcome> written = done.Written();
            List<PsExport.Outcome> failed = done.Failed();
            string summary = done.Summary();
            if (failed.Count > 0)
            {
                summary += " Not written: " +
                           string.Join(", ", failed.Take(3).Select(o => o.Label + " [" + o.Fmt + "]")) +
                           (failed.Count > 3 ? string.Format(Inv, " and {0} more", failed.Count - 3) : "") +
                           ". Details: " + (done.DebugPath ?? "");
            }
            Log(summary);

            if (written.Count > 0)
            {
                string folder = win.FolderToOpen(done);
                try
                {
                    PsExport.OpenFolder(folder);
                }
                catch (Exception err)
                {
                    Log("the folder would not open: " + err.Message);
                }
            }
            progress.Finish(written.Count > 0 && failed.Count == 0 && !done.Cancelled, summary);
        }

        // ======================================================================
        // the window, hidden
        // ======================================================================

        private static void StopTimers(PsWindow.ProSheetsWindow win)
        {
            foreach (DispatcherTimer timer in new[] { win.ThemeTimer, win.FilterTimer })
            {
                try
                {
                    timer?.Stop();
                }
                catch (Exception)
                {
                }
            }
        }

        /// <summary>A template saved in Views mode has no sheets in it.</summary>
        private static void ForceSheets(PsWindow.ProSheetsWindow win)
        {
            if (win.IsViewsMode())
            {
                try
                {
                    win.C<RadioButton>("ViewsRadio").IsChecked = false;
                    win.C<RadioButton>("SheetsRadio").IsChecked = true;
                }
                catch (Exception)
                {
                }
            }
            if (win.Rows.Any(row => !row.IsSheet))
                win.ModeChanged(null, null);
        }

        /// <summary>Exactly the sheets selected; whatever the template had ticked goes.</summary>
        private static void TickExactly(PsWindow.ProSheetsWindow win, HashSet<string> keys)
        {
            win.SuspendTicks = true;
            try
            {
                foreach (DataRow entry in win.Table.Rows)
                {
                    string key = Convert.ToString(entry["key"], Inv) ?? "";
                    if (string.IsNullOrEmpty(key))
                        continue; // a group heading
                    entry["sel"] = keys.Contains(key);
                }
            }
            finally
            {
                win.SuspendTicks = false;
            }
        }

        /// <summary>Close the hidden window without Close()'s questions.</summary>
        private static void CloseQuietly(PsWindow.ProSheetsWindow win)
        {
            if (win == null)
                return;
            StopTimers(win);
            try
            {
                win.Exporting = false;
                win.ReportHook = null;
                win.ProgressHook = null;
            }
            catch (Exception)
            {
            }
            try
            {
                win.Register.Close();
            }
            catch (Exception)
            {
            }
            try
            {
                win.Window.Close();
            }
            catch (Exception)
            {
            }
        }

        // ======================================================================
        // the log
        // ======================================================================

        private static string LogPath()
        {
            try
            {
                return Path.Combine(PsExport.Dirname(PsConfig.ErrorPath()), LogName);
            }
            catch (Exception)
            {
                return "";
            }
        }

        private static void LogReset(string text)
        {
            try
            {
                string path = LogPath();
                if (!string.IsNullOrEmpty(path) && File.Exists(path))
                    File.Delete(path);
            }
            catch (Exception)
            {
            }
            Log(text);
        }

        internal static void Log(string text)
        {
            try
            {
                string path = LogPath();
                if (string.IsNullOrEmpty(path))
                    return;
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                File.AppendAllText(path,
                                   DateTime.Now.ToString("HH:mm:ss", Inv) + "  " + text + "\n",
                                   new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }

        // ======================================================================
        // the floating progress strip
        // ======================================================================

        /// <summary>
        /// A small borderless strip at the bottom middle of the screen Revit is on.
        /// It never takes focus, and closes itself a few seconds after the run.
        /// </summary>
        internal sealed class ExpressProgress
        {
            private const double StripWidth = 440;
            private readonly WpfWindow window;
            private readonly string theme;
            private readonly IntPtr owner;
            private readonly TextBlock headline;
            private readonly TextBlock percent;
            private readonly TextBlock label;
            private readonly TextBlock count;
            private readonly TextBlock stop;
            private readonly ProgressBar bar;
            private bool finished;

            public Action StopRequested;

            public ExpressProgress(string themeName, IntPtr ownerHandle)
            {
                theme = themeName ?? "dark";
                owner = ownerHandle;

                headline = Text("Express Export", 13, "TextBrush", FontWeights.SemiBold);
                percent = Text("", 13, "TextBrush", FontWeights.SemiBold);
                percent.HorizontalAlignment = HorizontalAlignment.Right;
                var top = new DockPanel { LastChildFill = true };
                DockPanel.SetDock(percent, Dock.Right);
                top.Children.Add(percent);
                top.Children.Add(headline);

                label = Text("", 12, "MutedBrush", FontWeights.Normal);
                label.Margin = new Thickness(0, 4, 0, 8);
                label.TextTrimming = TextTrimming.CharacterEllipsis;

                bar = new ProgressBar
                {
                    Height = 6,
                    Minimum = 0,
                    Maximum = 1,
                    Value = 0,
                    BorderThickness = new Thickness(0),
                    Foreground = Brush("GreenBrush"),
                    Background = Brush("FieldBg"),
                    IsIndeterminate = true,
                };

                count = Text("", 11, "MutedBrush", FontWeights.Normal);
                stop = Text("Stop", 11, "BlueBrush", FontWeights.SemiBold);
                stop.Cursor = Cursors.Hand;
                stop.HorizontalAlignment = HorizontalAlignment.Right;
                stop.MouseLeftButtonUp += (sender, args) =>
                {
                    if (finished)
                        return;
                    stop.Text = "Stopping after this file...";
                    stop.Cursor = Cursors.Arrow;
                    try
                    {
                        StopRequested?.Invoke();
                    }
                    catch (Exception)
                    {
                    }
                };
                var bottom = new DockPanel { LastChildFill = true, Margin = new Thickness(0, 8, 0, 0) };
                DockPanel.SetDock(stop, Dock.Right);
                bottom.Children.Add(stop);
                bottom.Children.Add(count);

                var stack = new StackPanel();
                stack.Children.Add(top);
                stack.Children.Add(label);
                stack.Children.Add(bar);
                stack.Children.Add(bottom);

                var card = new Border
                {
                    Background = Brush("CardBg"),
                    BorderBrush = Brush("WindowEdgeBrush"),
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(8),
                    Padding = new Thickness(16, 12, 16, 12),
                    Margin = new Thickness(12),
                    Child = stack,
                    Effect = new System.Windows.Media.Effects.DropShadowEffect
                    {
                        BlurRadius = 14,
                        ShadowDepth = 2,
                        Opacity = 0.35,
                        Color = Colors.Black,
                    },
                };

                window = new WpfWindow
                {
                    Title = "RevoBIM Express Export",
                    WindowStyle = WindowStyle.None,
                    AllowsTransparency = true,
                    Background = Brushes.Transparent,
                    ResizeMode = ResizeMode.NoResize,
                    ShowInTaskbar = false,
                    ShowActivated = false,
                    Topmost = true,
                    Width = StripWidth + 24,
                    SizeToContent = SizeToContent.Height,
                    WindowStartupLocation = WindowStartupLocation.Manual,
                    Content = card,
                };
                // Once finished, a click puts it away before its timer does.
                window.MouseLeftButtonUp += (sender, args) =>
                {
                    if (finished)
                        Close();
                };
                try
                {
                    new WindowInteropHelper(window).Owner = owner;
                }
                catch (Exception)
                {
                }
            }

            public void Begin(string text)
            {
                label.Text = text;
                try
                {
                    window.Left = -10000;
                    window.Top = -10000;
                    window.Show();
                    window.UpdateLayout();
                    Place();
                }
                catch (Exception)
                {
                }
                Pump();
            }

            /// <summary>done files of total, and the one starting now.</summary>
            public void Update(int done, int total, string what)
            {
                if (finished)
                    return;
                total = Math.Max(1, total);
                done = Math.Max(0, Math.Min(done, total));
                bar.IsIndeterminate = false;
                bar.Maximum = total;
                bar.Value = done;
                int pct = (int)Math.Round(100.0 * done / total, MidpointRounding.AwayFromZero);
                percent.Text = pct.ToString(Inv) + "%";
                label.Text = what ?? "";
                count.Text = string.Format(Inv, "{0} of {1} file{2} written", done, total, total == 1 ? "" : "s");
                Pump();
            }

            /// <summary>The end of the run: what happened, then gone after a few seconds.</summary>
            public void Finish(bool ok, string text)
            {
                if (finished)
                    return;
                finished = true;
                bar.IsIndeterminate = false;
                bar.Maximum = 1;
                bar.Value = 1;
                bar.Foreground = Brush(ok ? "GreenBrush" : "OrangeBrush");
                headline.Text = ok ? "Express Export finished" : "Express Export";
                percent.Text = ok ? "100%" : "";
                label.Text = text ?? "";
                label.TextTrimming = TextTrimming.None;
                label.TextWrapping = TextWrapping.Wrap;
                count.Text = "Click to close";
                stop.Visibility = Visibility.Collapsed;
                try
                {
                    window.UpdateLayout();
                    Place();
                }
                catch (Exception)
                {
                }
                Pump();

                var timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(ok ? 5 : 12) };
                timer.Tick += (sender, args) =>
                {
                    timer.Stop();
                    Close();
                };
                timer.Start();
            }

            public void Close()
            {
                try
                {
                    window.Close();
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Bottom middle of the working area of the screen Revit is on.</summary>
            private void Place()
            {
                var area = PsUi.HandleArea(owner);
                double left, width, top, height;
                if (area.HasValue)
                {
                    (left, top, width, height) = area.Value;
                }
                else
                {
                    left = SystemParameters.WorkArea.Left;
                    top = SystemParameters.WorkArea.Top;
                    width = SystemParameters.WorkArea.Width;
                    height = SystemParameters.WorkArea.Height;
                }
                double tall = window.ActualHeight > 0 ? window.ActualHeight : 120;
                window.Left = left + (width - window.Width) / 2;
                window.Top = top + height - tall - 24;
            }

            /// <summary>
            /// Let the strip draw. The export runs on Revit's main thread - the one this
            /// window lives on - so nothing renders until the message pump gets a turn.
            /// </summary>
            private void Pump()
            {
                try
                {
                    window.Dispatcher.Invoke(DispatcherPriority.Background, new Action(() => { }));
                }
                catch (Exception)
                {
                }
            }

            private Brush Brush(string key)
            {
                try
                {
                    return PsTheme.Brush(PsTheme.Colour(theme, key));
                }
                catch (Exception)
                {
                    return Brushes.Gray;
                }
            }

            private TextBlock Text(string text, double size, string brush, FontWeight weight)
            {
                return new TextBlock
                {
                    Text = text,
                    FontSize = size,
                    FontWeight = weight,
                    Foreground = Brush(brush),
                    FontFamily = new FontFamily("Segoe UI"),
                };
            }
        }
    }
}
