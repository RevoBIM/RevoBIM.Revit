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

        // ---------------------------------------------------------------- formatting helpers
        private static string InsEx(Exception ex)
        {
            string m = ex.Message ?? "";
            return ex.GetType().FullName + ": " + m.Replace("\r", " ").Replace("\n", " ");
        }

        private static string InsP(XYZ p)
        {
            if (p == null) return "null";
            return "(" + Fm(p.X * MM, 1) + ", " + Fm(p.Y * MM, 1) + ", " + Fm(p.Z * MM, 1) + ")";
        }

        private static string InsDir(XYZ v)
        {
            if (v == null) return "null";
            return "(" + Fm(v.X, 4) + ", " + Fm(v.Y, 4) + ", " + Fm(v.Z, 4) + ")";
        }

        private static string InsStable(Document doc, Reference r)
        {
            if (r == null) return null;
            try { return r.ConvertToStableRepresentation(doc); }
            catch (Exception) { return null; }
        }

        private static string InsCat(Element e)
        {
            try { return e.Category != null ? e.Category.Name : "(no category)"; }
            catch (Exception) { return "(category ?)"; }
        }

        private static string InsEl(Element e)
        {
            if (e == null) return "null";
            string extra = "";
            FamilyInstance fi = e as FamilyInstance;
            if (fi != null)
            {
                try { extra = " family \"" + ElName(fi.Symbol.Family) + "\" type \"" + ElName(fi.Symbol) + "\""; }
                catch (Exception) { }
            }
            return Inv(Eid(e.Id)) + " " + e.GetType().Name + " [" + InsCat(e) + "] \"" + ElName(e) + "\"" + extra;
        }

        private static string InsView(Document doc, ElementId id)
        {
            View v = null;
            try { v = doc.GetElement(id) as View; }
            catch (Exception) { }
            if (v == null) return "none (id " + Inv(Eid(id)) + ")";
            var sb = new StringBuilder();
            sb.Append(Inv(Eid(v.Id)) + " \"" + ElName(v) + "\"");
            try { sb.Append(" type " + v.ViewType); } catch (Exception) { }
            try { sb.Append(" detail " + v.DetailLevel); } catch (Exception) { }
            try { sb.Append(" discipline " + v.Discipline); } catch (Exception) { }
            return sb.ToString();
        }

        private static string InsCurve(Curve c)
        {
            if (c == null) return "null";
            try
            {
                if (!c.IsBound) return c.GetType().Name + " unbound";
                XYZ a = c.GetEndPoint(0), b = c.GetEndPoint(1);
                string dir = "";
                try { dir = " dir " + InsDir((b - a).Normalize()); }
                catch (Exception) { }
                return c.GetType().Name + " from " + InsP(a) + " to " + InsP(b) + dir + " length " + Fm(c.Length * MM, 1) + " mm";
            }
            catch (Exception ex) { return c.GetType().Name + " (" + ex.GetType().Name + ")"; }
        }

        private static string InsGeomDetail(GeometryObject g)
        {
            try
            {
                PlanarFace pf = g as PlanarFace;
                if (pf != null) return "origin " + InsP(pf.Origin) + " normal " + InsDir(pf.FaceNormal) + " area " + Fm(pf.Area * MM * MM, 0) + " mm2";
                Face f = g as Face;
                if (f != null) return "area " + Fm(f.Area * MM * MM, 0) + " mm2";
                Line ln = g as Line;
                if (ln != null)
                {
                    string dir = "";
                    try { dir = " dir " + InsDir(ln.Direction); }
                    catch (Exception) { }
                    return "from " + InsP(ln.GetEndPoint(0)) + " to " + InsP(ln.GetEndPoint(1)) + dir + " length " + Fm(ln.Length * MM, 1) + " mm";
                }
                Curve cu = g as Curve;
                if (cu != null) return InsCurve(cu);
                Edge ed = g as Edge;
                if (ed != null) return "edge curve " + InsCurve(ed.AsCurve());
                Mesh me = g as Mesh;
                if (me != null) return "mesh with " + Inv(me.Vertices.Count) + " vertices, " + Inv(me.NumTriangles) + " triangles";
                Point pt = g as Point;
                if (pt != null) return "point " + InsP(pt.Coord);
            }
            catch (Exception ex) { return "(detail failed: " + ex.GetType().Name + ")"; }
            return "";
        }

        // ---------------------------------------------------------------- geometry walk (counts + references)
        private static void InsWalk(Document doc, IEnumerable<GeometryObject> geo, string path, int depth, Dictionary<string, InsGeoCount> counts, List<InsGeoItem> items)
        {
            InsGeoCount c;
            if (!counts.TryGetValue(path, out c))
            {
                c = new InsGeoCount();
                counts[path] = c;
            }
            foreach (GeometryObject g in geo)
            {
                if (g == null) continue;
                GeometryInstance gi = g as GeometryInstance;
                Solid so = g as Solid;
                Mesh me = g as Mesh;
                Curve cu = g as Curve;
                Point pt = g as Point;
                if (gi != null)
                {
                    c.Instances++;
                    if (depth < 3)
                    {
                        try { InsWalk(doc, gi.GetInstanceGeometry(), path + ">inst", depth + 1, counts, items); }
                        catch (Exception) { c.Errors++; }
                        try { InsWalk(doc, gi.GetSymbolGeometry(), path + ">sym", depth + 1, counts, items); }
                        catch (Exception) { c.Errors++; }
                    }
                }
                else if (so != null)
                {
                    c.Solids++;
                    try
                    {
                        if (so.Faces.Size == 0) c.EmptySolids++;
                        foreach (Face f in so.Faces)
                        {
                            Reference r = null;
                            try { r = f.Reference; }
                            catch (Exception) { }
                            string kind;
                            if (f is PlanarFace) { c.Planar++; kind = "PlanarFace"; if (r == null) c.PlanarNoRef++; }
                            else if (f is CylindricalFace) { c.Cyl++; kind = "CylindricalFace"; if (r == null) c.CylNoRef++; }
                            else { c.OtherFace++; kind = f.GetType().Name; c.Others.Add(kind); if (r == null) c.OtherFaceNoRef++; }
                            if (r != null && items.Count < 3000) items.Add(new InsGeoItem { Path = path, Kind = kind, Stable = InsStable(doc, r), Obj = f });
                        }
                    }
                    catch (Exception) { c.Errors++; }
                    try
                    {
                        foreach (Edge e in so.Edges)
                        {
                            c.Edges++;
                            Reference r = null;
                            try { r = e.Reference; }
                            catch (Exception) { }
                            if (r == null) c.EdgesNoRef++;
                            else if (items.Count < 3000) items.Add(new InsGeoItem { Path = path, Kind = "Edge", Stable = InsStable(doc, r), Obj = e });
                        }
                    }
                    catch (Exception) { c.Errors++; }
                }
                else if (me != null) c.Meshes++;
                else if (cu != null)
                {
                    Reference r = null;
                    try { r = cu.Reference; }
                    catch (Exception) { }
                    bool isLine = cu is Line;
                    if (isLine) c.Lines++; else c.Curves++;
                    if (r == null) { if (isLine) c.LinesNoRef++; else c.CurvesNoRef++; }
                    else if (items.Count < 3000) items.Add(new InsGeoItem { Path = path, Kind = isLine ? "Line" : cu.GetType().Name, Stable = InsStable(doc, r), Obj = cu });
                }
                else if (pt != null)
                {
                    c.Points++;
                    Reference r = null;
                    try { r = pt.Reference; }
                    catch (Exception) { }
                    if (r == null) c.PointsNoRef++;
                    else if (items.Count < 3000) items.Add(new InsGeoItem { Path = path, Kind = "Point", Stable = InsStable(doc, r), Obj = pt });
                }
                else c.Others.Add(g.GetType().Name);
            }
        }

        private static string InsCountText(InsGeoCount c)
        {
            var p = new List<string>();
            if (c.Solids > 0)
                p.Add("solids " + Inv(c.Solids) + (c.EmptySolids > 0 ? " (" + Inv(c.EmptySolids) + " empty)" : "") + ", faces: planar " + Inv(c.Planar) + " (ref null " + Inv(c.PlanarNoRef)
                      + "), cylindrical " + Inv(c.Cyl) + " (ref null " + Inv(c.CylNoRef) + "), other " + Inv(c.OtherFace) + " (ref null " + Inv(c.OtherFaceNoRef) + "), edges " + Inv(c.Edges)
                      + " (ref null " + Inv(c.EdgesNoRef) + ")");
            if (c.Meshes > 0) p.Add("meshes " + Inv(c.Meshes));
            if (c.Lines > 0) p.Add("lines " + Inv(c.Lines) + " (ref null " + Inv(c.LinesNoRef) + ")");
            if (c.Curves > 0) p.Add("arcs/curves " + Inv(c.Curves) + " (ref null " + Inv(c.CurvesNoRef) + ")");
            if (c.Points > 0) p.Add("points " + Inv(c.Points) + " (ref null " + Inv(c.PointsNoRef) + ")");
            if (c.Instances > 0) p.Add("instances " + Inv(c.Instances));
            if (c.Others.Count > 0) p.Add("other types " + string.Join("/", c.Others));
            if (c.Errors > 0) p.Add("errors " + Inv(c.Errors));
            return p.Count == 0 ? "empty" : string.Join(", ", p);
        }

        private static string InsCountsText(Dictionary<string, InsGeoCount> counts)
        {
            return string.Join("; ", counts.Select(kv => kv.Key + " {" + InsCountText(kv.Value) + "}"));
        }

        /// <summary>One compact line: what the geometry of an element holds as the Locker's own walk (ElementFaces) sees it
        /// (ComputeReferences, no hidden objects; the view's geometry or Fine without a view), counted by type per nesting level
        /// (top level, GetInstanceGeometry, GetSymbolGeometry). Used by the lock when it finds no side / bottom faces.</summary>
        public static string InsGeoSummary(Document doc, Element el, View view)
        {
            try
            {
                Options opt = new Options();
                opt.ComputeReferences = true;
                opt.IncludeNonVisibleObjects = false;
                if (view != null) opt.View = view;
                else
                {
                    try { opt.DetailLevel = ViewDetailLevel.Fine; }
                    catch (Exception) { }
                }
                GeometryElement geo = el.get_Geometry(opt);
                if (geo == null) return "get_Geometry returned null";
                var counts = new Dictionary<string, InsGeoCount>();
                InsWalk(doc, geo, "top", 0, counts, new List<InsGeoItem>());
                return InsCountsText(counts);
            }
            catch (Exception ex) { return "geometry could not be read: " + InsEx(ex); }
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

        // ---------------------------------------------------------------- one dimension / alignment
        private static void InsDescribeDim(Document doc, InsDim di, Dictionary<long, string> roles, Dictionary<string, string> dimStable, HashSet<string> kinds,
                                           List<Element> serviceEls, FhaDebugLog log)
        {
            Dimension d = di.D;
            var sb = new StringBuilder();
            sb.Append("inspect: DIMENSION " + Inv(Eid(d.Id)) + " class " + d.GetType().Name + " category " + InsCat(d) + (InsIsAlignment(d) ? " (ALIGNMENT)" : "") + (di.Related ? " (related, via host/neighbour)" : ""));
            try
            {
                DimensionType dt = doc.GetElement(d.GetTypeId()) as DimensionType;
                sb.Append(" | type " + (dt != null ? "\"" + ElName(dt) + "\" style " + dt.StyleType : "none"));
            }
            catch (Exception ex) { sb.Append(" | type ? " + ex.GetType().Name); }
            sb.Append(" | view " + InsView(doc, d.OwnerViewId));
            try { sb.Append(" | IsLocked " + d.IsLocked); } catch (Exception ex) { sb.Append(" | IsLocked ? " + ex.GetType().Name); }
            try { sb.Append(" | AreSegmentsEqual " + d.AreSegmentsEqual); } catch (Exception ex) { sb.Append(" | AreSegmentsEqual ? " + ex.GetType().Name); }
            try
            {
                double? v = d.Value;
                sb.Append(" | Value " + (v.HasValue ? Fm(v.Value * MM, 3) + " mm" : "none"));
            }
            catch (Exception ex) { sb.Append(" | Value ? " + ex.GetType().Name); }
            try { sb.Append(" | NumberOfSegments " + Inv(d.NumberOfSegments)); } catch (Exception ex) { sb.Append(" | NumberOfSegments ? " + ex.GetType().Name); }
            try
            {
                var vals = new List<string>();
                foreach (DimensionSegment sg in d.Segments)
                    vals.Add(sg.Value.HasValue ? Fm(sg.Value.Value * MM, 3) : "?");
                if (vals.Count > 0) sb.Append(" | segment values (mm) " + string.Join(" / ", vals));
            }
            catch (Exception) { }
            try { sb.Append(" | Origin " + InsP(d.Origin)); } catch (Exception ex) { sb.Append(" | Origin ? " + ex.GetType().Name); }
            try { sb.Append(" | Curve " + InsCurve(d.Curve)); } catch (Exception ex) { sb.Append(" | Curve ? " + ex.GetType().Name); }
            sb.Append(" | references " + Inv(di.Refs.Count) + (di.RefErr != null ? " (reading them failed: " + di.RefErr + ")" : ""));
            log.Add(sb.ToString());
            for (int i = 0; i < di.Refs.Count; i++)
                InsDescribeRef(doc, d, i, di.Refs[i], roles, dimStable, kinds, serviceEls, log);
        }

        private static void InsDescribeRef(Document doc, Dimension d, int index, Reference r, Dictionary<long, string> roles, Dictionary<string, string> dimStable,
                                           HashSet<string> kinds, List<Element> serviceEls, FhaDebugLog log)
        {
            string head = "inspect:   dim " + Inv(Eid(d.Id)) + " ref " + Inv(index) + ": ";
            long eid = 0, leid = 0;
            try { eid = Eid(r.ElementId); } catch (Exception) { }
            try { leid = Eid(r.LinkedElementId); } catch (Exception) { }
            bool linked = leid > 0;
            Element owner = null, linkedEl = null;
            try { owner = doc.GetElement(r.ElementId); } catch (Exception) { }
            if (linked)
            {
                try
                {
                    RevitLinkInstance li = owner as RevitLinkInstance;
                    Document ld = li != null ? li.GetLinkDocument() : null;
                    if (ld != null) linkedEl = ld.GetElement(r.LinkedElementId);
                }
                catch (Exception) { }
            }
            Element described = linkedEl ?? owner;
            string role;
            if (!roles.TryGetValue(eid, out role)) role = described is FamilyInstance ? "hanger?" : "other";
            string rtype;
            try { rtype = r.ElementReferenceType.ToString(); } catch (Exception ex) { rtype = "? " + ex.GetType().Name; }
            string gp;
            try { gp = InsP(r.GlobalPoint); } catch (Exception ex) { gp = "? " + ex.GetType().Name; }
            string stable = InsStable(doc, r);
            var sb = new StringBuilder();
            sb.Append(head + "ElementId " + Inv(eid) + " (" + (owner != null ? InsEl(owner) : "not found") + ")");
            sb.Append(" | LinkedElementId " + (linked ? Inv(leid) + (linkedEl != null ? " (" + InsEl(linkedEl) + ")" : "") : "none"));
            sb.Append(" | role " + role + " | ElementReferenceType " + rtype + " | GlobalPoint " + gp);
            sb.Append(" | stable=" + (stable ?? "?"));
            log.Add(sb.ToString());

            GeometryObject g = null;
            string gtype;
            try
            {
                g = owner != null ? owner.GetGeometryObjectFromReference(r) : null;
                gtype = g == null ? "null" : g.GetType().FullName + " (visibility " + g.Visibility + ", element geometry " + g.IsElementGeometry + ")";
            }
            catch (Exception ex) { gtype = "throws " + InsEx(ex); }
            string geq = "";
            try
            {
                Face gf = g as Face;
                Curve gc = g as Curve;
                Edge ge = g as Edge;
                Reference gr = gf != null ? gf.Reference : gc != null ? gc.Reference : ge != null ? ge.Reference : null;
                if (gr != null) geq = " | geometry.Reference stable " + (InsStable(doc, gr) == stable ? "EQUALS" : "DIFFERS from") + " the dimension's reference";
            }
            catch (Exception) { }
            log.Add(head + "geometry " + gtype + (g != null ? " " + InsGeomDetail(g) : "") + geq);

            string kind = role + ": " + rtype + " -> " + (g == null ? "no geometry object" : g.GetType().Name);
            kinds.Add(kind);

            FamilyInstance inst = (owner as FamilyInstance) ?? (linkedEl as FamilyInstance);
            if (inst != null)
            {
                var where = new List<string>();
                foreach (FamilyInstanceReferenceType t in Enum.GetValues(typeof(FamilyInstanceReferenceType)))
                {
                    try
                    {
                        IList<Reference> l = inst.GetReferences(t);
                        for (int k = 0; k < l.Count; k++)
                        {
                            if (InsStable(doc, l[k]) != stable) continue;
                            string nm = "";
                            try { nm = inst.GetReferenceName(l[k]); }
                            catch (Exception) { nm = "?"; }
                            where.Add(t + " #" + Inv(k + 1) + " name \"" + nm + "\"");
                        }
                    }
                    catch (Exception) { }
                }
                log.Add(head + "hanger reference list: " + (where.Count == 0 ? "NOT in any inst.GetReferences(type) list (exact stable compare)" : string.Join("; ", where)));
            }
            else if (role != "hanger" && stable != null && !dimStable.ContainsKey(stable))
            {
                dimStable[stable] = "dim " + Inv(Eid(d.Id)) + " ref " + Inv(index) + ", " + rtype + (g != null ? ", " + g.GetType().Name : "");
            }
            if (inst == null && described != null && !(described is FamilyInstance) && !serviceEls.Any(s => Eid(s.Id) == Eid(described.Id)) && linkedEl == null)
                serviceEls.Add(described);
        }

        // ---------------------------------------------------------------- the service geometry from one source
        private static void InsDumpSource(Document doc, Element svc, string label, Options opt, Dictionary<string, string> dimStable,
                                          Dictionary<string, List<string>> foundIn, FhaDebugLog log)
        {
            string head = "inspect:   source [" + label + "]: ";
            GeometryElement geo = null;
            try { geo = svc.get_Geometry(opt); }
            catch (Exception ex)
            {
                log.Add(head + "get_Geometry throws " + InsEx(ex));
                return;
            }
            if (geo == null)
            {
                log.Add(head + "get_Geometry returned null");
                return;
            }
            var counts = new Dictionary<string, InsGeoCount>();
            var items = new List<InsGeoItem>();
            try { InsWalk(doc, geo, "top", 0, counts, items); }
            catch (Exception ex) { log.Add(head + "walk failed " + InsEx(ex)); }
            log.Add(head + InsCountsText(counts));
            var seen = new HashSet<string>(StringComparer.Ordinal);
            var stables = new List<string>();
            int shown = 0, hidden = 0;
            foreach (InsGeoItem it in items)
            {
                string key = it.Path + "|" + it.Stable;
                if (!seen.Add(key)) continue;
                if (it.Stable != null) stables.Add(it.Stable);
                bool match = it.Stable != null && dimStable.ContainsKey(it.Stable);
                if (match) foundIn[it.Stable].Add(label + " @ " + it.Path + " (" + it.Kind + ")");
                if (!(it.Kind == "Line" || it.Kind == "PlanarFace" || match)) continue;
                if (shown >= 40 && !match) { hidden++; continue; }
                shown++;
                log.Add(head + "  ref " + it.Path + " " + it.Kind + " stable=" + (it.Stable ?? "?") + " " + InsGeomDetail(it.Obj) + (match ? "  <== EQUALS A DIMENSION REFERENCE" : ""));
            }
            if (hidden > 0) log.Add(head + "  ... " + Inv(hidden) + " more Line/PlanarFace reference(s) not listed");
            foreach (KeyValuePair<string, string> kv in dimStable)
            {
                if (stables.Contains(kv.Key)) continue;
                int best = 0;
                foreach (string s in stables)
                {
                    int n = 0, m = Math.Min(s.Length, kv.Key.Length);
                    while (n < m && s[n] == kv.Key[n]) n++;
                    if (n > best) best = n;
                }
                log.Add(head + "  dimension reference " + kv.Key + " NOT in this source (" + Inv(stables.Count) + " references here; the closest shares its first " + Inv(best) + " of " + Inv(kv.Key.Length) + " characters)");
            }
        }

        // ---------------------------------------------------------------- replay (always rolled back)
        private static void InsReplay(Document doc, View active, List<InsDim> found, FhaDebugLog log, InsTally tally)
        {
            var two = found.Where(d => d.Refs.Count == 2).Take(8).ToList();
            if (two.Count == 0)
            {
                log.Add("inspect: replay skipped - no alignment/dimension with exactly two references");
                return;
            }
            Transaction tr = new Transaction(doc, "Hanger Automation - inspect lock (replay, rolled back)");
            try { tr.Start(); }
            catch (Exception ex)
            {
                log.Add("inspect: replay skipped - the transaction could not start: " + InsEx(ex));
                return;
            }
            tally.Ran = true;
            try
            {
                foreach (InsDim di in two)
                {
                    Dimension d = di.D;
                    var views = new List<KeyValuePair<string, View>>();
                    try
                    {
                        View ov = doc.GetElement(d.OwnerViewId) as View;
                        if (ov != null && !ov.IsTemplate) views.Add(new KeyValuePair<string, View>("owner view \"" + ElName(ov) + "\"", ov));
                    }
                    catch (Exception) { }
                    if (active is ViewPlan && !views.Any(v => Eid(v.Value.Id) == Eid(active.Id)))
                        views.Add(new KeyValuePair<string, View>("active plan \"" + ElName(active) + "\"", active));
                    string s0 = InsStable(doc, di.Refs[0]), s1 = InsStable(doc, di.Refs[1]);
                    log.Add("inspect: REPLAY of dimension " + Inv(Eid(d.Id)) + " in " + Inv(views.Count) + " view(s); refs " + (s0 ?? "?") + "  &  " + (s1 ?? "?"));
                    foreach (bool removed in new[] { false, true })
                    {
                        foreach (KeyValuePair<string, View> vk in views)
                        {
                            foreach (bool swap in new[] { false, true })
                            {
                                foreach (bool parsed in new[] { false, true })
                                {
                                    string outcome = InsTry(doc, d, vk.Value, di.Refs[swap ? 1 : 0], di.Refs[swap ? 0 : 1], swap ? s1 : s0, swap ? s0 : s1, parsed, removed, out bool ok);
                                    if (removed)
                                    {
                                        if (parsed) { tally.RemovedParsedAttempts++; if (ok) tally.RemovedParsedOk++; }
                                        else { tally.RemovedObjAttempts++; if (ok) tally.RemovedObjOk++; }
                                    }
                                    else if (parsed) { tally.ParsedAttempts++; if (ok) tally.ParsedOk++; }
                                    else { tally.ObjAttempts++; if (ok) tally.ObjOk++; }
                                    log.Add("inspect:   NewAlignment(" + vk.Key + ", " + (swap ? "ref1, ref0" : "ref0, ref1") + ", " + (parsed ? "re-parsed from stable text" : "the existing reference objects")
                                            + (removed ? ", original removed first" : ", original still present") + "): " + outcome);
                                }
                            }
                        }
                    }
                }
            }
            finally
            {
                try
                {
                    if (tr.GetStatus() == TransactionStatus.Started) tr.RollBack();
                }
                catch (Exception) { }
            }
            log.Add("inspect: replay rolled back (the model is unchanged)");
        }

        private static string InsTry(Document doc, Dimension original, View view, Reference a, Reference b, string sa, string sb, bool parsed, bool removed, out bool ok)
        {
            ok = false;
            SubTransaction st = new SubTransaction(doc);
            try { st.Start(); }
            catch (Exception ex) { return "sub-transaction could not start: " + InsEx(ex); }
            try
            {
                if (removed)
                {
                    try { doc.Delete(original.Id); }
                    catch (Exception ex) { return "could not remove the original first: " + InsEx(ex); }
                }
                Reference ra = a, rb = b;
                if (parsed)
                {
                    try
                    {
                        ra = Reference.ParseFromStableRepresentation(doc, sa);
                        rb = Reference.ParseFromStableRepresentation(doc, sb);
                    }
                    catch (Exception ex) { return "re-parsing the stable text failed: " + InsEx(ex); }
                    if (ra == null || rb == null) return "re-parsing the stable text gave null";
                }
                try
                {
                    Dimension nd = doc.Create.NewAlignment(view, ra, rb);
                    ok = nd != null;
                    return nd != null ? "OK, accepted (new element " + Inv(Eid(nd.Id)) + ", rolled back)" : "returned null";
                }
                catch (Exception ex) { return "REFUSED " + InsEx(ex); }
            }
            finally
            {
                try { st.RollBack(); }
                catch (Exception) { }
            }
        }
    }
}
