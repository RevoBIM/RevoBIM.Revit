using System;
using System.Collections.Generic;
using System.Data;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsWindow
    {
        public partial class ProSheetsWindow
        {
            // ==================================================================
            // filling the table
            // ==================================================================

            internal void FillTable()
            {
                SuspendTicks = true;
                try
                {
                    HashSet<string> ticked = TickedKeys();
                    // First fill after the tool opens: whatever was selected in
                    // Revit arrives ticked.
                    if (FirstFill && PreselectedKeys.Count > 0)
                    {
                        ticked = new HashSet<string>(ticked, StringComparer.Ordinal);
                        foreach (long key in PreselectedKeys)
                            ticked.Add(key.ToString(Inv));
                    }
                    Table.Rows.Clear();
                    for (int index = 0; index < Rows.Count; index++)
                    {
                        PsModel.Row row = Rows[index];
                        DataRow entry = Table.NewRow();
                        entry["sel"] = ticked.Contains(row.Key.ToString(Inv));
                        entry["num"] = row.Number ?? "";
                        entry["name"] = row.Name ?? "";
                        entry["rev"] = row.Revision ?? "";
                        entry["size"] = row.Size ?? "";
                        entry["fname"] = "";
                        entry["key"] = row.Key.ToString(Inv);
                        entry["vis"] = "1";
                        entry["show"] = "1";
                        entry["gid"] = "";
                        entry["grp"] = "";
                        entry["ord"] = index.ToString("D6", Inv) + "\x01";
                        Table.Rows.Add(entry);
                    }
                    FirstFill = false;
                }
                finally
                {
                    SuspendTicks = false;
                }
            }

            internal HashSet<string> TickedKeys()
            {
                var found = new HashSet<string>(StringComparer.Ordinal);
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        if (B(entry["sel"]) && !string.IsNullOrEmpty(S(entry["key"])))
                            found.Add(S(entry["key"]));
                    }
                }
                catch (Exception)
                {
                }
                return found;
            }

            /// <summary>
            /// Python _as_key: int(text), else the text itself. Keys are longs here,
            /// so text that is not a number becomes long.MinValue, which matches no
            /// row and no set - the same outcome as the Python's string key.
            /// </summary>
            internal long AsKey(string text)
            {
                return long.TryParse((text ?? "").Trim(), NumberStyles.Integer, Inv, out long key) ? key : long.MinValue;
            }

            /// <summary>
            /// Take the filter decision once and write it into vis. show is then vis
            /// minus anything inside a collapsed group. Two reasons to hide a row
            /// need two flags.
            /// </summary>
            internal int ApplyFilters()
            {
                string needle;
                try
                {
                    needle = (C<TextBox>("SearchBox").Text ?? "").Trim().ToLowerInvariant();
                }
                catch (Exception)
                {
                    needle = "";
                }
                string setName = PsUi.ComboText(C<ComboBox>("SheetSetCombo"), NoSet);
                HashSet<long> members = null;
                bool setChosen = !string.IsNullOrEmpty(setName);
                if (setChosen)
                    SheetSets.TryGetValue(setName, out members);
                bool onListOnly;
                try
                {
                    onListOnly = C<ToggleButton>("OnSheetListCheck").IsChecked == true;
                }
                catch (Exception)
                {
                    onListOnly = false;
                }

                int shown = 0;
                int parameterCount = ParameterColumns().Count;
                foreach (DataRow entry in Table.Rows)
                {
                    if (string.IsNullOrEmpty(S(entry["key"])))
                        continue;                       // a heading, decided below
                    long key = AsKey(S(entry["key"]));
                    RowsByKey.TryGetValue(key, out PsModel.Row row);
                    bool visible = true;

                    if (IsolatedKeys != null && !IsolatedKeys.Contains(key))
                        visible = false;
                    if (visible && members != null && !members.Contains(key))
                        visible = false;
                    if (visible && onListOnly && row != null && row.IsSheet)
                    {
                        if (!row.OnSheetList)
                            visible = false;
                    }
                    if (visible && !string.IsNullOrEmpty(needle))
                    {
                        var parts = new List<string> { S(entry["num"]), S(entry["name"]), S(entry["fname"]) };
                        // Anything the user put on the grid is something they may
                        // want to search by.
                        for (int index = 0; index < parameterCount; index++)
                        {
                            try
                            {
                                parts.Add(S(entry["c" + index.ToString(Inv)]));
                            }
                            catch (Exception)
                            {
                                continue;
                            }
                        }
                        if (!string.Join(" ", parts).ToLowerInvariant().Contains(needle))
                            visible = false;
                    }

                    // Then each column's own box, Excel style: every one of them has
                    // to match, so they narrow rather than widen.
                    if (visible)
                    {
                        foreach (var pair in ColumnSearch.ToList())
                        {
                            string term = (pair.Value ?? "").Trim().ToLowerInvariant();
                            if (string.IsNullOrEmpty(term))
                                continue;
                            string cell;
                            try
                            {
                                cell = S(entry[DataKey(pair.Key)]).ToLowerInvariant();
                            }
                            catch (Exception)
                            {
                                cell = "";
                            }
                            if (!cell.Contains(term))
                            {
                                visible = false;
                                break;
                            }
                        }
                    }

                    entry["vis"] = visible ? "1" : "0";
                    int group = Grouped ? AsInt(entry["gid"]) : 0;
                    entry["show"] = (visible && !Collapsed.Contains(group)) ? "1" : "0";
                    if (visible)
                        shown++;
                }

                // A heading shows when its group still has anything in it, whether
                // or not the group is collapsed.
                if (Grouped)
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        if (!string.IsNullOrEmpty(S(entry["key"])))
                            continue;
                        int group = AsInt(entry["gid"]);
                        bool alive = Groups.TryGetValue(group, out List<DataRow> found) &&
                                     found.Any(m => S(m["vis"]) == "1");
                        entry["vis"] = alive ? "1" : "0";
                        entry["show"] = entry["vis"];
                    }
                    LabelGroups();
                }

                PsUi.SetVisible(C("CollapseAllButton"), Grouped);
                PsUi.SetVisible(C("SelectionHeadingModeButton"), Grouped);
                return shown;
            }

            internal void SetAll(bool wanted, bool visibleOnly = true)
            {
                SuspendTicks = true;
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        // A heading occupies a row position but holds no sheet.
                        if (string.IsNullOrEmpty(S(entry["key"])))
                            continue;
                        if (visibleOnly && S(entry["show"]) != "1")
                            continue;
                        entry["sel"] = wanted;
                    }
                }
                finally
                {
                    SuspendTicks = false;
                }
                SyncGroupTicks();
                RefreshCounts();
                RefreshPlan();
            }

            internal void Invert()
            {
                SuspendTicks = true;
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        if (string.IsNullOrEmpty(S(entry["key"])))
                            continue;
                        if (S(entry["show"]) != "1")
                            continue;
                        entry["sel"] = !B(entry["sel"]);
                    }
                }
                finally
                {
                    SuspendTicks = false;
                }
                SyncGroupTicks();
                RefreshCounts();
                RefreshPlan();
            }

            // ==================================================================
            // combos that never change
            // ==================================================================

            internal void FillStaticCombos()
            {
                PsUi.FillCombo(C<ComboBox>("MarginCombo"), MarginChoices.Select(pair => pair.Label).ToList());
                PsUi.FillCombo(C<ComboBox>("RasterQualityCombo"), RasterChoices.Select(pair => pair.Label).ToList());
                PsUi.FillCombo(C<ComboBox>("ColorsCombo"), ColourChoices.Select(pair => pair.Label).ToList());
                PsUi.FillCombo(C<ComboBox>("DwgVersionCombo"), DwgVersions.Select(pair => pair.Label).ToList());

                NativePdf = PsExport.NativePdfAvailable(Doc);
                var printers = NativePdf ? new List<string> { RevitPdf } : new List<string>();
                printers.AddRange(PsExport.ListPrinters());
                PrinterList = printers;
                // Picked out once, here, rather than searched for every time the
                // dropdown changes. See KnownPrinters in PsExport.
                PreferredPrinter = PsExport.PreferredPrinter(printers) ?? "";
                PsUi.FillCombo(C<ComboBox>("PrinterCombo"), printers);

                var setups = new List<string> { DefaultDwgSetup };
                setups.AddRange(PsExport.ListDwgSetups(Doc));
                PsUi.FillCombo(C<ComboBox>("DwgSetupCombo"), setups);

                foreach (var (controlName, choices) in new[]
                         {
                             ("NwcParamsCombo", NwcParamChoices),
                             ("NwcCoordsCombo", NwcCoordChoices),
                             ("IfcVersionCombo", IfcVersionChoices),
                             ("IfcFileTypeCombo", IfcFileTypeChoices),
                             ("IfcSpaceBoundCombo", IfcBoundaryChoices),
                             ("IfcOriginCombo", IfcOriginChoices),
                             ("IfcDetailCombo", IfcDetailChoices),
                             ("IfcLinkedCombo", IfcLinkedChoices),
                         })
                {
                    PsUi.FillCombo(C<ComboBox>(controlName), choices.Select(pair => pair.Label).ToList());
                }

                IfcPhases = PsModel.ReadPhases(Doc) ?? new Dictionary<string, string>(StringComparer.Ordinal);
                PsUi.FillCombo(C<ComboBox>("IfcPhaseCombo"), IfcPhaseNames(), selected: IfcDefaultPhase);
                FillIfcSetups();

                FillSheetSets();
                FillProfiles();
            }

            public List<string> IfcPhaseNames()
            {
                var names = new List<string> { IfcDefaultPhase };
                names.AddRange(IfcPhases.Keys.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal));
                return names;
            }

            internal void FillIfcSetups(string selected = null)
            {
                var names = new List<string> { IfcInSession };
                names.AddRange(PsConfig.IfcSetupNames());
                var combo = C<ComboBox>("IfcSetupCombo");
                try
                {
                    combo.SelectionChanged -= IfcSetupChanged;
                }
                catch (Exception)
                {
                }
                PsUi.FillCombo(combo, names, selected: string.IsNullOrEmpty(selected) ? IfcInSession : selected);
                try
                {
                    combo.SelectionChanged += IfcSetupChanged;
                }
                catch (Exception)
                {
                }
            }

            internal void FillSheetSets()
            {
                var names = new List<string> { NoSet };
                names.AddRange(SheetSets.Keys.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal));
                PsUi.FillCombo(C<ComboBox>("SheetSetCombo"), names, selected: NoSet);
            }

            internal void FillProfiles(string selected = null)
            {
                var names = new List<string> { NoTemplate };
                names.AddRange(PsConfig.ProfileNames(Doc));
                var combo = C<ComboBox>("ProfileCombo");
                try
                {
                    combo.SelectionChanged -= ProfileChanged;
                }
                catch (Exception)
                {
                }
                PsUi.FillCombo(combo, names, selected: string.IsNullOrEmpty(selected) ? NoTemplate : selected);
                try
                {
                    combo.SelectionChanged += ProfileChanged;
                }
                catch (Exception)
                {
                }
            }

            // ==================================================================
            // wiring
            // ==================================================================

            internal void Wire()
            {
                var clicks = new List<(string Name, RoutedEventHandler Handler)>
                {
                    ("ThemeChip", ToggleTheme),
                    ("SetupButton", (s, a) => OpenSetup()),
                    ("ProfileNewButton", NewProfile),
                    ("ProfileSaveButton", SaveProfile),
                    ("ProfileDeleteButton", DeleteProfile),
                    ("ProfileImportButton", ImportTemplates),
                    ("ProfileExportButton", ExportTemplates),
                    ("SelectAllButton", (s, a) => SetAll(true)),
                    ("SelectNoneButton", (s, a) => SetAll(false)),
                    ("InvertButton", (s, a) => Invert()),
                    ("CollapseAllButton", CollapseAll),
                    ("SelectionHeadingModeButton", CycleHeadingMode),
                    ("SaveSetButton", SaveSheetSet),
                    ("CustomNameButton", OpenNameDialog),
                    ("FormatCustomNameButton", OpenNameDialog),
                    ("DwgCustomNameButton", OpenNameDialog),
                    ("OrderButton", OpenOrderDialog),
                    ("BrowseButton", BrowseRoot),
                    ("StagingBrowseButton", BrowseStaging),
                    ("AddTokenButton", AddToken),
                    ("MakeDefaultPrinterButton", MakeDefaultPrinter),
                    ("NwcCustomNameButton", OpenNameDialog),
                    ("IfcCustomNameButton", OpenNameDialog),
                    ("IfcUserPsetsBrowse", (s, a) => BrowseInto("IfcUserPsetsBox", "User defined property sets",
                                                                 ".txt", "Property set definitions")),
                    ("IfcParamMapBrowse", (s, a) => BrowseInto("IfcParamMapBox", "Parameter mapping table",
                                                                ".txt", "Parameter mapping table")),
                    ("IfcHeaderButton", ExplainIfcHeader),
                    ("IfcAddressButton", ExplainIfcAddress),
                    ("IfcClassificationButton", ExplainIfcClassification),
                    ("IfcImportSettingsButton", ImportIfcSettings),
                    ("IfcExportSettingsButton", ExportIfcSettings),
                    ("BackButton", GoBack),
                    ("NextButton", GoNext),
                    ("ExportButton", StartExport),
                    ("ExpressExportButton", (s, a) => ExpressExport(s, a)),
                    ("CancelExportButton", StopExport),
                };
                foreach (var (name, handler) in clicks)
                {
                    if (!(C(name) is ButtonBase control))
                        continue;
                    try
                    {
                        control.Click += handler;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }

                foreach (string name in new[] { "SearchBox" })
                {
                    if (C(name) is TextBox box)
                    {
                        try
                        {
                            box.TextChanged += SearchChanged;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }

                if (C("StagingBox") is TextBox staging)
                {
                    try
                    {
                        staging.TextChanged += StagingChanged;
                    }
                    catch (Exception)
                    {
                    }
                }

                foreach (string name in new[] { "RootFolderBox", "TokenBox" })
                {
                    if (C(name) is TextBox box)
                    {
                        try
                        {
                            box.TextChanged += PathChanged;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }

                if (C("SheetSetCombo") is Selector setCombo)
                {
                    try
                    {
                        setCombo.SelectionChanged += FilterChanged;
                    }
                    catch (Exception)
                    {
                    }
                }

                if (C("PrinterCombo") is Selector printer)
                {
                    try
                    {
                        printer.SelectionChanged += PrinterChanged;
                    }
                    catch (Exception)
                    {
                    }
                }

                foreach (string name in new[] { "SheetsRadio", "ViewsRadio" })
                {
                    if (C(name) is ToggleButton radio)
                    {
                        try
                        {
                            radio.Checked += ModeChanged;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }

                foreach (string name in new[] { "PlaceCenterRadio", "PlaceOffsetRadio" })
                {
                    if (C(name) is ToggleButton radio)
                    {
                        try
                        {
                            radio.Checked += PlacementChanged;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }

                foreach (string name in new[] { "SeparateFilesRadio", "CombineRadio" })
                {
                    if (C(name) is ToggleButton radio)
                    {
                        try
                        {
                            radio.Checked += CombineChanged;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }

                if (C("DwgXrefCheck") is ToggleButton xref)
                {
                    try
                    {
                        xref.Checked += XrefChanged;
                        xref.Unchecked += XrefChanged;
                    }
                    catch (Exception)
                    {
                    }
                }

                // Every format's tick and tile in one pass, from the registry, so a
                // new format cannot be added to the tab and left unwired.
                foreach (var (fmt, tick, tile, _, _, _, _) in Formats)
                {
                    if (C(tick) is ToggleButton box)
                    {
                        try
                        {
                            box.Checked += FormatChanged;
                            box.Unchecked += FormatChanged;
                        }
                        catch (Exception)
                        {
                        }
                    }
                    if (C(tile) is ButtonBase button)
                    {
                        try
                        {
                            button.Click += MakeTileClick(fmt);
                        }
                        catch (Exception)
                        {
                        }
                    }
                }

                // The two property-set file pickers only make sense when their own
                // tickbox is on, and Revit's own dialog greys them the same way.
                foreach (var (boxName, targets) in new[]
                         {
                             ("IfcUserPsetsCheck", new[] { "IfcUserPsetsBox", "IfcUserPsetsBrowse", "IfcTypePropsCheck" }),
                             ("IfcParamMapCheck", new[] { "IfcParamMapBox", "IfcParamMapBrowse" }),
                             ("IfcSchedulePsetsCheck", new[] { "IfcSpecificSchedulesCheck" }),
                             ("Ifc2dRoomBoundaryCheck", new[] { "IfcSiteElevationCheck" }),
                         })
                {
                    if (!(C(boxName) is ToggleButton box))
                        continue;
                    RoutedEventHandler handler = MakeDependants(boxName, targets);
                    try
                    {
                        box.Checked += handler;
                        box.Unchecked += handler;
                    }
                    catch (Exception)
                    {
                    }
                }

                if (C("GroupCheck") is ToggleButton groupCheck)
                {
                    try
                    {
                        groupCheck.Checked += ToggleGrouping;
                        groupCheck.Unchecked += ToggleGrouping;
                    }
                    catch (Exception)
                    {
                    }
                }

                if (C("ShowAllCheck") is ToggleButton showAll)
                {
                    try
                    {
                        showAll.Checked += ShowAllChanged;
                        showAll.Unchecked += ShowAllChanged;
                    }
                    catch (Exception)
                    {
                    }
                }

                if (C("OnSheetListCheck") is ToggleButton onList)
                {
                    try
                    {
                        onList.Checked += FilterChanged;
                        onList.Unchecked += FilterChanged;
                    }
                    catch (Exception)
                    {
                    }
                }

                foreach (string name in new[] { "FolderPerFormatCheck" })
                {
                    if (C(name) is ToggleButton box)
                    {
                        try
                        {
                            box.Checked += PathChanged;
                            box.Unchecked += PathChanged;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }

                // Offering to open the folder, and the debug log, are global
                // settings rather than part of a template: they are about how you
                // like to work, not about this job.
                foreach (var (name, key) in new[]
                         {
                             ("OpenFolderCheck", "open_folder_after_export"),
                             ("DebugCheck", "debug"),
                             ("SuppressCheck", "suppress_dialogs"),
                         })
                {
                    if (!(C(name) is ToggleButton box))
                        continue;
                    try
                    {
                        box.IsChecked = Settings.Flag(key);
                        box.Checked += MakeSettingSaver(key);
                        box.Unchecked += MakeSettingSaver(key);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }

                if (C("MainTabs") is Selector tabs)
                {
                    try
                    {
                        tabs.SelectionChanged += TabChanged;
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            // -------------------------------------------------------- handlers
            internal RoutedEventHandler MakeSettingSaver(string key)
            {
                return (sender, args) =>
                {
                    try
                    {
                        Settings.Set(key, ((ToggleButton)sender).IsChecked == true ? "1" : "0");
                        Settings.Save();
                    }
                    catch (Exception)
                    {
                    }
                    if (key == "debug")
                    {
                        Say(FlagOf("DebugCheck")
                            ? "Debug log on. The next export writes a blow-by-blow log beside the tool's error log."
                            : "Debug log off.");
                    }
                };
            }

            internal void SearchChanged(object sender, TextChangedEventArgs args)
            {
                ApplyFilters();
                RefreshCounts();
            }

            internal void FilterChanged(object sender, EventArgs args)
            {
                ApplyFilters();
                RefreshCounts();
                RefreshPlan();
            }

            internal void ModeChanged(object sender, RoutedEventArgs args)
            {
                if (!Ready)
                    return;
                IsolatedKeys = null;
                PsUi.SetVisible(C("IsolationChip"), false);
                // Sheets and views carry different columns, so the order in hand
                // belongs to the mode being left. Park it, take the other one, and
                // drop any sort or search aimed at a column that no longer exists.
                ParkColumns(OtherMode());
                ParkRules(OtherMode());
                ReadModel();
                AdoptColumns(ModeName());
                AdoptRules(ModeName());
                FillTable();
                RefreshAll();
            }

            internal string OtherMode()
            {
                return IsViewsMode() ? "sheets" : "views";
            }

            internal void ParkRules(string mode)
            {
                if (RulesByMode == null)
                    RulesByMode = new Dictionary<string, List<PsNaming.Rule>>(StringComparer.Ordinal);
                RulesByMode[mode] = new List<PsNaming.Rule>(Rules);
            }

            internal void AdoptRules(string mode)
            {
                List<PsNaming.Rule> found = null;
                RulesByMode?.TryGetValue(mode, out found);
                Rules = new List<PsNaming.Rule>(found != null && found.Count > 0 ? found : PsNaming.DefaultRules(mode));
            }

            internal void ParkColumns(string mode)
            {
                ColumnOrders[mode] = new List<string>(ColumnOrder);
                ColumnOrders[mode + ".widths"] = ColumnWidths();
            }

            internal void AdoptColumns(string mode)
            {
                ColumnOrders.TryGetValue(mode, out List<string> order);
                if (order == null || order.Count == 0)
                    order = StartingColumns(mode, DefaultExtras(), BrowserNames);
                ColumnOrder = new List<string>(order);
                SavedWidths = ColumnOrders.TryGetValue(mode + ".widths", out List<string> widths)
                    ? widths : new List<string>();
                var live = new HashSet<string>(ColumnOrder, StringComparer.Ordinal);
                SortStack = SortStack.Where(pair => live.Contains(pair.ColId)).ToList();
                foreach (string colId in ColumnSearch.Keys.ToList())
                {
                    if (!live.Contains(colId))
                        ColumnSearch.Remove(colId);
                }
                // The sort that belonged to the other list has gone. This one opens
                // the way it was left, or - never touched - the way it comes out of
                // the box.
                if (!RestoreSort(mode))
                {
                    if (mode == "views" || Ready)
                        SortStack = new List<(string ColId, bool Descending)>();
                    ApplyDefaultSort();
                }
                BuildColumns();
            }

            internal void PlacementChanged(object sender, RoutedEventArgs args)
            {
                bool offset = false;
                try
                {
                    offset = C<ToggleButton>("PlaceOffsetRadio").IsChecked == true;
                }
                catch (Exception)
                {
                }
                foreach (string name in new[] { "MarginCombo", "OffsetXBox", "OffsetYBox" })
                    SetEnabled(C(name), offset);
            }

            internal void CombineChanged(object sender, RoutedEventArgs args)
            {
                bool combine = false;
                try
                {
                    combine = C<ToggleButton>("CombineRadio").IsChecked == true;
                }
                catch (Exception)
                {
                }
                SetEnabled(C("OrderButton"), combine);
                SetEnabled(C("KeepPaperSizeCheck"), combine);
                RefreshPlan();
            }

            internal void FormatChanged(object sender, RoutedEventArgs args)
            {
                RefreshPlan();
                SayFormats();
            }

            internal void PrinterChanged(object sender, SelectionChangedEventArgs args)
            {
                string name = PsUi.ComboText(C<ComboBox>("PrinterCombo"));
                object note = C("PrinterNote");
                bool driver = !string.IsNullOrEmpty(name) && name != RevitPdf;
                var known = driver ? PsExport.KnownPrinter(name) : null;
                if (!driver)
                {
                    string text = "Revit's own exporter needs no printer set up and keeps each sheet at its own size.";
                    // Say it is there rather than leave it to be found.
                    if (!string.IsNullOrEmpty(PreferredPrinter))
                    {
                        text += "  \"" + PreferredPrinter + "\" is installed on this machine, which is the one driver " +
                                "here that is already set up for unattended export.";
                    }
                    PsUi.SetText(note, text);
                }
                else if (known != null)
                {
                    var (description, needsStaging) = known.Value;
                    string text = "\"" + name + "\" is " + description + ".";
                    if (needsStaging)
                    {
                        text += "  It is still PDF24 underneath, so it writes to PDF24's own output folder rather " +
                                "than to the path Revit asks for - set \"Driver saves to\" below, or run one sheet " +
                                "and let the report find the folder for you.";
                    }
                    PsUi.SetText(note, text);
                }
                else
                {
                    PsUi.SetText(note, "Sheets print through \"" + name + "\". Its own settings decide compression " +
                                       "and quality; it must be set not to ask for a file name.");
                }
                // Where a driver saves is a fact about the driver, not about the
                // job, so it is remembered per printer and follows the dropdown.
                string previous = CurrentPrinter;
                if (!string.IsNullOrEmpty(previous) && previous != name)
                    RememberStaging(previous, TextOf("StagingBox"));
                if (name != previous)
                {
                    CurrentPrinter = name;
                    if (driver)
                    {
                        string remembered = RecallStaging(name);
                        SetTextValue(C("StagingBox"), remembered);
                    }
                }

                foreach (string controlName in new[] { "StagingBox", "StagingBrowseButton" })
                    SetEnabled(C(controlName), driver);
                SayStaging();
            }

            internal void SayStaging()
            {
                object note = C("StagingNote");
                string printer = PsUi.ComboText(C<ComboBox>("PrinterCombo"));
                string staging = TextOf("StagingBox");
                if (string.IsNullOrEmpty(printer) || printer == RevitPdf)
                {
                    PsUi.SetText(note, "Not needed: the built-in exporter writes straight to the file name you asked for.");
                }
                else if (!string.IsNullOrEmpty(staging))
                {
                    if (BusyFolder(staging))
                    {
                        PsUi.SetText(note,
                            "Careful: that is a folder you use. Anything that collects PDFs takes whatever new PDF " +
                            "appears while a run is going, so a PDF saved there by anything else mid-run would be " +
                            "renamed and moved with the sheets. A folder of its own is safer.");
                    }
                    else
                    {
                        PsUi.SetText(note,
                            "Each sheet is collected from that folder and renamed. \"" + printer + "\" still has to " +
                            "be set to save there on its own rather than asking - it names the file, this tool " +
                            "renames it.");
                    }
                }
                else
                {
                    PsUi.SetText(note,
                        "Empty means the driver is expected to take the path Revit gives it. If nothing lands, \"" +
                        printer + "\" is saving where its own settings say - point this at that folder.");
                }
            }

            internal string StagingKey(string printer)
            {
                return PsConfig.StagingKey(printer);
            }

            internal void RememberStaging(string printer, string folder)
            {
                if (string.IsNullOrEmpty(printer) || printer == RevitPdf)
                    return;
                try
                {
                    Settings.Set(StagingKey(printer), folder ?? "");
                    Settings.Save();
                }
                catch (Exception)
                {
                }
            }

            internal string RecallStaging(string printer)
            {
                if (string.IsNullOrEmpty(printer) || printer == RevitPdf)
                    return "";
                try
                {
                    return Settings.Text(StagingKey(printer), "");
                }
                catch (Exception)
                {
                    return "";
                }
            }

            /// <summary>Python os.path.normcase(os.path.normpath(p)).rstrip('\\/').</summary>
            internal static string NormFolder(string path)
            {
                return PsPaths.OsPathNormPath(path ?? "").Replace('/', '\\').ToLowerInvariant().TrimEnd('\\', '/');
            }

            /// <summary>
            /// Is this a folder the user keeps things in, rather than a staging one?
            /// Collecting takes whatever new PDF turns up, so pointing it at the
            /// Desktop means a PDF saved there by anything else gets filed too.
            /// </summary>
            internal bool BusyFolder(string path)
            {
                string wanted;
                try
                {
                    wanted = NormFolder(path);
                }
                catch (Exception)
                {
                    return false;
                }
                if (string.IsNullOrEmpty(wanted))
                    return false;
                var risky = new List<string>();
                foreach (string variable in new[] { "USERPROFILE", "OneDrive", "OneDriveCommercial" })
                {
                    string root = Environment.GetEnvironmentVariable(variable) ?? "";
                    if (string.IsNullOrEmpty(root))
                        continue;
                    risky.Add(root);
                    foreach (string leaf in new[] { "Desktop", "Documents", "Downloads", "Pictures" })
                        risky.Add(PsPaths.OsPathJoin(root, leaf));
                }
                foreach (string candidate in risky)
                {
                    try
                    {
                        if (NormFolder(candidate) == wanted)
                            return true;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                return false;
            }

            public void BrowseStaging(object sender = null, RoutedEventArgs args = null)
            {
                string chosen = PsUi.BrowseFolder(TextOf("StagingBox"), "Where does the driver save its PDFs?");
                if (!string.IsNullOrEmpty(chosen))
                    SetTextValue(C("StagingBox"), chosen);
            }

            internal void XrefChanged(object sender, RoutedEventArgs args)
            {
                PsUi.SetText(C("DwgXrefNote"),
                             FlagOf("DwgXrefCheck")
                                 ? "On: views and links become XREFs beside the DWG."
                                 : "Off: links and views are bound into the DWG.");
            }

            internal void StagingChanged(object sender, TextChangedEventArgs args)
            {
                SayStaging();
                RememberStaging(PsUi.ComboText(C<ComboBox>("PrinterCombo")), TextOf("StagingBox"));
            }

            internal void PathChanged(object sender, EventArgs args)
            {
                RefreshPlan();
            }

            internal void TabChanged(object sender, SelectionChangedEventArgs args)
            {
                try
                {
                    if (!ReferenceEquals(args.OriginalSource, sender))
                        return;
                }
                catch (Exception)
                {
                }
                SayStep();
                int index = TabIndex();
                if (index == TabRegister)
                    Register.Show();
                else if (index == TabCreate)
                    RefreshPlan();
            }
        }
    }
}
