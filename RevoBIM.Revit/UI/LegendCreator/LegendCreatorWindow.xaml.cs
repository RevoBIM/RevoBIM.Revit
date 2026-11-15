using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using Autodesk.Revit.DB;
using RevoBIM.Tools.LegendCreator;
using static RevoBIM.Tools.LegendCreator.LgcCore;
using static RevoBIM.Tools.LegendCreator.LgcLogic;
using Grid = System.Windows.Controls.Grid;
using TextBlock = System.Windows.Controls.TextBlock;
using Border = System.Windows.Controls.Border;
using CheckBox = System.Windows.Controls.CheckBox;
using HorizontalAlignment = System.Windows.HorizontalAlignment;
using VerticalAlignment = System.Windows.VerticalAlignment;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.LegendCreator
{
    /// <summary>
    /// The tool window: family legends on one tab, system colours on the
    /// other. Dark and light, switched from the chip in the header.
    /// Port of lgc_windows.CategoryPicker.
    /// </summary>
    public partial class LegendCreatorWindow : Window
    {
        private readonly LgcModel model;
        private readonly bool familyReady;
        private readonly List<(string Name, ElementId Id)> phases;
        private readonly List<(string Name, ElementId Id)> textTypes;
        private readonly Dictionary<string, string> settings;
        private readonly WindowDrawer drawer;

        private List<(CheckBox Check, CategoryInfo Info, Border Row)> rows = new List<(CheckBox, CategoryInfo, Border)>();
        private List<CategoryInfo> infos = new List<CategoryInfo>();
        private readonly Dictionary<string, List<CategoryInfo>> cache = new Dictionary<string, List<CategoryInfo>>();
        private Dictionary<string, double> baseDistances;
        private Dictionary<string, double> capturedBeforeScale;

        private readonly List<(string Name, View View)> templates;
        private List<int> templateCounts = new List<int>();
        private List<LegendEntry> sysEntries = new List<LegendEntry>();
        private List<(CheckBox Check, LegendEntry Entry, Border Row)> sysRows = new List<(CheckBox, LegendEntry, Border)>();
        private Dictionary<string, double> sysHeights;
        private Dictionary<string, double> sysBase;
        private Dictionary<string, double> sysCaptured;
        private string kindKey;
        private bool loading = true;

        private string themeMode;
        private Dictionary<string, string> palette;

        // --- what the run reads back once the window has closed ---
        public string ThemeName { get; private set; }
        public string Mode { get; private set; } = "family";
        public List<CategoryInfo> FamilyResult { get; private set; } = new List<CategoryInfo>();
        public List<LegendEntry> SystemResult { get; private set; } = new List<LegendEntry>();
        public FamilyOptions FamilyOpts { get; private set; }
        public SystemOptions SystemOpts { get; private set; }
        public List<string> SysNotes { get; private set; } = new List<string>();
        public bool DebugTicked => debug_cb.IsChecked == true;
        public bool HasResult => Mode == "system" ? SystemResult.Count > 0 : FamilyResult.Count > 0;

        public LegendCreatorWindow(LgcModel model, List<(string, ElementId)> phases,
                                   List<(string, ElementId)> textTypes, Dictionary<string, string> settings,
                                   bool familyReady)
        {
            InitializeComponent();
            this.model = model;
            this.familyReady = familyReady;
            this.phases = phases;
            this.textTypes = textTypes;
            this.settings = settings;

            version_tb.Text = "v" + LgcCore.Version;
            FitToScreen();
            debug_cb.IsChecked = settings.Get("debug", "0") == "1";
            themeMode = settings.Get("theme_mode", ThemeAuto);
            if (!ThemeOrder.Contains(themeMode)) themeMode = ThemeAuto;
            ThemeName = LgcTheme.ResolveTheme(themeMode);
            palette = LgcTheme.ApplyPalette(this, ThemeName);
            drawer = new WindowDrawer(this, header_bar, shrink_btn); // before WireEvents: it sees keys first
            WireEvents();

            Log("window: filling the family tab");
            FillPhases();
            FillTextTypes();
            FillScales(scale_cb, settings.Get("scale", DefaultScale.ToString(Inv)), DefaultScale);
            RestoreCase();
            combine_cb.IsChecked = settings.Get("combined", "0") == "1";

            // Base distances are held at the reference scale and shown restated
            // for the chosen scale, so the boxes always read in view millimetres.
            baseDistances = new Dictionary<string, double>
            {
                ["row"] = SettingFloat("row_spacing", RowSpacingMm),
                ["text"] = SettingFloat("text_offset", TextOffsetMm),
                ["column"] = SettingFloat("column_spacing", DefaultColumnSpacingMm),
            };
            ShowDistances();

            // --- system colour legend tab
            templates = model.ViewTemplates();
            FillKinds();
            FillTemplates();
            FillSysTextTypes();
            FillScales(sys_scale_cb, settings.Get("sys_scale", SystemDefaultScale.ToString(Inv)), SystemDefaultScale);
            sys_upper_cb.IsChecked = settings.Get("sys_upper", "1") == "1";
            sys_lw_tb.Text = ClampWeight(settings.Get("sys_line_weight", DefaultLineWeight.ToString(Inv))).ToString(Inv);
            string savedName = settings.Get("sys_view_name", "");
            sys_name_tb.Text = savedName.Length > 0 ? savedName : SelectedKind().ViewName;
            ApplyKind();
            // Swatch height is per kind - a pipe run is a thin band where a cable
            // tray is a block - so it is held keyed by kind.
            sysHeights = ParseKvList(settings.Get("sys_swatch_h", ""),
                                     SystemKinds.ToDictionary(k => k.Key, k => k.SwatchH));
            kindKey = SelectedKind().Key;
            sysBase = new Dictionary<string, double>
            {
                ["swatch_w"] = SettingFloat("sys_swatch_w", SwatchWMm),
                ["row_pitch"] = SettingFloat("sys_row_pitch", SysRowPitchMm),
                ["text_gap"] = SettingFloat("sys_text_gap", SysTextGapMm),
            };
            ShowSysDistances();
            LabelTheme();

            Log("window: reading the model");
            loading = false;
            ReloadCategories();
            ReloadFilters();
            Log("window: ready");
        }

        // -- population ----------------------------------------------------------
        private void FillPhases()
        {
            phase_cb.Items.Add("All phases");
            string wanted = settings.Get("phase", DefaultPhase);
            int chosen = 0;
            for (int index = 0; index < phases.Count; index++)
            {
                phase_cb.Items.Add(phases[index].Name);
                if (phases[index].Name == wanted) chosen = index + 1;
            }
            // Saved phase gone from this model: fall back to the last phase.
            if (chosen == 0 && wanted != "All phases" && phases.Count > 0) chosen = phases.Count;
            phase_cb.SelectedIndex = chosen;
        }

        private void FillTextTypes()
        {
            string wanted = settings.Get("text_type", "");
            long defaultId = LgcModel.Eid(model.DefaultTextTypeId());
            int chosen = 0;
            for (int index = 0; index < textTypes.Count; index++)
            {
                text_cb.Items.Add(textTypes[index].Name);
                if (textTypes[index].Name == wanted) chosen = index;
                else if (wanted.Length == 0 && LgcModel.Eid(textTypes[index].Id) == defaultId) chosen = index;
            }
            if (text_cb.Items.Count > 0) text_cb.SelectedIndex = chosen;
        }

        private void FillParams()
        {
            param_cb.Items.Clear();
            var names = new List<string> { NameTypeName, NameFamilyType };
            var found = model.StringParameterNames(infos);
            if (!found.Contains(DefaultNameParam)) found.Insert(0, DefaultNameParam);
            names.AddRange(found);

            string wanted = settings.Get("name_param", DefaultNameParam);
            int chosen = 0;
            for (int index = 0; index < names.Count; index++)
            {
                param_cb.Items.Add(names[index]);
                if (names[index] == wanted) chosen = index;
            }
            param_cb.SelectedIndex = chosen;
        }

        private double SettingFloat(string key, double fallback)
        {
            if (TryNumber(settings.Get(key, ""), out double value) && value > 0) return value;
            return fallback;
        }

        private static void FillScales(ComboBox box, string wanted, int fallback)
        {
            int chosen = Array.IndexOf(ScaleChoices, fallback);
            for (int index = 0; index < ScaleChoices.Length; index++)
            {
                box.Items.Add("1:" + ScaleChoices[index].ToString(Inv));
                if (ScaleChoices[index].ToString(Inv) == wanted) chosen = index;
            }
            box.SelectedIndex = chosen;
        }

        private static int SelectedScale(ComboBox box, int fallback)
        {
            int index = box.SelectedIndex;
            return index < 0 || index >= ScaleChoices.Length ? fallback : ScaleChoices[index];
        }

        private int FamilyScale => SelectedScale(scale_cb, DefaultScale);
        private int SysScale => SelectedScale(sys_scale_cb, SystemDefaultScale);

        /// <summary>Restate the stored base distances for the chosen scale.</summary>
        private void ShowDistances()
        {
            int scale = FamilyScale;
            row_tb.Text = FormatMm(ScaledMm(baseDistances["row"], scale));
            text_tb.Text = FormatMm(ScaledMm(baseDistances["text"], scale));
            spacing_tb.Text = FormatMm(ScaledMm(baseDistances["column"], scale));
        }

        /// <summary>Read the boxes back, converting to base distances. Null if any is bad.</summary>
        private Dictionary<string, double> CaptureDistances()
        {
            int scale = FamilyScale;
            var captured = new Dictionary<string, double>();
            foreach (var (key, box) in new[] { ("row", row_tb), ("text", text_tb), ("column", spacing_tb) })
            {
                if (!TryNumber(box.Text, out double value) || value <= 0) return null;
                captured[key] = UnscaledMm(value, scale);
            }
            return captured;
        }

        /// <summary>Keep the borderless window inside the working area.</summary>
        private void FitToScreen()
        {
            Rect area;
            try
            {
                area = SystemParameters.WorkArea;
            }
            catch (Exception err)
            {
                Swallowed(err);
                return;
            }

            const double margin = 40.0;
            double maxWidth = area.Width - margin;
            double maxHeight = area.Height - margin;

            if (MinWidth > maxWidth) MinWidth = Math.Max(420.0, maxWidth);
            if (MinHeight > maxHeight) MinHeight = Math.Max(380.0, maxHeight);
            if (Width > maxWidth) Width = Math.Max(MinWidth, maxWidth);
            if (Height > maxHeight) Height = Math.Max(MinHeight, maxHeight);

            Left = area.Left + (area.Width - Width) / 2.0;
            Top = area.Top + (area.Height - Height) / 2.0;
        }

        private void WireEvents()
        {
            header_bar.MouseLeftButtonDown += DragWindow;
            shrink_btn.Click += (s, e) => drawer.Toggle();
            close_btn.Click += (s, e) => Cancel("the X");
            cancel_btn.Click += (s, e) => Cancel("Cancel");
            // after the drawer: a parked bar has already taken Escape
            PreviewKeyDown += OnKey;
            create_btn.Click += Create;
            theme_btn.Click += ToggleTheme;
            tabs.SelectionChanged += TabChanged;

            filter_tb.TextChanged += (s, e) => FilterChanged();
            sel_all_btn.Click += (s, e) => SelectAll();
            clear_btn.Click += (s, e) => { foreach (var r in rows) r.Check.IsChecked = false; };
            phase_cb.SelectionChanged += (s, e) => { if (!loading) ReloadCategories(); };
            scale_cb.DropDownOpened += (s, e) => { if (!loading) capturedBeforeScale = CaptureDistances(); };
            scale_cb.SelectionChanged += ScaleChanged;
            combine_cb.Click += (s, e) => UpdateStatus();

            kind_cb.SelectionChanged += KindChanged;
            template_cb.SelectionChanged += (s, e) => { if (!loading) ReloadFilters(); };
            sys_scale_cb.DropDownOpened += (s, e) => { if (!loading) sysCaptured = CaptureSysDistances(); };
            sys_scale_cb.SelectionChanged += SysScaleChanged;
            sys_upper_cb.Click += (s, e) => { if (!loading) ReloadFilters(); };
            sys_sel_btn.Click += (s, e) => { foreach (var r in sysRows) r.Check.IsChecked = true; };
            sys_clear_btn.Click += (s, e) => { foreach (var r in sysRows) r.Check.IsChecked = false; };

            grip_tl.DragDelta += (s, e) => Resize(e.HorizontalChange, e.VerticalChange, 0, 0);
            grip_t.DragDelta += (s, e) => Resize(0, e.VerticalChange, 0, 0);
            grip_tr.DragDelta += (s, e) => Resize(0, e.VerticalChange, e.HorizontalChange, 0);
            grip_l.DragDelta += (s, e) => Resize(e.HorizontalChange, 0, 0, 0);
            grip_r.DragDelta += (s, e) => Resize(0, 0, e.HorizontalChange, 0);
            grip_bl.DragDelta += (s, e) => Resize(e.HorizontalChange, 0, 0, e.VerticalChange);
            grip_b.DragDelta += (s, e) => Resize(0, 0, 0, e.VerticalChange);
            grip_br.DragDelta += (s, e) => Resize(0, 0, e.HorizontalChange, e.VerticalChange);
        }

        // -- resizing: a borderless window moves its own edges -----------------------
        private void Resize(double left, double top, double right, double bottom)
        {
            double width = double.IsNaN(Width) ? ActualWidth : Width;
            double height = double.IsNaN(Height) ? ActualHeight : Height;

            if (left != 0)
            {
                double newWidth = width - left;
                if (newWidth >= MinWidth)
                {
                    Left += left;
                    Width = newWidth;
                }
            }
            if (right != 0) Width = Math.Max(MinWidth, width + right);
            if (top != 0)
            {
                double newHeight = height - top;
                if (newHeight >= MinHeight)
                {
                    Top += top;
                    Height = newHeight;
                }
            }
            if (bottom != 0) Height = Math.Max(MinHeight, height + bottom);
        }

        /// <summary>Auto -> Dark -> Light -> Auto. Auto follows Revit's canvas theme.</summary>
        private void ToggleTheme(object sender, RoutedEventArgs args)
        {
            themeMode = NextThemeMode(themeMode);
            ThemeName = LgcTheme.ResolveTheme(themeMode);
            Log("theme: " + themeMode + " -> " + ThemeName);
            palette = LgcTheme.ApplyPalette(this, ThemeName);
            LabelTheme();
            // Rows are built in code, so their brushes do not follow a palette swap.
            if (!loading)
            {
                ReloadCategories();
                ReloadFilters();
            }
            var saved = LoadSettings();
            saved["theme_mode"] = themeMode;
            SaveSettings(saved);
        }

        private void LabelTheme()
        {
            if (themeMode != ThemeAuto)
            {
                theme_btn.Content = Capitalize(themeMode);
                theme_btn.ToolTip = "Pinned to " + themeMode + ". Click again to follow Revit.";
                return;
            }
            theme_btn.Content = "Auto";
            string following = LgcTheme.RevitTheme();
            theme_btn.ToolTip = following != null
                ? "Following Revit, currently " + following + ". Click to pin dark or light."
                : "This Revit release does not report a canvas theme, so the tool is using dark. " +
                  "Click to pin dark or light.";
        }

        private string Colour(string key) => palette.TryGetValue(key, out string value) ? value : "#9A9A9E";

        // -- system colour legend ------------------------------------------------
        private void FillKinds()
        {
            string wanted = settings.Get("sys_kind", "containment");
            int chosen = 0;
            for (int index = 0; index < SystemKinds.Length; index++)
            {
                kind_cb.Items.Add(SystemKinds[index].Label);
                if (SystemKinds[index].Key == wanted) chosen = index;
            }
            kind_cb.SelectedIndex = chosen;
        }

        private LegendKind SelectedKind()
        {
            int index = kind_cb.SelectedIndex;
            return index < 0 || index >= SystemKinds.Length ? SystemKinds[0] : SystemKinds[index];
        }

        /// <summary>List every view template, and pick the one that has the filters - never silently.</summary>
        private void FillTemplates()
        {
            template_cb.Items.Clear();
            LegendKind kind = SelectedKind();
            templateCounts = new List<int>();
            bool usesFilters = kind.Source == "filters" && kind.Ready;
            foreach (var (name, view) in templates)
            {
                int count = usesFilters ? model.MatchingFilterCount(view, kind) : 0;
                templateCounts.Add(count);
                template_cb.Items.Add(count == 0 ? name : string.Format(Inv, "{0}   ({1} matching)", name, count));
            }

            var names = templates.Select(t => t.Name).ToList();
            var (chosen, why) = ChooseTemplate(names, templateCounts, settings.Get("sys_template", ""),
                                               kind.Template, usesFilters);
            if (usesFilters)
            {
                Log(string.Format(Inv,
                    "template choice for {0}: \"{1}\" - {2}; default \"{3}\" {4}; {5} of {6} templates have matching filters",
                    kind.Label, chosen >= 0 ? names[chosen] : "none", why, kind.Template,
                    names.Contains(kind.Template) ? "present" : "not in this model",
                    templateCounts.Count(c => c > 0), names.Count));
            }
            template_cb.SelectedIndex = chosen;
        }

        private View SelectedTemplate()
        {
            int index = template_cb.SelectedIndex;
            return index < 0 || index >= templates.Count ? null : templates[index].View;
        }

        private void FillSysTextTypes()
        {
            string body = settings.Get("sys_text_type", "");
            string head = settings.Get("sys_head_type", "");
            long defaultId = LgcModel.Eid(model.DefaultTextTypeId());
            int bodyIndex = 0, headIndex = 0;
            for (int index = 0; index < textTypes.Count; index++)
            {
                var (name, id) = textTypes[index];
                sys_text_cb.Items.Add(name);
                sys_head_cb.Items.Add(name);
                if (name == body) bodyIndex = index;
                else if (body.Length == 0 && LgcModel.Eid(id) == defaultId) bodyIndex = index;
                if (name == head) headIndex = index;
                else if (head.Length == 0 && LgcModel.Eid(id) == defaultId) headIndex = index;
            }
            if (textTypes.Count > 0)
            {
                sys_text_cb.SelectedIndex = bodyIndex;
                sys_head_cb.SelectedIndex = headIndex;
            }
        }

        private void ShowSysDistances()
        {
            int scale = SysScale;
            sw_tb.Text = FormatMm(ScaledMm(sysBase["swatch_w"], scale, SystemReferenceScale));
            pitch_tb.Text = FormatMm(ScaledMm(sysBase["row_pitch"], scale, SystemReferenceScale));
            gap_tb.Text = FormatMm(ScaledMm(sysBase["text_gap"], scale, SystemReferenceScale));
            sh_tb.Text = FormatMm(ScaledMm(CurrentHeight(), scale, SystemReferenceScale));
        }

        /// <summary>The weight box, or null if it is not a usable number.</summary>
        private int? LineWeight()
        {
            if (!TryNumber(sys_lw_tb.Text, out double number)) return null;
            int weight = (int)Math.Round(number, MidpointRounding.AwayFromZero);
            if (weight < MinLineWeight || weight > MaxLineWeight) return null;
            return weight;
        }

        private double CurrentHeight()
        {
            LegendKind kind = SelectedKind();
            return sysHeights.TryGetValue(kind.Key, out double h) ? h : kind.SwatchH;
        }

        private Dictionary<string, double> CaptureSysDistances()
        {
            int scale = SysScale;
            var captured = new Dictionary<string, double>();
            foreach (var (key, box) in new[] { ("swatch_w", sw_tb), ("swatch_h", sh_tb),
                                               ("row_pitch", pitch_tb), ("text_gap", gap_tb) })
            {
                if (!TryNumber(box.Text, out double value) || value <= 0) return null;
                captured[key] = UnscaledMm(value, scale, SystemReferenceScale);
            }
            return captured;
        }

        /// <summary>Bank captured boxes: the height against the kind, the rest shared.</summary>
        private void BankSys(Dictionary<string, double> captured)
        {
            sysHeights[kindKey] = captured["swatch_h"];
            sysBase = captured.Where(p => p.Key != "swatch_h").ToDictionary(p => p.Key, p => p.Value);
        }

        /// <summary>Re-read the chosen template and rebuild the preview list.</summary>
        private void ReloadFilters()
        {
            LegendKind kind = SelectedKind();
            View template = SelectedTemplate();
            Log("system tab: " + kind.Label + ", template " + (template != null ? LgcModel.ElementName(template) : "none"));
            sysRows = new List<(CheckBox, LegendEntry, Border)>();
            filter_panel.Children.Clear();

            if (!kind.Ready)
            {
                sysEntries = new List<LegendEntry>();
                SysNotes = new List<string>();
                sys_status_tb.Text = "This legend kind is not configured yet. Containment is the one that is.";
                UpdateStatus();
                return;
            }

            List<LegendEntry> entries;
            List<string> notes;
            if (kind.Source == "duct_systems") (entries, notes) = model.ReadDuctSystems(kind);
            else if (kind.Source == "pipe_systems") (entries, notes) = model.ReadPipeSystems(kind);
            else (entries, notes) = model.ReadTemplateFilters(template, kind);
            sysEntries = entries;
            SysNotes = notes;

            for (int index = 0; index < sysEntries.Count; index++)
            {
                LegendEntry entry = sysEntries[index];
                var row = new Border { Style = (Style)FindResource(index % 2 == 1 ? "RowEven" : "RowOdd") };

                var grid = new Grid();
                foreach (GridLength width in new[] { new GridLength(26), new GridLength(54),
                                                     new GridLength(1, GridUnitType.Star) })
                    grid.ColumnDefinitions.Add(new ColumnDefinition { Width = width });

                var check = new CheckBox { IsChecked = true, VerticalAlignment = VerticalAlignment.Center };
                check.Checked += (s, e) => UpdateStatus();
                check.Unchecked += (s, e) => UpdateStatus();

                var swatch = new Border
                {
                    Width = 44,
                    Height = 15,
                    Background = LgcTheme.Brush(entry.HexColour),
                    BorderBrush = LgcTheme.Brush(Colour("Ink")),
                    BorderThickness = (Thickness)FindResource("HairThickness"),
                    VerticalAlignment = VerticalAlignment.Center,
                    HorizontalAlignment = HorizontalAlignment.Left,
                };
                Grid.SetColumn(swatch, 1);

                string text = sys_upper_cb.IsChecked == true ? entry.Label.ToUpperInvariant() : entry.Label;
                if (!string.IsNullOrEmpty(entry.Group)) text = text + "   (" + entry.Group + ")";
                var label = new TextBlock
                {
                    Text = text,
                    Foreground = LgcTheme.Brush(Colour("Ink")),
                    VerticalAlignment = VerticalAlignment.Center,
                    Margin = (Thickness)FindResource("LabelMargin"),
                };
                if (entry.Colour == null) label.ToolTip = "No colour override on this filter";
                Grid.SetColumn(label, 2);

                grid.Children.Add(check);
                grid.Children.Add(swatch);
                grid.Children.Add(label);
                row.Child = grid;

                filter_panel.Children.Add(row);
                sysRows.Add((check, entry, row));
            }

            bool systems = kind.Source == "duct_systems" || kind.Source == "pipe_systems";
            string noun = Noun(kind, "filter");
            if (sysEntries.Count == 0)
            {
                sys_status_tb.Text = systems
                    ? "No " + noun + " types are in use in this model."
                    : string.Format(Inv, "No filters on this template are on {0} and named \"{1}\".",
                                    string.Join(" / ", kind.Categories.Select(c => c.Replace("OST_", ""))),
                                    kind.NameToken);
            }
            else
            {
                int grey = sysEntries.Count(e => e.Colour == null);
                string message = string.Format(Inv, "{0} {1}(s) found", sysEntries.Count, noun);
                if (grey > 0) message += string.Format(Inv, "  -  {0} with no colour override", grey);
                sys_status_tb.Text = message;
            }
            UpdateStatus();
        }

        private static string Noun(LegendKind kind, string fallback)
        {
            if (kind.Source == "duct_systems") return "duct system";
            if (kind.Source == "pipe_systems") return "pipe system";
            return fallback;
        }

        private void KindChanged(object sender, SelectionChangedEventArgs args)
        {
            if (loading) return;
            Log("legend type: " + SelectedKind().Label);
            // Bank whatever is on screen against the kind it was typed for.
            var captured = CaptureSysDistances();
            if (captured != null) BankSys(captured);
            kindKey = SelectedKind().Key;

            FillTemplates();
            ApplyKind();
            sys_name_tb.Text = SelectedKind().ViewName;
            ShowSysDistances();
            ReloadFilters();
        }

        /// <summary>Duct and pipe legends read system types directly - the template picker is greyed.</summary>
        private void ApplyKind()
        {
            bool usesTemplate = SelectedKind().Source == "filters";
            template_cb.IsEnabled = usesTemplate;
            template_lbl.Opacity = usesTemplate ? 1.0 : 0.45;
        }

        private void SysScaleChanged(object sender, SelectionChangedEventArgs args)
        {
            if (loading) return;
            var captured = sysCaptured ?? CaptureSysDistances();
            if (captured != null) BankSys(captured);
            sysCaptured = null;
            ShowSysDistances();
        }

        private void TabChanged(object sender, SelectionChangedEventArgs args)
        {
            // SelectionChanged bubbles up from every ComboBox inside the tabs.
            if (loading || !ReferenceEquals(args.OriginalSource, tabs)) return;
            Log("tab: " + (tabs.SelectedIndex == 1 ? "System Colour Legend" : "Family Legend"));
            UpdateStatus();
        }

        private void RestoreCase()
        {
            string mode = settings.Get("text_case", DefaultCase);
            if (mode == CaseUpper) case_upper.IsChecked = true;
            else if (mode == CaseCamel) case_camel.IsChecked = true;
            else case_asis.IsChecked = true;
        }

        private string SelectedCase()
        {
            if (case_upper.IsChecked == true) return CaseUpper;
            if (case_camel.IsChecked == true) return CaseCamel;
            return CaseAsIs;
        }

        private ElementId SelectedPhaseId()
        {
            int index = phase_cb.SelectedIndex;
            return index <= 0 || index > phases.Count ? null : phases[index - 1].Id;
        }

        private string SelectedPhaseName()
        {
            int index = phase_cb.SelectedIndex;
            return index <= 0 || index > phases.Count ? "All phases" : phases[index - 1].Name;
        }

        /// <summary>Re-read the model for the chosen phase, remembering the ticks.</summary>
        private void ReloadCategories()
        {
            var ticked = new HashSet<string>(rows.Where(r => r.Check.IsChecked == true).Select(r => r.Info.Name));

            ElementId phaseId = SelectedPhaseId();
            string key = phaseId != null ? LgcModel.Eid(phaseId).ToString(Inv) : "all";
            if (!cache.ContainsKey(key)) cache[key] = model.CollectUsedTypes(phaseId);
            infos = cache[key];

            rows = new List<(CheckBox, CategoryInfo, Border)>();
            list_panel.Children.Clear();
            for (int index = 0; index < infos.Count; index++)
            {
                CategoryInfo info = infos[index];
                var row = new Border { Style = (Style)FindResource(index % 2 == 1 ? "RowEven" : "RowOdd") };

                var grid = new Grid();
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(70) });

                var check = new CheckBox { Content = info.Name, IsChecked = ticked.Contains(info.Name) };
                check.Checked += (s, e) => UpdateStatus();
                check.Unchecked += (s, e) => UpdateStatus();

                var count = new TextBlock
                {
                    Text = info.Count.ToString(Inv),
                    FontSize = 11,
                    Foreground = LgcTheme.Brush(Colour("Muted")),
                    HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Center,
                };
                var pill = new Border { Style = (Style)FindResource("Pill"), Child = count };
                Grid.SetColumn(pill, 1);

                grid.Children.Add(check);
                grid.Children.Add(pill);
                row.Child = grid;

                list_panel.Children.Add(row);
                rows.Add((check, info, row));
            }

            FillParams();
            FilterChanged();
            UpdateStatus();
        }

        // -- events ----------------------------------------------------------------
        /// <summary>No system title bar, so the header bar moves the window.</summary>
        private void DragWindow(object sender, MouseButtonEventArgs args)
        {
            if (drawer.HeaderDown(args)) return;
            try
            {
                DragMove();
            }
            catch (Exception)
            {
                // DragMove throws if the button is already up
            }
        }

        /// <summary>Escape closes the window - once the drawer has had its look.</summary>
        private void OnKey(object sender, KeyEventArgs args)
        {
            try
            {
                if (!args.Handled && args.Key == Key.Escape)
                {
                    args.Handled = true;
                    Cancel("Escape");
                }
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        /// <summary>Rescale the distance boxes so they stay constant on paper, keeping hand-typed values.</summary>
        private void ScaleChanged(object sender, SelectionChangedEventArgs args)
        {
            if (loading) return;
            var captured = capturedBeforeScale ?? CaptureDistances();
            if (captured != null) baseDistances = captured;
            capturedBeforeScale = null;
            ShowDistances();
            UpdateStatus();
        }

        private void FilterChanged()
        {
            string needle = filter_tb.Text.ToLowerInvariant().Trim();
            foreach (var (_, info, row) in rows)
                row.Visibility = info.Name.ToLowerInvariant().Contains(needle) ? Visibility.Visible : Visibility.Collapsed;
        }

        private void SelectAll()
        {
            foreach (var (check, _, row) in rows)
                if (row.Visibility == Visibility.Visible) check.IsChecked = true;
        }

        private void Create(object sender, RoutedEventArgs args)
        {
            if (drawer.Intercept()) return; // Enter on a parked window reopens it
            Log("Create pressed on the " + (tabs.SelectedIndex == 1 ? "System Colour Legend" : "Family Legend") + " tab");
            if (tabs.SelectedIndex == 1) CreateSystem();
            else CreateFamily();
        }

        private void CreateSystem()
        {
            LegendKind kind = SelectedKind();
            if (!kind.Ready)
            {
                Refuse("This legend kind is not configured yet.");
                return;
            }

            var chosen = sysRows.Where(r => r.Check.IsChecked == true).Select(r => r.Entry).ToList();
            if (chosen.Count == 0)
            {
                Refuse("Tick at least one filter.");
                return;
            }

            var captured = CaptureSysDistances();
            if (captured == null)
            {
                Refuse("Swatch and spacing values must all be positive numbers in mm.");
                return;
            }
            int? weight = LineWeight();
            if (weight == null)
            {
                Refuse("Line weight must be a whole number from 1 to 16.");
                return;
            }

            BankSys(captured);

            int scale = SysScale;
            View template = SelectedTemplate();
            int textIndex = Math.Max(0, sys_text_cb.SelectedIndex);
            int headIndex = Math.Max(0, sys_head_cb.SelectedIndex);
            string name = sys_name_tb.Text.Trim();
            if (name.Length == 0) name = kind.ViewName;

            SystemResult = chosen;
            Mode = "system";
            SystemOpts = new SystemOptions
            {
                Kind = kind,
                Theme = ThemeName,
                ThemeMode = themeMode,
                Debug = DebugTicked,
                Heading = kind.Heading,
                RegionPrefix = kind.RegionPrefix,
                Style = kind.Style,
                Centreline = kind.Centreline,
                LineWeight = weight.Value,
                TemplateName = template != null ? LgcModel.ElementName(template) : "",
                Scale = scale,
                ViewName = name,
                Upper = sys_upper_cb.IsChecked == true,
                TextTypeId = textTypes[textIndex].Id,
                TextTypeName = textTypes[textIndex].Name,
                HeadTypeId = textTypes[headIndex].Id,
                HeadTypeName = textTypes[headIndex].Name,
                SwatchW = ScaledMm(captured["swatch_w"], scale, SystemReferenceScale),
                SwatchH = ScaledMm(captured["swatch_h"], scale, SystemReferenceScale),
                RowPitch = ScaledMm(captured["row_pitch"], scale, SystemReferenceScale),
                TextGap = ScaledMm(captured["text_gap"], scale, SystemReferenceScale),
                HeadingGap = ScaledMm(SysHeadingGapMm, scale, SystemReferenceScale),
            };

            var saved = LoadSettings();
            saved["sys_kind"] = kind.Key;
            saved["sys_template"] = SystemOpts.TemplateName;
            saved["sys_scale"] = scale.ToString(Inv);
            saved["sys_text_type"] = SystemOpts.TextTypeName;
            saved["sys_head_type"] = SystemOpts.HeadTypeName;
            saved["sys_swatch_w"] = FormatMm(captured["swatch_w"]);
            saved["sys_swatch_h"] = FormatKvList(sysHeights);
            saved["sys_line_weight"] = weight.Value.ToString(Inv);
            saved["sys_row_pitch"] = FormatMm(captured["row_pitch"]);
            saved["sys_text_gap"] = FormatMm(captured["text_gap"]);
            saved["sys_view_name"] = name;
            saved["sys_upper"] = SystemOpts.Upper ? "1" : "0";
            saved["theme_mode"] = themeMode;
            saved["debug"] = DebugTicked ? "1" : "0";
            SaveSettings(saved);
            Close();
        }

        private void CreateFamily()
        {
            var chosen = rows.Where(r => r.Check.IsChecked == true).Select(r => r.Info).ToList();
            if (chosen.Count == 0)
            {
                Refuse("Tick at least one category.");
                return;
            }
            if (text_cb.Items.Count == 0)
            {
                Refuse("This project has no text note type.");
                return;
            }

            var captured = CaptureDistances();
            if (captured == null)
            {
                Refuse("Row, text and column distances must all be positive numbers in mm.");
                return;
            }
            baseDistances = captured;

            int scale = FamilyScale;
            int textIndex = Math.Max(0, text_cb.SelectedIndex);
            int paramIndex = Math.Max(0, param_cb.SelectedIndex);

            FamilyResult = chosen;
            Mode = "family";
            FamilyOpts = new FamilyOptions
            {
                Theme = ThemeName,
                ThemeMode = themeMode,
                Debug = DebugTicked,
                Phase = SelectedPhaseName(),
                NameParam = (string)param_cb.Items[paramIndex],
                TextTypeId = textTypes[textIndex].Id,
                TextTypeName = textTypes[textIndex].Name,
                TextCase = SelectedCase(),
                Combined = combine_cb.IsChecked == true,
                Scale = scale,
                // handed on as real view millimetres at the chosen scale
                RowSpacing = ScaledMm(captured["row"], scale),
                TextOffset = ScaledMm(captured["text"], scale),
                ColumnSpacing = ScaledMm(captured["column"], scale),
            };

            var saved = LoadSettings();
            saved["phase"] = FamilyOpts.Phase;
            saved["name_param"] = FamilyOpts.NameParam;
            saved["text_type"] = FamilyOpts.TextTypeName;
            saved["text_case"] = FamilyOpts.TextCase;
            saved["combined"] = FamilyOpts.Combined ? "1" : "0";
            saved["scale"] = scale.ToString(Inv);
            saved["row_spacing"] = FormatMm(captured["row"]);
            saved["text_offset"] = FormatMm(captured["text"]);
            saved["column_spacing"] = FormatMm(captured["column"]);
            saved["theme_mode"] = themeMode;
            saved["debug"] = DebugTicked ? "1" : "0";
            SaveSettings(saved);
            Close();
        }

        private void Cancel(string how)
        {
            Log("closed with " + how);
            FamilyResult = new List<CategoryInfo>();
            SystemResult = new List<LegendEntry>();
            Close();
        }

        // -- helpers ---------------------------------------------------------------
        /// <summary>The footer line - orange when it says why nothing will happen.</summary>
        private void Say(string text, bool warn = false)
        {
            status_tb.Text = text;
            try
            {
                status_tb.SetResourceReference(TextBlock.ForegroundProperty, warn ? "Orange" : "Muted");
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        private void Refuse(string text)
        {
            Log("create refused: " + text);
            Say(text, true);
        }

        /// <summary>Why Create cannot run on this tab right now, or null.</summary>
        private string Blocker(bool systemTab)
        {
            if (systemTab)
            {
                LegendKind kind = SelectedKind();
                if (!kind.Ready) return "This legend kind is not configured yet.";
                if (sysEntries.Count == 0)
                {
                    if (kind.Source == "filters")
                    {
                        View template = SelectedTemplate();
                        if (templateCounts.Any(c => c > 0))
                            return "No matching filters on \"" +
                                   (template != null ? LgcModel.ElementName(template) : "this template") +
                                   "\" - pick a template marked \"matching\".";
                        return "No view template in this model has " +
                               string.Join("/", kind.Categories.Take(1).Select(c => c.Replace("OST_", ""))) +
                               " filters named \"" + kind.NameToken + "\".";
                    }
                    return "No " + Noun(kind, "system") + " types are in use in this model.";
                }
                if (!sysRows.Any(r => r.Check.IsChecked == true)) return "Tick at least one row.";
                return null;
            }

            if (!familyReady)
                return "Family Legend needs a legend holding one legend component - none in this model. " +
                       "Drag any family type into a legend view, then reopen.";
            if (rows.Count == 0) return "Nothing placed on this phase.";
            if (!rows.Any(r => r.Check.IsChecked == true)) return "Tick at least one category.";
            return null;
        }

        private void UpdateStatus()
        {
            bool systemTab = tabs.SelectedIndex == 1;
            string blocker = Blocker(systemTab);
            create_btn.IsEnabled = blocker == null;
            if (blocker != null)
            {
                Say(blocker, true);
                return;
            }

            if (systemTab)
            {
                Say(string.Format(Inv, "{0} of {1} rows  -  1:{2}",
                                  sysRows.Count(r => r.Check.IsChecked == true), sysRows.Count, SysScale));
                return;
            }

            var chosen = rows.Where(r => r.Check.IsChecked == true).Select(r => r.Info).ToList();
            int types = chosen.Sum(i => i.Count);
            if (chosen.Count == 0)
            {
                Say(string.Format(Inv, "{0} categories on this phase", rows.Count));
                return;
            }
            string shape = combine_cb.IsChecked == true && chosen.Count > 1
                ? string.Format(Inv, "1 combined legend, {0} columns", chosen.Count)
                : string.Format(Inv, "{0} legend{1}", chosen.Count, chosen.Count == 1 ? "" : "s");
            Say(string.Format(Inv, "{0}  -  {1} types  -  1:{2}", shape, types, FamilyScale));
        }
    }
}
