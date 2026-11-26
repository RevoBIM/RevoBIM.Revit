using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Threading;
using RevoBIM.Tools.ViewManager;

namespace RevoBIM.UI.ViewManager
{
    /// <summary>
    /// What the View Manager and View Range tabs share: the toolbar (parameters, group, open/close all, clear sort, refresh,
    /// keyword search), the grid, the status line with Revert and Apply, and the add-a-column picker. A tab supplies its columns,
    /// how its rows are read and how its edits are written.
    /// </summary>
    internal abstract class VmGridTab : IVmBuilderHost
    {
        protected readonly VmWindow Owner;
        protected readonly string Prefix;
        protected readonly VmCore.EditStore Edits = new VmCore.EditStore();
        protected readonly VmTableHost Host;
        protected List<VmCore.Field> Fields;
        protected List<VmCore.RefRow> Rows = new List<VmCore.RefRow>();
        protected bool Loaded;
        private readonly string settingsKey;
        private readonly DispatcherTimer searchTimer;
        private List<VmRevit.ParamName> colNames = new List<VmRevit.ParamName>();
        private VmBuilderWindow builder;

        protected readonly Window Win;
        protected readonly Button BtnApply, BtnRevert, BtnParams, BtnGroup;
        protected readonly TextBlock Summary, GroupText;
        protected readonly TextBox SearchBox, ColSearch;
        protected readonly FrameworkElement Overlay, ColPanel;
        protected readonly TextBlock ColNote;
        protected readonly StackPanel ColList;

        public VmCore.EditStore Store { get { return Edits; } }

        protected T Find<T>(string suffix) where T : class
        {
            return Win.FindName(Prefix + suffix) as T;
        }

        protected VmGridTab(VmWindow owner, string prefix, string settingsKey)
        {
            Owner = owner;
            Prefix = prefix;
            this.settingsKey = settingsKey;
            Win = owner.Window;

            BtnApply = Find<Button>("Apply");
            BtnRevert = Find<Button>("Revert");
            BtnParams = Find<Button>("Params");
            BtnGroup = Find<Button>("Group");
            Summary = Find<TextBlock>("Summary");
            GroupText = Find<TextBlock>("GroupText");
            SearchBox = Find<TextBox>("Search");
            ColSearch = Find<TextBox>("ColSearch");
            Overlay = Find<FrameworkElement>("Overlay");
            ColPanel = Find<FrameworkElement>("ColPanel");
            ColNote = Find<TextBlock>("ColNote");
            ColList = Find<StackPanel>("ColList");

            Host = new VmTableHost(Win, Find<DataGrid>("Grid"), Edits, Say);
            Host.OnPlus = OpenColumns;
            Host.OnRemove = RemoveColumn;
            Host.OnChanged = () => Guard("changed", () =>
            {
                UpdateState();
                Say(Edits.Edits.Count + " edit(s) staged - press Apply to Revit to write them.", false);
            });
            Host.OnSelection = () => Guard("selection", UpdateState);
            Host.OnShownChanged = () => { try { UpdateState(); } catch (Exception) { } };

            searchTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(260) };
            searchTimer.Tick += (s, e) =>
            {
                searchTimer.Stop();
                Guard("search", () =>
                {
                    Host.GlobalSearch = SearchBox.Text ?? "";
                    if (Loaded) Host.Fill();
                });
            };
            SearchBox.TextChanged += (s, e) => { searchTimer.Stop(); searchTimer.Start(); };
            BtnParams.Click += (s, e) => Guard("parameters", OpenColumns);
            BtnGroup.Click += (s, e) => Guard("group", ToggleGroup);
            Find<Button>("Expand").Click += (s, e) => Guard("open all", () => Host.ExpandAll(true));
            Find<Button>("Collapse").Click += (s, e) => Guard("close all", () => Host.ExpandAll(false));
            Find<Button>("ClearSort").Click += (s, e) => Guard("clear sort", () => { if (Loaded) Host.ClearSort(); });
            Find<Button>("Refresh").Click += (s, e) => Guard("refresh", () => { if (!Owner.Busy) Reload(); });
            BtnApply.Click += (s, e) => Guard("apply", Apply);
            BtnRevert.Click += (s, e) => Guard("revert", Revert);
            Find<Button>("ColClose").Click += (s, e) => Guard("close", HidePanels);
            ColSearch.TextChanged += (s, e) => Guard("col search", BuildColumnList);
            Fields = SavedFields();
        }

        // ---------------------------------------------------------------- what a tab supplies --

        protected abstract IList<VmCore.Field> DefaultFields { get; }
        /// <summary>Built-in columns the picker offers besides parameters.</summary>
        protected virtual IList<VmCore.Field> OfferedFields { get { return new VmCore.Field[0]; } }
        protected abstract List<VmCore.RefRow> ReadRows(List<string> paramNames);
        protected abstract void ApplyItems(List<VmCore.EditItem> items, out List<VmCore.CellKey> applied, out Dictionary<VmCore.CellKey, string> failed);
        protected abstract string SummaryText(int shown, int total, int ticked, int edits);

        // ---------------------------------------------------------------- small things --

        protected void Guard(string name, Action a) { Owner.Guard(name, a); }

        protected void Say(string message, bool error)
        {
            Owner.SetStatus(message, error);
        }

        protected bool IsDefault(string key) { return DefaultFields.Any(d => d.Key == key); }

        private VmCore.Field FieldFromKey(string key)
        {
            foreach (VmCore.Field f in DefaultFields) if (f.Key == key) return f;
            foreach (VmCore.Field f in OfferedFields) if (f.Key == key) return f;
            if (key.StartsWith(VmCore.ParamPrefix) && key.Length > VmCore.ParamPrefix.Length) return VmCore.ParamField(key.Substring(VmCore.ParamPrefix.Length));
            return null;
        }

        private List<VmCore.Field> SavedFields()
        {
            var list = new List<VmCore.Field>(DefaultFields);
            var have = new HashSet<string>(list.Select(f => f.Key));
            foreach (string key in (VmCore.Get(settingsKey) ?? "").Split('|'))
            {
                if (key.Length == 0) continue;
                VmCore.Field field = FieldFromKey(key);
                if (field != null && have.Add(field.Key)) list.Add(field);
            }
            return list;
        }

        private void SaveFields()
        {
            VmCore.Settings[settingsKey] = string.Join("|", Fields.Where(f => !IsDefault(f.Key)).Select(f => f.Key.Replace("|", "/")));
            string note;
            VmCore.SaveSettings(out note);
        }

        protected List<string> ParamNames()
        {
            return Fields.Where(f => f.Kind == "param").Select(f => f.Param).ToList();
        }

        // ---------------------------------------------------------------- loading --

        public void Activate()
        {
            if (!Loaded) Reload();
            else UpdateState();
        }

        /// <summary>Marks the rows stale, so the next time the tab is shown it reads the model again.</summary>
        public void Invalidate() { Loaded = false; }

        public void Reload()
        {
            Rows = ReadRows(ParamNames());
            Edits.Load(Rows);
            Loaded = true;
            Rebuild();
            Say("Read " + Rows.Count + " view(s).", false);
        }

        /// <summary>Rebuilds the columns (they may have changed) over the rows already read.</summary>
        protected void Rebuild()
        {
            Host.Fields = Fields;
            Host.Removable = new HashSet<string>(Fields.Where(f => !IsDefault(f.Key)).Select(f => f.Key));
            Host.TypeOptions = VmCore.TypeOptions(Rows);
            if (Host.TypeName != null && !Host.TypeOptions.Any(o => o.Name == Host.TypeName)) Host.TypeName = null;
            Host.BuildColumns(Rows);
        }

        // ---------------------------------------------------------------- state --

        public virtual void UpdateState()
        {
            bool busy = Owner.Busy;
            int edits = Edits.Edits.Count;
            BtnApply.IsEnabled = edits > 0 && !busy;
            BtnRevert.IsEnabled = edits > 0 && !busy;
            BtnApply.Content = edits > 0 ? "Apply to Revit (" + edits + ")" : "Apply to Revit";
            Summary.Text = SummaryText(Host.Shown.Count, Rows.Count, Host.CheckedIds().Count, edits);
            AfterState(busy);
        }

        protected virtual void AfterState(bool busy) { }

        private void ToggleGroup()
        {
            if (!Loaded) return;
            Host.SetGrouping(!Host.Grouping);
            GroupText.Text = Host.Grouping ? "Grouped" : "Group";
            GroupText.Foreground = (Brush)Win.Resources[Host.Grouping ? "Orange" : "Text"];
            Say(Host.Grouping
                ? "Grouped by " + (Host.Sort.Count > 0 ? Fields.First(f => f.Key == Host.Sort[0].Key).Label : Fields[0].Label) + " - click a heading to open or close it."
                : "Grouping off.", false);
        }

        // ---------------------------------------------------------------- columns --

        private void OpenColumns()
        {
            Guard("columns", () =>
            {
                if (!Loaded) return;
                Say("Reading the parameters on these views...", false);
                colNames = VmRevit.ParameterNames(Owner.Doc, Rows, Host.TypeName);
                ColNote.Text = "Parameters on " + (Host.TypeName != null ? VmCore.ViewTypeLabel(Host.TypeName) + " views" : "all views")
                    + ". Editable ones can be changed here; read-only ones are shown for reference. Every column can be sorted, grouped and searched.";
                ColSearch.Text = "";
                BuildColumnList();
                ShowPanel(ColPanel);
                Say("Pick a column to add.", false);
            });
        }

        private void BuildColumnList()
        {
            ColList.Children.Clear();
            string[] words = (ColSearch.Text ?? "").ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            var have = new HashSet<string>(Fields.Select(f => f.Key));
            var entries = new List<Tuple<string, VmCore.Field, bool, string>>();
            foreach (VmCore.Field f in OfferedFields) entries.Add(Tuple.Create(f.Label, f, false, "built in"));
            foreach (VmRevit.ParamName p in colNames)
                entries.Add(Tuple.Create(p.Name, VmCore.ParamField(p.Name), p.Editable, p.Editable ? "" : "read-only"));
            int count = 0;
            foreach (var entry in entries)
            {
                if (have.Contains(entry.Item2.Key)) continue;
                if (words.Length > 0 && !words.All(w => entry.Item1.ToLowerInvariant().Contains(w))) continue;
                var button = new Button { Style = (Style)Win.FindResource("Flat"), HorizontalContentAlignment = HorizontalAlignment.Left, Tag = entry.Item2.Key };
                bool muted = !entry.Item3 && entry.Item4.Length > 0;
                button.Content = new TextBlock
                {
                    Width = 380,
                    TextAlignment = TextAlignment.Left,
                    Text = entry.Item1 + (entry.Item4.Length > 0 ? "    (" + entry.Item4 + ")" : ""),
                    Foreground = (Brush)Win.Resources[muted ? "Muted" : "Text"],
                };
                button.Click += (s, e) => Guard("pick column", () => PickColumn((string)((Button)s).Tag));
                ColList.Children.Add(button);
                if (++count >= 400) break;
            }
        }

        private void PickColumn(string key)
        {
            VmCore.Field field = FieldFromKey(key);
            if (field == null) return;
            HidePanels();
            if (Fields.Any(f => f.Key == field.Key)) return;
            Fields.Add(field);
            SaveFields();
            if (field.Kind == "param") Reload();
            else Rebuild();
            Say("Added the '" + field.Label + "' column.", false);
        }

        private void RemoveColumn(string key)
        {
            Guard("remove column", () =>
            {
                if (IsDefault(key)) return;
                Fields = Fields.Where(f => f.Key != key).ToList();
                foreach (VmCore.CellKey k in Edits.Edits.Keys.Where(k => k.Key == key).ToList()) Edits.Edits.Remove(k);
                Host.Sort.RemoveAll(s => s.Key == key);
                Host.ColumnFilters.Remove(key);
                SaveFields();
                Rebuild();
            });
        }

        // ---------------------------------------------------------------- panels --

        protected virtual IEnumerable<FrameworkElement> AllPanels { get { return new[] { ColPanel }; } }

        protected void ShowPanel(FrameworkElement panel)
        {
            foreach (FrameworkElement p in AllPanels) p.Visibility = ReferenceEquals(p, panel) ? Visibility.Visible : Visibility.Collapsed;
            Overlay.Visibility = Visibility.Visible;
        }

        protected void HidePanels()
        {
            Overlay.Visibility = Visibility.Collapsed;
            foreach (FrameworkElement p in AllPanels) p.Visibility = Visibility.Collapsed;
        }

        // ---------------------------------------------------------------- writing --

        public void Apply()
        {
            if (Owner.Busy) return;
            Dictionary<VmCore.CellKey, string> clashes = Edits.Conflicts();
            if (clashes.Count > 0)
            {
                Host.Sync(false);
                Say(clashes.Count + " edit(s) would clash (red) - fix them first.", true);
                return;
            }
            List<VmCore.EditItem> items = Edits.Items();
            if (items.Count == 0)
            {
                Say("Nothing is staged.", false);
                return;
            }
            Owner.LogEnvironment(Prefix == "Rg" ? "View range - " + items.Count + " edit(s)" : "View Manager tab - " + items.Count + " edit(s)");
            Host.Failed = new Dictionary<VmCore.CellKey, string>();
            Owner.Queue(app =>
            {
                List<VmCore.CellKey> applied;
                Dictionary<VmCore.CellKey, string> failed;
                ApplyItems(items, out applied, out failed);
                Owner.BackOnUi(() => AfterApply(items.Count, applied, failed));
            });
        }

        private void AfterApply(int count, List<VmCore.CellKey> applied, Dictionary<VmCore.CellKey, string> failed)
        {
            Host.Failed = new Dictionary<VmCore.CellKey, string>(failed);
            try
            {
                Rows = ReadRows(ParamNames());
                Edits.Load(Rows);
                Rebuild();
            }
            catch (Exception ex)
            {
                Owner.Log.Add("re-read failed: " + VmCore.Describe(ex));
            }
            Owner.InvalidateGridTabs(this);
            string message;
            if (failed.Count > 0)
            {
                VmCore.CellKey first = failed.Keys.OrderBy(k => k.View).ThenBy(k => k.Key, StringComparer.Ordinal).First();
                message = "Wrote " + applied.Count + " of " + count + " edit(s). " + failed.Count + " refused (red) - " + failed[first];
            }
            else message = "Wrote " + applied.Count + " edit(s) to the model.";
            Owner.Finish(message, failed.Count > 0, failed.Count > 0);
        }

        public void Revert()
        {
            Edits.Revert();
            Host.Failed = new Dictionary<VmCore.CellKey, string>();
            Host.Fill();
            Say("Staged edits cleared.", false);
        }

        // ---------------------------------------------------------------- the builders (Views tab) --

        public void BuilderClosed() { builder = null; }

        public void AcceptBuilder(List<VmCore.EditItem> changes)
        {
            int staged = 0;
            foreach (VmCore.EditItem c in changes)
            {
                string held, message;
                if (Edits.Stage(c.ViewId, c.Key, c.Text, out held, out message)) staged++;
            }
            Host.Fill();
            Say(staged + " edit(s) staged from the builder. Press Apply to Revit to write them.", false);
        }

        protected void OpenBuilder(string target)
        {
            if (builder != null)
            {
                try
                {
                    builder.Activate();
                    return;
                }
                catch (Exception) { builder = null; }
            }
            var ticked = new HashSet<long>(Host.CheckedIds());
            List<VmCore.RefRow> chosen = Host.Shown.Where(r => ticked.Contains(r.ViewId)).ToList();
            if (chosen.Count == 0)
            {
                Say("Tick the views to rewrite first.", true);
                return;
            }
            builder = new VmBuilderWindow(this, Owner, chosen, target);
            builder.Show();
        }

        // ---------------------------------------------------------------- a drop-down menu --

        /// <summary>A small menu under a button, in the window's own colours (a stock ContextMenu would be white in a dark window).</summary>
        protected void DropMenu(Button anchor, params KeyValuePair<string, Action>[] items)
        {
            var stack = new StackPanel { Margin = new Thickness(3) };
            var popup = new Popup
            {
                PlacementTarget = anchor,
                Placement = PlacementMode.Bottom,
                StaysOpen = false,
                AllowsTransparency = true,
                PopupAnimation = PopupAnimation.Fade,
            };
            foreach (KeyValuePair<string, Action> item in items)
            {
                Action run = item.Value;
                var b = new Button
                {
                    Style = (Style)Win.FindResource("Flat"),
                    HorizontalContentAlignment = HorizontalAlignment.Left,
                    Content = new TextBlock { Text = item.Key, MinWidth = 230, TextAlignment = TextAlignment.Left },
                };
                b.Click += (s, e) =>
                {
                    popup.IsOpen = false;
                    Guard("menu", run);
                };
                stack.Children.Add(b);
            }
            popup.Child = new Border
            {
                Background = (Brush)Win.Resources["Panel"],
                BorderBrush = (Brush)Win.Resources["Line"],
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(3),
                Child = stack,
            };
            popup.IsOpen = true;
        }

        protected static KeyValuePair<string, Action> Item(string text, Action run)
        {
            return new KeyValuePair<string, Action>(text, run);
        }
    }
}
