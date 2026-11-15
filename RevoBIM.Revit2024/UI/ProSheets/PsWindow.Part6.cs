using System;
using System.Collections.Generic;
using System.Data;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using RevoBIM.Tools.ProSheets;
using View = Autodesk.Revit.DB.View;
using Element = Autodesk.Revit.DB.Element;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsWindow
    {
        public partial class ProSheetsWindow
        {
            // ==================================================================
            // naming
            // ==================================================================

            public void OpenNameDialog(object sender = null, RoutedEventArgs args = null)
            {
                PsModel.Row sampleRow = FirstTickedRow() ?? (Rows.Count > 0 ? Rows[0] : null);
                PsModel.RowLookup lookup = sampleRow != null ? LookupFor(sampleRow) : null;
                string label = "";
                if (sampleRow != null)
                    label = !string.IsNullOrEmpty(sampleRow.Number) ? sampleRow.Number : sampleRow.Name;
                string mode = ModeName();
                var dialog = new PsNameWin.CustomNameWindow(Catalogue, lookup, Rules, ThemeName, Window, label, mode: mode);
                List<PsNaming.Rule> chosen = dialog.Show();
                if (chosen == null)
                    return;
                Rules = chosen;
                ParkRules(mode);
                RefreshNames();
                RefreshPlan();
                Say("File naming for " + (mode == "views" ? "views" : "sheets") + " updated.");
            }

            internal PsModel.Row FirstTickedRow()
            {
                foreach (DataRow entry in Table.Rows)
                {
                    if (B(entry["sel"]))
                    {
                        RowsByKey.TryGetValue(AsKey(S(entry["key"])), out PsModel.Row row);
                        return row;
                    }
                }
                return null;
            }

            /// <summary>Write every row's file name into the table.</summary>
            internal void RefreshNames()
            {
                SuspendTicks = true;
                try
                {
                    foreach (DataRow entry in Table.Rows)
                    {
                        if (!RowsByKey.TryGetValue(AsKey(S(entry["key"])), out PsModel.Row row) || row == null)
                            continue;
                        string fallback = !string.IsNullOrEmpty(row.Number) ? row.Number
                                        : !string.IsNullOrEmpty(row.Name) ? row.Name : "sheet";
                        string name = PsNaming.BuildName(Rules, LookupFor(row), fallback);
                        entry["fname"] = name ?? "";
                        row.CustomName = name;
                    }
                }
                finally
                {
                    SuspendTicks = false;
                }
            }

            // ==================================================================
            // the plan
            // ==================================================================

            /// <summary>
            /// Every ticked format that can actually be written right now. A format
            /// whose tile is greyed is left out even if its box is still ticked from
            /// a template, so the plan never promises a file the run cannot produce.
            /// </summary>
            public List<string> ChosenFormats()
            {
                var found = new List<string>();
                HashSet<string> allowed = AvailableFormats();
                foreach (var (fmt, tick, _, _, _, _, live) in Formats)
                {
                    if (!live || !allowed.Contains(fmt))
                        continue;
                    try
                    {
                        if (C(tick) is ToggleButton box && box.IsChecked == true)
                            found.Add(fmt);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                return found;
            }

            /// <summary>
            /// Which formats the current selection allows. NWC and IFC are exported
            /// per view and Navisworks only understands a 3D one, so in Sheets mode
            /// neither is reachable and in Views mode they wait for a 3D view.
            /// </summary>
            internal HashSet<string> AvailableFormats()
            {
                var allowed = new HashSet<string>(LiveFormats().Where(fmt => !ViewOnlyFormats.Contains(fmt)),
                                                  StringComparer.Ordinal);
                if (!IsViewsMode())
                    return allowed;
                if (HasTicked3d())
                    allowed.UnionWith(ViewOnlyFormats);
                return allowed;
            }

            internal bool HasTicked3d()
            {
                foreach (PsModel.Row row in TickedRows())
                {
                    if (PsModel.IsThreeD(row))
                        return true;
                }
                return false;
            }

            /// <summary>
            /// Every ticked row, in the order the Selection tab sorts them. Hidden
            /// rows included: ticked means printed; what is on screen has no say.
            /// </summary>
            public List<PsModel.Row> TickedRows()
            {
                var found = new List<PsModel.Row>();
                DataRow[] entries;
                try
                {
                    entries = Table.Select("", "[ord] ASC");
                }
                catch (Exception)
                {
                    entries = new DataRow[0];
                }
                foreach (DataRow entry in entries)
                {
                    string key;
                    try
                    {
                        if (!B(entry["sel"]))
                            continue;
                        key = S(entry["key"]);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    if (string.IsNullOrEmpty(key))
                        continue;                       // a group heading
                    if (RowsByKey.TryGetValue(AsKey(key), out PsModel.Row row) && row != null)
                        found.Add(row);
                }
                return found;
            }

            /// <summary>
            /// Every ticked row turned into a Job, with clashes already resolved. Two
            /// sheets whose chosen parameters happen to match would otherwise export
            /// one file and overwrite it with the other; the clash is reported.
            /// </summary>
            public (List<PsExport.Job> Jobs, Dictionary<string, List<long>> Clashes) PlanJobs()
            {
                List<string> formats = ChosenFormats();
                List<PsModel.Row> rows = TickedRows();
                if (rows.Count == 0 || formats.Count == 0)
                    return (new List<PsExport.Job>(), new Dictionary<string, List<long>>(StringComparer.Ordinal));

                string root = TextOf("RootFolderBox");
                string tokens = TextOf("TokenBox");
                bool perFormat = FlagOf("FolderPerFormatCheck", true);

                var pairs = new List<(long Key, string Name)>();
                foreach (PsModel.Row row in rows)
                {
                    PsModel.RowLookup lookup = LookupFor(row);
                    // In Views mode row.Number carries the view type, so the fallback
                    // has to be the name; "ThreeD.pdf" is not a file anybody asked for.
                    string fallback = !row.IsSheet
                        ? (!string.IsNullOrEmpty(row.Name) ? row.Name : row.Number)
                        : (!string.IsNullOrEmpty(row.Number) ? row.Number : row.Name);
                    string name = PsNaming.BuildName(Rules, lookup, string.IsNullOrEmpty(fallback) ? "sheet" : fallback);
                    pairs.Add((row.Key, name));
                }
                Dictionary<string, List<long>> clashes = PsNaming.Clashes(pairs);
                var settled = new Dictionary<long, string>();
                foreach (var (key, name) in PsNaming.UniqueNames(pairs))
                    settled[key] = name;

                var jobs = new List<PsExport.Job>();
                foreach (PsModel.Row row in rows)
                {
                    PsModel.RowLookup lookup = LookupFor(row);
                    var folders = new Dictionary<string, string>(StringComparer.Ordinal);
                    foreach (string fmt in formats)
                        folders[fmt] = PsPaths.FullFolder(root, tokens, lookup, perFormat ? fmt.ToUpperInvariant() : null);
                    string baseName = settled.TryGetValue(row.Key, out string settledName)
                        ? settledName
                        : (!string.IsNullOrEmpty(row.Number) ? row.Number : "sheet");
                    jobs.Add(new PsExport.Job(
                        key: row.Key,
                        label: ((row.Number ?? "") + " " + (row.Name ?? "")).Trim(),
                        elementId: row.ElementId,
                        baseName: baseName,
                        folders: folders,
                        sizeInfo: row.SizeInfo,
                        view: row.Element as View));
                }
                return (jobs, clashes);
            }

            /// <summary>
            /// Where the register goes with a run: the issue folder - the folder
            /// before the sheet series level, because the register covers every
            /// series in the issue. Worked out from the plan rather than from what
            /// the run wrote, so the Create list can show it before anything is
            /// written.
            /// </summary>
            public string RegisterFolder(IEnumerable<PsExport.Job> jobs, IEnumerable<string> formats)
            {
                var folders = new List<string>();
                List<string> fmts = formats?.ToList() ?? new List<string>();
                foreach (PsExport.Job job in jobs ?? Enumerable.Empty<PsExport.Job>())
                {
                    foreach (string fmt in fmts)
                    {
                        string folder = job.Folders != null && job.Folders.TryGetValue(fmt, out string found) ? found : "";
                        if (!string.IsNullOrEmpty(folder))
                            folders.Add(folder);
                    }
                }
                if (folders.Count == 0)
                {
                    // Nothing ticked: the register on its own, in the issue folder
                    // the tokens name without a sheet.
                    return RegisterAloneFolder();
                }
                string cut = PsPaths.IssueCut(TextOf("RootFolderBox"), TextOf("TokenBox"), folders,
                                              Settings.Text("param_series", ""));
                if (!string.IsNullOrEmpty(cut))
                    return cut;
                string registerFolder = PsRegister.RegisterFolder(folders, FlagOf("FolderPerFormatCheck", true));
                return !string.IsNullOrEmpty(registerFolder) ? registerFolder : TextOf("RootFolderBox");
            }

            /// <summary>Where the register goes when it is the only thing written.</summary>
            public string RegisterAloneFolder()
            {
                Func<string, string> lookup;
                try
                {
                    lookup = LookupFor(null);
                }
                catch (Exception)
                {
                    lookup = name => "";
                }
                return PsPaths.ProjectFolder(TextOf("RootFolderBox"), TextOf("TokenBox"), lookup,
                                             Settings.Text("param_series", ""));
            }

            /// <summary>
            /// Whether a run is the Document Register by itself: nothing ticked, and
            /// the register tab asking to be added to the export.
            /// </summary>
            public bool RegisterAlone(IList<PsExport.Job> jobs)
            {
                try
                {
                    return (jobs == null || jobs.Count == 0) && Register.AddToExport();
                }
                catch (Exception)
                {
                    return false;
                }
            }

            /// <summary>
            /// Where "Open folder" goes after a run: the issue, not one series - the
            /// folder before the sheet series level of the folder tokens.
            /// </summary>
            public string IssueFolder(IList<PsExport.Job> jobs, IList<string> formats)
            {
                var folders = new List<string>();
                foreach (PsExport.Job job in jobs ?? new List<PsExport.Job>())
                {
                    foreach (string fmt in formats ?? new List<string>())
                        folders.Add(job.Folders != null && job.Folders.TryGetValue(fmt, out string found) ? found : "");
                }
                string cut = PsPaths.IssueCut(TextOf("RootFolderBox"), TextOf("TokenBox"), folders,
                                              Settings.Text("param_series", ""));
                return !string.IsNullOrEmpty(cut) ? cut : RegisterFolder(jobs, formats);
            }

            /// <summary>
            /// How many files a run will actually write. Not jobs times formats: NWC
            /// and IFC only take the 3D views, and a combined PDF is one file. A
            /// count that overstates is worse than no count.
            /// </summary>
            internal int FileCount(IList<PsExport.Job> jobs, IList<string> formats)
            {
                if (jobs == null || jobs.Count == 0 || formats == null || formats.Count == 0)
                    return 0;
                int solid = jobs.Count(job => PsModel.IsThreeD(RowsByKey.TryGetValue(job.Key, out var row) ? row : null));
                int total = 0;
                foreach (string fmt in formats)
                {
                    if (ViewOnlyFormats.Contains(fmt))
                        total += solid;
                    else if (fmt == "pdf" && FlagOf("CombineRadio"))
                        total += 1;
                    else
                        total += jobs.Count;
                }
                return total;
            }

            /// <summary>
            /// The extension a format will actually land under. IFC's file type
            /// dropdown decides between .ifc, .ifcXML and .ifcZIP.
            /// </summary>
            internal string SuffixFor(string fmt)
            {
                if (fmt == "ifc")
                    return PsExport.IfcExtension(CollectIfc());
                return "." + fmt;
            }

            /// <summary>Just the IFC keys, for anything that needs them before a run.</summary>
            internal Dictionary<string, string> CollectIfc()
            {
                var profile = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (Field field in IfcFields)
                    ReadField(profile, field);
                return profile;
            }

            internal string TextOf(string controlName, string @default = "")
            {
                try
                {
                    string value = GetTextValue(C(controlName));
                    return string.IsNullOrEmpty(value) ? @default : value;
                }
                catch (Exception)
                {
                    return @default;
                }
            }

            internal bool FlagOf(string controlName, bool @default = false)
            {
                if (C(controlName) is ToggleButton control)
                {
                    try
                    {
                        return control.IsChecked == true;
                    }
                    catch (Exception)
                    {
                        return @default;
                    }
                }
                return @default;
            }

            internal void RefreshPlan()
            {
                // Ticking a 3D view is what makes NWC and IFC reachable, so the tiles
                // are re-judged here - the one method every path that changes the
                // selection already ends in.
                RefreshFormatTiles();
                RefreshCreateColumns();
                var (jobs, clashes) = PlanJobs();
                List<string> formats = ChosenFormats();

                CreateTable.Rows.Clear();
                foreach (PsExport.Job job in jobs)
                {
                    RowsByKey.TryGetValue(job.Key, out PsModel.Row row);
                    DataRow entry = CreateTable.NewRow();
                    entry["num"] = row != null ? row.Number ?? "" : job.Label ?? "";
                    entry["name"] = row != null ? row.Name ?? "" : "";
                    entry["size"] = row != null ? row.Size ?? "" : "";
                    entry["fmt"] = string.Join(", ", formats.Select(FormatLabel));
                    entry["fname"] = job.BaseName ?? "";
                    entry["folder"] = formats.Count > 0 && job.Folders.TryGetValue(formats[0], out string folder)
                        ? folder ?? "" : "";
                    entry["key"] = job.Key.ToString(Inv);
                    entry["state"] = "";
                    CreateTable.Rows.Add(entry);
                }

                // The Document Register, when the register tab says to add it: one
                // more file the run writes, listed with the rest so it can be seen
                // going in - and turning green or red like them.
                bool alone = RegisterAlone(jobs);
                bool withRegister = alone || (jobs.Count > 0 && Register.AddToExport());
                if (withRegister)
                {
                    DataRow entry = CreateTable.NewRow();
                    entry["num"] = "";
                    entry["name"] = "Document Register";
                    entry["size"] = "";
                    entry["fmt"] = "XLSX";
                    entry["fname"] = PsPaths.OsPathSplitExt(Register.FileName()).Root;
                    entry["folder"] = RegisterFolder(jobs, formats);
                    entry["key"] = "register";
                    entry["state"] = "";
                    CreateTable.Rows.Add(entry);
                }

                int count = jobs.Count;
                int fileCount = FileCount(jobs, formats);
                string word = IsViewsMode() ? "view" : "sheet";
                string summary;
                if (count != 0)
                {
                    summary = string.Format(Inv, "{0} {1}{2} ticked, {3} file{4} to write{5}.",
                                            count, word, Plural(count), fileCount, Plural(fileCount),
                                            withRegister ? ", plus the Document Register" : "");
                }
                else
                {
                    summary = alone
                        ? "No sheets ticked - Export writes the Document Register on its own."
                        : "Nothing ticked yet.";
                }
                PsUi.SetText(C("CreateSummary"), summary);

                if (clashes.Count > 0)
                {
                    PsUi.SetText(C("ClashWarning"),
                                 string.Format(Inv, "{0} name{1} repeated - \"(2)\" was added so nothing is overwritten.",
                                               clashes.Count, Plural(clashes.Count)));
                }
                else
                {
                    PsUi.SetText(C("ClashWarning"), "");
                }

                object preview = C("PathPreview");
                if (jobs.Count > 0 && formats.Count > 0)
                {
                    PsExport.Job first = jobs[0];
                    string folder = first.Folders.TryGetValue(formats[0], out string found) ? found : "";
                    PsUi.SetText(preview, PsPaths.OsPathJoin(folder ?? "", first.BaseName + SuffixFor(formats[0])));
                }
                else if (string.IsNullOrEmpty(TextOf("RootFolderBox")))
                {
                    PsUi.SetText(preview, "Choose a root folder to see where the first sheet lands.");
                }
                else if (alone)
                {
                    PsUi.SetText(preview, PsPaths.OsPathJoin(RegisterFolder(new List<PsExport.Job>(), formats),
                                                             Register.FileName()));
                }
                else
                {
                    PsUi.SetText(preview, "Nothing ticked yet.");
                }

                SayExportReady(jobs, formats);
            }

            internal void SayExportReady(IList<PsExport.Job> jobs, IList<string> formats)
            {
                object button = C("ExportButton");
                bool ready = ((jobs.Count > 0 && formats.Count > 0) || RegisterAlone(jobs))
                             && !string.IsNullOrEmpty(TextOf("RootFolderBox"));
                if (button != null)
                    SetEnabled(button, ready && !Exporting);
            }

            internal void SayFormats()
            {
                List<string> formats = ChosenFormats();
                if (formats.Count == 0)
                    Say("No format ticked, so there is nothing to write.");
                else
                    Say("Exporting as " + string.Join(" and ", formats.Select(FormatLabel)) + ".");
            }

            // ==================================================================
            // panels, tabs and counts
            // ==================================================================

            public void ShowPanel(string which)
            {
                foreach (var (fmt, _, _, _, panel, _, _) in Formats)
                {
                    if (string.IsNullOrEmpty(panel))
                        continue;
                    PsUi.SetVisible(C(panel), fmt == which);
                }
            }

            /// <summary>
            /// The Create list follows the mode the same way the first tab does: a
            /// view has no sheet number and no paper size.
            /// </summary>
            internal void RefreshCreateColumns()
            {
                var grid = C<DataGrid>("CreateGrid");
                bool views = IsViewsMode();
                List<DataGridColumn> columns;
                try
                {
                    columns = grid.Columns.ToList();
                }
                catch (Exception)
                {
                    return;
                }
                if (columns.Count < 3)
                    return;
                try
                {
                    columns[0].Header = views ? "View type" : "Sheet";
                    columns[2].Visibility = views ? Visibility.Collapsed : Visibility.Visible;
                }
                catch (Exception)
                {
                }
            }

            internal RoutedEventHandler MakeTileClick(string fmt)
            {
                return (sender, args) => ShowPanel(fmt);
            }

            internal RoutedEventHandler MakeDependants(string boxName, IList<string> targets)
            {
                return (sender, args) => ApplyDependants(boxName, targets);
            }

            internal void ApplyDependants(string boxName, IList<string> targets)
            {
                bool on = FlagOf(boxName, false);
                foreach (string name in targets)
                {
                    object control = C(name);
                    if (control == null)
                        continue;
                    SetEnabled(control, on);
                }
            }

            internal void RefreshDependants()
            {
                ApplyDependants("IfcUserPsetsCheck", new[] { "IfcUserPsetsBox", "IfcUserPsetsBrowse", "IfcTypePropsCheck" });
                ApplyDependants("IfcParamMapCheck", new[] { "IfcParamMapBox", "IfcParamMapBrowse" });
                ApplyDependants("IfcSchedulePsetsCheck", new[] { "IfcSpecificSchedulesCheck" });
                ApplyDependants("Ifc2dRoomBoundaryCheck", new[] { "IfcSiteElevationCheck" });
            }

            /// <summary>
            /// Grey the tiles the current selection cannot reach, and say why. The
            /// tick is left alone rather than cleared.
            /// </summary>
            internal void RefreshFormatTiles()
            {
                HashSet<string> allowed = AvailableFormats();
                foreach (var (fmt, tick, tile, group, _, _, live) in Formats)
                {
                    bool usable = live && allowed.Contains(fmt);
                    foreach (var (name, dim) in new[] { (tick, false), (tile, false), (group, true) })
                    {
                        if (!(C(name) is UIElement control))
                            continue;
                        try
                        {
                            control.IsEnabled = usable;
                            if (dim)
                                control.Opacity = usable ? 1.0 : 0.45;
                        }
                        catch (Exception)
                        {
                            continue;
                        }
                    }
                }

                var blocked = ViewOnlyFormats.Where(fmt => !allowed.Contains(fmt)).Select(FormatLabel).ToList();
                string message;
                if (blocked.Count == 0)
                {
                    message = "";
                }
                else if (!IsViewsMode())
                {
                    message = string.Join(" and ", blocked) +
                              " export one 3D view at a time, so they wait for Views above rather than Sheets.";
                }
                else
                {
                    message = "Tick a 3D view to turn " + string.Join(" and ", blocked) + " on. Navisworks has no " +
                              "idea what a plan is, and an IFC of one would hold nothing.";
                }
                var reserved = Formats.Where(row => !row.Live).Select(row => row.Label).ToList();
                if (reserved.Count > 0)
                {
                    string extra = string.Join(" and ", reserved) + " " + (reserved.Count == 1 ? "is" : "are") +
                                   " reserved for a later version.";
                    message = !string.IsNullOrEmpty(message) ? (message + "  " + extra).Trim() : extra;
                }
                PsUi.SetText(C("FormatNote"), message);

                foreach (var (name, fmt) in new[] { ("NwcAvailableNote", "nwc"), ("IfcAvailableNote", "ifc") })
                {
                    PsUi.SetText(C(name), allowed.Contains(fmt)
                        ? ""
                        : "Greyed out until a 3D view is ticked on the Selection tab.");
                }
            }

            internal int TabIndex()
            {
                try
                {
                    return ((Selector)C("MainTabs")).SelectedIndex;
                }
                catch (Exception)
                {
                    return 0;
                }
            }

            internal void SetTab(int index)
            {
                try
                {
                    ((Selector)C("MainTabs")).SelectedIndex = Math.Max(TabSelection, Math.Min(TabCreate, index));
                }
                catch (Exception)
                {
                }
            }

            public void GoBack(object sender = null, RoutedEventArgs args = null)
            {
                SetTab(TabIndex() - 1);
            }

            public void GoNext(object sender = null, RoutedEventArgs args = null)
            {
                SetTab(TabIndex() + 1);
            }

            internal void SayStep()
            {
                int index = TabIndex();
                SetEnabled(C("BackButton"), index > TabSelection);
                PsUi.SetVisible(C("NextButton"), index < TabCreate);
                PsUi.SetVisible(C("ExportButton"), index == TabCreate);
                // Express Export lives on Selection: tick, press, done.
                PsUi.SetVisible(C("ExpressExportButton"), index == TabSelection);
            }

            internal void RefreshCounts()
            {
                int shown = 0;
                int ticked = 0;
                int outOfSight = 0;
                foreach (DataRow entry in Table.Rows)
                {
                    if (string.IsNullOrEmpty(S(entry["key"])))
                        continue;
                    if (S(entry["vis"]) == "1")
                        shown++;
                    if (B(entry["sel"]))
                    {
                        ticked++;
                        if (S(entry["show"]) != "1")
                            outOfSight++;
                    }
                }
                int total = Rows.Count;
                string word = IsViewsMode() ? "view" : "sheet";
                string text = string.Format(Inv, "{0} of {1} {2}{3} showing, {4} ticked.",
                                            shown, total, word, Plural(total), ticked);
                if (outOfSight != 0)
                {
                    // Ticked is printed, whatever the filter is hiding - so say so.
                    text = string.Format(Inv, "{0} {1} of them {2} out of sight and will still be exported.",
                                         text, outOfSight, outOfSight == 1 ? "is" : "are");
                }
                Say(text);
                if (HeaderTick != null)
                {
                    try
                    {
                        HeaderTick.IsChecked = shown > 0 && ticked >= shown;
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            /// <summary>Say when a template's own sort is what is on screen.</summary>
            internal bool SayTemplateSort()
            {
                string name = TemplateSort ?? "";
                if (string.IsNullOrEmpty(name))
                    return false;
                Say("This template was saved sorted by " + name + ", so that is what it opened in. Sort by " +
                    HeadingOf(SeriesColumn() ?? "") + " and save the template again to make that the one it remembers.");
                return true;
            }

            internal void RefreshAll()
            {
                FillTable();
                FillParameterValues();
                RefreshNames();
                ApplyOrder();
                ApplyGrouping();
                ApplyFilters();
                PaintSortHeaders();
                RefreshCounts();
                RefreshDependants();
                RefreshPlan();
                if (!SayTemplateSort())
                    SayStep();
                ShowPanel("pdf");
            }

            public void Say(string text)
            {
                PsUi.SetText(C("StatusText"), text);
            }

            // ==================================================================
            // small actions
            // ==================================================================

            // ------------------------------------------------ IFC odds and ends
            public void BrowseInto(string controlName, string title, string extension, string label)
            {
                string chosen = PsUi.PickFile(false, title, extension, label: label);
                if (string.IsNullOrEmpty(chosen))
                    return;
                SetTextValue(C(controlName), chosen);
            }

            internal void IfcSetupChanged(object sender = null, SelectionChangedEventArgs args = null)
            {
                string name = PsUi.ComboText(C<ComboBox>("IfcSetupCombo"), IfcInSession);
                if (string.IsNullOrEmpty(name) || name == IfcInSession)
                    return;
                Dictionary<string, string> values = PsConfig.ReadIfcSetup(PsConfig.IfcSetupPath(name));
                if (values == null || values.Count == 0)
                {
                    Say("\"" + name + "\" holds no IFC settings.");
                    return;
                }
                var merged = new Dictionary<string, string>(PsConfig.Defaults(), StringComparer.Ordinal);
                foreach (var pair in values)
                    merged[pair.Key] = pair.Value;
                WriteFields(merged, IfcFields);
                RefreshDependants();
                RefreshPlan();
                Say("IFC setup \"" + name + "\" loaded.");
            }

            public void ExportIfcSettings(object sender = null, RoutedEventArgs args = null)
            {
                string name = PsUi.AskText("Save the IFC setup", "What should this setup be called?",
                                           "House IFC 2x3", ThemeName, Window);
                if (string.IsNullOrEmpty(name))
                    return;
                name = PsConfig.SafeName(name, "setup");
                string path = PsConfig.IfcSetupPath(name);
                if (PsConfig.WriteIfcSetup(path, CollectIfc()))
                {
                    FillIfcSetups(selected: name);
                    Say("IFC setup saved as \"" + name + "\".");
                }
                else
                {
                    Say("That IFC setup could not be written.");
                }
            }

            public void ImportIfcSettings(object sender = null, RoutedEventArgs args = null)
            {
                string chosen = PsUi.PickFile(false, "Load an IFC setup", PsConfig.IfcSetupExtension,
                                              label: "RevoBIM IFC setup");
                if (string.IsNullOrEmpty(chosen))
                    return;
                Dictionary<string, string> values = PsConfig.ReadIfcSetup(chosen);
                if (values == null || values.Count == 0)
                {
                    new PsUi.Prompt(
                        title: "IFC setup",
                        headline: "That file holds no IFC settings.",
                        message: "A setup file is the plain text one this tool writes, with keys beginning \"ifc.\". " +
                                 "Revit's own exported IFC setup is a different format and cannot be read here.",
                        detail: chosen, primary: "Close",
                        themeName: ThemeName, owner: Window).Show();
                    return;
                }
                var merged = new Dictionary<string, string>(PsConfig.Defaults(), StringComparer.Ordinal);
                foreach (var pair in values)
                    merged[pair.Key] = pair.Value;
                WriteFields(merged, IfcFields);
                RefreshDependants();

                // Keep a copy so it shows in the Current Setup list next time,
                // rather than only living wherever it was picked up from.
                string name = PsConfig.SafeName(PsPaths.OsPathSplitExt(PsPaths.OsPathBaseName(chosen)).Root, "setup");
                List<string> taken = PsConfig.IfcSetupNames();
                name = PsConfig.UniqueTemplateName(taken, name);
                PsConfig.WriteIfcSetup(PsConfig.IfcSetupPath(name), merged);
                FillIfcSetups(selected: name);
                RefreshPlan();
                Say("IFC setup \"" + name + "\" loaded and kept.");
            }

            public void ExplainIfcHeader(object sender = null, RoutedEventArgs args = null)
            {
                Explain(
                    "File Header Information",
                    "This comes from the model, not from here.",
                    "Revit keeps the IFC file header - the description, the author, the organisation and the " +
                    "authorisation - against the project itself, and the exporter reads it straight from there. " +
                    "There is no API to override it per run, so a value typed here would be a value quietly " +
                    "thrown away.",
                    "Set it once in Revit: File > Export > Options > IFC Options, or the File Header Information " +
                    "button on Revit's own IFC export dialog. Every export from this tool then carries it.");
            }

            public void ExplainIfcAddress(object sender = null, RoutedEventArgs args = null)
            {
                Explain(
                    "Project Address",
                    "This comes from the model, not from here.",
                    "The IFC postal address is Revit's own Project Address, stored on the project information. " +
                    "The exporter reads it from there and the API offers no per-run override.",
                    "Manage > Project Information > Project Address, or the Project Address button on Revit's own " +
                    "IFC export dialog.");
            }

            public void ExplainIfcClassification(object sender = null, RoutedEventArgs args = null)
            {
                Explain(
                    "Classification Settings",
                    "This comes from the model, not from here.",
                    "Classification name, source, edition, edition date and location are stored against the " +
                    "project by Revit's IFC exporter and reused on every export, including this one. They are not " +
                    "among the named options the exporter accepts per run.",
                    "Set them once on Revit's own IFC export dialog, under Classification Settings. Uniclass or " +
                    "NRM entered there comes through on the files this tool writes.");
            }

            internal void Explain(string title, string headline, string message, string detail)
            {
                new PsUi.Prompt(title: title, headline: headline, message: message, detail: detail,
                                primary: "Close", themeName: ThemeName, owner: Window).Show();
            }

            public void BrowseRoot(object sender = null, RoutedEventArgs args = null)
            {
                string start = TextOf("RootFolderBox");
                if (string.IsNullOrEmpty(start))
                {
                    try
                    {
                        start = PsExport.Dirname(Doc.PathName ?? "");
                    }
                    catch (Exception)
                    {
                        start = "";
                    }
                }
                string chosen = PsUi.BrowseFolder(start);
                if (!string.IsNullOrEmpty(chosen))
                    SetTextValue(C("RootFolderBox"), chosen);
            }

            /// <summary>
            /// The folder picker. Deliberately not the file naming dialog: a name is
            /// one string with prefixes and separators, a path is a stack of levels.
            /// </summary>
            public void AddToken(object sender = null, RoutedEventArgs args = null)
            {
                PsModel.Row sampleRow = FirstTickedRow() ?? (Rows.Count > 0 ? Rows[0] : null);
                PsModel.RowLookup lookup = sampleRow != null ? LookupFor(sampleRow) : null;
                string label = "";
                if (sampleRow != null)
                    label = !string.IsNullOrEmpty(sampleRow.Number) ? sampleRow.Number : sampleRow.Name;
                string chosen = PsTokenWin.Pick(Catalogue, lookup, TextOf("TokenBox"), ThemeName, Window, label);
                if (chosen == null)
                    return;
                SetTextValue(C("TokenBox"), chosen);
            }

            public void MakeDefaultPrinter(object sender = null, RoutedEventArgs args = null)
            {
                string name = PsUi.ComboText(C<ComboBox>("PrinterCombo"));
                Settings.Set("default_printer", name == RevitPdf ? "" : name);
                Settings.Save();
                Say("\"" + name + "\" is now the default for new templates.");
            }

            public void OpenOrderDialog(object sender = null, RoutedEventArgs args = null)
            {
                var (jobs, _) = PlanJobs();
                if (jobs.Count == 0)
                {
                    Say("Nothing ticked to order.");
                    return;
                }
                List<(string Key, string Label)> entries = jobs.Select(job => (job.Key.ToString(Inv), job.Label)).ToList();
                if (CombineOrder.Count > 0)
                {
                    var position = new Dictionary<string, int>(StringComparer.Ordinal);
                    for (int index = 0; index < CombineOrder.Count; index++)
                        position[CombineOrder[index]] = index;
                    entries = entries.OrderBy(pair => position.TryGetValue(pair.Key, out int at) ? at : 1000000).ToList();
                }
                var dialog = new PsOrderWin.OrderWindow(entries, ThemeName, Window);
                List<string> chosen = dialog.Show();
                if (chosen == null)
                    return;
                CombineOrder = chosen;
                Say("Page order set for the combined file.");
            }

            /// <summary>
            /// Save the ticked sheets as a Revit View/Sheet Set. This writes to the
            /// model, so it goes out through the external event like everything else.
            /// </summary>
            public void SaveSheetSet(object sender = null, RoutedEventArgs args = null)
            {
                List<PsModel.Row> rows = TickedRows();
                if (rows.Count == 0)
                {
                    Say("Tick some sheets first.");
                    return;
                }
                string name = PsUi.AskText("Save a View/Sheet Set", "What should the set be called?",
                                           "RevoBIM export set", ThemeName, Window);
                if (string.IsNullOrEmpty(name))
                    return;
                List<Element> views = rows.Select(row => row.Element).ToList();
                Queue(uiapp => DoSaveSet(uiapp, name, views));
            }

            /// <summary>Write the set on Revit's thread, then refresh both tabs' lists.</summary>
            internal bool DoSaveSet(Autodesk.Revit.UI.UIApplication uiapp, string name, IEnumerable<Element> views)
            {
                List<View> sheets = views.Where(view => view != null).OfType<View>().ToList();
                // The Selection tab's set is exactly what is ticked there, views
                // included, so nothing already in the set is kept.
                var (ok, message) = PsModel.SaveViewSheetSet(Doc, name, sheets, keepOtherViews: false);

                OnUi(() =>
                {
                    RefreshSheetSets();
                    Say(message);
                });
                return ok;
            }

            /// <summary>
            /// Read the View/Sheet Sets again, for the Selection tab's filter and for
            /// the Document Register's set list alike.
            /// </summary>
            public void RefreshSheetSets()
            {
                SheetSets = PsModel.ReadSheetSets(Doc);
                PsModel.TagRowsWithSets(Rows, SheetSets);
                FillSheetSets();
            }
        }
    }
}
