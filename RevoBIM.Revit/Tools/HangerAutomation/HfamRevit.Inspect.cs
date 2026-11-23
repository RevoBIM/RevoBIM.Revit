using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.HangerAutomation
{
    // =====================================================================================================
    // Inspect lock (diagnostic, no Python original). The owner aligns a hanger to a service BY HAND with Revit's Align tool, selects
    // the hanger (or the service) and presses "Inspect lock": every constraint / dimension that references the element is described
    // (view, references, stable representations, the geometry each reference points at), the service's geometry references are
    // dumped from several sources (so the exact reference the manual alignment uses can be compared with what our geometry walk
    // sees), and the same alignments are re-created through the API inside a rolled-back sub-transaction to see what Revit accepts.
    // Everything verbose goes to the debug file (lines prefixed "inspect:").
    // =====================================================================================================
    public static partial class HfamRevit
    {
        // ---------------------------------------------------------------- small records
        private class InsDim
        {
            public Dimension D;
            public List<Reference> Refs = new List<Reference>();
            public string RefErr;
            public bool Related;   // found through the host / neighbour, not through the selected element itself
        }

        private class InsGeoCount
        {
            public int Solids, EmptySolids, Planar, PlanarNoRef, Cyl, CylNoRef, OtherFace, OtherFaceNoRef, Edges, EdgesNoRef;
            public int Meshes, Lines, LinesNoRef, Curves, CurvesNoRef, Points, PointsNoRef, Instances, Errors;
            public HashSet<string> Others = new HashSet<string>(StringComparer.Ordinal);
        }

        private class InsGeoItem
        {
            public string Path, Kind, Stable;
            public GeometryObject Obj;
        }

        private class InsTally
        {
            public int ObjAttempts, ObjOk, ParsedAttempts, ParsedOk, RemovedObjAttempts, RemovedObjOk, RemovedParsedAttempts, RemovedParsedOk;
            public bool Ran;
        }

        // ---------------------------------------------------------------- the job
        /// <summary>Inspect lock: describes how the selected hanger / service are constrained (by Revit's own Align or dimensions),
        /// dumps the service's geometry references, and replays the alignments through the API (rolled back).</summary>
        public static JobResult JobInspectLock(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            JobResult res = FhaRevit.NewResult("Inspect lock");
            bool wasOn = log.Enabled;
            log.Enabled = true;
            try
            {
                InspectRun(uidoc, log, res);
            }
            catch (Exception ex)
            {
                log.Add("inspect: FAILED " + ex);
                res.Failed++;
                res.Lines.Add("Inspect lock failed: " + ex.Message);
                res.Lines.Add("Press Copy debug and paste it to Claude.");
            }
            if (!wasOn)
                res.Lines.Add("Debug was not ticked: it was switched on for this run, so Copy debug still holds everything (tick Debug to keep it on for other tools).");
            return res;
        }

        private static List<Element> InsSelection(UIDocument uidoc, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            var els = new List<Element>();
            try
            {
                foreach (ElementId id in uidoc.Selection.GetElementIds())
                {
                    Element e = doc.GetElement(id);
                    if (e == null || e is Dimension || e is View) continue;
                    els.Add(e);
                }
            }
            catch (Exception ex) { log.Add("inspect: reading the selection failed - " + InsEx(ex)); }
            if (els.Count == 0)
            {
                try
                {
                    Reference pr = uidoc.Selection.PickObject(ObjectType.Element, "Inspect lock: pick the hanger or the service");
                    Element e = pr != null ? doc.GetElement(pr.ElementId) : null;
                    if (e != null) els.Add(e);
                }
                catch (Autodesk.Revit.Exceptions.OperationCanceledException) { }
                catch (Exception ex) { log.Add("inspect: pick failed - " + InsEx(ex)); }
            }
            return els;
        }

        private static bool InsRefersTo(Reference r, long id)
        {
            try { if (Eid(r.ElementId) == id) return true; }
            catch (Exception) { }
            try { if (Eid(r.LinkedElementId) == id) return true; }
            catch (Exception) { }
            return false;
        }

        private static void InspectRun(UIDocument uidoc, FhaDebugLog log, JobResult res)
        {
            Document doc = uidoc.Document;
            View active = uidoc.ActiveView;
            log.Add("inspect: ===== Inspect lock (Hanger Automation " + FhaCore.Version + ") =====");
            log.Add("inspect: active view " + InsView(doc, active.Id));
            List<Element> picked = InsSelection(uidoc, log);
            if (picked.Count == 0)
            {
                log.Add("inspect: nothing selected");
                res.Lines.Add("Nothing selected. Select the hanger (or the service) in Revit, then press Inspect lock.");
                return;
            }
            var hangers = new List<FamilyInstance>();
            var services = new List<Element>();
            var roles = new Dictionary<long, string>();
            foreach (Element e in picked)
            {
                FamilyInstance fi = e as FamilyInstance;
                if (fi != null) { hangers.Add(fi); roles[Eid(e.Id)] = "hanger"; }
                else { services.Add(e); roles[Eid(e.Id)] = "service"; }
                log.Add("inspect: selected " + (fi != null ? "hanger " : "service ") + InsEl(e));
                if (fi != null)
                {
                    try { log.Add("inspect:   hanger host " + (fi.Host != null ? InsEl(fi.Host) : "none") + ", super component " + (fi.SuperComponent != null ? InsEl(fi.SuperComponent) : "none")); }
                    catch (Exception) { }
                }
            }

            foreach (FamilyInstance fi in hangers) InsDumpHangerRefs(doc, fi, log);

            // ---- every dimension / constraint in the model
            List<InsDim> all = InsAllDims(doc, log);
            int nAlign = all.Count(d => InsIsAlignment(d.D));
            log.Add("inspect: " + Inv(all.Count) + " dimension element(s) in the model (" + Inv(nAlign) + " in the Constraints category)");

            var found = new List<InsDim>();
            var foundIds = new HashSet<long>();
            foreach (Element e in picked)
            {
                long id = Eid(e.Id);
                var mine = all.Where(d => d.Refs.Any(r => InsRefersTo(r, id))).ToList();
                log.Add("inspect: element " + Inv(id) + " is referenced by " + Inv(mine.Count) + " constraint/dimension(s): " + string.Join(", ", mine.Select(d => Inv(Eid(d.D.Id)))));
                foreach (InsDim d in mine)
                    if (foundIds.Add(Eid(d.D.Id))) found.Add(d);
            }
            // ---- a hanger with nothing on it: dimensions in the active view / "Hanger Automation" views on its host or neighbour
            foreach (FamilyInstance fi in hangers)
            {
                long hid = Eid(fi.Id);
                if (all.Any(d => d.Refs.Any(r => InsRefersTo(r, hid)))) continue;
                var partners = new HashSet<long>();
                foreach (Element e in picked) if (Eid(e.Id) != hid) partners.Add(Eid(e.Id));
                try { if (fi.Host != null) partners.Add(Eid(fi.Host.Id)); }
                catch (Exception) { }
                try { if (fi.SuperComponent != null) partners.Add(Eid(fi.SuperComponent.Id)); }
                catch (Exception) { }
                var rel = new List<InsDim>();
                foreach (InsDim d in all)
                {
                    if (foundIds.Contains(Eid(d.D.Id))) continue;
                    bool ok = false;
                    try
                    {
                        View ov = doc.GetElement(d.D.OwnerViewId) as View;
                        ok = Eid(d.D.OwnerViewId) == Eid(active.Id) || (ov != null && ElName(ov).StartsWith("Hanger Automation", StringComparison.Ordinal));
                    }
                    catch (Exception) { }
                    if (ok && d.Refs.Any(r => partners.Any(p => InsRefersTo(r, p)))) rel.Add(d);
                }
                log.Add("inspect: hanger " + Inv(hid) + " is not referenced by any constraint/dimension; " + Inv(rel.Count)
                        + " dimension(s) in the active view or the \"Hanger Automation\" views reference its host / neighbour " + string.Join(",", partners.Select(p => Inv(p))));
                foreach (InsDim d in rel)
                {
                    d.Related = true;
                    if (foundIds.Add(Eid(d.D.Id))) found.Add(d);
                }
            }

            // ---- describe each dimension and its references
            var dimStable = new Dictionary<string, string>(StringComparer.Ordinal);   // stable representation -> where it was used (non-hanger refs)
            var kinds = new HashSet<string>(StringComparer.Ordinal);
            var ownerViews = new List<View>();
            var serviceEls = new List<Element>(services);
            foreach (InsDim d in found)
            {
                InsDescribeDim(doc, d, roles, dimStable, kinds, serviceEls, log);
                try
                {
                    View ov = doc.GetElement(d.D.OwnerViewId) as View;
                    if (ov != null && !ownerViews.Any(v => Eid(v.Id) == Eid(ov.Id))) ownerViews.Add(ov);
                }
                catch (Exception) { }
            }
            foreach (FamilyInstance fi in hangers)
            {
                try
                {
                    if (fi.Host != null && !serviceEls.Any(s => Eid(s.Id) == Eid(fi.Host.Id))) serviceEls.Add(fi.Host);
                }
                catch (Exception) { }
            }

            // ---- the service's geometry references, from several sources
            var foundIn = new Dictionary<string, List<string>>(StringComparer.Ordinal);
            foreach (string s in dimStable.Keys) foundIn[s] = new List<string>();
            var gviews = new List<View>(ownerViews.Take(3));
            if (!gviews.Any(v => Eid(v.Id) == Eid(active.Id))) gviews.Add(active);
            foreach (Element svc in serviceEls)
            {
                log.Add("inspect: ----- geometry of " + InsEl(svc) + " -----");
                foreach (View v in gviews)
                {
                    foreach (bool nonVis in new[] { false, true })
                    {
                        Options opt = new Options { ComputeReferences = true, IncludeNonVisibleObjects = nonVis, View = v };
                        InsDumpSource(doc, svc, "view \"" + ElName(v) + "\" nonvisible=" + (nonVis ? "true" : "false") + (nonVis ? "" : " [as the Locker reads it with a view]"), opt, dimStable, foundIn, log);
                    }
                }
                foreach (ViewDetailLevel dl in new[] { ViewDetailLevel.Coarse, ViewDetailLevel.Medium, ViewDetailLevel.Fine })
                {
                    Options opt = new Options { ComputeReferences = true, IncludeNonVisibleObjects = true, DetailLevel = dl };
                    InsDumpSource(doc, svc, "no view, " + dl + ", nonvisible=true", opt, dimStable, foundIn, log);
                }
                Options lk = new Options { ComputeReferences = true, IncludeNonVisibleObjects = false, DetailLevel = ViewDetailLevel.Fine };
                InsDumpSource(doc, svc, "no view, Fine, nonvisible=false [as the Locker reads it without a view]", lk, dimStable, foundIn, log);
            }
            var conclusions = new List<string>();
            foreach (KeyValuePair<string, List<string>> kv in foundIn)
            {
                string c = "inspect: KEY the reference the dimension uses on the service: " + kv.Key + " (" + dimStable[kv.Key] + ") -> "
                           + (kv.Value.Count == 0 ? "NOT FOUND as an exact reference in ANY of our geometry sources" : "found in: " + string.Join(" | ", kv.Value));
                log.Add(c);
                conclusions.Add(kv.Value.Count == 0 ? "service reference " + kv.Key + " is in none of our sources" : "service reference found in " + Inv(kv.Value.Count) + " source(s), first: " + kv.Value[0]);
            }

            // ---- replay through the API (rolled back)
            InsTally tally = new InsTally();
            InsReplay(doc, active, found, log, tally);

            // ---- the results box
            res.Done = found.Count;
            res.Lines.Add("Constraints/dimensions found on the selection: " + Inv(found.Count) + " (" + Inv(found.Count(d => InsIsAlignment(d.D))) + " alignment(s))"
                          + (found.Any(d => d.Related) ? ", some only through the host / neighbour" : "") + ".");
            if (found.Count > 0)
            {
                res.Lines.Add("Owner view(s): " + (ownerViews.Count == 0 ? "none" : string.Join("; ", ownerViews.Select(v => "\"" + ElName(v) + "\" (" + v.ViewType + ")"))) + ".");
                res.Lines.Add("Reference kinds: " + (kinds.Count == 0 ? "none" : string.Join("; ", kinds)) + ".");
                foreach (string c in conclusions) res.Lines.Add(c.StartsWith("service", StringComparison.Ordinal) ? "Service " + c.Substring(8) + "." : c);
                if (tally.Ran)
                    res.Lines.Add("Replay with Revit's own references (rolled back): " + Inv(tally.ObjOk) + " of " + Inv(tally.ObjAttempts) + " NewAlignment calls worked; re-parsed from stable text: "
                                  + Inv(tally.ParsedOk) + " of " + Inv(tally.ParsedAttempts) + "; with the original alignment removed first: " + Inv(tally.RemovedObjOk) + " of " + Inv(tally.RemovedObjAttempts)
                                  + " (re-parsed " + Inv(tally.RemovedParsedOk) + " of " + Inv(tally.RemovedParsedAttempts) + ").");
                else
                    res.Lines.Add("Replay: not run (no alignment/dimension with exactly two references, or no transaction).");
            }
            else
            {
                res.Lines.Add("No constraint references this element. Align the hanger to the service by hand first (Revit's Align tool, hanger centre plane to the duct), then select the hanger and press Inspect lock again.");
            }
            res.Lines.Add("Press Copy debug and paste it to Claude.");
        }

        /// <summary>EVERY reference of the hanger by every FamilyInstanceReferenceType, with the name (GetReferenceName), the stable
        /// representation and the GetReferenceByName round trip, so a manual alignment's hanger reference can be matched to a name.</summary>
        private static void InsDumpHangerRefs(Document doc, FamilyInstance fi, FhaDebugLog log)
        {
            log.Add("inspect: ----- all references of hanger " + Inv(Eid(fi.Id)) + " by FamilyInstanceReferenceType -----");
            int n = 0;
            foreach (FamilyInstanceReferenceType t in Enum.GetValues(typeof(FamilyInstanceReferenceType)))
            {
                IList<Reference> l;
                try { l = fi.GetReferences(t); }
                catch (Exception ex) { log.Add("inspect:   " + t + ": throws " + InsEx(ex)); continue; }
                if (l == null || l.Count == 0) continue;
                for (int k = 0; k < l.Count; k++)
                {
                    n++;
                    string nm;
                    try { nm = fi.GetReferenceName(l[k]); }
                    catch (Exception ex) { nm = "? " + ex.GetType().Name; }
                    string byName = "";
                    try
                    {
                        Reference b = string.IsNullOrEmpty(nm) ? null : fi.GetReferenceByName(nm);
                        byName = b == null ? " | GetReferenceByName: null" : " | GetReferenceByName: " + (InsStable(doc, b) == InsStable(doc, l[k]) ? "same reference" : "a different reference");
                    }
                    catch (Exception ex) { byName = " | GetReferenceByName throws " + ex.GetType().Name; }
                    string rt;
                    try { rt = l[k].ElementReferenceType.ToString(); } catch (Exception) { rt = "?"; }
                    log.Add("inspect:   " + t + " #" + Inv(k + 1) + " name \"" + nm + "\" " + rt + " stable=" + (InsStable(doc, l[k]) ?? "?") + byName);
                }
            }
            log.Add("inspect:   " + Inv(n) + " reference(s) in total");
        }

        private static bool InsIsAlignment(Dimension d)
        {
            try { return d.Category != null && Eid(d.Category.Id) == (long)BuiltInCategory.OST_Constraints; }
            catch (Exception) { return false; }
        }

        private static List<InsDim> InsAllDims(Document doc, FhaDebugLog log)
        {
            var list = new List<InsDim>();
            var seen = new HashSet<long>();
            Action<IEnumerable<Element>> add = els =>
            {
                foreach (Element e in els)
                {
                    Dimension d = e as Dimension;
                    if (d == null) continue;
                    if (!seen.Add(Eid(d.Id))) continue;
                    var di = new InsDim { D = d };
                    try
                    {
                        ReferenceArray ra = d.References;
                        if (ra != null)
                            for (int i = 0; i < ra.Size; i++) di.Refs.Add(ra.get_Item(i));
                    }
                    catch (Exception ex) { di.RefErr = InsEx(ex); }
                    list.Add(di);
                }
            };
            try { add(new FilteredElementCollector(doc).OfClass(typeof(Dimension)).ToElements()); }
            catch (Exception ex) { log.Add("inspect: collecting Dimension class failed - " + InsEx(ex)); }
            try { add(new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Constraints).WhereElementIsNotElementType().ToElements()); }
            catch (Exception ex) { log.Add("inspect: collecting the Constraints category failed - " + InsEx(ex)); }
            return list;
        }
    }
}
