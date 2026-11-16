using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Microsoft.Win32;
using RevoBIM.Tools.ModelCleanup;
using static RevoBIM.Tools.ModelCleanup.McuCore;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;
using Control = System.Windows.Controls.Control;
using Grid = System.Windows.Controls.Grid;
using Panel = System.Windows.Controls.Panel;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.ModelCleanup
{
    /// <summary>
    /// The Model Cleanup window. Modeless, so Revit stays usable while it is open. Nothing here touches the
    /// model directly: every button that needs Revit queues a job on the runner, Revit runs it in API context
    /// when it is free, and the job does the work - prompts included. Three big step buttons in order - Sync,
    /// Save As, Clean Up - and Clean Up stays dark until both of the first two are done. While a job runs
    /// Revit is switched off and the window's body goes deaf, all but the shrink button. Port of mcu_window.py.
    /// </summary>
    public sealed partial class McuWindow
    {
        private sealed class PublishCancelled : Exception { }

        private static readonly string[] DeafNames = { "BodyGrid", "FooterBar", "ThemeChip", "FullScreenButton", "CloseButton" };

        /// <summary>The one open window, so a second press of the ribbon button brings it back.</summary>
        private static McuWindow current;

        public static bool BringBackExisting()
        {
            McuWindow window = current;
            if (window == null) return false;
            try
            {
                if (window.BringBack()) return true;
            }
            catch (Exception) { }
            current = null;
            return false;
        }

        private readonly UIApplication uiapp;
        private readonly UIDocument uidoc;
        private readonly Document doc;
        private readonly Dictionary<string, string> settings;
        private readonly McuThemeState theme;
        private bool busy, synced, savedAs, cleaned, skipped;
        private Document targetDoc;
        private string targetPath = "";
        private bool targetIsActive;
        private string openAfter = "";
        private McuPurgeScan purgeCache;
        private string templateName = "";
        private Dictionary<string, string> template = DefaultTemplate();
        private readonly McuModelInfo info;
        private bool cancelRequested;
        private DebugReport debug = new DebugReport(false);
        private bool closeDecided, runSaved, postClose;
        private DispatcherTimer publishTimer;
        private (string Project, string Item)? publishTarget;
        private DateTime publishStarted;
        private bool closed;
        private string queuedLabel;
        private DateTime queuedAt;
        private DispatcherTimer watchdog;
        private bool revitLocked;
        private readonly IntPtr revitWindow;
        private readonly string username = "";
        private readonly List<(string, object)> environment;
        private readonly McuApiRunner runner;

        public readonly Window Window;
        private readonly McuFinder find;
        private readonly McuDrawer drawer;
        private readonly McuProgressBar progress;
        private readonly bool owned;

        public McuWindow(UIApplication uiapp)
        {
            this.uiapp = uiapp;
            uidoc = uiapp.ActiveUIDocument;
            doc = uidoc.Document;
            settings = LoadGlobal();
            theme = new McuThemeState(uiapp, settings);
            info = McuModel.Describe(doc);
            revitWindow = McuUi.RevitHandle(uiapp);
            // read now, while the command is running: outside a job the window has no business reading the model
            try { username = uiapp.Application.Username ?? ""; } catch (Exception) { }
            try { environment = McuModel.Environment(uiapp, doc); }
            catch (Exception error) { environment = new List<(string, object)> { ("environment", FormatException(error)) }; }
            // the ExternalEvent has to be made while a command is running
            runner = new McuApiRunner(OnJobFailed);

            var standard = McuUi.StandardWindow("ModelCleanup.xaml", theme, () => busy);
            Window = standard.Window;
            find = standard.Find;
            drawer = standard.Drawer;
            owned = McuUi.OwnToRevit(Window, uiapp);
            progress = new McuProgressBar(Window, find);

            WireJob("SyncButton", "Sync", OnSync);
            WireJob("SaveAsButton", "Save As", OnSaveAs);
            WireJob("CleanupButton", "Clean Up", OnCleanup);
            WireJob("ExportSettingsButton", "Export Settings", OnExportSettings);
            WireJob("ScanButton", "Count", OnScan);
            WireJob("PublishButton", "Publish", OnPublish);
            Wire("BrowseButton", OnBrowse);
            Wire("FooterCloseButton", (s, a) => Window.Close());
            Wire("SkipButton", OnSkip);
            Wire("OpenDebugButton", OnOpenDebug);
            find.Check("DebugCheck").IsChecked = AsBool(settings.Get("debug"));
            find.Check("DebugCheck").Click += McuUi.Safe(Window, OnDebugToggled, theme, "debug report");
            find.Combo("TemplateCombo").SelectionChanged += McuUi.SafeSelection(Window, OnTemplateChanged, theme, "template");
            Window.Closing += OnClosing;
            Window.Closed += OnClosed;
            Window.PreviewKeyDown += OnKey;

            FillModelCard();
            LoadTemplates(settings.Get("last_template"));
            RefreshSteps();
            Say("Model Cleanup v" + McuCore.Version + " - " + info.Title);
            if (AsBool(settings.Get("debug"))) StartDebug();
        }

        private void Wire(string name, Action<object, RoutedEventArgs> handler)
        {
            find.Button(name).Click += McuUi.Safe(Window, handler, theme, name);
        }

        /// <summary>A button whose work needs Revit: queued on the runner, run in API context when Revit is free.</summary>
        private void WireJob(string name, string label, Action<object, RoutedEventArgs> handler)
        {
            find.Button(name).Click += McuUi.Safe(Window, (sender, args) => RequestJob(label, u => handler(sender, args)), theme, name);
        }

        /// <summary>Modeless: returns at once and Revit carries on.</summary>
        public void Show()
        {
            Window.Show();
            current = this;
        }

        private bool BringBack()
        {
            if (closed) return false;
            if (drawer.Parked) drawer.Expand();
            McuUi.BringToFront(Window);
            return true;
        }

        // ============================================================
        // jobs
        // ============================================================

        private bool IsOccupied() { return busy || queuedLabel != null || runner.Running != null; }

        private bool RequestJob(string label, Action<UIApplication> work)
        {
            if (closed) return false;
            if (IsOccupied())
            {
                Say(label + " ignored - the tool is still working on " + (queuedLabel ?? runner.Running ?? "a job") + ".");
                return false;
            }
            queuedLabel = label;
            queuedAt = DateTime.Now;
            string before = find.Text("StatusText").Text;
            SetDeaf(true);
            SetStatus(WaitingNote(0));

            Action<UIApplication> job = app =>
            {
                queuedLabel = null;
                StopWatchdog();
                SetDeaf(false);
                SetStatus(before);
                if (!ModelOpen()) return;
                try
                {
                    work(app);
                }
                finally
                {
                    if (busy) EndBusy(label + " stopped - see the log", "fail");
                    LockRevit(false);
                }
            };
            var (kept, status) = runner.Request(label, job);
            if (!kept)
            {
                queuedLabel = null;
                SetDeaf(false);
                SetStatus(before);
                Tell(label, string.Format(RaiseHelp, status));
                return false;
            }
            StartWatchdog();
            return true;
        }

        private void OnJobFailed(string label, string text)
        {
            debug.Exception(label, text);
            try
            {
                var lines = text.Trim().Split('\n');
                Say(label + " failed: " + lines[lines.Length - 1].Trim());
            }
            catch (Exception) { }
            if (!closed) McuUi.ShowError(Window, label, text, theme);
        }

        /// <summary>The model this window was opened for may have been closed in Revit while the window sat open.</summary>
        private bool ModelOpen()
        {
            bool alive;
            try { alive = doc.IsValidObject; } catch (Exception) { alive = false; }
            if (alive) return true;
            Tell("Model Cleanup", "The model this window was opened for has been closed in Revit, so the window closes too.");
            closeDecided = true;
            Window.Close();
            return false;
        }

        private bool ActiveIs(UIApplication app, Document other)
        {
            try { return McuModel.SameDocument(app.ActiveUIDocument.Document, other); }
            catch (Exception) { return false; }
        }

        private void StartWatchdog()
        {
            StopWatchdog();
            var timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
            timer.Tick += McuUi.SafeTick(Window, OnWatchdog, theme, "waiting for Revit");
            watchdog = timer;
            timer.Start();
        }

        private void StopWatchdog()
        {
            if (watchdog != null)
            {
                try { watchdog.Stop(); } catch (Exception) { }
            }
            watchdog = null;
        }

        private void OnWatchdog()
        {
            if (queuedLabel == null)
            {
                StopWatchdog();
                return;
            }
            SetStatus(WaitingNote((DateTime.Now - queuedAt).TotalSeconds));
        }

        private bool CancelQueued()
        {
            string label = queuedLabel;
            if (label == null) return false;
            runner.Cancel(label);
            queuedLabel = null;
            StopWatchdog();
            SetDeaf(false);
            SetStatus(label + " cancelled before Revit picked it up.");
            Say(label + " cancelled while waiting for Revit.");
            return true;
        }

        private void SetDeaf(bool deaf)
        {
            foreach (string name in DeafNames)
            {
                try { find[name].IsHitTestVisible = !deaf; } catch (Exception) { }
            }
        }

        /// <summary>
        /// A Windows file dialog only disables its owner. Inside a job Revit is still in the middle of the
        /// job's API call, so it is switched off for as long as the dialog is up.
        /// </summary>
        private bool FileDialog(Microsoft.Win32.FileDialog dialog)
        {
            bool inJob = runner.Running != null;
            bool was = revitLocked;
            if (inJob) LockRevit(true);
            try { return dialog.ShowDialog(Window) == true; }
            finally { if (inJob && !was) LockRevit(false); }
        }

        private void LockRevit(bool locked)
        {
            if (locked == revitLocked) return;
            if (McuUi.SetRevitEnabled(revitWindow, !locked)) revitLocked = locked;
            else if (!locked) revitLocked = false;
        }

        private void SetStatus(string text) { find.Text("StatusText").Text = text ?? ""; }

        private void Say(string text)
        {
            TextBox box = find.Box("LogBox");
            box.AppendText(DateTime.Now.ToString("HH:mm:ss") + "  " + text + "\n");
            box.ScrollToEnd();
            Log(text);
        }

        private bool Ask(string title, string message, string yesLabel, string style = "GreenButton")
        {
            return McuUi.Confirm(Window, title, message, yesLabel, style, theme);
        }

        private void Tell(string title, string message) { McuUi.Tell(Window, title, message, theme); }

        private object Choose(string title, string message, params McuButton[] buttons)
        {
            return McuUi.Prompt(Window, title, message, buttons.ToList(), theme);
        }

        private void BeginBusy(string text)
        {
            busy = true;
            SetDeaf(true);
            LockRevit(true);
            SetStatus(text);
            RefreshSteps();
            progress.Begin(text);
        }

        private void EndBusy(string text, string state = "ok")
        {
            busy = false;
            SetDeaf(false);
            LockRevit(false);
            progress.Finish(text, state);
            SetStatus(text);
            RefreshSteps();
            // a sync, open or save can hand focus back to Revit - come back up
            McuUi.BringToFront(Window);
        }

        // ------------------------------------------------------------
        private void FillModelCard()
        {
            find.Text("ModelNameText").Text = info.Title.Length > 0 ? info.Title : "(untitled)";
            string path = info.Central.Length > 0 ? info.Central : info.Path.Length > 0 ? info.Path : "Not saved yet";
            find.Text("ModelPathText").Text = path;
            find.Text("ModelPathText").ToolTip = path;
            find.Text("ModelKindText").Text = info.Workshared
                ? (info.Cloud ? "Workshared, cloud model" : "Workshared model") : "Not workshared - step 1 saves it";
            find.Text("SyncTitle").Text = SyncLabel(info.Workshared);
            if (!info.Workshared)
            {
                find.Text("SyncSub").Text = "Save the model so the copy carries the latest work.";
                find["SyncCommentBox"].IsEnabled = false;
                find["RelinquishCheck"].IsEnabled = false;
            }
        }

        private void LoadTemplates(string wanted)
        {
            var names = ListTemplates();
            ComboBox combo = find.Combo("TemplateCombo");
            loadingTemplates = true;
            try
            {
                combo.Items.Clear();
                foreach (string name in names) combo.Items.Add(name);
                string chosen = PickTemplate(names, wanted);
                combo.SelectedItem = chosen;
                ApplyTemplate(chosen);
            }
            finally { loadingTemplates = false; }
        }

        private bool loadingTemplates;

        private void ApplyTemplate(string name)
        {
            templateName = name;
            template = LoadTemplate(name);
            settings["last_template"] = name;
            SaveGlobal(settings);
            find.Box("SyncCommentBox").Text = template.Get("sync_comment");
            find.Check("RelinquishCheck").IsChecked = AsBool(template.Get("relinquish"), true);
            bool preserve = template.Get("detach_mode") != DetachDiscard;
            string detach = info.Workshared ? (preserve ? "Detach and preserve worksets" : "Detach and discard worksets")
                                            : "Copy of the saved file";
            if (AsBool(template.Get("audit"))) detach += ", audit";
            if (AsBool(template.Get("compact"), true)) detach += ", compact";
            find.Text("DetachText").Text = detach;
            find.Text("TemplateSummaryText").Text = EnabledOps(template).Count + " of " + CleanupOps.Count + " clean up actions on";
            if (!savedAs) find.Box("TargetPathBox").Text = SuggestPath();
            FillPlan(null);
        }

        private string SuggestPath()
        {
            string folder = settings.Get("last_folder");
            if (folder.Length == 0 || !Directory.Exists(folder))
            {
                try
                {
                    string path = info.Path;
                    folder = path.Length > 0 && !info.Cloud ? Path.GetDirectoryName(path) ?? "" : "";
                }
                catch (Exception) { folder = ""; }
            }
            if (folder.Length == 0) folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Documents");
            string source = info.Central.Length > 0 ? info.Central : info.Path.Length > 0 ? info.Path : info.Title;
            string name = SendFileName(source, ActiveSuffix(template), AsBool(template.Get("add_date"), true),
                                       null, username.Length > 0 ? username : null);
            return Path.Combine(folder, name);
        }

        private void FillPlan(McuCounts counts)
        {
            Panel panel = find.Get<Panel>("PlanPanel");
            panel.Children.Clear();
            foreach (var op in CleanupOps)
            {
                bool on = AsBool(template.Get(op.Key));
                var row = new Grid { Margin = new Thickness(0, 2, 0, 2) };
                row.ColumnDefinitions.Add(new ColumnDefinition());
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                var name = new TextBlock { Text = op.Label, TextWrapping = TextWrapping.Wrap };
                var value = new TextBlock { Margin = new Thickness(10, 0, 0, 0) };
                int count;
                if (!on)
                {
                    name.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush");
                    value.Text = "off";
                    value.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush");
                }
                else if (counts == null || !counts.Counts.TryGetValue(op.Key, out count))
                {
                    value.Text = "on";
                    value.SetResourceReference(TextBlock.ForegroundProperty, "BlueBrush");
                }
                else
                {
                    value.Text = count.ToString();
                    value.SetResourceReference(TextBlock.ForegroundProperty, count > 0 ? "OrangeBrush" : "GreenBrush");
                }
                Grid.SetColumn(value, 1);
                row.Children.Add(name);
                row.Children.Add(value);
                panel.Children.Add(row);
            }
            var leftOut = SplitList(template.Get("purge_exclude"));
            if (leftOut.Count > 0 && AsBool(template.Get("purge")))
            {
                var note = new TextBlock { Text = leftOut.Count + " purge categories left out", Margin = new Thickness(0, 6, 0, 0) };
                note.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush");
                panel.Children.Add(note);
            }
        }

        // ------------------------------------------------------------
        private bool TargetAlive()
        {
            try { return targetDoc != null && targetDoc.IsValidObject; }
            catch (Exception) { return false; }
        }

        private void RefreshSteps()
        {
            bool alive = targetDoc != null && TargetAlive();
            var (syncedNow, savedAsNow) = EffectiveSteps(synced, savedAs, skipped);
            var states = StepStates(syncedNow, savedAsNow, cleaned, busy, alive);
            if (skipped)
            {
                states[StepSync] = false;
                states[StepSaveAs] = false;
            }
            PaintStep("Sync", states[StepSync], synced, false, skipped);
            PaintStep("SaveAs", states[StepSaveAs], savedAs, false, skipped);
            find["SkipButton"].IsEnabled = CanSkip(synced, savedAs, skipped, cleaned, busy);
            PaintStep("Cleanup", states[StepCleanup], cleaned, true);
            find["BrowseButton"].IsEnabled = !savedAs && !busy;
            find["TargetPathBox"].IsEnabled = !savedAs && !busy;
            find["TemplateCombo"].IsEnabled = !busy && !cleaned;
            find["ExportSettingsButton"].IsEnabled = !busy && !cleaned;
            find["ScanButton"].IsEnabled = !busy;
            bool publishable = info.Cloud && info.Workshared;
            find["PublishRow"].Visibility = publishable ? Visibility.Visible : Visibility.Collapsed;
            find["PublishButton"].IsEnabled = !busy && McuAps.CanPublish(info, synced) == null;
            Button close = find.Button("FooterCloseButton");
            if (cleaned && openAfter.Length > 0)
            {
                close.Content = "Close and open the cleaned copy";
                close.SetResourceReference(FrameworkElement.StyleProperty, "GreenButton");
            }
            else
            {
                close.Content = "Close";
            }
        }

        private void PaintStep(string prefix, bool enabled, bool done, bool lightsUp, bool skippedStep = false)
        {
            Button button = find.Button(prefix + "Button");
            TextBlock badge = find.Text(prefix + "Badge");
            Border number = find.Get<Border>(prefix + "Number");
            TextBlock numberText = find.Text(prefix + "NumberText");
            TextBlock title = find.Text(prefix + "Title");
            TextBlock sub = find.Text(prefix + "Sub");
            button.IsEnabled = enabled;
            badge.Text = StepBadge(enabled, done, skippedStep);
            Action<FrameworkElement, DependencyProperty, string> paint = (e, p, k) => e.SetResourceReference(p, k);
            if (skippedStep)
            {
                paint(button, Control.BackgroundProperty, "OrangeSoftBrush");
                paint(button, Control.BorderBrushProperty, "OrangeBrush");
                paint(number, Border.BackgroundProperty, "OrangeBrush");
                paint(numberText, TextBlock.ForegroundProperty, "OnAccentBrush");
                paint(badge, TextBlock.ForegroundProperty, "OrangeBrush");
                paint(title, TextBlock.ForegroundProperty, "MutedBrush");
                paint(sub, TextBlock.ForegroundProperty, "MutedBrush");
            }
            else if (done)
            {
                paint(button, Control.BackgroundProperty, "GreenSoftBrush");
                paint(button, Control.BorderBrushProperty, "GreenBrush");
                paint(number, Border.BackgroundProperty, "GreenBrush");
                paint(badge, TextBlock.ForegroundProperty, "GreenBrush");
                paint(title, TextBlock.ForegroundProperty, "TextBrush");
                paint(sub, TextBlock.ForegroundProperty, "MutedBrush");
                paint(numberText, TextBlock.ForegroundProperty, "OnAccentBrush");
            }
            else if (enabled && lightsUp)
            {
                // Clean Up illuminates only once both earlier steps are done
                paint(button, Control.BackgroundProperty, "GreenBrush");
                paint(button, Control.BorderBrushProperty, "GreenHoverBrush");
                paint(number, Border.BackgroundProperty, "OnAccentBrush");
                paint(numberText, TextBlock.ForegroundProperty, "GreenBrush");
                foreach (TextBlock block in new[] { badge, title, sub }) paint(block, TextBlock.ForegroundProperty, "OnAccentBrush");
            }
            else if (enabled)
            {
                paint(button, Control.BackgroundProperty, "BlueSoftBrush");
                paint(button, Control.BorderBrushProperty, "BlueBrush");
                paint(number, Border.BackgroundProperty, "BlueBrush");
                paint(numberText, TextBlock.ForegroundProperty, "OnAccentBrush");
                paint(badge, TextBlock.ForegroundProperty, "BlueBrush");
                paint(title, TextBlock.ForegroundProperty, "TextBrush");
                paint(sub, TextBlock.ForegroundProperty, "MutedBrush");
            }
            else
            {
                paint(button, Control.BackgroundProperty, "LockedBrush");
                paint(button, Control.BorderBrushProperty, "EdgeBrush");
                paint(number, Border.BackgroundProperty, "EdgeBrush");
                paint(numberText, TextBlock.ForegroundProperty, "MutedBrush");
                foreach (TextBlock block in new[] { badge, title, sub }) paint(block, TextBlock.ForegroundProperty, "MutedBrush");
            }
        }

        // ============================================================
        // step 1
        // ============================================================
        private void OnSync(object sender, RoutedEventArgs args)
        {
            if (busy) return;
            bool workshared = info.Workshared;
            string comment = find.Box("SyncCommentBox").Text;
            bool relinquish = find.Check("RelinquishCheck").IsChecked == true;
            BeginBusy(workshared ? "Syncing with central..." : "Saving...");
            progress.Update(0.05, workshared ? "Syncing with central (Revit is busy - the bar moves when it returns)"
                                             : "Saving (Revit is busy)");
            bool ok;
            string message;
            try
            {
                (ok, message) = McuOps.SyncCurrent(uiapp, doc, comment, relinquish, AsBool(template.Get("compact"), true));
            }
            catch (Exception error)
            {
                debug.Exception("step 1", FormatException(error));
                EndBusy("Step 1 failed - see the log", "fail");
                Say("Step 1 failed: " + FormatException(error));
                throw;
            }
            DebugStep("Step 1", new List<(string, object)>
                { ("ok", ok), ("message", message), ("comment", comment), ("relinquish", relinquish) });
            if (ok)
            {
                synced = true;
                Say(message);
                EndBusy("Step 1 done. Step 2 is ready.");
                OfferPublishAfterSync();
            }
            else
            {
                Say(message);
                EndBusy(message, "fail");
                Tell("Step 1", message);
            }
        }

        // ============================================================
        // debug report
        // ============================================================
        private void StartDebug()
        {
            if (debug.Enabled) return;
            debug = new DebugReport(true);
            debug.Section("Session");
            debug.Values(environment);
            debug.Values(new List<(string, object)>
            {
                ("Template", templateName), ("Theme mode", settings.Get("theme_mode")),
                ("APS client id set", ClientId().Length > 0), ("Owned by Revit's window", owned), ("Window", "modeless"),
            });
            debug.Flush();
            Say("Debug report: " + debug.Path);
            find["OpenDebugButton"].Visibility = Visibility.Visible;
        }

        private void DebugStep(string title, List<(string, object)> pairs)
        {
            if (!debug.Enabled) return;
            debug.Section(title);
            debug.Values(pairs);
            debug.Flush();
        }

        private void OnDebugToggled(object sender, RoutedEventArgs args)
        {
            bool on = find.Check("DebugCheck").IsChecked == true;
            settings["debug"] = BoolText(on);
            SaveGlobal(settings);
            if (on)
            {
                StartDebug();
                SetStatus("Debug report on: " + debug.Path);
            }
            else
            {
                debug.Flush();
                SetStatus("Debug report off. The report so far stays in its file.");
            }
        }

        private void OnOpenDebug(object sender, RoutedEventArgs args)
        {
            debug.Flush();
            try { Process.Start("explorer.exe", "/select,\"" + debug.Path + "\""); }
            catch (Exception)
            {
                Tell("Debug report", "The report is here:\n" + debug.Path);
                return;
            }
            SetStatus("Send this file: " + debug.Path);
        }

        // ============================================================
        // skipping steps 1 and 2
        // ============================================================
        private void OnSkip(object sender, RoutedEventArgs args)
        {
            if (IsOccupied() || !CanSkip(synced, savedAs, skipped, cleaned, busy)) return;
            var (answer, typed) = McuUi.PromptInput(Window, "Skip steps 1 and 2 - not for central models", SkipWarning(info),
                new List<McuButton> { new McuButton("Cancel", false, "BaseButton"), new McuButton("Skip steps 1 and 2", true, "RedGhostButton") },
                theme, "", "Type " + ConfirmWord);
            if (answer as bool? != true) return;
            if (!ConfirmTyped(typed))
            {
                Tell("Skip steps 1 and 2", "Nothing was skipped. The box has to read " + ConfirmWord + " exactly, in capitals.");
                return;
            }
            skipped = true;
            targetDoc = doc;
            targetIsActive = true;
            targetPath = info.Path.Length > 0 ? info.Path : info.Title;
            find.Text("CleanupTargetText").Text = "Will clean the OPEN model: " + info.Title + ". It will not be saved or synced.";
            find.Text("CleanupTargetText").SetResourceReference(TextBlock.ForegroundProperty, "RedBrush");
            DebugStep("Steps 1 and 2 skipped", new List<(string, object)>
                { ("model", info.Title), ("workshared", info.Workshared), ("central", info.Central) });
            Say("Steps 1 and 2 skipped (typed " + ConfirmWord + "). Clean Up will run on the open model " + info.Title +
                " and will not save it.");
            SetStatus("Steps 1 and 2 skipped. Clean Up runs on the open model.");
            RefreshSteps();
        }

        // ============================================================
        // step 2
        // ============================================================
        private void OnBrowse(object sender, RoutedEventArgs args)
        {
            TextBox box = find.Box("TargetPathBox");
            string currentText = box.Text;
            var dialog = new SaveFileDialog
            {
                Title = "Save the send copy as", Filter = "Revit project (*.rvt)|*.rvt", DefaultExt = ".rvt",
                AddExtension = true, OverwritePrompt = true,
            };
            if (currentText.Length > 0)
            {
                string folder = Path.GetDirectoryName(currentText);
                if (!string.IsNullOrEmpty(folder) && Directory.Exists(folder)) dialog.InitialDirectory = folder;
                dialog.FileName = Path.GetFileName(currentText);
            }
            if (FileDialog(dialog))
            {
                box.Text = dialog.FileName;
                settings["last_folder"] = Path.GetDirectoryName(dialog.FileName) ?? "";
                SaveGlobal(settings);
            }
        }

        private List<string> ProtectedPaths()
        {
            var paths = new List<string> { info.Path };
            if (info.Central.Length > 0 && !info.Cloud) paths.Add(info.Central);
            return paths;
        }

        private void OnSaveAs(object sender, RoutedEventArgs args)
        {
            if (busy || !synced) return;
            string target = find.Box("TargetPathBox").Text.Trim();
            string problem = CheckTargetPath(target, ProtectedPaths());
            if (problem != null)
            {
                Tell("Save As", problem);
                return;
            }
            string route = SaveAsRoute(info);
            string message = SaveAsConfirmation(info, target, template.Get("detach_mode"));
            if (McuOps.TargetExists(target)) message += "\n\nA file with that name already exists and will be replaced.";
            if (!Ask("Save As Detached Copy", message, "Save the detached copy")) return;
            Document copy = null;
            if (route == RouteSaveOpen)
            {
                BeginBusy("Saving the open ACC model as the detached copy...");
                try
                {
                    progress.Update(0.1, "Saving the open model as the detached copy (Revit is busy)");
                    McuOps.SaveActiveAsCopy(uiapp, doc, target, template);
                }
                catch (Exception error)
                {
                    debug.Exception("step 2 (save the open model)", FormatException(error));
                    EndBusy("Save As failed - see the log", "fail");
                    throw;
                }
                targetIsActive = true;
                copy = doc;
            }
            else
            {
                BeginBusy("Opening a detached copy and saving it...");
                try
                {
                    progress.Update(0.05, "Opening the central detached (Revit is busy)");
                    copy = McuOps.OpenDetachedCopy(uiapp, doc, target, template, (label, fraction) => progress.Update(fraction, label));
                }
                catch (McuSaveAsFailed error)
                {
                    // it opened; it was the save that failed, and saving the live model to the same place would fail too
                    debug.Exception("step 2 (saving the detached copy)", FormatException(error));
                    EndBusy("The detached copy could not be saved", "fail");
                    Tell("Save As Detached Copy", "Revit opened the detached copy but could not save it to\n" + target + "\n\n" +
                         error.Message + "\n\nCheck the folder exists and is writable and the file is not open elsewhere, " +
                         "then try again. The copy has been closed.");
                    return;
                }
                catch (Exception error)
                {
                    string detail = FormatException(error);
                    debug.Exception("step 2 (detached copy)", detail);
                    Say("Detached copy failed: " + error.Message);
                    Log(detail);
                }
                if (copy == null)
                {
                    EndBusy("Revit would not open a detached copy", "fail");
                    copy = OfferFallback(target);
                    if (copy == null) return;
                    BeginBusy("Saving the open model as the detached copy...");
                }
            }
            targetDoc = copy;
            targetPath = target;
            savedAs = true;
            settings["last_folder"] = Path.GetDirectoryName(target) ?? "";
            SaveGlobal(settings);
            find.Text("CleanupTargetText").Text = "Will clean the detached copy: " + target;
            find.Text("SaveAsSub").Text = "The detached copy is saved. Everything from here works on it.";
            Say("Detached copy saved: " + target);
            DebugStep("Step 2", new List<(string, object)>
                { ("target", target), ("route", route), ("working in the open model", targetIsActive), ("detach", template.Get("detach_mode")) });
            EndBusy("Step 2 done. Clean Up is ready.");
        }

        private Document OfferFallback(string target)
        {
            if (!info.Workshared)
            {
                Tell("Save As", "Revit would not open the copied file. The log has the reason.");
                return null;
            }
            if (template.Get("detach_mode") == DetachDiscard)
            {
                Tell("Save As", "Revit would not open the central a second time, and discarding worksets needs that. " +
                                "Close other copies of this model and try again, or switch the template to preserve worksets.");
                return null;
            }
            string message = "Revit would not open the central a second time.\n\nThe open model can be saved as the detached " +
                             "copy instead. It has just been synced, so nothing is lost. The saved file is the detached " +
                             "model, and this session will then be working in it, not the live model.\n\nSave the open model as\n" +
                             target + "?";
            if (!Ask("Save As Detached Copy", message, "Save the open model as the copy", "OrangeButton")) return null;
            BeginBusy("Saving the open model as the send copy...");
            try
            {
                progress.Update(0.1, "Saving the open model as the copy (Revit is busy)");
                McuOps.SaveActiveAsCopy(uiapp, doc, target, template);
            }
            catch (Exception)
            {
                EndBusy("Save As failed - see the log", "fail");
                throw;
            }
            targetIsActive = true;
            busy = false;
            return doc;
        }

        // ============================================================
        // step 3
        // ============================================================
        private void OnCleanup(object sender, RoutedEventArgs args)
        {
            if (busy || !((synced && savedAs) || skipped) || cleaned) return;
            if (targetDoc == null || !TargetAlive())
            {
                Tell("Clean Up", "The saved copy is no longer open. Run step 2 again.");
                return;
            }
            if (targetIsActive && !ActiveIs(uiapp, targetDoc))
            {
                Tell("Clean Up", "Switch Revit back to " + info.Title + " - the model this clean up runs in - then press Clean Up again.");
                return;
            }
            var warnings = RetentionWarnings(template);
            if (warnings.Count > 0)
            {
                object answer = Choose("Clean Up - retained views and sheets",
                    RetentionMessage(template, warnings) + "\n\nTurn the missing delete stages on for this template?",
                    new McuButton("Cancel", null, "BaseButton"), new McuButton("Run as it is", false, "OrangeButton"),
                    new McuButton("Turn them on and run", true, "GreenButton"));
                if (answer == null) return;
                if (answer as bool? == true)
                {
                    template = FixRetention(template, warnings);
                    SaveTemplate(templateName, template);
                    FillPlan(null);
                    Say("Turned on: " + RetentionMessage(template, warnings));
                }
                DebugStep("Retention warning", new List<(string, object)> { ("warnings", string.Join(", ", warnings)), ("answer", answer) });
            }
            bool nwcOn = AsBool(template.Get("export_nwc"));
            if (nwcOn)
            {
                var nwcProblems = McuNwc.Problems(template, McuModel.NwcAvailable());
                if (nwcProblems.Count > 0)
                {
                    object answer = Choose("Clean Up - NWC export", string.Join("\n", nwcProblems) + "\n\nClean up without exporting NWC?",
                        new McuButton("Cancel", null, "BaseButton"), new McuButton("Clean up without NWC", true, "OrangeButton"));
                    if (answer as bool? != true) return;
                    nwcOn = false;
                }
            }
            var opsOn = EnabledOps(template).Where(op => op.Key != "export_nwc" || nwcOn).ToList();
            if (opsOn.Count == 0)
            {
                Tell("Clean Up", "The template has every clean up action switched off.");
                return;
            }
            string nwcFolder = "", nwcStem = "";
            if (nwcOn)
            {
                (nwcFolder, nwcStem) = NwcDestination();
                if (nwcFolder.Length == 0) return;
            }
            long activeId = 0;
            UIDocument activeUi = null;
            if (targetIsActive)
            {
                activeUi = uiapp.ActiveUIDocument;
                try { activeId = McuModel.Eid(activeUi.ActiveView.Id); } catch (Exception) { activeId = 0; }
            }
            McuCounts counts;
            try { counts = McuModel.PlanCounts(targetDoc, template, 0); }
            catch (Exception error)
            {
                counts = new McuCounts();
                debug.Exception("counting before Clean Up", FormatException(error));
            }
            var lines = new List<string>();
            foreach (var op in opsOn)
            {
                if (op.Key == "export_nwc")
                {
                    var (views, primary) = McuNwc.Selection(template);
                    lines.Add("  - Export NWC first, to " + nwcFolder + ":");
                    lines.AddRange(McuNwc.FileNames(nwcStem, views, primary)
                        .Select(n => "      " + n.File + ".nwc   (" + n.View + (n.View == primary ? ", primary" : "") + ")"));
                    continue;
                }
                int count;
                if (op.Key == "purge") lines.Add("  - " + op.Label + ": up to " + AsInt(template.Get("purge_passes"), 4, 1, 10) + " passes");
                else if (counts.Counts.TryGetValue(op.Key, out count)) lines.Add("  - " + op.Label + ": " + count);
                else lines.Add("  - " + op.Label);
            }
            if (counts.Kept.Count > 0)
            {
                lines.Add("");
                lines.Add("Staying:");
                lines.AddRange(counts.Kept.Select(k => "  - " + k));
            }
            string joined = string.Join("\n", lines);
            string text = skipped
                ? "Steps 1 and 2 were skipped. This runs on the OPEN model:\n" + info.Title + "\n\n" + joined +
                  "\n\nIf the open view is going, a retained one is opened first and the old one closed.\n" +
                  "It will not be saved or synced. Never a central model."
                : "This runs on the saved copy only:\n" + targetPath + "\n\n" + joined + "\n\nThe live model is not touched.";
            DebugStep("Clean Up asked", new List<(string, object)>
                { ("counts", string.Join(", ", counts.Counts.Select(p => p.Key + "=" + p.Value))) });
            if (!Ask("Clean Up", text, "Clean Up")) return;
            BeginBusy("Cleaning...");
            var runTemplate = new Dictionary<string, string>(template);
            runTemplate["export_nwc"] = BoolText(nwcOn);
            if (nwcOn && !ExportNwcPhase(runTemplate, nwcFolder, nwcStem)) return;
            McuRunReport report;
            try
            {
                report = McuOps.RunCleanup(uiapp, targetDoc, runTemplate, activeId, (label, fraction) => progress.Update(fraction, label),
                                           !skipped, activeUi, debug);
            }
            catch (Exception error)
            {
                debug.Exception("Clean Up", FormatException(error));
                EndBusy(!TargetModified() ? "Clean Up failed - nothing was removed" : "Clean Up failed part way - see the log before saving", "fail");
                Say("Clean Up failed: " + error.Message);
                throw;
            }
            foreach (string line in report.Lines) Say(line);
            cleaned = true;
            runSaved = report.Saved;
            if (AsBool(template.Get("open_when_done"), true) && !targetIsActive) openAfter = targetPath;
            string result = report.Total() + " elements removed";
            if (report.KeptCount() > 0) result += ", " + report.KeptCount() + " views kept because a view that stays depends on them";
            if (report.RefusedCount() > 0)
            {
                result += ", " + report.RefusedCount() + " refused (listed in the log)";
                find.Text("CleanupResultText").SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush");
            }
            else
            {
                find.Text("CleanupResultText").SetResourceReference(TextBlock.ForegroundProperty, "GreenBrush");
            }
            find.Text("CleanupResultText").Text = result;
            if (debug.Enabled) result += ". Debug report written";
            EndBusy("Clean Up done. " + result + ".", report.RefusedCount() > 0 ? "warn" : "ok");
        }

        /// <summary>(folder, model name) for the NWC files: the detached copy's folder. An ACC or never-saved model has no folder, so ask for one.</summary>
        private (string Folder, string Stem) NwcDestination()
        {
            string path = !skipped ? targetPath : info.Path;
            string folder = FolderOf(path);
            string stem = ModelStem(path.Length > 0 ? path : info.Title);
            if (folder.Length > 0 && Directory.Exists(folder)) return (folder, stem);
            var (views, primary) = McuNwc.Selection(template);
            var dialog = new SaveFileDialog
            {
                Title = "Where should the NWC files go? (name of the primary file)", Filter = "Navisworks cache (*.nwc)|*.nwc",
                DefaultExt = ".nwc",
                FileName = views.Count > 0 ? McuNwc.FileNames(stem, views, primary)[0].File + ".nwc" : stem + ".nwc",
            };
            if (!FileDialog(dialog)) return ("", "");
            return (Path.GetDirectoryName(dialog.FileName) ?? "", ModelStem(dialog.FileName));
        }

        /// <summary>The NWC export, before anything is removed. False stops Clean Up.</summary>
        private bool ExportNwcPhase(Dictionary<string, string> runTemplate, string folder, string stem)
        {
            bool save = !skipped;
            var keys = EnabledOps(runTemplate).Select(o => o.Key).Concat(save ? new[] { "save" } : new string[0]);
            var plan = StagePlan(keys);
            Action<double, string> report = (local, label) => progress.Update(PlanFraction(plan, "export_nwc", local), label);
            List<(string View, string Path)> written;
            List<(string View, string Reason)> failures;
            try
            {
                (written, failures) = McuOps.ExportNwc(uiapp, targetDoc, runTemplate, folder, stem, report, debug);
            }
            catch (Exception error)
            {
                debug.Exception("NWC export", FormatException(error));
                EndBusy("NWC export failed - nothing was removed", "fail");
                throw;
            }
            foreach (var item in written) Say("NWC written: " + item.Path + "  (" + item.View + ")");
            foreach (var item in failures) Say("NWC not written for " + item.View + ": " + item.Reason);
            if (failures.Count == 0) return true;
            object answer = Choose("NWC export",
                written.Count + " of " + (written.Count + failures.Count) + " NWC file(s) were written.\n\nNot written:\n" +
                string.Join("\n", failures.Select(f => "  - " + f.View + ": " + f.Reason)) + "\n\nCarry on with the clean up?",
                new McuButton("Stop here", false, "BaseButton"), new McuButton("Carry on", true, "OrangeButton"));
            if (answer as bool? != true)
            {
                EndBusy("Stopped after the NWC export - nothing was removed", "warn");
                return false;
            }
            return true;
        }

        private bool TargetModified()
        {
            try { return targetDoc.IsModified; }
            catch (Exception) { return true; }
        }

        // ============================================================
        // template, settings, scan
        // ============================================================
        private void OnTemplateChanged(object sender, SelectionChangedEventArgs args)
        {
            if (loadingTemplates) return;
            object chosen = find.Combo("TemplateCombo").SelectedItem;
            if (chosen == null || chosen.ToString() == templateName) return;
            ApplyTemplate(chosen.ToString());
            SetStatus("Template: " + chosen);
        }

        private void OnExportSettings(object sender, RoutedEventArgs args) { OpenSettings(); }

        /// <summary>Modal to this window and run inside a job, so everything the dialog reads from the model is read in API context.</summary>
        private void OpenSettings()
        {
            var dialog = new McuSettingsWindow(this, templateName);
            string saved = dialog.Show();
            if (dialog.PurgeCache != null) purgeCache = dialog.PurgeCache;
            LoadTemplates(string.IsNullOrEmpty(saved) ? templateName : saved);
        }

        private void OnScan(object sender, RoutedEventArgs args)
        {
            BeginBusy("Counting in the live model...");
            McuCounts counts;
            try
            {
                if (purgeCache == null)
                {
                    progress.Update(0.1, "Asking Revit what is unused (Revit is busy)");
                    purgeCache = McuModel.ScanPurge(doc, true);
                }
                progress.Update(0.7, "Counting views, links, templates and filters");
                long activeId = 0;
                if (ActiveIs(uiapp, doc))
                {
                    try { activeId = McuModel.Eid(uiapp.ActiveUIDocument.ActiveView.Id); } catch (Exception) { activeId = 0; }
                }
                counts = McuModel.PlanCounts(doc, template, activeId, purgeCache.Unused);
            }
            catch (Exception)
            {
                EndBusy("Count failed", "fail");
                throw;
            }
            FillPlan(counts);
            EndBusy("Counts are from the live model; the copy is recounted when it runs.");
        }

        // ============================================================
        // closing after a clean up: save, close, show the folder
        // ============================================================
        private void FinishAndClose(UIApplication app)
        {
            try { FinishAndCloseCore(); }
            catch (Exception error)
            {
                string text = FormatException(error);
                debug.Exception("save and close", text);
                if (busy) EndBusy("Save and close failed", "fail");
                McuUi.ShowError(Window, "Save and close", text, theme);
            }
        }

        private void FinishAndCloseCore()
        {
            bool openModel = targetIsActive;
            string keepLabel, text;
            if (openModel)
            {
                keepLabel = "Close window, leave the model open";
                text = "The clean up is done in the open model, which has NOT been saved.\n\nSave and close saves it compact, " +
                       "relinquishes every workset, shows you its folder and closes the model.";
            }
            else
            {
                keepLabel = AsBool(template.Get("open_when_done"), true) ? "Close window and open the copy" : "Close window";
                text = "The cleaned copy is saved:\n" + targetPath + "\n\nSave and close saves it compact once more, relinquishes " +
                       "every workset, shows you its folder and closes it.";
            }
            object choice = Choose("Save and close the model", text, new McuButton("Cancel", null, "BaseButton"),
                                   new McuButton(keepLabel, "keep", "OrangeButton"), new McuButton("Save and close", "save", "GreenButton"));
            DebugStep("Close asked", new List<(string, object)> { ("choice", choice), ("open model", openModel) });
            if (choice == null) return;
            if ((string)choice == "save")
            {
                if (!SaveAndCloseModel()) return;
                openAfter = "";
            }
            closeDecided = true;
            Window.Close();
        }

        /// <summary>True when saved (and closed or queued to close).</summary>
        private bool SaveAndCloseModel()
        {
            Document model = targetDoc;
            if (model == null || !TargetAlive())
            {
                Tell("Save and close", "The cleaned model is no longer open.");
                return false;
            }
            McuModelInfo modelInfo = McuModel.Describe(model);
            string route = SaveRoute(modelInfo);
            const string comment = "Model Cleanup - cleaned, compacted and relinquished";
            bool unchanged = false;
            try { unchanged = runSaved && !model.IsModified; } catch (Exception) { }
            if (unchanged && (route == SaveSync || route == SavePlain)) route = SaveNone;
            if (route == McuCore.SaveAs)
            {
                string target = AskNewPath(modelInfo);
                if (target.Length == 0) return false;
                BeginBusy("Saving the model for the first time");
                progress.Update(0.2, "Save As, compact (Revit is busy)");
                try { McuOps.SaveNewFile(uiapp, model, target); }
                catch (Exception)
                {
                    EndBusy("Save As failed", "fail");
                    throw;
                }
                EndBusy("Saved as " + target);
                modelInfo = McuModel.Describe(model);
                route = SaveRoute(modelInfo);
            }
            if (route == SaveLocal)
            {
                object choice = Choose("Save and close - local file", LocalSaveMessage(modelInfo),
                    new McuButton("Cancel", null, "BaseButton"), new McuButton("Sync and relinquish", "sync", "RedGhostButton"),
                    new McuButton("Save local only", "local", "GreenButton"));
                if (choice == null) return false;
                if ((string)choice == "sync")
                {
                    var (answer, typed) = McuUi.PromptInput(Window, "Sync the clean up to the central",
                        "This sends every deletion and the purge to\n" + (modelInfo.Central.Length > 0 ? modelInfo.Central : "the central model") +
                        "\n\nType " + ConfirmWord + " to sync.",
                        new List<McuButton> { new McuButton("Cancel", false, "BaseButton"), new McuButton("Sync", true, "RedGhostButton") },
                        theme, "", "Type " + ConfirmWord);
                    if (answer as bool? != true || !ConfirmTyped(typed))
                    {
                        SetStatus("Not synced.");
                        return false;
                    }
                    route = SaveSync;
                }
            }
            BeginBusy("Saving and closing");
            string stageText;
            switch (route)
            {
                case SaveNone: stageText = "Already saved by Clean Up - closing"; break;
                case SaveSync: stageText = "Syncing compact and relinquishing (Revit is busy)"; break;
                case SavePlain: stageText = "Saving compact (Revit is busy)"; break;
                case SaveLocal: stageText = "Saving the local file compact (Revit is busy)"; break;
                default: stageText = "Saving"; break;
            }
            progress.Update(0.1, stageText);
            string message;
            try
            {
                if (route == SaveNone)
                {
                    message = "Already saved compact and relinquished by Clean Up, and nothing has changed since - no second sync needed.";
                    route = modelInfo.Workshared ? SaveSync : SavePlain;
                }
                else
                {
                    message = McuOps.SaveModel(uiapp, model, route, comment, debug);
                }
            }
            catch (Exception)
            {
                EndBusy("Saving failed - the model is still open", "fail");
                throw;
            }
            Say(message);
            string path = route == SaveSync && modelInfo.Central.Length > 0 ? modelInfo.Central : modelInfo.Path;
            progress.Update(0.8, "Closing the model");
            string closedText;
            if (targetIsActive)
            {
                // Revit will not let an add-in close the model in front of it; its own Close command is posted as the window closes
                postClose = true;
                closedText = "The model closes as soon as this window does.";
            }
            else
            {
                McuOps.CloseDocument(model, false);
                targetDoc = null;
                closedText = "The model is closed.";
            }
            EndBusy(message);
            DebugStep("Saved and closed", new List<(string, object)>
                { ("route", route), ("path", path), ("closes after the window", postClose) });
            string folder = FolderOf(path);
            if (folder.Length == 0)
            {
                Tell("Saved", message + "\n\n" + closedText + "\n\nThis model lives on ACC, so there is no folder to open.");
                return true;
            }
            object open = Choose("Saved", message + "\n\n" + closedText + "\n\nOpen the folder?\n" + folder,
                                 new McuButton("No", false, "BaseButton"), new McuButton("Open folder", true, "GreenButton"));
            if (open as bool? == true) ShowInFolder(path);
            return true;
        }

        private string AskNewPath(McuModelInfo modelInfo)
        {
            var dialog = new SaveFileDialog
            {
                Title = "Save the cleaned model as", Filter = "Revit project (*.rvt)|*.rvt", DefaultExt = ".rvt", AddExtension = true,
                FileName = SendFileName(modelInfo.Title.Length > 0 ? modelInfo.Title : "Model", ActiveSuffix(template), false),
            };
            string folder = settings.Get("last_folder");
            if (folder.Length > 0 && Directory.Exists(folder)) dialog.InitialDirectory = folder;
            return FileDialog(dialog) ? dialog.FileName : "";
        }

        private void ShowInFolder(string path)
        {
            try
            {
                if (File.Exists(path)) Process.Start("explorer.exe", "/select,\"" + path + "\"");
                else Process.Start("explorer.exe", "\"" + FolderOf(path) + "\"");
                SetStatus("Opened " + FolderOf(path));
            }
            catch (Exception) { Tell("Folder", "The model is in:\n" + FolderOf(path)); }
        }

        // ============================================================
        // closing
        // ============================================================
        private void OnKey(object sender, KeyEventArgs args)
        {
            try
            {
                if (args.Handled) return;
                bool escape = args.Key == Key.Escape;
                if (queuedLabel != null)
                {
                    if (escape) CancelQueued();
                    args.Handled = true;
                    return;
                }
                if (busy)
                {
                    // keys could otherwise press a focused button mid-job
                    if (escape)
                    {
                        cancelRequested = true;
                        SetStatus("Cancelling...");
                    }
                    args.Handled = true;
                    return;
                }
                if (escape)
                {
                    args.Handled = true;
                    Window.Close();
                }
            }
            catch (Exception) { }
        }

        private void OnClosing(object sender, CancelEventArgs args)
        {
            // a job may close the window itself (Save and close, or the model having gone) - it says so with closeDecided
            if (busy || queuedLabel != null || (runner.Running != null && !closeDecided))
            {
                args.Cancel = true;
                return;
            }
            if (cleaned && !closeDecided)
            {
                args.Cancel = true;
                RequestJob("Save and close", FinishAndClose);
                return;
            }
            StopPublishPoll();
            StopWatchdog();
            if (!cleaned) openAfter = "";
            if (NeedsAfterClose())
            {
                var (kept, status) = runner.Request("Closing", AfterClose);
                if (!kept) Log("closing job refused (" + status + "); the copy stays open");
            }
            debug.Section("Window closed");
            debug.Flush();
        }

        private void OnClosed(object sender, EventArgs args)
        {
            closed = true;
            LockRevit(false);
            if (ReferenceEquals(current, this)) current = null;
        }

        private bool NeedsAfterClose()
        {
            bool background = targetDoc != null && !targetIsActive && TargetAlive();
            return background || postClose || openAfter.Length > 0;
        }

        /// <summary>Runs once the window has gone: closes the background copy, closes the cleaned open model, or opens the cleaned copy.</summary>
        private void AfterClose(UIApplication app)
        {
            Document model = targetDoc;
            bool alive = model != null && TargetAlive();
            if (alive && !targetIsActive && !postClose) McuOps.CloseDocument(model, false);
            if (postClose && alive)
            {
                if (ActiveIs(app, model))
                {
                    if (!McuOps.PostCloseActive(app)) Log("could not post Revit's Close command");
                }
                else
                {
                    // not the model in front: an add-in may close it directly, and it has just been saved
                    McuOps.CloseDocument(model, false);
                }
            }
            else if (openAfter.Length > 0)
            {
                Log("opening " + openAfter);
                try { app.OpenAndActivateDocument(openAfter); }
                catch (Exception error) { WriteError("opening the cleaned copy", FormatException(error)); }
            }
        }

        // ============================================================
        // what the settings window needs from this one
        // ============================================================
        public UIApplication UiApp { get { return uiapp; } }
        public Document Doc { get { return doc; } }
        public Window Frame { get { return Window; } }
        public McuThemeState Theme { get { return theme; } }
        public Dictionary<string, string> Settings { get { return settings; } }
        public McuPurgeScan PurgeCache { get { return purgeCache; } }
        public bool FileDialogShow(Microsoft.Win32.FileDialog dialog, Window parent) { return dialog.ShowDialog(parent) == true; }
    }
}

