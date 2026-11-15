using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Threading;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsWindow
    {
        public partial class ProSheetsWindow
        {
            // ==================================================================
            // theme
            // ==================================================================

            // Follow first, because the house standard is to match Revit's canvas.
            public static readonly string[] ThemeModes = { "follow", "dark", "light" };

            // How often the canvas is re-read while following. Two seconds is under
            // the threshold where a person notices the window is behind Revit.
            public const int ThemeWatchMs = 2000;

            /// <summary>
            /// Re-read Revit's canvas theme while the window is open. A timer rather
            /// than Revit's own theme changed event: a modeless window that leaks a
            /// handler onto the application outlives itself, and a DispatcherTimer
            /// stops when it is told to.
            /// </summary>
            internal void StartThemeWatch()
            {
                try
                {
                    var timer = new DispatcherTimer();
                    timer.Interval = TimeSpan.FromMilliseconds(ThemeWatchMs);
                    timer.Tick += ThemeTick;
                    timer.Start();
                    ThemeTimer = timer;
                }
                catch (Exception)
                {
                    ThemeTimer = null;
                }
            }

            internal void ThemeTick(object sender = null, EventArgs args = null)
            {
                if (ThemeMode != "follow")
                    return;
                string wanted;
                try
                {
                    wanted = PsTheme.DetectRevitTheme(ThemeName);
                }
                catch (Exception)
                {
                    return;
                }
                if (!string.IsNullOrEmpty(wanted) && wanted != ThemeName)
                {
                    WearTheme(wanted);
                    SayTheme();
                }
            }

            /// <summary>Put a palette on the live window, repainting what code drew.</summary>
            internal void WearTheme(string name)
            {
                ThemeName = name;
                PsTheme.Apply(Window, ThemeName);
                // The sort outlines, the run colours and the group row washes are
                // brushes set in code, so they do not follow a palette swap.
                PaintSortHeaders();
                ApplyGrouping();
                ApplyFilters();
                try
                {
                    C<DataGrid>("SheetGrid").Items.Refresh();
                }
                catch (Exception)
                {
                }
                // The register's heading bands, washes and tab colours are set in
                // code too.
                try
                {
                    Register.Repaint();
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Cycle Auto, Dark, Light.</summary>
            public void ToggleTheme(object sender = null, RoutedEventArgs args = null)
            {
                int place = Array.IndexOf(ThemeModes, ThemeMode);
                if (place < 0)
                    place = 0;
                ThemeMode = ThemeModes[(place + 1) % ThemeModes.Length];
                WearTheme(PsTheme.Resolve(ThemeMode, ThemeName));
                SayTheme();
                Settings.Set("theme_mode", ThemeMode);
                Settings.Save();
            }

            /// <summary>Offer setup the first time this machine opens the tool.</summary>
            internal void FirstRunSetup()
            {
                try
                {
                    if (SkipFirstRunSetup || !PsSetupWin.Needed(Settings))
                        return;
                    OpenSetup(firstRun: true);
                }
                catch (Exception)
                {
                }
            }

            /// <summary>
            /// The per machine settings, on demand or on a first run. section
            /// scrolls straight to one part of the window - the register's Settings
            /// button opens it at the register's own section.
            /// </summary>
            public void OpenSetup(object sender = null, RoutedEventArgs args = null, bool firstRun = false,
                                  string section = null)
            {
                string seriesBefore = SeriesColumn();
                bool saved;
                try
                {
                    saved = PsSetupWin.Run(Doc, Settings, ThemeName, Window, firstRun, Catalogue, focus: section);
                }
                catch (Exception)
                {
                    return;
                }
                if (!saved)
                    return;
                // Push what was chosen onto the live window rather than waiting for
                // a reopen.
                string printer = Settings.Text("default_printer") ?? "";
                PsUi.FillCombo(C<ComboBox>("PrinterCombo"), PrinterList,
                               selected: string.IsNullOrEmpty(printer) ? RevitPdf : printer);
                if (!string.IsNullOrEmpty(printer))
                {
                    string staging = RecallStaging(printer);
                    if (!string.IsNullOrEmpty(staging))
                        SetTextValue(C("StagingBox"), staging);
                }
                if (string.IsNullOrEmpty(TextOf("RootFolderBox")))
                    SetTextValue(C("RootFolderBox"), Settings.Text("default_root", ""));
                PrinterChanged(null, null);
                // The series and discipline columns come from setup, so the list has
                // to be rebuilt around whatever was just chosen.
                ColumnOrders = new Dictionary<string, List<string>>(StringComparer.Ordinal);
                AdoptColumns(ModeName());
                string series = SeriesColumn();
                if (!string.IsNullOrEmpty(series) && ColumnOrder.Contains(series) && SortStack.Count == 0)
                    SortStack = new List<(string ColId, bool Descending)> { (series, false) };
                // A sheet series named (or changed) just now is what the Sheets list
                // groups on first, whatever it was left sorted by before.
                if (!string.IsNullOrEmpty(series) && series != seriesBefore && !IsViewsMode())
                {
                    var stack = new List<(string ColId, bool Descending)> { (series, false) };
                    stack.AddRange(SortStack.Where(pair => pair.ColId != series).Take(MaxSortLevels - 1));
                    SortStack = stack;
                    if (!ColumnOrder.Contains(series))
                    {
                        var order = new List<string>(ColumnOrder);
                        int where = order.Contains("fname") ? order.IndexOf("fname") : order.Count;
                        order.Insert(where, series);
                        ColumnOrder = order;
                        BuildColumns();
                    }
                    EnsureGrouped();
                    Collapsed = new HashSet<int>();
                    RememberSort();
                }
                ApplyOrder();
                ApplyGrouping();
                ApplyFilters();
                PaintSortHeaders();
                RefreshPlan();
                // The register's tabs and headings come from the same two
                // parameters, so it reads again too.
                Register.Invalidate();
                Say("Setup saved for this machine.");
            }

            internal void SayTheme()
            {
                string label;
                string tip;
                if (ThemeMode == "follow")
                {
                    label = "Auto (" + ThemeName + ")";
                    tip = "Following Revit. Click to pin this window to dark whatever Revit does.";
                }
                else if (ThemeMode == "dark")
                {
                    label = "Dark";
                    tip = "Pinned to dark. Click for light.";
                }
                else
                {
                    label = "Light";
                    tip = "Pinned to light. Click to follow Revit again.";
                }
                PsUi.SetContent(C("ThemeChip"), label);
                try
                {
                    ((FrameworkElement)C("ThemeChip")).ToolTip = tip;
                }
                catch (Exception)
                {
                }
            }

            // ==================================================================
            // the pre-selection
            // ==================================================================

            /// <summary>Isolate to whatever was selected in Revit before the tool opened.</summary>
            internal void ApplyPreselection()
            {
                List<PsModel.Row> picked = PsModel.PreselectedRows(Uidoc, Rows);
                if (picked == null || picked.Count == 0)
                    return;
                PreselectedKeys = new HashSet<long>(picked.Select(row => row.Key));
                IsolatedKeys = new HashSet<long>(PreselectedKeys);
                PsUi.SetVisible(C("ShowAllCheck"), true);
                SetChecked(C("ShowAllCheck"), false);
                SayIsolation();
            }

            /// <summary>
            /// Show everything, or go back to the Revit selection. What is ticked is
            /// never touched by this.
            /// </summary>
            internal void ShowAllChanged(object sender, RoutedEventArgs args)
            {
                if (FlagOf("ShowAllCheck"))
                    IsolatedKeys = null;
                else
                    IsolatedKeys = new HashSet<long>(PreselectedKeys);
                ApplyFilters();
                RefreshCounts();
                SayIsolation();
            }

            internal void SayIsolation()
            {
                object note = C("IsolationNote");
                int count = PreselectedKeys.Count;
                if (count == 0)
                {
                    PsUi.SetVisible(note, false);
                    return;
                }
                if (IsolatedKeys == null)
                {
                    PsUi.SetText(note, string.Format(Inv, "{0} sheet{1} came from your Revit selection and stay ticked",
                                                     count, Plural(count)));
                }
                else
                {
                    PsUi.SetText(note, string.Format(Inv, "Showing your {0} selected sheet{1}", count, Plural(count)));
                }
                PsUi.SetVisible(note, true);
            }

            public void ClearIsolation(object sender = null, RoutedEventArgs args = null)
            {
                if (C("ShowAllCheck") is ToggleButton box)
                {
                    try
                    {
                        box.IsChecked = true;
                        return;
                    }
                    catch (Exception)
                    {
                    }
                }
                IsolatedKeys = null;
                ApplyFilters();
                RefreshCounts();
            }

            // ==================================================================
            // profiles
            // ==================================================================

            internal void LoadLastProfile()
            {
                Ready = false;
                string name = "";
                if (Settings.Flag("remember_last_profile", true))
                    name = Settings.Text("last_profile");
                List<string> available = PsConfig.ProfileNames(Doc);
                if (!string.IsNullOrEmpty(name) && available.Contains(name))
                {
                    Profile = PsConfig.LoadProfile(Doc, name);
                    FillProfiles(selected: name);
                }
                else
                {
                    Profile = PsConfig.Defaults();
                    string defaultPrinter = Settings.Text("default_printer");
                    // Nothing but an explicit choice goes in here. A driver writes
                    // nothing at all until "Driver saves to" is filled in, so it is
                    // offered in the setup window instead, with the folder it needs.
                    if (!string.IsNullOrEmpty(defaultPrinter))
                        Profile["pdf.printer"] = defaultPrinter;
                }
                ApplyProfile(Profile);
                // The sort and grouping set by hand last time win over the
                // template's; the template's still apply when it is picked.
                if (RestoreSort())
                    BuildColumns();
                Ready = true;
            }

            internal void ProfileChanged(object sender, SelectionChangedEventArgs args)
            {
                string name = PsUi.ComboText(C<ComboBox>("ProfileCombo"), NoTemplate);
                if (string.IsNullOrEmpty(name))
                    return;
                Profile = PsConfig.LoadProfile(Doc, name);
                ApplyProfile(Profile);
                Settings.Set("last_profile", name);
                Settings.Save();
                RememberSort();
                RefreshAll();
                Say("Template \"" + name + "\" loaded.");
            }

            /// <summary>Push a profile dictionary onto the controls.</summary>
            internal void ApplyProfile(Dictionary<string, string> profile)
            {
                void Flag(string key, string controlName, bool @default = false)
                {
                    if (!(C(controlName) is ToggleButton control))
                        return;
                    try
                    {
                        control.IsChecked = PsConfig.GetBool(profile, key, @default);
                    }
                    catch (Exception)
                    {
                    }
                }

                void Text(string key, string controlName, string @default = "")
                {
                    object control = C(controlName);
                    if (control == null)
                        return;
                    SetTextValue(control, PsConfig.GetText(profile, key, @default));
                }

                // Mode first: it decides which column set the saved order below is
                // even allowed to be.
                string wantedMode = PsConfig.GetText(profile, "mode", "sheets");
                if (wantedMode != "sheets" && wantedMode != "views")
                    wantedMode = "sheets";
                if (wantedMode != ModeName())
                {
                    try
                    {
                        C<ToggleButton>("ViewsRadio").IsChecked = wantedMode == "views";
                        C<ToggleButton>("SheetsRadio").IsChecked = wantedMode != "views";
                    }
                    catch (Exception)
                    {
                    }
                    // Flipping the radio raises ModeChanged, which does the re-read
                    // and the column swap itself - but only once the window is up.
                    // At startup it returns early, so the read has to happen here.
                    if (!Ready)
                        ReadModel();
                }

                var formats = new HashSet<string>(PsConfig.GetList(profile, "formats", new List<string> { "pdf" }),
                                                  StringComparer.Ordinal);
                foreach (var (fmt, tick, _, _, _, _, live) in Formats)
                {
                    if (!(C(tick) is ToggleButton box))
                        continue;
                    try
                    {
                        box.IsChecked = live && formats.Contains(fmt);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }

                string placement = PsConfig.GetText(profile, "pdf.placement", "center");
                try
                {
                    C<ToggleButton>("PlaceCenterRadio").IsChecked = placement != "offset";
                    C<ToggleButton>("PlaceOffsetRadio").IsChecked = placement == "offset";
                }
                catch (Exception)
                {
                }
                Text("pdf.offset_x", "OffsetXBox", "0.00");
                Text("pdf.offset_y", "OffsetYBox", "0.00");

                string zoomMode = PsConfig.GetText(profile, "pdf.zoom_mode", "zoom");
                try
                {
                    C<ToggleButton>("FitPageRadio").IsChecked = zoomMode == "fit";
                    C<ToggleButton>("ZoomRadio").IsChecked = zoomMode != "fit";
                }
                catch (Exception)
                {
                }
                Text("pdf.zoom", "ZoomBox", "100");

                string hidden = PsConfig.GetText(profile, "pdf.hidden_line", "vector");
                try
                {
                    C<ToggleButton>("VectorRadio").IsChecked = hidden != "raster";
                    C<ToggleButton>("RasterRadio").IsChecked = hidden == "raster";
                }
                catch (Exception)
                {
                }

                SetComboIndex("MarginCombo", MarginChoices, PsConfig.GetText(profile, "pdf.margin", "nomargin"));
                SetComboIndex("RasterQualityCombo", RasterChoices, PsConfig.GetText(profile, "pdf.raster_quality", "high"));
                SetComboIndex("ColorsCombo", ColourChoices, PsConfig.GetText(profile, "pdf.colors", "color"));
                SetComboIndex("DwgVersionCombo", DwgVersions, PsConfig.GetText(profile, "dwg.version", "default"));

                Flag("pdf.view_links_blue", "ViewLinksBlueCheck", true);
                Flag("pdf.hide_ref_planes", "HideRefPlanesCheck", true);
                Flag("pdf.hide_unreferenced_tags", "HideViewTagsCheck", true);
                Flag("pdf.hide_scope_boxes", "HideScopeBoxesCheck", true);
                Flag("pdf.hide_crop_boundaries", "HideCropCheck", true);
                Flag("pdf.replace_halftone", "HalftoneCheck", false);
                Flag("pdf.mask_coincident", "MaskCoincidentCheck", false);
                Flag("pdf.keep_paper_size", "KeepPaperSizeCheck", true);
                Flag("dwg.shared_coords", "DwgSharedCoordsCheck", true);
                Flag("dwg.external_refs", "DwgXrefCheck", false);
                Flag("out.folder_per_format", "FolderPerFormatCheck", true);
                Flag("out.overwrite", "OverwriteCheck", true);
                Flag("filter.active_only", "OnSheetListCheck", false);
                Flag("run.suppress_dialogs", "SuppressCheck", Settings.Flag("suppress_dialogs"));
                Flag("run.open_folder", "OpenFolderCheck", Settings.Flag("open_folder_after_export", true));
                Flag("run.debug", "DebugCheck", Settings.Flag("debug"));

                bool combine = PsConfig.GetBool(profile, "pdf.combine", false);
                try
                {
                    C<ToggleButton>("CombineRadio").IsChecked = combine;
                    C<ToggleButton>("SeparateFilesRadio").IsChecked = !combine;
                }
                catch (Exception)
                {
                }

                string asked = PsConfig.GetText(profile, "pdf.printer", "");
                string stagingAsked = PsConfig.GetText(profile, "pdf.staging", "");
                var (printer, refused, why) = UsablePrinter(
                    asked,
                    !string.IsNullOrEmpty(stagingAsked) ? stagingAsked : RecallStaging(asked),
                    PrinterList, NativePdf,
                    Settings.Flag("prefer_native_pdf", true));
                PsUi.FillCombo(C<ComboBox>("PrinterCombo"), PrinterList,
                               selected: string.IsNullOrEmpty(printer) ? RevitPdf : printer);
                if (!string.IsNullOrEmpty(refused))
                    PrinterRefused = (refused, why);

                string setup = PsConfig.GetText(profile, "dwg.setup", "");
                var setupCombo = C<ComboBox>("DwgSetupCombo");
                if (setupCombo != null)
                {
                    var setups = new List<string> { DefaultDwgSetup };
                    setups.AddRange(PsExport.ListDwgSetups(Doc));
                    PsUi.FillCombo(setupCombo, setups, selected: string.IsNullOrEmpty(setup) ? DefaultDwgSetup : setup);
                }

                WriteFields(profile, NwcFields);
                WriteFields(profile, IfcFields);
                string wantedPhase = PsConfig.GetText(profile, "ifc.phase", "");
                PsUi.FillCombo(C<ComboBox>("IfcPhaseCombo"), IfcPhaseNames(),
                               selected: string.IsNullOrEmpty(wantedPhase) ? IfcDefaultPhase : wantedPhase);
                var ifcSetups = new List<string> { IfcInSession };
                ifcSetups.AddRange(PsConfig.IfcSetupNames());
                PsUi.FillCombo(C<ComboBox>("IfcSetupCombo"), ifcSetups, selected: IfcInSession);
                RefreshDependants();

                Text("pdf.staging", "StagingBox");
                Text("out.root", "RootFolderBox");
                Text("out.tokens", "TokenBox");
                if (string.IsNullOrEmpty(TextOf("RootFolderBox")))
                    SetTextValue(C("RootFolderBox"), Settings.Text("default_root", ""));

                ColumnOrders = new Dictionary<string, List<string>>(StringComparer.Ordinal);
                List<string> saved = PsConfig.GetList(profile, "cols", new List<string>())
                                             .Where(name => !string.IsNullOrEmpty(name)).ToList();
                // Saved as the full ordered list from 1.6.0 on. An older template
                // holds only the parameter names, so those go on the end where they
                // used to be rather than being thrown away.
                if (saved.Count > 0 && saved.All(name => KnownColumns.Contains(name) ||
                                                         name.StartsWith("p:", StringComparison.Ordinal)))
                {
                    ColumnOrder = SaneOrder(saved);
                }
                else
                {
                    ColumnOrder = StartingColumns(ModeName(), DefaultExtras(), BrowserNames)
                        .Concat(saved.Select(name => "p:" + name)).ToList();
                }
                SortStack = new List<(string ColId, bool Descending)>();
                foreach (string piece in PsConfig.GetList(profile, "sort.stack", new List<string>()))
                {
                    if (string.IsNullOrEmpty(piece))
                        continue;
                    var (colId, direction) = Partition(piece, '|');
                    if (!string.IsNullOrEmpty(colId))
                        SortStack.Add((colId, direction == "desc"));
                }
                ApplyDefaultSort();
                Grouped = PsConfig.GetBool(profile, "sort.grouped", true);
                foreach (var (key, prop) in new[] { ("win.width", "Width"), ("win.height", "Height") })
                {
                    int value = PsConfig.GetInt(profile, key, 0);
                    if (value <= 0)
                        continue;
                    try
                    {
                        double least = prop == "Width" ? Window.MinWidth : Window.MinHeight;
                        if (value >= least)
                        {
                            if (prop == "Width")
                                Window.Width = value;
                            else
                                Window.Height = value;
                        }
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                // A template's widths win when it has any; otherwise whatever this
                // machine was left at last time.
                SavedWidths = PsConfig.GetList(profile, "colwidths", new List<string>());
                if (SavedWidths == null || SavedWidths.Count == 0)
                    SavedWidths = PsConfig.GetList(Settings.Store, "column_widths", new List<string>());
                SetChecked(C("GroupCheck"), Grouped);
                BuildColumns();
                TemplateSort = "";
                if (SortStack.Count > 0)
                {
                    string first = SortStack[0].ColId;
                    string series = SeriesColumn();
                    if (!string.IsNullOrEmpty(series) && first != series)
                        TemplateSort = HeadingOf(first);
                }
                RulesByMode = PsNaming.RulesByMode(profile);
                AdoptRules(ModeName());
                CombineOrder = PsConfig.GetList(profile, "pdf.order", new List<string>());

                PlacementChanged(null, null);
                CombineChanged(null, null);
                XrefChanged(null, null);
                PrinterChanged(null, null);
                var refusedNow = PrinterRefused;
                if (refusedNow != null)
                {
                    PrinterRefused = null;
                    var (name, reason) = refusedNow.Value;
                    if (reason == "prefer-native")
                    {
                        Say("This template asks for \"" + name + "\", but this machine is set to use " + RevitPdf +
                            " - which needs no driver, no folder and no setup. Untick that in Set up if you want " +
                            "the driver.");
                    }
                    else if (reason == "not-installed")
                    {
                        Say("This template asks for \"" + name + "\", which is not installed here, so it would " +
                            "write nothing - switched to " + RevitPdf + ".");
                    }
                    else
                    {
                        Say("This template asks for \"" + name + "\", which has no \"Driver saves to\" folder set " +
                            "on this machine, so it would write nothing - switched to " + RevitPdf + ". Set up " +
                            "puts it back.");
                    }
                }
                SayTheme();
            }

            internal void SetComboIndex(string controlName, IList<(string Label, string Key)> choices, string stored)
            {
                if (!(C(controlName) is Selector combo))
                    return;
                try
                {
                    combo.SelectedIndex = Pick(choices, stored);
                }
                catch (Exception)
                {
                }
            }

            internal string ComboValue(string controlName, IList<(string Label, string Key)> choices, string @default)
            {
                try
                {
                    int index = ((Selector)C(controlName)).SelectedIndex;
                    if (index >= 0 && index < choices.Count)
                        return choices[index].Key;
                }
                catch (Exception)
                {
                }
                return @default;
            }

            /// <summary>One field, control to profile. See NwcFields for the table.</summary>
            internal void ReadField(IDictionary<string, string> profile, Field field)
            {
                if (field.Kind == "flag")
                {
                    try
                    {
                        profile[field.Key] = ((ToggleButton)C(field.ControlName)).IsChecked == true ? "1" : "0";
                    }
                    catch (Exception)
                    {
                        profile[field.Key] = field.FlagDefault ? "1" : "0";
                    }
                }
                else if (field.Kind == "text")
                {
                    profile[field.Key] = TextOf(field.ControlName, field.TextDefault);
                }
                else
                {
                    profile[field.Key] = ComboValue(field.ControlName, field.Choices, field.TextDefault);
                }
            }

            /// <summary>One field, profile to control.</summary>
            internal void WriteField(IDictionary<string, string> profile, Field field)
            {
                object control = C(field.ControlName);
                if (control == null)
                    return;
                if (field.Kind == "flag")
                {
                    SetChecked(control, PsConfig.GetBool(profile, field.Key, field.FlagDefault));
                }
                else if (field.Kind == "text")
                {
                    SetTextValue(control, PsConfig.GetText(profile, field.Key, field.TextDefault));
                }
                else
                {
                    SetComboIndex(field.ControlName, field.Choices,
                                  PsConfig.GetText(profile, field.Key, field.TextDefault));
                }
            }

            internal void ReadFields(IDictionary<string, string> profile, IEnumerable<Field> fields)
            {
                foreach (Field field in fields)
                    ReadField(profile, field);
            }

            internal void WriteFields(IDictionary<string, string> profile, IEnumerable<Field> fields)
            {
                foreach (Field field in fields)
                    WriteField(profile, field);
            }

            /// <summary>Read the controls back into a profile dictionary.</summary>
            internal Dictionary<string, string> CollectProfile()
            {
                Dictionary<string, string> profile = PsConfig.Defaults();

                void Flag(string key, string controlName, bool @default = false)
                {
                    try
                    {
                        profile[key] = ((ToggleButton)C(controlName)).IsChecked == true ? "1" : "0";
                    }
                    catch (Exception)
                    {
                        profile[key] = @default ? "1" : "0";
                    }
                }

                void Text(string key, string controlName, string @default = "")
                {
                    try
                    {
                        string value = GetTextValue(C(controlName));
                        profile[key] = string.IsNullOrEmpty(value) ? @default : value;
                    }
                    catch (Exception)
                    {
                        profile[key] = @default;
                    }
                }

                profile["mode"] = IsViewsMode() ? "views" : "sheets";
                profile["formats"] = PsConfig.PutList(ChosenFormats());

                try
                {
                    profile["pdf.placement"] = ((ToggleButton)C("PlaceOffsetRadio")).IsChecked == true ? "offset" : "center";
                }
                catch (Exception)
                {
                    profile["pdf.placement"] = "center";
                }
                profile["pdf.margin"] = ComboValue("MarginCombo", MarginChoices, "nomargin");
                Text("pdf.offset_x", "OffsetXBox", "0.0");
                Text("pdf.offset_y", "OffsetYBox", "0.0");
                try
                {
                    profile["pdf.zoom_mode"] = ((ToggleButton)C("FitPageRadio")).IsChecked == true ? "fit" : "zoom";
                }
                catch (Exception)
                {
                    profile["pdf.zoom_mode"] = "zoom";
                }
                Text("pdf.zoom", "ZoomBox", "100");
                try
                {
                    profile["pdf.hidden_line"] = ((ToggleButton)C("RasterRadio")).IsChecked == true ? "raster" : "vector";
                }
                catch (Exception)
                {
                    profile["pdf.hidden_line"] = "vector";
                }
                profile["pdf.raster_quality"] = ComboValue("RasterQualityCombo", RasterChoices, "high");
                profile["pdf.colors"] = ComboValue("ColorsCombo", ColourChoices, "color");

                Flag("pdf.view_links_blue", "ViewLinksBlueCheck", true);
                Flag("pdf.hide_ref_planes", "HideRefPlanesCheck", true);
                Flag("pdf.hide_unreferenced_tags", "HideViewTagsCheck", true);
                Flag("pdf.hide_scope_boxes", "HideScopeBoxesCheck", true);
                Flag("pdf.hide_crop_boundaries", "HideCropCheck", true);
                Flag("pdf.replace_halftone", "HalftoneCheck", false);
                Flag("pdf.mask_coincident", "MaskCoincidentCheck", false);
                Flag("pdf.keep_paper_size", "KeepPaperSizeCheck", true);
                try
                {
                    profile["pdf.combine"] = ((ToggleButton)C("CombineRadio")).IsChecked == true ? "1" : "0";
                }
                catch (Exception)
                {
                    profile["pdf.combine"] = "0";
                }

                string printer = PsUi.ComboText(C<ComboBox>("PrinterCombo"));
                profile["pdf.printer"] = printer == RevitPdf ? "" : printer;

                string setup = PsUi.ComboText(C<ComboBox>("DwgSetupCombo"));
                profile["dwg.setup"] = setup == DefaultDwgSetup ? "" : setup;
                profile["dwg.version"] = ComboValue("DwgVersionCombo", DwgVersions, "default");
                Flag("dwg.shared_coords", "DwgSharedCoordsCheck", true);
                Flag("dwg.external_refs", "DwgXrefCheck", false);

                ReadFields(profile, NwcFields);
                ReadFields(profile, IfcFields);
                string phase = PsUi.ComboText(C<ComboBox>("IfcPhaseCombo"), IfcDefaultPhase);
                profile["ifc.phase"] = phase == IfcDefaultPhase ? "" : phase;
                profile["ifc.phase_id"] = IfcPhases.TryGetValue(phase ?? "", out string phaseId) ? phaseId : "";

                Text("pdf.staging", "StagingBox");
                Text("out.root", "RootFolderBox");
                Text("out.tokens", "TokenBox");
                Flag("out.folder_per_format", "FolderPerFormatCheck", true);
                Flag("out.overwrite", "OverwriteCheck", true);
                Flag("filter.active_only", "OnSheetListCheck", false);
                Flag("run.suppress_dialogs", "SuppressCheck", false);
                Flag("run.open_folder", "OpenFolderCheck", true);
                Flag("run.debug", "DebugCheck", false);

                string setName = PsUi.ComboText(C<ComboBox>("SheetSetCombo"), NoSet);
                profile["filter.sheet_set"] = setName == NoSet ? "" : setName;

                profile["selected"] = PsConfig.PutList(TickedKeys().OrderBy(key => key, StringComparer.Ordinal));
                profile["pdf.order"] = PsConfig.PutList(CombineOrder);
                profile["cols"] = PsConfig.PutList(ColumnOrder);
                profile["sort.stack"] = PsConfig.PutList(
                    SortStack.Select(pair => pair.ColId + "|" + (pair.Descending ? "desc" : "asc")));
                profile["sort.grouped"] = Grouped ? "1" : "0";
                profile["colwidths"] = PsConfig.PutList(ColumnWidths());
                try
                {
                    var (width, height) = Chrome.TrueSize();
                    profile["win.width"] = ((int)width).ToString(Inv);
                    profile["win.height"] = ((int)height).ToString(Inv);
                }
                catch (Exception)
                {
                }
                ParkRules(ModeName());
                PsNaming.StoreRulesByMode(RulesByMode, profile);
                return profile;
            }

            public void NewProfile(object sender = null, RoutedEventArgs args = null)
            {
                string name = PsUi.AskText("Save a template", "What should this template be called?",
                                           "Standard issue", ThemeName, Window);
                if (string.IsNullOrEmpty(name))
                    return;
                name = PsConfig.SafeName(name, "template");
                Dictionary<string, string> profile = CollectProfile();
                if (PsConfig.SaveProfile(Doc, name, profile))
                {
                    Profile = profile;
                    FillProfiles(selected: name);
                    Settings.Set("last_profile", name);
                    Settings.Save();
                    Say("Template \"" + name + "\" saved against this project.");
                }
                else
                {
                    Say("That template could not be written. Check %APPDATA%.");
                }
            }

            public void SaveProfile(object sender = null, RoutedEventArgs args = null)
            {
                string name = PsUi.ComboText(C<ComboBox>("ProfileCombo"), NoTemplate);
                if (string.IsNullOrEmpty(name))
                {
                    NewProfile();
                    return;
                }
                Dictionary<string, string> profile = CollectProfile();
                if (PsConfig.SaveProfile(Doc, name, profile))
                {
                    Profile = profile;
                    Say("Template \"" + name + "\" updated.");
                }
                else
                {
                    Say("That template could not be written. Check %APPDATA%.");
                }
            }

            public void DeleteProfile(object sender = null, RoutedEventArgs args = null)
            {
                string name = PsUi.ComboText(C<ComboBox>("ProfileCombo"), NoTemplate);
                if (string.IsNullOrEmpty(name))
                    return;
                string answer = new PsUi.Prompt(
                    title: "Delete a template",
                    headline: "Delete \"" + name + "\"?",
                    message: "This only removes the saved settings. Nothing that has already been exported is touched.",
                    primary: "Delete", secondary: "Keep it",
                    themeName: ThemeName, owner: Window).Show();
                if (answer != "primary")
                    return;
                PsConfig.DeleteProfile(Doc, name);
                FillProfiles();
                Say("Template \"" + name + "\" deleted.");
            }

            // ==================================================================
            // templates as files
            // ==================================================================

            /// <summary>Write every template for this project into one file.</summary>
            public void ExportTemplates(object sender = null, RoutedEventArgs args = null)
            {
                List<string> names = PsConfig.ProfileNames(Doc);
                string current = PsUi.ComboText(C<ComboBox>("ProfileCombo"), NoTemplate);
                var bundle = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
                foreach (string name in names)
                    bundle[name] = PsConfig.LoadProfile(Doc, name);
                // What is on screen but never saved would be silently lost, so it
                // goes in under the loaded name, or under a plain one.
                Dictionary<string, string> live = CollectProfile();
                bundle[string.IsNullOrEmpty(current) ? "Current settings" : current] = live;

                if (bundle.Count == 0)
                {
                    Say("There is nothing to save yet.");
                    return;
                }

                string suggested = PsConfig.ProjectKey(Doc) + " templates" + PsConfig.BundleExtension;
                string path = PsUi.PickFile(true, "Save templates to a file", PsConfig.BundleExtension, suggested);
                if (string.IsNullOrEmpty(path))
                    return;
                if (PsConfig.WriteBundle(path, bundle))
                    Say(string.Format(Inv, "{0} template{1} written to {2}", bundle.Count, Plural(bundle.Count), path));
                else
                    Say("That file could not be written.");
            }

            /// <summary>Load templates from a file, merging or replacing.</summary>
            public void ImportTemplates(object sender = null, RoutedEventArgs args = null)
            {
                string path = PsUi.PickFile(false, "Load templates from a file", PsConfig.BundleExtension);
                if (string.IsNullOrEmpty(path))
                    return;
                Dictionary<string, Dictionary<string, string>> incoming = PsConfig.ReadBundle(path);
                if (incoming == null || incoming.Count == 0)
                {
                    new PsUi.Prompt(
                        title: "Load templates",
                        headline: "Nothing in that file looked like a template.",
                        message: "A bundle is plain text with a line reading @template=<name> before each one. " + path,
                        primary: "Close", themeName: ThemeName, owner: Window).Show();
                    return;
                }

                List<string> existing = PsConfig.ProfileNames(Doc);
                var clashes = incoming.Keys.Where(name => existing.Contains(name)).ToList();
                List<string> incomingNames = incoming.Keys.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();

                bool replacing;
                if (existing.Count > 0)
                {
                    var detail = new List<string> { "Coming in:" };
                    foreach (string name in incomingNames)
                    {
                        string mark = existing.Contains(name) ? "  (name already used)" : "";
                        detail.Add("   " + name + mark);
                    }
                    detail.Add("");
                    detail.Add("Already here:");
                    foreach (string name in existing)
                        detail.Add("   " + name);

                    string answer = new PsUi.Prompt(
                        title: "Load templates",
                        headline: string.Format(Inv, "{0} template{1} in that file.", incoming.Count, Plural(incoming.Count)),
                        message: string.Format(Inv,
                            "Merge keeps what you already have and brings these in alongside; {0} Replace all " +
                            "removes the {1} template{2} already saved against this project first.",
                            clashes.Count > 0 ? "a repeated name gains (1), (2) and so on." : "",
                            existing.Count, Plural(existing.Count)),
                        detail: string.Join("\n", detail),
                        primary: "Merge", secondary: "Replace all",
                        themeName: ThemeName, owner: Window).Show();
                    if (answer == null)
                        return;
                    replacing = answer == "secondary";
                }
                else
                {
                    replacing = false;
                }

                if (replacing)
                {
                    foreach (string name in existing)
                        PsConfig.DeleteProfile(Doc, name);
                    existing = new List<string>();
                }

                var taken = new List<string>(existing);
                int written = 0;
                var renamed = new List<(string From, string To)>();
                foreach (string name in incomingNames)
                {
                    string final = PsConfig.UniqueTemplateName(taken, name);
                    if (final != name)
                        renamed.Add((name, final));
                    if (PsConfig.SaveProfile(Doc, final, incoming[name]))
                    {
                        taken.Add(final);
                        written++;
                    }
                }

                FillProfiles();
                string message = string.Format(Inv, "{0} template{1} loaded.", written, Plural(written));
                if (renamed.Count > 0)
                {
                    message += string.Format(Inv, " {0} renamed to avoid a clash: {1}.", renamed.Count,
                                             string.Join(", ", renamed.Take(4).Select(pair => pair.From + " -> " + pair.To)));
                }
                Say(message);
            }
        }
    }
}
