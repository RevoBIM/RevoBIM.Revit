using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        // ============================================================= dimension
        /// <summary>The (reference, which) pair dim_ref_across returns. Ref is null (and Which null) when nothing was found.</summary>
        public class DimRef
        {
            public Reference Ref;
            public string Which;
        }

        /// <summary>The family's centre reference square to the run, chosen from the instance's own axes (so a
        /// hanger turned either way works), falling back to the other centre, then to a face square to the run.</summary>
        public static DimRef DimRefAcross(Element inst, V3 along)
        {
            string first;
            try
            {
                FamilyInstance fi = (FamilyInstance)inst;
                XYZ h = fi.HandOrientation, f = fi.FacingOrientation;
                first = HfamCore.ReferenceTypeAcross(new V3(h.X, h.Y, 0.0), new V3(f.X, f.Y, 0.0), along);
            }
            catch (Exception) { first = "CenterFrontBack"; }
            string other = first == "CenterFrontBack" ? "CenterLeftRight" : "CenterFrontBack";
            foreach (string n in new[] { first, other })
            {
                try
                {
                    FamilyInstanceReferenceType t = (FamilyInstanceReferenceType)Enum.Parse(typeof(FamilyInstanceReferenceType), n);
                    IList<Reference> refs = ((FamilyInstance)inst).GetReferences(t);
                    if (refs != null && refs.Count > 0) return new DimRef { Ref = refs[0], Which = n };
                }
                catch (Exception) { }
            }
            try
            {
                List<PlanarFace> fs = FhaRevit.FacesAcross(inst, along, null);
                if (fs.Count > 0)
                {
                    V3? p = InstancePoint(inst);
                    PlanarFace best = null; double bestKey = 0;
                    foreach (PlanarFace fa in fs)
                    {
                        double k = Math.Abs(FhaRevit.T(fa, p.Value, along));
                        if (best == null || k < bestKey) { best = fa; bestKey = k; }
                    }
                    return new DimRef { Ref = best.Reference, Which = "face" };
                }
            }
            catch (Exception) { }
            return new DimRef();
        }

        public static Reference DimRefsFor(Element inst, string axis, V3? along = null)
        {
            V3 a = along ?? (axis == "X" ? new V3(0.0, 1.0, 0.0) : new V3(1.0, 0.0, 0.0));
            return DimRefAcross(inst, a).Ref;
        }

        /// <summary>One chained dimension along a run in `view`: the run's ends and every
        /// hanger's centre plane square to the run. Revit refuses a dimension whose
        /// references it cannot see in that view (a duct end outside the crop, say),
        /// so if the full chain is refused it is tried again on the hangers alone.
        /// Every reason it gives up is logged. Returns hangers dimensioned.</summary>
        public static int ChainDimension(Document doc, View view, V3 pStart, V3 pEnd, IEnumerable<Element> insts, Element firstEl, Element lastEl,
                                         string axis, FhaSettings settings, FhaDebugLog log, DimensionType dimType = null)
        {
            try { doc.Regenerate(); }   // hangers placed this run need geometry before another view can reference them
            catch (Exception) { }
            V3 d = FhaCore.VNorm(FhaCore.VSub(pEnd, pStart));
            var hang = new List<KeyValuePair<double, Reference>>();
            foreach (Element inst in insts)
            {
                DimRef dr = DimRefAcross(inst, d);
                V3? p = InstancePoint(inst);
                if (dr.Ref != null && p != null)
                    hang.Add(new KeyValuePair<double, Reference>(FhaCore.VDot(FhaCore.VSub(p.Value, pStart), d), dr.Ref));
                else
                    log.Add("   dimension: hanger " + Inv(Eid(inst.Id)) + " has no reference square to the run");
            }
            var ends = new List<KeyValuePair<double, Reference>>();
            foreach (bool atEnd in new[] { false, true })
            {
                Element el = atEnd ? lastEl : firstEl;
                List<PlanarFace> fs = FhaRevit.FacesAcross(el, d, view);
                if (fs.Count > 0)
                {
                    PlanarFace f = null; double fk = 0;
                    foreach (PlanarFace c in fs)
                    {
                        double k = FhaRevit.T(c, pStart, d);
                        if (f == null || (atEnd ? k > fk : k < fk)) { f = c; fk = k; }
                    }
                    ends.Add(new KeyValuePair<double, Reference>(FhaRevit.T(f, pStart, d), f.Reference));
                }
            }
            V3 p0, p1;
            FhaRevit.ViewDimLine(view, pStart, pEnd, FhaCore.AsFloat(settings, "fam_dim_offset", 800.0), out p0, out p1);
            Line line = Line.CreateBound(ToXyz(p0), ToXyz(p1));
            var tries = new List<KeyValuePair<string, List<KeyValuePair<double, Reference>>>>
            {
                new KeyValuePair<string, List<KeyValuePair<double, Reference>>>("run ends and hangers", hang.Concat(ends).ToList()),
                new KeyValuePair<string, List<KeyValuePair<double, Reference>>>("hangers only", hang),
            };
            string last = null;
            foreach (var tr in tries)
            {
                string label = tr.Key;
                List<KeyValuePair<double, Reference>> items = FhaCore.CollapseRefs(tr.Value, 0.01);
                if (hang.Count == 0 || items.Count < 2)
                {
                    last = Inv(items.Count) + " usable references (" + Inv(hang.Count) + " hangers)";
                    continue;
                }
                ReferenceArray refs = new ReferenceArray();
                foreach (var kv in items) refs.Append(kv.Value);
                try
                {
                    if (dimType != null)
                        doc.Create.NewDimension(view, line, refs, dimType);
                    else
                        doc.Create.NewDimension(view, line, refs);
                    log.Add("   dimension in " + ElName(view) + ": " + label + ", " + Inv(items.Count) + " references"
                            + (label == tries[0].Key ? "" : " (the full chain was refused)"));
                    return hang.Count;
                }
                catch (Exception ex)
                {
                    last = label + ": " + ex.Message;
                    log.Add("   dimension in " + ElName(view) + " refused (" + last + ")");
                }
            }
            log.Add("   no dimension in " + ElName(view) + " - " + (last ?? "None"));
            return 0;
        }

        // ======================================================= dimension placer
        public static bool IsFloorPlan(View view)
        {
            try { return !view.IsTemplate && view.ViewType == ViewType.FloorPlan; }
            catch (Exception) { return false; }
        }

        /// <summary>Hanger family instances visible in the view: the configured / chosen
        /// families, plus anything in MEP Ancillary Framing.</summary>
        public static List<FamilyInstance> ViewHangers(Document doc, View view, ICollection<string> familyNames)
        {
            var o = new List<FamilyInstance>();
            FilteredElementCollector col;
            try { col = new FilteredElementCollector(doc, view.Id).OfClass(typeof(FamilyInstance)); }
            catch (Exception) { return o; }
            foreach (Element e in col)
            {
                try
                {
                    if (HangerCatKey(e) == null) continue;
                    FamilyInstance fi = (FamilyInstance)e;
                    if (familyNames.Contains(ElName(fi.Symbol.Family)) || CatIs(e, "OST_MEPAncillaryFraming"))
                        o.Add(fi);
                }
                catch (Exception) { }
            }
            return o;
        }

        public static List<ElementId> ViewDimensionIds(Document doc, View view)
        {
            var ids = new List<ElementId>();
            try
            {
                foreach (Element d in new FilteredElementCollector(doc, view.Id).OfCategory(FhaRevit.Bic("OST_Dimensions")).WhereElementIsNotElementType())
                    ids.Add(d.Id);
            }
            catch (Exception) { }
            return ids;
        }

        public static void ResetIsolate(Document doc, View view, FhaDebugLog log)
        {
            Transaction t = FhaRevit.StartTxn(doc, "Hanger dimensions - show all");
            try
            {
                view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate);
                FhaRevit.Committed(t);
            }
            catch (Exception ex)
            {
                FhaRevit.Rollback(t);
                log.Add("reset isolate: " + ex.Message);
            }
        }

        public static bool Isolate(Document doc, View view, IEnumerable<ElementId> ids, FhaDebugLog log)
        {
            Transaction t = FhaRevit.StartTxn(doc, "Hanger dimensions - isolate hangers");
            try
            {
                List<ElementId> lst = new List<ElementId>();
                foreach (ElementId i in ids) lst.Add(i);
                view.IsolateElementsTemporary(lst);
                return FhaRevit.Committed(t);
            }
            catch (Exception ex)
            {
                FhaRevit.Rollback(t);
                log.Add("isolate: " + ex.Message);
                return false;
            }
        }

        /// <summary>The direction of the duct run at a hanger: square to its width axis (null when unreadable).</summary>
        public static V3? RunDirection(Element inst, FamConfig cfg)
        {
            try
            {
                FamilyInstance fi = (FamilyInstance)inst;
                XYZ v = cfg.Get("axis", "X") == "X" ? fi.FacingOrientation : fi.HandOrientation;
                return new V3(v.X, v.Y, 0.0);
            }
            catch (Exception) { return null; }
        }

        /// <summary>Dimension placer: floor plans only. Isolates the hangers (keeping
        /// dimensions visible), lets the user box-select or click hangers, then puts a
        /// centre-to-centre chained dimension along each straight line of hangers,
        /// offset by the chosen distance, and restores the view.</summary>
        public static JobResult JobDims(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            View view = uidoc.ActiveView;
            JobResult res = FhaRevit.NewResult("Dimension placer");
            LogContext(uidoc, settings, log, "Dimension placer");
            if (!IsFloorPlan(view))
            {
                res.Lines.Add("Open a floor plan first - the dimension placer only works in floor plans.");
                return res;
            }
            Dictionary<string, FamConfig> fams = FamsOf(settings);
            HfamChoice chosen = ChoiceOf(settings);
            var names = new HashSet<string>(fams.Keys, StringComparer.Ordinal);
            if (chosen != null && !string.IsNullOrEmpty(chosen.Family)) names.Add(chosen.Family);
            List<FamilyInstance> hangers = ViewHangers(doc, view, names);
            var sortedNames = names.ToList();
            sortedNames.Sort(StringComparer.Ordinal);
            log.Add("hangers in view: " + Inv(hangers.Count) + " (families " + ReprList(sortedNames) + ")");
            if (hangers.Count == 0)
            {
                res.Lines.Add("No hanger families are visible in this view.");
                return res;
            }
            var allowed = new HashSet<long>(hangers.Select(h => Eid(h.Id)));
            ResetIsolate(doc, view, log);
            var isoIds = hangers.Select(h => h.Id).ToList();
            isoIds.AddRange(ViewDimensionIds(doc, view));
            bool isolated = Isolate(doc, view, isoIds, log);
            try { uidoc.RefreshActiveView(); }
            catch (Exception) { }
            var picked = new List<Element>();
            try
            {
                try
                {
                    IList<Reference> refs = uidoc.Selection.PickObjects(ObjectType.Element, new HfamFilter(e => allowed.Contains(Eid(e.Id))),
                                                                        "Select hangers to dimension (box or click), then Finish");
                    picked = refs.Select(r => doc.GetElement(r.ElementId)).ToList();
                }
                catch (Exception)
                {
                    picked = new List<Element>();
                }
                log.Add("picked " + Inv(picked.Count) + " hangers" + (isolated ? "" : " (view could not be isolated)"));
                if (picked.Count < 2)
                {
                    res.Lines.Add("Pick at least two hangers.");
                    return res;
                }
                var items = new List<RunHanger>();
                FamConfig cfgDefault = (chosen != null ? chosen.Cfg : null) ?? new FamConfig();
                var byKey = new List<KeyValuePair<long, Element>>();
                for (int i = 0; i < picked.Count; i++)
                {
                    Element h = picked[i];
                    FamConfig cfg;
                    if (!fams.TryGetValue(ElName(((FamilyInstance)h).Symbol.Family), out cfg)) cfg = cfgDefault;
                    V3? p = InstancePoint(h);
                    V3? d = RunDirection(h, cfg);
                    if (p == null || d == null)
                    {
                        log.Add("hanger " + Inv(Eid(h.Id)) + ": no location / orientation");
                        continue;
                    }
                    items.Add(new RunHanger(i, p.Value, d.Value));
                    byKey.Add(new KeyValuePair<long, Element>(i, h));
                }
                Func<long, Element> byKeyGet = k => byKey.First(x => x.Key == k).Value;
                List<RunGroup> groups = HfamCore.GroupRuns(items, 300.0 / MM);
                var grouped = new HashSet<long>();
                foreach (RunGroup g in groups) foreach (long k in g.Keys) grouped.Add(k);
                List<long> lonely = byKey.Where(x => !grouped.Contains(x.Key)).Select(x => Eid(x.Value.Id)).ToList();
                double offset = FhaCore.AsFloat(settings, "fam_dim_offset", 800.0);
                DimensionType dimType = FhaRevit.FindDimType(doc, SGet(settings, "fam_dim_type", ""));
                Transaction t = FhaRevit.StartTxn(doc, "Hanger dimensions");
                int made = 0;
                try
                {
                    foreach (RunGroup g in groups)
                    {
                        V3 d = g.Dir;
                        List<Element> insts = g.Keys.Select(k => byKeyGet(k)).ToList();
                        List<V3> pts = insts.Select(h => InstancePoint(h).Value).ToList();
                        var refs = new List<KeyValuePair<double, Reference>>();
                        var kinds = new List<string>();
                        for (int n = 0; n < insts.Count; n++)
                        {
                            DimRef dr = DimRefAcross(insts[n], d);
                            kinds.Add(dr.Which);
                            if (dr.Ref != null)
                                refs.Add(new KeyValuePair<double, Reference>(FhaCore.VDot(pts[n], d), dr.Ref));
                        }
                        refs = FhaCore.CollapseRefs(refs, 0.01);
                        log.Add("run along (" + Fm(d.X, 3) + ", " + Fm(d.Y, 3) + "): hangers " + ReprIds(insts.Select(h => Eid(h.Id)))
                                + " | references " + "[" + string.Join(", ", kinds.Select(w => w == null ? "None" : (w == "face" ? ReprStr(w) : "'" + w + "'"))) + "]");   // the centre names are byte str in the Python (no u prefix), 'face' is unicode
                        if (refs.Count < 2)
                        {
                            log.Add("   skipped - fewer than two usable references");
                            continue;
                        }
                        ReferenceArray arr = new ReferenceArray();
                        foreach (var kv in refs) arr.Append(kv.Value);
                        double z = pts[0].Z;
                        V3 p0, p1, nrm;
                        FhaCore.DimLine(new V3(pts[0].X, pts[0].Y, z), new V3(pts[pts.Count - 1].X, pts[pts.Count - 1].Y, z), offset, out p0, out p1, out nrm, 0.0);
                        Line line = Line.CreateBound(ToXyz(p0), ToXyz(p1));
                        try
                        {
                            if (dimType != null)
                                doc.Create.NewDimension(view, line, arr, dimType);
                            else
                                doc.Create.NewDimension(view, line, arr);
                            made++;
                            res.Done += refs.Count;
                            log.Add("   dimension " + Fpt(p0) + " -> " + Fpt(p1) + ", " + Inv(refs.Count) + " references");
                        }
                        catch (Exception ex)
                        {
                            res.Failed++;
                            log.Add("   NewDimension refused: " + ex.Message);
                        }
                    }
                    if (made > 0)
                        FhaRevit.Committed(t);
                    else
                        FhaRevit.Rollback(t);
                }
                catch (Exception ex)
                {
                    log.Add("dimensions: " + ex.Message);
                    FhaRevit.Rollback(t);
                }
                res.Title = "Dimension placer";
                res.Lines.Add(Inv(made) + " chained dimension" + (made == 1 ? "" : "s") + " on " + Inv(groups.Count) + " run" + (groups.Count == 1 ? "" : "s") + ".");
                if (lonely.Count > 0)
                {
                    res.Skipped += lonely.Count;
                    res.Lines.Add(Inv(lonely.Count) + " hanger(s) not in line with another picked hanger: " + ReprIds(lonely));
                }
                return res;
            }
            finally
            {
                ResetIsolate(doc, view, log);
                try { uidoc.RefreshActiveView(); }
                catch (Exception) { }
            }
        }
    }
}
