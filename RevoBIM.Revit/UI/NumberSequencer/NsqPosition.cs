using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.NumberSequencer;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using ComboBoxItem = System.Windows.Controls.ComboBoxItem;

namespace RevoBIM.UI.NumberSequencer
{
    /// <summary>
    /// Order by position: number whatever is selected, of any category (Air Terminals, say), in a snake across the
    /// view - left to right row by row, or top to bottom column by column. Picking a formation draws detail lines
    /// between the elements in order and isolates them temporarily; Shuffle tries another start corner; Run Sequence
    /// numbers in the order shown and removes the lines.
    /// </summary>
    public partial class SequencerWindow
    {
        private static readonly List<SequencerWindow> ClosingWindows = new List<SequencerWindow>();

        private int _posVariant;
        private NsqRevit.ViewFrame _posFrame = new NsqRevit.ViewFrame();
        private List<long> _posOrder = new List<long>();
        private NsqRevit.OrderPreview _preview;

        /// <summary>The Sequencer tab numbers elements, not systems; the System Selector tab keeps the systems.</summary>
        private bool PosOn() { return Tab == "seq"; }
        private int PosFormIndex() { return Math.Max(0, Ctl<ComboBox>("PosForm").SelectedIndex); }
        private bool PosLR() { return PosFormIndex() < 2; }
        private int PosFlip() { return PosFormIndex() % 2 == 1 ? 2 : 0; }
        private long? _posFirst;
        private bool PosSystem() { return _systems.Count == 1 && _systems[0].Kind == "pos" && _data != null; }

        private void WirePosition()
        {
            int form = NsqCore.ToInt(Settings["pos_form"], 0);
            Ctl<ComboBox>("PosForm").SelectedIndex = Math.Max(0, Math.Min(3, form));
            Ctl<ComboBox>("PosForm").SelectionChanged += (s, e) => Try("formation", OnFormation);
            On<Button>("AllInViewBtn", () => QueueBusy("all in view", JobAllInView, Added, "Reading every element the view shows"));
            On<Button>("PosPickBtn", PickFirst);
            On<Button>("PosClearBtn", () => { QueueClearPreview(); Status("Order lines removed"); });
        }

        private void OnFormation()
        {
            Settings["pos_form"] = PosFormIndex().ToString();
            Save();
            if (_loading || !PosSystem()) return;
            QueuePreview();
        }

        /// <summary>Click the element that gets the first number; the order and its lines are worked out from there.</summary>
        private void PickFirst()
        {
            if (!PosSystem()) { Status("Add a selection first, or All in view, then tick the categories"); return; }
            var ids = new HashSet<long>(_systems[0].Keys.Where(IncludeKey));
            if (ids.Count == 0) { Status("Tick a category first"); return; }
            QueueBusy("pick first", uiapp =>
            {
                Element el = NsqRevit.PickElementIn(uiapp.ActiveUIDocument, ids, "RevoBIM Number Sequencer: click the element that gets the first number (Esc cancels)");
                return el == null ? (object)null : NsqRevit.EidValue(el.Id);
            }, (res, err) =>
            {
                if (err != null || res == null) { Status("Cancelled"); return; }
                _posFirst = (long)res;
                QueuePreview();
            }, "Click the element that gets the first number (Esc cancels)");
        }
        /// <summary>The order the elements go in, from where they sit in the active view.</summary>
        private void BuildPosOrder()
        {
            SysDef sd = _systems[0];
            Dictionary<long, double[]> uv = NsqRevit.Project(_data.Points, sd.Keys.Where(IncludeKey), _posFrame);
            if (_posFirst != null && !uv.ContainsKey(_posFirst.Value)) _posFirst = null;
            List<long> order = NsqCore.SnakeOrder(uv, PosLR(), PosFlip(), _posFirst);
            order.AddRange(sd.Keys.Where(k => !uv.ContainsKey(k) && IncludeKey(k)).OrderBy(k => k));   // no position: numbered last
            _posOrder = order;
        }

        private void PosRecompute()
        {
            BuildPosOrder();
            _order = _posOrder;
            _spans = new List<KeyValuePair<int, int>> { new KeyValuePair<int, int>(0, _order.Count) };
            _selSys = 0;
            BuildSystems();
            RefreshStart();
            RefreshPreview();
        }

        private object JobAddPositional(UIApplication uiapp)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            List<Element> elems = NsqRevit.ModelElements(doc, uidoc.Selection.GetElementIds());
            Log.Add("add selection: " + elems.Count + " elements");
            return BuildAdd(doc, elems, false);
        }

        private object JobAllInView(UIApplication uiapp)
        {
            Document doc = uiapp.ActiveUIDocument.Document;
            List<Element> elems = NsqRevit.ElementsAllInView(doc, doc.ActiveView, NsqRevit.NetworkLimit);
            Log.Add("all in view: " + elems.Count + " elements in '" + NsqRevit.ElemName(doc.ActiveView) + "'");
            return BuildAdd(doc, elems, true);
        }

        private AddResult BuildAdd(Document doc, List<Element> elems, bool all)
        {
            var res = new AddResult { Positional = true, AllInView = all, Tags = NsqRevit.TagChoices(doc), Frame = NsqRevit.FrameOf(doc.ActiveView) };
            if (elems.Count > 0) res.Reads.Add(Read(doc, elems));
            return res;
        }

        private void AddedPositional(AddResult res)
        {
            if (res.Tags != null) { Tags = res.Tags; FillTags(); }
            if (res.Reads.Count == 0) { Status(res.AllInView ? "The active view shows no model elements" : "Select elements in Revit first (model elements of any category), then Add selection"); return; }
            QueueClearPreview();
            _systems = new List<SysDef>();
            _data = null;
            _typeOf = new Dictionary<long, string>();
            _sysSeq = 0;
            _posFirst = null;
            foreach (NetworkData d in res.Reads) Merge(d);
            var keys = _data.Nodes.Keys.OrderBy(k => k).ToList();
            _systems.Add(new SysDef { Keys = keys, Num = keys, Name = (res.AllInView ? "All in view (" : "Selection (") + keys.Count + " elements)", Kind = "pos" });
            _selSys = 0;
            _posFrame = res.Frame;
            // a selection is numbered as it is; everything in a view starts unticked, so only the categories you tick are numbered
            var types = new HashSet<string>(_data.Rows.Select(r => NsqCore.TypeKey(r.Category, r.Family, r.Type)));
            if (res.AllInView) _skipped.UnionWith(types); else _skipped.ExceptWith(types);
            Save();
            RefreshAll();
            if (res.AllInView) Status(keys.Count + " elements in the view - tick the categories to number, then Pick first element");
            else
            {
                Status(keys.Count + " elements added - Pick first element to see the order, or Run Sequence");
                QueuePreview();
            }
        }
        private class PreviewResult { public NsqRevit.ViewFrame Frame; public string Why = ""; public int Lines; }

        /// <summary>Show the order in the active view: detail lines between the elements in order, the elements isolated.</summary>
        private void QueuePreview()
        {
            if (!PosSystem()) return;
                        Runner.Queue("order preview", uiapp =>
            {
                UIDocument uidoc = uiapp.ActiveUIDocument;
                View view = uidoc.Document.ActiveView;
                ClearPreviewNow(uiapp);
                _posFrame = NsqRevit.FrameOf(view);
                if (!PosSystem()) return new PreviewResult { Frame = _posFrame };
                BuildPosOrder();
                var res = new PreviewResult { Frame = _posFrame };
                string why;
                if (!NsqRevit.CanDrawLines(view, out why)) { res.Why = why; return res; }
                var shown = _posOrder.Where(IncludeKey).ToList();
                if (shown.Count == 0) { res.Why = "Tick a category to see the order"; return res; }
                _preview = NsqRevit.DrawOrder(uidoc, shown, _data.Points, _data.IdMap, _posFrame, Log);
                res.Lines = _preview.Lines.Count;
                return res;
            }, (r, err) =>
            {
                if (err != null) { Status("Could not show the order - see debug"); return; }
                RecomputeOrder();
                var res = r as PreviewResult;
                string text = ComboText();
                if (res != null && res.Why.Length > 0) text += " - " + res.Why;
                else text += " - green line first, red after. Shuffle for another order, Run Sequence to number";
                Status(text);
            });
        }

        private string ComboText()
        {
            var item = Ctl<ComboBox>("PosForm").SelectedItem as ComboBoxItem;
            return (item != null ? item.Content.ToString() : "") + (_posFirst != null ? ", from the element you picked" : "");
        }

        private void ClearPreviewNow(UIApplication uiapp)
        {
            if (_preview == null) return;
            NsqRevit.OrderPreview p = _preview;
            _preview = null;
            NsqRevit.ClearOrder(uiapp, p, Log);
        }

        private void QueueClearPreview()
        {
            if (_preview == null) return;
            Runner.Queue("clear order preview", uiapp => { ClearPreviewNow(uiapp); return true; },
                         (r, err) => { if (err != null) Status("Could not remove the order lines - see debug"); });
        }

        private void ClosePosition()
        {
            if (_preview == null) return;
            NsqRevit.OrderPreview p = _preview;
            _preview = null;
            ClosingWindows.Add(this);   // held until the job has run: nothing else references a closed window
            bool queued = Runner.Queue("clear order preview on close", uiapp => { NsqRevit.ClearOrder(uiapp, p, Log); return true; },
                                       (r, err) => ClosingWindows.Remove(this));
            if (!queued) ClosingWindows.Remove(this);
        }
    }
}


