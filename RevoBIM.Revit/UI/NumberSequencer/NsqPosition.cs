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

        private bool PosOn() { return Ctl<CheckBox>("PosCheck").IsChecked == true; }
        private bool PosLR() { return Ctl<RadioButton>("PosLR").IsChecked == true; }
        private bool PosSystem() { return _systems.Count == 1 && _systems[0].Kind == "pos" && _data != null; }

        private void WirePosition()
        {
            On<CheckBox>("PosCheck", OnPosToggle);
            Ctl<RadioButton>("PosLR").Checked += (s, e) => Try("formation", OnFormation);
            Ctl<RadioButton>("PosTB").Checked += (s, e) => Try("formation", OnFormation);
            On<Button>("PosShuffleBtn", () =>
            {
                if (!PosSystem()) { Status("Add a selection first (Order by position is on)"); return; }
                _posVariant = (_posVariant + 1) % NsqCore.SnakeVariants;
                QueuePreview();
            });
            On<Button>("PosClearBtn", () => { QueueClearPreview(); Status("Order lines removed"); });
        }

        private void OnPosToggle()
        {
            bool on = PosOn();
            NsqUi.Show(Ctl<UIElement>("PosPanel"), on);
            if (on) Status("Select elements in Revit (any category), then Add selection - pick a formation to see the order");
            else QueueClearPreview();
        }

        private void OnFormation()
        {
            if (_loading || !PosSystem()) return;
            _posVariant = 0;
            QueuePreview();
        }

        /// <summary>The order the elements go in, from where they sit in the active view.</summary>
        private void BuildPosOrder()
        {
            SysDef sd = _systems[0];
            Dictionary<long, double[]> uv = NsqRevit.Project(_data.Points, sd.Keys, _posFrame);
            List<long> order = NsqCore.SnakeOrder(uv, PosLR(), _posVariant);
            order.AddRange(sd.Keys.Where(k => !uv.ContainsKey(k)).OrderBy(k => k));   // no position: numbered last
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
            var elems = new List<Element>();
            foreach (ElementId id in uidoc.Selection.GetElementIds())
            {
                Element e = doc.GetElement(id);
                if (e == null || e is ElementType || e.Category == null || e.Category.CategoryType != CategoryType.Model) continue;
                if (NsqRevit.ElemPoint(e) == null) continue;
                elems.Add(e);
            }
            Log.Add("add selection by position: " + elems.Count + " elements");
            var res = new AddResult { Positional = true, Tags = NsqRevit.TagChoices(doc), Frame = NsqRevit.FrameOf(doc.ActiveView) };
            if (elems.Count > 0) res.Reads.Add(Read(doc, elems));
            return res;
        }

        private void AddedPositional(AddResult res)
        {
            if (res.Tags != null) { Tags = res.Tags; FillTags(); }
            if (res.Reads.Count == 0) { Status("Select elements in Revit first (model elements of any category), then Add selection"); return; }
            _systems = new List<SysDef>();
            _data = null;
            _typeOf = new Dictionary<long, string>();
            _sysSeq = 0;
            foreach (NetworkData d in res.Reads) Merge(d);
            var keys = _data.Nodes.Keys.OrderBy(k => k).ToList();
            _systems.Add(new SysDef { Keys = keys, Num = keys, Name = "Selection (" + keys.Count + " elements)", Kind = "pos" });
            _selSys = 0;
            _posFrame = res.Frame;
            _posVariant = 0;
            RefreshAll();
            QueuePreview();
        }

        private class PreviewResult { public NsqRevit.ViewFrame Frame; public string Why = ""; public int Lines; }

        /// <summary>Show the order in the active view: detail lines between the elements in order, the elements isolated.</summary>
        private void QueuePreview()
        {
            if (!PosSystem()) return;
            bool lr = PosLR();
            int variant = _posVariant;
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
                _preview = NsqRevit.DrawOrder(uidoc, shown, _data.Points, _data.IdMap, _posFrame, Log);
                res.Lines = _preview.Lines.Count;
                return res;
            }, (r, err) =>
            {
                if (err != null) { Status("Could not show the order - see debug"); return; }
                RecomputeOrder();
                var res = r as PreviewResult;
                string text = NsqCore.SnakeText(lr, variant);
                if (res != null && res.Why.Length > 0) text += " - " + res.Why;
                else text += " - green line first, red after. Shuffle for another order, Run Sequence to number";
                Status(text);
            });
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
