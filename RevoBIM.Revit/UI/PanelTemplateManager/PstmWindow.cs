using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.PanelTemplateManager;

using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using Clipboard = System.Windows.Clipboard;
using ComboBox = System.Windows.Controls.ComboBox;
using DataGrid = System.Windows.Controls.DataGrid;
using ListBox = System.Windows.Controls.ListBox;
using MenuItem = System.Windows.Controls.MenuItem;
using Panel = System.Windows.Controls.Panel;
using ProgressBar = System.Windows.Controls.ProgressBar;
using TextBox = System.Windows.Controls.TextBox;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.PanelTemplateManager
{
    /// <summary>
    /// Panel Template Mngr main window (pstm_window.py). Modeless and owned by Revit's main window, so Revit stays fully navigable and editable with the
    /// manager open. Nothing is written to the model until Apply (or Create, Delete or Merge on the duplicator tab) is pressed, and every write goes out
    /// through an ExternalEvent.
    /// </summary>
    internal sealed class PstmWindow
    {
        /// <summary>The live window, parked here so a modeless window is never collected out from under the user.</summary>
        public static PstmWindow Active;

        private const string AllTypes = "(All types)";
        private const string NoParam = "(none)";
        private const string DropColumn = "(remove this column)";

        // Header controls that go deaf while a job runs. The shrink button is deliberately left off: shrinking touches only the window's own geometry.
        private static readonly string[] BusyDeaf = { "SettingsButton", "ThemeChip", "FullScreenButton", "CloseButton" };

        // name -> which edges of the window that grip moves (left, top, right, bottom)
        private static readonly Dictionary<string, bool[]> Grips = new Dictionary<string, bool[]>
        {
            { "GripNW", new[] { true, true, false, false } }, { "GripN", new[] { false, true, false, false } },
            { "GripNE", new[] { false, true, true, false } }, { "GripW", new[] { true, false, false, false } },
            { "GripE", new[] { false, false, true, false } }, { "GripSW", new[] { true, false, false, true } },
            { "GripS", new[] { false, false, false, true } }, { "GripSE", new[] { false, false, true, true } },
        };

        private readonly UIApplication uiapp;
        private readonly Document doc;
        private readonly PstmEventHandler handler;
        private readonly ExternalEvent ev;
        private readonly FullScreen full;
        private Dictionary<string, string> settings;
        private string palette;
        private ModelData data = new ModelData();
        private readonly Dictionary<string, ColumnHeader> headers = new Dictionary<string, ColumnHeader>();
        private List<string> colNames;
        private readonly Dictionary<string, long> displayToId = new Dictionary<string, long>();
        private readonly Dictionary<long, string> idToDisplay = new Dictionary<long, string>();
        private List<PanelRow> visibleRows = new List<PanelRow>();
        private List<TemplateInfo> templateView = new List<TemplateInfo>();
        private string sortKey = "panel";
        private bool sortDesc;
        private TemplateInfo dupSource;
        private readonly List<KeyValuePair<int, string>> slotItems = new List<KeyValuePair<int, string>>();
        private readonly Dictionary<string, int> slotLookup = new Dictionary<string, int>();
        private bool busy;
        private bool populating;
        private string typeNote = "";
        private string pendingLabel = "";
        private Dictionary<long, KeyValuePair<long, string>> applyWanted = new Dictionary<long, KeyValuePair<long, string>>();
        private string editingName = "";
        private RowConverter textConv, backConv, foreConv, boldConv, tplTextConv, tplBackConv, tplForeConv;
        private Button addButton;

        public readonly Window Win;
        public readonly WindowDrawer Drawer;

        public PstmWindow(UIApplication uiapp, Document doc)
        {
            this.uiapp = uiapp;
            this.doc = doc;
            settings = PstmCore.LoadSettings();
            palette = PstmCore.Get(settings, "theme");
            Win = PstmChrome.LoadWindow("PanelScheduleTemplateManager.xaml", palette);
            full = new FullScreen(Win);
            colNames = PstmCore.InitialColumns(settings);
            handler = new PstmEventHandler { Doc = doc, OnComplete = JobDone };
            ev = ExternalEvent.Create(handler);

            PstmChrome.SetText(Win, "VersionText", "v" + PstmCore.Version);
            var icon = Win.FindName("ToolIcon") as Image;
            PstmChrome.SetIcon(icon);
            // Three slow clicks on the logo open the RevoBIM Arcade.
            EggHook.Attach(Win, () => palette, icon);
            SetThemeChip();
            var header = (FrameworkElement)Win.FindName("HeaderBar");
            header.MouseLeftButtonDown += HeaderClick;
            Drawer = PstmChrome.MakeDrawer(Win);
            WireGrips();
            SetFullGlyph();
            BuildColumns();
            Wire();
            PstmCore.Log("open: Revit " + uiapp.Application.VersionName + " " + uiapp.Application.VersionBuild + ", " + doc.Title + ", theme " + palette);
            Refresh(true);
        }

        private T C<T>(string name) where T : class
        {
            return Win.FindName(name) as T;
        }

        private string Version
        {
            get { return "v" + PstmCore.Version; }
        }

        // ================================================================== chrome
        private void SetThemeChip()
        {
            try
            {
                string other = PstmTheme.Other(palette);
                C<Button>("ThemeChip").Content = char.ToUpperInvariant(other[0]) + other.Substring(1);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>WPF's resize border does not fire on a borderless AllowsTransparency window, so the window carries its own grips.</summary>
        private void WireGrips()
        {
            foreach (var entry in Grips)
            {
                var thumb = Win.FindName(entry.Key) as Thumb;
                if (thumb == null) continue;
                bool[] edges = entry.Value;
                thumb.DragDelta += (s, a) => Grip(edges[0], edges[1], edges[2], edges[3], a);
            }
        }

        private void Grip(bool left, bool top, bool right, bool bottom, DragDeltaEventArgs args)
        {
            if (Drawer.Parked) return;
            try
            {
                // dragging an edge is a deliberate exit from full screen
                if (full.IsFull)
                {
                    full.Saved = null;
                    SetFullGlyph();
                }
                double dx = args.HorizontalChange, dy = args.VerticalChange;
                if (left)
                {
                    double wide = Win.Width - dx;
                    if (wide >= Win.MinWidth)
                    {
                        Win.Left = Win.Left + dx;
                        Win.Width = wide;
                    }
                }
                if (right)
                {
                    double wide = Win.Width + dx;
                    if (wide >= Win.MinWidth) Win.Width = wide;
                }
                if (top)
                {
                    double tall = Win.Height - dy;
                    if (tall >= Win.MinHeight)
                    {
                        Win.Top = Win.Top + dy;
                        Win.Height = tall;
                    }
                }
                if (bottom)
                {
                    double tall = Win.Height + dy;
                    if (tall >= Win.MinHeight) Win.Height = tall;
                }
            }
            catch (Exception)
            {
            }
        }

        private void SetFullGlyph()
        {
            try
            {
                bool isFull = full.IsFull;
                C<UIElement>("MaxGlyph").Visibility = isFull ? Visibility.Collapsed : Visibility.Visible;
                C<UIElement>("RestoreGlyph").Visibility = isFull ? Visibility.Visible : Visibility.Collapsed;
            }
            catch (Exception)
            {
            }
        }

        private void HeaderClick(object sender, MouseButtonEventArgs args)
        {
            // A parked bar belongs to the drawer even while a job runs: a double click brings the window back. It is only dragged when no job is
            // running - DragMove runs a modal loop, and one of those inside Revit's API context is not something to start mid transaction.
            if (Drawer.Parked)
            {
                if (args.ClickCount == 2 && Drawer.OnHeaderDoubleClick())
                {
                    args.Handled = true;
                    return;
                }
                if (!busy && !Drawer.Sliding)
                {
                    try { Win.DragMove(); } catch (Exception) { }
                }
                return;
            }
            if (busy) return;
            try
            {
                if (args.ClickCount == 2)
                {
                    full.Toggle();
                    SetFullGlyph();
                    return;
                }
                if (full.IsFull)
                {
                    full.Saved = null;
                    SetFullGlyph();
                }
                Win.DragMove();
            }
            catch (Exception)
            {
            }
        }

        // ================================================================== events
        private void Wire()
        {
            C<Button>("CloseButton").Click += (s, a) => CloseClicked();
            C<Button>("ThemeChip").Click += (s, a) => ToggleTheme();
            C<Button>("FullScreenButton").Click += (s, a) => ToggleFull();
            C<Button>("SettingsButton").Click += (s, a) => OpenSettings();
            C<Button>("RefreshButton").Click += (s, a) => RefreshClicked();
            C<Button>("RegenerateButton").Click += (s, a) => RegenerateClicked();
            C<Button>("ApplyButton").Click += (s, a) => ApplyClicked();

            C<ComboBox>("TemplateTypeCombo").SelectionChanged += (s, a) => TemplateFilterChanged();
            C<ComboBox>("TemplateFilterCombo").SelectionChanged += (s, a) => TemplateFilterChanged();
            C<TextBox>("TemplateSearchBox").TextChanged += (s, a) =>
            {
                if (populating) return;
                FillTemplateList();
            };
            C<MenuItem>("EditTemplateItem").Click += (s, a) => EditTemplateClicked();
            C<MenuItem>("CopyTemplateNameItem").Click += (s, a) => CopyTemplateName();
            C<TextBox>("PanelSearchBox").TextChanged += (s, a) => AnyFilter();
            C<Button>("ClearFiltersButton").Click += (s, a) => ClearFilters();
            C<Button>("AutoAssignAllButton").Click += (s, a) => AutoAssign(null);
            C<Button>("AutoAssignSelectedButton").Click += (s, a) => AutoAssignSelected();
            C<Button>("ResetChangesButton").Click += (s, a) => ResetClicked();

            C<TextBox>("DupSearchBox").TextChanged += (s, a) => DupFilterChanged();
            C<CheckBox>("UnusedOnlyCheck").Click += (s, a) => DupFilterChanged();
            C<CheckBox>("DupUseFiltersCheck").Click += (s, a) => DupFilterChanged();
            C<Button>("DeleteTemplatesButton").Click += (s, a) => DeleteClicked();
            C<Button>("MergeTemplatesButton").Click += (s, a) => MergeClicked();
            C<Button>("RenameTemplatesButton").Click += (s, a) => RenameClicked();
            C<Button>("DuplicateButton").Click += (s, a) => DuplicateClicked();
            C<Button>("CreateButton").Click += (s, a) => CreateClicked();
            C<Button>("SlotAllButton").Click += (s, a) => { try { C<ListBox>("SlotList").SelectAll(); } catch (Exception) { } };
            C<Button>("SlotNoneButton").Click += (s, a) => { try { C<ListBox>("SlotList").UnselectAll(); } catch (Exception) { } };
            C<Button>("SlotCommonButton").Click += (s, a) => SlotsCommon();
            C<TextBox>("DupBaseName").TextChanged += (s, a) => DupPreview();
            C<CheckBox>("DupSinglePhaseCheck").Click += (s, a) => SinglePhaseClicked();
            C<ListBox>("SlotList").SelectionChanged += (s, a) => DupPreview();

            var gridCtrl = C<DataGrid>("PanelGrid");
            gridCtrl.Sorting += OnSort;
            gridCtrl.SelectionChanged += (s, a) => PanelSelection();
            C<DataGrid>("TemplateGrid").SelectionChanged += (s, a) =>
            {
                if (populating) return;
                FillMergeTargets();
            };
            Win.PreviewKeyDown += OnKey;
            Win.Closed += (s, a) =>
            {
                handler.OnComplete = null;
                Active = null;
                PstmCore.Log("closed");
            };
        }

        // ================================================================== columns
        public static string ParamKey(int index)
        {
            return "p" + index;
        }

        public static int? ParamIndex(string key)
        {
            string text = key ?? "";
            int n;
            if (text.Length > 1 && text[0] == 'p' && int.TryParse(text.Substring(1), out n)) return n;
            return null;
        }

        /// <summary>What a column's filter belongs to: a parameter, or a fixed column. Keyed by parameter name so adding or removing a column does not hand one column's filter to another.</summary>
        private string FilterId(string key)
        {
            int? index = ParamIndex(key);
            if (index != null && index.Value < colNames.Count) return "param:" + (colNames[index.Value] ?? "");
            return "fixed:" + key;
        }

        private Dictionary<string, Tuple<string, HashSet<string>>> SnapshotFilters()
        {
            var snap = new Dictionary<string, Tuple<string, HashSet<string>>>();
            foreach (var entry in headers)
                snap[FilterId(entry.Key)] = Tuple.Create(entry.Value.SearchBox != null ? entry.Value.SearchBox.Text ?? "" : "", entry.Value.Allowed);
            return snap;
        }

        private void RestoreFilters(Dictionary<string, Tuple<string, HashSet<string>>> snap)
        {
            if (snap == null || snap.Count == 0) return;
            foreach (var entry in headers)
            {
                Tuple<string, HashSet<string>> saved;
                if (!snap.TryGetValue(FilterId(entry.Key), out saved)) continue;
                ColumnHeader header = entry.Value;
                header.Suppress = true;
                try
                {
                    if (header.SearchBox != null) header.SearchBox.Text = saved.Item1;
                }
                finally
                {
                    header.Suppress = false;
                }
                header.Allowed = saved.Item2;
                header.Mark();
            }
        }

        private void BuildColumns()
        {
            textConv = new RowConverter((row, key) => CellText(row as PanelRow, key));
            backConv = new RowConverter((row, key) => CellBack(row as PanelRow, key));
            foreConv = new RowConverter((row, key) => CellFore(row as PanelRow, key));
            boldConv = new RowConverter((row, key) => CellBold(row as PanelRow, key));
            tplTextConv = new RowConverter((tpl, key) => TplText(tpl as TemplateInfo, key));
            tplBackConv = new RowConverter((tpl, key) => TplBack(tpl as TemplateInfo, key));
            tplForeConv = new RowConverter((tpl, key) => TplFore(tpl as TemplateInfo, key));

            var panelGrid = C<DataGrid>("PanelGrid");
            var keepFilters = SnapshotFilters();
            panelGrid.Columns.Clear();
            headers.Clear();

            // (key, heading, star share, minimum px, searchable, kind)
            var specs = new List<Tuple<string, string, double, double, bool, string>>
            {
                Tuple.Create("panel", "Panel", 1.15, 120.0, true, (string)null),
                Tuple.Create("template", "Panel template used", 2.3, 195.0, true, (string)null),
            };
            for (int index = 0; index < colNames.Count; index++) specs.Add(Tuple.Create(ParamKey(index), "", 1.25, 120.0, true, "param"));
            specs.Add(Tuple.Create("note", "Auto Assign", 1.75, 150.0, false, (string)null));

            foreach (var spec in specs)
            {
                string key = spec.Item1;
                var header = new ColumnHeader(key, spec.Item2, AnyFilter, key != "note" ? (Action<ColumnHeader>)OpenTickFilter : null,
                                              spec.Item6 == "param" ? data.ParamNames : null, spec.Item6 == "param" ? (Action<string, string>)ParamPick : null,
                                              spec.Item5);
                headers[key] = header;
                if (spec.Item6 == "param")
                {
                    string nm = colNames[ParamIndex(key).Value];
                    header.SetParam(nm.Length > 0 ? nm : NoParam);
                }
                DataTemplate cell;
                if (key == "template") cell = PstmGrid.ComboCellTemplate(backConv, key, ComboLoaded, ComboChanged);
                else cell = PstmGrid.TextCellTemplate(textConv, backConv, foreConv, key, boldConv);
                panelGrid.Columns.Add(PstmGrid.MakeColumn(header.Content, cell, null, key, spec.Item4, spec.Item3));
            }

            // the green + on the end adds another parameter column
            addButton = new Button { Content = "+", ToolTip = "Add another parameter column" };
            addButton.Click += (s, a) => AddColumn();
            try { addButton.SetResourceReference(FrameworkElement.StyleProperty, "AddButton"); } catch (Exception) { }
            panelGrid.Columns.Add(PstmGrid.MakeColumn(addButton, PstmGrid.TextCellTemplate(textConv, backConv, foreConv, "add"), 40, "add", 40, null, false));

            RestoreFilters(keepFilters);
            // a sort on a parameter column means nothing once the columns move
            if (ParamIndex(sortKey) != null)
            {
                sortKey = "panel";
                sortDesc = false;
            }

            var tplGrid = C<DataGrid>("TemplateGrid");
            tplGrid.Columns.Clear();
            foreach (var spec in new[]
            {
                Tuple.Create("name", "Template name", 2.4, 210.0), Tuple.Create("type", "Schedule type", 1.0, 115.0),
                Tuple.Create("config", "Configuration", 1.25, 135.0), Tuple.Create("slots", "Slots", 0.55, 60.0),
                Tuple.Create("used", "Used by", 0.8, 84.0), Tuple.Create("default", "Default", 0.6, 68.0),
            })
            {
                DataTemplate cell = PstmGrid.TextCellTemplate(tplTextConv, tplBackConv, tplForeConv, spec.Item1);
                tplGrid.Columns.Add(PstmGrid.MakeColumn(spec.Item2, cell, null, spec.Item1, spec.Item4, spec.Item3));
            }
        }

        private List<string> ParamChoices()
        {
            var choices = new List<string> { NoParam };
            if (colNames.Count > 2) choices.Add(DropColumn);
            choices.AddRange(data.ParamNames);
            return choices;
        }

        private void RebuildParamItems()
        {
            for (int index = 0; index < colNames.Count; index++)
            {
                ColumnHeader header;
                if (!headers.TryGetValue(ParamKey(index), out header) || header.ParamCombo == null) continue;
                header.Suppress = true;
                try
                {
                    header.ParamCombo.Items.Clear();
                    foreach (string name in ParamChoices()) header.ParamCombo.Items.Add(name);
                }
                finally
                {
                    header.Suppress = false;
                }
                header.SetParam(colNames[index].Length > 0 ? colNames[index] : NoParam);
            }
        }

        private void AddColumn()
        {
            colNames.Add("");
            SaveColumns();
            BuildColumns();
            RebuildParamItems();
            ApplyFilters();
            Status("Added a parameter column - pick what goes in it from its heading.");
        }

        private void SaveColumns()
        {
            settings["columns"] = string.Join("|", colNames);
            PstmCore.SaveSettings(settings);
        }

        // ================================================================== brushes
        private Brush BrushOf(string key)
        {
            try
            {
                object found = Win.Resources[key];
                var b = found as Brush;
                if (b != null) return b;
            }
            catch (Exception)
            {
            }
            return PstmTheme.Brush(PstmTheme.Hex(palette, key));
        }

        // ================================================================== cell content - panels
        private object CellText(PanelRow row, string key)
        {
            if (row == null) return "";
            if (key == "panel") return row.Name;
            if (key == "template") return row.DisplayTemplate();
            if (key == "note")
            {
                if (row.Locked.Length > 0) return "LOCKED - " + row.Locked;
                var bits = new List<string>();
                if (row.CalcSlots != null && row.CalcSlots.Value != 0) bits.Add(row.CalcSlots.Value + " slots");
                if (row.Note.Length > 0) bits.Add(row.Note);
                return string.Join("  -  ", bits);
            }
            int? index = ParamIndex(key);
            if (index != null && index.Value < colNames.Count)
            {
                string name = colNames[index.Value];
                return name.Length == 0 ? "" : row.Value(name);
            }
            return "";
        }

        private string State(PanelRow row)
        {
            if (row == null) return "";
            if (row.Locked.Length > 0) return "locked";
            if (row.Status == "review") return "review";
            if (row.Changed) return "changed";
            if (row.Status == "multi") return "multi";
            if (row.Note.Length > 0 && row.Note.EndsWith("already right", StringComparison.Ordinal)) return "matched";
            return "";
        }

        private object CellBack(PanelRow row, string key)
        {
            string state = State(row);
            if (state == "locked") return BrushOf("UnusedBg");
            if (state == "review") return BrushOf("ReviewBg");
            if ((state == "changed" || state == "multi") && (key == "template" || key == "note")) return BrushOf("ChangedBg");
            if (state == "matched" && (key == "template" || key == "note")) return BrushOf("MatchedBg");
            return null;
        }

        private object CellFore(PanelRow row, string key)
        {
            string state = State(row);
            if (state == "locked") return key == "note" ? BrushOf("OrangeBrush") : BrushOf("MutedBrush");
            if (state == "review") return BrushOf("RedBrush");
            if ((state == "changed" || state == "multi") && (key == "template" || key == "note")) return BrushOf("OrangeBrush");
            if (state == "matched" && key == "note") return BrushOf("GreenBrush");
            return BrushOf("TextBrush");
        }

        private object CellBold(PanelRow row, string key)
        {
            string state = State(row);
            if ((state == "changed" || state == "multi" || state == "review") && (key == "template" || key == "note" || key == "panel")) return FontWeights.SemiBold;
            return FontWeights.Normal;
        }

        // ================================================================== cell content - templates
        private object TplText(TemplateInfo tpl, string key)
        {
            if (tpl == null) return "";
            switch (key)
            {
                case "name": return tpl.Name;
                case "type": return tpl.ScheduleType;
                case "config": return tpl.ConfigPretty;
                case "slots": return tpl.Slots != 0 ? tpl.Slots.ToString() : "";
                case "used":
                    if (tpl.UsedCount == 0) return "not used";
                    if (tpl.UsedCount == 1) return "1 panel";
                    return tpl.UsedCount + " panels";
                case "default": return tpl.IsDefault ? "default" : "";
            }
            return "";
        }

        private object TplBack(TemplateInfo tpl, string key)
        {
            return tpl != null && tpl.UsedCount == 0 ? BrushOf("UnusedBg") : null;
        }

        private object TplFore(TemplateInfo tpl, string key)
        {
            if (tpl == null) return BrushOf("TextBrush");
            if (key == "used" && tpl.UsedCount == 0) return BrushOf("MutedBrush");
            if (key == "default" && tpl.IsDefault) return BrushOf("BlueBrush");
            return BrushOf("TextBrush");
        }

        // ================================================================== reading the model
        private void Refresh(bool first = false, bool keepChanges = false)
        {
            Status("Reading the model...");
            var pending = new Dictionary<long, Tuple<long, string, string, string, int?>>();
            if (keepChanges)
            {
                foreach (PanelRow row in data.Rows)
                    if (row.Changed) pending[row.IdVal] = Tuple.Create(row.ChosenId, row.ChosenName, row.Status, row.Note, row.CalcSlots);
            }
            try
            {
                data = PstmModel.Read(doc, settings);
            }
            catch (Exception ex)
            {
                PstmCore.Log("read failed: " + ex);
                Status("Could not read the model: " + ex.Message);
                return;
            }
            foreach (PanelRow row in data.Rows)
            {
                Tuple<long, string, string, string, int?> saved;
                if (pending.TryGetValue(row.IdVal, out saved))
                {
                    row.ChosenId = saved.Item1;
                    row.ChosenName = saved.Item2;
                    row.Status = saved.Item3;
                    row.Note = saved.Item4;
                    row.CalcSlots = saved.Item5;
                }
            }
            RebuildParamItems();
            FillTemplateType(first);
            FillTemplateFilter(first);
            BuildDisplayMap();
            FillTemplateList();
            typeNote = "";
            GuardTypeFilter();
            FillSlotList(ChosenSlots());
            ApplyFilters();
            RefreshTemplatesTab();
            UpdatePending();
            PstmCore.Log("read: " + data.Rows.Count + " panels, " + data.Templates.Count + " templates, " + data.Rows.Count(r => r.View != null) + " with a schedule, " +
                         data.Rows.Count(r => r.Locked.Length > 0) + " locked, " + data.ParamNames.Count + " parameters" + (keepChanges ? ", changes kept" : ""));
            Status(data.Rows.Count + " panels, " + data.Templates.Count + " templates." + typeNote);
        }

        private void FillTemplateType(bool first)
        {
            var combo = C<ComboBox>("TemplateTypeCombo");
            object want = first ? null : combo.SelectedItem;
            populating = true;
            try
            {
                combo.Items.Clear();
                combo.Items.Add(AllTypes);
                foreach (string name in PstmModel.ScheduleTypes) combo.Items.Add(name);
                // anything the project uses that is not one of the three
                foreach (TemplateInfo tpl in data.Templates)
                    if (tpl.ScheduleType.Length > 0 && !combo.Items.Cast<object>().Contains(tpl.ScheduleType)) combo.Items.Add(tpl.ScheduleType);
                object target = want;
                if (first) target = PstmCore.Get(settings, "default_schedule_type");
                if (target != null && combo.Items.Cast<object>().Contains(target)) combo.SelectedItem = target;
                else combo.SelectedIndex = 0;
            }
            finally
            {
                populating = false;
            }
        }

        /// <summary>A filter that hides every template is worse than no filter.</summary>
        private void GuardTypeFilter()
        {
            if (data.Templates.Count == 0) return;
            if (TemplatesInList().Count > 0) return;
            if (TypeFilter() == null) return;
            populating = true;
            try
            {
                C<ComboBox>("TemplateTypeCombo").SelectedIndex = 0;
            }
            finally
            {
                populating = false;
            }
            FillTemplateList();
            typeNote = "  No template reports that schedule type, so the list is showing every type.";
        }

        private string TypeFilter()
        {
            string chosen = C<ComboBox>("TemplateTypeCombo").SelectedItem as string ?? "";
            if (chosen.Length == 0 || chosen == AllTypes) return null;
            return chosen;
        }

        private void FillTemplateFilter(bool first)
        {
            var combo = C<ComboBox>("TemplateFilterCombo");
            object want = first ? null : combo.SelectedItem;
            populating = true;
            try
            {
                combo.Items.Clear();
                combo.Items.Add("(All configurations)");
                foreach (string name in PstmModel.ConfigChoices()) combo.Items.Add(PstmModel.PrettyEnum(name));
                object target = want;
                if (first)
                {
                    string def = PstmCore.Get(settings, "default_config");
                    target = def == "All" ? "(All configurations)" : PstmModel.PrettyEnum(def);
                }
                if (target != null && combo.Items.Cast<object>().Contains(target)) combo.SelectedItem = target;
                else combo.SelectedIndex = 0;
            }
            finally
            {
                populating = false;
            }
        }

        /// <summary>The panel configuration the template list is showing, or null.</summary>
        private string ConfigFilter()
        {
            string chosen = C<ComboBox>("TemplateFilterCombo").SelectedItem as string ?? "";
            if (chosen.Length == 0 || chosen.StartsWith("(All", StringComparison.Ordinal)) return null;
            foreach (string name in PstmModel.ConfigChoices())
                if (PstmModel.PrettyEnum(name) == chosen) return name;
            return null;
        }

        private List<TemplateInfo> TemplatesInList()
        {
            string want = ConfigFilter();
            string wantType = TypeFilter();
            string needle = (C<TextBox>("TemplateSearchBox").Text ?? "").Trim().ToLowerInvariant();
            var output = new List<TemplateInfo>();
            foreach (TemplateInfo tpl in data.Templates)
            {
                if (want != null && tpl.Config != want) continue;
                if (wantType != null && tpl.ScheduleType != wantType) continue;
                if (needle.Length > 0 && (tpl.Name ?? "").ToLowerInvariant().IndexOf(needle, StringComparison.Ordinal) < 0) continue;
                output.Add(tpl);
            }
            return output;
        }

        private void BuildDisplayMap()
        {
            displayToId.Clear();
            idToDisplay.Clear();
            var used = new HashSet<string>();
            foreach (TemplateInfo tpl in data.Templates)
            {
                string baseName = string.IsNullOrEmpty(tpl.Name) ? "(unnamed)" : tpl.Name;
                if (tpl.Slots != 0) baseName = baseName + "   -   " + tpl.Slots + " slot";
                string display = baseName;
                if (used.Contains(display.ToLowerInvariant())) display = baseName + "  [" + tpl.IdVal + "]";
                used.Add(display.ToLowerInvariant());
                displayToId[display] = tpl.IdVal;
                idToDisplay[tpl.IdVal] = display;
            }
        }

        private string DisplayOf(TemplateInfo tpl)
        {
            string d;
            return idToDisplay.TryGetValue(tpl.IdVal, out d) ? d : tpl.Name;
        }

        private void FillTemplateList()
        {
            var listbox = C<ListBox>("TemplateListBox");
            listbox.Items.Clear();
            List<TemplateInfo> shown = TemplatesInList();
            foreach (TemplateInfo tpl in shown) listbox.Items.Add(DisplayOf(tpl));
            PstmChrome.SetText(Win, "TemplateCountText", shown.Count + " of " + data.Templates.Count + " templates");
        }

        // ================================================================== filtering the panel table
        private void ApplyFilters()
        {
            string needle = (C<TextBox>("PanelSearchBox").Text ?? "").Trim().ToLowerInvariant();
            var rows = new List<PanelRow>();
            foreach (PanelRow row in data.Rows)
                if (RowPasses(row, needle)) rows.Add(row);
            rows = Sorted(rows);
            visibleRows = rows;
            C<DataGrid>("PanelGrid").ItemsSource = new List<object>(rows);
            PstmChrome.SetText(Win, "PanelCountText", rows.Count + " of " + data.Rows.Count + " shown");
            int active = headers.Values.Count(h => h.SearchText.Length > 0 || h.Allowed != null);
            PstmChrome.SetText(Win, "FilterSummaryText", active > 0 ? active + " column filters on" : "");
        }

        private string TextOf(PanelRow row, string key)
        {
            return (CellText(row, key) as string) ?? "";
        }

        private bool RowPasses(PanelRow row, string needle)
        {
            foreach (var entry in headers)
                if (!entry.Value.Passes(TextOf(row, entry.Key))) return false;
            if (needle.Length > 0)
            {
                string blob = string.Join(" ", headers.Keys.Select(k => TextOf(row, k)));
                if (blob.ToLowerInvariant().IndexOf(needle, StringComparison.Ordinal) < 0) return false;
            }
            return true;
        }

        private List<PanelRow> Sorted(List<PanelRow> rows)
        {
            string key = string.IsNullOrEmpty(sortKey) ? "panel" : sortKey;
            if (key == "panel") rows = rows.OrderBy(r => r, Comparer<PanelRow>.Create((a, b) => PstmModel.NaturalCompare(a.Name, b.Name))).ToList();
            else rows = rows.OrderBy(r => TextOf(r, key).ToLowerInvariant(), StringComparer.Ordinal).ToList();
            if (sortDesc) rows.Reverse();
            return rows;
        }

        /// <summary>Sorts the row list, not a CollectionView - the grid binds row objects.</summary>
        private void OnSort(object sender, DataGridSortingEventArgs args)
        {
            try
            {
                args.Handled = true;
                string key = args.Column.SortMemberPath;
                if (key == sortKey) sortDesc = !sortDesc;
                else
                {
                    sortKey = key;
                    sortDesc = false;
                }
                ApplyFilters();
            }
            catch (Exception)
            {
            }
        }

        private void AnyFilter()
        {
            if (populating) return;
            ApplyFilters();
        }

        private void ClearFilters()
        {
            populating = true;
            try
            {
                foreach (ColumnHeader header in headers.Values) header.Clear();
                C<TextBox>("PanelSearchBox").Text = "";
            }
            finally
            {
                populating = false;
            }
            ApplyFilters();
        }

        private void ParamPick(string key, string name)
        {
            int? index = ParamIndex(key);
            if (index == null || index.Value >= colNames.Count) return;
            if (name == DropColumn)
            {
                colNames.RemoveAt(index.Value);
                SaveColumns();
                BuildColumns();
                RebuildParamItems();
                ApplyFilters();
                Status("Column removed.");
                return;
            }
            colNames[index.Value] = name == NoParam ? "" : name;
            SaveColumns();
            ColumnHeader header;
            if (headers.TryGetValue(key, out header)) header.Clear();   // the old parameter's search text does not apply to the new one
            ApplyFilters();
        }

        private void OpenTickFilter(ColumnHeader header)
        {
            if (header.Popup != null)
            {
                try { header.Content.Children.Remove(header.Popup); } catch (Exception) { }
                header.Popup = null;
            }
            var values = new HashSet<string>();
            foreach (PanelRow row in data.Rows)
            {
                string t = TextOf(row, header.Key);
                values.Add(t.Length > 0 ? t : PstmGrid.NoValue);
            }
            List<string> ordered = values.OrderBy(s => s.ToLowerInvariant(), StringComparer.Ordinal).ToList();
            var popup = new TickFilter(header, ordered, ApplyFilters);
            header.Popup = popup.Popup;
            try { header.Content.Children.Add(popup.Popup); } catch (Exception) { }
            popup.Show();
        }

        private void TemplateFilterChanged()
        {
            if (populating) return;
            FillTemplateList();
            RefreshTemplatesTab();
            ApplyFilters();
        }

        // ================================================================== the template combo in every row
        private void ComboLoaded(object sender, RoutedEventArgs args)
        {
            var combo = sender as ComboBox ?? args.OriginalSource as ComboBox;
            if (combo == null) return;
            var row = combo.DataContext as PanelRow;
            if (row == null) return;
            populating = true;
            try
            {
                combo.Items.Clear();
                List<TemplateInfo> options = TemplatesInList();
                var ids = new HashSet<long>(options.Select(t => t.IdVal));
                TemplateInfo tpl;
                if (row.CurrentId != 0 && !ids.Contains(row.CurrentId) && data.ById.TryGetValue(row.CurrentId, out tpl))
                {
                    options.Insert(0, tpl);
                    ids.Add(tpl.IdVal);
                }
                if (row.ChosenId != 0 && !ids.Contains(row.ChosenId) && data.ById.TryGetValue(row.ChosenId, out tpl)) options.Insert(0, tpl);
                var seen = new HashSet<long>();
                foreach (TemplateInfo t in options)
                {
                    if (!seen.Add(t.IdVal)) continue;
                    combo.Items.Add(DisplayOf(t));
                }
                string want;
                idToDisplay.TryGetValue(row.ChosenId != 0 ? row.ChosenId : row.CurrentId, out want);
                if (want != null && combo.Items.Cast<object>().Contains(want)) combo.SelectedItem = want;
                else
                {
                    combo.SelectedIndex = -1;
                    combo.Tag = "no template on this panel";
                }
            }
            finally
            {
                populating = false;
            }
        }

        private void ComboChanged(object sender, SelectionChangedEventArgs args)
        {
            if (populating) return;
            var combo = sender as ComboBox ?? args.OriginalSource as ComboBox;
            if (combo == null) return;
            var row = combo.DataContext as PanelRow;
            if (row == null) return;
            string display = combo.SelectedItem as string ?? "";
            long tid;
            if (!displayToId.TryGetValue(display, out tid) || tid == 0) return;
            TemplateInfo tpl;
            string name = data.ById.TryGetValue(tid, out tpl) ? tpl.Name : display;

            // picking a template on one row of a multi row selection sets them all
            var targets = new List<PanelRow> { row };
            List<PanelRow> picked = SelectedRows();
            if (picked.Count > 1 && picked.Any(r => ReferenceEquals(r, row))) targets = picked;

            var blocked = targets.Where(t => t.Locked.Length > 0).ToList();
            foreach (PanelRow target in targets)
            {
                // queueing a change Apply could only skip would be a lie in the table, so a locked row simply does not take one
                if (target.Locked.Length > 0) continue;
                target.SetChoice(tid, name);
                // a row the user has fixed by hand is no longer one to review
                target.Status = target.Changed ? "changed" : "";
                target.Note = target.Changed ? "changed by hand" : "";
            }
            args.Handled = true;
            RefreshRows();
            UpdatePending();
            int moved = targets.Count - blocked.Count;
            PstmCore.Log("pick: " + targets.Count + " panel(s) -> '" + name + "', " + blocked.Count + " locked");
            if (blocked.Count > 0 && moved > 0) Status(moved + " panels set to \"" + name + "\". " + blocked.Count + " left alone - " + blocked[0].Locked + ".");
            else if (blocked.Count > 0) Status(blocked[0].Name + " is locked - " + blocked[0].Locked + ".");
            else if (targets.Count > 1) Status(targets.Count + " panels set to \"" + name + "\".");
        }

        private void RefreshRows()
        {
            try
            {
                C<DataGrid>("PanelGrid").Items.Refresh();
            }
            catch (Exception)
            {
                ApplyFilters();
            }
        }

        private void UpdatePending()
        {
            int count = data.Rows.Count(r => r.Changed);
            int review = data.Rows.Count(r => r.Status == "review");
            int locked = data.Rows.Count(r => r.Locked.Length > 0);
            string text = "";
            if (count > 0) text = count + " change" + (count == 1 ? "" : "s") + " waiting";
            if (review > 0) text = (text.Length > 0 ? text + "   " : "") + review + " to review";
            if (locked > 0) text = (text.Length > 0 ? text + "   " : "") + locked + " locked";
            PstmChrome.SetText(Win, "PendingText", text);
            C<Button>("ApplyButton").IsEnabled = count > 0 && !busy;
        }

        // ================================================================== Auto Assign
        private void PanelSelection()
        {
            try
            {
                C<Button>("AutoAssignSelectedButton").IsEnabled = C<DataGrid>("PanelGrid").SelectedItems.Count > 0;
            }
            catch (Exception)
            {
            }
        }

        private List<PanelRow> SelectedRows()
        {
            var output = new List<PanelRow>();
            try
            {
                foreach (object item in C<DataGrid>("PanelGrid").SelectedItems)
                {
                    var row = item as PanelRow;
                    if (row != null) output.Add(row);
                }
            }
            catch (Exception)
            {
            }
            return output;
        }

        private void AutoAssignSelected()
        {
            List<PanelRow> rows = SelectedRows();
            if (rows.Count == 0)
            {
                Status("Pick the rows you want Auto Assign to work on first.");
                return;
            }
            AutoAssign(rows);
        }

        private void AutoAssign(List<PanelRow> rows)
        {
            if (PstmCore.Get(settings, "ways_param").Length == 0 || PstmCore.Get(settings, "phases_param").Length == 0)
            {
                PstmDialogs.Info(Win, palette, "Auto Assign Template",
                                 "Set the number of ways and number of phases parameters in Settings first, then run Auto Assign again.", Version);
                return;
            }
            AssignSummary summary;
            try
            {
                summary = PstmModel.AutoAssign(data, settings, rows, ConfigFilter());
            }
            catch (Exception ex)
            {
                PstmCore.Log("auto assign failed: " + ex);
                Status("Auto Assign failed: " + ex.Message);
                return;
            }
            ApplyFilters();
            UpdatePending();
            string scope = rows == null ? "all panels" : rows.Count + " selected panel(s)";
            string message = "Auto Assign over " + scope + ": " + summary.Assigned + " set, " + summary.Already + " already right, " + summary.Review + " to review by hand.";
            if (summary.Locked > 0) message += "  " + summary.Locked + " skipped - locked by somebody else.";
            if (summary.Kept > 0) message += "  " + summary.Kept + " kept the template you picked by hand.";
            PstmCore.Log("auto assign: " + scope + " -> set " + summary.Assigned + ", already " + summary.Already + ", review " + summary.Review +
                         ", locked " + summary.Locked + ", kept " + summary.Kept);
            Status(message);
        }

        // ================================================================== right click on a template in the list
        private TemplateInfo PickedTemplate()
        {
            string display = C<ListBox>("TemplateListBox").SelectedItem as string ?? "";
            long id;
            TemplateInfo tpl;
            if (display.Length == 0 || !displayToId.TryGetValue(display, out id)) return null;
            return data.ById.TryGetValue(id, out tpl) ? tpl : null;
        }

        private void CopyTemplateName()
        {
            TemplateInfo tpl = PickedTemplate();
            if (tpl == null)
            {
                Status("Click a template in the list first.");
                return;
            }
            try
            {
                Clipboard.SetText(tpl.Name ?? "");
                Status("Copied \"" + tpl.Name + "\".");
            }
            catch (Exception ex)
            {
                Status("Could not reach the clipboard: " + ex.Message);
            }
        }

        /// <summary>
        /// Opens the picked template in Revit's own editor, then gets out of the way. Revit has no API for opening the template editor on a chosen
        /// PanelScheduleTemplate (it derives from Element, not View), so this works only where the release exposes the template as a view.
        /// </summary>
        private void EditTemplateClicked()
        {
            if (busy) return;
            TemplateInfo tpl = PickedTemplate();
            if (tpl == null)
            {
                Status("Click a template in the list first.");
                return;
            }
            editingName = tpl.Name;
            Raise(PstmOps.JobEditTemplate(doc, tpl.Id, tpl.Name), "Opening \"" + tpl.Name + "\" in Revit...", "edit");
        }

        private void FinishEdit(JobResult result)
        {
            string name = editingName.Length > 0 ? editingName : "that template";
            if (result != null && result.Ok)
            {
                Status("Opening \"" + name + "\" in Revit.");
                try { Win.Close(); } catch (Exception) { }
                return;
            }
            string note = result == null ? "" : result.Note;
            string copied = "";
            try
            {
                Clipboard.SetText(name);
                copied = "\n\nThe name is on the clipboard, so it can be pasted into the search box in that dialog.";
            }
            catch (Exception)
            {
            }
            PstmDialogs.Info(Win, palette, "Revit will not open it from here",
                             note + "\n\nOpen it by hand instead: Manage tab, Panel Schedule Templates, Edit a Template, then pick\n\n    " + name + copied, Version);
            Status("\"" + name + "\" has to be opened from Manage, Panel Schedule Templates, Edit a Template.");
        }

        // ================================================================== Regenerate Templates
        /// <summary>Pushes the current template back through every panel schedule: editing a template does not reach the schedules already made from it.</summary>
        private void RegenerateClicked()
        {
            if (busy) return;
            int count = PstmModel.InstanceViews(doc).Count;
            if (count == 0)
            {
                Status("There are no panel schedules in this project to regenerate.");
                return;
            }
            int answer = PstmDialogs.Ask(Win, palette, "Regenerate panel schedules",
                count + " panel schedule" + (count == 1 ? "" : "s") + " will be re-poured from the template each one is already on, so the schedules placed on " +
                "sheets show current information.\n\nNo template is assigned or changed by this, and no panel moves onto a different template.\n\n" +
                "Worth knowing: re-pouring a schedule takes its layout from the template, so anything moved about on an individual schedule by hand goes back " +
                "to what the template says.\n\nOn a project this size it takes a while - sync first and make a cup of tea.",
                PstmDialogs.Buttons("Cancel", "ghost", "Regenerate", "primary"), "orange", Version);
            if (answer != 1) return;
            Raise(PstmOps.JobRegenerate(doc, Progress), "Regenerating " + count + " panel schedule(s)...", "regenerate");
        }

        private void ResetClicked()
        {
            foreach (PanelRow row in data.Rows) row.ResetChoice();
            ApplyFilters();
            UpdatePending();
            Status("Changes cleared. Nothing has been written to the model.");
        }

        // ================================================================== Apply
        private void ApplyClicked()
        {
            if (busy) return;
            List<PanelRow> changed = data.Rows.Where(r => r.Changed && r.Locked.Length == 0).ToList();
            List<PanelRow> held = data.Rows.Where(r => r.Changed && r.Locked.Length > 0).ToList();
            if (changed.Count == 0)
            {
                if (held.Count > 0) Status(held.Count + " panel(s) have changes waiting but are locked by somebody else - nothing to apply.");
                return;
            }
            if (PstmCore.AsBool(PstmCore.Get(settings, "confirm_apply"), true))
            {
                var preview = new List<string>();
                foreach (PanelRow row in changed.Take(14)) preview.Add("  " + row.Name + "   ->   " + (row.ChosenName.Length > 0 ? row.ChosenName : "(none)"));
                int more = changed.Count - preview.Count;
                if (more > 0) preview.Add("  ... and " + more + " more");
                string heldNote = held.Count > 0 ? "\n\n" + held.Count + " more are locked by somebody else and will be left alone." : "";
                int answer = PstmDialogs.Ask(Win, palette, "Apply template changes",
                    changed.Count + " panel" + (changed.Count == 1 ? "" : "s") + " will be moved onto a different panel schedule template.\n\n" +
                    string.Join("\n", preview) + "\n\nNothing else in the model is touched." + heldNote,
                    PstmDialogs.Buttons("Cancel", "ghost", "Apply", "primary"), "orange", Version);
                if (answer != 1) return;
            }
            var jobs = new List<MoveJob>();
            applyWanted = new Dictionary<long, KeyValuePair<long, string>>();
            foreach (PanelRow row in changed)
            {
                if (row.Locked.Length > 0) continue;
                jobs.Add(new MoveJob { PanelId = row.Id, ViewId = row.ViewId, TemplateId = IdOf(row.ChosenId), Label = row.Name });
                applyWanted[row.IdVal] = new KeyValuePair<long, string>(row.ChosenId, row.Name);
            }
            bool rebuild = PstmCore.AsBool(PstmCore.Get(settings, "rebuild_schedule"), true);
            PstmCore.Log("apply: " + jobs.Count + " panel(s), rebuild " + rebuild + ", " + held.Count + " locked and held");
            Raise(PstmOps.JobApplyAssignments(doc, jobs, Progress, rebuild), "Applying " + jobs.Count + " template change(s)...", "apply");
        }

        private ElementId IdOf(long idValue)
        {
            TemplateInfo tpl;
            return data.ById.TryGetValue(idValue, out tpl) ? tpl.Id : null;
        }

        // ================================================================== Template Duplicator tab
        private void RefreshTemplatesTab()
        {
            templateView = DupFiltered();
            C<DataGrid>("TemplateGrid").ItemsSource = new List<object>(templateView);
            int unused = data.Templates.Count(t => t.UsedCount == 0);
            PstmChrome.SetText(Win, "DupCountText", templateView.Count + " shown, " + unused + " of " + data.Templates.Count + " not used anywhere");
            FillMergeTargets();
        }

        private List<TemplateInfo> DupFiltered()
        {
            string needle = (C<TextBox>("DupSearchBox").Text ?? "").Trim().ToLowerInvariant();
            bool unusedOnly = C<CheckBox>("UnusedOnlyCheck").IsChecked == true;
            bool useFilters = C<CheckBox>("DupUseFiltersCheck").IsChecked == true;
            string wantType = useFilters ? TypeFilter() : null;
            string wantConfig = useFilters ? ConfigFilter() : null;
            var bits = new List<string>();
            if (wantType != null) bits.Add(wantType);
            if (wantConfig != null) bits.Add(PstmModel.PrettyEnum(wantConfig));
            PstmChrome.SetText(Win, "DupFilterText", bits.Count > 0 ? "showing " + string.Join(", ", bits) : "");
            var output = new List<TemplateInfo>();
            foreach (TemplateInfo tpl in data.Templates)
            {
                if (wantType != null && tpl.ScheduleType != wantType) continue;
                if (wantConfig != null && tpl.Config != wantConfig) continue;
                if (unusedOnly && tpl.UsedCount > 0) continue;
                if (needle.Length > 0 && (tpl.Name ?? "").ToLowerInvariant().IndexOf(needle, StringComparison.Ordinal) < 0) continue;
                output.Add(tpl);
            }
            return output;
        }

        private void DupFilterChanged()
        {
            if (populating) return;
            RefreshTemplatesTab();
        }

        private List<TemplateInfo> SelectedTemplates()
        {
            var output = new List<TemplateInfo>();
            try
            {
                foreach (object item in C<DataGrid>("TemplateGrid").SelectedItems)
                {
                    var t = item as TemplateInfo;
                    if (t != null) output.Add(t);
                }
            }
            catch (Exception)
            {
            }
            return output;
        }

        /// <summary>Leads the eye to Duplicate once exactly one template is picked.</summary>
        private void FillMergeTargets()
        {
            List<TemplateInfo> picked = SelectedTemplates();
            var button = C<Button>("DuplicateButton");
            try
            {
                if (picked.Count == 1) button.SetResourceReference(FrameworkElement.StyleProperty, "PrimaryButton");
                else button.ClearValue(FrameworkElement.StyleProperty);
            }
            catch (Exception)
            {
            }
            try
            {
                C<Button>("MergeTemplatesButton").IsEnabled = picked.Count > 1;
                C<Button>("RenameTemplatesButton").IsEnabled = picked.Count > 0;
            }
            catch (Exception)
            {
            }
        }

        private void DeleteClicked()
        {
            if (busy) return;
            List<TemplateInfo> picked = SelectedTemplates();
            if (picked.Count == 0)
            {
                Status("Pick the templates to delete first.");
                return;
            }
            List<TemplateInfo> inUse = picked.Where(t => t.UsedCount > 0).ToList();
            IEnumerable<string> lines = picked.Take(16).Select(t => "  " + t.Name + "   -   " + (t.UsedCount == 0 ? "not used" : t.UsedCount + " panel(s) use it"));
            string warning = inUse.Count > 0
                ? "\n\n" + inUse.Count + " of these are still in use. Deleting a template a panel is using changes that panel schedule."
                : "";
            int answer = PstmDialogs.Ask(Win, palette, "Delete templates",
                "These " + picked.Count + " template(s) will be deleted from the project:\n\n" + string.Join("\n", lines) + warning,
                PstmDialogs.Buttons("Cancel", "ghost", "Delete", "danger"), "red", Version);
            if (answer != 1) return;
            var items = picked.Select(t => new LabelledId { Id = t.Id, Label = t.Name }).ToList();
            PstmCore.Log("delete: " + items.Count + " template(s)");
            Raise(PstmOps.JobDelete(doc, items, Progress), "Deleting " + items.Count + " template(s)...", "delete");
        }

        private void MergeClicked()
        {
            if (busy) return;
            List<TemplateInfo> picked = SelectedTemplates();
            if (picked.Count < 2)
            {
                Status("Pick two or more templates to merge.");
                return;
            }
            List<string> options = picked.Select(DisplayOf).ToList();
            string display = PstmDialogs.Choose(Win, palette, "Merge templates",
                "Which template to merge to?\n\nEvery panel using the others moves onto the one you pick, and the emptied templates are then deleted.",
                options, "Merge", Version);
            if (string.IsNullOrEmpty(display)) return;
            long targetId;
            TemplateInfo target;
            if (!displayToId.TryGetValue(display, out targetId) || !data.ById.TryGetValue(targetId, out target))
            {
                Status("Could not work out which template you picked.");
                return;
            }
            List<TemplateInfo> others = picked.Where(t => t.IdVal != target.IdVal).ToList();
            if (others.Count == 0)
            {
                Status("Choose a merge target that is not the only one picked.");
                return;
            }
            var otherIds = new HashSet<long>(others.Select(t => t.IdVal));
            List<PanelRow> moving = data.Rows.Where(r => otherIds.Contains(r.CurrentId)).ToList();
            int answer = PstmDialogs.Ask(Win, palette, "Merge templates",
                "Are you sure you know what you are doing you crazy person!\n\n" + others.Count + " template(s) are about to be merged into \"" + target.Name + "\".\n" +
                moving.Count + " panel(s) move onto it, and the " + others.Count + " emptied template(s) are then deleted from the project.\n\n" +
                "This one cannot be undone from inside the tool - only with Revit's own undo.",
                PstmDialogs.Buttons("Cancel", "ghost", "Yes, merge them", "danger"), "red", Version);
            if (answer != 1) return;
            var moves = moving.Select(r => new MoveJob { PanelId = r.Id, ViewId = r.ViewId, TemplateId = target.Id, Label = r.Name }).ToList();
            var removals = others.Select(t => new LabelledId { Id = t.Id, Label = t.Name }).ToList();
            bool rebuild = PstmCore.AsBool(PstmCore.Get(settings, "rebuild_schedule"), true);
            PstmCore.Log("merge: " + others.Count + " template(s) into '" + target.Name + "', " + moves.Count + " panel(s) move");
            Raise(PstmOps.JobMerge(doc, moves, removals, Progress, rebuild), "Merging " + others.Count + " template(s)...", "merge");
        }

        private void RenameClicked()
        {
            if (busy) return;
            List<TemplateInfo> picked = SelectedTemplates();
            if (picked.Count == 0)
            {
                Status("Pick the templates you want to rename first.");
                return;
            }
            List<KeyValuePair<string, string>> pairs = PstmDialogs.Rename(Win, palette, picked.Select(t => t.Name).ToList(), Version);
            if (pairs == null || pairs.Count == 0) return;
            var byName = new Dictionary<string, TemplateInfo>();
            foreach (TemplateInfo tpl in picked) byName[tpl.Name] = tpl;
            var jobs = new List<KeyValuePair<Element, string>>();
            foreach (var pair in pairs)
            {
                TemplateInfo tpl;
                if (byName.TryGetValue(pair.Key, out tpl)) jobs.Add(new KeyValuePair<Element, string>(tpl.Element, pair.Value));
            }
            if (jobs.Count == 0) return;
            List<string> taken = data.Templates.Select(t => t.Name).ToList();
            PstmCore.Log("rename: " + jobs.Count + " template(s)");
            Raise(PstmOps.JobRenameMany(doc, jobs, taken, Progress), "Renaming " + jobs.Count + " template(s)...", "rename");
        }

        private void DuplicateClicked()
        {
            List<TemplateInfo> picked = SelectedTemplates();
            if (picked.Count != 1)
            {
                Status("Pick one template to duplicate.");
                return;
            }
            dupSource = picked[0];
            C<UIElement>("DupPlaceholder").Visibility = Visibility.Collapsed;
            C<UIElement>("DupPanel").Visibility = Visibility.Visible;
            PstmChrome.SetText(Win, "DupSourceText", "From \"" + dupSource.Name + "\" - " + (dupSource.ScheduleType.Length > 0 ? dupSource.ScheduleType : "panel schedule") + ", " +
                                                      (dupSource.ConfigPretty.Length > 0 ? dupSource.ConfigPretty : "as drawn") +
                                                      (dupSource.Slots != 0 ? ", " + dupSource.Slots + " slot" : ""));
            populating = true;
            try
            {
                C<TextBox>("DupBaseName").Text = dupSource.Name;
                var combo = C<ComboBox>("DupConfigCombo");
                combo.Items.Clear();
                foreach (string name in PstmModel.ConfigChoices()) combo.Items.Add(PstmModel.PrettyEnum(name));
                string want = PstmModel.PrettyEnum(dupSource.Config);
                if (want.Length > 0 && combo.Items.Cast<object>().Contains(want)) combo.SelectedItem = want;
                else if (combo.Items.Count > 0) combo.SelectedIndex = 0;
                C<CheckBox>("DupSinglePhaseCheck").IsChecked = dupSource.SinglePhase;
                // the source decides how many slots a way is, so the list is rebuilt for it rather than left offering multiples of three
                FillSlotList(new List<int>());
            }
            finally
            {
                populating = false;
            }
            DupPreview();
        }

        /// <summary>Slots per way for whatever the duplicator is set to build: a single phase way takes one slot, not three.</summary>
        private int PerWay()
        {
            bool single = false;
            try { single = C<CheckBox>("DupSinglePhaseCheck").IsChecked == true; } catch (Exception) { }
            return PstmCore.SlotsPerWay(single);
        }

        /// <summary>Slot counts as a plain list, so click / shift click / ctrl click all behave the way they do everywhere else in Windows.</summary>
        private void FillSlotList(List<int> keep = null)
        {
            var listbox = C<ListBox>("SlotList");
            var keepSet = new HashSet<int>(keep ?? new List<int>());
            int perWay = PerWay();
            bool wasPopulating = populating;
            populating = true;
            try
            {
                listbox.Items.Clear();
                slotItems.Clear();
                slotLookup.Clear();
                PstmChrome.SetText(Win, "SlotRuleText", perWay == 1
                    ? "Single phase: one way is one slot, so the list counts up in ones."
                    : "Three phase: one way is " + perWay + " slots, so the list counts up in " + perWay + "s.");
                foreach (int number in PstmCore.SlotOptions(settings, perWay))
                {
                    int ways = PstmCore.WaysFromSlots(number, perWay);
                    string display = number + " slot" + (number == 1 ? "" : "s") + "   -   " + ways + " way" + (ways == 1 ? "" : "s");
                    slotItems.Add(new KeyValuePair<int, string>(number, display));
                    slotLookup[display] = number;
                    listbox.Items.Add(display);
                }
                SelectSlots(keepSet);
            }
            finally
            {
                populating = wasPopulating;
            }
            DupPreview();
        }

        /// <summary>Keeps the same number of WAYS when the phase setting changes: 12 ways on three phase is 12 slots, not 36, on single phase.</summary>
        private void SinglePhaseClicked()
        {
            if (populating) return;
            int old = PerWay();
            // the tick has already flipped, so the old step is the other one
            int previous = old != 1 ? 1 : PstmCore.SlotsPerWayThreePhase;
            var wanted = new List<int>();
            foreach (int slots in ChosenSlots()) wanted.Add(PstmCore.WaysFromSlots(slots, previous) * old);
            FillSlotList(wanted);
        }

        private void SelectSlots(ISet<int> wanted)
        {
            var listbox = C<ListBox>("SlotList");
            try
            {
                listbox.SelectedItems.Clear();
                foreach (var item in slotItems)
                    if (wanted.Contains(item.Key)) listbox.SelectedItems.Add(item.Value);
            }
            catch (Exception)
            {
            }
        }

        private List<int> ChosenSlots()
        {
            var output = new List<int>();
            try
            {
                foreach (object item in C<ListBox>("SlotList").SelectedItems)
                {
                    int number;
                    if (slotLookup.TryGetValue(item as string ?? "", out number) && number != 0) output.Add(number);
                }
            }
            catch (Exception)
            {
            }
            output.Sort();
            return output;
        }

        private void SlotsCommon()
        {
            int perWay = PerWay();
            SelectSlots(new HashSet<int>(slotItems.Where(i =>
            {
                int ways = PstmCore.WaysFromSlots(i.Key, perWay);
                return ways >= 4 && ways <= 16;
            }).Select(i => i.Key)));
        }

        /// <summary>
        /// Each copy is named for its ways, as a suffix (a 36 slot board is a 12 way board, so the copy gets "12 Ways" on the end). A name that already
        /// exists gets "New" after that rather than overwriting anything, and the word "Master" is taken out on the way: a copy is not the master.
        /// </summary>
        private List<KeyValuePair<int, string>> DupNames()
        {
            string baseName = (C<TextBox>("DupBaseName").Text ?? "").Trim();
            if (baseName.Length == 0 && dupSource != null) baseName = dupSource.Name;
            var taken = new HashSet<string>(data.Templates.Select(t => (t.Name ?? "").ToLowerInvariant()));
            int perWay = PerWay();
            var output = new List<KeyValuePair<int, string>>();
            foreach (int slots in ChosenSlots())
            {
                int ways = PstmCore.WaysFromSlots(slots, perWay);
                string name = PstmCore.UniqueName(PstmCore.NameWithWays(baseName, ways), taken);
                taken.Add(name.ToLowerInvariant());
                output.Add(new KeyValuePair<int, string>(slots, name));
            }
            return output;
        }

        private void DupPreview()
        {
            if (populating) return;
            List<KeyValuePair<int, string>> names = DupNames();
            var button = C<Button>("CreateButton");
            button.IsEnabled = names.Count > 0 && !busy;
            button.Content = names.Count == 0 ? "Create" : "Create " + names.Count + " template" + (names.Count == 1 ? "" : "s");
            var preview = C<TextBlock>("DupPreviewText");
            if (names.Count == 0)
            {
                preview.Text = "Pick one or more slot counts above.";
                return;
            }
            var shown = names.Take(6).Select(p => "  " + p.Value + "   (" + p.Key + " slots)").ToList();
            if (names.Count > 6) shown.Add("  ... and " + (names.Count - 6) + " more");
            preview.Text = "Will create:\n" + string.Join("\n", shown);
        }

        private void CreateClicked()
        {
            if (busy || dupSource == null) return;
            List<KeyValuePair<int, string>> names = DupNames();
            if (names.Count == 0) return;
            if (names.Count > 5)
            {
                int answer = PstmDialogs.Ask(Win, palette, "This will take a while",
                    "WARNING, this process takes some time if you selected a lot, I advise you SYNC the model before running and make a cup of tea.\n\n" +
                    names.Count + " templates are about to be created.",
                    PstmDialogs.Buttons("Cancel", "ghost", "Go on then", "primary"), "orange", Version);
                if (answer != 1) return;
            }
            string configName = C<ComboBox>("DupConfigCombo").SelectedItem as string ?? "";
            PanelConfiguration? configValue = null;
            foreach (string name in PstmModel.ConfigChoices())
            {
                if (PstmModel.PrettyEnum(name) == configName)
                {
                    configValue = PstmModel.ConfigValue(name);
                    break;
                }
            }
            var flags = new Dictionary<string, bool>(dupSource.Flags);
            flags["IsPanelSinglePhase"] = C<CheckBox>("DupSinglePhaseCheck").IsChecked == true;
            var taken = new HashSet<string>(data.Templates.Select(t => (t.Name ?? "").ToLowerInvariant()));
            var specs = names.Select(n => new DuplicateSpec { Slots = n.Key, Name = n.Value, Config = configValue, Flags = flags }).ToList();
            bool copyLayout = C<CheckBox>("DupCopyLayoutCheck").IsChecked == true;
            PstmCore.Log("create: " + specs.Count + " template(s) from '" + dupSource.Name + "', config " + configName + ", single phase " + flags["IsPanelSinglePhase"] +
                         ", copy layout " + copyLayout);
            Raise(PstmOps.JobDuplicate(doc, dupSource.Element, specs, taken, copyLayout, Progress), "Creating " + specs.Count + " template(s)...", "create");
        }

        // ================================================================== running a job through the external event
        private void Raise(PstmJob job, string message, string label)
        {
            SetBusy(true);
            pendingLabel = label;
            handler.Job = job;
            C<Button>("ApplyButton").IsEnabled = false;
            C<Button>("CreateButton").IsEnabled = false;
            C<Button>("RegenerateButton").IsEnabled = false;
            ProgressOpen(message);
            Status(message);
            PstmCore.Log("job: " + label + " raised");
            try
            {
                ev.Raise();
            }
            catch (Exception ex)
            {
                SetBusy(false);
                ProgressClose();
                UpdatePending();
                DupPreview();
                Status("Could not reach Revit: " + ex.Message);
            }
        }

        private void JobDone(JobResult result, string error)
        {
            try
            {
                Win.Dispatcher.Invoke(new Action(() => Finish(result, error)));
            }
            catch (Exception)
            {
                Finish(result, error);
            }
        }

        private static string Capitalise(string s)
        {
            return string.IsNullOrEmpty(s) ? s : char.ToUpperInvariant(s[0]) + s.Substring(1);
        }

        private void Finish(JobResult result, string error)
        {
            SetBusy(false);
            ProgressClose();
            string label = pendingLabel;
            if (!string.IsNullOrEmpty(error))
            {
                PstmCore.Log("job: " + label + " FAILED: " + error);
                Status(Capitalise(label) + " failed: " + error);
                string headline, body;
                if (label == "apply" || label == "merge")
                {
                    // these run in pieces, so some of it may well have landed
                    headline = "The run stopped early";
                    body = "The " + label + " stopped on something Revit would not do. Panels it had already finished are written; the one it stopped on and anything after it are not.\n\n" +
                           error + "\n\nRe-reading the model now - whatever is still outstanding will show as waiting for Apply again.";
                }
                else
                {
                    headline = "Nothing was changed";
                    body = "Revit refused the " + label + ", so the whole transaction was rolled back and the model is exactly as it was.\n\n" + error;
                }
                PstmDialogs.Info(Win, palette, headline, body, Version);
                Refresh(false, true);
                UpdatePending();
                DupPreview();
                return;
            }
            if (label == "edit")
            {
                FinishEdit(result);
                return;
            }
            result = result ?? new JobResult();
            string summary = Summarise(label, result);
            if (label == "create") SelectSlots(new HashSet<int>());
            // keep_changes: a delete or a create on the other tab must not quietly drop assignments that are still waiting for Apply
            Refresh(false, true);
            DupPreview();
            if (label == "create") summary += CheckCreated(result.Ids, result.Names);
            var stayed = new List<KeyValuePair<string, string>>();
            if (label == "apply") summary = CheckApplied(summary, out stayed);
            List<KeyValuePair<string, string>> failed = result.Failed.ToList();
            List<KeyValuePair<string, string>> noted = result.Made.Where(m => !string.IsNullOrEmpty(m.Value)).ToList();
            noted.AddRange(result.Notes);
            List<KeyValuePair<string, string>> held = result.Locked;
            // a panel that failed in the job and is also still on its old template is one problem, not two - and a locked one is already accounted for
            var seen = new HashSet<string>(failed.Select(f => f.Key));
            foreach (var h in held) seen.Add(h.Key);
            failed.AddRange(stayed.Where(s => !seen.Contains(s.Key)));
            if (held.Count > 0) summary += "  " + held.Count + " left alone - locked by somebody else.";
            PstmCore.Log("job: " + label + " done - " + summary.Replace("\n", " ") + " (failed " + failed.Count + ", noted " + noted.Count + ", locked " + held.Count + ")");
            foreach (var f in failed.Take(12)) PstmCore.Log("  failed: " + f.Key + ": " + f.Value);
            if (failed.Count > 0 || noted.Count > 0 || held.Count > 0)
            {
                var lines = new List<string>();
                if (held.Count > 0)
                {
                    lines.Add("These are locked and were left alone:");
                    lines.AddRange(held.Take(12).Select(h => "  " + h.Key + ": " + h.Value));
                    if (held.Count > 12) lines.Add("  ... and " + (held.Count - 12) + " more");
                    if (failed.Count > 0 || noted.Count > 0) lines.Add("");
                }
                if (failed.Count > 0)
                {
                    lines.Add(label == "apply" ? "These did not go through:" : "These were skipped:");
                    lines.AddRange(failed.Take(12).Select(f => "  " + f.Key + ": " + f.Value));
                    if (failed.Count > 12) lines.Add("  ... and " + (failed.Count - 12) + " more");
                }
                if (noted.Count > 0)
                {
                    if (lines.Count > 0) lines.Add("");
                    lines.Add("These went through, with something to note:");
                    lines.AddRange(noted.Take(12).Select(n => "  " + n.Key + ": " + n.Value));
                    if (noted.Count > 12) lines.Add("  ... and " + (noted.Count - 12) + " more");
                }
                string title = held.Count > 0 && failed.Count == 0 ? "Some panels were left alone" : "Some of it did not go through";
                PstmDialogs.Info(Win, palette, title, summary + "\n\n" + string.Join("\n", lines), Version);
            }
            Status(summary);
        }

        /// <summary>Reads the model back and sees which panels really moved: the job's own count says how many calls Revit accepted, which is not the same question.</summary>
        private string CheckApplied(string summary, out List<KeyValuePair<string, string>> stayed)
        {
            stayed = new List<KeyValuePair<string, string>>();
            if (applyWanted.Count == 0) return summary;
            int moved = 0;
            foreach (PanelRow row in data.Rows)
            {
                KeyValuePair<long, string> pair;
                if (!applyWanted.TryGetValue(row.IdVal, out pair)) continue;
                if (row.CurrentId == pair.Key) moved++;
                else
                {
                    TemplateInfo on;
                    stayed.Add(new KeyValuePair<string, string>(pair.Value, "still on \"" + (data.ById.TryGetValue(row.CurrentId, out on) ? on.Name : "no template") + "\""));
                }
            }
            applyWanted = new Dictionary<long, KeyValuePair<long, string>>();
            if (stayed.Count > 0) summary = "Apply: " + moved + " of " + (moved + stayed.Count) + " panel(s) really moved - " + stayed.Count + " did not.";
            else summary = "Apply: " + moved + " panel(s) moved onto a new template, checked against the model.";
            return summary;
        }

        /// <summary>
        /// Proves the new templates are really in the model, and shows them. "It says it created them but they are not there" is one of three things:
        /// the element never landed, a filter is hiding it, or this check itself is wrong - so it looks by id AND by name.
        /// </summary>
        private string CheckCreated(List<long> ids, List<string> names)
        {
            if (ids.Count == 0) return "";
            var byName = new Dictionary<string, long>();
            foreach (TemplateInfo tpl in data.Templates) byName[(tpl.Name ?? "").ToLowerInvariant()] = tpl.IdVal;
            List<string> named = (names ?? new List<string>()).Select(n => n.ToLowerInvariant()).Where(n => byName.ContainsKey(n)).ToList();
            List<long> missing = ids.Where(i => !data.ById.ContainsKey(i)).ToList();
            List<long> found = ids.Where(i => data.ById.ContainsKey(i)).ToList();
            if (missing.Count > 0 && named.Count > 0)
            {
                // they are in the model, just not under the ids we captured
                foreach (string n in named)
                    if (!found.Contains(byName[n])) found.Add(byName[n]);
                missing.Clear();
            }
            if (missing.Count > 0 && found.Count == 0)
                return "  None of them are in the model after re-reading - Revit took the call but kept nothing.";
            string note = "";
            if (missing.Count > 0) note += "  " + missing.Count + " of them are not in the model after re-reading.";
            // if the duplicator view would hide them, stop hiding them
            var visible = new HashSet<long>(DupFiltered().Select(t => t.IdVal));
            List<long> hidden = found.Where(i => !visible.Contains(i)).ToList();
            if (hidden.Count > 0)
            {
                populating = true;
                try
                {
                    C<CheckBox>("DupUseFiltersCheck").IsChecked = false;
                    C<TextBox>("DupSearchBox").Text = "";
                    C<CheckBox>("UnusedOnlyCheck").IsChecked = false;
                }
                finally
                {
                    populating = false;
                }
                RefreshTemplatesTab();
                note += "  " + hidden.Count + " of them did not match the filters, so the filters have been turned off to show them.";
            }
            SelectTemplates(found);
            return note;
        }

        /// <summary>Picks the given templates in the duplicator list and scrolls to them.</summary>
        private void SelectTemplates(List<long> ids)
        {
            var wanted = new HashSet<long>(ids ?? new List<long>());
            if (wanted.Count == 0) return;
            var gridCtrl = C<DataGrid>("TemplateGrid");
            try
            {
                gridCtrl.SelectedItems.Clear();
                TemplateInfo first = null;
                foreach (TemplateInfo tpl in templateView)
                {
                    if (!wanted.Contains(tpl.IdVal)) continue;
                    gridCtrl.SelectedItems.Add(tpl);
                    if (first == null) first = tpl;
                }
                if (first != null) gridCtrl.ScrollIntoView(first);
            }
            catch (Exception)
            {
            }
        }

        private static string Summarise(string label, JobResult result)
        {
            int done = result.Done.Count, made = result.Made.Count, removed = result.Removed.Count, failed = result.Failed.Count;
            var bits = new List<string>();
            if (label == "regenerate")
            {
                string line = done + " of " + result.Total + " panel schedule(s) regenerated";
                if (result.OnSheet > 0) line += " - " + result.OnSheet + " of them are on sheets";
                if (failed > 0) line += ", " + failed + " skipped";
                return "Regenerate: " + line + ".";
            }
            if (done > 0)
            {
                if (label == "rename") bits.Add(done + " template(s) renamed");
                else bits.Add(done + " panel(s) moved onto a new template");
            }
            if (made > 0) bits.Add(made + " template(s) created");
            if (removed > 0) bits.Add(removed + " template(s) deleted");
            if (failed > 0) bits.Add(failed + " skipped");
            if (bits.Count == 0) bits.Add("nothing to do");
            return Capitalise(label) + ": " + string.Join(", ", bits) + ".";
        }

        // ================================================================== progress
        private void ProgressOpen(string text)
        {
            try
            {
                C<UIElement>("ProgressBand").Visibility = Visibility.Visible;
                C<ProgressBar>("ProgressBarMain").Value = 0;
                PstmChrome.SetText(Win, "ProgressPercent", "0%");
                PstmChrome.SetText(Win, "ProgressText", text);
                Pump();
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Called from the job, which runs on Revit's thread - the same thread WPF draws on - so the bar has to be pumped by hand or it never moves.</summary>
        private void Progress(int done, int total, string label)
        {
            try
            {
                int percent = total == 0 ? 100 : (int)Math.Round(100.0 * done / total);
                percent = Math.Max(0, Math.Min(100, percent));
                C<ProgressBar>("ProgressBarMain").Value = percent;
                PstmChrome.SetText(Win, "ProgressPercent", percent + "%");
                if (!string.IsNullOrEmpty(label)) PstmChrome.SetText(Win, "ProgressText", label + "  (" + Math.Min(done + 1, total) + " of " + total + ")");
                Pump();
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Lets the bar repaint while the job holds the UI thread. Dispatcher.Invoke from the dispatcher's own thread pushes a message frame that also
        /// dispatches real mouse and key messages, so the window is made deaf for the duration of a job (see SetBusy) and every handler that could still
        /// be reached checks busy.
        /// </summary>
        private void Pump()
        {
            try
            {
                Win.Dispatcher.Invoke(DispatcherPriority.Render, new Action(() => { }));
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Makes the window deaf for the length of a job - all but the shrink button, so a long Apply can be put away while Revit is watched.</summary>
        private void SetBusy(bool value)
        {
            busy = value;
            bool live = !busy;
            var header = (FrameworkElement)Win.FindName("HeaderBar");
            try
            {
                foreach (UIElement child in ((Panel)header.Parent).Children)
                    if (!ReferenceEquals(child, header)) child.IsHitTestVisible = live;
            }
            catch (Exception)
            {
                try { Win.IsHitTestVisible = live; } catch (Exception) { }
            }
            foreach (string name in BusyDeaf)
            {
                try { C<UIElement>(name).IsHitTestVisible = live; } catch (Exception) { }
            }
            try
            {
                // Apply and Create are re-enabled by what they depend on; this one depends on nothing
                C<Button>("RegenerateButton").IsEnabled = !busy;
            }
            catch (Exception)
            {
            }
            Drawer.Busy = busy;
        }

        private void ProgressClose()
        {
            try
            {
                C<UIElement>("ProgressBand").Visibility = Visibility.Collapsed;
            }
            catch (Exception)
            {
            }
        }

        private void Status(string text)
        {
            try
            {
                PstmChrome.SetText(Win, "StatusText", text);
            }
            catch (Exception)
            {
            }
        }

        // ================================================================== window level
        private void ToggleTheme()
        {
            if (busy) return;
            palette = PstmTheme.Other(palette);
            PstmTheme.Apply(Win, palette);
            settings["theme"] = palette;
            PstmCore.SaveSettings(settings);
            SetThemeChip();
            RefreshRows();
            try { C<DataGrid>("TemplateGrid").Items.Refresh(); } catch (Exception) { }
        }

        private void ToggleFull()
        {
            if (Drawer.Parked)
            {
                // full screen on a window nobody can see would only hide it again
                Drawer.Expand();
                return;
            }
            if (busy) return;
            full.Toggle();
            SetFullGlyph();
        }

        private void OpenSettings()
        {
            if (busy) return;
            // the configured parameters go into the list even when the panels in this project do not carry them, or Save would silently repoint them
            var names = data.ParamNames.ToList();
            foreach (string key in new[] { "ways_param", "phases_param" })
            {
                string value = PstmCore.Get(settings, key);
                if (value.Length > 0 && !names.Contains(value)) names.Insert(0, value);
            }
            var dialog = new PstmSettingsWindow(Win, settings, names, PstmModel.ConfigChoices(), PstmModel.ScheduleTypes);
            Dictionary<string, string> values;
            if (!dialog.Show(out values)) return;
            settings = values;
            colNames = PstmCore.ColumnsAfterSettings(colNames, settings);
            SaveColumns();
            BuildColumns();
            if (PstmCore.Get(settings, "theme") != palette)
            {
                palette = PstmCore.Get(settings, "theme");
                PstmTheme.Apply(Win, palette);
                SetThemeChip();
            }
            FillSlotList(ChosenSlots());
            Refresh(true, true);
            Status("Settings saved.");
        }

        private void RefreshClicked()
        {
            if (busy) return;
            if (data.Rows.Any(r => r.Changed))
            {
                int answer = PstmDialogs.Ask(Win, palette, "Re-read the model",
                    "There are changes waiting for Apply. Re-reading keeps them where the panel is still in the model.",
                    PstmDialogs.Buttons("Cancel", "ghost", "Re-read", "accent"), "orange", Version);
                if (answer != 1) return;
            }
            Refresh(false, true);
        }

        private void OnKey(object sender, KeyEventArgs args)
        {
            // Escape, Enter and F11 have already brought a parked bar back, and nothing else on a bar has anything to do
            if (Drawer.Parked) return;
            if (busy) return;
            try
            {
                if (args.Key == Key.F5)
                {
                    Refresh(false, true);
                    args.Handled = true;
                }
                else if (args.Key == Key.F11)
                {
                    full.Toggle();
                    SetFullGlyph();
                    args.Handled = true;
                }
                else if (args.Key == Key.Escape && full.IsFull)
                {
                    full.Leave();
                    SetFullGlyph();
                    args.Handled = true;
                }
            }
            catch (Exception)
            {
            }
        }

        private void CloseClicked()
        {
            if (busy) return;
            if (data.Rows.Any(r => r.Changed))
            {
                int answer = PstmDialogs.Ask(Win, palette, "Close without applying",
                    "There are changes waiting for Apply. Closing drops them - nothing has been written to the model.",
                    PstmDialogs.Buttons("Stay open", "ghost", "Close anyway", "danger"), "orange", Version);
                if (answer != 1) return;
            }
            try { Win.Close(); } catch (Exception) { }
        }

        public void Show()
        {
            PstmChrome.OwnByRevit(Win, uiapp);
            Win.Show();
        }
    }
}
