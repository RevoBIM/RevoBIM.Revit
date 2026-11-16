using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Threading;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.BulkRename;
using Document = Autodesk.Revit.DB.Document;
using Panel = System.Windows.Controls.Panel;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.BulkRename
{
    /// <summary>One line of the list. Only redrawn when its text or state moved.</summary>
    internal sealed class BrnRowView
    {
        private const double RowHeight = 26.0;
        private string signature;
        private readonly TextBlock text = new TextBlock();
        private readonly TextBlock context = new TextBlock();
        public readonly Border Border = new Border();

        public BrnRowView()
        {
            Border.Height = RowHeight;
            Border.Padding = new Thickness(8, 0, 8, 0);
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            text.VerticalAlignment = VerticalAlignment.Center;
            text.TextTrimming = TextTrimming.CharacterEllipsis;
            text.TextWrapping = TextWrapping.NoWrap;
            context.VerticalAlignment = VerticalAlignment.Center;
            context.Margin = new Thickness(14, 0, 0, 0);
            context.FontSize = 11;
            context.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
            Grid.SetColumn(context, 1);
            grid.Children.Add(text);
            grid.Children.Add(context);
            Border.Child = grid;
        }

        public void Show(Item item, string contextText)
        {
            string next = item.New + "\u0001" + item.State + "\u0001" + item.Old + "\u0001" + contextText;
            if (next == signature) return;
            signature = next;
            context.Text = contextText;
            InlineCollection inlines = text.Inlines;
            inlines.Clear();
            if (item.State == ItemState.Change)
            {
                text.SetResourceReference(TextBlock.ForegroundProperty, "Text");
                foreach (Segment piece in item.Segments)
                {
                    var run = new Run(piece.Text);
                    if (piece.Changed)
                    {
                        run.SetResourceReference(TextElement.ForegroundProperty, "Orange");
                        run.FontWeight = FontWeights.SemiBold;
                    }
                    inlines.Add(run);
                }
                Border.ToolTip = "Was: " + item.Old;
            }
            else if (item.State == ItemState.Clash || item.State == ItemState.Bad)
            {
                text.SetResourceReference(TextBlock.ForegroundProperty, "Red");
                inlines.Add(new Run(string.IsNullOrEmpty(item.New) ? item.Old : item.New));
                Border.ToolTip = item.Reason + " - left alone. Now: " + item.Old;
            }
            else
            {
                text.SetResourceReference(TextBlock.ForegroundProperty, "Text");
                inlines.Add(new Run(item.Old));
                Border.ToolTip = item.Old;
            }
        }
    }

    /// <summary>
    /// The Bulk Rename window: tools on the left, the selected items on the right, a live preview, and
    /// nothing written until Apply. Modeless; the write runs in Revit's API context through an external event.
    /// Port of brn_main.py.
    /// </summary>
    internal sealed class BrnWindow : BrnThemedWindow
    {
        private const double ListMaxWidth = 640.0;
        private const int WatchdogSeconds = 20;

        /// <summary>The window that is open, so a second run replaces it instead of stacking another.</summary>
        internal static BrnWindow Current;

        private readonly Document doc;
        private readonly List<Row> rows;
        private readonly BrnRunner runner;
        private readonly int leftOut;
        private readonly List<string> parameters;
        private readonly bool hasSheets;
        private readonly bool mixed;
        private readonly Dictionary<long, BrnRowView> views = new Dictionary<long, BrnRowView>();
        private readonly Dictionary<Field, Rules> rules = new Dictionary<Field, Rules>
        {
            { Field.Name, new Rules() }, { Field.Number, new Rules() },
        };

        private Dictionary<string, HashSet<string>> taken;
        private List<Item> items = new List<Item>();
        private Field field = Field.Name;
        private bool busy;
        private bool loading;
        private DispatcherTimer watchdog;

        private readonly TextBox findBox, replaceBox, prefixBox, suffixBox;
        private readonly CheckBox caseBox, debugBox;
        private readonly Panel listHost;
        private readonly ScrollViewer listScroller;
        private readonly TextBlock listHeading, status, applyText, tabNameText, tabNumberText;
        private readonly Button applyBtn, clearBtn, writeBtn, settingsBtn;
        private readonly RadioButton tabName, tabNumber;

        public BrnWindow(UIApplication uiapp, Dictionary<string, string> settings, BrnLog log, Document doc,
                         List<Row> rows, Dictionary<string, HashSet<string>> taken, int leftOut, BrnRunner runner,
                         List<string> parameters)
            : base(uiapp, settings, log, "BulkRename.xaml")
        {
            this.doc = doc;
            this.rows = rows;
            this.taken = taken;
            this.leftOut = leftOut;
            this.runner = runner;
            this.parameters = parameters;
            hasSheets = rows.Any(r => r.Has(Field.Number));
            mixed = rows.Select(r => r.Kind).Distinct().Count() > 1;

            findBox = (TextBox)Win.FindName("FindBox");
            replaceBox = (TextBox)Win.FindName("ReplaceBox");
            caseBox = (CheckBox)Win.FindName("CaseBox");
            prefixBox = (TextBox)Win.FindName("PrefixBox");
            suffixBox = (TextBox)Win.FindName("SuffixBox");
            listHost = (Panel)Win.FindName("ListHost");
            listScroller = (ScrollViewer)Win.FindName("ListScroller");
            listHeading = (TextBlock)Win.FindName("ListHeading");
            status = (TextBlock)Win.FindName("StatusText");
            applyBtn = (Button)Win.FindName("ApplyBtn");
            applyText = (TextBlock)Win.FindName("ApplyText");
            clearBtn = (Button)Win.FindName("ClearBtn");
            tabName = (RadioButton)Win.FindName("TabName");
            tabNumber = (RadioButton)Win.FindName("TabNumber");
            tabNameText = (TextBlock)Win.FindName("TabNameText");
            tabNumberText = (TextBlock)Win.FindName("TabNumberText");
            debugBox = (CheckBox)Win.FindName("DebugBox");
            writeBtn = (Button)Win.FindName("WriteBtn");
            settingsBtn = (Button)Win.FindName("SettingsBtn");

            string debug;
            debugBox.IsChecked = !settings.TryGetValue("debug", out debug) || debug == "1";
            writeBtn.Visibility = hasSheets ? Visibility.Visible : Visibility.Collapsed;
            ((UIElement)Win.FindName("TabBar")).Visibility = hasSheets ? Visibility.Visible : Visibility.Collapsed;

            foreach (Row row in rows) views[row.Key] = new BrnRowView();
            Fit();
            WireTools();
            OwnToRevit();
            Refresh();
            EggHook.Attach(Win, () => ThemeName, Logo);
        }

        // ---------- layout ----------

        /// <summary>
        /// The window sizes itself to the list. Once drawn it goes back to a normal window, so typing cannot
        /// make it jump and the grips work.
        /// </summary>
        private void Fit()
        {
            listScroller.MaxHeight = SystemParameters.WorkArea.Height * 0.75;
            listScroller.MaxWidth = ListMaxWidth;
            Win.ContentRendered += (s, a) => Guard("rendered", OnRendered);
        }

        private void OnRendered()
        {
            double width = Win.ActualWidth, height = Win.ActualHeight;
            Win.SizeToContent = SizeToContent.Manual;
            Win.Width = width;
            Win.Height = height;
            listScroller.ClearValue(FrameworkElement.MaxHeightProperty);
            listScroller.ClearValue(FrameworkElement.MaxWidthProperty);
            Win.MinHeight = Math.Min(height, 300.0);
            findBox.Focus();
        }

        private void ShowField()
        {
            listHost.Children.Clear();
            foreach (Row row in rows)
            {
                if (row.Has(field)) listHost.Children.Add(views[row.Key].Border);
            }
            string text = BrnCore.Plural(listHost.Children.Count, "item") + " selected";
            if (leftOut > 0) text += ", " + leftOut + " cannot be renamed here";
            listHeading.Text = text;
        }

        // ---------- tools ----------
        private void WireTools()
        {
            foreach (TextBox box in new[] { findBox, replaceBox, prefixBox, suffixBox })
                box.TextChanged += (s, a) => Guard("rule", OnRuleChanged);
            caseBox.Click += (s, a) => Guard("rule", OnRuleChanged);
            tabName.Checked += (s, a) => Guard("tab", () => SetField(Field.Name));
            tabNumber.Checked += (s, a) => Guard("tab", () => SetField(Field.Number));
            applyBtn.Click += (s, a) => Guard("apply", OnApply);
            clearBtn.Click += (s, a) => Guard("clear", OnClear);
            writeBtn.Click += (s, a) => Guard("write", OnWrite);
            settingsBtn.Click += (s, a) => Guard("settings", OnSettings);
            debugBox.Click += (s, a) => Guard("debug", OnDebug);
            ShowField();
        }

        private void OnDebug()
        {
            bool on = debugBox.IsChecked == true;
            Log.Enabled = on;
            Settings["debug"] = on ? "1" : "0";
            BrnCore.SaveSettings(Settings);
        }

        private void OnRuleChanged()
        {
            if (loading) return;
            Rules current = rules[field];
            current.Find = findBox.Text;
            current.Replace = replaceBox.Text;
            current.MatchCase = caseBox.IsChecked == true;
            current.Prefix = prefixBox.Text;
            current.Suffix = suffixBox.Text;
            Refresh();
        }

        private void LoadTools()
        {
            Rules current = rules[field];
            loading = true;
            try
            {
                findBox.Text = current.Find;
                replaceBox.Text = current.Replace;
                caseBox.IsChecked = current.MatchCase;
                prefixBox.Text = current.Prefix;
                suffixBox.Text = current.Suffix;
            }
            finally
            {
                loading = false;
            }
        }

        private void SetField(Field next)
        {
            if (next == field) return;
            field = next;
            LoadTools();
            ShowField();
            Refresh();
            WidenToFit();
        }

        private double TextWidth(string text, double size, FontWeight? weight = null)
        {
            if (string.IsNullOrEmpty(text)) return 0.0;
            var probe = new TextBlock { FontFamily = Win.FontFamily, FontSize = size, Text = text };
            if (weight.HasValue) probe.FontWeight = weight.Value;
            probe.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            return probe.DesiredSize.Width;
        }

        /// <summary>
        /// Measured on a loose TextBlock, so the rows' own layout is untouched. Only ever grows: the width
        /// stays for the next tab.
        /// </summary>
        private void WidenToFit()
        {
            var pairs = new List<Tuple<double, double>>();
            foreach (Item item in items)
            {
                if (item.Field != field) continue;
                pairs.Add(Tuple.Create(TextWidth(item.Final, Win.FontSize, FontWeights.SemiBold),
                                       TextWidth(ContextFor(item), 11)));
            }
            double extra = BrnCore.ListWidth(pairs) - listScroller.ActualWidth;
            Rect4 area = WorkArea();
            Tuple<double, double> grown = BrnCore.Widened(Win.Left, Win.ActualWidth, extra, area.Left, area.Width);
            if (grown.Item2 != Win.ActualWidth)
            {
                FullBounds = null;
                Win.Left = grown.Item1;
                Win.Width = grown.Item2;
                Log.Write("widened to " + grown.Item2);
            }
        }

        private void OnClear()
        {
            rules[Field.Name] = new Rules();
            rules[Field.Number] = new Rules();
            LoadTools();
            Refresh();
        }

        // ---------- preview ----------
        private void Refresh()
        {
            items = BrnCore.Evaluate(rows, rules, taken);
            foreach (Item item in items)
            {
                if (item.Field == field) views[item.Row.Key].Show(item, ContextFor(item));
            }
            status.Text = BrnCore.StatusLine(items);
            int count = BrnCore.Changes(items).Count;
            applyText.Text = count > 0 ? "Apply (" + count + ")" : "Apply";
            applyBtn.IsEnabled = count > 0 && !busy;
            clearBtn.IsEnabled = !rules.Values.All(r => r.IsEmpty);
            if (hasSheets)
            {
                tabNameText.Text = TabLabel("Sheet Name", Field.Name);
                tabNumberText.Text = TabLabel("Sheet Number", Field.Number);
            }
        }

        private string TabLabel(string title, Field of)
        {
            int count = BrnCore.Changes(items).Count(i => i.Field == of);
            return count > 0 ? title + " (" + count + ")" : title;
        }

        private string ContextFor(Item item)
        {
            Row row = item.Row;
            if (row.Has(Field.Number))
            {
                Field other = item.Field == Field.Name ? Field.Number : Field.Name;
                return row.Values[other];
            }
            return mixed ? row.Kind : "";
        }

        // ---------- apply ----------
        private void OnApply()
        {
            if (busy || BrnCore.Changes(items).Count == 0) return;
            SetBusy(true);
            status.Text = "Renaming...";
            if (runner.Submit(Job, OnRefused)) StartWatchdog();
        }

        private void SetBusy(bool value)
        {
            busy = value;
            applyBtn.IsEnabled = !value && BrnCore.Changes(items).Count > 0;
            writeBtn.IsEnabled = !value;
        }

        /// <summary>Runs inside Revit's API context.</summary>
        private void Job()
        {
            BrnReport report;
            try
            {
                if (!doc.IsValidObject)
                {
                    report = new BrnReport();
                    report.Failed.Add(new Failure(null, "That model is no longer open"));
                }
                else
                {
                    report = BrnRevit.ApplyJob(doc, rows, rules, Log);
                }
            }
            catch (Exception err)
            {
                Log.Write("apply: " + err);
                report = new BrnReport();
                report.Failed.Add(new Failure(null, "Revit stopped the rename: " + err.Message));
            }
            Win.Dispatcher.BeginInvoke(new Action(() => AfterApply(report)));
        }

        private void AfterApply(BrnReport report)
        {
            Guard("after_apply", () =>
            {
                StopWatchdog();
                SetBusy(false);
                Log.Write("applied " + report.Done + ", failed " + report.Failed.Count);
                if (report.Failed.Count == 0)
                {
                    ForceClose();
                    return;
                }
                if (report.Taken != null) taken = report.Taken;
                OnClear();
                int count = report.Failed.Count;
                status.Text = report.Done + " renamed, " + count + " not";
                ShowFailed(report, report.Done + " renamed, " + count + " left as it was.");
            });
        }

        // ---------- write sheet names ----------
        private void OnSettings()
        {
            if (busy) return;
            Row sheet = rows.FirstOrDefault(r => r.Has(Field.Number));
            string sample = sheet != null ? sheet.Values[Field.Name] : "NAME_ONE_TWO";
            new BrnSettingsWindow(Uiapp, Settings, Log, this, parameters, sample).Run();
        }

        private void OnWrite()
        {
            if (busy) return;
            if (BrnCore.SheetWrites("x", Settings).Count == 0)
            {
                OnSettings();
                return;
            }
            int waiting = BrnCore.Changes(items).Count;
            if (waiting > 0)
            {
                bool go = BrnDialogs.Ask(Uiapp, Settings, Log,
                    "Apply the " + BrnCore.Plural(waiting, "change") + " first, then write the sheet names?",
                    "Apply and write", "Cancel", this);
                if (!go) return;
            }
            SetBusy(true);
            status.Text = "Writing sheet names...";
            bool rename = waiting > 0;
            if (runner.Submit(() => WriteJob(rename), OnRefused)) StartWatchdog();
        }

        /// <summary>Runs inside Revit's API context.</summary>
        private void WriteJob(bool rename)
        {
            BrnReport report;
            try
            {
                if (!doc.IsValidObject)
                {
                    report = new BrnReport();
                    report.Failed.Add(new Failure(null, "That model is no longer open"));
                }
                else
                {
                    report = BrnRevit.RenameAndWrite(doc, rows, rules, Settings, rename, Log);
                }
            }
            catch (Exception err)
            {
                Log.Write("write: " + err);
                report = new BrnReport();
                report.Failed.Add(new Failure(null, "Revit stopped the write: " + err.Message));
            }
            Win.Dispatcher.BeginInvoke(new Action(() => AfterWrite(report, rename)));
        }

        private void AfterWrite(BrnReport report, bool rename)
        {
            Guard("after_write", () =>
            {
                StopWatchdog();
                SetBusy(false);
                Log.Write("wrote " + report.Written + ", failed " + report.Failed.Count);
                if (report.Taken != null) taken = report.Taken;
                if (rename) OnClear();
                status.Text = "Sheet names written on " + BrnCore.Plural(report.Written, "sheet");
                if (report.Failed.Count > 0)
                    ShowFailed(report, report.Written + " written, " + report.Failed.Count + " not.");
            });
        }

        private void ShowFailed(BrnReport report, string message)
        {
            var lines = new List<string>();
            foreach (Failure failure in report.Failed)
            {
                string name = failure.Row != null ? failure.Row.Values[Field.Name] : "Sheet names";
                lines.Add(name + ": " + failure.Reason);
            }
            BrnDialogs.Tell(Uiapp, Settings, Log, message, "Some not done", string.Join("\n", lines), this);
        }

        private void OnRefused(string answer)
        {
            SetBusy(false);
            status.Text = "Revit would not take the rename (" + answer + "). Try again.";
        }

        private void StartWatchdog()
        {
            watchdog = new DispatcherTimer { Interval = TimeSpan.FromSeconds(WatchdogSeconds) };
            watchdog.Tick += (s, a) => Guard("watchdog", OnWatchdog);
            watchdog.Start();
        }

        private void StopWatchdog()
        {
            if (watchdog == null) return;
            watchdog.Stop();
            watchdog = null;
        }

        private void OnWatchdog()
        {
            StopWatchdog();
            Log.Write("watchdog: Revit has not picked up the job");
            SetBusy(false);
            status.Text = "Revit is busy. The rename runs when it is free.";
        }

        // ---------- lifetime ----------
        public override void RequestClose()
        {
            if (busy) return;
            if (BrnCore.Changes(items).Count > 0)
            {
                bool leave = BrnDialogs.Ask(Uiapp, Settings, Log, "Close without applying these changes?",
                                            "Close", "Keep editing", this);
                if (!leave) return;
            }
            Win.Close();
        }

        public void ForceClose()
        {
            Win.Close();
        }

        protected override void OnClosed()
        {
            base.OnClosed();
            StopWatchdog();
            BrnCore.SaveSettings(Settings);
            if (ReferenceEquals(Current, this)) Current = null;
        }

        /// <summary>Shows the window modelessly and records it as the open one.</summary>
        public void Show()
        {
            Current = this;
            Win.Show();
        }
    }
}
