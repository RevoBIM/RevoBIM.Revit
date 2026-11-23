using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
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
    }
}
