using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.NumberSequencer;
using Border = System.Windows.Controls.Border;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using ComboBoxItem = System.Windows.Controls.ComboBoxItem;
using DockPanel = System.Windows.Controls.DockPanel;
using Grid = System.Windows.Controls.Grid;
using TextBox = System.Windows.Controls.TextBox;
using Panel = System.Windows.Controls.Panel;
using Point = System.Windows.Point;
using Control = System.Windows.Controls.Control;

namespace RevoBIM.UI.NumberSequencer
{
    /// <summary>One job queued for the ExternalEvent: a name, what to do in Revit, and what to do with the answer.</summary>
    public class NsqJob
    {
        public string Name;
        public Func<UIApplication, object> Fn;
        public Action<object, string> Done;
    }

    public class NsqHandler : IExternalEventHandler
    {
        public readonly DebugLog Log;
        public List<NsqJob> Jobs = new List<NsqJob>();

        public NsqHandler(DebugLog log) { Log = log; }

        public void Execute(UIApplication uiapp)
        {
            List<NsqJob> jobs = Jobs;
            Jobs = new List<NsqJob>();
            foreach (NsqJob job in jobs)
            {
                object res = null;
                string err = null;
                try { res = job.Fn(uiapp); }
                catch (Exception ex)
                {
                    err = ex.Message + "\n" + ex;
                    Log.Add("job " + job.Name + " failed: " + ex);
                }
                try { job.Done(res, err); }
                catch (Exception ex) { Log.Add("callback " + job.Name + " failed: " + ex); }
            }
        }

        public string GetName() { return "RevoBIM Number Sequencer"; }
    }

    /// <summary>Every read and write of the model goes out through one ExternalEvent; the window never waits for it.</summary>
    public class Runner
    {
        private readonly DebugLog _log;
        private readonly NsqHandler _handler;
        private readonly ExternalEvent _event;

        public Runner(DebugLog log)
        {
            _log = log;
            _handler = new NsqHandler(log);
            _event = ExternalEvent.Create(_handler);
        }

        /// <summary>Queue behind anything Pending; drop only this job if refused.</summary>
        public bool Queue(string name, Func<UIApplication, object> fn, Action<object, string> cb)
        {
            var job = new NsqJob { Name = name, Fn = fn, Done = cb };
            _handler.Jobs.Add(job);
            ExternalEventRequest status = _event.Raise();
            string text = status.ToString();
            _log.Add("raise " + name + ": " + text);
            if (text == "Accepted" || text == "Pending") return true;
            _handler.Jobs.Remove(job);
            try { cb(null, "Revit refused the request (" + text + ")"); } catch (Exception) { }
            return false;
        }
    }

    /// <summary>
    /// Number Sequencer: the modeless window (port of nsq_window.py). Revit stays usable behind it. Numbers every
    /// element along a duct, pipe or fabrication system into a parameter you choose - branches first, then on up the
    /// main - and can tag each numbered element.
    /// </summary>
    public partial class SequencerWindow
    {
        private static SequencerWindow _current;

        private const int WatchdogSeconds = 20;
        private const int ParamListMax = 400;
        private const double FamilyShare = 0.5;     // the selector's families grow to their full height, up to this share
        private const double SystemsReserve = 260;  // what the systems card needs below them

        private class SectionDef { public string Key, Btn, Body, Row; }
        private static readonly SectionDef[] SectionDefs =
        {
            new SectionDef { Key = "seq_sys", Btn = "SeqSysToggle", Body = "SeqSysBody" },
            new SectionDef { Key = "seq_fam", Btn = "SeqFamToggle", Body = "SeqFamBody", Row = "SeqFamRow" },
            new SectionDef { Key = "sel_fam", Btn = "SelFamToggle", Body = "SelFamBody" },
            new SectionDef { Key = "sel_sys", Btn = "SelSysToggle", Body = "SelSysBody", Row = "SelSysRow" },
            new SectionDef { Key = "start", Btn = "StartToggle", Body = "StartBody" },
            new SectionDef { Key = "param", Btn = "ParamToggle", Body = "ParamBody" },
            new SectionDef { Key = "sequence", Btn = "SequenceToggle", Body = "SequenceBody" },
        };

        public readonly UIApplication UiApp;
        public Dictionary<string, string> Settings;
        public DebugLog Log;
        public Runner Runner;
        public Window Win;
        public string Mode = "dark";
        public string Tab = "seq";
        public List<TagChoice> Tags = new List<TagChoice>();
        public SelectorTab Sel;
        public TagViewsPanel Views;

        private bool _busy;
        private NetworkData _data;
        private List<KeyValuePair<string, int>> _paramsPlaceholder;
        private List<NsqCore.ParamRow> _params = new List<NsqCore.ParamRow>();
        private Dictionary<long, string> _typeOf = new Dictionary<long, string>();
        private List<long> _order = new List<long>();
        private List<KeyValuePair<int, int>> _spans = new List<KeyValuePair<int, int>>();
        private List<SysDef> _systems = new List<SysDef>();
        private int _selSys = -1;
        private int _sysSeq;
        private List<TextBlock> _sysRows = new List<TextBlock>();
        private string _paramName;
        private List<NsqCore.ParamRow> _paramHits = new List<NsqCore.ParamRow>();
        private List<Border> _paramItems = new List<Border>();
        private int _paramHi = -1;
        private bool _paramTyping;
        private HashSet<string> _skipped;
        private List<TagChoice> _tagView = new List<TagChoice>();
        private double? _foldBatch;
        private Window _tagwin;
        private Chrome _tagchrome;
        private bool _tagClosing;
        private Tuple<List<ElementId>, bool> _wantSelect;
        private bool _selectQueued;
        private List<NsqCore.KeyMsg> _lastErrors = new List<NsqCore.KeyMsg>();
        private bool _loading = true;
        private Chrome _chrome;
        private DispatcherTimer _watchdog;
        private FamilyTree _tree;
        private Dictionary<string, Section> _sections = new Dictionary<string, Section>();

        // ---------------------------------------------------- the window

        public SequencerWindow(UIApplication uiapp)
        {
            UiApp = uiapp;
            Settings = NsqCore.LoadSettings();
            Log = new DebugLog(Settings["debug"] != "off");
            Log.Add("Number Sequencer " + NsqCore.Version);
            Log.Add(NsqCore.BuildInfo());
            try { Log.Add("Revit " + uiapp.Application.VersionNumber); } catch (Exception) { }
            Runner = new Runner(Log);
            _skipped = NsqCore.SkipKeysFrom(Settings["skip"]);

            Win = (Window)NsqUi.LoadXaml("NumberSequencer.xaml");
            NsqUi.MergeTheme(Win);
            try { NsqUi.Iconize(Win); } catch (Exception) { }
            Ctl<TextBlock>("VersionText").Text = "v" + NsqCore.Version;
            ImageSourceHolder.Set(Ctl<System.Windows.Controls.Image>("HeaderIcon"));
            ApplyTheme();
            _chrome = new Chrome(Win, Ctl<Border>("HeaderBar"), Ctl<Button>("FullBtn"), Ctl<Button>("CloseBtn"), Ctl<FrameworkElement>("RevoText"), Ctl<Button>("MinBtn"));
            EggHook.Attach(Win, () => Mode, Ctl<UIElement>("RevoText"), Ctl<UIElement>("HeaderIcon"));
            NsqUi.OwnToRevit(Win, uiapp);
            // the size it was closed at (folded sections shrank it), then the screen's limits
            int ww = NsqCore.ToInt(Settings["win_w"], 0);
            int wh = NsqCore.ToInt(Settings["win_h"], 0);
            if (ww > 200) Win.Width = ww;
            if (wh > 200) Win.Height = wh;
            NsqUi.FitToScreen(Win);

            _watchdog = new DispatcherTimer { Interval = TimeSpan.FromSeconds(WatchdogSeconds) };
            _watchdog.Tick += (s, e) => Try("watchdog", OnWatchdog);

            _tree = new FamilyTree(Ctl<StackPanel>("TreeHost"), Ctl<TextBlock>("CountText"), Ctl<TextBox>("SearchBox"), () => Mode, _skipped, OnTreeChanged, OnTreeSelect);
            _tree.TryRun = Try;
            Sel = new SelectorTab(this);
            Views = new TagViewsPanel(this);
            RestoreControls();
            Wire();
            BuildSections();
            _loading = false;
        }

        public T Ctl<T>(string name) where T : class
        {
            object o = Win.FindName(name);
            if (o == null) throw new InvalidOperationException("Layout control missing: " + name);
            return (T)o;
        }

        /// <summary>Run a handler; a failure is logged, never thrown into Revit.</summary>
        public void Try(string name, Action fn)
        {
            try { fn(); }
            catch (Exception ex)
            {
                Log.Add("handler " + name + " failed: " + ex);
                Status("Something went wrong - tick Debug and Copy debug");
            }
        }

        private void On<T>(string name, Action fn) where T : ButtonBase
        {
            Ctl<T>(name).Click += (s, e) => Try(name, fn);
        }

        private void Wire()
        {
            On<Button>("ThemeBtn", OnTheme);
            Ctl<RadioButton>("TabSeq").Checked += (s, e) => Try("tab", OnTab);
            Ctl<RadioButton>("TabSel").Checked += (s, e) => Try("tab", OnTab);
            On<Button>("AddSelBtn", () => QueueBusy("add selection", JobAddSelection, Added, "Reading the Revit selection"));
            On<Button>("PickSysBtn", () => QueueBusy("pick systems", JobPickSystems, Added, "Click the first element of each system, in order - Esc when done"));
            On<Button>("SysUpBtn", OnSysUp);
            On<Button>("SysDownBtn", OnSysDown);
            On<Button>("SysRemoveBtn", OnSysRemove);
            On<Button>("SysClearBtn", OnSysClear);
            On<Button>("PickStartBtn", OnPickStart);
            On<Button>("AutoStartBtn", OnAutoStart);
            On<Button>("ShowStartBtn", OnShowStart);
            On<Button>("ExpandAllBtn", () => _tree.ExpandAll());
            On<Button>("CollapseAllBtn", () => _tree.CollapseAll());
            On<Button>("TickAllBtn", () => { if (_data != null) _tree.TickAll(); });
            On<Button>("UntickAllBtn", () => { if (_data != null) _tree.UntickAll(); });
            Ctl<TextBox>("SearchBox").TextChanged += (s, e) => Try("search", () => _tree.Build());
            var pb = Ctl<TextBox>("ParamBox");
            pb.TextChanged += (s, e) => Try("param typed", OnParamTyped);
            pb.PreviewKeyDown += (s, e) => Try("param keys", () => OnParamKeys(e));
            pb.PreviewMouseLeftButtonDown += (s, e) => Try("param mouse", () => OnParamMouse(e));
            pb.GotKeyboardFocus += (s, e) => Try("param focus", () => pb.SelectAll());
            pb.LostKeyboardFocus += (s, e) => Try("param left", OnParamLeft);
            On<Button>("ParamDrop", () => { ShowParamList(""); Ctl<TextBox>("ParamBox").Focus(); });
            foreach (string n in new[] { "Fmt3", "Fmt2", "Fmt1", "DirUp", "DirDown" })
                Ctl<RadioButton>(n).Checked += (s, e) => Try("sequence", OnSequenceChanged);
            Ctl<TextBox>("StartBox").TextChanged += (s, e) => Try("sequence", OnSequenceChanged);
            On<CheckBox>("TagCheck", OnTagChanged);
            Ctl<ComboBox>("TagCombo").SelectionChanged += (s, e) => Try("tag", OnTagChanged);
            On<CheckBox>("TagUntaggedCheck", OnTagChanged);
            foreach (string n in new[] { "TagLeaderCheck", "TagElbowCheck", "TagRemoveCheck", "TagUntangleCheck" }) On<CheckBox>(n, OnTagChanged);
            foreach (string n in new[] { "TagScopeView", "TagScopeTicked" }) Ctl<RadioButton>(n).Checked += (s, e) => Try("tag scope", OnTagChanged);
            foreach (string n in new[] { "TagOffX", "TagOffY", "TagElbowMm" }) Ctl<TextBox>(n).TextChanged += (s, e) => Try("tag option", OnTagChanged);
            On<CheckBox>("DebugCheck", OnDebug);
            On<Button>("CopyDebugBtn", OnCopyDebug);
            On<Button>("ApplyBtn", OnApply);
            Win.Activated += (s, e) => Try("activated", OnActivated);
            Win.Closed += (s, e) => Try("closed", OnClosed);
            WirePosition();
        }

        // ---------------------------------------------------- folding sections, the tag drawer

        private void BuildSections()
        {
            var shut = new HashSet<string>((Settings["collapsed"] ?? "").Split(new[] { NsqCore.SkipSep }, StringSplitOptions.None).Where(k => k.Length > 0));
            _sections = new Dictionary<string, Section>();
            foreach (SectionDef d in SectionDefs)
            {
                RowDefinition row = d.Row != null ? Ctl<RowDefinition>(d.Row) : null;
                _sections[d.Key] = new Section(d.Key, Ctl<Button>(d.Btn), Ctl<FrameworkElement>(d.Body), row, SectionChanged, shut.Contains(d.Key), SectionResize);
            }
            Ctl<FrameworkElement>("SelPane").SizeChanged += (s, e) => Try("main size", OnMainSize);
            On<Button>("FoldAllBtn", OnFoldAll);
            RefreshFoldAll();
            NsqUi.SetIconData(Ctl<System.Windows.Shapes.Path>("TagOpenIcon"), "tag");
            On<Button>("TagOpenBtn", OnTagOpen);
            RefreshTagOpen();
        }

        private List<Section> TabSections()
        {
            var own = Tab == "sel" ? new[] { "sel_fam", "sel_sys" } : new[] { "seq_sys", "seq_fam" };
            return own.Concat(new[] { "start", "param", "sequence" }).Where(_sections.ContainsKey).Select(k => _sections[k]).ToList();
        }

        private void RefreshFoldAll()
        {
            var btn = Ctl<Button>("FoldAllBtn");
            if (TabSections().Any(s => s.Open)) NsqUi.SetButton(btn, "collapse", "Collapse all");
            else NsqUi.SetButton(btn, "expand", "Expand all");
        }

        /// <summary>Fold every section on the tab (any open) or open them all. The window moves once, by the total.</summary>
        private void OnFoldAll()
        {
            List<Section> secs = TabSections();
            bool open = !secs.Any(s => s.Open);
            _foldBatch = 0.0;
            double total;
            try { foreach (Section s in secs) s.Set(open); }
            finally { total = _foldBatch ?? 0.0; _foldBatch = null; }
            SectionResize(total);
            RefreshFoldAll();
        }

        /// <summary>A section folded or opened: the window shrinks or grows by what it gave up or takes back.</summary>
        private void SectionResize(double delta)
        {
            if (_foldBatch != null) { _foldBatch += delta; return; }   // Collapse / Expand all: one move for the lot
            if (_loading || _chrome.Full || _chrome.Shrunk) return;
            Window w = Win;
            double h0 = w.ActualHeight;
            double[] area = NsqUi.WorkArea(w);
            double most = area != null ? area[3] - w.Top : h0 + delta;
            double to = Math.Max(w.MinHeight, Math.Min(most, h0 + delta));
            if (Math.Abs(to - h0) < 1.0) return;
            _chrome.ClearTall();
            NsqUi.Animate(w, FrameworkElement.HeightProperty, to, h0);
        }

        private void SectionChanged(string key, bool open)
        {
            if (_loading) return;
            if (_foldBatch == null) RefreshFoldAll();
            var shut = _sections.Where(kv => !kv.Value.Open).Select(kv => kv.Key).OrderBy(x => x, StringComparer.Ordinal);
            Settings["collapsed"] = string.Join(NsqCore.SkipSep, shut);
            Save();
        }

        /// <summary>The selector's families show in full, up to a share of its pane - never so tall the systems table loses its room.</summary>
        private void OnMainSize()
        {
            double h = Ctl<FrameworkElement>("SelPane").ActualHeight;
            Ctl<ScrollViewer>("SelTreeScroll").MaxHeight = Math.Max(80.0, Math.Min(h * FamilyShare, h - SystemsReserve) - 70.0);
        }

        private bool ScopeTicked() { return Ctl<RadioButton>("TagScopeTicked").IsChecked == true; }

        private double Mm(string name)
        {
            double v;
            return double.TryParse((Ctl<TextBox>(name).Text ?? "").Trim(), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out v) ? v : 0;
        }

        private string TagSummary()
        {
            int n = Views != null && ScopeTicked() ? Views.TickedCount() : 0;
            if (Ctl<CheckBox>("TagCheck").IsChecked != true) return "tags off" + (n > 0 ? " - " + n + " view(s) ticked" : "");
            return "tags on - " + (n > 0 ? n + " view(s) ticked" : "the active view");
        }

        private void RefreshTagOpen()
        {
            string text = TagSummary();
            Ctl<TextBlock>("TagOpenNote").Text = text;
            if (_tagwin != null)
            {
                try { ((TextBlock)_tagwin.FindName("TStatus")).Text = char.ToUpper(text[0]) + text.Substring(1) + ". Apply to go back, then Run Sequence."; }
                catch (Exception) { }
            }
        }

        // ---------------------------------------------------- the Tag Views or Sheets window

        /// <summary>A bigger window for the tag, the sheets and the views. Their controls move into it while it is open.</summary>
        private void OnTagOpen()
        {
            if (_tagwin != null) { _tagwin.Activate(); return; }
            var tw = (Window)NsqUi.LoadXaml("NumberSequencerTags.xaml");
            NsqUi.MergeTheme(tw);
            NsqUi.ApplyPalette(tw, Mode);
            try { NsqUi.Iconize(tw); } catch (Exception) { }
            tw.Owner = Win;
            Func<string, object> f = tw.FindName;
            ((TextBlock)f("TVersion")).Text = "v" + NsqCore.Version;
            ((TextBlock)f("TThemeText")).Text = NsqCore.ThemeLabel(Settings["theme"]);
            ImageSourceHolder.Set((System.Windows.Controls.Image)f("TIcon"));
            var content = Ctl<UIElement>("TagContent");
            Ctl<Border>("TagStore").Child = null;
            ((Border)f("THost")).Child = content;
            _tagwin = tw;
            _tagClosing = false;
            _tagchrome = new Chrome(tw, (Border)f("THeader"), (Button)f("TFullBtn"), (Button)f("TCloseX"), null, (Button)f("TMinBtn"), CloseTagWin);
            ((Button)f("TApplyBtn")).Click += (s, e) => Try("tag apply", CloseTagWin);
            ((Button)f("TThemeBtn")).Click += (s, e) => Try("tag theme", () =>
            {
                OnTheme();
                ((TextBlock)f("TThemeText")).Text = NsqCore.ThemeLabel(Settings["theme"]);
            });
            tw.Closed += (s, e) => Try("tag closed", () =>
            {
                // the controls go home before anything else can touch them
                ((Border)f("THost")).Child = null;
                Ctl<Border>("TagStore").Child = content;
                _tagwin = null;
                RefreshPreview();
                Status(Capitalise(TagSummary()) + " - press Run Sequence");
                try { Ctl<Button>("ApplyBtn").Focus(); } catch (Exception) { }
            });
            if (Ctl<CheckBox>("TagCheck").IsChecked != true)
            {
                // opening Tag Views or Sheets means tagging: switch it on
                Ctl<CheckBox>("TagCheck").IsChecked = true;
                OnTagChanged();
            }
            RefreshTagOpen();
            tw.Show();
        }

        private static string Capitalise(string s) { return string.IsNullOrEmpty(s) ? s : char.ToUpper(s[0]) + s.Substring(1); }

        private void CloseTagWin()
        {
            Window tw = _tagwin;
            if (tw == null || _tagClosing) return;
            _tagClosing = true;
            try { tw.Close(); } catch (Exception) { }
        }

        /// <summary>After a run that tagged in ticked views: offer to open them.</summary>
        private void OfferOpen(TagJob tag)
        {
            if (tag == null || tag.Views.Count == 0) return;
            List<long> viewIds;
            List<SheetData> sheets = NsqCore.OpenList(Views.Sheets, Views.TickedIdsHere(), out viewIds);
            var byId = Views.Rows.ToDictionary(r => long.Parse(r.Id), r => r.Eid);
            var ids = sheets.Select(sh => sh.Eid).Concat(viewIds.Where(byId.ContainsKey).Select(v => byId[v])).ToList();
            if (ids.Count == 0) return;
            var what = new List<string>();
            if (sheets.Count > 0) what.Add(sheets.Count + " sheet" + (sheets.Count == 1 ? "" : "s"));
            if (viewIds.Count > 0) what.Add(viewIds.Count + " view" + (viewIds.Count == 1 ? "" : "s"));
            string msg = "The sequence is applied and tagged. Open the " + string.Join(" and ", what) + " you ticked?";
            if (ids.Count > 15) msg += " (" + ids.Count + " tabs will open.)";
            if (!NsqUi.AskYesNo(Win, Mode, "Open the tagged views", msg, "Open them", "Not now")) return;
            Runner.Queue("open tagged views", uiapp => NsqRevit.OpenViews(uiapp.ActiveUIDocument, ids, Log),
                         (n, err) => Status(err != null ? "Could not open them all - see debug" : "Opened " + (n ?? 0) + " view(s) / sheet(s)"));
        }

        private void RestoreControls()
        {
            var s = Settings;
            int pad = NsqCore.ToInt(s["pad"], 3);
            Ctl<RadioButton>(pad == 3 ? "Fmt3" : pad == 2 ? "Fmt2" : "Fmt1").IsChecked = true;
            Ctl<RadioButton>(s["direction"] == "down" ? "DirDown" : "DirUp").IsChecked = true;
            Ctl<TextBox>("StartBox").Text = string.IsNullOrEmpty(s["start"]) ? "1" : s["start"];
            Ctl<CheckBox>("TagCheck").IsChecked = s["tag"] == "on";
            Ctl<CheckBox>("TagUntaggedCheck").IsChecked = s["tag_untagged"] != "off";
            Ctl<RadioButton>(s["tag_scope"] == "ticked" ? "TagScopeTicked" : "TagScopeView").IsChecked = true;
            Ctl<CheckBox>("TagLeaderCheck").IsChecked = s["tag_leader"] == "on";
            Ctl<TextBox>("TagOffX").Text = s["tag_offx"];
            Ctl<TextBox>("TagOffY").Text = s["tag_offy"];
            Ctl<CheckBox>("TagElbowCheck").IsChecked = s["tag_elbow"] == "on";
            Ctl<TextBox>("TagElbowMm").Text = s["tag_elbow_mm"];
            Ctl<CheckBox>("TagRemoveCheck").IsChecked = s["tag_remove"] == "on";
            Ctl<CheckBox>("TagUntangleCheck").IsChecked = s["tag_untangle"] == "on";
            Ctl<CheckBox>("DebugCheck").IsChecked = Log.Enabled;
            Ctl<TextBlock>("ThemeText").Text = NsqCore.ThemeLabel(s["theme"]);
            Ctl<RadioButton>(s["tab"] == "sel" ? "TabSel" : "TabSeq").IsChecked = true;
        }

        // ---------------------------------------------------- theme

        private bool ApplyTheme()
        {
            bool? dark = NsqUi.CanvasIsDark(UiApp);
            string mode = NsqCore.ResolveTheme(Settings["theme"], dark);
            bool changed = mode != Mode;
            Mode = mode;
            NsqUi.ApplyPalette(Win, mode);
            if (_tagwin != null) NsqUi.ApplyPalette(_tagwin, mode);
            return changed;
        }

        private void OnTheme()
        {
            Settings["theme"] = NsqCore.NextTheme(Settings["theme"]);
            Ctl<TextBlock>("ThemeText").Text = NsqCore.ThemeLabel(Settings["theme"]);
            ApplyTheme();
            BuildTree();
            Sel.Rebuild();
            RefreshPreview();
            Save();
        }

        private void OnActivated()
        {
            if (Tab == "sel") Sel.CheckView();
            if (Settings["theme"] == "auto" && ApplyTheme())
            {
                BuildTree();
                Sel.Rebuild();
                RefreshPreview();
            }
        }

        // ---------------------------------------------------- tabs

        private void OnTab()
        {
            if (_loading) return;
            ShowTab(Ctl<RadioButton>("TabSel").IsChecked == true ? "sel" : "seq");
        }

        private void ShowTab(string tab)
        {
            Tab = tab;
            Settings["tab"] = tab;
            NsqUi.Show(Ctl<UIElement>("SeqPane"), tab == "seq");
            NsqUi.Show(Ctl<UIElement>("SelPane"), tab == "sel");
            // the selector has its own Pick start / Auto Re-order under Duct / Pipe
            NsqUi.Show(Ctl<UIElement>("PickStartBtn"), tab == "seq");
            NsqUi.Show(Ctl<UIElement>("AutoStartBtn"), false);
            Ctl<TextBlock>("StartHead").Text = tab == "seq" ? "Start point" : "Start point of the sequence";
            if (tab == "sel") Sel.Activate();
            RefreshShared();
            RefreshFoldAll();
            Save();
        }

        private void RefreshShared()
        {
            RefreshParams();
            FillTags();
            RefreshStart();
            RefreshPreview();
        }

        /// <summary>The System Selector changed what is numbered.</summary>
        public void SelChanged(bool parms = true)
        {
            if (Tab != "sel") return;
            if (parms) RefreshParams();
            FillTags();
            RefreshStart();
            RefreshPreview();
        }

        /// <summary>Elements of the selected system(s), for Find views with this system.</summary>
        public List<ElementId> FindKeys(out string label)
        {
            label = "";
            List<long> keys;
            Dictionary<long, ElementId> idmap;
            if (Tab == "sel")
            {
                keys = Sel.PickedKeys(out label);
                idmap = Sel.St().Data != null ? Sel.St().Data.IdMap : new Dictionary<long, ElementId>();
            }
            else if (_selSys >= 0 && _selSys < _systems.Count)
            {
                SysDef sd = _systems[_selSys];
                keys = sd.Keys.ToList();
                label = sd.Name;
                idmap = _data != null ? _data.IdMap : new Dictionary<long, ElementId>();
            }
            else return new List<ElementId>();
            return keys.Where(idmap.ContainsKey).Select(k => idmap[k]).ToList();
        }

        /// <summary>What the shared options act on: the active tab's sequence.</summary>
        private NumSource Src()
        {
            if (Tab == "sel") return Sel.Source();
            NetworkData d = _data;
            var keys = d != null ? d.Nodes.Keys.ToList() : new List<long>();
            return new NumSource
            {
                Order = _order, Include = IncludeKey,
                IdMap = d != null ? d.IdMap : new Dictionary<long, ElementId>(),
                Labels = d != null ? d.Labels : new Dictionary<long, string>(),
                HostCat = d != null ? d.HostCat : new Dictionary<long, string>(),
                Storages = d != null ? d.Storages : new Dictionary<string, string>(),
                PerElem = d != null ? d.PerElem : new Dictionary<long, List<string>>(),
                Keys = keys, Total = keys.Count, Has = _systems.Count > 0, Systems = _systems.Count, Kind = "duct", PlansOnly = false,
                ViewType = "", Verb = "Apply", After = null, EmptyHint = "Add a system to list its parameters",
            };
        }

        // ---------------------------------------------------- status / busy

        public void Status(string text)
        {
            try { Ctl<TextBlock>("StatusText").Text = text; } catch (Exception) { }
        }

        private void SetBusy(bool busy)
        {
            _busy = busy;
            if (busy) _watchdog.Start(); else _watchdog.Stop();
            RefreshApply();
        }

        private void OnWatchdog()
        {
            _watchdog.Stop();
            if (_busy)
            {
                Log.Add("watchdog freed a busy window");
                _busy = false;
                Status("Revit did not answer - try again");
                RefreshApply();
            }
        }

        public void QueueBusy(string name, Func<UIApplication, object> fn, Action<object, string> cb, string status)
        {
            if (_busy)
            {
                Log.Add("click ignored while busy: " + name);
                Status("Busy - waiting for Revit");
                return;
            }
            SetBusy(true);
            Status(status);
            Runner.Queue(name, fn, (res, err) => { SetBusy(false); cb(res, err); });
        }

        // ---------------------------------------------------- reading

        /// <summary>At launch we are inside the command, so read directly.</summary>
        public void ReadNow(UIApplication uiapp)
        {
            object res = JobAddSelection(uiapp);
            Added(res, null);
            Views.LoadNow(uiapp);
            if (Settings["tab"] == "sel")
            {
                Sel.ReadNow(uiapp);
                ShowTab("sel");
            }
        }

        private HashSet<long> Known() { return _data != null ? new HashSet<long>(_data.Nodes.Keys) : new HashSet<long>(); }

        private class AddResult
        {
            public List<NetworkData> Reads = new List<NetworkData>();
            public HashSet<long> Starts = new HashSet<long>();
            public List<TagChoice> Tags;
            public bool Positional;
            public bool AllInView;
            public NsqRevit.ViewFrame Frame;
        }

        private NetworkData Read(Document doc, List<Element> elems)
        {
            NetworkData data = NsqRevit.ReadNetwork(doc, elems, Log);
            NsqRevit.ParamMap(elems, out data.Storages, out data.PerElem);
            return data;
        }

        private object JobAddSelection(UIApplication uiapp)
        {
            if (PosOn()) return JobAddPositional(uiapp);
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            List<ElementId> ids = uidoc.Selection.GetElementIds().ToList();
            HashSet<long> known = Known();
            var elems = NsqRevit.ExpandSelection(doc, ids).Where(e => !known.Contains(NsqRevit.EidValue(e.Id))).ToList();
            Log.Add("add selection: " + ids.Count + " ids -> " + elems.Count + " new duct elements");
            var res = new AddResult { Tags = NsqRevit.TagChoices(doc) };
            if (elems.Count > 0) res.Reads.Add(Read(doc, elems));
            return res;
        }

        /// <summary>Pick the first element of each system in turn until Escape.</summary>
        private object JobPickSystems(UIApplication uiapp)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            HashSet<long> known = Known();
            var res = new AddResult();
            while (true)
            {
                int n = _systems.Count + res.Reads.Count + 1;
                Element el = NsqRevit.PickDuctElement(uidoc, "RevoBIM Number Sequencer: click the first element of system " + n + " - Esc when done");
                if (el == null) break;
                long k = NsqRevit.EidValue(el.Id);
                res.Starts.Add(k);
                if (known.Contains(k)) continue;   // already listed: it just becomes that system's start
                var elems = NsqRevit.CollectNetwork(doc, el).Where(e => !known.Contains(NsqRevit.EidValue(e.Id))).ToList();
                foreach (Element e in elems) known.Add(NsqRevit.EidValue(e.Id));
                Log.Add("picked " + k + ": " + elems.Count + " new elements");
                if (elems.Count > 0) res.Reads.Add(Read(doc, elems));
            }
            if (res.Reads.Count == 0 && res.Starts.Count == 0) return null;
            res.Tags = NsqRevit.TagChoices(doc);
            return res;
        }

        private object JobPickStart(UIApplication uiapp)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            Element el = NsqRevit.PickDuctElement(uidoc, "RevoBIM Number Sequencer: click the element to start numbering from");
            if (el == null) return null;
            long k = NsqRevit.EidValue(el.Id);
            var res = new AddResult();
            res.Starts.Add(k);
            if (Known().Contains(k)) return res;
            HashSet<long> known = Known();
            var elems = NsqRevit.CollectNetwork(doc, el).Where(e => !known.Contains(NsqRevit.EidValue(e.Id))).ToList();
            if (elems.Count > 0) res.Reads.Add(Read(doc, elems));
            return res;
        }

        private void OnPickStart()
        {
            if (Tab == "sel") { Sel.PickStart(); return; }
            PickFirst();
        }

        private void Added(object resObj, string err)
        {
            if (err != null) { Status("Could not read - see debug"); return; }
            var res = resObj as AddResult;
            if (res == null) { Status("Cancelled"); return; }
            if (res.Positional) { AddedPositional(res); return; }
            if (res.Tags != null) { Tags = res.Tags; FillTags(); }
            int moved = 0;
            for (int i = 0; i < _systems.Count; i++)
                foreach (long k in res.Starts)
                    if (_systems[i].Keys.Contains(k)) { _systems[i].Start = k; _selSys = i; moved++; }
            int added = 0;
            foreach (NetworkData data in res.Reads)
            {
                List<long> newKeys = Merge(data);
                if (newKeys.Count == 0) continue;
                var comps = NsqCore.Components(_data.Nodes, newKeys);
                var starts = res.Starts.ToDictionary(k => k, k => true);
                foreach (var cs in OrderSystems(_data.Nodes, comps, res.Starts, ExitPoint()))
                {
                    AppendSystem(cs.Key, cs.Value);
                    added++;
                }
            }
            RefreshAll();
            if (added > 0) Status("Added " + added + " system(s) - " + _systems.Count + " in the sequence");
            else if (moved > 0) Status("Start moved");
            else if (_systems.Count == 0) Status("Nothing with duct connectors selected - tab-select duct systems, or Pick systems");
            else Status("Nothing new - those elements are already in the sequence");
        }

        /// <summary>Order new systems: the one holding a picked start first, else the nearest from the point, else the auto start; then each next the nearest to where the last finished.</summary>
        private static List<KeyValuePair<List<long>, long?>> OrderSystems(Dictionary<long, Node> nodes, List<List<long>> comps, HashSet<long> starts, double[] fromPoint)
        {
            var left = comps.Select(c => new List<long>(c)).ToList();
            var o = new List<KeyValuePair<List<long>, long?>>();
            Func<List<long>, long?> startIn = comp => { foreach (long k in comp) if (starts.Contains(k)) return k; return null; };
            List<long> first = left.FirstOrDefault(c => startIn(c) != null);
            if (first == null && left.Count > 0 && fromPoint != null)
                first = left.OrderBy(c => NsqCore.CompDistance(nodes, c, fromPoint)).ThenBy(c => c[0]).First();
            if (first == null && left.Count > 0)
            {
                var allKeys = left.SelectMany(c => c).ToList();
                var sub = allKeys.ToDictionary(k => k, k => nodes[k]);
                long? pick = NsqCore.ChooseStart(sub, allKeys);
                first = left.FirstOrDefault(c => pick != null && c.Contains(pick.Value));
            }
            while (first != null)
            {
                left.Remove(first);
                long? st = startIn(first);
                o.Add(new KeyValuePair<List<long>, long?>(first, st));
                List<long> order = NsqCore.SystemOrder(nodes, first, st);
                double[] exit = order.Count > 0 ? NsqCore.NodePoint(nodes[order[order.Count - 1]]) : null;
                if (left.Count == 0) break;
                if (exit == null) first = left[0];
                else { double[] ex = exit; first = left.OrderBy(c => NsqCore.CompDistance(nodes, c, ex)).ThenBy(c => c[0]).First(); }
            }
            return o;
        }

        // ---------------------------------------------------- the model held

        private List<long> Merge(NetworkData data)
        {
            if (_data == null) _data = new NetworkData();
            NetworkData d = _data;
            var newKeys = data.Nodes.Keys.Where(k => !d.Nodes.ContainsKey(k)).ToList();
            foreach (long k in newKeys)
            {
                d.Nodes[k] = data.Nodes[k];
                string s; ElementId id; List<string> pe;
                if (data.IdMap.TryGetValue(k, out id)) d.IdMap[k] = id;
                if (data.HostCat.TryGetValue(k, out s)) d.HostCat[k] = s;
                if (data.Labels.TryGetValue(k, out s)) d.Labels[k] = s;
                if (data.SysName.TryGetValue(k, out s)) d.SysName[k] = s;
                if (data.PerElem.TryGetValue(k, out pe)) d.PerElem[k] = pe;
                double[] pt;
                if (data.Points.TryGetValue(k, out pt)) d.Points[k] = pt;
            }
            var newSet = new HashSet<long>(newKeys);
            foreach (NsqCore.TreeRow row in data.Rows)
                if (newSet.Contains(row.ElementKey))
                {
                    d.Rows.Add(row);
                    _typeOf[row.ElementKey] = NsqCore.TypeKey(row.Category, row.Family, row.Type);
                }
            foreach (var kv in data.Storages) if (!d.Storages.ContainsKey(kv.Key)) d.Storages[kv.Key] = kv.Value;
            return newKeys;
        }

        private void DropKeys(IEnumerable<long> keys)
        {
            NetworkData d = _data;
            if (d == null) return;
            var gone = new HashSet<long>(keys);
            foreach (long k in gone)
            {
                d.Nodes.Remove(k); d.IdMap.Remove(k); d.HostCat.Remove(k); d.Labels.Remove(k); d.SysName.Remove(k); d.PerElem.Remove(k);
                _typeOf.Remove(k);
            }
            d.Rows = d.Rows.Where(r => !gone.Contains(r.ElementKey)).ToList();
        }

        private void AppendSystem(List<long> comp, long? start)
        {
            _sysSeq++;
            string name = NsqCore.SystemName(comp, _data.SysName, "System " + _sysSeq);
            _systems.Add(new SysDef { Keys = new List<long>(comp), Start = start, Name = name });
            _selSys = _systems.Count - 1;
            Log.Add("system " + _systems.Count + ": " + name + ", " + comp.Count + " elements, start " + start);
        }

        /// <summary>Where the last listed system finishes - the next one starts nearest it.</summary>
        private double[] ExitPoint()
        {
            if (_systems.Count == 0 || _data == null) return null;
            SysDef last = _systems[_systems.Count - 1];
            List<long> order = NsqCore.SystemOrder(_data.Nodes, last.Keys, last.Start);
            return order.Count == 0 ? null : NsqCore.NodePoint(_data.Nodes[order[order.Count - 1]]);
        }

        private void RefreshAll()
        {
            RefreshParams();
            RecomputeOrder();
            BuildTree();
        }

        private void RefreshParams()
        {
            NumSource src = Src();
            _params = src.Keys.Count > 0 ? NsqCore.ParamList(src.Storages, src.PerElem, src.Keys) : new List<NsqCore.ParamRow>();
            FillParams();
        }

        // ---------------------------------------------------- systems list

        private void RecomputeOrder()
        {
            if (PosSystem()) { PosRecompute(); return; }
            if (_systems.Count == 0 || _data == null) { _order = new List<long>(); _spans = new List<KeyValuePair<int, int>>(); }
            else
            {
                _order = new List<long>();
                _spans = new List<KeyValuePair<int, int>>();
                foreach (SysDef sd in _systems)
                {
                    int a = _order.Count;
                    _order.AddRange(NsqCore.SystemOrder(_data.Nodes, sd.Keys, sd.Start));
                    _spans.Add(new KeyValuePair<int, int>(a, _order.Count));
                }
                Log.Add("walk: " + _order.Count + " elements over " + _systems.Count + " system(s)");
            }
            if (_systems.Count > 0) _selSys = Math.Max(0, Math.Min(_selSys, _systems.Count - 1));
            else _selSys = -1;
            BuildSystems();
            RefreshStart();
            RefreshPreview();
        }

        private void BuildSystems()
        {
            var host = Ctl<StackPanel>("SystemHost");
            host.Children.Clear();
            _sysRows = new List<TextBlock>();
            for (int i = 0; i < _systems.Count; i++)
            {
                int idx = i;
                SysDef sd = _systems[i];
                var row = new Border { CornerRadius = new CornerRadius(3), Margin = new Thickness(0, 1, 0, 1), Padding = new Thickness(4, 3, 8, 3), Cursor = Cursors.Hand };
                if (i == _selSys) row.SetResourceReference(Border.BackgroundProperty, "Sel");
                var grid = new Grid();
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(26) });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                var badge = new Border { Width = 20, Height = 20, CornerRadius = new CornerRadius(10) };
                badge.SetResourceReference(Border.BackgroundProperty, "Orange");
                var num = new TextBlock { Text = (i + 1).ToString(), FontSize = 11, FontWeight = FontWeights.SemiBold, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
                num.SetResourceReference(TextBlock.ForegroundProperty, "OnAccent");
                badge.Child = num;
                Grid.SetColumn(badge, 0);
                grid.Children.Add(badge);
                var name = new TextBlock { Text = sd.Name + (sd.Start != null ? "   (picked start)" : ""), Margin = new Thickness(4, 0, 6, 0), VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis };
                name.SetResourceReference(TextBlock.ForegroundProperty, "Text");
                Grid.SetColumn(name, 1);
                grid.Children.Add(name);
                var rng = new TextBlock { Margin = new Thickness(0, 0, 10, 0), VerticalAlignment = VerticalAlignment.Center };
                rng.SetResourceReference(TextBlock.ForegroundProperty, "Blue");
                Grid.SetColumn(rng, 2);
                grid.Children.Add(rng);
                var cnt = new TextBlock { Text = sd.Keys.Count + " el.", VerticalAlignment = VerticalAlignment.Center };
                cnt.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
                Grid.SetColumn(cnt, 3);
                grid.Children.Add(cnt);
                row.Child = grid;
                row.ToolTip = "Click to choose, double-click to select this system in Revit";
                row.MouseLeftButtonDown += (s, e) => Try("system click", () => SysClick(idx, e));
                host.Children.Add(row);
                _sysRows.Add(rng);
            }
            int n = _systems.Count;
            Ctl<TextBlock>("SysCountText").Text = n > 0 ? n + " system" + (n == 1 ? "" : "s") : "";
            bool has = _selSys >= 0 && _selSys < n;
            Ctl<Button>("SysUpBtn").IsEnabled = has && _selSys > 0;
            Ctl<Button>("SysDownBtn").IsEnabled = has && _selSys < n - 1;
            Ctl<Button>("SysRemoveBtn").IsEnabled = has;
            Ctl<Button>("SysClearBtn").IsEnabled = n > 0;
        }

        private void SysClick(int index, MouseButtonEventArgs e)
        {
            if (e.ClickCount == 2)
            {
                var ids = _systems[index].Keys.Where(_data.IdMap.ContainsKey).Select(k => _data.IdMap[k]).ToList();
                SelectIds(ids);
                e.Handled = true;
                return;
            }
            _selSys = index;
            BuildSystems();
            List<NsqCore.KeyMsg> errs; int? start;
            RefreshSystemRanges(Plan(null, out errs, out start));
            RefreshStart();
            e.Handled = true;
        }

        private void RefreshSystemRanges(List<NsqCore.PlanItem> plan)
        {
            if (_sysRows.Count == 0) return;
            var orderLists = _spans.Select(sp => _order.Skip(sp.Key).Take(sp.Value - sp.Key).ToList()).ToList();
            List<string[]> ranges = NsqCore.SystemRanges(plan ?? new List<NsqCore.PlanItem>(), orderLists);
            for (int i = 0; i < _sysRows.Count && i < ranges.Count; i++)
            {
                string[] r = ranges[i];
                _sysRows[i].Text = r != null ? (r[0] == r[1] ? r[0] : r[0] + " - " + r[1]) : "none";
            }
        }

        private void OnSysUp()
        {
            int i = _selSys;
            if (i > 0 && i < _systems.Count)
            {
                SysDef t = _systems[i - 1]; _systems[i - 1] = _systems[i]; _systems[i] = t;
                _selSys = i - 1;
                RecomputeOrder();
            }
        }

        private void OnSysDown()
        {
            int i = _selSys;
            if (i >= 0 && i < _systems.Count - 1)
            {
                SysDef t = _systems[i + 1]; _systems[i + 1] = _systems[i]; _systems[i] = t;
                _selSys = i + 1;
                RecomputeOrder();
            }
        }

        private void OnSysRemove()
        {
            int i = _selSys;
            if (i >= 0 && i < _systems.Count)
            {
                SysDef gone = _systems[i];
                _systems.RemoveAt(i);
                QueueClearPreview();
                DropKeys(gone.Keys);
                RefreshAll();
            }
        }

        private void OnSysClear()
        {
            QueueClearPreview();
            _systems = new List<SysDef>();
            _data = null;
            _typeOf = new Dictionary<long, string>();
            _sysSeq = 0;
            RefreshAll();
        }

        // ---------------------------------------------------- start point

        private void OnAutoStart()
        {
            if (Tab == "sel") { Sel.AutoReorder(Keyboard.Modifiers.HasFlag(ModifierKeys.Shift)); return; }
            if (_selSys >= 0 && _selSys < _systems.Count)
            {
                _systems[_selSys].Start = null;
                RecomputeOrder();
            }
        }

        private long? SelStartKey()
        {
            if (!(_selSys >= 0 && _selSys < _spans.Count)) return null;
            var sp = _spans[_selSys];
            return sp.Value > sp.Key ? (long?)_order[sp.Key] : null;
        }

        private void OnShowStart()
        {
            if (Tab == "sel") { Sel.ShowStart(); return; }
            long? k = SelStartKey();
            ElementId id;
            if (k != null && _data.IdMap.TryGetValue(k.Value, out id)) SelectIds(new List<ElementId> { id });
        }

        /// <summary>Select in Revit. Clicks in quick succession only send the last one, and selecting never blocks the window.</summary>
        public void SelectIds(List<ElementId> ids, bool zoom = true)
        {
            _wantSelect = Tuple.Create(ids, zoom);
            if (_selectQueued) return;
            _selectQueued = true;
            Runner.Queue("select", uiapp =>
            {
                _selectQueued = false;
                var want = _wantSelect;
                _wantSelect = null;
                if (want == null) return false;
                NsqRevit.SelectAndShow(uiapp.ActiveUIDocument, want.Item1, want.Item2);
                return true;
            }, (r, err) =>
            {
                _selectQueued = false;
                if (err != null) Status("Could not select - see debug");
            });
        }

        public void RefreshStart()
        {
            if (Tab == "sel") { Sel.RefreshStart(); return; }
            var auto = Ctl<Button>("AutoStartBtn");
            NsqUi.SetButton(auto, "auto", "Auto");
            auto.SetResourceReference(FrameworkElement.StyleProperty, "ToolButton");
            auto.ToolTip = "Put the chosen system back on the automatic start";
            var t = Ctl<TextBlock>("StartText");
            long? k = SelStartKey();
            if (PosSystem())
            {
                NsqUi.SetButton(Ctl<Button>("PickStartBtn"), "start", "Pick first element");
                string fl;
                t.Text = k == null ? "Tick a category, then Pick first element" :
                    "First: " + (_data.Labels.TryGetValue(k.Value, out fl) ? fl : "") + "  [" + k + "]" + (_posFirst != null ? "  (picked)" : "  (start of the formation)");
                return;
            }
            if (k == null) { t.Text = "No systems yet - Add selection or Pick systems"; return; }
            SysDef sd = _systems[_selSys];
            string how = sd.Start != null ? "picked" : "auto";
            string label;
            t.Text = "System " + (_selSys + 1) + ", " + sd.Name + ": starts (" + how + ") at " + (_data.Labels.TryGetValue(k.Value, out label) ? label : "") + "  [" + k + "]";
        }

        // ---------------------------------------------------- the family tree (Sequencer tab)

        private void BuildTree()
        {
            _tree.SetRows(_data != null ? _data.Rows : new List<NsqCore.TreeRow>(), _data != null ? _data.Nodes.Count : 0);
            _tree.Build();
        }

        private void OnTreeChanged()
        {
            if (PosSystem() && _preview != null) QueuePreview();
            RefreshPreview();
            Save();
        }

        private void OnTreeSelect(List<long> keys)
        {
            var idmap = _data != null ? _data.IdMap : new Dictionary<long, ElementId>();
            SelectIds(keys.Where(idmap.ContainsKey).Select(k => idmap[k]).ToList());
        }

        // ---------------------------------------------------- parameter: type-to-filter dropdown

        private void FillParams()
        {
            var names = _params.Select(p => p.Name).ToList();
            if (_paramName == null || !names.Contains(_paramName))
            {
                string d = NsqCore.DefaultParameter(names, Settings["parameter"]);
                _paramName = string.IsNullOrEmpty(d) ? null : d;
            }
            SetParamText(_paramName ?? "");
            RefreshParamNote();
        }

        private void SetParamText(string text)
        {
            _paramTyping = true;
            try { Ctl<TextBox>("ParamBox").Text = text; }
            finally { _paramTyping = false; }
        }

        private NsqCore.ParamRow ChosenParam() { return _params.FirstOrDefault(p => p.Name == _paramName); }

        /// <summary>Rebuild the dropdown with the names containing what was typed.</summary>
        private void ShowParamList(string typed)
        {
            _paramHits = NsqCore.FilterParams(_params, typed);
            var host = Ctl<StackPanel>("ParamListHost");
            host.Children.Clear();
            _paramItems = new List<Border>();
            NumSource src = Src();
            int total = src.Total;
            if (_paramHits.Count == 0)
            {
                var tb = new TextBlock { Margin = new Thickness(8, 6, 8, 6), Text = _params.Count > 0 ? "No parameter contains \"" + typed.Trim() + "\"" : src.EmptyHint };
                tb.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
                host.Children.Add(tb);
            }
            for (int i = 0; i < Math.Min(ParamListMax, _paramHits.Count); i++)
            {
                NsqCore.ParamRow p = _paramHits[i];
                int idx = i;
                var row = new Border { Padding = new Thickness(8, 4, 8, 4), CornerRadius = new CornerRadius(3), Cursor = Cursors.Hand };
                var dock = new DockPanel();
                var info = new TextBlock { Text = (p.Storage == "text" ? "text" : "integer") + "  " + p.Count + "/" + total, FontSize = 11, Margin = new Thickness(12, 0, 0, 0) };
                info.SetResourceReference(TextBlock.ForegroundProperty, "Muted");
                DockPanel.SetDock(info, Dock.Right);
                dock.Children.Add(info);
                var name = new TextBlock { Text = p.Name };
                if (p.Name == _paramName)
                {
                    name.FontWeight = FontWeights.SemiBold;
                    name.SetResourceReference(TextBlock.ForegroundProperty, "Blue");
                }
                else name.SetResourceReference(TextBlock.ForegroundProperty, "Text");
                dock.Children.Add(name);
                row.Child = dock;
                string pname = p.Name;
                row.MouseLeftButtonDown += (s, e) => Try("param click", () => { ChooseParam(pname); e.Handled = true; });
                row.MouseEnter += (s, e) => Try("param hover", () => { _paramHi = idx; PaintParamHi(); });
                host.Children.Add(row);
                _paramItems.Add(row);
            }
            var names = _paramHits.Select(p => p.Name).ToList();
            if (typed.Trim().Length > 0) _paramHi = names.Count > 0 ? 0 : -1;
            else _paramHi = _paramName != null && names.Contains(_paramName) ? names.IndexOf(_paramName) : -1;
            PaintParamHi();
            Ctl<Popup>("ParamPopup").IsOpen = true;
        }

        private void PaintParamHi()
        {
            for (int i = 0; i < _paramItems.Count; i++)
            {
                if (i == _paramHi)
                {
                    _paramItems[i].SetResourceReference(Border.BackgroundProperty, "Hover");
                    try { _paramItems[i].BringIntoView(); } catch (Exception) { }
                }
                else _paramItems[i].ClearValue(Border.BackgroundProperty);
            }
        }

        /// <summary>What to filter by: the box text, unless it still shows the chosen name.</summary>
        private string ListText()
        {
            string text = Ctl<TextBox>("ParamBox").Text ?? "";
            return text == (_paramName ?? "") ? "" : text;
        }

        private void OnParamTyped()
        {
            if (_paramTyping) return;
            ShowParamList(Ctl<TextBox>("ParamBox").Text ?? "");
        }

        private void OnParamMouse(MouseButtonEventArgs e)
        {
            var box = Ctl<TextBox>("ParamBox");
            if (!box.IsKeyboardFocusWithin)
            {
                box.Focus();
                ShowParamList("");
                e.Handled = true;
            }
        }

        /// <summary>Leaving the box: an exact name typed counts as chosen, anything else goes back to the chosen parameter.</summary>
        private void OnParamLeft()
        {
            string exact = NsqCore.ExactParam(_params, Ctl<TextBox>("ParamBox").Text);
            if (exact != null && exact != _paramName) { ChooseParam(exact); return; }
            SetParamText(_paramName ?? "");
        }

        private void OnParamKeys(KeyEventArgs e)
        {
            var popup = Ctl<Popup>("ParamPopup");
            Key key = e.Key;
            if (key == Key.Down || key == Key.Up)
            {
                if (!popup.IsOpen) ShowParamList(ListText());
                int n = _paramItems.Count;
                if (n > 0)
                {
                    int step = key == Key.Down ? 1 : -1;
                    _paramHi = Math.Max(0, Math.Min(n - 1, _paramHi + step));
                    PaintParamHi();
                }
                e.Handled = true;
            }
            else if (key == Key.Enter)
            {
                if (popup.IsOpen && _paramItems.Count > 0)
                {
                    int i = _paramHi >= 0 && _paramHi < _paramItems.Count ? _paramHi : 0;
                    ChooseParam(_paramHits[i].Name);
                }
                e.Handled = true;
            }
            else if (key == Key.Escape && popup.IsOpen)
            {
                popup.IsOpen = false;
                SetParamText(_paramName ?? "");
                e.Handled = true;
            }
        }

        private void ChooseParam(string name)
        {
            _paramName = name;
            Ctl<Popup>("ParamPopup").IsOpen = false;
            SetParamText(name);
            Settings["parameter"] = name;
            Save();
            RefreshParamNote();
            RefreshPreview();
        }

        private void RefreshParamNote()
        {
            NsqCore.ParamRow p = ChosenParam();
            var note = Ctl<TextBlock>("ParamNote");
            NumSource src = Src();
            if (!src.Has) note.Text = "";
            else if (p == null) note.Text = "No writable text or integer parameter found on these elements";
            else
            {
                int total = src.Total;
                string kind = p.Storage == "text" ? "Text" : "Integer";
                note.Text = kind + " parameter on " + p.Count + " of " + total + " elements";
                if (p.Count < total) note.Text += " - the rest are reported after " + src.Verb;
            }
        }

        // ---------------------------------------------------- sequence

        private int Pad()
        {
            if (Ctl<RadioButton>("Fmt3").IsChecked == true) return 3;
            if (Ctl<RadioButton>("Fmt2").IsChecked == true) return 2;
            return 0;
        }

        private string Direction() { return Ctl<RadioButton>("DirDown").IsChecked == true ? "down" : "up"; }

        private void OnSequenceChanged()
        {
            if (_loading) return;
            Settings["pad"] = Pad().ToString();
            Settings["direction"] = Direction();
            Settings["start"] = (Ctl<TextBox>("StartBox").Text ?? "").Trim();
            Save();
            RefreshPreview();
        }

        private bool IncludeKey(long key)
        {
            string t;
            return !(_typeOf.TryGetValue(key, out t) && _skipped.Contains(t));
        }

        private List<NsqCore.PlanItem> Plan(NumSource src, out List<NsqCore.KeyMsg> errors, out int? start)
        {
            src = src ?? Src();
            start = NsqCore.ParseStart(Ctl<TextBox>("StartBox").Text);
            errors = new List<NsqCore.KeyMsg>();
            if (src.Order.Count == 0 || start == null) return null;
            List<NsqCore.PlanItem> plan;
            NsqCore.PlanNumbers(src.Order, src.Include, start.Value, Direction(), Pad(), out plan, out errors);
            return plan;
        }

        public List<NsqCore.PlanItem> PlanOnly()
        {
            List<NsqCore.KeyMsg> e; int? s;
            return Plan(null, out e, out s);
        }

        public void RefreshPreview()
        {
            var prev = Ctl<TextBlock>("PreviewText");
            NumSource src = Src();
            List<NsqCore.KeyMsg> errors; int? start;
            List<NsqCore.PlanItem> plan = Plan(src, out errors, out start);
            if (Tab == "sel") Sel.RefreshRanges(plan); else RefreshSystemRanges(plan);
            if (!src.Has) prev.Text = "";
            else if (start == null) prev.Text = "Type a whole number to start from, e.g. 045";
            else
            {
                int skipped = src.Order.Count(k => !src.Include(k));
                prev.Text = NsqCore.PreviewText(plan ?? new List<NsqCore.PlanItem>(), errors, skipped, Pad());
                if (src.Systems > 1) prev.Text += "  |  " + src.Systems + " systems";
            }
            RefreshTagNote(plan, src);
            RefreshApply(plan, src);
        }

        private void RefreshApply(List<NsqCore.PlanItem> plan = null, NumSource src = null)
        {
            src = src ?? Src();
            if (plan == null) { List<NsqCore.KeyMsg> e; int? s; plan = Plan(src, out e, out s); }
            int n = plan != null ? plan.Count : 0;
            bool ok = n > 0 && ChosenParam() != null && !_busy;
            bool waiting = src.NeedsStart && !src.Started;
            // the System Selector runs only once a start is picked (step 2.3)
            var btn = Ctl<Button>("ApplyBtn");
            btn.IsEnabled = ok && !waiting;
            btn.ToolTip = waiting ? "Pick a start first (2.3 Pick start)" : "Number the sequence (and tag it, when Tags is on)";
            NsqUi.SetIconData(Ctl<System.Windows.Shapes.Path>("ApplyIcon"), "run");
            Ctl<TextBlock>("ApplyText").Text = n > 0 ? "Run Sequence (" + n + ")" : "Run Sequence";
        }

        // ---------------------------------------------------- tags

        private void FillTags()
        {
            var combo = Ctl<ComboBox>("TagCombo");
            string saved = Settings["tag_type"];
            _tagView = NsqCore.TagsForKind(Tags, Src().Kind);
            bool was = _loading;
            _loading = true;
            try
            {
                combo.Items.Clear();
                ComboBoxItem pick = null, fallback = null;
                for (int i = 0; i < _tagView.Count; i++)
                {
                    var item = new ComboBoxItem { Content = _tagView[i].Label, Tag = i };
                    combo.Items.Add(item);
                    if (_tagView[i].Label == saved) pick = item;
                    if (fallback == null && _tagView[i].TagCat == "OST_MultiCategoryTags") fallback = item;
                }
                pick = pick ?? fallback;
                if (pick == null && combo.Items.Count > 0) pick = (ComboBoxItem)combo.Items[0];
                if (pick != null) combo.SelectedItem = pick;
            }
            finally { _loading = was; }
            SyncTagEnabled();
        }

        private TagChoice ChosenTag()
        {
            var item = Ctl<ComboBox>("TagCombo").SelectedItem as ComboBoxItem;
            if (item == null) return null;
            try { return _tagView[(int)item.Tag]; } catch (Exception) { return null; }
        }

        private void SyncTagEnabled()
        {
            bool on = Ctl<CheckBox>("TagCheck").IsChecked == true;
            Ctl<ComboBox>("TagCombo").IsEnabled = on;
            Ctl<CheckBox>("TagUntaggedCheck").IsEnabled = on;
            foreach (string n in new[] { "TagLeaderCheck", "TagElbowCheck", "TagRemoveCheck", "TagUntangleCheck" }) Ctl<CheckBox>(n).IsEnabled = on;
            foreach (string n in new[] { "TagOffX", "TagOffY", "TagElbowMm", "TagScopeView", "TagScopeTicked" }) Ctl<Control>(n).IsEnabled = on;
        }

        /// <summary>The tag each host category gets for the chosen tag.</summary>
        private Dictionary<string, TagChoice> TagPlan(List<NsqCore.PlanItem> plan, NumSource src, out List<string> hosts)
        {
            hosts = (plan ?? new List<NsqCore.PlanItem>()).Select(p => { string h; return src.HostCat.TryGetValue(p.Key, out h) ? h : null; }).ToList();
            return NsqCore.TagForHosts(Tags, ChosenTag(), hosts.Where(h => h != null));
        }

        private void OnTagChanged()
        {
            if (_loading) return;
            SyncTagEnabled();
            Settings["tag"] = Ctl<CheckBox>("TagCheck").IsChecked == true ? "on" : "off";
            Settings["tag_untagged"] = Ctl<CheckBox>("TagUntaggedCheck").IsChecked == true ? "on" : "off";
            Settings["tag_scope"] = ScopeTicked() ? "ticked" : "view";
            Settings["tag_leader"] = Ctl<CheckBox>("TagLeaderCheck").IsChecked == true ? "on" : "off";
            Settings["tag_offx"] = Ctl<TextBox>("TagOffX").Text ?? "0";
            Settings["tag_offy"] = Ctl<TextBox>("TagOffY").Text ?? "0";
            Settings["tag_elbow"] = Ctl<CheckBox>("TagElbowCheck").IsChecked == true ? "on" : "off";
            Settings["tag_elbow_mm"] = Ctl<TextBox>("TagElbowMm").Text ?? "300";
            Settings["tag_remove"] = Ctl<CheckBox>("TagRemoveCheck").IsChecked == true ? "on" : "off";
            Settings["tag_untangle"] = Ctl<CheckBox>("TagUntangleCheck").IsChecked == true ? "on" : "off";
            TagChoice t = ChosenTag();
            if (t != null) Settings["tag_type"] = t.Label;
            Save();
            RefreshTagNote(PlanOnly());
        }

        public void RefreshTagNote(List<NsqCore.PlanItem> plan, NumSource src = null)
        {
            RefreshTagOpen();
            src = src ?? Src();
            var note = Ctl<TextBlock>("TagNote");
            if (Ctl<CheckBox>("TagCheck").IsChecked != true)
            {
                note.Text = src.PlansOnly ? "Plan views only on this tab" : "";
                return;
            }
            TagChoice t = ChosenTag();
            if (t == null)
            {
                note.Text = "No " + src.Kind + ", fitting, accessory, fabrication or multi-category tags are loaded";
                return;
            }
            if (plan == null || plan.Count == 0) { note.Text = ""; return; }
            List<string> hosts;
            Dictionary<string, TagChoice> byHost = TagPlan(plan, src, out hosts);
            int yes, no; List<KeyValuePair<string, int>> others;
            NsqCore.TagPlanNote(byHost, t, hosts.Where(h => h != null), out yes, out no, out others);
            string text = no == 0
                ? "Tags all " + yes + " numbered elements"
                : "Tags " + yes + " of " + (yes + no) + " - no loaded tag can take the other " + no + "; load one for their category or a multi-category tag";
            if (others.Count > 0)
                text += ". This tag cannot take every category, so " + string.Join("; ", others.Select(o => o.Value + " get " + o.Key));
            if (Ctl<CheckBox>("TagUntaggedCheck").IsChecked == true) text += ". Anything already tagged in a view is left alone";
            int n = Views != null && ScopeTicked() ? Views.TickedCount() : 0;
            if (n > 0)
                text = "Tags go in the " + n + " ticked view(s), wherever the numbered elements show (3D views must be locked). " + text;
            else if (src.PlansOnly)
            {
                string why;
                bool ok = NsqCore.TagViewOk(src.ViewType, out why, false, false, true);
                text = ok ? "Active view - plan views only. " + text : "No tags will be placed: " + why;
            }
            note.Text = text;
        }

        // ---------------------------------------------------- apply / run

        private void OnApply()
        {
            NumSource src = Src();
            if (src.NeedsStart && !src.Started) { Status("Pick a start first (2.3 Pick start)"); return; }
            List<NsqCore.KeyMsg> preErrors; int? start;
            List<NsqCore.PlanItem> plan = Plan(src, out preErrors, out start);
            NsqCore.ParamRow p = ChosenParam();
            if (plan == null || plan.Count == 0 || p == null) return;
            string name = p.Name, storage = p.Storage;
            var idmap = src.IdMap;
            var labels = src.Labels;
            var after = src.After;
            TagJob tag = null;
            if (Ctl<CheckBox>("TagCheck").IsChecked == true)
            {
                TagChoice t = ChosenTag();
                if (t != null)
                {
                    List<string> hosts;
                    Dictionary<string, TagChoice> byHost = TagPlan(plan, src, out hosts);
                    tag = new TagJob
                    {
                        On = true, Choice = t, PlansOnly = src.PlansOnly, Views = ScopeTicked() ? Views.TickedIds() : new List<ElementId>(), ViewsDoc = Views.DocKeyValue,
                        Leader = Ctl<CheckBox>("TagLeaderCheck").IsChecked == true, OffX = Mm("TagOffX"), OffY = Mm("TagOffY"),
                        Elbow = Ctl<CheckBox>("TagElbowCheck").IsChecked == true, ElbowMm = Mm("TagElbowMm"),
                        RemovePrev = Ctl<CheckBox>("TagRemoveCheck").IsChecked == true, Untangle = Ctl<CheckBox>("TagUntangleCheck").IsChecked == true,
                        ByHost = byHost.Where(kv => kv.Key != null).ToDictionary(kv => kv.Key, kv => kv.Value),
                        UntaggedOnly = Ctl<CheckBox>("TagUntaggedCheck").IsChecked == true,
                    };
                }
            }
            Log.Add(src.Verb.ToLowerInvariant() + ": " + plan.Count + " planned, param " + name + " (" + storage + "), pad " + Pad() + ", start " + start + " " + Direction() +
                    ", tag " + (tag != null ? tag.Choice.TagCat : "off"));
            foreach (var it in plan)
            {
                string label;
                Log.Add("  " + it.Key + " -> " + it.Text + "  " + (labels.TryGetValue(it.Key, out label) ? label : ""));
            }
            var snapshotPlan = plan;
            QueueBusy(src.Verb.ToLowerInvariant(), uiapp =>
            {
                ClearPreviewNow(uiapp);   // the order lines go before the numbers are written
                Document doc = uiapp.ActiveUIDocument.Document;
                List<NsqCore.WriteItem> writes; List<long> same; List<NsqCore.KeyMsg> errors;
                NsqCore.PrepareWrites(snapshotPlan, k => NsqRevit.ReadParamInfo(doc.GetElement(idmap[k]), name), out writes, out same, out errors);
                var job = new ApplyJob { Param = name, Storage = storage, Writes = writes, Same = same, IdMap = idmap, Tag = tag };
                ApplyResult res = NsqRevit.ApplyJobRun(uiapp, job, Log);
                var all = new List<NsqCore.KeyMsg>(preErrors);
                all.AddRange(errors);
                all.AddRange(res.Errors);
                res.Errors = all;
                int cleared = 0;
                if (after != null)
                {
                    try { cleared = after(uiapp); }
                    catch (Exception ex)
                    {
                        Log.Add("after run failed: " + ex);
                        res.Errors.Add(new NsqCore.KeyMsg { Key = 0, Msg = "The view colours could not be cleared - use Clear colours" });
                    }
                }
                return new RunOutcome { Res = res, Cleared = cleared };
            }, (r, err) => Applied(r as RunOutcome, err, src, tag), "Numbering");
        }

        private class RunOutcome { public ApplyResult Res; public int Cleared; }

        private void Applied(RunOutcome outcome, string err, NumSource src, TagJob tag)
        {
            src = src ?? Src();
            if (err != null || outcome == null)
            {
                Status(src.Verb + " failed - see debug");
                ShowResults(new List<NsqCore.KeyMsg> { new NsqCore.KeyMsg { Key = 0, Msg = err ?? src.Verb + " failed" } }, src);
                return;
            }
            ApplyResult res = outcome.Res;
            string msg = "Numbered " + res.Written;
            if (res.Same > 0) msg += " (" + res.Same + " already right)";
            if (res.Tagged > 0 || res.TagSkipped > 0)
            {
                msg += "  |  tagged " + res.Tagged;
                if (res.TagViews > 0) msg += " in " + res.TagViews + " view(s)";
                if (res.TagAlready > 0) msg += ", " + res.TagAlready + " already tagged";
                if (res.TagNoTag > 0) msg += ", " + res.TagNoTag + " with no tag for their category";
            }
            if (outcome.Cleared > 0) msg += "  |  view colours cleared";
            if (res.Errors.Count > 0) msg += "  |  " + res.Errors.Count + " to check";
            Status(msg);
            Sel.AfterRunUi();
            Log.Write();
            if (res.Errors.Count > 0)
            {
                var errs = res.Errors;
                // show after Execute has returned so Revit is not held
                Win.Dispatcher.BeginInvoke(new Action(() => Try("results", () => ShowResults(errs, src))));
            }
            if (tag != null && tag.Views.Count > 0 && res.Tagged > 0)
                Win.Dispatcher.BeginInvoke(new Action(() => Try("offer open", () => OfferOpen(tag))));
        }

        // ---------------------------------------------------- results window

        private void ShowResults(List<NsqCore.KeyMsg> errors, NumSource src)
        {
            src = src ?? Src();
            _lastErrors = errors;
            try
            {
                var rw = (Window)NsqUi.LoadXaml("NumberSequencerResults.xaml");
                NsqUi.MergeTheme(rw);
                NsqUi.ApplyPalette(rw, Mode);
                try { NsqUi.Iconize(rw); } catch (Exception) { }
                rw.Owner = Win;
                Func<string, object> f = rw.FindName;
                ((TextBlock)f("RVersion")).Text = "v" + NsqCore.Version;
                ImageSourceHolder.Set((System.Windows.Controls.Image)f("RIcon"));
                ((TextBlock)f("RSummary")).Text = errors.Count + " item(s) were not numbered or tagged. Everything else in the sequence went through.";
                var lst = (Panel)f("RList");
                var idmap = src.IdMap;
                var labels = src.Labels;
                foreach (var er in errors)
                {
                    var tb = new TextBlock { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(4, 2, 4, 2) };
                    tb.SetResourceReference(TextBlock.ForegroundProperty, "Text");
                    string label;
                    labels.TryGetValue(er.Key, out label);
                    if (er.Key == 0) tb.Text = er.Msg;
                    else
                    {
                        tb.Text = er.Key + "  " + (label ?? "") + "  -  " + er.Msg;
                        tb.Cursor = Cursors.Hand;
                        ElementId eid;
                        idmap.TryGetValue(er.Key, out eid);
                        tb.MouseLeftButtonDown += (s, e) => Try("result click", () => { if (e.ClickCount == 2 && eid != null) SelectIds(new List<ElementId> { eid }); });
                    }
                    lst.Children.Add(tb);
                }
                string text = string.Join("\n", errors.Select(er => { string l; labels.TryGetValue(er.Key, out l); return (er.Key == 0 ? "" : er.Key.ToString()) + "\t" + (l ?? "") + "\t" + er.Msg; }));
                ((Button)f("RCloseX")).Click += (s, e) => rw.Close();
                ((Button)f("RCloseBtn")).Click += (s, e) => rw.Close();
                ((Button)f("RCopyBtn")).Click += (s, e) => { try { Clipboard.SetText(text); } catch (Exception) { } };
                ((Button)f("RSelectBtn")).Click += (s, e) =>
                {
                    var ids = errors.Where(er => idmap.ContainsKey(er.Key)).Select(er => idmap[er.Key]).ToList();
                    if (ids.Count > 0) SelectIds(ids);
                };
                ((UIElement)f("RHeader")).MouseLeftButtonDown += (s, e) => { try { rw.DragMove(); } catch (Exception) { } };
                rw.Show();
            }
            catch (Exception ex) { Log.Add("results window failed: " + ex); }
        }

        // ---------------------------------------------------- debug, save, close

        private void OnDebug()
        {
            Log.Enabled = Ctl<CheckBox>("DebugCheck").IsChecked == true;
            Settings["debug"] = Log.Enabled ? "on" : "off";
            Save();
        }

        private void OnCopyDebug()
        {
            string text = NsqCore.FormatSettings(Settings) + "\n" + Log.Text();
            try { Clipboard.SetText(text); Status("Debug copied to the clipboard"); }
            catch (Exception) { Status("Could not reach the clipboard"); }
            Log.Write();
        }

        public void Save()
        {
            if (_loading) return;
            Settings["skip"] = NsqCore.SkipTextFrom(_skipped);
            Settings["sel_skip"] = NsqCore.SkipTextFrom(Sel.Skipped);
            NsqCore.SaveSettings(Settings);
        }

        private void RememberSize()
        {
            Window w = Win;
            if (_chrome.Full) return;
            double height = _chrome.Shrunk && _chrome.Before != null ? _chrome.Before[1] : w.ActualHeight;
            Settings["win_w"] = ((int)Math.Round(w.ActualWidth)).ToString();
            Settings["win_h"] = ((int)Math.Round(height)).ToString();
        }

        private void OnClosed()
        {
            try { RememberSize(); } catch (Exception) { }
            if (_tagwin != null) { try { _tagwin.Close(); } catch (Exception) { } }
            Sel.OnClosed();
            ClosePosition();
            Save();
            Log.Write();
            if (ReferenceEquals(_current, this)) _current = null;
        }

        public void Show()
        {
            _current = this;
            Win.Show();
            Win.Activate();
        }

        public static SequencerWindow Existing()
        {
            try
            {
                if (_current != null && _current.Win.IsVisible) return _current;
            }
            catch (Exception) { }
            return null;
        }

        public static SequencerWindow Launch(UIApplication uiapp)
        {
            SequencerWindow w = Existing();
            if (w != null)
            {
                try
                {
                    w.Win.Activate();
                    if (w.Tab == "sel") w.Sel.Refresh();
                    else w.QueueBusy("add selection", w.JobAddSelection, w.Added, "Reading the Revit selection");
                }
                catch (Exception) { }
                return w;
            }
            w = new SequencerWindow(uiapp);
            w.ReadNow(uiapp);
            w.Show();
            return w;
        }
    }

    /// <summary>Sets an Image's source to the tool's icon.</summary>
    internal static class ImageSourceHolder
    {
        public static void Set(System.Windows.Controls.Image img)
        {
            if (img == null) return;
            var src = NsqUi.LoadIcon();
            if (src != null) img.Source = src;
        }
    }
}





