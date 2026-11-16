using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        // ================================================================ graph
        /// <summary>The connectors of a run member (logical ones left out), in id order.</summary>
        public static List<Connector> GConns(Element el)
        {
            FabricationPart fp = el as FabricationPart;
            if (fp != null) return FhaRevit.AllConns(fp);
            ConnectorManager cm = null;
            try
            {
                MEPCurve mc = el as MEPCurve;
                if (mc != null) cm = mc.ConnectorManager;
            }
            catch (Exception) { }
            if (cm == null)
            {
                try
                {
                    FamilyInstance fi = el as FamilyInstance;
                    cm = fi.MEPModel.ConnectorManager;
                }
                catch (Exception) { cm = null; }
            }
            var o = new List<Connector>();
            try
            {
                foreach (Connector c in cm.Connectors)
                {
                    try
                    {
                        if (c.ConnectorType == ConnectorType.Logical) continue;
                    }
                    catch (Exception) { }
                    o.Add(c);
                }
            }
            catch (Exception) { }
            return o.Select((c, i) => new { c, i }).OrderBy(z => z.c.Id).ThenBy(z => z.i).Select(z => z.c).ToList();
        }

        /// <summary>MEPModel.PartType name -> graph kind.</summary>
        public static readonly Dictionary<string, string> PartKind = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "Elbow", "bend" }, { "Offset", "bend" }, { "Tee", "tee" }, { "Cross", "tee" }, { "Wye", "tee" },
            { "LateralTee", "tee" }, { "LateralCross", "tee" }, { "Pants", "tee" }, { "Transition", "inline" },
            { "Union", "inline" }, { "Cap", "other" }, { "TapPerpendicular", "tap" }, { "TapAdjustable", "tap" },
            { "SpudPerpendicular", "tap" }, { "SpudAdjustable", "tap" },
        };

        public static string GKind(Element el, List<Connector> cons, bool accessories)
        {
            FabricationPart fp = el as FabricationPart;
            if (fp != null) return FhaRevit.Classify(fp, cons);
            if (IsRvtDuct(el)) return "straight";
            int n = cons.Count;
            if (el is FamilyInstance && (CatIs(el, "OST_DuctAccessory") || CatIs(el, "OST_PipeAccessory")))
            {
                if (n >= 2) return accessories ? "accessory" : "inline";
                return "other";
            }
            try
            {
                string k;
                if (PartKind.TryGetValue(Prop(((FamilyInstance)el).MEPModel, "PartType").ToString(), out k) && !string.IsNullOrEmpty(k)) return k;
            }
            catch (Exception) { }
            if (n == 1) return "tap";
            if (n == 2) return FhaCore.VDot(FhaRevit.Axis(cons[0]), FhaRevit.Axis(cons[1])) < -0.98 ? "inline" : "bend";
            return n >= 3 ? "tee" : "other";
        }

        /// <summary>The connector joined to c on another run member, or null.</summary>
        public static Connector GNeighbour(Connector c)
        {
            try
            {
                long own = Eid(c.Owner.Id);
                foreach (Connector r in c.AllRefs)
                {
                    try
                    {
                        if (r.ConnectorType == ConnectorType.Logical) continue;
                    }
                    catch (Exception) { }
                    Element o = r.Owner;
                    if (o != null && Eid(o.Id) != own && IsRunMember(o)) return r;
                }
            }
            catch (Exception) { }
            return null;
        }

        /// <summary>The Python g_record dict: a FhaPart (kind, len, horizontal, conns, cobj, pts, cid, sides, side_ids).
        /// Its conns are FhaConn (to / to_conn / role plus the neighbouring connector Nb, the Python '_nb').</summary>
        public static FhaPart GRecord(Element el, bool accessories)
        {
            List<Connector> cons = GConns(el);
            string kind = GKind(el, cons, accessories);
            var sides = new List<V3>();
            var sideIds = new HashSet<int>();
            if (kind == "straight")
            {
                List<Connector> side;
                FabricationPart fp = el as FabricationPart;
                // frv.end_pair works on any part's connector list; the part itself is not read
                List<Connector> ends = FhaRevit.EndPair(fp, cons, out side);
                sides = side.Select(c => Pt(c.Origin)).ToList();
                sideIds = new HashSet<int>(side.Select(c => c.Id));
                cons = ends;
            }
            var rec = new FhaPart { Kind = kind, Len = 0.0, Horizontal = true, Cobj = cons, Sides = sides, SideIds = sideIds };
            rec.Pts = cons.Select(c => Pt(c.Origin)).ToList();
            for (int k = 0; k < cons.Count; k++) rec.Cid[cons[k].Id] = k;
            if (cons.Count >= 2)
            {
                V3 a = rec.Pts[0], b = rec.Pts[1];
                rec.Len = FhaCore.VLen(FhaCore.VSub(b, a));
                if (kind == "straight")
                    rec.Horizontal = Math.Abs(b.Z - a.Z) < 0.1 * Math.Max(rec.Len, 1e-6);
            }
            foreach (Connector c in cons)
            {
                string role = null;
                if (kind == "tee")
                {
                    role = "branch";
                    foreach (Connector o in cons)
                        if (!ReferenceEquals(o, c) && Math.Abs(FhaCore.VDot(FhaRevit.Axis(c), FhaRevit.Axis(o))) > 0.98)
                            role = "main";
                }
                rec.Conns.Add(new FhaConn { To = null, ToConn = null, Role = role, Nb = GNeighbour(c) });
            }
            return rec;
        }

        /// <summary>What build_graph returns: (parts, elems, selected). Parts are FhaPart (the takeoff markers keyed -id are
        /// plain PartRec); Elems hold any run member (Revit curves, fittings, fabrication parts).</summary>
        public class FamGraph
        {
            public Dictionary<long, PartRec> Parts = new Dictionary<long, PartRec>();
            public Dictionary<long, Element> Elems = new Dictionary<long, Element>();
            public HashSet<long> Selected = new HashSet<long>();
        }

        /// <summary>The selected run plus one ring of neighbours that only type the span ends.</summary>
        public static FamGraph BuildGraph(IEnumerable<Element> seeds, bool accessories, FhaDebugLog log)
        {
            var g = new FamGraph();
            var elems = g.Elems;
            var parts = g.Parts;
            var selected = g.Selected;
            List<Element> seedList = seeds.ToList();
            foreach (Element e in seedList) selected.Add(Eid(e.Id));
            foreach (Element e in seedList)
            {
                elems[Eid(e.Id)] = e;
                parts[Eid(e.Id)] = GRecord(e, accessories);
            }
            foreach (long pid in selected.ToList())
            {
                foreach (ConnRec cr in parts[pid].Conns)
                {
                    FhaConn c = (FhaConn)cr;
                    Connector nb = c.Nb;
                    if (nb == null) continue;
                    long nid = Eid(nb.Owner.Id);
                    if (parts.ContainsKey(nid)) continue;
                    elems[nid] = nb.Owner;
                    FhaPart rec = GRecord(nb.Owner, accessories);
                    if (rec.Kind == "straight")
                        rec.Kind = "other";   // a neighbouring straight is a boundary, not hung
                    parts[nid] = rec;
                }
            }
            var taps = new Dictionary<long, PartRec>();
            foreach (KeyValuePair<long, PartRec> kv in parts)
            {
                long pid = kv.Key;
                FhaPart rec = (FhaPart)kv.Value;
                foreach (ConnRec cr in rec.Conns)
                {
                    FhaConn c = (FhaConn)cr;
                    Connector nb = c.Nb;
                    c.Nb = null;
                    if (nb == null || !selected.Contains(pid)) continue;
                    long nid = Eid(nb.Owner.Id);
                    PartRec otherRec;
                    if (!parts.TryGetValue(nid, out otherRec)) continue;
                    FhaPart other = (FhaPart)otherRec;
                    int ci;
                    if (other.Cid.TryGetValue(nb.Id, out ci))
                    {
                        c.To = nid; c.ToConn = ci;
                    }
                    else if (other.SideIds.Contains(nb.Id))
                    {
                        taps[-nid] = new PartRec { Kind = "tap", Len = 0.0, Horizontal = true };
                        c.To = -nid; c.ToConn = null;
                    }
                }
            }
            foreach (KeyValuePair<long, PartRec> kv in taps) parts[kv.Key] = kv.Value;
            log.Add("run: " + Inv(parts.Count) + " parts, " + Inv(selected.Count) + " selected");
            return g;
        }
    }
}

