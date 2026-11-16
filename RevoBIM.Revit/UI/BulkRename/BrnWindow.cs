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
using ComboBox = System.Windows.Controls.ComboBox;
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

    /// <summary>One sheet on the Parameter Push tab: its number, its name, and what each part would be written as.</summary>
    internal sealed class BrnPushRowView
    {
        private const double RowHeight = 26.0;
        private string signature;
        private readonly TextBlock number = new TextBlock();
        private readonly TextBlock name = new TextBlock();
        private readonly TextBlock result = new TextBlock();
        public readonly Border Border = new Border();

        public BrnPushRowView()
        {
            Border.Height = RowHeight;
            Border.Padding = new Thickness(8, 0, 8, 0);
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto), MinWidth = 64 });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
            number.VerticalAlignment = VerticalAlignment.Center;
            number.FontSize = 11;
            number.Margin = new Thickness(0, 0, 12, 0);
            number.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
            name.VerticalAlignment = VerticalAlignment.Center;
            name.TextTrimming = TextTrimming.CharacterEllipsis;
            name.TextWrapping = TextWrapping.NoWrap;
            name.SetResourceReference(TextBlock.ForegroundProperty, "Text");
            result.VerticalAlignment = VerticalAlignment.Center;
            result.Margin = new Thickness(14, 0, 0, 0);
            result.FontWeight = FontWeights.SemiBold;
            Grid.SetColumn(name, 1);
            Grid.SetColumn(result, 2);
            grid.Children.Add(number);
            grid.Children.Add(name);
            grid.Children.Add(result);
            Border.Child = grid;
        }

        public static string ResultText(IList<KeyValuePair<string, string>> writes)
        {
            return string.Join("  |  ", writes.Select(w => w.Value.Length > 0 ? w.Value : "(blank)"));
        }

        public void Show(string sheetNumber, string sheetName, IList<KeyValuePair<string, string>> writes)
        {
            string text = ResultText(writes);
            string next = sheetNumber + "\u0001" + sheetName + "\u0001" + text;
            if (next == signature) return;
            signature = next;
            number.Text = sheetNumber;
            name.Text = sheetName;
            result.Text = text;
            if (writes.Count == 0) result.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
            else result.SetResourceReference(TextBlock.ForegroundProperty, "Orange");
            Border.ToolTip = writes.Count == 0
                ? "No target parameter is set"
                : string.Join("\n", writes.Select(w => w.Key + " = " + (w.Value.Length > 0 ? w.Value : "(blank)")));
        }
    }

    /// <summary>
    /// The Bulk Rename window: tools on the left, the selected items on the right, a live preview, and
    /// nothing written until Apply. Modeless; the write runs in Revit's API context through an external event.
    /// With sheets selected a third tab, Parameter Push, splits each sheet's name into parts and writes them
    /// to the parameters chosen there (the Sheet Name Push tool).
    /// Port of brn_main.py, with Sheet Name Push folded in.
    /// </summary>
    internal sealed class BrnWindow : BrnThemedWindow
    {
        private const double ListMaxWidth = 640.0;
        private const int WatchdogSeconds = 20;
        private const string None = "(none)";

        private static readonly string[] DefaultParams = { "BGL_Sheet Title 1", "BGL_Sheet Title 2", "BGL_Sheet Title 3" };

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
        private readonly Dictionary<long, BrnPushRowView> pushViews = new Dictionary<long, BrnPushRowView>();
        private readonly Dictionary<Field, Rules> rules = new Dictionary<Field, Rules>
        {
            { Field.Name, new Rules() }, { Field.Number, new Rules() },
        };

        private Dictionary<string, HashSet<string>> taken;
        private List<Item> items = new List<Item>();
        private Field field = Field.Name;
        private bool onPush;
        private bool busy;
        private bool loading;
        private DispatcherTimer watchdog;

        private readonly TextBox findBox, replaceBox, prefixBox, suffixBox, pushDelimiter;
        private readonly CheckBox caseBox, debugBox;
        private readonly Panel listHost;
        private readonly ScrollViewer listScroller;
        private readonly TextBlock listHeading, status, applyText, tabNameText, tabNumberText, tabPushText;
        private readonly Button applyBtn, clearBtn, pushDefaultsBtn;
        private readonly RadioButton tabName, tabNumber, tabPush, fmtUpper, fmtTitle, fmtNone;
        private readonly UIElement renameTools, pushTools;
        private readonly List<ComboBox> pushCombos = new List<ComboBox>();

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
            tabPush = (RadioButton)Win.FindName("TabPush");
            tabNameText = (TextBlock)Win.FindName("TabNameText");
            tabNumberText = (TextBlock)Win.FindName("TabNumberText");
            tabPushText = (TextBlock)Win.FindName("TabPushText");
            debugBox = (CheckBox)Win.FindName("DebugBox");
            renameTools = (UIElement)Win.FindName("RenameTools");
            pushTools = (UIElement)Win.FindName("PushTools");
            pushDelimiter = (TextBox)Win.FindName("PushDelimiter");
            pushDefaultsBtn = (Button)Win.FindName("PushDefaultsBtn");
            fmtUpper = (RadioButton)Win.FindName("FmtUpper");
            fmtTitle = (RadioButton)Win.FindName("FmtTitle");
            fmtNone = (RadioButton)Win.FindName("FmtNone");
            for (int i = 1; i <= 3; i++) pushCombos.Add((ComboBox)Win.FindName("PushParam" + i));

            string debug;
            debugBox.IsChecked = !settings.TryGetValue("debug", out debug) || debug == "1";
            ((UIElement)Win.FindName("TabBar")).Visibility = hasSheets ? Visibility.Visible : Visibility.Collapsed;

            foreach (Row row in rows)
            {
                views[row.Key] = new BrnRowView();
                if (row.Has(Field.Number)) pushViews[row.Key] = new BrnPushRowView();
            }
            LoadPushSettings();
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
            // The Parameter Push tools are taller than the rename ones: never start shorter than they need.
            Win.MinHeight = Math.Min(height, 300.0);
            findBox.Focus();
        }

        private void ShowField()
        {
            listHost.Children.Clear();
            foreach (Row row in rows)
            {
                if (onPush)
                {
                    if (row.Has(Field.Number)) listHost.Children.Add(pushViews[row.Key].Border);
                }
                else if (row.Has(field))
                {
                    listHost.Children.Add(views[row.Key].Border);
                }
            }
            string text = BrnCore.Plural(listHost.Children.Count, onPush ? "sheet" : "item") + " selected";
            if (leftOut > 0 || (onPush && rows.Count > listHost.Children.Count))
            {
                int other = leftOut + (onPush ? rows.Count - listHost.Children.Count : 0);
                text += ", " + other + " cannot be " + (onPush ? "pushed" : "renamed") + " here";
            }
            listHeading.Text = text;
        }

        // ---------- tools ----------
        private void WireTools()
        {
            foreach (TextBox box in new[] { findBox, replaceBox, prefixBox, suffixBox })
                box.TextChanged += (s, a) => Guard("rule", OnRuleChanged);
            caseBox.Click += (s, a) => Guard("rule", OnRuleChanged);
            tabName.Checked += (s, a) => Guard("tab", () => Select(false, Field.Name));
            tabNumber.Checked += (s, a) => Guard("tab", () => Select(false, Field.Number));
            tabPush.Checked += (s, a) => Guard("tab", () => Select(true, field));
            applyBtn.Click += (s, a) => Guard("apply", OnApply);
            clearBtn.Click += (s, a) => Guard("clear", OnClear);
            debugBox.Click += (s, a) => Guard("debug", OnDebug);
            foreach (ComboBox combo in pushCombos)
                combo.SelectionChanged += (s, a) => Guard("push", OnPushChanged);
            pushDelimiter.TextChanged += (s, a) => Guard("push", OnPushChanged);
            foreach (RadioButton radio in new[] { fmtUpper, fmtTitle, fmtNone })
                radio.Click += (s, a) => Guard("push", OnPushChanged);
            pushDefaultsBtn.Click += (s, a) => Guard("push", OnPushDefaults);
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

        /// <summary>Switch tab. The Parameter Push tab keeps the field the rename tabs were last on.</summary>
        private void Select(bool push, Field next)
        {
            if (push == onPush && (push || next == field)) return;
            onPush = push;
            if (!push) field = next;
            renameTools.Visibility = push ? Visibility.Collapsed : Visibility.Visible;
            pushTools.Visibility = push ? Visibility.Visible : Visibility.Collapsed;
            clearBtn.Visibility = push ? Visibility.Collapsed : Visibility.Visible;
            if (!push) LoadTools();
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
            if (onPush)
            {
                foreach (Row row in rows.Where(r => r.Has(Field.Number)))
                {
                    var writes = PushWrites(row);
                    pairs.Add(Tuple.Create(TextWidth(row.Values[Field.Number], 11) + 76 + TextWidth(FinalName(row), Win.FontSize),
                                           TextWidth(BrnPushRowView.ResultText(writes), Win.FontSize, FontWeights.SemiBold)));
                }
            }
            else
            {
                foreach (Item item in items)
                {
                    if (item.Field != field) continue;
                    pairs.Add(Tuple.Create(TextWidth(item.Final, Win.FontSize, FontWeights.SemiBold),
                                           TextWidth(ContextFor(item), 11)));
                }
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
            if (!onPush) LoadTools();
            Refresh();
        }

        // ---------- parameter push settings ----------
        private string SettingOf(string key)
        {
            string value;
            return Settings.TryGetValue(key, out value) ? value ?? "" : "";
        }

        private void LoadPushSettings()
        {
            loading = true;
            try
            {
                for (int i = 0; i < pushCombos.Count; i++)
                {
                    ComboBox combo = pushCombos[i];
                    string current = SettingOf(BrnCore.ParamKeys[i]);
                    combo.Items.Clear();
                    combo.Items.Add(None);
                    var names = new List<string>(parameters);
                    foreach (string wanted in DefaultParams.Concat(new[] { current }))
                    {
                        if (wanted.Length > 0 && !names.Contains(wanted)) names.Insert(0, wanted);
                    }
                    foreach (string name in names) combo.Items.Add(name);
                    combo.SelectedItem = current.Length > 0 ? current : None;
                }
                pushDelimiter.Text = SettingOf("sheet_delimiter");
                string format = SettingOf("sheet_format");
                fmtUpper.IsChecked = format == "upper";
                fmtTitle.IsChecked = format == "title";
                fmtNone.IsChecked = format != "upper" && format != "title";
            }
            finally
            {
                loading = false;
            }
        }

        /// <summary>Remembered at once, for the next run.</summary>
        private void OnPushChanged()
        {
            if (loading) return;
            for (int i = 0; i < pushCombos.Count; i++)
            {
                string value = pushCombos[i].SelectedItem as string ?? "";
                Settings[BrnCore.ParamKeys[i]] = value == None ? "" : value;
            }
            Settings["sheet_delimiter"] = pushDelimiter.Text ?? "";
            Settings["sheet_format"] = fmtUpper.IsChecked == true ? "upper" : fmtTitle.IsChecked == true ? "title" : "none";
            BrnCore.SaveSettings(Settings);
            Refresh();
        }

        private void OnPushDefaults()
        {
            for (int i = 0; i < DefaultParams.Length; i++) Settings[BrnCore.ParamKeys[i]] = DefaultParams[i];
            Settings["sheet_delimiter"] = BrnCore.Defaults["sheet_delimiter"];
            BrnCore.SaveSettings(Settings);
            LoadPushSettings();
            Refresh();
        }

        /// <summary>The sheet's name as it will be once any staged rename is applied.</summary>
        private string FinalName(Row row)
        {
            Item item = items.FirstOrDefault(i => ReferenceEquals(i.Row, row) && i.Field == Field.Name);
            return item != null ? item.Final : row.Values[Field.Name];
        }

        private List<KeyValuePair<string, string>> PushWrites(Row row)
        {
            return BrnCore.SheetWrites(FinalName(row), Settings);
        }

        private int PushSheetCount()
        {
            return rows.Count(r => r.Has(Field.Number));
        }

        // ---------- preview ----------
        private void Refresh()
        {
            items = BrnCore.Evaluate(rows, rules, taken);
            foreach (Item item in items)
            {
                if (!onPush && item.Field == field) views[item.Row.Key].Show(item, ContextFor(item));
            }
            int count = BrnCore.Changes(items).Count;
            if (onPush)
            {
                foreach (Row row in rows.Where(r => r.Has(Field.Number)))
                    pushViews[row.Key].Show(row.Values[Field.Number], FinalName(row), PushWrites(row));
                int sheets = PushSheetCount();
                int targets = BrnCore.SheetWrites("x", Settings).Count;
                status.Text = targets == 0
                    ? "Choose at least one parameter to push to."
                    : BrnCore.Plural(sheets, "sheet") + " will be written to " + BrnCore.Plural(targets, "parameter") +
                      " (" + BrnCore.FormatLabel(SettingOf("sheet_format")) + ")" +
                      (count > 0 ? ", after " + BrnCore.Plural(count, "rename") : "");
                applyText.Text = "Push (" + sheets + ")";
                applyBtn.IsEnabled = targets > 0 && sheets > 0 && !busy;
            }
            else
            {
                status.Text = BrnCore.StatusLine(items);
                applyText.Text = count > 0 ? "Apply (" + count + ")" : "Apply";
                applyBtn.IsEnabled = count > 0 && !busy;
            }
            clearBtn.IsEnabled = !rules.Values.All(r => r.IsEmpty);
            if (hasSheets)
            {
                tabNameText.Text = TabLabel("Sheet Name", Field.Name);
                tabNumberText.Text = TabLabel("Sheet Number", Field.Number);
                tabPushText.Text = "Parameter Push";
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

        // ---------- apply and push ----------
        private void OnApply()
        {
            if (onPush)
            {
                OnPush();
                return;
            }
            if (busy || BrnCore.Changes(items).Count == 0) return;
            SetBusy(true);
            status.Text = "Renaming...";
            if (runner.Submit(Job, OnRefused)) StartWatchdog();
        }

        private void SetBusy(bool value)
        {
            busy = value;
            Refresh();
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

        private void OnPush()
        {
            if (busy) return;
            if (BrnCore.SheetWrites("x", Settings).Count == 0)
            {
                status.Text = "Choose at least one parameter to push to.";
                return;
            }
            int waiting = BrnCore.Changes(items).Count;
            if (waiting > 0)
            {
                bool go = BrnDialogs.Ask(Uiapp, Settings, Log,
                    "Apply the " + BrnCore.Plural(waiting, "rename") + " first, then push the sheet names?",
                    "Apply and push", "Cancel", this);
                if (!go) return;
            }
            SetBusy(true);
            status.Text = "Pushing sheet names...";
            bool rename = waiting > 0;
            if (runner.Submit(() => PushJob(rename), OnRefused)) StartWatchdog();
        }

        /// <summary>Runs inside Revit's API context.</summary>
        private void PushJob(bool rename)
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
                Log.Write("push: " + err);
                report = new BrnReport();
                report.Failed.Add(new Failure(null, "Revit stopped the push: " + err.Message));
            }
            Win.Dispatcher.BeginInvoke(new Action(() => AfterPush(report, rename)));
        }

        private void AfterPush(BrnReport report, bool rename)
        {
            Guard("after_push", () =>
            {
                StopWatchdog();
                SetBusy(false);
                Log.Write("pushed " + report.Written + ", failed " + report.Failed.Count);
                if (report.Taken != null) taken = report.Taken;
                if (rename) OnClear();
                int ok = report.Lines.Count(l => l.Status == "OK");
                int problems = report.Lines.Count - ok + report.Failed.Count(f => f.Row == null || !f.Push);
                status.Text = "Pushed " + BrnCore.Plural(report.Written, "sheet") + (problems > 0 ? ", " + problems + " to look at" : "");
                ShowPushResults(report, rename, ok, problems);
            });
        }

        /// <summary>The results of a push: what each parameter was set to, and anything that was not.</summary>
        private void ShowPushResults(BrnReport report, bool rename, int ok, int problems)
        {
            var lines = new List<string>();
            foreach (PushLine line in report.Lines)
            {
                string mark = line.Status == "OK" ? "  " : "! ";
                lines.Add(mark + line.Number + "  " + line.Name + "  |  " + line.Param + " = " +
                          (line.Value != null && line.Value.Length > 0 ? line.Value : "(blank)") + "  -  " + line.Status);
            }
            foreach (Failure failure in report.Failed.Where(f => f.Row == null || !f.Push))
            {
                string who = failure.Row != null ? failure.Row.Values[Field.Name] : "Whole job";
                lines.Add("! " + who + ": " + failure.Reason);
            }
            int sheets = report.Lines.Select(l => l.Number).Distinct().Count();
            string message = BrnCore.Plural(sheets, "sheet") + " - " + BrnCore.Plural(ok, "parameter") + " written - text format: " +
                             BrnCore.FormatLabel(SettingOf("sheet_format")) +
                             (rename ? " - " + report.Done + " renamed first" : "") + "\n" +
                             (problems > 0 ? BrnCore.Plural(problems, "item") + " need a look (marked !)." : "Everything written cleanly.");
            BrnDialogs.Tell(Uiapp, Settings, Log, message, "Parameter Push", string.Join("\n", lines), this, true);
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
            status.Text = "Revit would not take the request (" + answer + "). Try again.";
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
            status.Text = "Revit is busy. The job runs when it is free.";
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
