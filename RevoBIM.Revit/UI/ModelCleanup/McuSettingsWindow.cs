using System;
using System.Collections.Generic;
using System.Data;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;
using Microsoft.Win32;
using RevoBIM.Tools.ModelCleanup;
using static RevoBIM.Tools.ModelCleanup.McuCore;
using Path = System.IO.Path;

namespace RevoBIM.UI.ModelCleanup
{
    /// <summary>
    /// One "to retain" list: rows grouped as the project browser shows them, a search box, a tick per item
    /// and a part-tickable tick per folder.
    /// </summary>
    internal sealed class McuRetainList
    {
        private const int Indent = 18;
        private readonly McuSettingsWindow owner;
        private readonly McuFinder find;
        private readonly string prefix, noun;
        private List<McuRetainItem> items = new List<McuRetainItem>();
        public HashSet<string> Retained = new HashSet<string>();
        private HashSet<string> collapsed = new HashSet<string>();
        private bool onlyRetained;
        private Dictionary<string, CheckBox> itemChecks = new Dictionary<string, CheckBox>();
        private Dictionary<string, (CheckBox Check, List<string> Children)> headerChecks =
            new Dictionary<string, (CheckBox, List<string>)>();
        private string organisation = "";
        private readonly DispatcherTimer timer;

        public McuRetainList(McuSettingsWindow owner, string prefix, string noun)
        {
            this.owner = owner;
            find = owner.Find;
            this.prefix = prefix;
            this.noun = noun;
            Window window = owner.Window;
            find.Button(prefix + "AllButton").Click += McuUi.Safe(window, (s, a) => SetKeys(ShownKeys(), true), owner.Theme, prefix + " all");
            find.Button(prefix + "NoneButton").Click += McuUi.Safe(window, (s, a) => SetKeys(ShownKeys(), false), owner.Theme, prefix + " none");
            find.Button(prefix + "CollapseButton").Click += McuUi.Safe(window, (s, a) => OnCollapse(), owner.Theme, prefix + " collapse");
            find.Button(prefix + "IsolateButton").Click += McuUi.Safe(window, (s, a) => OnIsolate(), owner.Theme, prefix + " isolate");
            find.Box(prefix + "SearchBox").TextChanged += (s, a) => { timer.Stop(); timer.Start(); };
            timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(220) };
            timer.Tick += McuUi.SafeTick(window, () => { timer.Stop(); Render(); }, owner.Theme, prefix + " search");
        }

        public void Load(List<McuRetainItem> newItems, string newOrganisation, IEnumerable<string> retained)
        {
            items = newItems;
            organisation = newOrganisation;
            Retained = new HashSet<string>(retained);
            Render();
        }

        public List<string> Keys()
        {
            var keys = Retained.ToList();
            keys.Sort(NaturalCompare);
            return keys;
        }

        private string Search() { return find.Box(prefix + "SearchBox").Text; }

        public void Render()
        {
            ListBox listbox = find.Get<ListBox>(prefix + "List");
            listbox.Items.Clear();
            itemChecks = new Dictionary<string, CheckBox>();
            headerChecks = new Dictionary<string, (CheckBox, List<string>)>();
            foreach (McuRetainRow row in RetainRows(items, Search(), Retained, collapsed, onlyRetained))
                listbox.Items.Add(row.IsHeader ? Header(row) : Item(row));
            UpdateSummary();
        }

        private ListBoxItem Header(McuRetainRow row)
        {
            var item = new ListBoxItem();
            var panel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Margin = new Thickness(Indent * row.Level, row.Level == 0 ? 4 : 1, 0, 1),
            };
            var arrow = new Button
            {
                Width = 18, Height = 18, Padding = new Thickness(0), MinHeight = 0, Margin = new Thickness(0, 0, 4, 0),
            };
            arrow.SetResourceReference(FrameworkElement.StyleProperty, "WindowButton");
            var glyph = new System.Windows.Shapes.Path
            {
                Data = Geometry.Parse(row.Collapsed ? "M 0,0 L 4,4 L 0,8" : "M 0,0 L 4,4 L 8,0"),
                StrokeThickness = 1.6,
            };
            glyph.SetResourceReference(Shape.StrokeProperty, "MutedBrush");
            arrow.Content = glyph;
            string path = row.Path;
            arrow.Click += McuUi.Safe(owner.Window, (s, a) =>
            {
                if (!collapsed.Add(path)) collapsed.Remove(path);
                Render();
            }, owner.Theme, "folder");
            var check = new CheckBox
            {
                IsChecked = row.State == "all" ? true : row.State == "none" ? (bool?)false : null,
                Margin = new Thickness(0),
            };
            var label = new TextBlock { Text = row.Label + "  (" + row.Count + ")", FontWeight = FontWeights.SemiBold };
            label.SetResourceReference(TextBlock.ForegroundProperty, row.Level == 0 ? "BlueBrush" : "OrangeBrush");
            check.Content = label;
            var children = row.Children;
            check.Click += McuUi.Safe(owner.Window, (s, a) => SetKeys(children, ((CheckBox)s).IsChecked == true), owner.Theme, "folder tick");
            panel.Children.Add(arrow);
            panel.Children.Add(check);
            item.Content = panel;
            item.Tag = "header";
            headerChecks[row.Path] = (check, row.Children);
            return item;
        }

        private ListBoxItem Item(McuRetainRow row)
        {
            var item = new ListBoxItem();
            var check = new CheckBox
            {
                Content = row.Label, IsChecked = row.Checked, Margin = new Thickness(Indent * row.Level + 22, 0, 0, 0),
            };
            string key = row.Key;
            check.Click += McuUi.Safe(owner.Window, (s, a) =>
            {
                if (((CheckBox)s).IsChecked == true) Retained.Add(key); else Retained.Remove(key);
                RefreshHeaders();
            }, owner.Theme, "tick");
            item.Content = check;
            item.Tag = row.Key;
            itemChecks[row.Key] = check;
            return item;
        }

        private void SetKeys(IEnumerable<string> keys, bool on)
        {
            foreach (string key in keys)
            {
                if (on) Retained.Add(key); else Retained.Remove(key);
                CheckBox check;
                if (itemChecks.TryGetValue(key, out check)) check.IsChecked = on;
            }
            RefreshHeaders();
        }

        private void RefreshHeaders()
        {
            foreach (var entry in headerChecks.Values)
            {
                string state = GroupState(entry.Children, Retained);
                entry.Check.IsChecked = state == "all" ? true : state == "none" ? (bool?)false : null;
            }
            UpdateSummary();
        }

        private void UpdateSummary()
        {
            string text = RetainSummary(items, Retained, noun) + ". Browser organisation: " +
                          (organisation.Length > 0 ? organisation : "type only") + ".";
            if (onlyRetained) text += " Showing retained only - anything you untick stays listed until you show all.";
            find.Text(prefix + "SummaryText").Text = text;
        }

        private List<string> ShownKeys()
        {
            return RetainRows(items, Search(), Retained, null, onlyRetained).Where(r => !r.IsHeader).Select(r => r.Key).ToList();
        }

        /// <summary>Show only what is ticked. The list is taken once, so unticking something here leaves it in place.</summary>
        private void OnIsolate()
        {
            onlyRetained = !onlyRetained;
            Button button = find.Button(prefix + "IsolateButton");
            button.Content = onlyRetained ? "Show all" : "Retained only";
            button.SetResourceReference(FrameworkElement.StyleProperty, onlyRetained ? "OrangeButton" : "BaseButton");
            Render();
        }

        private void OnCollapse()
        {
            Button button = find.Button(prefix + "CollapseButton");
            if (collapsed.Count > 0)
            {
                collapsed = new HashSet<string>();
                button.Content = "Collapse all";
            }
            else
            {
                collapsed = new HashSet<string>(AllFolderPaths(items).Where(p => !p.Contains("\x1f")));
                button.Content = "Expand all";
            }
            Render();
        }
    }

    /// <summary>The NWC tab: export settings, and the 3D views with one primary.</summary>
    internal sealed class McuNwcPanel
    {
        private readonly McuSettingsWindow owner;
        private readonly McuFinder find;
        private List<string> names = new List<string>();
        private List<string> views = new List<string>();
        private string primary = "";
        private bool onlySelected;
        private bool read;
        private Dictionary<string, (CheckBox Check, RadioButton Radio)> rows = new Dictionary<string, (CheckBox, RadioButton)>();
        private string stem = "Model";
        private readonly DispatcherTimer timer;

        public McuNwcPanel(McuSettingsWindow owner)
        {
            this.owner = owner;
            find = owner.Find;
            Window window = owner.Window;
            foreach (var option in McuNwc.Coordinates) find.Combo("NwcCoordinatesCombo").Items.Add(option.Label);
            foreach (var option in McuNwc.Parameters) find.Combo("NwcParametersCombo").Items.Add(option.Label);
            find.Button("NwcAllButton").Click += McuUi.Safe(window, (s, a) =>
            {
                (views, primary) = McuNwc.Normalise(views.Concat(Shown()), primary);
                SyncRows();
            }, owner.Theme, "NWC all");
            find.Button("NwcNoneButton").Click += McuUi.Safe(window, (s, a) =>
            {
                foreach (string name in Shown()) (views, primary) = McuNwc.Untick(views, primary, name);
                SyncRows();
            }, owner.Theme, "NWC none");
            find.Button("NwcIsolateButton").Click += McuUi.Safe(window, (s, a) =>
            {
                onlySelected = !onlySelected;
                Button button = find.Button("NwcIsolateButton");
                button.Content = onlySelected ? "Show all" : "Ticked only";
                button.SetResourceReference(FrameworkElement.StyleProperty, onlySelected ? "OrangeButton" : "BaseButton");
                Render();
            }, owner.Theme, "NWC ticked only");
            foreach (string name in new[] { "ExportNwcCheck", "NwcDefaultsRadio", "NwcCustomRadio" })
                ((System.Windows.Controls.Primitives.ToggleButton)find[name]).Click +=
                    McuUi.Safe(window, (s, a) => UpdateEnabled(), owner.Theme, "NWC enable");
            find.Box("NwcSearchBox").TextChanged += (s, a) => { timer.Stop(); timer.Start(); };
            timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(220) };
            timer.Tick += McuUi.SafeTick(window, () => { timer.Stop(); Render(); }, owner.Theme, "NWC search");
        }

        public void Push(Dictionary<string, string> values)
        {
            find.Check("ExportNwcCheck").IsChecked = AsBool(values.Get("export_nwc"));
            bool custom = values.Get("nwc_source") != McuNwc.SourceDefaults;
            Radio("NwcCustomRadio").IsChecked = custom;
            Radio("NwcDefaultsRadio").IsChecked = !custom;
            find.Combo("NwcCoordinatesCombo").SelectedIndex = McuNwc.Coordinates.FindIndex(
                o => o.Key == McuNwc.Choice(values.Get("nwc_coordinates"), McuNwc.Coordinates, "shared"));
            find.Combo("NwcParametersCombo").SelectedIndex = McuNwc.Parameters.FindIndex(
                o => o.Key == McuNwc.Choice(values.Get("nwc_parameters"), McuNwc.Parameters, "all"));
            foreach (var option in NwcBoolOptions)
                find.Check("NwcOpt_" + option.Key).IsChecked = AsBool(values.Get(option.Key, option.Default), option.Default == "1");
            find.Box("NwcFacetingBox").Text = values.Get("nwc_faceting");
            (views, primary) = McuNwc.Selection(values);
            UpdateEnabled();
            if (read) Render();
        }

        private RadioButton Radio(string name) { return find.Get<RadioButton>(name); }

        public Dictionary<string, string> Pull(Dictionary<string, string> values)
        {
            values["export_nwc"] = BoolText(find.Check("ExportNwcCheck").IsChecked == true);
            values["nwc_source"] = Radio("NwcDefaultsRadio").IsChecked == true ? McuNwc.SourceDefaults : McuNwc.SourceCustom;
            int coords = find.Combo("NwcCoordinatesCombo").SelectedIndex;
            int parameters = find.Combo("NwcParametersCombo").SelectedIndex;
            values["nwc_coordinates"] = coords >= 0 ? McuNwc.Coordinates[coords].Key : "shared";
            values["nwc_parameters"] = parameters >= 0 ? McuNwc.Parameters[parameters].Key : "all";
            foreach (var option in NwcBoolOptions)
                values[option.Key] = BoolText(find.Check("NwcOpt_" + option.Key).IsChecked == true);
            values["nwc_faceting"] = McuNwc.Faceting(find.Box("NwcFacetingBox").Text).ToString("0.###", Inv);
            values["nwc_views"] = JoinRetain(views);
            values["nwc_primary"] = primary;
            return values;
        }

        private void UpdateEnabled()
        {
            bool on = find.Check("ExportNwcCheck").IsChecked == true;
            find["NwcSettingsPanel"].IsEnabled = on;
            find["NwcCustomPanel"].IsEnabled = on && Radio("NwcCustomRadio").IsChecked == true;
            // the views stay pickable while export is off, so they can be set up first
            find["NwcViewList"].IsEnabled = true;
        }

        public void Load(Autodesk.Revit.DB.Document doc)
        {
            names = McuModel.ThreeDViews(doc).Keys.ToList();
            names.Sort(NaturalCompare);
            stem = ModelStem(McuModel.ModelTitle(doc));
            if (stem.Length == 0) stem = "Model";
            bool available = McuModel.NwcAvailable();
            TextBlock text = find.Text("NwcAvailableText");
            text.Text = available ? "Navisworks exporter found" : "Navisworks exporter not installed";
            text.SetResourceReference(TextBlock.ForegroundProperty, available ? "GreenBrush" : "RedBrush");
            read = true;
            Render();
        }

        private string Search() { return find.Box("NwcSearchBox").Text; }

        private List<string> Shown() { return McuNwc.Rows(names, Search(), views, onlySelected); }

        private void Render()
        {
            ListBox listbox = find.Get<ListBox>("NwcViewList");
            listbox.Items.Clear();
            rows = new Dictionary<string, (CheckBox, RadioButton)>();
            foreach (string name in Shown())
            {
                var item = new ListBoxItem();
                var grid = new Grid();
                grid.ColumnDefinitions.Add(new ColumnDefinition());
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                var check = new CheckBox { Content = name, IsChecked = views.Contains(name) };
                string captured = name;
                check.Click += McuUi.Safe(owner.Window, (s, a) =>
                {
                    if (((CheckBox)s).IsChecked == true) (views, primary) = McuNwc.Normalise(views.Concat(new[] { captured }), primary);
                    else (views, primary) = McuNwc.Untick(views, primary, captured);
                    SyncRows();
                }, owner.Theme, "NWC tick");
                var radio = new RadioButton
                {
                    GroupName = "NwcPrimary", Content = "Primary", IsChecked = name == primary, Margin = new Thickness(12, 0, 4, 0),
                };
                radio.Checked += (s, a) =>
                {
                    try
                    {
                        if (captured == primary) return;
                        (views, primary) = McuNwc.Normalise(views, captured);
                        SyncRows();
                    }
                    catch (Exception error) { Log("nwc primary: " + FormatException(error)); }
                };
                Grid.SetColumn(radio, 1);
                grid.Children.Add(check);
                grid.Children.Add(radio);
                item.Content = grid;
                listbox.Items.Add(item);
                rows[name] = (check, radio);
            }
            UpdateSummary();
        }

        private void SyncRows()
        {
            foreach (var pair in rows)
            {
                pair.Value.Check.IsChecked = views.Contains(pair.Key);
                if (pair.Key == primary && pair.Value.Radio.IsChecked != true) pair.Value.Radio.IsChecked = true;
                else if (pair.Key != primary && pair.Value.Radio.IsChecked == true) pair.Value.Radio.IsChecked = false;
            }
            UpdateSummary();
        }

        private void UpdateSummary()
        {
            var missing = views.Where(v => read && !names.Contains(v)).ToList();
            string text = McuNwc.Summary(views, primary, stem);
            if (missing.Count > 0) text += ". Not in this model: " + string.Join(", ", missing);
            find.Text("NwcSummaryText").Text = text;
        }
    }

    /// <summary>
    /// Export Settings - edits one settings template. The purge list is read from the live model with Revit's
    /// own purge query, so only categories that exist are offered. Ticks are stored as an exclusion list, so a
    /// category that turns up in a later model is purged by default. Port of mcu_settings.py.
    /// </summary>
    public sealed class McuSettingsWindow
    {
        private static readonly (string Control, string Key, bool Default)[] Checks =
        {
            ("AuditCheck", "audit", false), ("CompactCheck", "compact", true), ("RelinquishDefaultCheck", "relinquish", true),
            ("OpenWhenDoneCheck", "open_when_done", true), ("AddDateCheck", "add_date", true), ("AddSuffixCheck", "add_suffix", true),
            ("RemoveLinksCheck", "remove_revit_links", true), ("RemoveCadCheck", "remove_cad", true),
            ("RemovePointCloudsCheck", "remove_point_clouds", true), ("DeleteUnplacedImagesCheck", "delete_unplaced_images", true),
            ("DeleteSheetsCheck", "delete_sheets_not_retained", false), ("DeleteViewsCheck", "delete_views_off_sheet", true),
            ("DeleteSchedulesCheck", "delete_schedules_off_sheet", true), ("DeleteLegendsCheck", "delete_legends_off_sheet", false),
            ("DeleteTemplatesCheck", "delete_unused_templates", true), ("DeleteFiltersCheck", "delete_unused_filters", true),
            ("PurgeCheck", "purge", true), ("OfferPublishCheck", "offer_publish", true), ("ShowUsedCheck", "show_used", false),
        };

        private static readonly (string Control, string Key)[] Texts =
        {
            ("FileSuffixBox", "file_suffix"), ("SyncCommentDefaultBox", "sync_comment"),
            ("KeepWordsBox", "keep_view_words"), ("PurgePassesBox", "purge_passes"),
        };

        private const int RowLimit = 20000;

        private static readonly (string Key, string Label)[] LinkLabels =
        {
            (McuAps.LinksAsk, "Ask each time"), (McuAps.LinksWith, "Always with links"), (McuAps.LinksWithout, "Always without links"),
        };

        private readonly McuWindow ownerWindow;
        private readonly Autodesk.Revit.DB.Document doc;
        public readonly McuThemeState Theme;
        public McuPurgeScan PurgeCache;
        private string name;
        private Dictionary<string, string> values;
        private HashSet<string> excluded;
        private Dictionary<string, CheckBox> checks = new Dictionary<string, CheckBox>();
        private Dictionary<string, ListBoxItem> items = new Dictionary<string, ListBoxItem>();
        private string selectedGroup;
        private string savedName = "";
        private bool loading;
        private bool busy;

        public readonly Window Window;
        public readonly McuFinder Find;
        private readonly McuProgressBar progress;
        private readonly McuRetainList viewList;
        private readonly McuNwcPanel nwcPanel;
        private readonly McuRetainList sheetList;
        private bool browserRead;
        private readonly DataTable table;
        private readonly DispatcherTimer searchTimer;

        public McuSettingsWindow(McuWindow owner, string templateName)
        {
            ownerWindow = owner;
            doc = owner.Doc;
            Theme = owner.Theme;
            PurgeCache = owner.PurgeCache;
            name = templateName;
            values = LoadTemplate(templateName);
            excluded = new HashSet<string>(SplitList(values.Get("purge_exclude")));

            var standard = McuUi.StandardWindow("McuSettings.xaml", Theme, () => busy);
            Window = standard.Window;
            Find = standard.Find;
            McuUi.SetOwner(Window, owner.Frame);
            progress = new McuProgressBar(Window, Find);
            viewList = new McuRetainList(this, "View", "views");
            nwcPanel = new McuNwcPanel(this);
            sheetList = new McuRetainList(this, "Sheet", "sheets");
            table = new DataTable("elements");
            foreach (string column in new[] { "eid", "name", "grp", "status" }) table.Columns.Add(column);
            Find.Get<DataGrid>("ElementGrid").ItemsSource = table.DefaultView;

            Wire("SaveButton", OnSave);
            Wire("CancelButton", (s, a) => Window.Close());
            Wire("SaveAsNewButton", OnSaveAsNew);
            Wire("DeleteTemplateButton", OnDelete);
            Wire("ExportTemplateButton", OnExportFile);
            Wire("ImportTemplateButton", OnImportFile);
            Wire("SelectAllButton", (s, a) => TickAll(true));
            Wire("SelectNoneButton", (s, a) => TickAll(false));
            Wire("RescanButton", OnRescan);
            Wire("ApsHelpButton", (s, a) => McuUi.Tell(Window, "Publish to ACC", McuAps.SetupHelpFor(ApsPort()), Theme));
            Wire("SignOutButton", OnSignOut);
            Find.Box("ApsPortBox").TextChanged += (s, a) => { try { UpdateApsText(); } catch (Exception) { } };
            Find.Box("ApsClientIdBox").TextChanged += (s, a) => { try { UpdateApsText(); } catch (Exception) { } };
            Find.Check("ShowUsedCheck").Click += McuUi.Safe(Window, (s, a) => FillCategories(), Theme, "show used");
            Find.Get<ListBox>("CategoryList").SelectionChanged += McuUi.SafeSelection(Window, OnCategoryPicked, Theme, "category");
            Find.Combo("SettingsTemplateCombo").SelectionChanged += McuUi.SafeSelection(Window, OnTemplateChanged, Theme, "template");
            Find.Check("PurgeCheck").Click += McuUi.Safe(Window, (s, a) => UpdatePurgeEnabled(), Theme, "purge");
            Find.Check("AddSuffixCheck").Click += McuUi.Safe(Window, (s, a) => UpdateSuffixEnabled(), Theme, "suffix");
            Window.PreviewKeyDown += OnKey;

            searchTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(220) };
            searchTimer.Tick += McuUi.SafeTick(Window, () => { searchTimer.Stop(); FillCategories(); }, Theme, "search");
            Find.Box("CategorySearchBox").TextChanged += (s, a) => { searchTimer.Stop(); searchTimer.Start(); };
            Find.Box("ElementSearchBox").TextChanged += (s, a) => { searchTimer.Stop(); searchTimer.Start(); };
            Window.ContentRendered += (s, a) =>
            {
                try { OnFirstRender(); }
                catch (Exception error) { McuUi.ShowError(Window, "first render", FormatException(error), Theme); }
            };

            ComboBox combo = Find.Combo("PublishLinksCombo");
            foreach (var link in LinkLabels) combo.Items.Add(link.Label);
            Find.Box("ApsClientIdBox").Text = owner.Settings.Get("aps_client_id");
            Find.Box("ApsPortBox").Text = owner.Settings.Get("aps_port");
            UpdateApsText();

            FillTemplates();
            PushValues();
        }

        private void Wire(string controlName, Action<object, RoutedEventArgs> handler)
        {
            Find.Button(controlName).Click += McuUi.Safe(Window, handler, Theme, controlName);
        }

        public string Show()
        {
            Window.ShowDialog();
            return savedName;
        }

        private void SetStatus(string text) { Find.Text("StatusText").Text = text ?? ""; }

        // ------------------------------------------------------------
        private void FillTemplates()
        {
            loading = true;
            try
            {
                ComboBox combo = Find.Combo("SettingsTemplateCombo");
                combo.Items.Clear();
                var names = ListTemplates();
                foreach (string item in names) combo.Items.Add(item);
                name = PickTemplate(names, name);
                combo.SelectedItem = name;
            }
            finally { loading = false; }
        }

        private void PushValues()
        {
            bool preserve = values.Get("detach_mode") != DetachDiscard;
            Find.Get<RadioButton>("PreserveRadio").IsChecked = preserve;
            Find.Get<RadioButton>("DiscardRadio").IsChecked = !preserve;
            foreach (var check in Checks) Find.Check(check.Control).IsChecked = AsBool(values.Get(check.Key), check.Default);
            foreach (var text in Texts) Find.Box(text.Control).Text = values.Get(text.Key);
            int link = Array.FindIndex(LinkLabels, l => l.Key == McuAps.NormaliseLinks(values.Get("publish_links")));
            Find.Combo("PublishLinksCombo").SelectedIndex = link;
            excluded = new HashSet<string>(SplitList(values.Get("purge_exclude")));
            UpdatePurgeEnabled();
            UpdateSuffixEnabled();
            nwcPanel.Push(values);
            FillCategories();
            if (browserRead)
            {
                viewList.Retained = new HashSet<string>(SplitRetain(values.Get("retain_views")));
                sheetList.Retained = new HashSet<string>(SplitRetain(values.Get("retain_sheets")));
                viewList.Render();
                sheetList.Render();
            }
        }

        private Dictionary<string, string> PullValues()
        {
            var result = new Dictionary<string, string>(values);
            result["detach_mode"] = Find.Get<RadioButton>("DiscardRadio").IsChecked == true ? DetachDiscard : DetachPreserve;
            foreach (var check in Checks) result[check.Key] = BoolText(Find.Check(check.Control).IsChecked == true);
            foreach (var text in Texts) result[text.Key] = Find.Box(text.Control).Text.Trim();
            result["purge_passes"] = AsInt(result["purge_passes"], 4, 1, 10).ToString(Inv);
            nwcPanel.Pull(result);
            if (browserRead)
            {
                result["retain_views"] = JoinRetain(viewList.Keys());
                result["retain_sheets"] = JoinRetain(sheetList.Keys());
            }
            int index = Find.Combo("PublishLinksCombo").SelectedIndex;
            result["publish_links"] = index >= 0 && index < LinkLabels.Length ? LinkLabels[index].Key : McuAps.LinksAsk;
            result["purge_exclude"] = JoinList(excluded.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal));
            return result;
        }

        private void UpdateSuffixEnabled()
        {
            Find["FileSuffixBox"].IsEnabled = Find.Check("AddSuffixCheck").IsChecked == true;
        }

        private void UpdatePurgeEnabled()
        {
            bool on = Find.Check("PurgeCheck").IsChecked == true;
            foreach (string control in new[] { "PurgePassesBox", "CategoryList", "SelectAllButton", "SelectNoneButton" })
                Find[control].IsEnabled = on;
        }

        // ------------------------------------------------------------
        private void OnFirstRender()
        {
            ReadBrowser();
            if (PurgeCache == null) Scan();
            else FillCategories();
        }

        /// <summary>Views and sheets, grouped as the project browser shows them now.</summary>
        private void ReadBrowser()
        {
            busy = true;
            SetDeaf(true);
            progress.Begin("Reading the project browser");
            progress.Update(0.2, "Reading views and their browser folders");
            string state = "fail";
            try
            {
                var (views, viewOrg) = McuModel.ViewRetainItems(doc);
                progress.Update(0.6, "Reading sheets and their browser folders");
                var (sheets, sheetOrg) = McuModel.SheetRetainItems(doc);
                progress.Update(0.85, "Reading 3D views for the NWC export");
                nwcPanel.Load(doc);
                browserRead = true;
                viewList.Load(views, viewOrg, SplitRetain(values.Get("retain_views")));
                sheetList.Load(sheets, sheetOrg, SplitRetain(values.Get("retain_sheets")));
                state = "ok";
            }
            finally
            {
                busy = false;
                SetDeaf(false);
                progress.Finish(state == "ok" ? "Project browser read" : "Reading the project browser failed", state);
            }
        }

        /// <summary>Mouse off the body for a read - all but the shrink button.</summary>
        private void SetDeaf(bool deaf)
        {
            foreach (string control in new[] { "BodyGrid", "FooterBar", "ThemeChip", "FullScreenButton", "CloseButton" })
            {
                try { Find[control].IsHitTestVisible = !deaf; } catch (Exception) { }
            }
        }

        private void Scan()
        {
            busy = true;
            SetDeaf(true);
            SetStatus("Reading what can be purged from the live model...");
            progress.Begin("Reading the live model");
            progress.Update(0.1, "Asking Revit what is unused (Revit is busy)");
            string state = "fail";
            try
            {
                PurgeCache = McuModel.ScanPurge(doc, true);
                state = PurgeCache.Ok ? "ok" : "warn";
                progress.Update(0.8, "Listing categories");
                FillCategories();
            }
            finally
            {
                busy = false;
                SetDeaf(false);
                progress.Finish(state == "ok" ? "Model read" : state == "warn" ? "Purge is not available here" : "Reading the model failed", state);
            }
            if (!PurgeCache.Ok) SetStatus(PurgeCache.Reason);
        }

        /// <summary>Re-read the browser and the purge list, keeping the ticks made so far.</summary>
        private void OnRescan(object sender, RoutedEventArgs args)
        {
            if (browserRead)
            {
                values["retain_views"] = JoinRetain(viewList.Keys());
                values["retain_sheets"] = JoinRetain(sheetList.Keys());
            }
            nwcPanel.Pull(values);
            ReadBrowser();
            PurgeCache = null;
            Scan();
        }

        private bool ShowUsed() { return Find.Check("ShowUsedCheck").IsChecked == true; }

        private void FillCategories()
        {
            ListBox listbox = Find.Get<ListBox>("CategoryList");
            listbox.Items.Clear();
            checks = new Dictionary<string, CheckBox>();
            items = new Dictionary<string, ListBoxItem>();
            McuPurgeScan cache = PurgeCache;
            bool showUsed = ShowUsed();
            Visibility usedVisibility = showUsed ? Visibility.Visible : Visibility.Collapsed;
            Find["UsedHeaderText"].Visibility = usedVisibility;
            if (cache == null)
            {
                Find.Text("CategorySummaryText").Text = "Reading the model...";
                return;
            }
            var rows = GroupCounts(cache.Unused, cache.Used);
            var shown = VisibleGroups(rows, showUsed, Find.Box("CategorySearchBox").Text);
            foreach (var row in shown)
            {
                var item = new ListBoxItem();
                var grid = new Grid();
                grid.ColumnDefinitions.Add(new ColumnDefinition());
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(56) });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(56) });
                var check = new CheckBox { Content = row.Group, IsChecked = !excluded.Contains(row.Group), Margin = new Thickness(0, 2, 0, 2) };
                string group = row.Group;
                check.Click += McuUi.Safe(Window, (s, a) =>
                {
                    if (((CheckBox)s).IsChecked == true) excluded.Remove(group); else excluded.Add(group);
                    UpdateSummary(null);
                }, Theme, "category tick");
                var unusedText = new TextBlock
                {
                    Text = row.Unused.ToString(), TextAlignment = TextAlignment.Right, VerticalAlignment = VerticalAlignment.Center,
                };
                unusedText.SetResourceReference(TextBlock.ForegroundProperty, row.Unused > 0 ? "OrangeBrush" : "MutedBrush");
                var usedBlock = new TextBlock
                {
                    Text = row.Used.ToString(), TextAlignment = TextAlignment.Right, VerticalAlignment = VerticalAlignment.Center,
                    Visibility = usedVisibility,
                };
                usedBlock.SetResourceReference(TextBlock.ForegroundProperty, "GreenBrush");
                Grid.SetColumn(unusedText, 1);
                Grid.SetColumn(usedBlock, 2);
                grid.Children.Add(check);
                grid.Children.Add(unusedText);
                grid.Children.Add(usedBlock);
                item.Content = grid;
                item.Tag = row.Group;
                listbox.Items.Add(item);
                checks[row.Group] = check;
                items[row.Group] = item;
            }
            ListBoxItem selected;
            if (selectedGroup != null && items.TryGetValue(selectedGroup, out selected)) listbox.SelectedItem = selected;
            UpdateSummary(rows);
            FillElements();
        }

        private void UpdateSummary(List<(string Group, int Unused, int Used)> rows)
        {
            McuPurgeScan cache = PurgeCache;
            if (rows == null) rows = GroupCounts(cache == null ? new List<(long, string)>() : cache.Unused,
                                                 cache == null ? new List<(long, string)>() : cache.Used);
            int purgeCount = rows.Where(r => !excluded.Contains(r.Group)).Sum(r => r.Unused);
            int leftOut = rows.Count(r => excluded.Contains(r.Group));
            string text = purgeCount + " unused elements would be purged from the live model today";
            if (leftOut > 0) text += "; " + leftOut + " categories left out";
            text += ". The copy is rescanned when Clean Up runs.";
            Find.Text("CategorySummaryText").Text = text;
        }

        private void FillElements()
        {
            table.Rows.Clear();
            McuPurgeScan cache = PurgeCache;
            if (cache == null || selectedGroup == null) return;
            bool showUsed = ShowUsed();
            var words = Find.Box("ElementSearchBox").Text.ToLowerInvariant().Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
            int count = 0;
            table.BeginLoadData();
            try
            {
                foreach (var entry in cache.Rows)
                {
                    if (entry.Group != selectedGroup) continue;
                    if (entry.Status == "Used" && !showUsed) continue;
                    string lower = entry.Name.ToLowerInvariant();
                    if (words.Any(w => !lower.Contains(w))) continue;
                    DataRow row = table.NewRow();
                    row["eid"] = entry.Id.ToString(Inv);
                    row["name"] = entry.Name;
                    row["grp"] = entry.Group;
                    row["status"] = entry.Status;
                    table.Rows.Add(row);
                    count++;
                    if (count >= RowLimit) break;
                }
            }
            finally { table.EndLoadData(); }
            SetStatus(selectedGroup + ": " + count + " element(s) shown");
        }

        // ------------------------------------------------------------
        private void OnCategoryPicked(object sender, SelectionChangedEventArgs args)
        {
            var item = Find.Get<ListBox>("CategoryList").SelectedItem as ListBoxItem;
            if (item == null) return;
            selectedGroup = item.Tag as string;
            FillElements();
        }

        private void TickAll(bool on)
        {
            foreach (var pair in checks)
            {
                pair.Value.IsChecked = on;
                if (on) excluded.Remove(pair.Key); else excluded.Add(pair.Key);
            }
            UpdateSummary(null);
        }

        private void OnTemplateChanged(object sender, SelectionChangedEventArgs args)
        {
            if (loading) return;
            object chosen = Find.Combo("SettingsTemplateCombo").SelectedItem;
            if (chosen == null || chosen.ToString() == name) return;
            name = chosen.ToString();
            values = LoadTemplate(name);
            PushValues();
            SetStatus("Editing " + name);
        }

        // ------------------------------------------------------------
        private int ApsPort() { return AsInt(Find.Box("ApsPortBox").Text, McuAps.DefaultPort, 1024, 65535); }

        private void UpdateApsText()
        {
            Find.Text("ApsCallbackText").Text = "Callback URL: " + McuAps.CallbackUrl(ApsPort());
            string client = Find.Box("ApsClientIdBox").Text.Trim();
            string text = "No Client ID yet - publishing is off.";
            if (client.Length > 0)
            {
                try { text = McuWeb.SignedInText(client); }
                catch (Exception) { text = "Publishing could not load on this Revit."; }
            }
            Find.Text("ApsSignedInText").Text = text;
        }

        private void SaveAps()
        {
            var settings = ownerWindow.Settings;
            settings["aps_client_id"] = Find.Box("ApsClientIdBox").Text.Trim();
            settings["aps_port"] = ApsPort().ToString(Inv);
            SaveGlobal(settings);
        }

        private void OnSignOut(object sender, RoutedEventArgs args)
        {
            try { McuWeb.Forget(); } catch (Exception) { }
            UpdateApsText();
            SetStatus("Signed out of Autodesk for this tool.");
        }

        private void OnSave(object sender, RoutedEventArgs args)
        {
            SaveAps();
            var result = PullValues();
            var warnings = RetentionWarnings(result);
            if (warnings.Count > 0)
            {
                object answer = McuUi.Prompt(Window, "Retained views and sheets",
                    RetentionMessage(result, warnings) + "\n\nTurn the matching delete stages on?",
                    new List<McuButton>
                    {
                        new McuButton("Back", null, "BaseButton"), new McuButton("Save as it is", false, "OrangeButton"),
                        new McuButton("Turn them on and save", true, "GreenButton"),
                    }, Theme);
                if (answer == null) return;
                if (answer as bool? == true) result = FixRetention(result, warnings);
            }
            if (!SaveTemplate(name, result))
            {
                McuUi.Tell(Window, "Save", "The template could not be written to\n" + TemplatePath(name), Theme);
                return;
            }
            savedName = name;
            Window.Close();
        }

        private void OnSaveAsNew(object sender, RoutedEventArgs args)
        {
            var (answer, text) = McuUi.PromptInput(Window, "Save as new template", "Name the new settings template.",
                new List<McuButton> { new McuButton("Cancel", false, "BaseButton"), new McuButton("Save", true, "GreenButton") },
                Theme, name + " copy", "Template name");
            if (answer as bool? != true) return;
            string newName = SanitizeName(text);
            if (newName.Length == 0)
            {
                SetStatus("A template needs a name.");
                return;
            }
            if (ListTemplates().Contains(newName))
            {
                if (!McuUi.Confirm(Window, "Save as new template", newName + " already exists. Replace it?", "Replace", "OrangeButton", Theme))
                    return;
            }
            if (!SaveTemplate(newName, PullValues()))
            {
                SetStatus("Could not write " + TemplatePath(newName));
                return;
            }
            name = newName;
            FillTemplates();
            SetStatus("Saved as " + newName);
        }

        private void OnDelete(object sender, RoutedEventArgs args)
        {
            if (!McuUi.Confirm(Window, "Delete template", "Delete the settings template " + name + "?", "Delete", "RedGhostButton", Theme)) return;
            var (ok, reason) = DeleteTemplate(name);
            if (!ok)
            {
                SetStatus(reason);
                return;
            }
            FillTemplates();
            values = LoadTemplate(name);
            PushValues();
            savedName = name;
            SetStatus("Deleted. Now editing " + name);
        }

        // ---------------------------------------------------------- files
        private void OnExportFile(object sender, RoutedEventArgs args)
        {
            var result = PullValues();
            var dialog = new SaveFileDialog
            {
                Title = "Save the settings template to a file", Filter = "Model Cleanup template (*.txt)|*.txt", DefaultExt = ".txt",
                AddExtension = true, FileName = ExportFileName(name),
            };
            string folder = ownerWindow.Settings.Get("template_folder");
            if (folder.Length > 0 && Directory.Exists(folder)) dialog.InitialDirectory = folder;
            if (!ownerWindow.FileDialogShow(dialog, Window)) return;
            if (!ExportTemplate(result, name, dialog.FileName))
            {
                SetStatus("Could not write " + dialog.FileName);
                return;
            }
            RememberFolder(dialog.FileName);
            SetStatus("Saved to " + dialog.FileName);
        }

        private void OnImportFile(object sender, RoutedEventArgs args)
        {
            var dialog = new OpenFileDialog
            {
                Title = "Load a settings template from a file", Filter = "Model Cleanup template (*.txt)|*.txt|All files (*.*)|*.*",
            };
            string folder = ownerWindow.Settings.Get("template_folder");
            if (folder.Length > 0 && Directory.Exists(folder)) dialog.InitialDirectory = folder;
            if (!ownerWindow.FileDialogShow(dialog, Window)) return;
            var (imported, suggested, error) = ImportTemplate(dialog.FileName);
            if (error.Length > 0)
            {
                McuUi.Tell(Window, "Load from file", error, Theme);
                return;
            }
            RememberFolder(dialog.FileName);
            var (answer, typed) = McuUi.PromptInput(Window, "Load from file",
                "Loaded from\n" + dialog.FileName + "\n\nSave it as a template under this name:",
                new List<McuButton> { new McuButton("Cancel", false, "BaseButton"), new McuButton("Save", true, "GreenButton") },
                Theme, suggested, "Template name");
            if (answer as bool? != true) return;
            string newName = SanitizeName(typed);
            if (newName.Length == 0) newName = suggested;
            var existing = ListTemplates();
            if (existing.Contains(newName))
            {
                object choice = McuUi.Prompt(Window, "Load from file", newName + " already exists.",
                    new List<McuButton>
                    {
                        new McuButton("Cancel", null, "BaseButton"), new McuButton("Keep both", "both", "BaseButton"),
                        new McuButton("Replace it", "replace", "OrangeButton"),
                    }, Theme);
                if (choice == null) return;
                if ((string)choice == "both") newName = UniqueTemplateName(newName, existing);
            }
            if (!SaveTemplate(newName, imported))
            {
                SetStatus("Could not save " + newName);
                return;
            }
            name = newName;
            values = LoadTemplate(newName);
            savedName = newName;
            FillTemplates();
            PushValues();
            SetStatus("Loaded " + newName + ". It is now the template being edited.");
        }

        private void RememberFolder(string path)
        {
            ownerWindow.Settings["template_folder"] = Path.GetDirectoryName(path) ?? "";
            SaveGlobal(ownerWindow.Settings);
        }

        private void OnKey(object sender, KeyEventArgs args)
        {
            try
            {
                if (args.Handled) return;
                if (busy)
                {
                    args.Handled = true;
                    return;
                }
                if (args.Key == Key.Escape)
                {
                    Window.Close();
                    args.Handled = true;
                }
            }
            catch (Exception) { }
        }
    }
}

