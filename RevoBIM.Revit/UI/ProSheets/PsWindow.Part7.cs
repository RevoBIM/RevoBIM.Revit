using System;
using System.Collections.Generic;
using System.Data;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Threading;
using RevoBIM.Tools.ProSheets;
using UIApplication = Autodesk.Revit.UI.UIApplication;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsWindow
    {
        public partial class ProSheetsWindow
        {
            // ==================================================================
            // exporting
            // ==================================================================

            public bool Queue(Action<UIApplication> work)
            {
                if (Handler == null || Event == null)
                {
                    Say("The Revit event is not available; reopen the tool.");
                    return false;
                }
                Handler.Work = work;
                try
                {
                    Event.Raise();
                    return true;
                }
                catch (Exception err)
                {
                    Say("Revit would not take the job: " + err.Message);
                    return false;
                }
            }

            /// <summary>
            /// Marshal a callable onto the window's thread, then let it repaint. The
            /// export runs inside an ExternalEvent on Revit's main thread - the thread
            /// this window lives on - so nothing renders until the message pump gets
            /// a turn. Pumping afterwards is what fixes it.
            /// </summary>
            public void OnUi(Action call)
            {
                try
                {
                    Window.Dispatcher.Invoke(call);
                }
                catch (Exception)
                {
                    try
                    {
                        call();
                    }
                    catch (Exception)
                    {
                    }
                }
                Pump();
            }

            /// <summary>Let the window draw. See OnUi for why this is needed at all.</summary>
            internal void Pump()
            {
                try
                {
                    Window.Dispatcher.Invoke(DispatcherPriority.Background, new Action(() => { }));
                }
                catch (Exception)
                {
                }
            }

            public void StartExport(object sender = null, RoutedEventArgs args = null)
            {
                if (Exporting)
                    return;
                // The full Export always asks and reports, whatever an Express run
                // that never reached Revit left behind.
                ExpressRun = false;
                var (jobs, clashes) = PlanJobs();
                List<string> formats = ChosenFormats();
                if (RegisterAlone(jobs))
                {
                    StartRegisterAlone();
                    return;
                }
                if (jobs.Count == 0 || formats.Count == 0)
                {
                    Say("Tick some sheets and at least one format first.");
                    return;
                }

                // The one check that has to happen before a run rather than be
                // reported after it. A driver with no staging folder cannot produce a
                // single file.
                string blocker = PdfBlocker(formats);
                if (!string.IsNullOrEmpty(blocker))
                {
                    string choice = new PsUi.Prompt(
                        title: "Export",
                        headline: "This would not write a single PDF.",
                        message: blocker,
                        detail: "Revit's own exporter needs nothing set up, writes the exact file name asked for and " +
                                "keeps each sheet at its own size. It is also the faster of the two.",
                        primary: "Use Revit's own exporter",
                        secondary: "Open setup",
                        themeName: ThemeName, owner: Window).Show();
                    if (choice == "primary")
                    {
                        PsUi.FillCombo(C<ComboBox>("PrinterCombo"), PrinterList, selected: RevitPdf);
                        PrinterChanged(null, null);
                        Say("Switched to Revit's own exporter. Press Export again.");
                    }
                    else if (choice == "secondary")
                    {
                        OpenSetup();
                    }
                    return;
                }

                string root = TextOf("RootFolderBox");
                var (ok, error) = PsPaths.Writable(root);
                if (!ok)
                {
                    new PsUi.Prompt(
                        title: "Export", headline: "That folder cannot be written to.",
                        message: root + "\n\n" + error,
                        primary: "Close", themeName: ThemeName, owner: Window).Show();
                    return;
                }

                Dictionary<string, string> profile = CollectProfile();
                bool quiet = FlagOf("SuppressCheck");
                if (!quiet)
                {
                    string detail = ConfirmationDetail(jobs, formats, clashes);
                    int files = FileCount(jobs, formats);
                    string answer = new PsUi.Prompt(
                        title: "Export",
                        headline: string.Format(Inv, "Write {0} file{1}?", files, Plural(files)),
                        message: "Nothing has been written yet. This is exactly what will happen.",
                        detail: detail, primary: "Export", secondary: "Go back",
                        themeName: ThemeName, owner: Window).Show();
                    if (answer != "primary")
                        return;
                }
                LaunchExport(jobs, formats, profile, quiet);
            }

            /// <summary>
            /// Start a planned run on Revit's thread. Export and Express Export both
            /// end here, so the two can never drift apart.
            /// </summary>
            internal void LaunchExport(List<PsExport.Job> jobs, List<string> formats,
                                       Dictionary<string, string> profile, bool quiet)
            {
                HuntedFolder = "";
                // Decided now, from the plan: the folder names carry the time, and
                // the report comes a minute or an hour later.
                try
                {
                    IssueFolderCore = IssueFolder(jobs, formats);
                }
                catch (Exception)
                {
                    IssueFolderCore = "";
                }
                MarkPlanPending();
                PsExport.DebugReset();
                if (quiet)
                    PsExport.BeginSuppression(Uiapp);
                PsExport.Debug("RevoBIM Pro Sheets Exporter debug log");
                string chosenPrinter = PsUi.ComboText(C<ComboBox>("PrinterCombo"));
                if (string.IsNullOrEmpty(chosenPrinter))
                    chosenPrinter = RevitPdf;
                PsExport.Debug(string.Format(Inv, "{0} sheet(s), formats {1}, printer \"{2}\"",
                                             jobs.Count, string.Join("+", formats), chosenPrinter));
                if (PsExport.KnownPrinter(chosenPrinter) != null)
                {
                    PsExport.Debug("that printer is a known good driver, so a missing file is a staging folder " +
                                   "problem rather than a Save As dialog");
                }
                else if (!string.IsNullOrEmpty(PreferredPrinter) && chosenPrinter != PreferredPrinter)
                {
                    PsExport.Debug("\"" + PreferredPrinter + "\" is also installed and is set up for unattended export");
                }

                BeginProgress(FileCount(jobs, formats));
                Queue(uiapp => DoExport(uiapp, jobs, formats, profile));
            }

            // ------------------------------------------- Express Export

            /// <summary>
            /// Express Export, from the Selection tab: the ticked sheets written with
            /// the template's settings as they stand, past Format and Create, with no
            /// question asked before, during or after the run. A run that cannot
            /// happen at all says why and stops.
            /// </summary>
            public bool ExpressExport(object sender = null, RoutedEventArgs args = null)
            {
                if (Exporting)
                    return false;
                var (jobs, _) = PlanJobs();
                List<string> formats = ChosenFormats();
                bool alone = RegisterAlone(jobs);
                if (!alone && (jobs.Count == 0 || formats.Count == 0))
                {
                    Say("Express Export: tick some " + (IsViewsMode() ? "view" : "sheet") +
                        "s, and a format in the template, first.");
                    return false;
                }
                string root = TextOf("RootFolderBox");
                if (string.IsNullOrEmpty(root))
                {
                    Say("Express Export: the template has no root folder. Set one on the Create tab.");
                    return false;
                }
                var (ok, error) = PsPaths.Writable(root);
                if (!ok)
                {
                    Say("Express Export: " + root + " cannot be written to - " + error);
                    return false;
                }
                bool switched = false;
                if (!alone && !string.IsNullOrEmpty(PdfBlocker(formats)))
                {
                    PsUi.FillCombo(C<ComboBox>("PrinterCombo"), PrinterList, selected: RevitPdf);
                    PrinterChanged(null, null);
                    switched = true;
                }
                ExpressRun = true;
                if (alone)
                    StartRegisterAlone();
                else
                    LaunchExport(jobs, formats, CollectProfile(), true);
                if (switched)
                {
                    Say("Express Export: the print driver has no \"Driver saves to\" folder, so Revit's own exporter " +
                        "is writing the PDFs.");
                }
                return true;
            }

            /// <summary>
            /// The end of an Express Export: no report window. The summary goes on
            /// the status line, and the folder opens when the template says so.
            /// </summary>
            internal string ExpressFinished(PsExport.Report report)
            {
                ExpressRun = false;
                EndProgress();
                try
                {
                    string written = WriteDebugLog();
                    report.DebugPath = !string.IsNullOrEmpty(written) ? written : report.DebugPath;
                }
                catch (Exception)
                {
                }
                string text = report.Summary();
                List<PsExport.Outcome> failed = report.Failed();
                if (failed.Count > 0)
                {
                    text = text + " Not written: " +
                           string.Join(", ", failed.Take(3).Select(o => o.Label + " [" + o.Fmt + "]")) +
                           (failed.Count > 3 ? string.Format(Inv, " and {0} more", failed.Count - 3) : "");
                }
                if (report.Folders().Count > 0 && FlagOf("OpenFolderCheck", true))
                {
                    string target = FolderToOpen(report);
                    try
                    {
                        PsExport.OpenFolder(target);
                    }
                    catch (Exception)
                    {
                    }
                }
                Say(text);
                return text;
            }

            /// <summary>
            /// Export with nothing ticked and Add to export on: the register by
            /// itself, through the same run, report and Open folder as any other.
            /// </summary>
            internal void StartRegisterAlone()
            {
                string root = TextOf("RootFolderBox");
                var (ok, error) = PsPaths.Writable(root);
                if (!ok)
                {
                    new PsUi.Prompt(
                        title: "Export", headline: "That folder cannot be written to.",
                        message: root + "\n\n" + error,
                        primary: "Close", themeName: ThemeName, owner: Window).Show();
                    return;
                }
                Dictionary<string, string> profile = CollectProfile();
                HuntedFolder = "";
                try
                {
                    IssueFolderCore = RegisterFolder(new List<PsExport.Job>(), new List<string>());
                }
                catch (Exception)
                {
                    IssueFolderCore = "";
                }
                MarkPlanPending();
                PsExport.DebugReset();
                PsExport.Debug("RevoBIM Pro Sheets Exporter debug log");
                PsExport.Debug("no sheets ticked: the Document Register on its own");
                if (ExpressRun)
                    PsExport.BeginSuppression(Uiapp);
                BeginProgress(1);
                Queue(uiapp => DoExport(uiapp, new List<PsExport.Job>(), new List<string>(), profile));
            }

            /// <summary>
            /// (printer to use, the one refused, why). A template carries the printer
            /// it was saved with; a driver is a fact about a machine. This machine
            /// may prefer Revit's own exporter (the default), the driver may not be
            /// installed, or it may have no folder to collect from. Where there is no
            /// built-in exporter to fall back to, the driver is kept whatever else is
            /// true.
            /// </summary>
            public static (string Printer, string Refused, string Why) UsablePrinter(
                string wanted, string staging, IEnumerable<string> installed, bool native, bool preferNative = true)
            {
                string name = wanted ?? "";
                if (string.IsNullOrEmpty(name))
                    return ("", "", "");
                if (!native)
                    return (name, "", "");
                if (preferNative)
                    return ("", name, "prefer-native");
                var here = new HashSet<string>((installed ?? Enumerable.Empty<string>()).Select(one => one ?? ""),
                                               StringComparer.Ordinal);
                if (!here.Contains(name))
                    return ("", name, "not-installed");
                if (string.IsNullOrEmpty((staging ?? "").Trim()))
                    return ("", name, "no-folder");
                return (name, "", "");
            }

            /// <summary>
            /// Whether a PDF run cannot possibly write a file: a print driver selected
            /// with no folder to collect from. Revit's own exporter never blocks, and
            /// neither does a run with no PDF in it.
            /// </summary>
            public static bool PdfBlocked(IEnumerable<string> formats, string printer, string staging)
            {
                if (formats == null || !formats.Contains("pdf"))
                    return false;
                string name = printer ?? "";
                if (string.IsNullOrEmpty(name) || name == RevitPdf)
                    return false;
                return string.IsNullOrEmpty((staging ?? "").Trim());
            }

            /// <summary>Why a PDF run cannot produce anything, or an empty string.</summary>
            internal string PdfBlocker(IEnumerable<string> formats)
            {
                string printer = PsUi.ComboText(C<ComboBox>("PrinterCombo"));
                if (!PdfBlocked(formats, printer, TextOf("StagingBox")))
                    return "";
                return "\"" + printer + "\" is a print driver. A driver saves where it is configured to save, not to " +
                       "the path Revit asks for, so the tool collects each file from that folder and renames it - and " +
                       "\"Driver saves to\" on the Format tab is empty, so there is nothing to collect from. Every " +
                       "sheet would fail with \"no file appeared\".";
            }

            internal string ConfirmationDetail(List<PsExport.Job> jobs, List<string> formats,
                                               Dictionary<string, List<long>> clashes)
            {
                var lines = new List<string>();
                lines.Add("Formats : " + string.Join(", ", formats.Select(FormatLabel)));
                string printer = PsUi.ComboText(C<ComboBox>("PrinterCombo"));
                lines.Add("PDF via : " + (string.IsNullOrEmpty(printer) ? RevitPdf : printer));
                lines.Add("Naming  : " + PsNaming.Preview(Rules));
                lines.Add("");
                // Said before the run, not after it. A driver that asks where to save
                // turns a 200 sheet issue into 200 dialogs.
                if (formats.Contains("pdf") && !string.IsNullOrEmpty(printer) && printer != RevitPdf)
                {
                    string staging = TextOf("StagingBox");
                    if (!string.IsNullOrEmpty(staging))
                    {
                        lines.Add("Collecting from : " + staging);
                        if (PsExport.KnownPrinter(printer) != null)
                        {
                            lines.Add("\"" + printer + "\" is already set not to ask where to save, so the only thing " +
                                      "to check is that the folder above is the one it writes to.");
                        }
                        else
                        {
                            lines.Add("\"" + printer + "\" must be set to save there on its own. If it asks where to " +
                                      "save instead, nothing will be collected and every sheet will be reported as a " +
                                      "failure.");
                        }
                        if (BusyFolder(staging))
                        {
                            lines.Add("");
                            lines.Add("CAREFUL: that is a folder you use for other things. Collecting takes whatever " +
                                      "new PDF appears while the run is going, so anything else that saves a PDF there " +
                                      "in the next few minutes will be renamed and filed with your sheets. A folder of " +
                                      "its own avoids that.");
                        }
                    }
                    else
                    {
                        lines.Add("\"" + printer + "\" is a print driver, so the file names above only happen if it " +
                                  "takes the path Revit gives it. A driver set to ask where to save will prompt once " +
                                  "per sheet and nothing will land. Test on two or three sheets before a full issue, " +
                                  "or use \"" + RevitPdf + "\", which needs no driver.");
                    }
                    lines.Add("");
                }
                if (clashes != null && clashes.Count > 0)
                {
                    lines.Add("These names were repeated and had a number added:");
                    foreach (string name in clashes.Keys.OrderBy(k => k, StringComparer.Ordinal).Take(10))
                        lines.Add("   " + name);
                    lines.Add("");
                }
                foreach (PsExport.Job job in jobs.Take(200))
                {
                    bool solid = PsModel.IsThreeD(RowsByKey.TryGetValue(job.Key, out var row) ? row : null);
                    foreach (string fmt in formats)
                    {
                        if (ViewOnlyFormats.Contains(fmt) && !solid)
                            continue;
                        string folder = job.Folders.TryGetValue(fmt, out string found) ? found : "";
                        lines.Add(PsPaths.OsPathJoin(folder ?? "", job.BaseName + SuffixFor(fmt)));
                    }
                }
                if (jobs.Count > 200)
                    lines.Add(string.Format(Inv, "... and {0} more", jobs.Count - 200));
                return string.Join("\n", lines);
            }

            /// <summary>Clear last run's colours off the Create list.</summary>
            internal void MarkPlanPending()
            {
                try
                {
                    foreach (DataRow entry in CreateTable.Rows)
                        entry["state"] = "";
                }
                catch (Exception)
                {
                }
            }

            /// <summary>
            /// The colour a Create row should end up in. A failure wins over a
            /// success on the same row and is never undone.
            /// </summary>
            public static string PlanState(object was, bool good)
            {
                if (S(was) == "failed")
                    return "failed";
                return good ? "done" : "failed";
            }

            /// <summary>
            /// Colour one row of the Create list as each file lands. Called from
            /// Revit's thread as the run goes, so it is marshalled across.
            /// </summary>
            internal void MarkPlan(PsExport.Outcome outcome)
            {
                string key;
                bool good;
                try
                {
                    key = S(outcome?.Key);
                    good = outcome != null && outcome.Ok;
                }
                catch (Exception)
                {
                    return;
                }
                if (string.IsNullOrEmpty(key))
                    return;

                OnUi(() =>
                {
                    try
                    {
                        foreach (DataRow entry in CreateTable.Rows)
                        {
                            if (S(entry["key"]) != key)
                                continue;
                            string wanted = PlanState(entry["state"], good);
                            if (S(entry["state"]) != wanted)
                                entry["state"] = wanted;
                            return;
                        }
                    }
                    catch (Exception)
                    {
                    }
                });
            }

            internal void BeginProgress(int total)
            {
                Exporting = true;
                StopWanted = false;
                ExportStarted = Now();
                ExportTotal = Math.Max(1, total);
                ProgressDone = 0;
                if (C("Progress") is RangeBase bar)
                {
                    try
                    {
                        bar.Minimum = 0;
                        bar.Maximum = ExportTotal;
                        bar.Value = 0;
                    }
                    catch (Exception)
                    {
                    }
                }
                // The Create list is what turns green as the run goes, so it is the
                // tab to be on for it. Express Export stays where it was pressed.
                if (!ExpressRun)
                    SetTab(TabCreate);
                PsUi.SetText(C("ProgressText"), "0%");
                PsUi.SetVisible(C("ProgressRow"), true);
                PsUi.SetVisible(C("CancelExportButton"), true);
                foreach (string name in new[] { "ExportButton", "BackButton", "NextButton", "ExpressExportButton" })
                    SetEnabled(C(name), false);
                Say("Exporting...");
                // Draw the bar before the first sheet rather than after it.
                Pump();
            }

            internal void EndProgress()
            {
                Exporting = false;
                PsUi.SetVisible(C("ProgressRow"), false);
                PsUi.SetVisible(C("CancelExportButton"), false);
                foreach (string name in new[] { "BackButton", "NextButton", "ExpressExportButton" })
                    SetEnabled(C(name), true);
                SayStep();
                RefreshPlan();
            }

            public void StopExport(object sender = null, RoutedEventArgs args = null)
            {
                StopWanted = true;
                Say("Stopping after the file being written...");
            }

            /// <summary>Seconds as m:ss, or h:mm:ss once it is worth the extra field.</summary>
            internal static string Clock(double seconds)
            {
                int whole;
                try
                {
                    // IronPython's round() is half away from zero.
                    whole = (int)Math.Max(0, Math.Round(seconds, MidpointRounding.AwayFromZero));
                }
                catch (Exception)
                {
                    return "--";
                }
                int hours = whole / 3600;
                int rest = whole % 3600;
                int minutes = rest / 60;
                int secs = rest % 60;
                if (hours != 0)
                    return string.Format(Inv, "{0}:{1:00}:{2:00}", hours, minutes, secs);
                return string.Format(Inv, "{0}:{1:00}", minutes, secs);
            }

            /// <summary>
            /// Called from Revit's thread as each file starts. The estimate is the
            /// mean of what has actually happened so far. The count is kept here
            /// rather than taken from index, which is each exporter's own position.
            /// </summary>
            internal void Progress(int index, int total, string label, string fmt)
            {
                int done = ProgressDone;
                ProgressDone++;

                if (ProgressHook != null)
                {
                    try
                    {
                        ProgressHook(done, ExportTotal, string.Format(Inv, "{0}  {1}", fmt, label));
                    }
                    catch (Exception)
                    {
                    }
                }

                OnUi(() =>
                {
                    if (C("Progress") is RangeBase bar)
                    {
                        try
                        {
                            bar.Maximum = Math.Max(1, ExportTotal);
                            bar.Value = Math.Min(bar.Maximum, done);
                        }
                        catch (Exception)
                        {
                        }
                    }

                    double started = ExportStarted != 0 ? ExportStarted : Now();
                    double elapsed = Now() - started;
                    int percent = (int)Math.Round(100.0 * done / Math.Max(1, ExportTotal), MidpointRounding.AwayFromZero);

                    var parts = new List<string> { percent.ToString(Inv) + "%", Clock(elapsed) };
                    if (done >= 1 && elapsed > 0)
                    {
                        double each = elapsed / done;
                        double left = each * (ExportTotal - done);
                        parts.Add("~" + Clock(left) + " left");
                        try
                        {
                            DateTime finish = DateTime.Now.AddSeconds(left);
                            parts.Add("done ~" + PsModel.ToText(finish.ToString("HH:mm", Inv)));
                        }
                        catch (Exception)
                        {
                        }
                    }
                    PsUi.SetText(C("ProgressText"), string.Join("  ", parts));

                    Say(string.Format(Inv, "{0} {1} of {2} : {3}", fmt, index, total, label));
                });
            }

            internal bool ShouldStop()
            {
                return StopWanted;
            }

            /// <summary>The whole run, on Revit's API thread.</summary>
            internal void DoExport(UIApplication uiapp, List<PsExport.Job> jobs, List<string> formats,
                                   Dictionary<string, string> profile)
            {
                Stopwatch watch = Stopwatch.StartNew();
                var report = new PsExport.Report();
                report.OnAdd = MarkPlan;

                try
                {
                    if (formats.Contains("pdf"))
                    {
                        string printer = PsConfig.GetText(profile, "pdf.printer", "");
                        bool combine = PsConfig.GetBool(profile, "pdf.combine", false);
                        List<PsExport.Job> ordered = Ordered(jobs);
                        if (combine && string.IsNullOrEmpty(printer))
                        {
                            string name = CombinedName(ordered);
                            PsExport.ExportPdfCombined(Doc, ordered, profile, name, progress: Progress, report: report);
                        }
                        else if (combine && !string.IsNullOrEmpty(printer))
                        {
                            report.Note("A combined PDF is only written through Revit's own exporter, so the sheets " +
                                        "were written as separate files.");
                            PdfRun(ordered, profile, printer, report);
                        }
                        else
                        {
                            PdfRun(ordered, profile, printer, report);
                        }
                    }

                    if (formats.Contains("dwg") && !report.Cancelled)
                    {
                        PsExport.ExportDwg(Doc, jobs, profile, progress: Progress, shouldStop: ShouldStop,
                                           report: report);
                    }

                    // NWC and IFC only ever see the 3D views out of the ticked rows.
                    if (!report.Cancelled && (formats.Contains("nwc") || formats.Contains("ifc")))
                    {
                        List<PsExport.Job> solid = jobs.Where(job =>
                            PsModel.IsThreeD(RowsByKey.TryGetValue(job.Key, out var row) ? row : null)).ToList();
                        int skipped = jobs.Count - solid.Count;
                        if (skipped != 0)
                        {
                            report.Note(string.Format(Inv, "{0} of the ticked views {1} not 3D, so {2} skipped {3}.",
                                skipped,
                                skipped == 1 ? "is" : "are",
                                skipped == 1 ? "it was" : "they were",
                                string.Join(" and ", formats.Where(f => ViewOnlyFormats.Contains(f)).Select(FormatLabel))));
                        }
                        if (formats.Contains("nwc") && !report.Cancelled)
                        {
                            PsExport.ExportNwc(Doc, solid, profile, progress: Progress, shouldStop: ShouldStop,
                                               report: report);
                        }
                        if (formats.Contains("ifc") && !report.Cancelled)
                        {
                            PsExport.ExportIfc(Doc, solid, profile, progress: Progress, shouldStop: ShouldStop,
                                               report: report);
                        }
                    }
                }
                catch (Exception err)
                {
                    report.Note("The run stopped early: " + err.Message);
                }

                // The Document Register goes with the issue it describes, into the
                // folder the drawings went to - when the register tab says so.
                try
                {
                    if (!report.Cancelled && Register.AddToExport())
                        Register.ExportInto(RegisterFolder(jobs, formats), report);
                    else if (report.Cancelled && Register.AddToExport())
                        report.Note("The Document Register was not written: the run was cancelled.");
                }
                catch (Exception err)
                {
                    report.Note("The Document Register was not written: " + err.Message);
                }

                try
                {
                    watch.Stop();
                    report.Seconds = watch.ElapsedMilliseconds / 1000.0;
                }
                catch (Exception)
                {
                    report.Seconds = 0.0;
                }

                // Always turned off, even where the run threw: leaving Revit's
                // dialogs answered automatically after the tool has finished would be
                // a genuinely dangerous thing to forget.
                List<string> quieted = PsExport.EndSuppression();
                if (quieted != null && quieted.Count > 0)
                {
                    report.Note(string.Format(Inv, "{0} Revit dialog(s) were answered automatically while exporting.",
                                              quieted.Count));
                }

                report.DebugPath = WriteDebugLog();

                LastReport = report;
                OnUi(() => ShowReport(report));
            }

            internal void PdfRun(List<PsExport.Job> jobs, Dictionary<string, string> profile, string printer,
                                 PsExport.Report report)
            {
                if (!string.IsNullOrEmpty(printer))
                {
                    PsExport.ExportPdfPrinter(Doc, jobs, profile, printer, progress: Progress,
                                              shouldStop: ShouldStop, report: report);
                }
                else
                {
                    PsExport.ExportPdfNative(Doc, jobs, profile, progress: Progress,
                                             shouldStop: ShouldStop, report: report);
                }
            }

            internal List<PsExport.Job> Ordered(List<PsExport.Job> jobs)
            {
                if (CombineOrder.Count == 0)
                    return jobs;
                var position = new Dictionary<string, int>(StringComparer.Ordinal);
                for (int index = 0; index < CombineOrder.Count; index++)
                    position[CombineOrder[index]] = index;
                return jobs.OrderBy(job => position.TryGetValue(job.Key.ToString(Inv), out int at) ? at : 1000000)
                           .ToList();
            }

            internal string CombinedName(List<PsExport.Job> jobs)
            {
                string stem;
                try
                {
                    stem = PsPaths.OsPathSplitExt(PsPaths.OsPathBaseName(Doc.PathName ?? "")).Root;
                }
                catch (Exception)
                {
                    stem = "";
                }
                if (string.IsNullOrEmpty(stem))
                    stem = "Sheets";
                return PsNaming.Sanitise(string.Format(Inv, "{0} - {1} sheets", stem, jobs.Count));
            }

            /// <summary>
            /// Put the run's debug lines somewhere the user can send them on: beside
            /// the error log, overwritten each run.
            /// </summary>
            internal string WriteDebugLog()
            {
                try
                {
                    string path = PsPaths.OsPathJoin(PsExport.Dirname(PsConfig.ErrorPath()),
                                                     "pro_sheets_exporter_debug.txt");
                    File.WriteAllText(path, PsExport.DebugText() ?? "", new UTF8Encoding(false));
                    return path;
                }
                catch (Exception)
                {
                    return "";
                }
            }

            /// <summary>
            /// Where did the driver put them? Only asked when it matters. The window
            /// is the run's own duration plus a margin: a PDF saved before the export
            /// started is not evidence of anything.
            /// </summary>
            internal List<string> HuntForDriverFolder(List<PsExport.Outcome> written, List<PsExport.Outcome> failed,
                                                      PsExport.Report report = null)
            {
                if ((written != null && written.Count > 0) || failed == null || failed.Count == 0)
                    return new List<string>();
                string printer = PsUi.ComboText(C<ComboBox>("PrinterCombo"));
                if (string.IsNullOrEmpty(printer) || printer == RevitPdf)
                    return new List<string>();
                // Scanned even when a staging folder IS set: a folder that is set but
                // wrong looks exactly like a driver that is prompting.
                double window = 90.0;
                try
                {
                    if (report != null && report.Seconds != 0)
                        window = Math.Max(60.0, report.Seconds + 30.0);
                }
                catch (Exception)
                {
                    window = 90.0;
                }
                List<string> found;
                try
                {
                    found = PsExport.FindRecentPdfs(window) ?? new List<string>();
                    HuntedFolder = "";
                    string staging = TextOf("StagingBox");
                    var folders = new List<string>();
                    foreach (string path in found)
                    {
                        string folder = PsExport.Dirname(path);
                        // The staging folder itself is not news.
                        if (!string.IsNullOrEmpty(staging) && PsPaths.SameFolder(folder, staging))
                            continue;
                        if (!folders.Contains(folder))
                            folders.Add(folder);
                    }
                    if (folders.Count == 1)
                        HuntedFolder = folders[0];
                }
                catch (Exception)
                {
                    return new List<string>();
                }
                return found;
            }

            /// <summary>The debug log in its own window, ready to be copied.</summary>
            internal void ShowDebugWindow(PsExport.Report report)
            {
                string text = PsExport.DebugText();
                if (string.IsNullOrEmpty(text))
                    return;
                new PsUi.Prompt(
                    title: "Debug log",
                    headline: "What the tool asked Revit and the driver to do",
                    message: "In order, with timings. Press Copy detail to put the whole thing on the clipboard. It " +
                             "is also saved to " + (string.IsNullOrEmpty(report.DebugPath) ? "(not saved)" : report.DebugPath),
                    detail: text,
                    primary: "Close",
                    themeName: ThemeName, owner: Window).Show();
            }

            /// <summary>The line under the headline: what it means and what to do next.</summary>
            internal string ReportMessage(List<PsExport.Outcome> written, List<PsExport.Outcome> failed)
            {
                string printer = PsUi.ComboText(C<ComboBox>("PrinterCombo"));
                var driverSilent = failed.Where(o => (o.Message ?? "").Contains("no file appeared")).ToList();

                if (failed.Count > 0 && written.Count == 0 && driverSilent.Count > 0 &&
                    !string.IsNullOrEmpty(printer) && printer != RevitPdf)
                {
                    string staging = TextOf("StagingBox");
                    string hunted = HuntedFolder ?? "";
                    if (!string.IsNullOrEmpty(staging) && !string.IsNullOrEmpty(hunted))
                    {
                        return string.Format(Inv,
                            "\"{0}\" wrote its PDF to {1}, not to the folder it was told to collect from ({2}). " +
                            "\"Driver saves to\" has to be the folder the **driver** is configured to save into - it " +
                            "tells the tool where to look, it cannot tell the driver where to put things. Point it at " +
                            "{1}, or use \"{3}\", which needs no folder at all.",
                            printer, hunted, staging, RevitPdf);
                    }
                    if (!string.IsNullOrEmpty(staging))
                    {
                        return string.Format(Inv,
                            "\"{0}\" took the job and no new PDF appeared in the staging folder, or anywhere else the " +
                            "tool can see. So it is sitting on a prompt of its own - the PDF24 assistant window opens " +
                            "behind Revit and waits - or the job was dropped. Check for a window behind Revit, turn on " +
                            "automatic saving in the driver, or use \"{1}\", which needs no driver at all and is the " +
                            "faster of the two.",
                            printer, RevitPdf);
                    }
                    if (string.IsNullOrEmpty(hunted) && !HuntFoundAny)
                    {
                        return string.Format(Inv,
                            "\"{0}\" took the job, reported no error, and no PDF appeared anywhere the tool can see. So " +
                            "the driver is most likely sitting on a prompt, or its own settings are sending the job " +
                            "somewhere unusual. Check it saves automatically, then set \"Driver saves to\" to that " +
                            "folder - or use \"{1}\", which needs no driver at all.",
                            printer, RevitPdf);
                    }
                    if (!string.IsNullOrEmpty(hunted))
                    {
                        return string.Format(Inv,
                            "\"{0}\" took the job but wrote nothing to the path above. It looks like it saved to {1} " +
                            "instead - that is where PDFs have just appeared. Press \"Use that folder\" and the sheets " +
                            "will be collected from there and renamed on the next run.",
                            printer, hunted);
                    }
                    return string.Format(Inv,
                        "Revit handed the job to \"{0}\" and it was accepted, but nothing arrived at the path above. " +
                        "Some drivers cannot take a path from Revit at all - they collect the job through their own " +
                        "port and save where their own settings say. Set \"Driver saves to\" on the Format tab to that " +
                        "folder and the sheets will be collected and renamed, or use \"{1}\", which needs no driver.",
                        printer, RevitPdf);
                }
                if (failed.Count > 0 && written.Count == 0)
                    return "Nothing was written. The reason for each sheet is below.";
                if (failed.Count > 0)
                {
                    return "Every file was checked for on disk afterwards, so the count is the files that exist, not " +
                           "the calls Revit accepted. The ones that did not arrive are listed first, with the reason " +
                           "under each.";
                }
                return "Every file was checked for on disk afterwards, so this count is the files that exist, not the " +
                       "calls Revit accepted.";
            }

            internal void ShowReport(PsExport.Report report)
            {
                if (ReportHook != null)
                {
                    Exporting = false;
                    ReportHook(report);
                    return;
                }
                if (ExpressRun)
                {
                    ExpressFinished(report);
                    return;
                }
                EndProgress();
                List<PsExport.Outcome> written = report.Written();
                List<PsExport.Outcome> failed = report.Failed();

                // The failure reason goes on its own line under the sheet it belongs
                // to, rather than trailing off the end of it.
                var lines = new List<string>();
                if (failed.Count > 0)
                {
                    lines.Add("Did not write:");
                    foreach (PsExport.Outcome outcome in failed)
                    {
                        lines.Add("   " + outcome.Label + "  [" + outcome.Fmt + "]");
                        if (!string.IsNullOrEmpty(outcome.Message))
                            lines.Add("      " + outcome.Message);
                    }
                    lines.Add("");
                }
                if (report.Notes.Count > 0)
                {
                    lines.Add("Notes:");
                    foreach (string note in report.Notes)
                        lines.Add("   " + note);
                    lines.Add("");
                }
                // An empty "Written:" heading over nothing reads as a bug in the
                // report rather than as an export that wrote nothing.
                if (written.Count > 0)
                {
                    lines.Add("Written:");
                    foreach (PsExport.Outcome outcome in written)
                        lines.Add("   " + outcome.Path);
                }

                // When a driver took the job and nothing landed, go and look for
                // where it actually put the files rather than asking the user to.
                List<string> hunted = HuntForDriverFolder(written, failed, report);
                HuntFoundAny = hunted.Count > 0;
                if (hunted.Count > 0)
                {
                    lines.Add("");
                    lines.Add("PDFs written in the last few minutes:");
                    foreach (string path in hunted.Take(12))
                        lines.Add("   " + path);
                    if (hunted.Count > 12)
                        lines.Add(string.Format(Inv, "   ... and {0} more", hunted.Count - 12));
                    lines.Add("");
                    lines.Add("If those are your sheets, that folder is what \"Driver saves to\" on the Format tab wants.");
                }

                // The scan above runs after the log was first written, so write it
                // again - what the scan saw is the most useful part of it.
                string again = WriteDebugLog();
                report.DebugPath = !string.IsNullOrEmpty(again) ? again : report.DebugPath;
                if (!string.IsNullOrEmpty(report.DebugPath))
                {
                    lines.Add("");
                    lines.Add("Debug log saved to " + report.DebugPath);
                }

                List<string> folders = report.Folders();
                bool askToOpen = folders.Count > 0 && FlagOf("OpenFolderCheck", true);
                bool offerFolder = folders.Count == 0 && !string.IsNullOrEmpty(HuntedFolder);

                // When the user has asked to be offered the folder, the offer is the
                // main button. When they have not, Close is what the window is for.
                string extra = offerFolder ? "Use that folder"
                             : askToOpen ? null
                             : folders.Count > 0 ? "Open folder" : null;
                var prompt = new PsUi.Prompt(
                    title: "Export finished",
                    headline: report.Summary(),
                    message: ReportMessage(written, failed),
                    detail: string.Join("\n", lines).TrimEnd(),
                    primary: askToOpen ? "Open folder" : "Close",
                    secondary: askToOpen ? "Close" : null,
                    extra: extra,
                    themeName: ThemeName, owner: Window);

                string target = FolderToOpen(report);

                RoutedEventHandler openIt = (sender, args) => PsExport.OpenFolder(target);

                RoutedEventHandler takeFolder = (sender, args) =>
                {
                    try
                    {
                        SetTextValue(C("StagingBox"), HuntedFolder);
                        RememberStaging(PsUi.ComboText(C<ComboBox>("PrinterCombo")), HuntedFolder);
                        ((ContentControl)sender).Content = "Set";
                    }
                    catch (Exception)
                    {
                    }
                };

                if (offerFolder)
                    prompt.OnExtra(takeFolder);
                else if (folders.Count > 0 && !askToOpen)
                    prompt.OnExtra(openIt);

                string answer = prompt.Show();
                if (FlagOf("DebugCheck"))
                    ShowDebugWindow(report);
                if (askToOpen && answer == "primary")
                {
                    PsExport.OpenFolder(target);
                    Say(target + " opened.");
                    return;
                }
                Say(report.Summary());
            }

            /// <summary>
            /// The issue folder the run was planned into, where it exists. Falls back
            /// to the deepest folder written when the issue folder is not on disk.
            /// </summary>
            public string FolderToOpen(PsExport.Report report)
            {
                string planned = IssueFolderCore ?? "";
                if (!string.IsNullOrEmpty(planned) && Directory.Exists(planned))
                    return planned;
                var (deepFolder, _) = PsExport.DeepestWritten(report);
                List<string> folders = report.Folders();
                if (!string.IsNullOrEmpty(deepFolder))
                    return deepFolder;
                return folders.Count > 0 ? folders[0] : planned;
            }

            // ==================================================================
            // closing
            // ==================================================================

            public void Close()
            {
                // Revision changes staged on the Document Register and not applied.
                try
                {
                    if (!Register.CanClose())
                        return;
                }
                catch (Exception)
                {
                }
                if (Exporting)
                {
                    string answer = new PsUi.Prompt(
                        title: "Export running",
                        headline: "An export is still running.",
                        message: "Closing now stops it after the file being written.",
                        primary: "Stop and close", secondary: "Keep it open",
                        themeName: ThemeName, owner: Window).Show();
                    if (answer != "primary")
                        return;
                    StopWanted = true;
                }
                try
                {
                    if (ThemeTimer != null)
                        ThemeTimer.Stop();
                }
                catch (Exception)
                {
                }
                try
                {
                    Register.Close();
                }
                catch (Exception)
                {
                }
                try
                {
                    // The mode, not the palette. Saving the palette is what pinned the
                    // window the first time somebody touched the chip.
                    Settings.Set("theme_mode", ThemeMode);
                    RememberWindow();
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

            public void Show()
            {
                Window.Show();
            }
        }
    }
}
