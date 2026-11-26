using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using Autodesk.Revit.UI;
using RevoBIM.Tools.FamilyThumbnail;

using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using Grid = System.Windows.Controls.Grid;
using TextBox = System.Windows.Controls.TextBox;
using VerticalAlignment = System.Windows.VerticalAlignment;

namespace RevoBIM.UI.FamilyThumbnail
{
    /// <summary>
    /// The Update Batch window: tick the families, press Start Update, and each ticked family is opened, given its thumbnail,
    /// saved and loaded back into the project. Runs modal inside the command, so every Revit call is in API context. One family
    /// per timer tick, with a tick in between so the window paints "Working..." before Revit gets busy. Port of BatchWindow in ft_ui.py.
    /// </summary>
    internal sealed class FtBatchWindow : FtChromeWindow
    {
        private const int TickMs = 40;

        private sealed class Row
        {
            public FtEntry Entry;
            public Border Border;
            public TextBlock[] Texts;
            public CheckBox Check;
        }

        private readonly UIDocument uidoc;
        private readonly Autodesk.Revit.DB.Document doc;
        private readonly List<Row> rows = new List<Row>();
        private List<Row> queue = new List<Row>();
        private FtSettings settings;
        private readonly Action<Window> openSettings;
        private readonly DispatcherTimer timer;
        private readonly List<FtEntry> entries;
        private int index;
        private int phase;
        private int done;
        private int failed;
        private bool running;
        private bool finished;
        private bool cancel;
        private readonly List<string> failures = new List<string>();
        private readonly bool hasPreselected;
        private bool selectedOnly;

        private FtBatchWindow(UIApplication uiapp, UIDocument uidoc, List<FtEntry> entries, IList<string> notes, FtSettings settings,
            Action<Window> openSettings)
            : base(uiapp, "BatchWindow.xaml", settings.ThemeMode, true)
        {
            this.uidoc = uidoc;
            doc = uidoc.Document;
            this.entries = entries;
            this.settings = settings;
            this.openSettings = openSettings;
            timer =new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(TickMs) };
            timer.Tick += OnTick;

            Get<Button>("btnSettings").Click += (a, b) => OnSettings();
            ShowOptions();
            Get<TextBlock>("tbSkipped").Text = string.Join("  ", notes);
            foreach (FtEntry entry in entries) AddRow(entry);
            RefreshCounts();
            Get<Button>("btnStart").Click += (a, b) => OnStart();
            Get<Button>("btnClose").Click += (a, b) => RequestClose();
            Get<Button>("btnTickShown").Click += (a, b) => OnTickShown();
            Get<Button>("btnClear").Click += (a, b) => OnClear();
            Get<TextBox>("tbFilter").TextChanged += (a, b) => ApplyFilter();
            Get<Button>("btnShowAll").Click += (a, b) => OnShowAll();
            Get<Button>("btnDebug").Click += (a, b) => OnDebug();
            hasPreselected = entries.Any(e => e.Preselected);
            selectedOnly = hasPreselected; // families picked in Revit: show just those first
            ApplyFilter();
            WriteDebug(false);
            if (hasPreselected)
                SetStatus("Showing the selected families. Press Start Update, or Show all families to pick others", "bMuted");
            else
                SetStatus("Tick the families to update (or type names, comma separated, in the filter), then press Start Update", "bMuted");
        }

        // ---- rows --------------------------------------------------------------------------------------

        private void AddRow(FtEntry entry)
        {
            var border = new Border { CornerRadius = new CornerRadius(4), Margin = new Thickness(0, 0, 0, 4), Padding = new Thickness(10, 6, 10, 6) };
            var grid = new Grid();
            double[] widths = { 24, -1, 190, 170 };
            foreach (double width in widths)
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = width < 0 ? new GridLength(1, GridUnitType.Star) : new GridLength(width) });
            var check = new CheckBox { IsChecked = entry.Checked, VerticalAlignment = VerticalAlignment.Center };
            check.Checked += (a, b) => OnCheckChanged();
            check.Unchecked += (a, b) => OnCheckChanged();
            Grid.SetColumn(check, 0);
            grid.Children.Add(check);
            string[] texts = { entry.Name, entry.Category, "" };
            var blocks = new TextBlock[3];
            for (int i = 0; i < 3; i++)
            {
                var block = new TextBlock
                {
                    Text = texts[i],
                    TextTrimming = TextTrimming.CharacterEllipsis,
                    ToolTip = texts[i],
                    Margin = new Thickness(0, 0, 8, 0),
                    VerticalAlignment = VerticalAlignment.Center,
                };
                Grid.SetColumn(block, i + 1);
                grid.Children.Add(block);
                blocks[i] = block;
            }
            border.Child = grid;
            Get<StackPanel>("FamilyList").Children.Add(border);
            var row = new Row { Entry = entry, Border = border, Texts = blocks, Check = check };
            rows.Add(row);
            SetState(row, "waiting", "", null);
        }

        private void SetState(Row row, string state, string text, string detail)
        {
            string key = state == "working" ? "bSelect" : state == "done" ? "bGreen" : state == "failed" ? "bRed" : "bField";
            row.Border.SetResourceReference(Border.BackgroundProperty, key);
            bool coloured = state == "done" || state == "failed";
            foreach (TextBlock block in row.Texts)
            {
                if (coloured) block.Foreground = Brushes.White;
                else block.ClearValue(TextBlock.ForegroundProperty);
                block.FontWeight = state == "working" || state == "done" ? FontWeights.SemiBold : FontWeights.Normal;
            }
            TextBlock status = row.Texts[2];
            status.Text = text;
            status.ToolTip = string.IsNullOrEmpty(detail) ? text : detail;
            if (state == "working")
            {
                try
                {
                    row.Border.BringIntoView();
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("batch.bring_into_view", err);
                }
            }
        }

        // ---- settings ----------------------------------------------------------------------------------

        private void ShowOptions()
        {
            var options = new List<string> { settings.ImageSize + " px " + settings.ImageFormat };
            if (settings.FillParams)
                options.Add("parameters " + settings.ParamCreator + ", " + settings.ParamRevision + ", " + settings.ParamDate);
            else options.Add("parameters off");
            options.Add("saved to " + FtCore.ExportFolder(settings));
            Get<TextBlock>("tbOptions").Text = string.Join("  |  ", options);
        }

        private void OnSettings()
        {
            if (running || openSettings == null) return;
            openSettings(Win); // modal: returns when the Settings window closes
            settings = FtSettings.Load();
            ShowOptions();
            FtCore.Log("settings reloaded from the batch window: size=" + settings.ImageSize + " " + settings.ImageFormat + " fill_params=" + settings.FillParams
                       + " folder=" + FtCore.ExportFolder(settings));
            SetStatus("Settings reloaded", "bMuted");
        }

        // ---- ticking / filtering -----------------------------------------------------------------------

        private List<Row> Ticked() { return rows.Where(r => r.Check.IsChecked == true).ToList(); }

        private void OnCheckChanged()
        {
            if (!running && !finished) RefreshCounts();
        }

        private void ApplyFilter()
        {
            string text = Get<TextBox>("tbFilter").Text.Replace(";", ",").Replace("\n", ",");
            List<string> terms = text.Split(',').Select(t => t.Trim().ToLowerInvariant()).Where(t => t.Length > 0).ToList();
            foreach (Row row in rows)
            {
                string haystack = row.Entry.Name.ToLowerInvariant() + "\n" + row.Entry.Category.ToLowerInvariant();
                bool shown = terms.Count == 0 || terms.Any(t => haystack.Contains(t));
                if (selectedOnly && !row.Entry.Preselected) shown = false;
                row.Border.Visibility = shown ? Visibility.Visible : Visibility.Collapsed;
            }
            var button = Get<Button>("btnShowAll");
            button.Content = selectedOnly ? "Show all families" : "Show selected only";
            button.IsEnabled = hasPreselected && !running && !finished;
        }

        private void OnShowAll()
        {
            if (running || finished) return;
            selectedOnly = !selectedOnly;
            ApplyFilter();
        }

        private void OnTickShown()
        {
            if (running || finished) return;
            foreach (Row row in rows)
                if (row.Border.Visibility == Visibility.Visible) row.Check.IsChecked = true;
        }

        private void OnClear()
        {
            if (running || finished) return;
            foreach (Row row in rows) row.Check.IsChecked = false;
        }

        private void RefreshCounts()
        {
            Get<TextBlock>("tbSummary").Text = Ticked().Count + " of " + rows.Count + " families ticked";
            SetProgress();
        }

        // ---- progress / status -------------------------------------------------------------------------

        private void SetProgress()
        {
            int total = running || finished ? queue.Count : Ticked().Count;
            ColumnDefinitionCollection columns = Get<Grid>("barGrid").ColumnDefinitions;
            columns[0].Width = new GridLength(done + failed, GridUnitType.Star);
            columns[1].Width = new GridLength(Math.Max(total - done - failed, 0), GridUnitType.Star);
            string text = done + " of " + total + " completed";
            if (failed > 0) text += "  (" + failed + " failed)";
            Get<TextBlock>("tbProgress").Text = text;
        }

        private void SetStatus(string text, string brushKey)
        {
            var status = Get<TextBlock>("tbStatus");
            status.Text = text;
            status.SetResourceReference(TextBlock.ForegroundProperty, brushKey);
        }

        // ---- run ---------------------------------------------------------------------------------------

        private void OnStart()
        {
            if (running || finished) return;
            queue = Ticked();
            if (queue.Count == 0)
            {
                SetStatus("Tick at least one family first", "bRed");
                return;
            }
            foreach (Row row in rows)
            {
                row.Check.IsEnabled = false;
                if (!queue.Contains(row)) row.Border.Opacity = 0.45;
            }
            foreach (string name in new[] { "btnTickShown", "btnClear", "btnShowAll" }) Get<Button>(name).IsEnabled = false;
            running = true;
            Get<Button>("btnStart").IsEnabled = false;
            Get<Button>("btnClose").Content = "Stop";
            SetProgress();
            SetStatus("Updating families...", "bOrange");
            FtCore.Log("--- batch start: " + queue.Count + " family(ies): " + string.Join(", ", queue.Select(r => r.Entry.Name).Take(40).ToArray())
                       + (queue.Count > 40 ? ", ..." : ""));
            FtCore.Log("batch settings: size=" + settings.ImageSize + " " + settings.ImageFormat + " fit=" + settings.FitMode + " fill_params=" + settings.FillParams
                       + " export_images=" + settings.ExportImages + " folder=" + FtCore.ExportFolder(settings));
            timer.Start();
        }

        private void OnTick(object sender, EventArgs args)
        {
            timer.Stop();
            if (cancel || index >= queue.Count)
            {
                Finish();
                return;
            }
            Row row = queue[index];
            if (phase == 0)
            {
                SetState(row, "working", "Working...", null);
                phase = 1; // let the window paint "Working..." before the family is opened
                timer.Start();
                return;
            }
            FtResult result;
            try
            {
                result = FtBatch.ProcessFamily(doc, row.Entry.Family, settings);
            }
            catch (Exception err)
            {
                FtCore.Swallowed("batch.process", err);
                result = new FtResult { Message = err.Message };
            }
            string notes = string.Join("; ", result.Notes);
            FtCore.Log("family '" + row.Entry.Name + "': " + (result.Ok ? "ok" : "FAILED") + " " + result.Message + " " + notes
                       + (result.Path == null ? "" : " | image " + result.Path) + (result.Rfa == null ? "" : " | rfa " + result.Rfa));
            if (result.Ok)
            {
                done++;
                SetState(row, "done", "Done", notes.Length > 0 ? notes : null);
            }
            else
            {
                failed++;
                failures.Add(row.Entry.Name);
                SetState(row, "failed", "Failed", result.Message);
            }
            index++;
            phase = 0;
            SetProgress();
            timer.Start();
        }

        private void Finish()
        {
            running = false;
            finished = true;
            int total = queue.Count;
            bool stopped = cancel && index < total;
            Get<Button>("btnClose").Content = "Close";
            Get<Button>("btnStart").Content = "Finished";
            if (stopped) SetStatus("Stopped: " + done + " of " + total + " done", "bOrange");
            else if (failed > 0) SetStatus("Finished with " + failed + " failed", "bOrange");
            else SetStatus("All families updated", "bGreen");
            FtCore.Log("batch finished: " + done + " done, " + failed + " failed, failures: " + string.Join(", ", failures.ToArray()));
            WriteDebug(false);
            PromptOpenFolder(stopped, total);
        }

        private void PromptOpenFolder(bool stopped, int total)
        {
            string folder = FtCore.ExportFolder(settings);
            string message = done + " of " + total + " families updated and loaded back into the project.";
            if (stopped) message = "Stopped. " + message;
            IList<string> notes = failures.Count > 0 ? new List<string> { "Failed: " + string.Join(", ", failures.ToArray()) } : null;
            FtPromptWindow.ShowMessage(Uiapp, "Update Batch complete", message, folder, notes, Directory.Exists(folder), Win);
        }

        // ---- debug -------------------------------------------------------------------------------------

        private string WriteDebug(bool ui)
        {
            try
            {
                return FtDebug.Write(Uiapp, uidoc, entries, settings, ui);
            }
            catch (Exception err)
            {
                FtCore.Swallowed("batch.debug", err);
                return null;
            }
        }

        private void OnDebug()
        {
            string path = WriteDebug(true);
            SetStatus(path != null ? "Debug log saved: " + path : "The debug log could not be saved", path != null ? "bGreen" : "bRed");
        }

        // ---- closing -----------------------------------------------------------------------------------

        public override void RequestClose()
        {
            if (running)
            {
                cancel = true;
                SetStatus("Stopping after the current family...", "bOrange");
                return;
            }
            Win.Close();
        }

        public static void Open(UIApplication uiapp, UIDocument uidoc, List<FtEntry> entries, IList<string> notes, FtSettings settings,
            Action<Window> openSettings)
        {
            new FtBatchWindow(uiapp, uidoc, entries, notes, settings, openSettings).Show(null);
        }
    }
}
