using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using RevoBIM.Tools.NumberSequencer;
using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using ComboBoxItem = System.Windows.Controls.ComboBoxItem;
using ContextMenu = System.Windows.Controls.ContextMenu;
using Grid = System.Windows.Controls.Grid;
using MenuItem = System.Windows.Controls.MenuItem;
using Path = System.Windows.Shapes.Path;
using TextBox = System.Windows.Controls.TextBox;
using Color = System.Windows.Media.Color;
using Point = System.Windows.Point;
using ViewKey = System.Tuple<string, long>;

namespace RevoBIM.UI.NumberSequencer
{
    /// <summary>What the shared options (parameter, format, tags) act on: the active tab's sequence.</summary>
    public class NumSource
    {
        public List<long> Order = new List<long>();
        public Func<long, bool> Include = k => true;
        public Dictionary<long, ElementId> IdMap = new Dictionary<long, ElementId>();
        public Dictionary<long, string> Labels = new Dictionary<long, string>();
        public Dictionary<long, string> HostCat = new Dictionary<long, string>();
        public Dictionary<string, string> Storages = new Dictionary<string, string>();
        public Dictionary<long, List<string>> PerElem = new Dictionary<long, List<string>>();
        public List<long> Keys = new List<long>();
        public int Total;
        public bool Has;
        public int Systems;
        public string Kind = "duct";
        public bool PlansOnly;
        public string ViewType = "";
        public string Verb = "Apply";
        public Func<UIApplication, int> After;
        public bool NeedsStart;
        public bool Started;
        public string EmptyHint = "Add a system to list its parameters";
    }

    public class SelState
    {
        public bool Loaded;
        public NetworkData Data;
        public List<SysDef> Systems = new List<SysDef>();
        public string Cur;
        public HashSet<string> Picked = new HashSet<string>();
        public string Anchor;
        public HashSet<long> LeftOut = new HashSet<long>();
        public List<long> Order = new List<long>();
        public List<KeyValuePair<int, int>> Spans = new List<KeyValuePair<int, int>>();
        public List<KeyValuePair<long?, string>> Starts = new List<KeyValuePair<long?, string>>();
        public Dictionary<long, string> TypeOf = new Dictionary<long, string>();
        public int ColourN;
        public FamilyTree Tree;
        public List<List<KeyValuePair<string, SysDef>>> Gone = new List<List<KeyValuePair<string, SysDef>>>();
        public List<string> Chain = new List<string>();
        public Dictionary<string, string> Groups = new Dictionary<string, string>();
        public Dictionary<string, string> Hues = new Dictionary<string, string>();
        public int GidN;
        public Dictionary<string, string> Shade = new Dictionary<string, string>();
        public bool ReorderDue;
    }

    public class SnapEntry
    {
        public ElementId ViewId;
        public Dictionary<long, KeyValuePair<ElementId, OverrideGraphicSettings>> Snap = new Dictionary<long, KeyValuePair<ElementId, OverrideGraphicSettings>>();
    }

    /// <summary>
    /// The System Selector tab (port of nsq_selector.py): every duct or pipe system in the active view in a table
    /// you put in order. That order is the numbering order: each system after the first starts at its open end
    /// nearest where the last one finished. Accessories are walked through but never numbered or selected.
    /// </summary>
    public class SelectorTab
    {
        private const string DragFormat = "RevoBIM.NumberSequencer.SystemRow";
        private const double DragMin = 6;
        private const double AutoScroll = 26;
        private const string GripData = "M0,0 L8,0 M0,4 L8,4 M0,8 L8,8";
        private const string Clear = "#00000000";
        private const string StepIso3d = "2.1", StepGroup = "2.2", StepPick = "2.3", StepAuto = "2.4";

        private class Col { public string Key, Head; public double Width; public bool Star; public double Min; }
        private static readonly Col[] Columns =
        {
            new Col { Key = "grip", Head = "", Width = 18 },
            new Col { Key = "num", Head = "#", Width = 30 },
            new Col { Key = "on", Head = "", Width = 24 },
            new Col { Key = "swatch", Head = "", Width = 24 },
            new Col { Key = "grp", Head = "Group", Width = 64 },
            new Col { Key = "name", Head = "System name", Width = 3, Star = true, Min = 110 },
            new Col { Key = "type", Head = "System type", Width = 2, Star = true, Min = 80 },
            new Col { Key = "abbr", Head = "Abbrev.", Width = 1, Star = true, Min = 46 },
            new Col { Key = "cls", Head = "Classification", Width = 2, Star = true, Min = 80 },
            new Col { Key = "count", Head = "Elements", Width = 70 },
            new Col { Key = "range", Head = "Numbers", Width = 100 },
        };

        // the window that Revit's selection / view events talk to
        private static SelectorTab _target;
        private static List<KeyValuePair<string, bool>> _hookedNames;
        private static UIApplication _hookedApp;

        private static void OnSelectionChanged(object sender, Autodesk.Revit.UI.Events.SelectionChangedEventArgs e)
        {
            try
            {
                SelectorTab t = _target;
                if (t == null) return;
                t.RevitSelectionChanged(e.GetSelectedElements().Select(NsqRevit.EidValue).ToList(), NsqRevit.DocKey(e.GetDocument()));
            }
            catch (Exception) { }
        }

        private static void OnViewActivated(object sender, ViewActivatedEventArgs e)
        {
            try
            {
                SelectorTab t = _target;
                if (t == null) return;
                View view = e.CurrentActiveView;
                t.ViewChanged(NsqRevit.DocKey(e.Document), view != null ? (long?)NsqRevit.EidValue(view.Id) : null);
            }
            catch (Exception) { }
        }

        public static void RemoveHooks(DebugLog log)
        {
            if (_hookedApp == null) return;
            try { _hookedApp.SelectionChanged -= OnSelectionChanged; } catch (Exception) { log.Add("could not unhook SelectionChanged"); }
            try { _hookedApp.ViewActivated -= OnViewActivated; } catch (Exception) { log.Add("could not unhook ViewActivated"); }
            _hookedApp = null;
            _hookedNames = null;
        }

        private bool InstallHooks(UIApplication uiapp, DebugLog log)
        {
            RemoveHooks(log);   // anything an earlier window left behind goes first
            var names = new List<KeyValuePair<string, bool>>();
            bool sel = false;
            try { uiapp.SelectionChanged += OnSelectionChanged; names.Add(new KeyValuePair<string, bool>("SelectionChanged", true)); sel = true; }
            catch (Exception) { log.Add("SelectionChanged not available - Remove from sequence reads the selection when pressed"); }
            try { uiapp.ViewActivated += OnViewActivated; names.Add(new KeyValuePair<string, bool>("ViewActivated", true)); }
            catch (Exception) { log.Add("ViewActivated not available - the view is checked when the window is activated"); }
            _hookedApp = uiapp;
            _hookedNames = names;
            log.Add("hooked: " + (names.Count > 0 ? string.Join(", ", names.Select(n => n.Key)) : "nothing"));
            return sel;
        }

        // windows closing: held until their tidy-up job has run
        private static readonly List<SequencerWindow> Closing = new List<SequencerWindow>();

        private readonly SequencerWindow _w;
        public string Kind;
        public HashSet<string> Skipped;
        private readonly Dictionary<string, SelState> _state = new Dictionary<string, SelState>();
        private readonly Dictionary<ViewKey, SnapEntry> _snapshots = new Dictionary<ViewKey, SnapEntry>();
        private readonly Dictionary<ViewKey, ElementId> _isoViews = new Dictionary<ViewKey, ElementId>();
        private readonly Dictionary<ViewKey, ElementId> _hideViews = new Dictionary<ViewKey, ElementId>();
        private readonly Dictionary<ViewKey, Tuple<ElementId, List<ElementId>>> _leftovers = new Dictionary<ViewKey, Tuple<ElementId, List<ElementId>>>();
        private readonly Dictionary<ViewKey, Tuple<ElementId, BoundingBoxXYZ>> _boxes = new Dictionary<ViewKey, Tuple<ElementId, BoundingBoxXYZ>>();
        private ViewKey _viewKey;
        private bool _isoOn, _colOn, _colAuto, _stale;
        private List<long> _userSel = new List<long>();
        private List<long> _viewSel = new List<long>();
        private HashSet<long> _ownSel;
        private bool _syncWanted, _syncQueued;
        private string _lastCol, _lastIso;
        private string _lastKey;
        private ViewKey _iso3d;
        private ElementId _iso3dId;
        private string _iso3dName = "";
        private bool _iso3dBusy, _col3d;
        private string _lastIso3d, _lastCol3d;
        private bool _filling3d;
        private int[] _drag;             // index, x, y
        private HashSet<int> _dragSet = new HashSet<int>();
        private bool _dragged, _skipUp;
        private readonly List<Tuple<Grid, Border, Border, Border>> _rows = new List<Tuple<Grid, Border, Border, Border>>();
        private readonly List<Tuple<SysDef, TextBlock>> _rangeCells = new List<Tuple<SysDef, TextBlock>>();
        private ContextMenu _menu;
        private MenuItem _menuTo, _menuTop, _menuNext, _menuClear, _menuGroup;
        private bool _selectionHooked;

        public SelectorTab(SequencerWindow w)
        {
            _w = w;
            Kind = NsqCore.Kinds.ContainsKey(w.Settings["sel_kind"]) ? w.Settings["sel_kind"] : "duct";
            Skipped = NsqCore.SkipKeysFrom(w.Settings["sel_skip"]);
            foreach (string k in NsqCore.Kinds.Keys)
            {
                var st = new SelState();
                st.Tree = new FamilyTree(_w.Ctl<StackPanel>("SelTreeHost"), _w.Ctl<TextBlock>("SelCountText"), _w.Ctl<TextBox>("SelSearchBox"),
                                         () => _w.Mode, Skipped, TreeChanged, SelectKeys);
                st.Tree.TryRun = _w.Try;
                _state[k] = st;
            }
            _w.Ctl<RadioButton>(Kind == "duct" ? "SelDuctTab" : "SelPipeTab").IsChecked = true;
            BuildHeader();
            BuildMenu();
            Fill3dCombo(new List<KeyValuePair<string, string>>());
            Wire();
            RefreshViewButtons();
            _target = this;
            _selectionHooked = InstallHooks(w.UiApp, w.Log);
        }

        private void On<T>(string name, Action fn) where T : ButtonBase
        {
            _w.Ctl<T>(name).Click += (s, e) => _w.Try(name, fn);
        }

        private void Wire()
        {
            _w.Ctl<RadioButton>("SelDuctTab").Checked += (s, e) => _w.Try("kind", OnKind);
            _w.Ctl<RadioButton>("SelPipeTab").Checked += (s, e) => _w.Try("kind", OnKind);
            On<Button>("SelRefreshBtn", () => Refresh());
            On<Button>("SelIsolateBtn", OnIsolate);
            On<Button>("SelColourBtn", OnColour);
            On<Button>("SelIso3DBtn", OnIso3d);
            _w.Ctl<ComboBox>("Sel3DCombo").SelectionChanged += (s, e) => _w.Try("3d choice", On3dChoice);
            On<Button>("SelRemoveBtn", OnRemove);
            On<Button>("SelRestoreBtn", OnRestore);
            On<Button>("SelUpBtn", () => { if (Shift()) MovePicked(-1); else Step(-1); });
            On<Button>("SelDownBtn", () => { if (Shift()) MovePicked(1); else Step(1); });
            On<Button>("SelTopBtn", () => MoveTo(PickedIdx(), 0));
            On<Button>("SelBottomBtn", () => MoveTo(PickedIdx(), Systems().Count));
            On<Button>("SelAutoOrderBtn", OnAutoOrder);
            On<Button>("SelAllOnBtn", () => { foreach (SysDef sd in Systems()) sd.On = true; Recompute(); });
            On<Button>("SelAllOffBtn", () => { foreach (SysDef sd in Systems()) sd.On = false; Recompute(); });
            On<Button>("SelPickStartBtn", PickStart);
            On<Button>("SelAutoBtn", () => AutoReorder(Shift()));
            On<Button>("SelGroupBtn", () => OnGroup(true));
            On<Button>("SelUngroupBtn", OnUngroup);
            On<Button>("SelGroupOrderBtn", OnGroupOrder);
            _w.Ctl<TextBox>("SelSearchBox").TextChanged += (s, e) => _w.Try("search", () => St().Tree.Build());
            On<Button>("SelExpandAllBtn", () => St().Tree.ExpandAll());
            On<Button>("SelCollapseAllBtn", () => St().Tree.CollapseAll());
            On<Button>("SelTickAllBtn", () => St().Tree.TickAll());
            On<Button>("SelUntickAllBtn", () => St().Tree.UntickAll());
            var scroll = _w.Ctl<ScrollViewer>("SelScroll");
            scroll.PreviewDragOver += (s, e) => _w.Try("scroll drag", () => OnScrollDrag(e));
            scroll.Drop += (s, e) => _w.Try("scroll drop", () => OnScrollDrop(e));
            _w.Win.PreviewKeyDown += (s, e) => _w.Try("key", () => OnKey(e));
        }

        public SelState St() { return _state[Kind]; }
        private List<SysDef> Systems() { return St().Systems; }

        private int? IndexOf(string key)
        {
            if (key == null) return null;
            var sys = Systems();
            for (int i = 0; i < sys.Count; i++) if (sys[i].Key == key) return i;
            return null;
        }

        private HashSet<int> PickedIdx()
        {
            SelState st = St();
            var idx = new HashSet<int>();
            for (int i = 0; i < st.Systems.Count; i++) if (st.Picked.Contains(st.Systems[i].Key)) idx.Add(i);
            if (idx.Count == 0 && IndexOf(st.Cur) != null) idx.Add(IndexOf(st.Cur).Value);
            return idx;
        }

        private int? CurIndex() { return IndexOf(St().Cur); }

        // ---------------------------------------------------- the active tab's numbering source

        public bool Include(long key)
        {
            SelState st = St();
            if (st.Data == null) return false;
            return NsqCore.SelInclude(key, st.Data.PassThrough, st.LeftOut, st.TypeOf, Skipped);
        }

        public List<SysDef> OnSystems() { return St().Systems.Where(sd => sd.On).ToList(); }

        public NumSource Source()
        {
            SelState st = St();
            NetworkData d = st.Data;
            var keys = OnSystems().SelectMany(sd => sd.Num).ToList();
            return new NumSource
            {
                Order = st.Order, Include = Include,
                IdMap = d != null ? d.IdMap : new Dictionary<long, ElementId>(),
                Labels = d != null ? d.Labels : new Dictionary<long, string>(),
                HostCat = d != null ? d.HostCat : new Dictionary<long, string>(),
                Storages = d != null ? d.Storages : new Dictionary<string, string>(),
                PerElem = d != null ? d.PerElem : new Dictionary<long, List<string>>(),
                Keys = keys, Total = keys.Count, Has = keys.Count > 0, Systems = OnSystems().Count, Kind = Kind, PlansOnly = true,
                ViewType = d != null ? d.ViewType : "", Verb = "Run", After = AfterRun, NeedsStart = true, Started = Started(),
                EmptyHint = "Tick a system to list its parameters",
            };
        }

        // ---------------------------------------------------- reading

        public void Activate()
        {
            if (!St().Loaded) Refresh();
            CheckView();
            Recompute();
        }

        private Func<UIApplication, object> ReadJob(string kind)
        {
            return uiapp =>
            {
                Document doc = uiapp.ActiveUIDocument.Document;
                View view = doc.ActiveView;
                var key = Tuple.Create(NsqRevit.DocKey(doc), NsqRevit.EidValue(view.Id));
                if (_isoViews.ContainsKey(key))
                {
                    // the tool's isolate stops the view's collector seeing the unticked systems: refreshing now would drop them
                    return new NetworkData { Kind = kind, SkippedIsolated = true };
                }
                NetworkData data = NsqRevit.ReadSelector(doc, view, kind, _w.Log);
                data.Isolated = NsqRevit.IsIsolated(view);
                data.Tags = NsqRevit.TagChoices(doc);
                data.Views3d = NsqRevit.Views3d(doc);
                HashSet<long> snap = _snapshots.ContainsKey(key) ? new HashSet<long>(_snapshots[key].Snap.Keys) : new HashSet<long>();
                data.Leftover = NsqRevit.ToolColoured(view, data.IdMap.Values.Where(i => !snap.Contains(NsqRevit.EidValue(i))));
                data.Kind = kind;
                data.DocKey = NsqRevit.DocKey(doc);
                return data;
            };
        }

        public void ReadNow(UIApplication uiapp)
        {
            try { Loaded(ReadJob(Kind)(uiapp), null); }
            catch (Exception ex) { _w.Log.Add("selector read failed: " + ex); }
        }

        public void Refresh()
        {
            string label = NsqCore.Kinds[Kind].Label.ToLowerInvariant();
            _w.QueueBusy("read " + Kind, ReadJob(Kind), Loaded, "Reading the " + label + " in the active view");
        }

        private void Loaded(object resObj, string err)
        {
            var res = resObj as NetworkData;
            if (err != null || res == null) { _w.Status("Could not read the systems - see debug"); return; }
            if (res.SkippedIsolated)
            {
                _w.Status("This view is isolated by the tool - reset its isolate, then Refresh (the isolate hides the unticked systems)");
                return;
            }
            SelState st = _state[res.Kind];
            var newKey = Tuple.Create(res.DocKey, NsqRevit.EidValue(res.ViewId));
            bool sameView = _viewKey == null || _viewKey.Equals(newKey);
            _viewKey = newKey;
            if (_iso3d != null && _iso3d.Item1 != res.DocKey) Iso3dOff();   // another project: its 3D view keeps the isolate until Reset or close
            Fill3dCombo(res.Views3d);
            if (res.Leftover.Count > 0) _leftovers[newKey] = Tuple.Create(res.ViewId, new List<ElementId>(res.Leftover));
            else _leftovers.Remove(newKey);
            // the same systems in another view keep their order, ticks and colours
            List<SysDef> old = st.Systems;
            List<SysDef> systems = old.Count > 0 ? NsqCore.MergeSystems(old, res.Systems) : res.Systems;
            var need = systems.Where(sd => string.IsNullOrEmpty(sd.Colour)).ToList();
            if (need.Count > 0)
            {
                var used = new HashSet<string>(systems.Where(sd => !string.IsNullOrEmpty(sd.Colour)).Select(sd => sd.Colour));
                List<string> pal = NsqCore.DistinctColours(st.ColourN + need.Count + used.Count);
                foreach (SysDef sd in need)
                {
                    while (used.Contains(pal[st.ColourN])) st.ColourN++;
                    sd.Colour = pal[st.ColourN];
                    used.Add(sd.Colour);
                    st.ColourN++;
                }
            }
            st.Data = res;
            st.Systems = systems;
            st.Loaded = true;
            st.TypeOf = res.Rows.ToDictionary(r => r.ElementKey, r => NsqCore.TypeKey(r.Category, r.Family, r.Type), null);
            st.LeftOut = new HashSet<long>(st.LeftOut.Where(res.Nodes.ContainsKey));
            st.Gone = new List<List<KeyValuePair<string, SysDef>>>();
            _lastKey = null;
            var keys = new HashSet<string>(systems.Select(sd => sd.Key));
            st.Picked = new HashSet<string>(st.Picked.Where(keys.Contains));
            if (st.Cur == null || !keys.Contains(st.Cur)) st.Cur = systems.Count > 0 ? systems[0].Key : null;
            st.Tree.SetRows(new List<NsqCore.TreeRow>(), 0, old.Count == 0);
            if (!sameView)
            {
                // a new view starts plain: the old view keeps its isolate and colours until the window closes or Clear is pressed
                _isoOn = false; _colOn = false; _colAuto = false; _lastIso = null; _lastCol = null;
            }
            _stale = false;
            _w.Tags = res.Tags;
            if (res.Kind == Kind) Recompute();
            RefreshViewButtons();
            _w.Status(systems.Count + " " + NsqCore.Kinds[res.Kind].Label.ToLowerInvariant() + " in " + res.ViewName + " (" + res.ViewType + ")" +
                      (res.Isolated ? " - read from an isolated view, only what it shows" : "") +
                      (res.Leftover.Count > 0 ? " - " + res.Leftover.Count + " elements still coloured from before: Clear colours takes it off" : ""));
        }

        // ---------------------------------------------------- the view changing under the window

        private ViewKey KindViewKey()
        {
            NetworkData d = St().Data;
            return d == null ? null : Tuple.Create(d.DocKey, NsqRevit.EidValue(d.ViewId));
        }

        public void ViewChanged(string docKey, long? viewValue)
        {
            if (_viewKey == null || viewValue == null) return;
            var here = Tuple.Create(docKey, viewValue.Value);
            ViewKey kv = KindViewKey();
            // stale when Revit moved on, or this kind was read in another view - never in the 3D view Isolate in 3D opened
            bool stale = !here.Equals(_viewKey) || (kv != null && !kv.Equals(here));
            if (_iso3d != null && here.Equals(_iso3d)) stale = false;
            if (_iso3d != null && here.Equals(_viewKey) && (_isoOn || _colOn)) RequestSync();
            if (stale != _stale)
            {
                _stale = stale;
                RefreshViewButtons();
                if (stale) _w.Status("The active view changed - Refresh from view to read its systems");
            }
        }

        public void CheckView()
        {
            try
            {
                UIDocument uidoc = _w.UiApp.ActiveUIDocument;
                ViewChanged(NsqRevit.DocKey(uidoc.Document), NsqRevit.EidValue(uidoc.ActiveView.Id));
            }
            catch (Exception) { }
        }

        public void RevitSelectionChanged(List<long> idValues, string docKey)
        {
            NetworkData d = St().Data;
            if (d == null || docKey != d.DocKey) return;
            bool own = _ownSel != null && new HashSet<long>(idValues).SetEquals(_ownSel);
            var keys = OnSystems().SelectMany(sd => sd.Num).Where(Include).ToList();
            _userSel = NsqCore.UserSelection(idValues, _ownSel, keys);
            _viewSel = own ? new List<long>() : new List<long>(idValues);
            if (idValues.Count > 0 && !own) FollowSelection(idValues);
            RefreshViewButtons();
            RefreshGroupButtons();
        }

        /// <summary>An element picked in the view: select its system's row, scroll to it, leave the Revit selection as the user made it.</summary>
        private void FollowSelection(List<long> idValues)
        {
            List<int> hits = NsqCore.SystemsHolding(Systems(), idValues);
            if (hits.Count == 0)
            {
                string other = Kind == "duct" ? "pipe" : "duct";
                SelState ost = _state[other];
                if (ost.Data == null || NsqCore.SystemsHolding(ost.Systems, idValues).Count == 0) return;
                _w.Ctl<RadioButton>(other == "pipe" ? "SelPipeTab" : "SelDuctTab").IsChecked = true;   // runs OnKind
                hits = NsqCore.SystemsHolding(Systems(), idValues);
                if (hits.Count == 0) return;
            }
            SelState st = St();
            st.Picked = new HashSet<string>(hits.Select(i => st.Systems[i].Key));
            st.Cur = st.Systems[hits[0]].Key;
            st.Anchor = st.Cur;
            PaintRows();
            BringIntoView(hits[0]);
            RefreshOrderButtons();
            _w.RefreshStart();
            var on = OnSystems();
            SysDef sd = st.Systems[hits[0]];
            string where = on.Contains(sd) ? "system " + (on.IndexOf(sd) + 1) : "unticked";
            _w.Status("Picked in the view: " + sd.Name + " (" + where + ")" + (hits.Count > 1 ? " and " + (hits.Count - 1) + " more" : ""));
        }

        // ---------------------------------------------------- order

        public void Recompute()
        {
            SelState st = St();
            NetworkData d = st.Data;
            List<KeyValuePair<string, SysDef>> gone;
            st.Systems = NsqCore.SplitGone(st.Systems, st.LeftOut, out gone);
            if (gone.Count > 0)
            {
                st.Gone.Add(gone);
                _w.Log.Add(gone.Count + " system(s) fully removed, off the list: " + string.Join(", ", gone.Select(g => g.Value.Name)));
                var keys = new HashSet<string>(st.Systems.Select(sd => sd.Key));
                st.Picked = new HashSet<string>(st.Picked.Where(keys.Contains));
                if (st.Cur == null || !keys.Contains(st.Cur)) st.Cur = st.Systems.Count > 0 ? st.Systems[0].Key : null;
            }
            Regroup();
            if (d == null)
            {
                st.Order = new List<long>(); st.Spans = new List<KeyValuePair<int, int>>(); st.Starts = new List<KeyValuePair<long?, string>>();
            }
            else
            {
                st.Order = NsqCore.SelectorOrder(d.Nodes, OnSystems(), Include, out st.Spans, out st.Starts);
                _w.Log.Add("selector walk: " + st.Order.Count + " elements over " + OnSystems().Count + " ticked system(s)");
            }
            Rebuild();
            _w.SelChanged();
            if (_isoOn || _colOn || _iso3d != null) RequestSync();
        }

        /// <summary>Table, tree and labels for the active kind.</summary>
        public void Rebuild()
        {
            SelState st = St();
            NetworkData d = st.Data;
            BuildRows();
            FamilyTree tree = st.Tree;
            if (d != null)
            {
                var keep = new HashSet<long>(OnSystems().SelectMany(sd => sd.Num));
                tree.SetRows(d.Rows.Where(r => keep.Contains(r.ElementKey)), keep.Count);
            }
            tree.Build();
            if (d == null) _w.Ctl<TextBlock>("SelViewText").Text = "Not read yet - Refresh from view";
            else
            {
                int outCount = st.LeftOut.Count;
                _w.Ctl<TextBlock>("SelViewText").Text = "View: " + d.ViewName + " (" + d.ViewType + ")  |  " + st.Systems.Count + " systems, " +
                    OnSystems().Count + " ticked" + (outCount > 0 ? ", " + outCount + " removed" : "") + "  |  " +
                    "Ctrl / Shift + click to select several, Up / Down to step, Shift + Up / Down or drag to re-order";
            }
            RefreshOrderButtons();
            RefreshViewButtons();
        }

        private void OnKind()
        {
            string kind = _w.Ctl<RadioButton>("SelPipeTab").IsChecked == true ? "pipe" : "duct";
            if (kind == Kind) return;
            Kind = kind;
            _w.Settings["sel_kind"] = kind;
            _w.Save();
            _userSel = new List<long>();
            _lastCol = null; _lastIso = null; _lastCol3d = null; _lastIso3d = null; _lastKey = null;
            if (!St().Loaded) Refresh();
            CheckView();
            Recompute();
        }

        // ---------------------------------------------------- the table

        private void ColumnsFor(Grid grid)
        {
            foreach (Col c in Columns)
            {
                var cd = new ColumnDefinition();
                if (c.Star) { cd.Width = new GridLength(c.Width, GridUnitType.Star); cd.MinWidth = c.Min; }
                else cd.Width = new GridLength(c.Width);
                grid.ColumnDefinitions.Add(cd);
            }
        }

        private TextBlock CellText(Grid grid, int col, string text, bool muted = false, bool bold = false)
        {
            var tb = new TextBlock
            {
                Text = text ?? "", Margin = new Thickness(4, 0, 6, 0), VerticalAlignment = VerticalAlignment.Center,
                TextTrimming = TextTrimming.CharacterEllipsis,
            };
            if (!string.IsNullOrEmpty(text)) tb.ToolTip = text;
            tb.SetResourceReference(TextBlock.ForegroundProperty, muted ? "Muted" : "Text");
            if (bold) tb.FontWeight = FontWeights.SemiBold;
            Grid.SetColumn(tb, col);
            grid.Children.Add(tb);
            return tb;
        }

        private void BuildHeader()
        {
            var grid = new Grid();
            ColumnsFor(grid);
            for (int i = 0; i < Columns.Length; i++)
                if (Columns[i].Head.Length > 0) CellText(grid, i, Columns[i].Head, true, true).FontSize = 11;
            _w.Ctl<Border>("SelHeaderHost").Child = grid;
        }

        private static Border Line(bool top)
        {
            var ln = new Border
            {
                Height = 3, CornerRadius = new CornerRadius(1.5),
                Margin = top ? new Thickness(2, -2, 2, 0) : new Thickness(2, 0, 2, -2),
                VerticalAlignment = top ? VerticalAlignment.Top : VerticalAlignment.Bottom,
                IsHitTestVisible = false,
            };
            ln.SetResourceReference(Border.BackgroundProperty, "Blue");
            NsqUi.Show(ln, false);
            return ln;
        }

        private void BuildRows()
        {
            var host = _w.Ctl<StackPanel>("SelRows");
            host.Children.Clear();
            _rows.Clear();
            _rangeCells.Clear();
            SelState st = St();
            if (st.Systems.Count == 0)
            {
                var tb = new TextBlock
                {
                    Margin = new Thickness(8),
                    Text = st.Loaded ? "No " + NsqCore.Kinds[Kind].Label.ToLowerInvariant() + " in the active view" : "Not read yet - Refresh from view",
                };
                tb.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
                host.Children.Add(tb);
                return;
            }
            HashSet<long> starts = NsqCore.StartKeys(st.Order, OnSystems());
            var groups = st.Groups;
            var shade = st.Shade;
            int onIndex = 0;
            string prevGid = null;
            for (int i = 0; i < st.Systems.Count; i++)
            {
                SysDef sd = st.Systems[i];
                int idx = i;
                string gid;
                groups.TryGetValue(sd.Key, out gid);
                var holder = new Grid { AllowDrop = true };
                int gap = i > 0 && gid != prevGid && (gid != null || prevGid != null) ? 5 : 0;
                prevGid = gid;
                holder.Background = NsqUi.Brush(Clear);
                var row = new Border { Padding = new Thickness(0, 3, 0, 3), CornerRadius = new CornerRadius(3), Background = NsqUi.Brush(Clear), Cursor = Cursors.Hand };
                var grid = new Grid();
                ColumnsFor(grid);

                var grip = new Path
                {
                    Data = Geometry.Parse(GripData), StrokeThickness = 1.4, VerticalAlignment = VerticalAlignment.Center,
                    HorizontalAlignment = HorizontalAlignment.Center, Cursor = Cursors.SizeNS,
                    ToolTip = "Drag to re-order (drags every selected system)",
                };
                grip.SetResourceReference(Shape.StrokeProperty, "Muted");
                Grid.SetColumn(grip, 0);
                grid.Children.Add(grip);

                var badge = new Border { Width = 22, Height = 20, CornerRadius = new CornerRadius(10) };
                var num = new TextBlock { FontSize = 11, FontWeight = FontWeights.SemiBold, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
                if (sd.On)
                {
                    onIndex++;
                    num.Text = onIndex.ToString();
                    badge.SetResourceReference(Border.BackgroundProperty, "Orange");
                    num.SetResourceReference(TextBlock.ForegroundProperty, "OnAccent");
                }
                else
                {
                    num.Text = "-";
                    badge.SetResourceReference(Border.BackgroundProperty, "Edge");
                    num.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
                }
                badge.Child = num;
                Grid.SetColumn(badge, 1);
                grid.Children.Add(badge);

                var cb = new CheckBox { IsChecked = sd.On, ToolTip = "Include in the sequence (applies to every selected system)", HorizontalAlignment = HorizontalAlignment.Center };
                cb.Click += (s, e) => _w.Try("tick system", () => Tick(idx, cb));
                Grid.SetColumn(cb, 2);
                grid.Children.Add(cb);

                string colour;
                if (!shade.TryGetValue(sd.Key, out colour) || string.IsNullOrEmpty(colour)) colour = sd.Colour;
                var sw = new Border
                {
                    Width = 16, Height = 16, CornerRadius = new CornerRadius(3), Background = NsqUi.Brush(colour), BorderThickness = new Thickness(1),
                    ToolTip = "Colour used by Colour systems: " + colour + (gid != null ? " - its group's shade for its place, darkest first" : ""),
                };
                sw.SetResourceReference(Border.BorderBrushProperty, "Edge");
                Grid.SetColumn(sw, 3);
                grid.Children.Add(sw);

                if (gid != null)
                {
                    var cell = new Grid();
                    string hue;
                    var bar = new Border
                    {
                        Width = 4, Margin = new Thickness(0, 1, 0, 1), HorizontalAlignment = HorizontalAlignment.Left,
                        Background = NsqUi.Brush(st.Hues.TryGetValue(gid, out hue) && hue != null ? hue : colour), CornerRadius = new CornerRadius(2),
                    };
                    cell.Children.Add(bar);
                    var chip = new Border
                    {
                        CornerRadius = new CornerRadius(3), Padding = new Thickness(5, 1, 5, 1), Margin = new Thickness(7, 0, 2, 0),
                        HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Center,
                    };
                    chip.SetResourceReference(Border.BackgroundProperty, "Edge");
                    var gt = new TextBlock { FontSize = 11, Text = NsqCore.GroupLabel(groups, sd.Key, st.Systems) };
                    gt.SetResourceReference(TextBlock.ForegroundProperty, "Text");
                    chip.Child = gt;
                    cell.Children.Add(chip);
                    cell.ToolTip = "Group " + gid + ": numbered as one block. Drag a system out to take it out of the group.";
                    Grid.SetColumn(cell, 4);
                    grid.Children.Add(cell);
                }

                string name = sd.Name;
                if (sd.Keys.Any(starts.Contains) && sd.On) name += "   (start)";
                CellText(grid, 5, name, !sd.On, sd.On);
                CellText(grid, 6, sd.Type, true);
                CellText(grid, 7, sd.Abbr, true);
                CellText(grid, 8, sd.Cls, true);
                int outN = sd.Num.Count(k => st.LeftOut.Contains(k));
                CellText(grid, 9, sd.Num.Count + (outN > 0 ? " (-" + outN + ")" : ""), true);
                TextBlock rng = CellText(grid, 10, sd.On ? "" : "off");
                rng.SetResourceReference(TextBlock.ForegroundProperty, "Blue");

                row.Margin = new Thickness(0, gap, 0, 1);
                row.Child = grid;
                Border top = Line(true), bottom = Line(false);
                holder.Children.Add(row);
                holder.Children.Add(top);
                holder.Children.Add(bottom);
                holder.ToolTip = "Click: select in Revit.  Ctrl / Shift + click: several.  Double-click: zoom.  Drag: re-order.";
                holder.PreviewMouseLeftButtonDown += (s, e) => _w.Try("row down", () => RowDown(idx, e));
                holder.PreviewMouseMove += (s, e) => _w.Try("row move", () => RowMove(idx, e));
                holder.MouseLeftButtonUp += (s, e) => _w.Try("row up", () => RowUp(idx, e));
                holder.DragOver += (s, e) => _w.Try("row drag", () => RowDragOver(idx, e));
                holder.DragLeave += (s, e) => _w.Try("row leave", () => { var r = _rows[idx]; NsqUi.Show(r.Item3, false); NsqUi.Show(r.Item4, false); });
                holder.Drop += (s, e) => _w.Try("row drop", () => RowDrop(idx, e));
                holder.PreviewMouseRightButtonDown += (s, e) => _w.Try("row right", () => { if (!PickedIdx().Contains(idx)) ClickRow(idx); });
                holder.ContextMenu = _menu;
                host.Children.Add(holder);
                _rows.Add(Tuple.Create(holder, row, top, bottom));
                _rangeCells.Add(Tuple.Create(sd, rng));
            }
            PaintRows();
        }

        private void PaintRows()
        {
            HashSet<int> picked = PickedIdx();
            int? cur = CurIndex();
            for (int i = 0; i < _rows.Count; i++)
            {
                Border row = _rows[i].Item2;
                if (picked.Contains(i)) row.SetResourceReference(Border.BackgroundProperty, "Sel");
                else row.Background = NsqUi.Brush(Clear);
                row.BorderThickness = new Thickness(3, 0, 0, 0);
                if (cur != null && i == cur.Value) row.SetResourceReference(Border.BorderBrushProperty, "Blue");
                else row.BorderBrush = NsqUi.Brush(Clear);
            }
        }

        public void RefreshRanges(List<NsqCore.PlanItem> plan)
        {
            SelState st = St();
            var on = _rangeCells.Where(c => c.Item1.On).Select(c => c.Item1).ToList();
            var orderLists = st.Spans.Select(sp => st.Order.Skip(sp.Key).Take(sp.Value - sp.Key).ToList()).ToList();
            List<string[]> ranges = NsqCore.SystemRanges(plan ?? new List<NsqCore.PlanItem>(), orderLists);
            var bySys = new Dictionary<SysDef, string[]>();
            for (int i = 0; i < on.Count && i < ranges.Count; i++) bySys[on[i]] = ranges[i];
            foreach (var c in _rangeCells)
            {
                if (!c.Item1.On) { c.Item2.Text = "off"; continue; }
                string[] r;
                if (!bySys.TryGetValue(c.Item1, out r) || r == null) { c.Item2.Text = "none"; continue; }
                c.Item2.Text = r[0] == r[1] ? r[0] : r[0] + " - " + r[1];
            }
        }

        // ---------------------------------------------------- selecting rows

        private static void Mods(out bool ctrl, out bool shift)
        {
            ModifierKeys m = Keyboard.Modifiers;
            ctrl = (m & ModifierKeys.Control) == ModifierKeys.Control;
            shift = (m & ModifierKeys.Shift) == ModifierKeys.Shift;
        }

        private static bool Shift() { bool c, s; Mods(out c, out s); return s; }

        private void ClickRow(int index, bool ctrl = false, bool shift = false, bool zoom = false)
        {
            SelState st = St();
            var systems = st.Systems;
            if (index < 0 || index >= systems.Count) return;
            int? na;
            HashSet<int> nw = NsqCore.ClickSelection(PickedIdx(), IndexOf(st.Anchor), index, ctrl, shift, out na);
            st.Picked = new HashSet<string>(nw.Select(i => systems[i].Key));
            st.Anchor = na != null ? systems[na.Value].Key : null;
            st.Cur = systems[index].Key;
            AfterPick(zoom);
        }

        private void AfterPick(bool zoom = false)
        {
            PaintRows();
            BringIntoView(CurIndex());
            SelectPicked(zoom);
            RefreshOrderButtons();
            _w.RefreshStart();
        }

        private void SelectPicked(bool zoom)
        {
            SelState st = St();
            if (st.Data == null) return;
            var idmap = st.Data.IdMap;
            var picked = PickedIdx().OrderBy(i => i).Select(i => st.Systems[i]).ToList();
            var keys = picked.SelectMany(sd => sd.Num).Where(idmap.ContainsKey).ToList();
            _ownSel = new HashSet<long>(keys);
            _userSel = new List<long>();
            _viewSel = new List<long>();
            RefreshViewButtons();
            RefreshGroupButtons();
            _w.SelectIds(keys.Select(k => idmap[k]).ToList(), zoom);
            if (picked.Count == 1) _w.Status(picked[0].Name + ": " + keys.Count + " elements selected in Revit");
            else if (picked.Count > 0) _w.Status(picked.Count + " systems, " + keys.Count + " elements selected in Revit");
        }

        private void SelectKeys(List<long> keys)
        {
            var idmap = St().Data != null ? St().Data.IdMap : new Dictionary<long, ElementId>();
            _ownSel = new HashSet<long>(keys.Where(idmap.ContainsKey));
            _w.SelectIds(keys.Where(idmap.ContainsKey).Select(k => idmap[k]).ToList(), true);
        }

        private void BringIntoView(int? index)
        {
            if (index != null && index.Value >= 0 && index.Value < _rows.Count)
            {
                try { _rows[index.Value].Item1.BringIntoView(); } catch (Exception) { }
            }
        }

        private void Step(int delta)
        {
            SelState st = St();
            int? i = NsqCore.StepIndex(st.Systems.Count, CurIndex(), delta);
            if (i == null) return;
            string key = st.Systems[i.Value].Key;
            st.Cur = key; st.Anchor = key; st.Picked = new HashSet<string> { key };
            AfterPick();
        }

        private void OnKey(KeyEventArgs e)
        {
            if (_w.Tab != "sel" || (e.Key != Key.Up && e.Key != Key.Down)) return;
            object focused = Keyboard.FocusedElement;
            if (focused is TextBox || focused is ComboBox || focused is ComboBoxItem) return;
            if (_w.Ctl<System.Windows.Controls.Primitives.Popup>("ParamPopup").IsOpen || _w.Ctl<ComboBox>("TagCombo").IsDropDownOpen) return;
            if (Systems().Count == 0) return;
            int delta = e.Key == Key.Up ? -1 : 1;
            if (Shift()) MovePicked(delta); else Step(delta);
            e.Handled = true;
        }

        // ---------------------------------------------------- row mouse

        private static bool InCheckbox(object source)
        {
            DependencyObject node = source as DependencyObject;
            for (int i = 0; i < 12; i++)
            {
                if (node == null) return false;
                if (node is CheckBox) return true;
                try { node = VisualTreeHelper.GetParent(node); } catch (Exception) { return false; }
            }
            return false;
        }

        private void RowDown(int index, MouseButtonEventArgs e)
        {
            if (InCheckbox(e.OriginalSource)) { _drag = null; return; }   // the tick box handles its own press
            try { _w.Ctl<ScrollViewer>("SelScroll").Focus(); } catch (Exception) { }
            if (e.ClickCount == 2)
            {
                ClickRow(index, false, false, true);
                _drag = null;
                _skipUp = true;   // the button-up after a double-click must not undo the zoom
                e.Handled = true;
                return;
            }
            Point p = e.GetPosition(_w.Ctl<StackPanel>("SelRows"));
            _drag = new[] { index, (int)p.X, (int)p.Y };
            _dragged = false;
        }

        private void RowUp(int index, MouseButtonEventArgs e)
        {
            if (_dragged || _skipUp) { _dragged = false; _skipUp = false; return; }
            _drag = null;
            bool ctrl, shift;
            Mods(out ctrl, out shift);
            ClickRow(index, ctrl, shift);
        }

        private void RowMove(int index, MouseEventArgs e)
        {
            if (_drag == null || _drag[0] != index) return;
            if (e.LeftButton != MouseButtonState.Pressed) { _drag = null; return; }
            Point p = e.GetPosition(_w.Ctl<StackPanel>("SelRows"));
            if (Math.Abs(p.Y - _drag[2]) < DragMin && Math.Abs(p.X - _drag[1]) < DragMin) return;
            _dragged = true;
            _drag = null;
            HashSet<int> picked = PickedIdx();
            _dragSet = picked.Contains(index) ? picked : new HashSet<int> { index };
            foreach (int i in _dragSet) if (i < _rows.Count) _rows[i].Item2.Opacity = 0.45;
            try { DragDrop.DoDragDrop(_rows[index].Item1, new DataObject(DragFormat, "rows"), DragDropEffects.Move); }
            finally
            {
                foreach (var r in _rows) { r.Item2.Opacity = 1.0; NsqUi.Show(r.Item3, false); NsqUi.Show(r.Item4, false); }
            }
        }

        private bool Below(int index, DragEventArgs e)
        {
            Grid holder = _rows[index].Item1;
            return e.GetPosition(holder).Y > holder.ActualHeight / 2.0;
        }

        private void RowDragOver(int index, DragEventArgs e)
        {
            if (!e.Data.GetDataPresent(DragFormat)) { e.Effects = DragDropEffects.None; e.Handled = true; return; }
            bool below = Below(index, e);
            for (int i = 0; i < _rows.Count; i++)
            {
                NsqUi.Show(_rows[i].Item3, i == index && !below);
                NsqUi.Show(_rows[i].Item4, i == index && below);
            }
            e.Effects = DragDropEffects.Move;
            e.Handled = true;
        }

        private void RowDrop(int index, DragEventArgs e)
        {
            e.Handled = true;
            if (!e.Data.GetDataPresent(DragFormat)) return;
            int before = NsqCore.DropBefore(index, Below(index, e));
            var moving = new HashSet<int>(_dragSet);
            Later(() => MoveTo(moving, before));   // rebuild after the drop event has finished with this row
        }

        private void OnScrollDrag(DragEventArgs e)
        {
            if (!e.Data.GetDataPresent(DragFormat)) return;
            var sv = _w.Ctl<ScrollViewer>("SelScroll");
            double y = e.GetPosition(sv).Y;
            if (y < AutoScroll) sv.LineUp();
            else if (y > sv.ActualHeight - AutoScroll) sv.LineDown();
        }

        private void OnScrollDrop(DragEventArgs e)
        {
            if (e.Handled || !e.Data.GetDataPresent(DragFormat)) return;
            e.Handled = true;
            var moving = new HashSet<int>(_dragSet);
            Later(() => MoveTo(moving, Systems().Count));
        }

        private void Tick(int index, CheckBox cb)
        {
            bool on = cb.IsChecked == true;
            HashSet<int> picked = PickedIdx();
            HashSet<int> targets = picked.Contains(index) ? picked : new HashSet<int> { index };
            foreach (int i in targets) Systems()[i].On = on;
            Later(Recompute);
        }

        private void Later(Action fn)
        {
            _w.Ctl<StackPanel>("SelRows").Dispatcher.BeginInvoke(new Action(() => _w.Try("deferred step", fn)));
        }

        // ---------------------------------------------------- re-ordering

        private void NotePlace(HashSet<int> nw)
        {
            if (nw.Count > 0) _lastKey = St().Systems[nw.Max()].Key;
        }

        /// <summary>(list index to insert at, the # it gives) straight after the last system moved, or null.</summary>
        private Tuple<int, int> NextPlace()
        {
            int? i0 = IndexOf(_lastKey);
            if (i0 == null) return null;
            int i = i0.Value;
            foreach (string k in UnitKeys(_lastKey)) { int? j = IndexOf(k); if (j != null && j.Value > i) i = j.Value; }
            SysDef sd = Systems()[i];
            return Tuple.Create(i + 1, NsqCore.PositionOf(Systems(), i, Counted, new[] { sd }) + 1);
        }

        private bool Counted(SysDef sd) { return sd.On; }

        private List<string> GoneKeys() { return St().Gone.SelectMany(b => b).Select(p => p.Value.Key).ToList(); }

        /// <summary>After a drag or a move to a place: tidy the groups. Returns left, joined, new indexes.</summary>
        private void Moved(HashSet<int> nw, out List<string> left, out List<string> joined, out HashSet<int> newIdx)
        {
            SelState st = St();
            var before = new Dictionary<string, string>(st.Groups);
            var moved = nw.Where(i => i >= 0 && i < st.Systems.Count).Select(i => st.Systems[i].Key).ToList();
            Dictionary<string, string> ng;
            st.Systems = NsqCore.TidyGroups(st.Systems, st.Groups, moved, out ng, GoneKeys());
            st.Groups = ng;
            var movedSet = new HashSet<string>(moved);
            newIdx = new HashSet<int>();
            for (int i = 0; i < st.Systems.Count; i++) if (movedSet.Contains(st.Systems[i].Key)) newIdx.Add(i);
            left = before.Keys.Where(k => !st.Groups.ContainsKey(k)).ToList();
            joined = st.Groups.Keys.Where(k => { string b; return !before.TryGetValue(k, out b) || b != st.Groups[k]; }).ToList();
            NotePlace(newIdx);
        }

        private string GroupNote(List<string> left, List<string> joined)
        {
            var bits = new List<string>();
            if (joined.Count > 0) bits.Add("joined " + St().Groups[joined[0]]);
            if (left.Count > 0) bits.Add(left.Count > 1 ? left.Count + " left a group" : "left its group");
            return bits.Count > 0 ? " - " + string.Join(", ", bits) : "";
        }

        private void MoveTo(IEnumerable<int> moving, int before)
        {
            SelState st = St();
            HashSet<int> nw;
            st.Systems = NsqCore.MoveMany(st.Systems, moving, before, out nw);
            List<string> left, joined; HashSet<int> ni;
            Moved(nw, out left, out joined, out ni);
            string note = GroupNote(left, joined);
            Recompute();
            BringIntoView(CurIndex());
            if (note.Length > 0) _w.Status("Moved" + note);
        }

        /// <summary>Shift+Up / Down: inside a group a member steps within it; otherwise systems and groups step over whole parts.</summary>
        private void MovePicked(int delta)
        {
            SelState st = St();
            var before = new Dictionary<string, string>(st.Groups);
            Dictionary<string, string> ng; HashSet<int> nw;
            st.Systems = NsqCore.StepUnits(st.Systems, st.Groups, PickedIdx(), delta, out ng, out nw, GoneKeys());
            st.Groups = ng;
            NotePlace(nw);
            string note = GroupNote(before.Keys.Where(k => !st.Groups.ContainsKey(k)).ToList(), new List<string>());
            Recompute();
            BringIntoView(CurIndex());
            if (note.Length > 0) _w.Status("Moved" + note);
        }

        private void MovePosition(int position)
        {
            SelState st = St();
            HashSet<int> picked = PickedIdx();
            if (picked.Count == 0) return;
            var names = picked.OrderBy(i => i).Select(i => st.Systems[i].Name).ToList();
            HashSet<int> nw; int last;
            st.Systems = NsqCore.MoveToPosition(st.Systems, picked, position, Counted, out nw, out last);
            List<string> left, joined; HashSet<int> ni;
            Moved(nw, out left, out joined, out ni);
            Recompute();
            MovedStatus(names, ni);
        }

        private void MovedStatus(List<string> names, HashSet<int> nw)
        {
            BringIntoView(CurIndex());
            SelState st = St();
            if (nw.Count == 0) return;
            int first = nw.Min();
            if (first >= st.Systems.Count) return;
            int at = NsqCore.PositionOf(st.Systems, first, Counted, new[] { st.Systems[first] });
            Tuple<int, int> nxt = NextPlace();
            _w.Status("Moved " + (names.Count == 1 ? names[0] : names.Count + " systems") + " to #" + at +
                      (nxt != null ? " - Move to next goes to #" + nxt.Item2 : ""));
        }

        // ---------------------------------------------------- right-click menu

        private void BuildMenu()
        {
            var menu = new ContextMenu();
            NsqUi.MergeTheme(menu);
            NsqUi.ApplyPalette(menu, _w.Mode);
            _menuTo = new MenuItem(); _menuTop = new MenuItem(); _menuNext = new MenuItem(); _menuClear = new MenuItem(); _menuGroup = new MenuItem();
            var defs = new[]
            {
                Tuple.Create(_menuTo, "order", "Move to...", (Action)OnMenuTo),
                Tuple.Create(_menuTop, "top", "Move to top", (Action)(() => MovePosition(1))),
                Tuple.Create(_menuNext, "down", "Move to next", (Action)OnMenuNext),
                Tuple.Create(_menuGroup, "group", "Select its group", (Action)OnMenuGroup),
                Tuple.Create(_menuClear, "remove", "Clear picked start", (Action)AutoStart),
            };
            foreach (var d in defs)
            {
                d.Item1.Header = d.Item3;
                d.Item1.Icon = NsqUi.Icon(d.Item2);
                Action fn = d.Item4;
                d.Item1.Click += (s, e) => _w.Try("menu", fn);
                menu.Items.Add(d.Item1);
            }
            menu.Opened += (s, e) => _w.Try("menu opened", OnMenuOpened);
            _menu = menu;
        }

        private void OnMenuOpened()
        {
            NsqUi.ApplyPalette(_menu, _w.Mode);
            int n = PickedIdx().Count;
            string what = n <= 1 ? "" : " (" + n + " systems)";
            _menuTo.Header = "Move to..." + what;
            _menuTop.Header = "Move to top" + what;
            _menuClear.IsEnabled = PickedIdx().Any(i => Systems()[i].Start != null);
            _menuGroup.IsEnabled = PickedGids().Count > 0;
            Tuple<int, int> nxt = NextPlace();
            int? last = IndexOf(_lastKey);
            if (nxt == null || (last != null && PickedIdx().Contains(last.Value)))
            {
                _menuNext.Header = nxt == null ? "Move to next (move a system first)" : "Move to next (this is the last one moved)";
                _menuNext.IsEnabled = false;
            }
            else
            {
                _menuNext.Header = "Move to next (#" + nxt.Item2 + ")" + what;
                _menuNext.IsEnabled = true;
            }
        }

        private void OnMenuTo()
        {
            SelState st = St();
            HashSet<int> picked = PickedIdx();
            if (picked.Count == 0) return;
            var moving = picked.Select(i => st.Systems[i]).ToList();
            int others = OnSystems().Count(x => !moving.Contains(x));
            int hi = others + 1;   // the block can land anywhere from first to after the last ticked system
            SysDef sd = st.Systems[picked.Min()];
            int now = Math.Min(hi, NsqCore.PositionOf(st.Systems, picked.Min(), Counted, new[] { sd }));
            string msg = "Move " + (picked.Count == 1 ? sd.Name : "the " + picked.Count + " selected systems") + " to position (1 to " + hi + "):";
            int? pos = NsqUi.PromptNumber(_w.Win, _w.Mode, "Move to", msg, now, 1, hi);
            if (pos != null) MovePosition(pos.Value);
        }

        /// <summary>Select every member of the selected systems' groups - to move a group as one.</summary>
        private void OnMenuGroup()
        {
            SelState st = St();
            HashSet<string> gids = PickedGids();
            var keys = st.Systems.Where(sd => { string g; return st.Groups.TryGetValue(sd.Key, out g) && gids.Contains(g); }).Select(sd => sd.Key).ToList();
            if (keys.Count > 0)
            {
                st.Picked = new HashSet<string>(keys);
                st.Cur = keys[0];
                st.Anchor = keys[0];
                AfterPick();
            }
        }

        /// <summary>Straight after the last system moved - ticked or not, no gaps.</summary>
        private void OnMenuNext()
        {
            Tuple<int, int> nxt = NextPlace();
            HashSet<int> picked = PickedIdx();
            int? last = IndexOf(_lastKey);
            if (nxt == null || picked.Count == 0 || (last != null && picked.Contains(last.Value))) return;
            SelState st = St();
            var names = picked.OrderBy(i => i).Select(i => st.Systems[i].Name).ToList();
            HashSet<int> nw;
            st.Systems = NsqCore.MoveMany(st.Systems, picked, nxt.Item1, out nw);
            List<string> left, joined; HashSet<int> ni;
            Moved(nw, out left, out joined, out ni);
            Recompute();
            MovedStatus(names, ni);
        }

        private void RefreshOrderButtons()
        {
            SelState st = St();
            int n = st.Systems.Count;
            bool has = n > 0;
            HashSet<int> picked = PickedIdx();
            _w.Ctl<Button>("SelUpBtn").IsEnabled = has;
            _w.Ctl<Button>("SelDownBtn").IsEnabled = has;
            _w.Ctl<Button>("SelTopBtn").IsEnabled = picked.Count > 0 && picked.Min() > 0;
            _w.Ctl<Button>("SelBottomBtn").IsEnabled = picked.Count > 0 && picked.Max() < n - 1;
            _w.Ctl<Button>("SelAutoOrderBtn").IsEnabled = OnSystems().Count > 1;
            RefreshGroupButtons();
        }

        private void OnAutoOrder()
        {
            SelState st = St();
            if (st.Data == null) return;
            st.Systems = NsqCore.AutoOrderUnits(st.Data.Nodes, st.Systems, st.Groups, Include);
            Recompute();
            var on = OnSystems();
            int n = new HashSet<string>(st.Groups.Values).Count;
            _w.Status("Ordered nearest-next from " + (on.Count > 0 ? on[0].Name : "the first system") +
                      (n > 0 ? " - " + n + " group(s) moved as one, each next starting nearest where the last finished" : ""));
        }

        // ---------------------------------------------------- groups

        /// <summary>Groups kept whole and together; their hues and every system's shade worked out.</summary>
        private void Regroup()
        {
            SelState st = St();
            var listed = st.Systems.Select(sd => sd.Key).Concat(GoneKeys()).ToList();
            st.Groups = NsqCore.CleanGroups(st.Groups, listed);
            st.Systems = NsqCore.GatherGroups(st.Systems, st.Groups);
            Dictionary<string, string> changed;
            st.Hues = NsqCore.ColourGroups(st.Systems, st.Groups, st.Hues, out changed);
            foreach (SysDef sd in st.Systems) { string c; if (changed.TryGetValue(sd.Key, out c)) sd.Colour = c; }
            st.Shade = NsqCore.SystemColours(st.Systems, st.Groups, st.Hues);
        }

        private HashSet<string> PickedGids()
        {
            SelState st = St();
            var o = new HashSet<string>();
            foreach (int i in PickedIdx())
            {
                string g;
                if (st.Groups.TryGetValue(st.Systems[i].Key, out g)) o.Add(g);
            }
            return o;
        }

        private string UnitOf(string key) { string g; return St().Groups.TryGetValue(key, out g) ? g : key; }

        /// <summary>The system and, when grouped, every other member of its group, in list order.</summary>
        private List<string> UnitKeys(string key, SelState st = null)
        {
            st = st ?? St();
            string gid;
            if (key == null || !st.Groups.TryGetValue(key, out gid)) return new List<string> { key };
            return st.Systems.Where(sd => { string g; return st.Groups.TryGetValue(sd.Key, out g) && g == gid; }).Select(sd => sd.Key).ToList();
        }

        private List<string> TickedKeys(IEnumerable<string> keys)
        {
            var on = new HashSet<string>(OnSystems().Select(sd => sd.Key));
            return keys.Where(on.Contains).ToList();
        }

        /// <summary>Grouped systems that are not their group's first ticked one: Auto next only ever starts a group at its first.</summary>
        private HashSet<string> EntrySkip()
        {
            SelState st = St();
            var o = new HashSet<string>();
            var seen = new HashSet<string>();
            foreach (SysDef sd in OnSystems())
            {
                string gid;
                if (!st.Groups.TryGetValue(sd.Key, out gid)) continue;
                if (seen.Contains(gid)) o.Add(sd.Key); else seen.Add(gid);
            }
            return o;
        }

        private List<int> ViewHits()
        {
            if (_viewSel.Count == 0) return new List<int>();
            return NsqCore.SystemsHolding(Systems(), _viewSel);
        }

        private List<SysDef> GroupCandidates(out string where)
        {
            SelState st = St();
            List<int> hits = ViewHits();
            if (hits.Count >= 2) { where = "from the view"; return hits.Select(i => st.Systems[i]).ToList(); }
            where = "from the table";
            return PickedIdx().OrderBy(i => i).Select(i => st.Systems[i]).ToList();
        }

        private void RefreshGroupButtons()
        {
            SelState st = St();
            bool has = st.Data != null && st.Systems.Count > 0;
            var btn = _w.Ctl<Button>("SelGroupBtn");
            List<int> hits = ViewHits();
            if (hits.Count >= 2)
            {
                NsqUi.SetButton(btn, "group", "Group systems (" + hits.Count + ")", StepGroup);
                btn.SetResourceReference(FrameworkElement.StyleProperty, "GreenFillButton");
            }
            else
            {
                NsqUi.SetButton(btn, "group", "Group systems", StepGroup);
                btn.SetResourceReference(FrameworkElement.StyleProperty, "GreenButton");
            }
            btn.IsEnabled = has && (hits.Count >= 2 || PickedIdx().Count >= 2 || !_selectionHooked);
            _w.Ctl<Button>("SelUngroupBtn").IsEnabled = PickedGids().Count > 0;
            _w.Ctl<Button>("SelGroupOrderBtn").IsEnabled = has && st.Groups.Count > 0;
        }

        private void OnGroup(bool fromButton)
        {
            SelState st = St();
            if (st.Data == null) return;
            string where;
            List<SysDef> sds = GroupCandidates(out where);
            if (sds.Count < 2)
            {
                if (_viewSel.Count == 0 && !_selectionHooked && fromButton)
                {
                    // no selection event (older Revit): read the selection now
                    ViewJob("read selection", uiapp => NsqRevit.SelectedIds(uiapp.ActiveUIDocument).Select(NsqRevit.EidValue).ToList(), (res, err) =>
                    {
                        var values = res as List<long> ?? new List<long>();
                        bool own = _ownSel != null && new HashSet<long>(values).SetEquals(_ownSel);
                        _viewSel = own ? new List<long>() : values;
                        OnGroup(false);
                    }, "Reading the Revit selection");
                    return;
                }
                _w.Status("Select elements of two or more systems in the view (or two or more rows), then Group systems");
                return;
            }
            string gid = NsqCore.NextGroupId(st.Groups, ref st.GidN);
            var keys = sds.Select(sd => sd.Key).ToList();
            Dictionary<string, string> ng;
            st.Systems = NsqCore.MakeGroup(st.Systems, st.Groups, keys, gid, out ng, GoneKeys());
            st.Groups = ng;
            List<string> members = UnitKeys(keys[0]);
            st.Picked = new HashSet<string>(members);
            st.Cur = members[0];
            st.Anchor = members[0];
            _lastKey = members[members.Count - 1];
            st.ReorderDue = true;
            _viewSel = new List<long>();   // used: the button stops offering the same group again
            if (!_colOn) { _colOn = true; _colAuto = false; }   // the group's shades are how it shows: colours on
            Recompute();
            BringIntoView(CurIndex());
            _w.Status("Grouped " + members.Count + " systems " + where + " as " + gid + " - numbered as one block, dark to light in order. Reorder in group puts them nearest-next");
        }

        private void OnUngroup()
        {
            SelState st = St();
            HashSet<string> gids = PickedGids();
            if (gids.Count == 0) { _w.Status("Select a grouped system first"); return; }
            var keys = st.Systems.Where(sd => { string g; return st.Groups.TryGetValue(sd.Key, out g) && gids.Contains(g); }).Select(sd => sd.Key).ToList();
            var listed = st.Systems.Select(sd => sd.Key).Concat(GoneKeys()).ToList();
            st.Groups = NsqCore.Ungroup(st.Groups, keys, listed);
            st.ReorderDue = true;
            Recompute();
            _w.Status("Ungrouped " + string.Join(", ", gids.OrderBy(x => x, Comparer<string>.Create(NsqCore.NaturalCompare))) + " - " + keys.Count + " systems back on their own");
        }

        /// <summary>Nearest-next inside the selected systems' groups, or every group.</summary>
        private void OnGroupOrder()
        {
            SelState st = St();
            if (st.Data == null || st.Groups.Count == 0) return;
            HashSet<string> gids = PickedGids();
            if (gids.Count == 0) gids = new HashSet<string>(st.Groups.Values);
            var ordered = new List<string>();
            foreach (SysDef sd in st.Systems.ToList())
            {
                string gid;
                if (st.Groups.TryGetValue(sd.Key, out gid) && gids.Contains(gid) && !ordered.Contains(gid)) ordered.Add(gid);
            }
            st.ReorderDue = true;
            foreach (string gid in ordered) st.Systems = NsqCore.ReorderGroup(st.Data.Nodes, st.Systems, st.Groups, gid, Include);
            Recompute();
            _w.Status("Re-ordered " + (ordered.Count == 1 ? "group " + ordered[0] : ordered.Count + " groups") + " nearest-next - shades follow the new order");
        }

        // ---------------------------------------------------- start point

        private bool Started() { return Chain().Count > 0 || OnSystems().Any(sd => sd.Start != null); }

        private void RefreshAuto()
        {
            SelState st = St();
            bool started = Started();
            var pick = _w.Ctl<Button>("SelPickStartBtn");
            if (started)
            {
                NsqUi.SetButton(pick, "start", "Start picked", StepPick);
                pick.SetResourceReference(FrameworkElement.StyleProperty, "ActiveButton");
                pick.ToolTip = "The sequence starts at the picked element - press to pick another";
            }
            else
            {
                NsqUi.SetButton(pick, "start", "Pick start", StepPick);
                pick.SetResourceReference(FrameworkElement.StyleProperty, "GreenFillButton");
                pick.ToolTip = "Click the element the sequence starts from - its system (or group) goes to #1";
            }
            pick.IsEnabled = Has();
            var btn = _w.Ctl<Button>("SelAutoBtn");
            int units = new HashSet<string>(OnSystems().Select(sd => UnitOf(sd.Key))).Count;
            NsqUi.SetButton(btn, "auto", "Auto Re-order", StepAuto);
            btn.SetResourceReference(FrameworkElement.StyleProperty, started && units > 1 && st.ReorderDue ? "GreenButton" : "ToolButton");
            btn.IsEnabled = started && units > 1;
            btn.ToolTip = started
                ? "Order every system (and group) from the picked start: each next is the one starting nearest where the last finished.  Shift: just the next one"
                : "Pick a start first";
        }

        public void RefreshStart()
        {
            RefreshAuto();
            var t = _w.Ctl<TextBlock>("StartText");
            SelState st = St();
            if (st.Data == null || st.Systems.Count == 0) { t.Text = "No systems read yet - Refresh from view"; return; }
            int? i = CurIndex();
            SysDef sd = st.Systems[i ?? 0];
            var on = OnSystems();
            if (!on.Contains(sd)) { t.Text = sd.Name + " is unticked - it is not numbered"; return; }
            int n = on.IndexOf(sd);
            long? key = null; string how = "auto";
            if (n < st.Starts.Count) { key = st.Starts[n].Key; how = st.Starts[n].Value; }
            if (key == null) { t.Text = sd.Name + ": nothing to number"; return; }
            string why = how == "picked" ? "picked" : how == "auto" ? "auto - equipment end or biggest open end" :
                         how == "nearest" ? "open end nearest where system " + n + " finished" : how;
            string label;
            t.Text = "System " + (n + 1) + ", " + sd.Name + ": starts (" + why + ") at " + (st.Data.Labels.TryGetValue(key.Value, out label) ? label : "") + "  [" + key + "]";
        }

        public void PickStart()
        {
            string kind = Kind;
            HashSet<long> ints = NsqRevit.KindInts(kind, "walk");
            _w.QueueBusy("pick start", uiapp =>
            {
                Element el = NsqRevit.PickElement(uiapp.ActiveUIDocument, ints, "RevoBIM Number Sequencer: click the element to start the sequence from");
                return el == null ? (object)null : NsqRevit.EidValue(el.Id);
            }, (res, err) =>
            {
                if (err != null || res == null) { _w.Status("Cancelled"); return; }
                long key = (long)res;
                SelState st = _state[kind];
                foreach (SysDef sd in st.Systems)
                {
                    if (!sd.Num.Contains(key)) continue;
                    sd.Start = key;
                    sd.On = true;
                    // the picked start begins the sequence: its system goes to #1 and starts the chain Auto next builds on
                    foreach (SysDef other in st.Systems)
                        if (!ReferenceEquals(other, sd) && other.Start != null && st.Chain.Take(1).Contains(other.Key)) other.Start = null;
                    string gid;
                    if (st.Groups.TryGetValue(sd.Key, out gid))
                    {
                        // a start inside a group: that system leads its group
                        var rest = st.Systems.Where(x => !ReferenceEquals(x, sd)).ToList();
                        int hit = rest.FindIndex(x => { string g; return st.Groups.TryGetValue(x.Key, out g) && g == gid; });
                        if (hit >= 0) { rest.Insert(hit, sd); st.Systems = rest; }
                    }
                    List<string> unit = UnitKeys(sd.Key, st);
                    var idx = new HashSet<int>();
                    for (int j = 0; j < st.Systems.Count; j++) if (unit.Contains(st.Systems[j].Key)) idx.Add(j);
                    HashSet<int> nw; int last;
                    st.Systems = NsqCore.MoveToPosition(st.Systems, idx, 1, Counted, out nw, out last);
                    // the whole group (or the system) begins the chain Auto next builds on
                    st.Chain = st.Systems.Where(x => unit.Contains(x.Key) && x.On).Select(x => x.Key).ToList();
                    st.ReorderDue = true;
                    _lastKey = st.Chain.Count > 0 ? st.Chain[st.Chain.Count - 1] : sd.Key;
                    st.Cur = sd.Key;
                    st.Anchor = sd.Key;
                    st.Picked = new HashSet<string> { sd.Key };
                    _colOn = true;    // show the start: colours on, the start drawn heavy in its own colour
                    _colAuto = false;
                    Recompute();
                    _w.Status("Start set on " + sd.Name + ", now #1 - press Auto next for the nearest system after it (Shift: all the rest)");
                    return;
                }
                _w.Status("That element is not in a listed system - Refresh from view first");
            }, "Click the element to start the sequence from (Esc cancels)");
        }

        /// <summary>For the right-click menu: back on the automatic start.</summary>
        public void AutoStart()
        {
            bool changed = false;
            foreach (int i in PickedIdx())
            {
                SysDef sd = Systems()[i];
                if (sd.Start != null)
                {
                    sd.Start = null;
                    changed = true;
                    if (St().Chain.Count > 0 && St().Chain[0] == sd.Key) St().Chain = new List<string>();
                }
            }
            if (changed) Recompute();
        }

        /// <summary>The systems placed so far by Pick start / Auto next, still listed and ticked.</summary>
        private List<string> Chain()
        {
            var on = new HashSet<string>(OnSystems().Select(sd => sd.Key));
            return St().Chain.Where(on.Contains).ToList();
        }

        /// <summary>Auto Re-order: from the picked start, every system and group in nearest-next order. Shift: only the next one.</summary>
        public void AutoReorder(bool step = false)
        {
            SelState st = St();
            if (st.Data == null || OnSystems().Count == 0) return;
            if (!step) st.Chain = new List<string>();
            AutoNext(!step);
            var chain = new HashSet<string>(Chain());
            var left = OnSystems().Where(sd => !chain.Contains(sd.Key)).ToList();
            st.ReorderDue = left.Count > 0;
            RefreshAuto();
        }

        private void AutoNext(bool allRest)
        {
            SelState st = St();
            if (st.Data == null || OnSystems().Count == 0) return;
            var nodes = st.Data.Nodes;
            List<string> chain = Chain();
            if (chain.Count == 0)
            {
                var starts = OnSystems().Where(sd => sd.Start != null).ToList();
                SysDef first = starts.Count > 0 ? starts[0] : OnSystems()[0];
                List<string> unit = UnitKeys(first.Key);
                var idx = new HashSet<int>(unit.Select(k => IndexOf(k)).Where(x => x != null).Select(x => x.Value));
                if (idx.Count > 0 && idx.Min() != 0)
                {
                    HashSet<int> nw; int last;
                    st.Systems = NsqCore.MoveToPosition(st.Systems, idx, 1, Counted, out nw, out last);
                }
                chain = TickedKeys(UnitKeys(first.Key));
            }
            var placed = new List<SysDef>();
            double? dist = null;
            while (true)
            {
                var on = OnSystems();
                var keys = on.Select(sd => sd.Key).ToList();
                int lastI = keys.IndexOf(chain[chain.Count - 1]);
                // a group is only ever entered at its first ticked system, and moves whole
                var skip = new HashSet<string>(chain);
                skip.UnionWith(EntrySkip());
                KeyValuePair<int, double>? found = NsqCore.NextNearest(nodes, on, lastI, skip, Include);
                if (found == null) break;
                SysDef sd = on[found.Value.Key];
                dist = found.Value.Value;
                List<string> unit = UnitKeys(sd.Key);
                int end = UnitKeys(chain[chain.Count - 1]).Select(k => IndexOf(k) ?? -1).Max() + 1;
                HashSet<int> nw;
                st.Systems = NsqCore.MoveMany(st.Systems, unit.Select(k => IndexOf(k) ?? -1).Where(x => x >= 0), end, out nw);
                chain.AddRange(TickedKeys(UnitKeys(sd.Key)));
                placed.Add(sd);
                if (!allRest) break;
            }
            st.Chain = chain;
            string lastKey = chain[chain.Count - 1];
            _lastKey = lastKey;
            st.Cur = lastKey;
            st.Anchor = lastKey;
            st.Picked = new HashSet<string> { lastKey };
            Recompute();
            BringIntoView(CurIndex());
            if (placed.Count == 0) { _w.Status("Every ticked system is placed"); return; }
            if (placed.Count == 1)
            {
                var on = OnSystems();
                int pos = on.Contains(placed[0]) ? on.IndexOf(placed[0]) + 1 : 0;
                string gid;
                string what = !st.Groups.TryGetValue(placed[0].Key, out gid) ? placed[0].Name :
                    "group " + gid + " (" + UnitKeys(placed[0].Key).Count + " systems, from " + placed[0].Name + ")";
                double mm = dist != null && dist.Value < 1e20 ? dist.Value * 304.8 : 0;
                _w.Status("Auto next: " + what + " is #" + pos + ", its start " + mm.ToString("0") + " mm from where the last one finishes");
                SelectPicked(false);
            }
            else _w.Status("Auto next placed " + placed.Count + " systems / groups, each the nearest after the last");
        }

        /// <summary>Element keys and label of the selected systems, for Find views.</summary>
        public List<long> PickedKeys(out string label)
        {
            SelState st = St();
            var picked = PickedIdx().OrderBy(i => i).Select(i => st.Systems[i]).ToList();
            label = picked.Count == 0 ? "" : picked.Count == 1 ? picked[0].Name : picked.Count + " systems";
            return picked.SelectMany(sd => sd.Num).ToList();
        }

        public void ShowStart()
        {
            SelState st = St();
            var on = OnSystems();
            int? i = CurIndex();
            if (i == null) return;
            SysDef sd = st.Systems[i.Value];
            if (on.Contains(sd) && on.IndexOf(sd) < st.Starts.Count)
            {
                long? key = st.Starts[on.IndexOf(sd)].Key;
                if (key != null && st.Data.IdMap.ContainsKey(key.Value))
                {
                    _ownSel = new HashSet<long> { key.Value };
                    _w.SelectIds(new List<ElementId> { st.Data.IdMap[key.Value] }, true);
                }
            }
        }

        // ---------------------------------------------------- the view: isolate, colour, remove

        private bool Has() { return St().Data != null && Systems().Count > 0; }

        private void SameView(UIApplication uiapp)
        {
            Document doc = uiapp.ActiveUIDocument.Document;
            var here = Tuple.Create(NsqRevit.DocKey(doc), NsqRevit.EidValue(doc.ActiveView.Id));
            if (St().Data == null || _viewKey == null || !here.Equals(_viewKey) || !here.Equals(KindViewKey()))
                throw new Exception("The active view is not the one the systems were read from - Refresh from view");
        }

        /// <summary>Only the families ticked in the tree, in the ticked systems, not removed - never accessories.</summary>
        private List<ElementId> IsolateIds()
        {
            var idmap = St().Data.IdMap;
            return OnSystems().SelectMany(sd => sd.Keys).Where(k => idmap.ContainsKey(k) && Include(k)).Select(k => idmap[k]).ToList();
        }

        /// <summary>Each system its swatch colour (a group's dark-to-light shade); the start last, heavy, in its own colour.</summary>
        private List<NsqRevit.ColourGroup> ColourGroupsList()
        {
            SelState st = St();
            var idmap = st.Data.IdMap;
            var o = new List<NsqRevit.ColourGroup>();
            foreach (SysDef sd in st.Systems)
            {
                string c;
                if (!st.Shade.TryGetValue(sd.Key, out c) || string.IsNullOrEmpty(c)) c = sd.Colour;
                o.Add(new NsqRevit.ColourGroup { Hex = c, Ids = sd.Keys.Where(idmap.ContainsKey).Select(k => idmap[k]).ToList() });
            }
            HashSet<long> starts = NsqCore.StartKeys(st.Order, OnSystems());
            o.Add(new NsqRevit.ColourGroup { Hex = NsqCore.StartColour, Ids = starts.OrderBy(x => x).Where(idmap.ContainsKey).Select(k => idmap[k]).ToList(), Weight = NsqCore.StartWeight });
            return o;
        }

        /// <summary>Bring the view in line with the table: colours and isolate. Many changes in a row send one job.</summary>
        private void RequestSync()
        {
            _syncWanted = true;
            if (_syncQueued) return;
            _syncQueued = true;
            _w.Runner.Queue("view sync", uiapp =>
            {
                _syncQueued = false;
                if (!_syncWanted) return "";
                _syncWanted = false;
                return Sync(uiapp);
            }, (res, err) =>
            {
                _syncQueued = false;
                RefreshViewButtons();
                if (err != null) _w.Status(Why(err, "Could not update the view"));
                else if (!string.IsNullOrEmpty(res as string)) _w.Status((string)res);
            });
        }

        private static string ColSig(ViewKey key, List<NsqRevit.ColourGroup> groups)
        {
            // order-free: re-ordering the table never re-colours the view
            var parts = groups.Select(g => g.Hex + ":" + string.Join(",", g.Ids.Select(NsqRevit.EidValue).OrderBy(x => x))).OrderBy(x => x, StringComparer.Ordinal);
            return key + "|" + string.Join(";", parts);
        }

        private static string IsoSig(ViewKey key, List<ElementId> ids)
        {
            return key + "|" + string.Join(",", ids.Select(NsqRevit.EidValue).OrderBy(x => x));
        }

        private string Sync(UIApplication uiapp)
        {
            if (!Has() || !(_colOn || _isoOn || _iso3d != null)) return "";
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            var msgs = new List<string>();
            var here = Tuple.Create(NsqRevit.DocKey(doc), NsqRevit.EidValue(doc.ActiveView.Id));
            if ((_colOn || _isoOn) && !(_iso3d != null && !here.Equals(_viewKey))) SyncReadView(uiapp, msgs);   // the read view
            if (_iso3d != null && here.Item1 == _iso3d.Item1) Sync3d(uidoc, msgs);
            try { uidoc.RefreshActiveView(); } catch (Exception) { }
            return msgs.Count > 0 ? "View: " + string.Join(", ", msgs) : "";
        }

        private SnapEntry Entry(ViewKey key, View view)
        {
            SnapEntry e;
            if (!_snapshots.TryGetValue(key, out e)) { e = new SnapEntry { ViewId = view.Id }; _snapshots[key] = e; }
            return e;
        }

        /// <summary>Keep the Isolate in 3D view in step with the table.</summary>
        private void Sync3d(UIDocument uidoc, List<string> msgs)
        {
            Document doc = uidoc.Document;
            View3D view = doc.GetElement(_iso3dId) as View3D;
            if (view == null) { Iso3dOff(); return; }
            ViewKey key = _iso3d;
            if (_col3d)
            {
                var groups = ColourGroupsList();
                string sig = ColSig(key, groups);
                if (sig != _lastCol3d)
                {
                    NsqRevit.ColourSystems(doc, view, groups, Entry(key, view).Snap, _w.Log);
                    Absorb(key);
                    _lastCol3d = sig;
                    msgs.Add("3D re-coloured");
                }
            }
            List<ElementId> ids = IsolateIds();
            string isig = IsoSig(key, ids);
            if (isig != _lastIso3d)
            {
                // new systems: the section box follows them
                BoundingBoxXYZ oldBox = NsqRevit.FitSectionBox(doc, view, ids, _w.Log);
                if (oldBox != null && !_boxes.ContainsKey(key)) _boxes[key] = Tuple.Create(view.Id, oldBox);
                int n = NsqRevit.IsolateSystems(uidoc, ids, _w.Log, view);
                _isoViews[key] = view.Id;
                _hideViews.Remove(key);
                _lastIso3d = isig;
                msgs.Add("3D isolated " + n + " elements and tags");
            }
        }

        private void SyncReadView(UIApplication uiapp, List<string> msgs)
        {
            SameView(uiapp);
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            View view = doc.ActiveView;
            var key = Tuple.Create(NsqRevit.DocKey(doc), NsqRevit.EidValue(view.Id));
            if (_colOn)
            {
                var groups = ColourGroupsList();
                string sig = ColSig(key, groups);
                if (sig != _lastCol)
                {
                    int n = NsqRevit.ColourSystems(doc, view, groups, Entry(key, view).Snap, _w.Log);
                    Absorb(key);
                    _lastCol = sig;
                    msgs.Add("coloured " + n + " elements");
                }
            }
            if (_isoOn)
            {
                List<ElementId> ids = IsolateIds();
                string sig = IsoSig(key, ids);
                if (sig != _lastIso)
                {
                    int n = NsqRevit.IsolateSystems(uidoc, ids, _w.Log);
                    _isoViews[key] = view.Id;
                    _hideViews.Remove(key);   // the isolate reset any temporary hide
                    _lastIso = sig;
                    msgs.Add("isolated " + n + " elements and tags");
                }
            }
        }

        /// <summary>View changes go straight to the runner: a toggle must never show a state the view did not get because the window was busy.</summary>
        private void ViewJob(string name, Func<UIApplication, object> fn, Action<object, string> done, string status)
        {
            _w.Status(status);
            _w.Runner.Queue(name, fn, done);
        }

        private void OnIsolate()
        {
            if (_isoOn)
            {
                _isoOn = false;
                _lastIso = null;
                bool clear = _colAuto;
                if (clear) { _colOn = false; _colAuto = false; _lastCol = null; }
                RefreshViewButtons();
                ViewJob("reset isolate", uiapp =>
                {
                    int n = ResetIsolates(uiapp, _iso3d);
                    if (clear) RestoreAll(uiapp, _iso3d);
                    return n;
                }, (r, err) =>
                {
                    RefreshViewButtons();
                    _w.Status(err != null ? "Could not reset the isolate - see debug" : "Isolate reset");
                }, "Resetting the isolate");
                return;
            }
            if (!Has()) { _w.Status("Nothing to isolate - Refresh from view"); return; }
            _isoOn = true;
            if (!_colOn) { _colOn = true; _colAuto = true; }   // isolating turned the colours on, resetting turns them off
            RefreshViewButtons();
            RequestSync();
        }

        // ---------------------------------------------------- Isolate in 3D

        /// <summary>The 3D view picker: Default 3D view, then the model's 3D views.</summary>
        public void Fill3dCombo(List<KeyValuePair<string, string>> views)
        {
            var combo = _w.Ctl<ComboBox>("Sel3DCombo");
            int idx;
            var items = NsqCore.Combo3dItems(views ?? new List<KeyValuePair<string, string>>(), _w.Settings["iso3d_view"] ?? "", out idx);
            _filling3d = true;
            try
            {
                combo.Items.Clear();
                foreach (var it in items) combo.Items.Add(new ComboBoxItem { Content = it.Value, Tag = it.Key });
                combo.SelectedIndex = idx;
            }
            finally { _filling3d = false; }
        }

        private void On3dChoice()
        {
            if (_filling3d) return;
            _w.Settings["iso3d_view"] = Chosen3d();
            _w.Save();
        }

        private string Chosen3d()
        {
            var it = _w.Ctl<ComboBox>("Sel3DCombo").SelectedItem as ComboBoxItem;
            return it != null && it.Tag != null ? it.Tag.ToString() : "";
        }

        private void Iso3dOff()
        {
            _iso3d = null; _iso3dId = null; _iso3dName = ""; _col3d = false; _lastIso3d = null; _lastCol3d = null;
        }

        private class Iso3dResult
        {
            public int N; public string Name; public bool Created; public ElementId Id; public List<KeyValuePair<string, string>> Views3d; public bool Boxed;
        }

        private void OnIso3d()
        {
            if (_iso3dBusy) return;
            if (_iso3d != null)
            {
                ViewKey key = _iso3d;
                ElementId vid = _iso3dId;
                string name = _iso3dName;
                Iso3dOff();
                bool clear = _colAuto && !_isoOn;
                if (clear) { _colOn = false; _colAuto = false; _lastCol = null; }
                RefreshViewButtons();
                ViewJob("reset 3D isolate", uiapp =>
                {
                    int n = 0;
                    foreach (var kv in NsqRevit.OpenDocuments(uiapp))
                    {
                        if (kv.Key != key.Item1) continue;
                        Document doc = kv.Value;
                        ElementId isoView; if (!_isoViews.TryGetValue(key, out isoView)) isoView = vid; _isoViews.Remove(key);
                        NsqRevit.ResetIsolateView(doc, isoView, _w.Log);
                        _hideViews.Remove(key);
                        Tuple<ElementId, BoundingBoxXYZ> box;
                        if (_boxes.TryGetValue(key, out box)) { _boxes.Remove(key); NsqRevit.RestoreSectionBox(doc, box.Item1, box.Item2, _w.Log); }
                        SnapEntry se;
                        if (_snapshots.TryGetValue(key, out se))
                        {
                            n += NsqRevit.RestoreOverrides(doc, se.ViewId, se.Snap, _w.Log);
                            if (se.Snap.Count == 0) _snapshots.Remove(key);
                        }
                    }
                    if (clear) n += RestoreAll(uiapp, null);
                    try { uiapp.ActiveUIDocument.RefreshActiveView(); } catch (Exception) { }
                    return n;
                }, (r, err) =>
                {
                    RefreshViewButtons();
                    _w.Status(err != null ? "Could not reset the 3D isolate - see debug" : "3D isolate reset in " + name);
                    CheckView();
                }, "Resetting the 3D isolate");
                return;
            }
            if (!Has()) { _w.Status("Nothing to isolate - Refresh from view"); return; }
            string uid = Chosen3d();
            _iso3dBusy = true;
            if (!_colOn) { _colOn = true; _colAuto = true; }   // isolating shows the colours: Colour systems on (off again with the reset)
            RefreshViewButtons();
            ViewJob("isolate in 3D", uiapp =>
            {
                UIDocument uidoc = uiapp.ActiveUIDocument;
                Document doc = uidoc.Document;
                NetworkData d = St().Data;
                if (d == null || NsqRevit.DocKey(doc) != d.DocKey)
                    throw new Exception("The active project is not the one the systems were read from - Refresh from view");
                View3D view = NsqRevit.ViewByUid(doc, uid) ?? NsqRevit.Default3d(doc);
                bool created = view == null;
                if (created) view = NsqRevit.CreateDefault3d(doc, _w.Log);
                var key = Tuple.Create(NsqRevit.DocKey(doc), NsqRevit.EidValue(view.Id));
                var groups = ColourGroupsList();
                NsqRevit.ColourSystems(doc, view, groups, Entry(key, view).Snap, _w.Log);
                Absorb(key);
                List<ElementId> ids = IsolateIds();
                BoundingBoxXYZ oldBox = NsqRevit.FitSectionBox(doc, view, ids, _w.Log);
                bool boxed = oldBox != null;
                if (boxed && !_boxes.ContainsKey(key)) _boxes[key] = Tuple.Create(view.Id, oldBox);
                int n = NsqRevit.IsolateSystems(uidoc, ids, _w.Log, view);
                _isoViews[key] = view.Id;
                _hideViews.Remove(key);
                _iso3d = key;
                _iso3dId = view.Id;
                _iso3dName = NsqRevit.ElemName(view);
                _col3d = true;
                _lastCol3d = ColSig(key, groups);
                _lastIso3d = IsoSig(key, ids);
                if (NsqRevit.EidValue(doc.ActiveView.Id) != key.Item2) uidoc.RequestViewChange(view);   // opens once this event returns
                return new Iso3dResult { N = n, Name = _iso3dName, Created = created, Id = view.Id, Views3d = created ? NsqRevit.Views3d(doc) : null, Boxed = boxed };
            }, (resObj, err) =>
            {
                _iso3dBusy = false;
                var res = resObj as Iso3dResult;
                if ((err != null || res == null) && _colAuto && !_isoOn && _iso3d == null)
                {
                    _colOn = false;   // nothing isolated: the colours it turned on go off again
                    _colAuto = false;
                }
                RefreshViewButtons();
                if (err != null || res == null) { _w.Status(Why(err, "Could not isolate in 3D")); return; }
                if (res.Views3d != null) Fill3dCombo(res.Views3d);
                _stale = false;
                RefreshViewButtons();
                _w.Status("Isolated " + res.N + " elements and tags in " + res.Name + (res.Created ? " (new 3D view)" : "") + ", coloured by system" +
                          (res.Boxed ? ", section box fitted to them" : ""));
                ElementId vid2 = res.Id;
                // the view opens after the isolate job returns: zoom in a job of its own
                _w.Runner.Queue("zoom 3D", uiapp2 => NsqRevit.ZoomView(uiapp2.ActiveUIDocument, vid2), (r2, e2) => { });
            }, "Isolating the systems in 3D");
        }

        /// <summary>Reset every isolate this tool made, in every open document - all but skip, the Isolate in 3D view.</summary>
        private int ResetIsolates(UIApplication uiapp, ViewKey skip)
        {
            int n = 0;
            foreach (var kv in NsqRevit.OpenDocuments(uiapp))
            {
                foreach (ViewKey key in _isoViews.Keys.ToList())
                {
                    if (key.Item1 != kv.Key || (skip != null && key.Equals(skip))) continue;
                    ElementId vid = _isoViews[key]; _isoViews.Remove(key);
                    if (NsqRevit.ResetIsolateView(kv.Value, vid, _w.Log)) n++;
                    _hideViews.Remove(key);   // the reset also undid any temporary hide
                }
            }
            try { uiapp.ActiveUIDocument.RefreshActiveView(); } catch (Exception) { }
            return n;
        }

        /// <summary>Undo the temporary hides Remove made, in the views it made them.</summary>
        private void ShowHidden(UIApplication uiapp)
        {
            foreach (var kv in NsqRevit.OpenDocuments(uiapp))
                foreach (ViewKey key in _hideViews.Keys.ToList())
                    if (key.Item1 == kv.Key) { ElementId vid = _hideViews[key]; _hideViews.Remove(key); NsqRevit.ResetIsolateView(kv.Value, vid, _w.Log); }
            try { uiapp.ActiveUIDocument.RefreshActiveView(); } catch (Exception) { }
        }

        private void OnColour()
        {
            if (_colOn || _leftovers.Count > 0)
            {
                // off: this session's colours put back, and any left from before taken off
                _colOn = false; _colAuto = false; _lastCol = null;
                RefreshViewButtons();
                ViewJob("clear colours", uiapp => RestoreAll(uiapp, _iso3d) + ClearLeftovers(uiapp, _iso3d), (n, err) =>
                {
                    RefreshViewButtons();
                    _w.Status(err != null ? "Could not clear the colours - see debug" : "Colours cleared from " + n + " elements");
                }, "Clearing the system colours");
                return;
            }
            if (!Has()) return;
            _colOn = true;
            _colAuto = false;
            RefreshViewButtons();
            RequestSync();
        }

        private void OnRemove()
        {
            SelState st = St();
            if (st.Data == null) return;
            List<long> keys = new List<long>(_userSel);
            var idmap = st.Data.IdMap;
            if (keys.Count == 0)
            {
                if (_selectionHooked)
                {
                    // Revit reports every selection; nothing lit means nothing of the user's own is selected
                    _w.Status("Select elements of the sequence in the view first");
                    return;
                }
                // no selection event (older Revit): read the selection now
                ViewJob("read selection", uiapp => NsqRevit.SelectedIds(uiapp.ActiveUIDocument).Select(NsqRevit.EidValue).ToList(), (res, err) =>
                {
                    var values = res as List<long> ?? new List<long>();
                    var seq = OnSystems().SelectMany(sd => sd.Num).Where(Include).ToList();
                    _userSel = NsqCore.UserSelection(values, _ownSel, seq);
                    if (_userSel.Count > 0) OnRemove();
                    else _w.Status("Select elements of the sequence in the view first");
                }, "Reading the Revit selection");
                return;
            }
            st.LeftOut.UnionWith(keys);
            st.ReorderDue = true;   // the order may want working out again
            _userSel = new List<long>();
            _ownSel = new HashSet<long>();
            var ids = keys.Where(idmap.ContainsKey).Select(k => idmap[k]).ToList();
            bool isolated = _isoOn;
            ViewJob("remove from sequence", uiapp =>
            {
                UIDocument uidoc = uiapp.ActiveUIDocument;
                NsqRevit.SelectAndShow(uidoc, new List<ElementId>(), false);
                Document doc = uidoc.Document;
                bool in3d = _iso3d != null && Tuple.Create(NsqRevit.DocKey(doc), NsqRevit.EidValue(doc.ActiveView.Id)).Equals(_iso3d);
                // isolated views drop them in the re-isolate the sync makes
                if (!isolated && !in3d)
                {
                    SameView(uiapp);
                    NsqRevit.HideTemporary(uidoc, ids, _w.Log);
                    View view = uidoc.Document.ActiveView;
                    _hideViews[Tuple.Create(NsqRevit.DocKey(uidoc.Document), NsqRevit.EidValue(view.Id))] = view.Id;
                }
                return ids.Count;
            }, (n, err) =>
            {
                RefreshViewButtons();
                _w.Status(err != null ? Why(err, "Removed from the sequence, but could not hide them") : n + " element(s) removed from the sequence and hidden");
            }, "Removing from the sequence");
            // when isolated, the isolate is rebuilt without them by the sync recompute asks for
            Recompute();
        }

        /// <summary>Everything removed comes back, on both tabs.</summary>
        private void OnRestore()
        {
            int n = 0;
            foreach (string kind in NsqCore.Kinds.Keys)
            {
                SelState st = _state[kind];
                n += st.LeftOut.Count;
                st.LeftOut = new HashSet<long>();
                st.Systems = NsqCore.BringBack(st.Systems, st.Gone);
                st.Gone = new List<List<KeyValuePair<string, SysDef>>>();
                st.ReorderDue = true;
            }
            if (_hideViews.Count > 0)
            {
                var hidden = new HashSet<ViewKey>(_hideViews.Keys);
                string kind = Kind;
                // one job: unhide, then read again if the active view was a hidden one, so the systems that left with their elements come back
                ViewJob("show removed", uiapp =>
                {
                    ShowHidden(uiapp);
                    Document doc = uiapp.ActiveUIDocument.Document;
                    var here = Tuple.Create(NsqRevit.DocKey(doc), NsqRevit.EidValue(doc.ActiveView.Id));
                    if (hidden.Contains(here) && !_isoViews.ContainsKey(here)) return ReadJob(kind)(uiapp);
                    return null;
                }, (res, err) =>
                {
                    if (res != null && err == null) Loaded(res, null);
                    RefreshViewButtons();
                }, "Showing the removed elements");
            }
            Recompute();
            _w.Status(n + " element(s) back in the sequence");
        }

        /// <summary>Left-over colours this session has now coloured over are in its record, so clearing takes them off.</summary>
        private void Absorb(ViewKey key)
        {
            Tuple<ElementId, List<ElementId>> left;
            if (!_leftovers.TryGetValue(key, out left)) return;
            HashSet<long> snap = _snapshots.ContainsKey(key) ? new HashSet<long>(_snapshots[key].Snap.Keys) : new HashSet<long>();
            var rest = left.Item2.Where(i => !snap.Contains(NsqRevit.EidValue(i))).ToList();
            if (rest.Count > 0) _leftovers[key] = Tuple.Create(left.Item1, rest);
            else _leftovers.Remove(key);
        }

        /// <summary>Take off the colours an earlier session left, in every open document.</summary>
        private int ClearLeftovers(UIApplication uiapp, ViewKey skip)
        {
            int n = 0;
            foreach (var kv in NsqRevit.OpenDocuments(uiapp))
                foreach (ViewKey key in _leftovers.Keys.ToList())
                {
                    if (key.Item1 != kv.Key || (skip != null && key.Equals(skip))) continue;
                    var entry = _leftovers[key]; _leftovers.Remove(key);
                    n += NsqRevit.ClearOverrides(kv.Value, entry.Item1, entry.Item2, _w.Log);
                }
            try { uiapp.ActiveUIDocument.RefreshActiveView(); } catch (Exception) { }
            return n;
        }

        /// <summary>Our own refusals carry a message worth showing; anything else is in the debug log.</summary>
        private static string Why(string err, string fallback)
        {
            if ((err ?? "").Contains("Refresh from view")) return "The active view changed - Refresh from view first";
            return fallback + " - see debug";
        }

        /// <summary>Put back the colours in every open document, each into the document it was taken from.</summary>
        private int RestoreAll(UIApplication uiapp, ViewKey skip)
        {
            int n = 0;
            foreach (var kv in NsqRevit.OpenDocuments(uiapp))
                foreach (ViewKey key in _snapshots.Keys.ToList())
                {
                    if (key.Item1 != kv.Key || (skip != null && key.Equals(skip))) continue;
                    SnapEntry se = _snapshots[key];
                    n += NsqRevit.RestoreOverrides(kv.Value, se.ViewId, se.Snap, _w.Log);
                    if (se.Snap.Count == 0) _snapshots.Remove(key);
                }
            try { uiapp.ActiveUIDocument.RefreshActiveView(); } catch (Exception) { }
            return n;
        }

        /// <summary>Run finished: turn the temporary colours off again - the 3D view's too. Isolates stay until reset.</summary>
        public int AfterRun(UIApplication uiapp)
        {
            _colOn = false; _colAuto = false; _lastCol = null; _col3d = false; _lastCol3d = null;
            int n = RestoreAll(uiapp, null);
            return n + ClearLeftovers(uiapp, null);
        }

        public void AfterRunUi() { RefreshViewButtons(); }

        private bool ColoursOn() { return _snapshots.Values.Any(e => e.Snap.Count > 0) || _leftovers.Count > 0; }

        public void RefreshViewButtons()
        {
            bool has = Has();
            var iso = _w.Ctl<Button>("SelIsolateBtn");
            if (_isoOn)
            {
                NsqUi.SetButton(iso, "unisolate", "Reset 2D isolate");
                iso.SetResourceReference(FrameworkElement.StyleProperty, "ActiveButton");
            }
            else
            {
                NsqUi.SetButton(iso, "isolate", "Isolate Systems 2D");
                iso.SetResourceReference(FrameworkElement.StyleProperty, "ToolButton");
            }
            iso.IsEnabled = has || _isoOn || _isoViews.Count > 0;
            var col = _w.Ctl<Button>("SelColourBtn");
            int left = _leftovers.Where(kv => _iso3d == null || !kv.Key.Equals(_iso3d)).Sum(kv => kv.Value.Item2.Count);
            if (_colOn)
            {
                // the row is kept compact: the colour toggle is its icon, orange while on
                NsqUi.SetButton(col, "uncolour", "");
                col.SetResourceReference(FrameworkElement.StyleProperty, "ActiveButton");
                col.ToolTip = "Colours on - press to take the system colours off the view";
            }
            else if (left > 0)
            {
                // colours left in the view by an earlier session: one press takes them off
                NsqUi.SetButton(col, "uncolour", left.ToString());
                col.SetResourceReference(FrameworkElement.StyleProperty, "ActiveButton");
                col.ToolTip = "Clear colours: " + left + " elements still carry colours from an earlier session - press to take them off";
            }
            else
            {
                NsqUi.SetButton(col, "colour", "");
                col.SetResourceReference(FrameworkElement.StyleProperty, "ToolButton");
                col.ToolTip = "Colour systems: each system in the view in its swatch colour; the start is drawn heavy in magenta. Press again to clear.";
            }
            col.IsEnabled = has || _colOn || left > 0;
            var b3 = _w.Ctl<Button>("SelIso3DBtn");
            if (_iso3d != null)
            {
                NsqUi.SetButton(b3, "cube", "Reset 3D isolate", StepIso3d);
                b3.SetResourceReference(FrameworkElement.StyleProperty, "ActiveButton");
                b3.ToolTip = "Reset the isolate and colours in " + _iso3dName;
            }
            else
            {
                NsqUi.SetButton(b3, "cube", "Isolate 3D", StepIso3d);
                b3.SetResourceReference(FrameworkElement.StyleProperty, "GreenFillButton");
                b3.ToolTip = "Open the 3D view chosen beside it, isolate the ticked systems there, fit its section box to them and colour them. Press again to reset that 3D view.";
            }
            b3.IsEnabled = (has || _iso3d != null) && !_iso3dBusy;
            var rem = _w.Ctl<Button>("SelRemoveBtn");
            if (_userSel.Count > 0)
            {
                NsqUi.SetButton(rem, "hide", "Remove from sequence (" + _userSel.Count + ")");
                rem.SetResourceReference(FrameworkElement.StyleProperty, "RedActiveButton");
            }
            else
            {
                NsqUi.SetButton(rem, "hide", "Remove from sequence");
                rem.SetResourceReference(FrameworkElement.StyleProperty, "RedButton");
            }
            rem.IsEnabled = has;
            var res = _w.Ctl<Button>("SelRestoreBtn");
            int outN = St().LeftOut.Count;
            NsqUi.SetButton(res, "restore", outN > 0 ? outN.ToString() : "");
            res.IsEnabled = outN > 0 || _hideViews.Count > 0 || St().Gone.Count > 0;
            var rf = _w.Ctl<Button>("SelRefreshBtn");
            if (_stale)
            {
                NsqUi.SetButton(rf, "refresh", "Refresh - view changed");
                rf.SetResourceReference(FrameworkElement.StyleProperty, "HotButton");
            }
            else
            {
                NsqUi.SetButton(rf, "refresh", "Refresh from view");
                rf.SetResourceReference(FrameworkElement.StyleProperty, "AccentButton");
            }
        }

        /// <summary>Closing the window resets the isolate and puts the view colours back.</summary>
        public void OnClosed()
        {
            if (ReferenceEquals(_target, this)) _target = null;
            RemoveHooks(_w.Log);
            if (_isoViews.Count == 0 && !ColoursOn() && _hideViews.Count == 0 && _boxes.Count == 0) return;
            DebugLog log = _w.Log;
            Func<UIApplication, object> job = uiapp =>
            {
                int n = 0;
                // colours first, each step on its own: a view that will not reset must never leave the colours on
                try { n += RestoreAll(uiapp, null); } catch (Exception ex) { log.Add("close: colours failed: " + ex); }
                try { n += ClearLeftovers(uiapp, null); } catch (Exception ex) { log.Add("close: left-over colours failed: " + ex); }
                foreach (var kv in NsqRevit.OpenDocuments(uiapp))
                    foreach (ViewKey key in _isoViews.Keys.ToList())
                        if (key.Item1 == kv.Key)
                        {
                            ElementId vid = _isoViews[key]; _isoViews.Remove(key);
                            try { NsqRevit.ResetIsolateView(kv.Value, vid, _w.Log); } catch (Exception ex) { log.Add("close: isolate reset failed: " + ex); }
                            _hideViews.Remove(key);
                        }
                try { ShowHidden(uiapp); } catch (Exception ex) { log.Add("close: unhide failed: " + ex); }
                foreach (var kv in NsqRevit.OpenDocuments(uiapp))
                    foreach (ViewKey key in _boxes.Keys.ToList())
                        if (key.Item1 == kv.Key)
                        {
                            var b = _boxes[key]; _boxes.Remove(key);
                            try { NsqRevit.RestoreSectionBox(kv.Value, b.Item1, b.Item2, log); } catch (Exception ex) { log.Add("close: section box failed: " + ex); }
                        }
                log.Add("close: tidied, " + n + " colours off");
                log.Write();
                return n;
            };
            Action<object, string> done = (r, err) => Closing.Remove(_w);
            Closing.Add(_w);   // held until the job has run: nothing else references a closed window
            bool queued = false;
            try { queued = _w.Runner.Queue("tidy the view on close", job, done); }
            catch (Exception ex) { log.Add("close: queue failed: " + ex); }
            if (!queued)
            {
                // Revit refused the event: do it the next time Revit is idle
                UIApplication app = _w.UiApp;
                EventHandler<Autodesk.Revit.UI.Events.IdlingEventArgs> handler = null;
                handler = (s, e) =>
                {
                    try { app.Idling -= handler; } catch (Exception) { }
                    try { job(app); } catch (Exception ex) { log.Add("idle job failed: " + ex); }
                    finally { done(null, null); }
                };
                try { app.Idling += handler; } catch (Exception ex) { log.Add("could not wait for idle: " + ex); }
            }
        }

        // ---------------------------------------------------- family tree

        private void TreeChanged()
        {
            _w.Save();
            Recompute();
        }
    }
}


