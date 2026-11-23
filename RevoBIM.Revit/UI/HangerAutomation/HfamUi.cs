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

        /// <summary>The project's linear dimension type names, read once when the window opens.</summary>
        List<string> DimTypeNames { get; }

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
        public UIElement Root;   // what goes in the list (the symbol column and the text)

        public FamRow(TextBlock tb, bool setUp)
        {
            Tb = tb;
            SetUp = setUp;
        }
    }

    public sealed partial class FamTab
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
            "BtnFamSwap", "BtnFamRodCats", "BtnFamRodCatsPlace",
        };

        private static readonly string[] RodControls =
        {
            "ChkFamRodPlace", "ChkFamRodRealign", "ChkFamRodAuto", "ChkFamRodLinked", "BtnFamRods",
            "BtnFamSwap", "BtnFamRodCats", "BtnFamRodCatsPlace",   // the swap tool and the rod target buttons: Family Hangers only
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
                dims = owner.DimTypeNames;   // read once by the window
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
            string[] tools = Floor ? new[] { "Place", "Realign", "Auto", "Dims" } : new[] { "Place", "Realign", "Auto", "Swap", "Rods", "Dims" };
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
            if (!Floor)
            {
                C<ButtonBase>("BtnFamRods").Click += RodsClick;
                C<ButtonBase>("BtnFamSwap").Click += SwapClick;
                C<ButtonBase>("BtnFamRodCats").Click += RodCatsClick;
                C<ButtonBase>("BtnFamRodCatsPlace").Click += RodCatsClick;
            }
            C<ButtonBase>("BtnFamRules").Click += RulesClick;
        }
    }
}
