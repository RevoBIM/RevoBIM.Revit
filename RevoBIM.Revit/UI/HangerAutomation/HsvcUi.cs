using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using RevoBIM.Tools.HangerAutomation;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.HangerAutomation
{
    /// <summary>
    /// What <see cref="SvcTab"/> needs from the window that owns it, on top of <see cref="IFhaHost"/>
    /// (Status, ResizeForFold ... which it also uses). The window (FhaWindow) implements this.
    /// Python names in brackets.
    /// </summary>
    public interface ISvcOwner : IFhaHost
    {
        /// <summary>Win.FindName(name): a named element of the window's layout (owner.c).</summary>
        FrameworkElement C(string name);

        /// <summary>Queue a tool job (picks, writes, results box, debug file) (owner.start_job). The optional extra
        /// callback adds job-only keys to the copy of the settings the job receives (SvcTab puts HsvcRevit.SvcIdsKey
        /// there). False when it could not start (busy ...); true also when it was queued behind a running quiet read.</summary>
        bool StartJob(FhaJob job, Action<FhaSettings> extra = null);

        /// <summary>Queue a quiet read (owner.start_quiet): when it is done callback(result, error) is called on the UI
        /// thread - result is what the job returned (null on error), error the failure text (null / empty when fine).
        /// False when the window is busy and the read was not started.</summary>
        bool StartQuiet(FhaJob job, Action<object, string> callback, string status = "Reading...");

        /// <summary>Gathers every control into the settings and writes them to disk (owner._save).</summary>
        void Save();

        /// <summary>The open tab's key: "fab", "fam", "floor" or "svc" (owner.tab).</summary>
        string Tab { get; }

        /// <summary>The text the "Copy debug" button copies (owner.last_debug); SvcTab sets it when the read fails.</summary>
        string LastDebug { get; set; }
    }

    // =====================================================================================================
    // Hanger Automation - the Hanger Service Type Assigner tab. Port of hsvc_ui.py.
    //
    // Lists every hanger in the project (read through the window's ExternalEvent as a quiet job), grouped by
    // the ticked fields, filtered by category and the house search, sorted by clicking the headings
    // (Shift+click adds a level). The rules live in HsvcCore; the Revit work in HsvcRevit.
    //
    // The window builds it after the layout is loaded and the fam tabs are made, then calls:
    //   svc = new SvcTab(this);   svc.Load(settings);   (after the window's chrome / drawer exist) svc.Wire();
    //   TabSvc shown -> svc.Shown();   F5 on the tab (not busy) -> svc.Scan();   in the window's gather -> svc.Gather(s);
    //   in its set-busy -> svc.SetBusy(busy);   when the window is idle again -> svc.RetryScan();
    //   after any job finished -> svc.AfterJob().
    // =====================================================================================================
    public class SvcTab
    {
        private static readonly KeyValuePair<string, string>[] ByChecks =
        {
            new KeyValuePair<string, string>("family", "ChkSvcByFamily"), new KeyValuePair<string, string>("type", "ChkSvcByType"),
            new KeyValuePair<string, string>("level", "ChkSvcByLevel"), new KeyValuePair<string, string>("comments", "ChkSvcByComments"),
        };
        private static readonly KeyValuePair<string, string>[] Heads =
        {
            new KeyValuePair<string, string>("family", "HdrSvcFamily"), new KeyValuePair<string, string>("type", "HdrSvcType"),
            new KeyValuePair<string, string>("level", "HdrSvcLevel"), new KeyValuePair<string, string>("comments", "HdrSvcComments"),
            new KeyValuePair<string, string>("count", "HdrSvcCount"),
        };
        /// <summary>null: the rest (matches the heading grid).</summary>
        private static readonly double?[] Widths = { 210.0, 170.0, 110.0, null, 60.0 };
        private static readonly string[] Buttons = { "BtnSvcReload", "BtnSvcApply", "BtnSvcReset3D" };
        private const double ListMin = 120.0, ListMax = 900.0;

        // ---- module-level helpers
        public static string SortText(IEnumerable<SortLevel> stack)
        {
            return string.Join(",", stack.Select(s => s.Field + ":" + (s.Desc ? "1" : "0")));
        }

        public static List<SortLevel> ParseSort(string text)
        {
            var o = new List<SortLevel>();
            foreach (string part in (text ?? "").Split(','))
            {
                int i = part.IndexOf(':');
                if (i >= 0)
                {
                    string f = part.Substring(0, i), d = part.Substring(i + 1);
                    if (HsvcCore.Sortable.Contains(f) && !o.Any(x => x.Field == f))
                        o.Add(new SortLevel(f, d.Trim() == "1"));
                }
            }
            return o.Take(HsvcCore.MaxSort).ToList();
        }

        public static double ListHeight(double h)
        {
            if (double.IsNaN(h)) h = 300.0;
            return Math.Max(ListMin, Math.Min(ListMax, h));
        }

        /// <summary>Python's "{0:g}": six significant digits, 300.0 -> "300".</summary>
        private static string G(double v)
        {
            return v.ToString("G6", CultureInfo.InvariantCulture).Replace("E+", "e+").Replace("E-", "e-");
        }

        /// <summary>s.get(key, dflt) on the settings dictionary (no fallback to the defaults).</summary>
        private static string Sget(FhaSettings s, string key, string dflt)
        {
            string v;
            return s != null && s.TryGetValue(key, out v) && v != null ? v : dflt;
        }

        // ---- state
        private readonly ISvcOwner o;
        public List<HangerRecord> Records = new List<HangerRecord>();
        public List<HangerGroup> Groups = new List<HangerGroup>();
        private List<Grid> rows = new List<Grid>();
        public List<SortLevel> Stack = new List<SortLevel>();
        public bool Loaded;
        public bool WantScan;
        public bool RescanAfterJob;
        private bool loading;
        public bool Busy;
        private double listGrow;

        public SvcTab(ISvcOwner owner)
        {
            o = owner;
            foreach (KeyValuePair<string, string> kv in HsvcCore.Categories) Cmb("CmbSvcCategory").Items.Add(kv.Value);
            foreach (KeyValuePair<string, string> kv in HsvcCore.Scopes) Cmb("CmbSvcScope").Items.Add(kv.Value);
        }

        public FrameworkElement C(string name) { return o.C(name); }
        private ComboBox Cmb(string name) { return (ComboBox)C(name); }
        private TextBox Txt(string name) { return (TextBox)C(name); }
        private TextBlock Tb(string name) { return (TextBlock)C(name); }
        private Button Btn(string name) { return (Button)C(name); }
        private CheckBox Chk(string name) { return (CheckBox)C(name); }
        private ListBox Lst() { return (ListBox)C("LstSvc"); }

        // ---- settings
        public void Load(FhaSettings s)
        {
            loading = true;
            try
            {
                var keys = HsvcCore.Categories.Select(k => k.Key).ToList();
                string cat = Sget(s, "svc_category", "all");
                Cmb("CmbSvcCategory").SelectedIndex = keys.Contains(cat) ? keys.IndexOf(cat) : 0;
                var scopes = HsvcCore.Scopes.Select(k => k.Key).ToList();
                string scope = Sget(s, "svc_scope", "selected");
                Cmb("CmbSvcScope").SelectedIndex = scopes.Contains(scope) ? scopes.IndexOf(scope) : 0;
                Txt("TxtSvcSearch").Text = Sget(s, "svc_search", "");
                Txt("TxtSvcTol").Text = Sget(s, "svc_tol", "150");
                List<string> by = Sget(s, "svc_by", "family,type,level,comments").Split(',').Where(b => HsvcCore.Fields.Contains(b)).ToList();
                foreach (KeyValuePair<string, string> fc in ByChecks) Chk(fc.Value).IsChecked = by.Contains(fc.Key);
                Stack = ParseSort(Sget(s, "svc_sort", ""));
                if (Stack.Count == 0) Stack = HsvcCore.DefaultStack(By());
                Lst().Height = ListHeight(FhaCore.ParseMm(Sget(s, "svc_list_h", "300"), 300.0));
                paramWanted = Sget(s, "svc_param", "Comments");
                FillParams(new List<string> { "Comments" });
            }
            finally
            {
                loading = false;
            }
        }

        public void Gather(FhaSettings s)
        {
            s["svc_category"] = Category();
            s["svc_scope"] = Scope();
            s["svc_search"] = Txt("TxtSvcSearch").Text ?? "";
            s["svc_tol"] = G(Math.Max(0.0, FhaCore.ParseMm(Txt("TxtSvcTol").Text, HsvcCore.RestTolMm)));
            s["svc_by"] = string.Join(",", By());
            s["svc_sort"] = SortText(Stack);
            s["svc_list_h"] = G(ListHeight(Lst().Height));
            s["svc_param"] = ParamChoice();
        }

        private string paramWanted = "Comments";

        /// <summary>The parameter chosen in "Write to parameter" (Comments when none).</summary>
        public string ParamChoice()
        {
            string v = Cmb("CmbSvcParam").SelectedItem as string;
            return string.IsNullOrEmpty(v) ? paramWanted : v;
        }

        /// <summary>Fill the list with the project's text instance parameters, keeping the chosen one even if it is not (yet) among them.</summary>
        private void FillParams(List<string> names)
        {
            var cb = Cmb("CmbSvcParam");
            string want = cb.Items.Count > 0 && cb.SelectedItem is string ? (string)cb.SelectedItem : paramWanted;
            var list = new List<string>(names ?? new List<string>());
            if (!list.Contains("Comments")) list.Insert(0, "Comments");
            if (!string.IsNullOrEmpty(want) && !list.Contains(want)) list.Add(want);
            bool was = loading;
            loading = true;
            try
            {
                cb.Items.Clear();
                foreach (string n in list) cb.Items.Add(n);
                int i = list.IndexOf(want);
                cb.SelectedIndex = i >= 0 ? i : 0;
            }
            finally
            {
                loading = was;
            }
        }

        public string Category()
        {
            int i = Cmb("CmbSvcCategory").SelectedIndex;
            return 0 <= i && i < HsvcCore.Categories.Count ? HsvcCore.Categories[i].Key : "all";
        }

        public string Scope()
        {
            int i = Cmb("CmbSvcScope").SelectedIndex;
            return 0 <= i && i < HsvcCore.Scopes.Count ? HsvcCore.Scopes[i].Key : "selected";
        }

        public List<string> By()
        {
            return ByChecks.Where(fc => Chk(fc.Value).IsChecked == true).Select(fc => fc.Key).ToList();
        }

        // ---- wiring
        public void Wire()
        {
            Btn("BtnSvcReload").Click += ReloadClick;
            Btn("BtnSvcShow3D").Click += ShowClick;
            Btn("BtnSvcReset3D").Click += ResetClick;
            Btn("BtnSvcApply").Click += ApplyClick;
            Cmb("CmbSvcParam").SelectionChanged += ParamChanged;
            Cmb("CmbSvcCategory").SelectionChanged += FilterSelectionChanged;
            Txt("TxtSvcSearch").TextChanged += FilterTextChanged;
            foreach (KeyValuePair<string, string> fc in ByChecks)
            {
                Chk(fc.Value).Checked += GroupChanged;
                Chk(fc.Value).Unchecked += GroupChanged;
            }
            foreach (KeyValuePair<string, string> fh in Heads)
                Btn(fh.Value).Click += HeadHandler(fh.Key);
            Lst().SelectionChanged += SelectionChangedHandler;
            ((Thumb)C("ThmSvcListSize")).DragDelta += ListDrag;
            ((Thumb)C("ThmSvcListSize")).DragCompleted += ListDropped;
        }

        /// <summary>A different "Write to parameter": save it, then read the hangers again so the list shows that parameter's values.</summary>
        private void ParamChanged(object sender, SelectionChangedEventArgs e)
        {
            if (loading) return;
            try
            {
                paramWanted = ParamChoice();
                o.Save();
                if (Loaded) Scan();
            }
            catch (Exception)
            {
            }
        }

        private RoutedEventHandler HeadHandler(string field)
        {
            return delegate (object sender, RoutedEventArgs e)
            {
                bool add;
                try { add = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift; }
                catch (Exception) { add = false; }
                SortBy(field, add);
            };
        }

        // ---- reading the model
        /// <summary>The tab came up: read the hangers the first time.</summary>
        public void Shown()
        {
            if (!Loaded) Scan();
        }

        public void Scan()
        {
            bool started = o.StartQuiet(HsvcRevit.ScanJob, Got, "Reading the hangers in the project...");
            WantScan = !started;
            if (started) Tb("TxtSvcCount").Text = "Reading the hangers...";
        }

        public void RetryScan()
        {
            if (WantScan && o.Tab == "svc") Scan();
        }

        /// <summary>A tool on this tab finished: read again so Comments show what was written.</summary>
        public void AfterJob()
        {
            if (RescanAfterJob)
            {
                RescanAfterJob = false;
                Scan();
            }
        }

        private void Got(object res, string err)
        {
            if (!string.IsNullOrEmpty(err))
            {
                Tb("TxtSvcCount").Text = "Could not read the hangers - see Copy debug";
                o.LastDebug = err;
                return;
            }
            IEnumerable<HangerRecord> recs = res as IEnumerable<HangerRecord>;
            Records = recs != null ? recs.ToList() : new List<HangerRecord>();
            Loaded = true;
            try { FillParams(HsvcRevit.ParamNames); }
            catch (Exception) { }
            Refill();
        }

        // ---- the list
        public List<HangerRecord> VisibleRecords()
        {
            string q = Txt("TxtSvcSearch").Text ?? "";
            string cat = Category();
            return Records.Where(r => HsvcCore.RecordMatches(r, q, cat)).ToList();
        }

        /// <summary>Filter, group and sort the records into rows; the rows picked before stay picked (by their group
        /// key) when keep is given (null: the rows picked now).</summary>
        public void Refill(HashSet<GroupKey> keep = null)
        {
            if (keep == null) keep = new HashSet<GroupKey>(SelectedIndices().Select(i => Groups[i].Key));
            List<HangerRecord> recs = VisibleRecords();
            Groups = HsvcCore.SortGroups(HsvcCore.GroupRecords(recs, By()), Stack);
            ListBox lst = Lst();
            loading = true;
            try
            {
                lst.Items.Clear();
                rows = new List<Grid>();
                foreach (HangerGroup g in Groups)
                {
                    Grid row = Row(g);
                    rows.Add(row);
                    lst.Items.Add(row);
                }
                for (int i = 0; i < Groups.Count; i++)
                {
                    if (keep.Contains(Groups[i].Key)) lst.SelectedItems.Add(rows[i]);
                }
            }
            catch (Exception) { }
            finally
            {
                loading = false;
            }
            Headings();
            UpdateSelection();
        }

        private Grid Row(HangerGroup g)
        {
            var grid = new Grid();
            foreach (double? w in Widths)
            {
                var cd = new ColumnDefinition();
                cd.Width = w == null ? new GridLength(1.0, GridUnitType.Star) : new GridLength(w.Value);
                grid.ColumnDefinitions.Add(cd);
            }
            var values = HsvcCore.Fields.Select(f => g[f]).ToList();
            values.Add(g.Count.ToString(CultureInfo.InvariantCulture));
            for (int i = 0; i < values.Count; i++)
            {
                string v = values[i];
                var tb = new TextBlock();
                tb.Text = v;
                tb.TextTrimming = TextTrimming.CharacterEllipsis;
                tb.VerticalAlignment = VerticalAlignment.Center;
                tb.Margin = new Thickness(0, 0, 8, 0);
                tb.ToolTip = !string.IsNullOrEmpty(v) ? v : null;
                if (v == HsvcCore.Mixed) tb.SetResourceReference(TextBlock.ForegroundProperty, "MutedBrush");
                if (i == values.Count - 1) tb.FontWeight = FontWeights.SemiBold;
                Grid.SetColumn(tb, i);
                grid.Children.Add(tb);
            }
            return grid;
        }

        private void Headings()
        {
            foreach (KeyValuePair<string, string> fh in Heads)
            {
                Button b = Btn(fh.Value);
                b.Content = HsvcCore.HeadingText(fh.Key, Stack);
                FhaUi.SetStyle(b, Stack.Any(x => x.Field == fh.Key) ? "ColHeadOn" : "ColHead");
            }
        }

        public void SortBy(string field, bool add = false)
        {
            Stack = HsvcCore.ClickSort(Stack, field, add);
            Refill();
            o.Save();
        }

        public List<int> SelectedIndices()
        {
            List<object> picked;
            try { picked = Lst().SelectedItems.Cast<object>().ToList(); }
            catch (Exception) { return new List<int>(); }
            var o2 = new List<int>();
            foreach (object item in picked)
            {
                for (int i = 0; i < rows.Count; i++)
                {
                    if (ReferenceEquals(rows[i], item))
                    {
                        o2.Add(i);
                        break;
                    }
                }
            }
            o2.Sort();
            return o2;
        }

        public List<long> IdsFor(string scope)
        {
            if (scope == "all") return HsvcCore.IdsOf(Groups, Enumerable.Range(0, Groups.Count));
            return HsvcCore.IdsOf(Groups, SelectedIndices());
        }

        // ---- events
        private void FilterSelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (!loading) Refill();
        }

        private void FilterTextChanged(object sender, TextChangedEventArgs e)
        {
            if (!loading) Refill();
        }

        private void GroupChanged(object sender, RoutedEventArgs e)
        {
            if (loading) return;
            List<string> by = By();
            Stack = Stack.Where(x => by.Contains(x.Field) || x.Field == "count").ToList();
            if (Stack.Count == 0) Stack = HsvcCore.DefaultStack(By());
            Refill(new HashSet<GroupKey>());
        }

        private void SelectionChangedHandler(object sender, SelectionChangedEventArgs e)
        {
            UpdateSelection();
        }

        /// <summary>Python _sel_changed(None, None): the Show button and the count line follow the selection.</summary>
        private void UpdateSelection()
        {
            if (loading) return;
            int n = IdsFor("selected").Count;
            try
            {
                Btn("BtnSvcShow3D").IsEnabled = n > 0 && !Busy;
                Tb("TxtSvcCount").Text = Loaded ? HsvcCore.Summary(Records, Groups, n) : "Reading the hangers...";
            }
            catch (Exception) { }
        }

        private void ReloadClick(object sender, RoutedEventArgs e)
        {
            Scan();
        }

        private void Start(FhaJob job, List<long> ids, bool rescan)
        {
            Action<FhaSettings> extra = delegate (FhaSettings s) { s[HsvcRevit.SvcIdsKey] = HsvcRevit.EncodeIds(ids); };
            if (o.StartJob(job, extra)) RescanAfterJob = rescan;
        }

        private void ShowClick(object sender, RoutedEventArgs e)
        {
            List<long> ids = IdsFor("selected");
            if (ids.Count == 0)
            {
                o.Status("Select one or more rows first");
                return;
            }
            Start(HsvcRevit.JobShow3d, ids, false);
        }

        private void ResetClick(object sender, RoutedEventArgs e)
        {
            Start(HsvcRevit.JobReset3d, new List<long>(), false);
        }

        private void ApplyClick(object sender, RoutedEventArgs e)
        {
            string scope = Scope();
            List<long> ids = IdsFor(scope);
            if (ids.Count == 0)
            {
                o.Status("Nothing to apply to - select rows, or choose \"Every row in the list\"");
                return;
            }
            Start(HsvcRevit.JobApply, ids, true);
        }

        public void SetBusy(bool busy)
        {
            Busy = busy;
            foreach (string n in Buttons)
            {
                try { Btn(n).IsEnabled = !busy; }
                catch (Exception) { }
            }
            UpdateSelection();
        }

        // ---- the list's grip
        private void ListDrag(object sender, DragDeltaEventArgs e)
        {
            try
            {
                ListBox lst = Lst();
                double old = lst.Height;
                double nw = ListHeight(old + e.VerticalChange);
                if (Math.Abs(nw - old) > 0.1)
                {
                    lst.Height = nw;
                    listGrow += nw - old;
                }
            }
            catch (Exception) { }
        }

        private void ListDropped(object sender, DragCompletedEventArgs e)
        {
            double grow = listGrow;
            listGrow = 0.0;
            try
            {
                if (Math.Abs(grow) > 0.5) o.ResizeForFold(grow);
            }
            catch (Exception) { }
        }
    }
}
