using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.BwicPenetration;
using ComboBox = System.Windows.Controls.ComboBox;
using Visibility = System.Windows.Visibility;
using Grid = System.Windows.Controls.Grid;
using TextBox = System.Windows.Controls.TextBox;

namespace RevoBIM.UI.BwicPenetration
{
    /// <summary>Lets the modeless window drive the Revit API: place, resize and Global Placement all run inside this external event.</summary>
    internal sealed class PlacementHandler : IExternalEventHandler
    {
        private readonly BwiMainWindow _window;
        public double ClearanceMm = BwicCore.DefaultClearanceMm;
        public BwicOptions Options = new BwicOptions();
        public Dictionary<string, string> Settings = new Dictionary<string, string>();
        public GlobalSettings GlobalSettings = new GlobalSettings();
        public string Mode = "place";

        public PlacementHandler(BwiMainWindow window) { _window = window; }

        public void Execute(UIApplication uiapp)
        {
            BwicCore.CurrentApp = uiapp;
            if (Mode == "global")
            {
                RunGlobal(uiapp);
                return;
            }
            try
            {
                if (Mode == "slab" || Mode == "slab_resize")
                    BwicCore.RunSlabLoop(uiapp, Settings, Options, _window.Report, Mode == "slab_resize" ? "resize" : "place");
                else
                    BwicCore.RunPlacementLoop(uiapp, ClearanceMm, Options, _window.Report, Mode);
            }
            catch (Exception err)
            {
                BwicCore.DebugLog("RUN EXCEPTION\n" + err);
                _window.Report("Error: " + err.Message);
            }
            finally
            {
                _window.Finish();
            }
        }

        /// <summary>Sweep the active view, then show what it did.</summary>
        private void RunGlobal(UIApplication uiapp)
        {
            GlobalSummary summary = null;
            try
            {
                // the wall family's own profile decides its parameter names
                BwicGlobal.Configure(BwicCore.FamilySettings(Settings, "wall"));
                try
                {
                    BwicCore.StartDebug(uiapp.ActiveUIDocument.Document, "GLOBAL PLACEMENT RUN", Settings, new Dictionary<string, string>
                    {
                        { "link_id", GlobalSettings.LinkId == null ? "" : BwicCore.EidValue(GlobalSettings.LinkId).ToString() },
                        { "gap_pipes_mm", GlobalSettings.GapPipesMm.ToString(CultureInfo.InvariantCulture) },
                        { "gap_trays_mm", GlobalSettings.GapTraysMm.ToString(CultureInfo.InvariantCulture) },
                        { "gap_conduit_mm", GlobalSettings.GapConduitMm.ToString(CultureInfo.InvariantCulture) },
                        { "log_comments", GlobalSettings.LogComments.ToString() }, { "use_workset", GlobalSettings.UseWorkset.ToString() },
                        { "level_param", GlobalSettings.LevelParam ?? "" },
                    });
                }
                catch (Exception) { }
                summary = BwicGlobal.RunGlobalPlacement(uiapp, GlobalSettings, _window.Report);
                if (summary != null)
                {
                    foreach (string line in summary.Log) BwicCore.DebugLog(line);
                    BwicCore.DebugLog("placed " + summary.Placed + ", to review " + summary.Review + ", failed " + summary.Failed + ", skipped "
                                      + summary.Skipped + ", repeats " + summary.Duplicates);
                }
            }
            catch (Exception err)
            {
                BwicCore.DebugLog("GLOBAL RUN EXCEPTION\n" + err);
                _window.Report("Error: " + err.Message);
            }
            finally
            {
                _window.Finish();
            }
            if (summary != null) _window.ShowResults(summary);
        }

        public string GetName() { return "RevoBIM BWIC Penetration"; }
    }

    /// <summary>
    /// BWIC Penetration main window (port of script.py BWICWindow): Wall, Slab and Global Placement tabs, family cards with preview,
    /// the step prompt, resize grips and the shrink-to-taskbar drawer. Modeless: every run goes through <see cref="PlacementHandler"/>.
    /// </summary>
    internal sealed class BwiMainWindow : BwiWindowBase, IPromptHost
    {
        private static readonly string[] TabNames = { "wall", "slab", "global" };
        private static readonly string[] SlabMethods = { "rectangular", "circular", "auto" };
        private static readonly string[] WallShapes = { "rectangular", "circular" };
        private static readonly string[][] DatumLabels =
        {
            new[] { "soffit", "The floor soffit, downwards" },
            new[] { "top", "The floor top, upwards" },
            new[] { "level", "The floor's level, plus its depth" },
        };

        private readonly UIApplication _uiapp;
        public Dictionary<string, string> Settings;
        public Dictionary<string, object> Profiles;
        private readonly Dictionary<string, System.Windows.Media.ImageSource> _previews = new Dictionary<string, System.Windows.Media.ImageSource>();
        private readonly Dictionary<string, Tuple<List<string>, List<string>, bool>> _paramCache = new Dictionary<string, Tuple<List<string>, List<string>, bool>>();
        private readonly Dictionary<string, FamilyCard> _cards = new Dictionary<string, FamilyCard>();
        private readonly List<Tuple<string, Expander>> _groups = new List<Tuple<string, Expander>>();
        private readonly PlacementHandler _handler;
        private readonly ExternalEvent _extEvent;
        private readonly SelectionHandler _selectHandler = new SelectionHandler();
        private readonly ExternalEvent _selectEvent;
        private StepPrompt _prompt;
        private PromptParts _dockParts;
        private bool _finishReady, _running;
        private List<BwicGlobal.LinkEntry> _links = new List<BwicGlobal.LinkEntry>();
        private ResultsWindow _results;
        private bool _ready;

        Window IPromptHost.Win { get { return Win; } }
        Drawer IPromptHost.Drawer { get { return Drawer; } }

        public BwiMainWindow(UIApplication uiapp)
        {
            _uiapp = uiapp;
            BwicCore.CurrentApp = uiapp;
            Win = BwiUi.Load("ui.xaml", Handlers());
            BwiUi.OwnToRevit(Win);
            try { Find<TextBlock>("version_tb").Text = "v" + BwicCore.ToolVersion; } catch (Exception) { }
            var logo = Find<Image>("logo_img");
            logo.Source = BwiUi.LoadLogoImage();
            EggHook.Attach(Win, () => "dark", logo);

            Settings = BwicCore.ReadSettings();
            BwicCore.ApplySettings(Settings);
            LoadLevelParams();
            LoadDatum();

            Profiles = BwicCore.LoadProfiles();
            _cards["wall"] = new FamilyCard(this, "wall", Find<ComboBox>("wr_family_cb"), Find<ComboBox>("wr_type_cb"), Find<Image>("wr_preview_img"),
                                            Find<TextBlock>("wr_noprev_tb"), Find<TextBlock>("wr_famsum_tb"));
            _cards["wall_circ"] = new FamilyCard(this, "wall_circ", Find<ComboBox>("wc_family_cb"), Find<ComboBox>("wc_type_cb"), Find<Image>("wc_preview_img"),
                                                 Find<TextBlock>("wc_noprev_tb"), Find<TextBlock>("wc_famsum_tb"));
            _cards["slab_rect"] = new FamilyCard(this, "slab_rect", Find<ComboBox>("sr_family_cb"), Find<ComboBox>("sr_type_cb"), Find<Image>("sr_preview_img"),
                                                 Find<TextBlock>("sr_noprev_tb"), Find<TextBlock>("sr_famsum_tb"));
            _cards["slab_circ"] = new FamilyCard(this, "slab_circ", Find<ComboBox>("sc_family_cb"), Find<ComboBox>("sc_type_cb"), Find<Image>("sc_preview_img"),
                                                 Find<TextBlock>("sc_noprev_tb"), Find<TextBlock>("sc_famsum_tb"));
            ReloadFamilies();

            foreach (string key in new[] { "wr_family", "wc_family", "wc_size", "wall_options", "wall_help", "sr_family", "sc_family", "sc_size",
                                           "sa_families", "sa_rules", "slab_setout", "slab_options", "g_link", "g_sizes", "g_options", "g_help" })
                _groups.Add(Tuple.Create(key, Find<Expander>("grp_" + key)));
            foreach (var g in _groups)
            {
                string saved = BwicFamilies.Get(Settings, "group_" + g.Item1);
                if (saved == "open" || saved == "closed") g.Item2.IsExpanded = saved == "open";
            }

            LoadShapes();
            RestoreSettings();
            ShowSlabFamily();

            Find<CheckBox>("debug_cb").IsChecked = BwicFamilies.Get(Settings, "debug") == "yes";
            DebugChanged(null);

            var tabs = Find<TabControl>("tabs");
            string active = BwicFamilies.Get(Settings, "active_tab");
            tabs.SelectedIndex = Array.IndexOf(TabNames, active) >= 0 ? Array.IndexOf(TabNames, active) : 0;
            ShowActions();
            tabs.SelectionChanged += TabChanged;

            Win.SourceInitialized += (s, e) => CapHeight();

            _handler = new PlacementHandler(this);
            _extEvent = ExternalEvent.Create(_handler);
            _selectEvent = ExternalEvent.Create(_selectHandler);

            Drawer = new Drawer(Win, Find<StackPanel>("header_pnl"), Find<Button>("shrink_btn"), Find<Grid>("grips_grid"));
            // parking the window mid-step moves the step card over Revit, and opening it brings the card back under the buttons
            Drawer.OnChange = heading => { if (_prompt != null) _prompt.Refresh(); };
            Win.PreviewKeyDown += (s, e) => Drawer.HandleKey(e);
            _dockParts = new PromptParts
            {
                Card = Find<Border>("pr_bd"), AccentBd = Find<Border>("pr_accent_bd"), EyebrowTb = Find<TextBlock>("pr_eyebrow_tb"),
                DotsTb = Find<TextBlock>("pr_dots_tb"), IconTb = Find<TextBlock>("pr_icon_tb"), TitleTb = Find<TextBlock>("pr_title_tb"),
                DetailTb = Find<TextBlock>("pr_detail_tb"), HintBd = Find<Border>("pr_hint_bd"), HintTb = Find<TextBlock>("pr_hint_tb"),
            };
            Win.Closed += WindowClosed;
            LoadLinks();
            RestoreGlobal();
            _ready = true;
            WriteOpenHeader();
        }

        private Document Doc { get { return _uiapp.ActiveUIDocument == null ? null : _uiapp.ActiveUIDocument.Document; } }

        /// <summary>The first lines of the debug file say which build is running (tool version, add-in version, build date, DLL path).</summary>
        private void WriteOpenHeader()
        {
            try
            {
                if (BwicCore.Debug) BwicCore.DebugLog("window opened: bwic_penetration " + BwicCore.ToolVersion + "  " + BwicCore.BuildInfo());
            }
            catch (Exception) { }
        }

        // ---------------------------------------------------------------- handlers

        private Dictionary<string, Action<object, RoutedEventArgs>> Handlers()
        {
            var h = new Dictionary<string, Action<object, RoutedEventArgs>>();
            Action<string, Action<object, RoutedEventArgs>> add = (name, body) => h[name] = G(name, body);
            add("close_click", (s, e) => Win.Close());
            add("debug_changed", (s, e) => DebugChanged(s));
            add("debug_clear_click", (s, e) => { BwicCore.ClearDebug(); Report("Debug log cleared."); });
            add("debug_open_click", (s, e) => DebugOpen());
            add("finish_click", (s, e) => FinishClick());
            add("global_refresh_click", (s, e) => { LoadLinks(); Report("Links re-read from the model."); });
            add("global_run_click", (s, e) => StartRun("global"));
            add("place_click", (s, e) => StartRun("place"));
            add("resize_click", (s, e) => StartRun("resize"));
            add("slab_place_click", (s, e) => StartRun("slab"));
            add("slab_resize_click", (s, e) => StartRun("slab_resize"));
            add("wr_famset_click", (s, e) => OpenFamilySettings("wall"));
            add("wc_famset_click", (s, e) => OpenFamilySettings("wall_circ"));
            add("sr_famset_click", (s, e) => OpenFamilySettings("slab_rect"));
            add("sc_famset_click", (s, e) => OpenFamilySettings("slab_circ"));
            add("settings_click", (s, e) => SettingsClick());
            add("shrink_click", (s, e) => Drawer.Toggle());
            add("slab_size_changed", (s, e) => SlabSizeChanged());
            add("slab_shape_changed", (s, e) => SlabShapeChanged(e));
            add("wall_shape_changed", (s, e) => WallShapeChanged(e));
            add("wall_round_changed", (s, e) => WallRoundChanged());
            add("topmost_changed", (s, e) => Win.Topmost = Find<CheckBox>("topmost_cb").IsChecked == true);
            add("drag_window", HeaderDown);
            add("grip_n_drag", (s, e) => Heighten(((DragDeltaEventArgs)e).VerticalChange, true));
            add("grip_s_drag", (s, e) => Heighten(((DragDeltaEventArgs)e).VerticalChange, false));
            add("grip_w_drag", (s, e) => Widen(((DragDeltaEventArgs)e).HorizontalChange, true));
            add("grip_e_drag", (s, e) => Widen(((DragDeltaEventArgs)e).HorizontalChange, false));
            add("grip_nw_drag", (s, e) => { var d = (DragDeltaEventArgs)e; Widen(d.HorizontalChange, true); Heighten(d.VerticalChange, true); });
            add("grip_ne_drag", (s, e) => { var d = (DragDeltaEventArgs)e; Widen(d.HorizontalChange, false); Heighten(d.VerticalChange, true); });
            add("grip_sw_drag", (s, e) => { var d = (DragDeltaEventArgs)e; Widen(d.HorizontalChange, true); Heighten(d.VerticalChange, false); });
            add("grip_se_drag", (s, e) => { var d = (DragDeltaEventArgs)e; Widen(d.HorizontalChange, false); Heighten(d.VerticalChange, false); });
            return h;
        }

        // ---------------------------------------------------------------- helpers

        private string S(string key, string fallback = "")
        {
            string v;
            return Settings.TryGetValue(key, out v) && v != null ? v : fallback;
        }

        private void CapHeight()
        {
            try
            {
                double scale = BwiUi.DpiScale(Win);
                System.Drawing.Rectangle area = System.Windows.Forms.Screen.PrimaryScreen.WorkingArea;
                Win.MaxHeight = Math.Max(360.0, (area.Height / scale) - 60.0);
            }
            catch (Exception) { }
        }

        private void LoadLevelParams()
        {
            List<string> names;
            try
            {
                Document doc = Doc;
                names = BwicCore.CollectParameterNames(doc, BwicCore.FindFamilySymbol(doc));
            }
            catch (Exception)
            {
                names = new List<string> { BwicCore.LevelParamName };
            }
            var cb = Find<ComboBox>("level_param_cb");
            cb.Items.Clear();
            cb.Items.Add("<do not write a level code>");
            foreach (string name in names) cb.Items.Add(name);
            string preferred = BwicCore.DefaultLevelParam(names);
            cb.SelectedIndex = preferred != null ? names.IndexOf(preferred) + 1 : 0;
        }

        private void LoadDatum()
        {
            var cb = Find<ComboBox>("slab_datum_cb");
            cb.Items.Clear();
            foreach (string[] d in DatumLabels) cb.Items.Add(d[1]);
            string wanted = S("slab_datum", "soffit");
            int index = Array.FindIndex(DatumLabels, d => d[0] == wanted);
            cb.SelectedIndex = index >= 0 ? index : 0;
            cb.SelectionChanged += (s, e) => DatumChanged();
            DatumChanged();
        }

        private string SelectedDatum()
        {
            int index = Find<ComboBox>("slab_datum_cb").SelectedIndex;
            return index >= 0 ? DatumLabels[index][0] : "soffit";
        }

        private void DatumChanged()
        {
            string d = SelectedDatum();
            Find<TextBlock>("slab_base_lbl").Text = d == "top" ? "top +" : d == "level" ? "level + depth +" : "soffit -";
        }

        private void RestoreSettings()
        {
            if (S("wall_circ_round").Length > 0) Find<TextBox>("wc_round_tb").Text = S("wall_circ_round");
            Find<CheckBox>("wc_insul_cb").IsChecked = S("wall_circ_insulation", "yes") != "no";
            WallRoundChanged();
            UpdatePlaceLabel();
            if (S("slab_circular_round").Length > 0) Find<TextBox>("slab_gapround_tb").Text = S("slab_circular_round");
            Find<CheckBox>("slab_insul_cb").IsChecked = S("slab_circular_insulation", "yes") != "no";
            if (S("slab_base_extra").Length > 0) Find<TextBox>("slab_base_tb").Text = S("slab_base_extra");
            if (S("slab_top_extra").Length > 0) Find<TextBox>("slab_top_tb").Text = S("slab_top_extra");
            string param = S("level_param");
            if (param.Length > 0)
            {
                var cb = Find<ComboBox>("level_param_cb");
                for (int i = 0; i < cb.Items.Count; i++)
                    if (cb.Items[i].ToString() == param)
                    {
                        cb.SelectedIndex = i;
                        break;
                    }
            }
            if (S("include_linked") == "yes") Find<CheckBox>("linked_cb").IsChecked = true;
        }

        /// <summary>Say how the Automatic tab splits services.</summary>
        private void ShowSlabFamily()
        {
            Find<TextBlock>("slab_shape_tb").Text = "Pipes and conduit on their own get a round hole each. Trays and ducts within "
                + S("slab_group_gap", "100") + " mm of each other, and pointing the same way, share one rectangular opening, and a pipe within "
                + S("slab_pipe_tray_gap", "150") + " mm of one joins it.";
            SlabSizeChanged();
            string rule = S("slab_rule", "two_level");
            if (rule == "single_level")
            {
                string height = S("slab_height_param");
                if (height.Length == 0) height = "not set";
                Find<TextBlock>("slab_rule_tb").Text = "Single level rule - placed on the nearest level, vertical height \"" + height + "\" set to the floor thickness.";
            }
            else Find<TextBlock>("slab_rule_tb").Text = "Two levels rule - Base Level and Top Level with offsets.";
        }

        private void LoadShapes()
        {
            string wall = S("wall_shape", "rectangular");
            Find<TabControl>("wall_shape_tabs").SelectedIndex = Array.IndexOf(WallShapes, wall) >= 0 ? Array.IndexOf(WallShapes, wall) : 0;
            string method = S("slab_method", "rectangular");
            Find<TabControl>("slab_shape_tabs").SelectedIndex = Array.IndexOf(SlabMethods, method) >= 0 ? Array.IndexOf(SlabMethods, method) : 0;
        }

        private string SelectedMethod()
        {
            int index = Find<TabControl>("slab_shape_tabs").SelectedIndex;
            return index >= 0 && index < SlabMethods.Length ? SlabMethods[index] : "rectangular";
        }

        private string SelectedWallShape()
        {
            int index = Find<TabControl>("wall_shape_tabs").SelectedIndex;
            return index >= 0 && index < WallShapes.Length ? WallShapes[index] : "rectangular";
        }

        private void SlabShapeChanged(RoutedEventArgs args)
        {
            if (!_ready || args == null || args.OriginalSource != Find<TabControl>("slab_shape_tabs")) return;
            Settings["slab_method"] = SelectedMethod();
            BwicCore.WriteSettings(Settings);
            ShowSlabFamily();
        }

        private void WallShapeChanged(RoutedEventArgs args)
        {
            if (!_ready || args == null || args.OriginalSource != Find<TabControl>("wall_shape_tabs")) return;
            Settings["wall_shape"] = SelectedWallShape();
            BwicCore.WriteSettings(Settings);
            UpdatePlaceLabel();
        }

        private void UpdatePlaceLabel()
        {
            Find<Button>("place_btn").Content = SelectedWallShape() == "circular" ? "Place Circular BWIC" : "Place BWIC";
        }

        // ---------------------------------------------------------------- families

        /// <summary>Read the project's generic model families into every card.</summary>
        public void ReloadFamilies()
        {
            List<GenericFamily> families;
            try { families = BwicCore.GenericModelFamilies(Doc, null); }
            catch (Exception) { families = new List<GenericFamily>(); }
            Dictionary<string, string> shapes;
            try { shapes = BwicCore.FamilyShapes(Doc); }
            catch (Exception) { shapes = new Dictionary<string, string>(); }
            foreach (FamilyCard card in _cards.Values) card.Fill(FamiliesForSlot(card.Slot, families, shapes), families);
            ShowAutoFamilies();
        }

        /// <summary>The families a slot's list offers: only those of the slot's shape (a family whose shape is unknown is offered everywhere).</summary>
        private static List<GenericFamily> FamiliesForSlot(string slot, List<GenericFamily> families, Dictionary<string, string> shapes)
        {
            string[] wanted = BwicFamilies.SlotShapes[slot];
            return families.Where(f =>
            {
                string shape;
                if (!shapes.TryGetValue(f.Name, out shape)) shape = wanted[0];
                return wanted.Contains(shape);
            }).ToList();
        }

        public System.Windows.Media.ImageSource Preview(string family, string typeName)
        {
            if (string.IsNullOrEmpty(family)) return null;
            string key = family + "\u0001" + (typeName ?? "");
            if (!_previews.ContainsKey(key))
            {
                try { _previews[key] = BwiUi.BitmapToImage(BwicCore.FamilyPreview(Doc, family, string.IsNullOrEmpty(typeName) ? null : typeName)); }
                catch (Exception) { _previews[key] = null; }
            }
            return _previews[key];
        }

        private Tuple<List<string>, List<string>, bool> FamilyParams(string family)
        {
            if (!_paramCache.ContainsKey(family))
            {
                try
                {
                    Document doc = Doc;
                    _paramCache[family] = Tuple.Create(BwicCore.FamilyParameterNames(doc, family), BwicCore.FamilyParameterNames(doc, family, false),
                                                       BwicCore.FamilyIsPlaced(doc, family));
                }
                catch (Exception)
                {
                    _paramCache[family] = Tuple.Create(new List<string>(), new List<string>(), false);
                }
            }
            return _paramCache[family];
        }

        public void FamilyChoiceChanged(string slot)
        {
            if (slot == "slab_rect" || slot == "slab_circ")
            {
                ShowAutoFamilies();
                ShowSlabFamily();
            }
        }

        /// <summary>The Automatic tab names both families it will use.</summary>
        private void ShowAutoFamilies()
        {
            foreach (var item in new[] { Tuple.Create("slab_rect", "sa_rect_img", "sa_rect_tb"), Tuple.Create("slab_circ", "sa_circ_img", "sa_circ_tb") })
            {
                FamilyCard card = _cards[item.Item1];
                string family = card.Family();
                Find<Image>(item.Item2).Source = Preview(family, card.TypeName());
                Find<TextBlock>(item.Item3).Text = family.Length > 0
                    ? family + (card.TypeName().Length > 0 ? " : " + card.TypeName() : "")
                    : "None chosen - pick one on its tab";
            }
        }

        private void OpenFamilySettings(string slot)
        {
            FamilyCard card = _cards[slot];
            string family = card.Family();
            if (family.Length == 0)
            {
                Report("Pick a family first.");
                return;
            }
            var p = FamilyParams(family);
            var existing = BwicFamilies.Sub(Profiles, family);
            var profile = existing != null && existing.Count > 0 ? existing : BwicFamilies.SeedProfile(slot, Settings, p.Item1, p.Item2);
            var dialog = new FamilySettingsWindow(slot, family, profile, p.Item1, p.Item2, p.Item3, Preview(family, card.TypeName()), Drawer,
                                                  ProfileSaved, ModelWorksets(), WorksetName());
            dialog.Win.Owner = Win;
            dialog.Win.WindowStartupLocation = WindowStartupLocation.CenterOwner;
            dialog.Win.ShowDialog();
        }

        /// <summary>The family slots a run needs set up before it may start.</summary>
        private List<string> SlotsFor(string mode)
        {
            if (mode == "place") return new List<string> { SelectedWallShape() == "circular" ? "wall_circ" : "wall" };
            if (mode == "slab")
            {
                string method = SelectedMethod();
                if (method == "rectangular") return new List<string> { "slab_rect" };
                if (method == "circular") return new List<string> { "slab_circ" };
                return new List<string> { "slab_rect", "slab_circ" };
            }
            if (mode == "global") return new List<string> { "wall" };
            return new List<string>();
        }

        private bool BlockedByFamilySettings(string mode)
        {
            Profiles = BwicCore.LoadProfiles();
            if (mode == "resize" || mode == "slab_resize")
            {
                if (Profiles.Count > 0) return false;
                BlockPrompt("No family has its Family settings saved yet. Set up the family of the BWIC to resize: Family settingsâ€¦ on its family card, then Save.");
                return true;
            }
            var missing = SlotsFor(mode).Where(slot => !BwicFamilies.IsSet(_cards[slot].Family(), Profiles)).Select(slot => Tuple.Create(slot, _cards[slot].Family())).ToList();
            if (missing.Count == 0) return false;
            var labels = new Dictionary<string, string>
            {
                { "wall", "Wall - Rectangular" }, { "wall_circ", "Wall - Circular" }, { "slab_rect", "Slab - Rectangular" }, { "slab_circ", "Slab - Circular" },
            };
            string names = string.Join("; ", missing.Select(m => m.Item2.Length > 0 ? "\"" + m.Item2 + "\" on " + labels[m.Item1] : "no family chosen on " + labels[m.Item1]));
            BlockPrompt("Set up Family settings first: " + names + ". Press Family settingsâ€¦ on the family card, check the parameters and clearance, then Save.");
            return true;
        }

        private void BlockPrompt(string detail)
        {
            BwicCore.DebugLog("run blocked: " + detail);
            OnGuide("blocked", BwicCore.Msg("Family settings needed", detail));
        }

        private List<string> ModelWorksets()
        {
            try { return BwicCore.ListWorksets(Doc).Select(w => w.Name).ToList(); }
            catch (Exception) { return new List<string>(); }
        }

        private void ProfileSaved(string slot, string family, Dictionary<string, object> profile)
        {
            Profiles[family] = profile;
            try { BwicFamilies.Save(BwicCore.ProfilesPath(), Profiles); }
            catch (Exception err)
            {
                Report("Family settings could not be saved: " + err.Message);
                return;
            }
            // set-up families go green and to the top of the lists
            ReloadFamilies();
            try { BwicCore.ApplySettings(Settings); } catch (Exception) { }
            Report("Family settings saved for \"" + family + "\".");
        }

        // ---------------------------------------------------------------- circular wall

        /// <summary>Spell out the round hole the numbers give, as the slab tab does.</summary>
        private void WallRoundChanged()
        {
            if (!_ready && _cards.Count == 0) return;
            double gap = BwicFamilies.ClearanceFor(S("wall_circ_family"), Profiles ?? new Dictionary<string, object>());
            double step;
            string text = Find<TextBox>("wc_round_tb").Text.Trim();
            if (text.Length == 0) step = 0;
            else if (!BwicCore.TryNumber(text, out step))
            {
                Find<TextBlock>("wc_example_tb").Text = "Round up to must be a number, in mm.";
                return;
            }
            double pipe = BwicFamilies.RoundHoleMm(114.3, 0, 0, gap, step);
            double group = BwicFamilies.RoundHoleMm(0, 300, 100, gap, step);
            Find<TextBlock>("wc_example_tb").Text = "DN100 steel (114.3 mm outside) gets a " + pipe.ToString("0") + " mm hole. A 300 x 100 tray gets "
                + group.ToString("0") + " mm, the circle around its corners plus the clearance (" + BwicFamilies.G(gap) + " mm, from Family settings).";
        }

        /// <summary>The Circular tab's gap and round-up, without complaining: used only when a resize turns out to have picked a round BWIC.</summary>
        private RoundSpec RoundSpecFromTab()
        {
            double step;
            if (!BwicCore.TryNumber(Find<TextBox>("wc_round_tb").Text.Trim(), out step)) step = 10.0;
            return new RoundSpec { GapMm = BwicFamilies.DefaultClearanceMm, RoundMm = step, Insulation = Find<CheckBox>("wc_insul_cb").IsChecked == true };
        }

        /// <summary>What a circular wall run needs from the circular family's own settings; null with a reason (or silently) when it cannot run.</summary>
        private RoundSpec RoundWallOptions(out string problem)
        {
            problem = null;
            var values = BwicCore.FamilySettings(Settings, "wall_circ");
            string family = BwicFamilies.Get(values, "wall_circ_family");
            if (family.Length == 0)
            {
                problem = "Pick a circular family on the Wall tab first.";
                return null;
            }
            double? step = ReadNumber(Find<TextBox>("wc_round_tb"), "Round up to");
            if (step == null) return null;
            return new RoundSpec
            {
                Family = family, Type = BwicFamilies.Get(values, "wall_circ_type"), Through = BwicFamilies.Get(values, "wall_circ_length_param"),
                Diameter = BwicFamilies.Get(values, "wall_circ_diameter_param"), Radius = BwicFamilies.Get(values, "wall_circ_radius") == "yes",
                GapMm = BwicFamilies.DefaultClearanceMm, RoundMm = step.Value, Insulation = Find<CheckBox>("wc_insul_cb").IsChecked == true,
            };
        }

        private string WorksetName()
        {
            string w = S("workset");
            return w.Length > 0 ? w : null;
        }

        private string SelectedLevelParam()
        {
            object value = Find<ComboBox>("level_param_cb").SelectedItem;
            if (value == null || value.ToString().StartsWith("<")) return null;
            return value.ToString();
        }

        private void SaveSettings()
        {
            Settings["wall_shape"] = SelectedWallShape();
            Settings["wall_circ_round"] = Find<TextBox>("wc_round_tb").Text.Trim();
            Settings["wall_circ_insulation"] = Find<CheckBox>("wc_insul_cb").IsChecked == true ? "yes" : "no";
            foreach (var g in _groups) Settings["group_" + g.Item1] = g.Item2.IsExpanded ? "open" : "closed";
            Settings["level_param"] = SelectedLevelParam() ?? "";
            Settings["include_linked"] = Find<CheckBox>("linked_cb").IsChecked == true ? "yes" : "no";
            Settings["slab_base_extra"] = Find<TextBox>("slab_base_tb").Text.Trim();
            Settings["slab_top_extra"] = Find<TextBox>("slab_top_tb").Text.Trim();
            Settings["slab_datum"] = SelectedDatum();
            Settings["slab_method"] = SelectedMethod();
            Settings["slab_circular_round"] = Find<TextBox>("slab_gapround_tb").Text.Trim();
            Settings["slab_circular_insulation"] = Find<CheckBox>("slab_insul_cb").IsChecked == true ? "yes" : "no";
            Settings["global_gap_pipes"] = Find<TextBox>("g_gap_pipes_tb").Text.Trim();
            Settings["global_gap_trays"] = Find<TextBox>("g_gap_trays_tb").Text.Trim();
            Settings["global_gap_conduit"] = Find<TextBox>("g_gap_conduit_tb").Text.Trim();
            Settings["global_comments"] = Find<CheckBox>("g_comments_cb").IsChecked == true ? "yes" : "no";
            Settings["global_workset"] = Find<CheckBox>("g_workset_cb").IsChecked == true ? "yes" : "no";
            var link = SelectedLink();
            if (link != null) Settings["global_link"] = link.Name;
            BwicCore.WriteSettings(Settings);
        }

        /// <summary>Say something to the user: while a run is going the step prompt already says what is happening, so it is logged; otherwise it shows briefly as a note.</summary>
        public override void Report(string message)
        {
            BwicCore.DebugLog("status: " + message);
            if (_running || string.IsNullOrEmpty(message)) return;
            try { OnGuide("note", new Dictionary<string, object> { { "detail", message } }); }
            catch (Exception) { }
        }

        /// <summary>Where a manual run has got to, from the core, for the prompt.</summary>
        private void OnGuide(string evt, Dictionary<string, object> details)
        {
            ArmFinish(PromptState.FinishArmed(evt, details, _finishReady));
            if (_prompt == null) _prompt = new StepPrompt(this);
            _prompt.Handle(evt, details);
        }

        // ---------------------------------------------------------------- Finish Selection

        private void ArmFinish(bool ready)
        {
            _finishReady = ready;
            var btn = Find<Button>("finish_btn");
            btn.IsEnabled = ready;
            btn.Tag = ready ? "ready" : "";
        }

        private void FinishClick()
        {
            // pressed once per step: Return a second time would repeat Revit's last command once the selection has finished
            if (!_finishReady) return;
            ArmFinish(false);
            if (!BwicCore.PressFinish()) ArmFinish(true);
        }

        // ---------------------------------------------------------------- the step card under the buttons

        public void ShowDockedPrompt(PromptLook look)
        {
            BwiPrompts.DrawCard(_dockParts, Win.FindResource, look);
            _dockParts.Card.Visibility = Visibility.Visible;
        }

        public void HideDockedPrompt() { _dockParts.Card.Visibility = Visibility.Collapsed; }

        private void WindowClosed(object sender, EventArgs args)
        {
            BwicCore.SetGuide(null);
            if (_prompt != null)
            {
                _prompt.Shut();
                _prompt = null;
            }
        }

        /// <summary>Called when a run ends any way at all (Esc, an error, a closed document): the prompt must not stay on screen.</summary>
        public void Finish()
        {
            _running = false;
            ArmFinish(false);
            if (_prompt != null) _prompt.Handle("done", new Dictionary<string, object>());
            foreach (string name in new[] { "place_btn", "resize_btn", "slab_place_btn", "slab_resize_btn", "g_run_btn" }) Find<Button>(name).IsEnabled = true;
            Win.Focusable = true;
            try { Win.Activate(); } catch (Exception) { }
        }

        private double? ReadNumber(TextBox box, string label)
        {
            double value;
            if (!BwicCore.TryNumber(box.Text.Trim(), out value))
            {
                Report(label + " must be a number, in mm.");
                return null;
            }
            if (value < 0)
            {
                Report(label + " cannot be negative.");
                return null;
            }
            return value;
        }

        // ---------------------------------------------------------------- starting a run

        private void StartRun(string mode)
        {
            // nothing runs on a family whose Family settings have not been saved
            if (BlockedByFamilySettings(mode)) return;
            string message;
            if (mode == "slab" || mode == "slab_resize")
            {
                string method = SelectedMethod();
                string rect = S("slab_family"), circ = S("slab_circ_family");
                if (method == "circular" && circ.Length == 0 && rect.Length == 0) { Report("Choose a circular family in Settings first."); return; }
                if (method == "rectangular" && rect.Length == 0) { Report("Choose a rectangular family in Settings first."); return; }
                if (method == "auto" && rect.Length == 0 && circ.Length == 0)
                {
                    Report("Choose a family in Settings first - the rectangular one for trays and ducts, the circular one for pipes.");
                    return;
                }
                if (method == "auto" && circ.Length == 0) Report("No circular family set, so pipes on their own will be skipped. Set one in Settings.");
                var checks = new List<Tuple<TextBox, string>>
                {
                    Tuple.Create(Find<TextBox>("slab_base_tb"), "Base offset"), Tuple.Create(Find<TextBox>("slab_top_tb"), "Top offset"),
                };
                if (method == "auto" || method == "circular") checks.Add(Tuple.Create(Find<TextBox>("slab_gapround_tb"), "Round up"));
                foreach (var c in checks) if (ReadNumber(c.Item1, c.Item2) == null) return;
                _handler.Options = new BwicOptions
                {
                    LogComments = Find<CheckBox>("slab_comments_cb").IsChecked == true, WorksetName = WorksetName() ?? "",
                    IncludeLinked = Find<CheckBox>("slab_linked_cb").IsChecked == true, Pin = Find<CheckBox>("slab_pin_cb").IsChecked == true,
                    LevelParam = SelectedLevelParam() ?? "",
                };
                var settings = new Dictionary<string, string>(Settings);
                settings["slab_base_extra"] = Find<TextBox>("slab_base_tb").Text.Trim();
                settings["slab_top_extra"] = Find<TextBox>("slab_top_tb").Text.Trim();
                settings["slab_datum"] = SelectedDatum();
                settings["slab_method"] = SelectedMethod();
                settings["slab_circular_round"] = Find<TextBox>("slab_gapround_tb").Text.Trim();
                settings["slab_circular_insulation"] = Find<CheckBox>("slab_insul_cb").IsChecked == true ? "yes" : "no";
                _handler.Settings = settings;
                message = mode == "slab_resize"
                    ? "Working in Revit - pick the opening, then the services and press Return, then the floor. Esc returns here."
                    : "Working in Revit - select the services and press Return, then click the floor. Esc returns here.";
            }
            else if (mode == "global")
            {
                var numbers = new List<double>();
                foreach (var c in new[] { Tuple.Create("g_gap_pipes_tb", "Pipe grouping distance"), Tuple.Create("g_gap_trays_tb", "Tray grouping distance"),
                                          Tuple.Create("g_gap_conduit_tb", "Conduit grouping distance") })
                {
                    double? v = ReadNumber(Find<TextBox>(c.Item1), c.Item2);
                    if (v == null) return;
                    numbers.Add(v.Value);
                }
                var link = SelectedLink();
                if (link == null)
                {
                    Report("There is no loaded link to read the walls from.");
                    return;
                }
                _handler.GlobalSettings = new GlobalSettings
                {
                    LinkId = link.Instance.Id, ClearanceMm = BwicFamilies.DefaultClearanceMm, GapPipesMm = numbers[0], GapTraysMm = numbers[1],
                    GapConduitMm = numbers[2], LogComments = Find<CheckBox>("g_comments_cb").IsChecked == true,
                    UseWorkset = Find<CheckBox>("g_workset_cb").IsChecked == true, LevelParam = SelectedLevelParam() ?? "",
                };
                _handler.Settings = new Dictionary<string, string>(Settings);
                message = "Working through the active view - the window will not redraw until the sweep finishes.";
            }
            else
            {
                double clearance = BwicFamilies.DefaultClearanceMm;
                RoundSpec roundWall = null;
                if (SelectedWallShape() == "circular")
                {
                    string problem;
                    roundWall = RoundWallOptions(out problem);
                    if (roundWall == null)
                    {
                        if (!string.IsNullOrEmpty(problem)) Report(problem);
                        return;
                    }
                }
                BwicCore.ApplySettings(Settings);
                _handler.ClearanceMm = clearance;
                _handler.Options = new BwicOptions
                {
                    LogComments = Find<CheckBox>("comments_cb").IsChecked == true, WorksetName = WorksetName() ?? "",
                    IncludeLinked = Find<CheckBox>("linked_cb").IsChecked == true, Pin = Find<CheckBox>("pin_cb").IsChecked == true,
                    LevelParam = SelectedLevelParam() ?? "", RoundWall = roundWall,
                    // a resize can pick a round BWIC from either tab, so the round figures always go along
                    RoundSpecValue = RoundSpecFromTab(),
                };
                message = mode == "resize"
                    ? "Working in Revit - pick the BWIC, then the services and press Return, then the wall. Esc returns here."
                    : "Working in Revit - select the services and press Return, then pick the wall. Esc returns here.";
            }
            SaveSettings();
            _handler.Mode = mode;
            foreach (string name in new[] { "place_btn", "resize_btn", "slab_place_btn", "slab_resize_btn", "g_run_btn" }) Find<Button>(name).IsEnabled = false;
            _running = true;
            Report(message);
            // stop the window taking keyboard focus while Revit is picking, so Return reaches Revit and finishes the selection
            Win.Focusable = false;
            BwicCore.SetGuide(mode == "global" ? (Action<string, Dictionary<string, object>>)null : OnGuide);
            _extEvent.Raise();
            BwicCore.FocusRevit();
        }

        private void SettingsClick()
        {
            // opening Settings beside a parked bar would put it in the wrong place
            Drawer.RestoreNow();
            try
            {
                var window = new SettingsWindow(Settings, SettingsApplied, Drawer);
                window.Win.Owner = Win;
                window.PlaceBeside(Win);
                window.Win.ShowDialog();
            }
            catch (Exception err)
            {
                BwicCore.DebugLog("settings window failed\n" + err);
                Report("Could not open Settings: " + err.Message);
            }
        }

        private void SettingsApplied(Dictionary<string, string> values)
        {
            Settings = values;
            LoadLevelParams();
            RestoreSettings();
            ShowSlabFamily();
            Report("Settings saved.");
        }

        // ---------------------------------------------------------------- resize grips

        // A borderless AllowsTransparency window has nothing hit testable in its frame, so WPF cannot resize it however ResizeMode is set.
        // These handlers are the frame. Each clamps at the minimum rather than letting the window turn inside out.
        private void Widen(double change, bool fromLeft)
        {
            if (fromLeft)
            {
                double next = Win.Width - change;
                if (next < Win.MinWidth) return;
                Win.Left += change;
                Win.Width = next;
            }
            else
            {
                double next = Win.Width + change;
                if (next >= Win.MinWidth) Win.Width = next;
            }
        }

        private void Heighten(double change, bool fromTop)
        {
            try { if (Win.SizeToContent != SizeToContent.Manual) Win.SizeToContent = SizeToContent.Manual; }
            catch (Exception) { }
            if (fromTop)
            {
                double next = Win.Height - change;
                if (next < Win.MinHeight) return;
                Win.Top += change;
                Win.Height = next;
            }
            else
            {
                double next = Win.Height + change;
                if (next >= Win.MinHeight) Win.Height = next;
            }
        }

        // ---------------------------------------------------------------- debug

        /// <summary>One tick box per tab, all the same setting: the one clicked decides.</summary>
        private void DebugChanged(object sender)
        {
            var boxes = new[] { Find<CheckBox>("debug_cb"), Find<CheckBox>("slab_debug_cb"), Find<CheckBox>("g_debug_cb") };
            bool on = sender != null && boxes.Contains(sender as CheckBox) ? ((CheckBox)sender).IsChecked == true : boxes[0].IsChecked == true;
            foreach (CheckBox box in boxes) box.IsChecked = on;
            BwicCore.SetDebug(on);
            Settings["debug"] = on ? "yes" : "no";
            if (sender != null)
            {
                BwicCore.WriteSettings(Settings);
                if (on)
                {
                    BwicCore.DebugLog("debug logging on: bwic_penetration " + BwicCore.ToolVersion + "  " + BwicCore.BuildInfo());
                    Report("Debug logging on. Log: " + BwicCore.DebugPath());
                }
                else Report("Debug logging off.");
            }
        }

        private void DebugOpen()
        {
            string path = BwicCore.DebugPath();
            if (!File.Exists(path))
            {
                Report("Nothing logged yet - run the tool with Debug ticked.");
                return;
            }
            try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); }
            catch (Exception) { Report("Log is at " + path); }
        }

        /// <summary>Spell out what the numbers will actually do: the gap is a clearance all round, so the hole is twice the gap bigger.</summary>
        private void SlabSizeChanged()
        {
            var example = Win.FindName("slab_gap_example") as TextBlock;
            if (example == null || Settings == null) return;
            double gap = BwicFamilies.ClearanceFor(S("slab_circ_family"), Profiles ?? new Dictionary<string, object>());
            double step;
            string text = Find<TextBox>("slab_gapround_tb").Text.Trim();
            if (text.Length == 0) step = 0;
            else if (!BwicCore.TryNumber(text, out step))
            {
                example.Text = "Round up to must be a number, in mm.";
                return;
            }
            double raw = 114.3 + 2 * gap;
            if (step > 0) raw = Math.Ceiling(raw / step - 1e-9) * step;
            example.Text = "DN100 steel is 114.3 mm outside, so it gets a " + raw.ToString("0") + " mm hole (114.3 + 2 x " + gap.ToString("0")
                           + ", rounded up). Its nominal size of 100 would have given a smaller one.";
        }

        // ---------------------------------------------------------------- Global Placement

        /// <summary>Fill the link list: a link selected in the model, then the remembered one, then the hinted, then any.</summary>
        private void LoadLinks()
        {
            var cb = Find<ComboBox>("g_link_cb");
            cb.Items.Clear();
            _links = new List<BwicGlobal.LinkEntry>();
            RevitLinkInstance selected = null;
            try
            {
                UIDocument uidoc = _uiapp.ActiveUIDocument;
                _links = BwicGlobal.LoadedLinks(uidoc.Document);
                selected = BwicGlobal.PreselectedLink(uidoc);
            }
            catch (Exception) { }
            if (_links.Count == 0)
            {
                cb.Items.Add("<no loaded links in this model>");
                cb.SelectedIndex = 0;
                cb.IsEnabled = false;
                return;
            }
            string remembered = S("global_link");
            int pSelected = -1, pRemembered = -1, pHint = -1;
            for (int position = 0; position < _links.Count; position++)
            {
                var pair = _links[position];
                cb.Items.Add(pair.Name);
                if (selected != null && pair.Instance.Id == selected.Id && pSelected < 0) pSelected = position;
                if (remembered.Length > 0 && pair.Name == remembered && pRemembered < 0) pRemembered = position;
                if (pair.Name.ToLowerInvariant().Contains(BwicGlobal.LinkNameHint.ToLowerInvariant()) && pHint < 0) pHint = position;
            }
            int index = new[] { pSelected, pRemembered, pHint }.FirstOrDefault(p => p >= 0);
            cb.IsEnabled = true;
            cb.SelectedIndex = index;
        }

        private BwicGlobal.LinkEntry SelectedLink()
        {
            int position = Find<ComboBox>("g_link_cb").SelectedIndex;
            if (_links.Count == 0 || position < 0 || position >= _links.Count) return null;
            return _links[position];
        }

        private void RestoreGlobal()
        {
            Find<TextBox>("g_gap_pipes_tb").Text = S("global_gap_pipes").Length > 0 ? S("global_gap_pipes") : BwicGlobal.DefaultGapPipesMm.ToString("0");
            Find<TextBox>("g_gap_trays_tb").Text = S("global_gap_trays").Length > 0 ? S("global_gap_trays") : BwicGlobal.DefaultGapTraysMm.ToString("0");
            Find<TextBox>("g_gap_conduit_tb").Text = S("global_gap_conduit").Length > 0 ? S("global_gap_conduit") : BwicGlobal.DefaultGapConduitMm.ToString("0");
            Find<CheckBox>("g_comments_cb").IsChecked = S("global_comments", "yes") != "no";
            Find<CheckBox>("g_workset_cb").IsChecked = S("global_workset", "yes") != "no";
        }

        /// <summary>The results window: modeless, and only ever one of it.</summary>
        public void ShowResults(GlobalSummary summary)
        {
            try
            {
                if (_results != null)
                {
                    try { _results.Win.Close(); } catch (Exception) { }
                }
                _results = new ResultsWindow(summary, _selectEvent, _selectHandler);
                _results.Show();
            }
            catch (Exception err)
            {
                BwicCore.DebugLog("results window failed\n" + err);
            }
        }

        private void TabChanged(object sender, SelectionChangedEventArgs args)
        {
            // every list and sub tab inside a tab bubbles its SelectionChanged up to here; only the main tabs themselves count
            if (args != null && args.OriginalSource != Find<TabControl>("tabs")) return;
            try
            {
                ShowActions();
                int index = Find<TabControl>("tabs").SelectedIndex;
                Settings["active_tab"] = index >= 0 && index < TabNames.Length ? TabNames[index] : "wall";
                BwicCore.WriteSettings(Settings);
            }
            catch (Exception) { }
        }

        /// <summary>Only the current tab's buttons are shown; they sit below the tab control so they can never be pushed off the bottom.</summary>
        private void ShowActions()
        {
            int index = Find<TabControl>("tabs").SelectedIndex;
            var panels = new[] { Find<StackPanel>("wall_actions"), Find<StackPanel>("slab_actions"), Find<StackPanel>("global_actions") };
            for (int position = 0; position < panels.Length; position++)
                panels[position].Visibility = position == index ? Visibility.Visible : Visibility.Collapsed;
            // Global Placement has nothing to select
            Find<Button>("finish_btn").Visibility = index == 2 ? Visibility.Collapsed : Visibility.Visible;
        }

        public void Show()
        {
            Win.Show();
        }
    }
}
