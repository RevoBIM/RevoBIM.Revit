using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using RevoBIM.Tools.HangerAutomation;

namespace RevoBIM.UI.HangerAutomation
{
    // =====================================================================================================
    // Hanger Automation - the Family Hangers and Family Floor Support tabs. Port of hfam_ui.py (FamTab and the
    // helper functions; the two dialogs are in HfamDialogs.cs).
    //
    // One FamTab class runs both tabs. The floor tab (mode "floor") has the same controls with Flr in place of
    // Fam in their names (HfamCore.FlrName), its own settings (flr_ in place of fam_, FhaCore.FloorKey) and no
    // drop rods; its jobs get the settings remapped back to fam_ keys plus _mode = "floor".
    //
    // Revit is only read through the window's ExternalEvent (StartQuiet / StartJob), never directly from a click
    // handler.
    // =====================================================================================================

    /// <summary>What a FamTab needs from the window (Python <c>owner</c> in hfam_ui.py), on top of IFhaHost.</summary>
    public interface IFamOwner : IFhaHost
    {
        /// <summary>Python owner.c(name): the named element of the window.</summary>
        object C(string name);

        /// <summary>The window's settings (Python owner.settings).</summary>
        FhaSettings Settings { get; }

        /// <summary>The model's user worksets (Python owner.worksets).</summary>
        List<string> Worksets { get; }

        /// <summary>Python owner.uiapp.</summary>
        Autodesk.Revit.UI.UIApplication UiApp { get; }

        /// <summary>Python owner.dim_ui: asks where dimensions go from a 3D view.</summary>
        DimViewsUI DimUi { get; }

        /// <summary>A job or read is queued or running.</summary>
        bool Busy { get; }

        /// <summary>Python owner._save(): gather every control and write the settings file.</summary>
        void Save();

        /// <summary>One tab saved a family's settings: the other re-reads the file.</summary>
        void FamilySettingsSaved(FamTab by);

        /// <summary>A tool: picks, writes, results box, debug file.</summary>
        bool StartJob(FhaJob job, Action<FhaSettings> extra = null);

        /// <summary>A read: the answer goes to callback(result, error). False if busy.</summary>
        bool StartQuiet(FhaJob job, Action<object, string> callback, string status = "Reading...");
    }

    /// <summary>A family's parameter names and where they came from (Python (names, source) tuple in FamTab.params).</summary>
    public sealed class FamParams
    {
        public List<string> Names;
        public string Source;

        public FamParams(List<string> names, string source)
        {
            Names = names;
            Source = source;
        }
    }

    /// <summary>One line of the family list: its TextBlock and whether the family is set up (Python (tb, set_up)).</summary>
    public sealed class FamRow
    {
        public readonly TextBlock Tb;
        public readonly bool SetUp;

        public FamRow(TextBlock tb, bool setUp)
        {
            Tb = tb;
            SetUp = setUp;
        }
    }

    public sealed class FamTab
    {
        private static readonly string[][] FamChecks =
        {
            new[] { "ChkFamRodPlace", "fam_rod_place" }, new[] { "ChkFamRodRealign", "fam_rod_realign" },
            new[] { "ChkFamRodAuto", "fam_rod_auto" }, new[] { "ChkFamDw144", "fam_dw144" },
            new[] { "ChkFamAccessory", "fam_accessory" }, new[] { "ChkFamSkipExisting", "fam_skip_existing" },
            new[] { "ChkFamDims", "fam_dims" }, new[] { "ChkFamInsPlace", "fam_ins_place" },
            new[] { "ChkFamInsRealign", "fam_ins_realign" }, new[] { "ChkFamInsAuto", "fam_ins_auto" },
            new[] { "ChkFamRodLinked", "fam_rod_linked" }, new[] { "ChkFamLockPlace", "fam_lock_place" },
            new[] { "ChkFamLockRealign", "fam_lock_realign" }, new[] { "ChkFamLockAuto", "fam_lock_auto" },
            new[] { "ChkFamSetOnly", "fam_set_only" },
        };

        private sealed class FamBox
        {
            public readonly string Name, Key;
            public readonly double Default;

            public FamBox(string name, string key, double dflt)
            {
                Name = name;
                Key = key;
                Default = dflt;
            }
        }

        private static readonly FamBox[] FamBoxes =
        {
            new FamBox("TxtFamSpacing", "fam_spacing", 3000.0), new FamBox("TxtFamStart", "fam_start_off", 300.0),
            new FamBox("TxtFamEnd", "fam_end_off", 300.0), new FamBox("TxtFamFlange", "fam_flange_clear", 150.0),
            new FamBox("TxtFamTakeoff", "fam_takeoff_clear", 400.0), new FamBox("TxtFamDimOffset", "fam_dim_offset", 800.0),
        };

        private static readonly string[] FamButtons =
        {
            "BtnFamPlace", "BtnFamRealign", "BtnFamAuto", "BtnFamRods", "BtnFamSettings", "BtnFamRefresh", "BtnFamRules",
        };

        private static readonly string[] RodControls =
        {
            "ChkFamRodPlace", "ChkFamRodRealign", "ChkFamRodAuto", "ChkFamRodLinked", "BtnFamRods",
        };

        public const string DimDefault = "(default dimension type)";
        public const string NoneLabel = "(none)";

        public const double ListH = 92.0;                    // the family list's starting height
        public const double ListMin = 60.0, ListMax = 700.0; // how far its grip drags

        /// <summary>A family already set up in Family settings is bold green.</summary>
        public static FamRow FamilyRow(string text, bool setUp)
        {
            var tb = new TextBlock();
            tb.Text = text;
            if (setUp)
            {
                tb.FontWeight = FontWeights.Bold;
                tb.SetResourceReference(TextBlock.ForegroundProperty, "SetTextBrush");
                tb.ToolTip = "Set up in Family settings";
            }
            return new FamRow(tb, setUp);
        }

        /// <summary>The family list height, kept between its limits.</summary>
        public static double ListHeight(double h)
        {
            if (double.IsNaN(h)) h = ListH;   // NaN (Height not set)
            return Math.Max(ListMin, Math.Min(ListMax, h));
        }

        private static string Sget(IDictionary<string, string> s, string key, string dflt)
        {
            string v;
            return s != null && s.TryGetValue(key, out v) && v != null ? v : dflt;
        }

        public readonly IFamOwner O;
        public readonly string Mode;
        public readonly bool Floor;
        public readonly string Noun;
        private readonly List<string[]> checks;
        private readonly List<string> buttons;
        public List<FamTypeItem> Items;
        private List<FamTypeItem> shown = new List<FamTypeItem>();
        private Dictionary<string, byte[]> previews = new Dictionary<string, byte[]>();
        public readonly Dictionary<string, FamParams> Params = new Dictionary<string, FamParams>();   // family name -> (parameter names, where they came from)
        public Dictionary<string, FamConfig> Fams;
        private bool loading;
        private string wantPreview;
        private bool busy;
        public bool ViewOk;
        private Collapser fold;
        private List<string> wsValues = new List<string>();
        private readonly HashSet<string> ignored = new HashSet<string>(StringComparer.Ordinal);   // families the user said to carry on with, unconfigured, this session
        /// <summary>While the window is being built we are in Revit's API context: previews read directly.</summary>
        public Autodesk.Revit.DB.Document OpenDoc;
        private bool mirroring;
        private double listGrow;
        private List<FamRow> rows = new List<FamRow>();   // one for each family listed

        public FamTab(IFamOwner owner, Autodesk.Revit.DB.Document doc, string mode = "hang", IEnumerable<FamTypeItem> items = null)
        {
            O = owner;
            Mode = Array.IndexOf(HfamCore.Modes, mode) >= 0 ? mode : "hang";
            Floor = Mode == "floor";
            Noun = Floor ? "floor support" : "hanger";
            checks = FamChecks.Where(c => !(Floor && Array.IndexOf(RodControls, c[0]) >= 0)).ToList();
            buttons = FamButtons.Where(n => !(Floor && Array.IndexOf(RodControls, n) >= 0)).ToList();
            Items = new List<FamTypeItem>();
            Fams = HfamCore.LoadFamilies();
            loading = false;
            wantPreview = null;
            busy = false;
            ViewOk = false;
            fold = null;
            OpenDoc = doc;
            if (items != null)
            {
                Items = new List<FamTypeItem>(items);
            }
            else
            {
                try
                {
                    Items = HfamRevit.ListFamilyTypes(doc);   // the command's own API context
                }
                catch (Exception)
                {
                    Items = new List<FamTypeItem>();
                }
            }
            var dims = new List<string>();
            try
            {
                dims = FhaRevit.LinearDimensionTypes(doc).Select(d => d.Key).ToList();
                ViewOk = HfamRevit.IsFloorPlan(owner.UiApp.ActiveUIDocument.ActiveView);
            }
            catch (Exception)
            {
            }
            foreach (string name in new[] { "CmbFamDimType", "CmbFamAutoDimType" })   // the Dimension placer and Auto place share them
            {
                var cd = C<ComboBox>(name);
                cd.Items.Add(DimDefault);
                foreach (string n in dims) cd.Items.Add(n);
            }
            mirroring = false;
            listGrow = 0.0;
            var cb = C<ComboBox>("CmbFamCategory");
            foreach (KeyValuePair<string, string> kv in HfamCore.Categories) cb.Items.Add(kv.Value);
            if (Floor)
            {
                var cbase = (ComboBox)O.C("CmbFlrBase");
                foreach (KeyValuePair<string, string> kv in FhaCore.Bases) cbase.Items.Add(kv.Value);
            }
        }

        public object C(string name)
        {
            return O.C(Floor ? HfamCore.FlrName(name) : name);
        }

        private T C<T>(string name) where T : class
        {
            return (T)C(name);
        }

        /// <summary>This tab's settings key for a Family Hangers key.</summary>
        public string K(string key)
        {
            return Floor ? FhaCore.FloorKey(key) : key;
        }

        // ---- settings in and out
        public void Load(IDictionary<string, string> s)
        {
            loading = true;
            foreach (string[] c in checks) C<ToggleButton>(c[0]).IsChecked = FhaCore.AsBool(s, K(c[1]));
            foreach (FamBox b in FamBoxes) C<TextBox>(b.Name).Text = Sget(s, K(b.Key), FhaCore.NumText(b.Default));
            List<string> keys = HfamCore.Categories.Select(c => c.Key).ToList();
            string cat = Sget(s, K("fam_category"), "all");
            C<ComboBox>("CmbFamCategory").SelectedIndex = keys.Contains(cat) ? keys.IndexOf(cat) : 0;
            C<TextBox>("TxtFamSearch").Text = Sget(s, K("fam_search"), "");
            C<ListBox>("LstFamilies").Height = ListHeight(FhaCore.ParseMm(Sget(s, K("fam_list_h"), "92"), ListH));
            string want = Sget(s, K("fam_dim_type"), "");
            foreach (string name in new[] { "CmbFamDimType", "CmbFamAutoDimType" })
            {
                var cd = C<ComboBox>(name);
                cd.SelectedIndex = 0;
                for (int i = 0; i < cd.Items.Count; i++)
                    if (want.Length > 0 && (cd.Items[i] as string) == want) cd.SelectedIndex = i;
            }
            C<TextBox>("TxtFamAutoDimOffset").Text = C<TextBox>("TxtFamDimOffset").Text;
            wsValues = FhaUi.FillWorksetCombo(C<ComboBox>("CmbFamWorkset"), O.Worksets, Sget(s, K("fam_workset"), ""));
            if (Floor)
            {
                List<string> bkeys = FhaCore.Bases.Select(b => b.Key).ToList();
                string bs = Sget(s, "flr_base", "level");
                ((ComboBox)O.C("CmbFlrBase")).SelectedIndex = bkeys.Contains(bs) ? bkeys.IndexOf(bs) : 0;
                ((ToggleButton)O.C("ChkFlrBaseLinked")).IsChecked = FhaCore.AsBool(s, "flr_base_linked");
            }
            loading = false;
            SetViewOk(ViewOk);
            Refill(Sget(s, K("fam_symbol"), ""));
        }

        public IDictionary<string, string> Gather(IDictionary<string, string> s)
        {
            foreach (string[] c in checks) s[K(c[1])] = C<ToggleButton>(c[0]).IsChecked == true ? "1" : "0";
            foreach (FamBox b in FamBoxes) s[K(b.Key)] = FhaCore.NumText(FhaCore.ParseMm(C<TextBox>(b.Name).Text, b.Default));
            var cd = C<ComboBox>("CmbFamDimType");
            s[K("fam_dim_type")] = cd.SelectedIndex <= 0 ? "" : Convert.ToString(cd.SelectedItem);
            s[K("fam_category")] = CategoryKey();
            if (wsValues.Count > 0) s[K("fam_workset")] = FhaCore.WorksetValue(wsValues, C<ComboBox>("CmbFamWorkset").SelectedIndex);
            if (Floor)
            {
                int i = ((ComboBox)O.C("CmbFlrBase")).SelectedIndex;
                s["flr_base"] = i >= 0 && i < FhaCore.Bases.Count ? FhaCore.Bases[i].Key : "level";
                s["flr_base_linked"] = ((ToggleButton)O.C("ChkFlrBaseLinked")).IsChecked == true ? "1" : "0";
            }
            s[K("fam_search")] = C<TextBox>("TxtFamSearch").Text ?? "";
            s[K("fam_list_h")] = FhaCore.NumText(ListHeight(C<ListBox>("LstFamilies").Height));
            FamTypeItem it = Current();
            if (it != null) s[K("fam_symbol")] = it.Key;
            return s;
        }

        public void Wire()
        {
            string[] tools = Floor ? new[] { "Place", "Realign", "Auto", "Dims" } : new[] { "Place", "Realign", "Auto", "Rods", "Dims" };
            fold = new Collapser(O.Win, tools, FoldChanged, O.ResizeForFold, Floor ? "Flr" : "Fam");
            fold.Load("");   // every tool starts folded; open the one you need
            C<ButtonBase>("BtnFamToggleAll").Click += ToggleAll;
            // Auto place's dimension distance and type mirror the Dimension placer's (one setting each)
            C<TextBoxBase>("TxtFamDimOffset").TextChanged += Mirror("TxtFamDimOffset", "TxtFamAutoDimOffset");
            C<TextBoxBase>("TxtFamAutoDimOffset").TextChanged += Mirror("TxtFamAutoDimOffset", "TxtFamDimOffset");
            C<Selector>("CmbFamDimType").SelectionChanged += MirrorSel("CmbFamDimType", "CmbFamAutoDimType");
            C<Selector>("CmbFamAutoDimType").SelectionChanged += MirrorSel("CmbFamAutoDimType", "CmbFamDimType");
            C<Selector>("CmbFamCategory").SelectionChanged += FilterChanged;
            C<TextBoxBase>("TxtFamSearch").TextChanged += FilterChanged;
            C<ToggleButton>("ChkFamSetOnly").Checked += FilterChanged;
            C<ToggleButton>("ChkFamSetOnly").Unchecked += FilterChanged;
            C<Selector>("LstFamilies").SelectionChanged += Picked;
            C<Thumb>("ThmFamListSize").DragDelta += ListDrag;
            C<Thumb>("ThmFamListSize").DragCompleted += ListDropped;
            C<ButtonBase>("BtnFamSettings").Click += SettingsClick;
            C<ButtonBase>("BtnFamRefresh").Click += RefreshClick;
            C<ButtonBase>("BtnFamPlace").Click += PlaceClick;
            C<ButtonBase>("BtnFamRealign").Click += RealignClick;
            C<ButtonBase>("BtnFamAuto").Click += AutoClick;
            C<ButtonBase>("BtnFamDims").Click += DimsClick;
            if (!Floor) C<ButtonBase>("BtnFamRods").Click += RodsClick;
            C<ButtonBase>("BtnFamRules").Click += RulesClick;
        }

        // ---- the family list: drag its grip to show more or fewer families
        private void ListDrag(object sender, DragDeltaEventArgs e)
        {
            try
            {
                var lst = C<ListBox>("LstFamilies");
                double old = lst.Height;
                double nu = ListHeight(old + e.VerticalChange);
                if (Math.Abs(nu - old) > 0.1)
                {
                    lst.Height = nu;
                    listGrow += nu - old;
                }
            }
            catch (Exception)
            {
            }
        }

        private void ListDropped(object sender, DragCompletedEventArgs e)
        {
            double grow = listGrow;
            listGrow = 0.0;
            try
            {
                if (Math.Abs(grow) > 0.5) O.ResizeForFold(grow);   // the window follows, like opening a tool
            }
            catch (Exception)
            {
            }
        }

        private TextChangedEventHandler Mirror(string src, string dst)
        {
            return (sender, e) =>
            {
                if (mirroring || loading) return;
                mirroring = true;
                try
                {
                    C<TextBox>(dst).Text = C<TextBox>(src).Text;
                }
                catch (Exception)
                {
                }
                finally
                {
                    mirroring = false;
                }
            };
        }

        private SelectionChangedEventHandler MirrorSel(string src, string dst)
        {
            return (sender, e) =>
            {
                if (mirroring || loading) return;
                mirroring = true;
                try
                {
                    C<ComboBox>(dst).SelectedIndex = C<ComboBox>(src).SelectedIndex;
                }
                catch (Exception)
                {
                }
                finally
                {
                    mirroring = false;
                }
            };
        }

        // ---- folding tools
        private void ToggleAll(object sender, RoutedEventArgs e)
        {
            try
            {
                fold.SetAll(!fold.AllOpen());
            }
            catch (Exception)
            {
            }
        }

        private void FoldChanged()
        {
            try
            {
                C<TextBlock>("FamToggleAllTxt").Text = fold.AllOpen() ? "Collapse all" : "Expand all";
            }
            catch (Exception)
            {
            }
        }

        private void RulesClick(object sender, RoutedEventArgs e)
        {
            try
            {
                var dlg = new RulesDialog(O, O.Settings);
                if (dlg.Show())
                {
                    foreach (KeyValuePair<string, string> kv in dlg.Result) O.Settings[kv.Key] = kv.Value;
                    O.Save();
                    O.Status("Hanger rules saved");
                }
            }
            catch (Exception ex)
            {
                O.Status("Hanger rules failed: " + ex.Message);
            }
        }

        public void SetBusy(bool isBusy)
        {
            busy = isBusy;
            foreach (string n in buttons)
            {
                try
                {
                    ((UIElement)C(n)).IsEnabled = !isBusy;
                }
                catch (Exception)
                {
                }
            }
            SetViewOk(ViewOk);
        }

        /// <summary>The dimension placer only lights up in a floor plan.</summary>
        public void SetViewOk(bool ok)
        {
            ViewOk = ok;
            try
            {
                ((UIElement)C("BtnFamDims")).IsEnabled = ViewOk && !busy;
                ((UIElement)C("FamDimHint")).Visibility = ViewOk ? Visibility.Collapsed : Visibility.Visible;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Family settings and the chosen type, for Copy debug.</summary>
        public string DebugText()
        {
            FamTypeItem it = Current();
            var lines = new List<string>
            {
                "[" + (Floor ? "Family Floor Support" : "Family Hangers") + "]",
                "Chosen: " + (it != null ? it.Key + " (" + it.CatLabel + ")" : "(none)"),
                "Families listed: " + Items.Count,
                "Floor plan active: " + (ViewOk ? "True" : "False"),
            };
            if (it != null)
            {
                FamConfig cfg = CfgFor(it);
                var keys = HfamCore.FamKeys.ToList();
                keys.Sort(StringComparer.Ordinal);
                lines.Add("Chosen family settings: " + string.Join(" | ", keys.Select(k => k + "=" + cfg[k])));
                FamParams p;
                if (!Params.TryGetValue(it.Family, out p)) p = new FamParams(new List<string>(), "not read yet");
                lines.Add("Parameters (" + p.Source + "): " + string.Join(", ", p.Names));
            }
            lines.Add(HfamCore.DumpFamilies(Fams));
            return string.Join("\n", lines);
        }

        // ---- the list
        public string CategoryKey()
        {
            int i = C<ComboBox>("CmbFamCategory").SelectedIndex;
            return i >= 0 && i < HfamCore.Categories.Count ? HfamCore.Categories[i].Key : "all";
        }

        public void Refill(string keepKey = null)
        {
            if (keepKey == null)
            {
                FamTypeItem cur = Current();
                keepKey = cur != null ? cur.Key : "";
            }
            loading = true;
            try
            {
                shown = HfamCore.FilterTypes(Items, CategoryKey(), C<TextBox>("TxtFamSearch").Text ?? "");
                if (C<ToggleButton>("ChkFamSetOnly").IsChecked == true)
                    shown = shown.Where(it => HfamCore.Configured(Fams, it.Family)).ToList();
                var lst = C<ListBox>("LstFamilies");
                lst.Items.Clear();
                rows = new List<FamRow>();
                int pick = -1;
                for (int i = 0; i < shown.Count; i++)
                {
                    FamTypeItem it = shown[i];
                    FamRow row = FamilyRow(it.Family + "  :  " + it.Type, HfamCore.Configured(Fams, it.Family));
                    rows.Add(row);
                    lst.Items.Add(row.Tb);
                    if (it.Key == keepKey) pick = i;
                }
                if (pick < 0 && shown.Count == 1) pick = 0;
                lst.SelectedIndex = pick;
                if (pick >= 0) lst.ScrollIntoView(lst.Items[pick]);
            }
            catch (Exception)
            {
            }
            finally
            {
                loading = false;
            }
            PaintRows();
            ChosenChanged();
        }

        /// <summary>
        /// Set-up families in bold green - the selected row in the normal text colour, so it still reads on the
        /// selection highlight.
        /// </summary>
        public void PaintRows()
        {
            int sel;
            try
            {
                sel = C<ListBox>("LstFamilies").SelectedIndex;
            }
            catch (Exception)
            {
                sel = -1;
            }
            for (int i = 0; i < rows.Count; i++)
            {
                if (rows[i].SetUp)
                {
                    try
                    {
                        rows[i].Tb.SetResourceReference(TextBlock.ForegroundProperty, i == sel ? "TextBrush" : "SetTextBrush");
                    }
                    catch (Exception)
                    {
                    }
                }
            }
        }

        public FamTypeItem Current()
        {
            int i;
            try
            {
                i = C<ListBox>("LstFamilies").SelectedIndex;
            }
            catch (Exception)
            {
                return null;
            }
            return i >= 0 && i < shown.Count ? shown[i] : null;
        }

        private void FilterChanged(object sender, RoutedEventArgs e)
        {
            if (!loading) Refill();
        }

        private void Picked(object sender, SelectionChangedEventArgs e)
        {
            if (!loading)
            {
                PaintRows();
                ChosenChanged();
            }
        }

        public FamConfig CfgFor(FamTypeItem it)
        {
            FamParams p;
            List<string> names = Params.TryGetValue(it.Family, out p) ? p.Names : new List<string>();
            return HfamCore.FamConfigFor(Fams, it.Family, names);
        }

        private void ChosenChanged()
        {
            FamTypeItem it = Current();
            var txt = C<TextBlock>("FamChosenTxt");
            if (it == null)
            {
                txt.Text = Items.Count > 0 ? "Choose the " + Noun + " family and type" :
                    "No Generic Model, MEP Ancillary Framing or Duct Accessory families in the project";
                ShowPreview(null);
                return;
            }
            FamConfig cfg = CfgFor(it);
            string width;
            if (cfg.Left.Length > 0 && cfg.Right.Length > 0) width = "width: " + cfg.Left + " / " + cfg.Right;
            else width = "width parameters not set - open Family settings";
            string setup = HfamCore.Configured(Fams, it.Family) ? "" : "  |  not set up yet";
            if (Floor && cfg.Style == "circ")
            {
                txt.Text = it.CatLabel + "  |  Circular System Based  |  diameter: " + Or(cfg.Dia, "(none)") +
                           "  |  height: " + Or(cfg.CircHeight, "(none)") + setup;
            }
            else if (Floor)
            {
                txt.Text = it.CatLabel + "  |  Rectangular Floor Based  |  " + width + "  |  first bar: " + Or(cfg.FirstBar, "(none)") +
                           "  |  height: " + Or(cfg.Height, "(none)") + setup;
            }
            else if (cfg.Style == "circ")
            {
                txt.Text = it.CatLabel + "  |  Circular System Based  |  diameter: " + Or(cfg.Dia, "(none)") +
                           "  |  rod: " + Or(cfg.Rod, "(none)") + setup;
            }
            else
            {
                txt.Text = it.CatLabel + "  |  " + width + "  |  rod: " + Or(cfg.Rod, "(none)") + setup;
            }
            if (previews.ContainsKey(it.Key)) ShowPreview(previews[it.Key]);
            else
            {
                ShowPreview(null, "Loading...");
                RequestPreview(it);
            }
        }

        /// <summary>Python's "x or y" on strings.</summary>
        private static string Or(string a, string b)
        {
            return !string.IsNullOrEmpty(a) ? a : b;
        }

        // ---- preview (read through the ExternalEvent)
        public void RequestPreview(FamTypeItem it)
        {
            wantPreview = it.Key;
            string key = it.Key;
            if (OpenDoc != null)   // opening the tool: read it now, so the chosen family shows at once
            {
                byte[] data;
                try
                {
                    data = HfamRevit.PreviewBytes(OpenDoc, it.Id);
                }
                catch (Exception)
                {
                    data = null;
                }
                GotPreview(key, data);
                return;
            }
            bool started = O.StartQuiet(HfamRevit.PreviewJobFor(it.Id), (res, err) => GotPreview(key, res as byte[]));
            if (!started)   // Revit busy with another read: try again when it finishes (RetryPreview)
                ShowPreview(null, "Loading...");
        }

        /// <summary>A read has finished: fetch the chosen type's preview if it is still missing.</summary>
        public void RetryPreview()
        {
            FamTypeItem it = Current();
            if (it != null && !previews.ContainsKey(it.Key) && !O.Busy) RequestPreview(it);
        }

        private void GotPreview(string key, byte[] data)
        {
            previews[key] = data;
            FamTypeItem it = Current();
            if (it == null) return;
            if (it.Key == key) ShowPreview(data);
            else if (!previews.ContainsKey(it.Key)) RequestPreview(it);   // the selection moved on while we were reading
        }

        public void ShowPreview(byte[] data, string hint = "No preview")
        {
            var img = C<Image>("FamPreview");
            var lab = C<TextBlock>("FamPreviewHint");
            try
            {
                if (data != null && data.Length > 0)
                {
                    img.Source = FhaUi.BitmapFromBytes(data);
                    lab.Visibility = Visibility.Collapsed;
                }
                else
                {
                    img.Source = null;
                    lab.Text = hint;
                    lab.Visibility = Visibility.Visible;
                }
            }
            catch (Exception)
            {
            }
        }

        // ---- refresh
        private void RefreshClick(object sender, RoutedEventArgs e)
        {
            O.StartQuiet(HfamRevit.ListJob, GotList, "Reading families...");
        }

        private void GotList(object res, string err)
        {
            var list = res as List<FamTypeItem>;
            if (!string.IsNullOrEmpty(err) || list == null)
            {
                O.Status("Could not read the families - see Copy debug");
                return;
            }
            Items = list;
            previews = new Dictionary<string, byte[]>();
            Refill();
            O.Status(Items.Count + " " + Noun + " family types");
        }

        // ---- family settings
        private void SettingsClick(object sender, RoutedEventArgs e)
        {
            FamTypeItem it = Current();
            if (it == null)
            {
                O.Status("Choose a family and type first");
                return;
            }
            if (Params.ContainsKey(it.Family))
            {
                OpenSettings(it);
                return;
            }
            string fam = it.Family;
            Action<object, string> got = (res, err) =>
            {
                List<string> names;
                string source;
                if (!(res != null && string.IsNullOrEmpty(err) && ParamsResult(res, out names, out source)))
                {
                    names = new List<string>();
                    source = "nothing - see Copy debug";
                }
                Params[fam] = new FamParams(new List<string>(names), source);
                OpenSettings(it);
            };
            O.StartQuiet(HfamRevit.ParamsJobFor(it.Id), got, "Reading the family parameters...");
        }

        /// <summary>
        /// The quiet params job answers (names, source): read as a Tuple / ValueTuple pair (Item1, Item2) so the job's
        /// exact pair type does not matter here.
        /// </summary>
        private static bool ParamsResult(object res, out List<string> names, out string source)
        {
            names = null;
            source = null;
            var direct = res as HfamRevit.FamParamNames;
            if (direct != null)
            {
                names = direct.Names != null ? direct.Names.ToList() : new List<string>();
                source = direct.Source ?? "";
                return true;
            }
            try
            {
                Type t = res.GetType();
                object a = null, b = null;
                PropertyInfo p1 = t.GetProperty("Item1"), p2 = t.GetProperty("Item2");
                FieldInfo f1 = t.GetField("Item1"), f2 = t.GetField("Item2");
                if (p1 != null && p2 != null)
                {
                    a = p1.GetValue(res, null);
                    b = p2.GetValue(res, null);
                }
                else if (f1 != null && f2 != null)
                {
                    a = f1.GetValue(res);
                    b = f2.GetValue(res);
                }
                else
                {
                    return false;
                }
                var en = a as IEnumerable<string>;
                if (en == null) return false;
                names = en.ToList();
                source = b == null ? "" : b.ToString();
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public void OpenSettings(FamTypeItem it)
        {
            FamParams p;
            if (!Params.TryGetValue(it.Family, out p)) p = new FamParams(new List<string>(), "");
            try
            {
                var dlg = new FamSettingsDialog(O, it, CfgFor(it), p.Names, p.Source, Mode);
                if (dlg.Show())
                {
                    Fams = HfamCore.LoadFamilies();   // the other tab may have saved since
                    Fams[it.Family] = dlg.Result;
                    HfamCore.SaveFamilies(Fams);
                    O.FamilySettingsSaved(this);
                    O.Status("Settings saved for " + it.Family);
                    Refill();
                }
            }
            catch (Exception ex)
            {
                O.Status("Family settings failed: " + ex.Message);
            }
        }

        // ---- the three tools
        /// <summary>
        /// What a job needs from this tab. The floor tab hands its own flr_ settings over as the fam_ keys the jobs
        /// read, no drop rods, and _mode = "floor" so the jobs fit floor supports. The family and the families table
        /// ride on the settings object (FhaJobExtras: _fam, _fams).
        /// </summary>
        public void JobExtra(FhaSettings s)
        {
            if (Floor)
            {
                foreach (string key in s.Keys.ToList())
                {
                    string fk = FhaCore.FloorKey(key);
                    if (fk != key && s.ContainsKey(fk)) s[key] = s[fk];
                }
                foreach (string key in FhaCore.FloorSkip)
                    if (key.Contains("_rod_")) s[key] = "0";
            }
            s["_mode"] = Mode;
            s.Prompts = O.DimUi;   // asks where dimensions go from a 3D view
            FamTypeItem it = Current();
            HfamRevit.HfamChoice choice = null;
            if (it != null)
            {
                FamConfig cfg = CfgFor(it).Clone();
                cfg.Mode = Mode;
                choice = new HfamRevit.HfamChoice { Id = it.Id, Family = it.Family, Cfg = cfg };
            }
            var all = new Dictionary<string, FamConfig>(StringComparer.Ordinal);
            foreach (string f in Fams.Keys)
            {
                FamConfig c = HfamCore.FamConfigFor(Fams, f);
                c.Mode = Mode;
                all[f] = c;
            }
            HfamRevit.SetFamilies(s, choice, all);   // _fam / _fams
        }

        public void ReloadFamilies()
        {
            Fams = HfamCore.LoadFamilies();
            Refill();   // set-up families are shown in bold green
        }

        /// <summary>
        /// Start a tool. A floor support family saved as Circular System Based runs its own job (HcircRevit);
        /// everything else runs the job given.
        /// </summary>
        private void Run(FhaJob job, FhaJob circJob = null)
        {
            FamTypeItem it = Current();
            if (it == null)
            {
                O.Status("Choose a " + Noun + " family and type first");
                return;
            }
            if (!HfamCore.Configured(Fams, it.Family) && !ignored.Contains(it.Family))
            {
                string ans = AskSetup(it);
                if (ans == "setup")
                {
                    SettingsClick(null, null);
                    return;
                }
                if (ans != "ignore") return;
                ignored.Add(it.Family);   // not asked again this session
            }
            FamConfig cfg = CfgFor(it);
            if (Circular(cfg))
            {
                if (!(cfg.Dia.Length > 0 && (cfg.CircHeight.Length > 0 || !Floor)))
                {
                    O.Status("Set the diameter" + (Floor ? " and support height" : "") + " parameter" + (Floor ? "s" : "") +
                             " in Family settings first");
                    return;
                }
                O.StartJob(circJob, JobExtra);
                return;
            }
            else
            {
                if (!(cfg.Left.Length > 0 && cfg.Right.Length > 0))
                {
                    O.Status("Set the two width parameters in Family settings first");
                    return;
                }
                if (Floor && !(cfg.FirstBar.Length > 0 && cfg.Height.Length > 0))
                {
                    O.Status("Set the first bar and support height parameters in Family settings first");
                    return;
                }
            }
            O.StartJob(job, JobExtra);
        }

        /// <summary>A family never set up: "setup" (open Family settings), "ignore" or null.</summary>
        public string AskSetup(FamTypeItem it)
        {
            string style = Floor ? " - Rectangular Floor Based or Circular System Based -" :
                                   " - Rectangular Hanger System or Circular System Based -";
            return new Prompt(O, "Family settings", "Set up the family first",
                "\"" + it.Family + "\" has not been set up yet. Family settings tells the tool which of its parameters set the " +
                "width, height" + (Floor ? " and first bar" : " and drop rod") + " and the rest" + style +
                ". Ignore carries on with the parameters guessed from their names.",
                new[]
                {
                    new PromptButton("ignore", "Ignore and carry on", false),
                    new PromptButton("setup", "Set up the family", true),
                }).Show();
        }

        /// <summary>
        /// The chosen family is saved as Circular System Based (a floor support or, from 1.14.0, a hanger): it runs
        /// the circular jobs (HcircRevit).
        /// </summary>
        public bool Circular(FamConfig cfg)
        {
            if (cfg == null) cfg = new FamConfig();
            FamConfig c = cfg.Clone();
            c.Mode = Mode;
            return HcircCore.IsCirc(c);
        }

        private void PlaceClick(object sender, RoutedEventArgs e)
        {
            Run(HfamRevit.JobPlace, HcircRevit.JobPlace);
        }

        private void RealignClick(object sender, RoutedEventArgs e)
        {
            Run(HfamRevit.JobRealign, HcircRevit.JobRealign);
        }

        private void AutoClick(object sender, RoutedEventArgs e)
        {
            Run(HfamRevit.JobAuto, HcircRevit.JobAuto);
        }

        private void RodsClick(object sender, RoutedEventArgs e)
        {
            O.StartJob(HfamRevit.JobRods, JobExtra);
        }

        private void DimsClick(object sender, RoutedEventArgs e)
        {
            if (!ViewOk)
            {
                O.Status("Open a floor plan first");
                return;
            }
            O.StartJob(HcircRevit.JobDims, JobExtra);   // changes nothing for rectangular families
        }
    }
}
