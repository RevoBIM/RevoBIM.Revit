using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    /// <summary>A graph connector record: the fha_core ConnRec plus the neighbouring Revit connector (Python '_nb', popped once the links are resolved).</summary>
    public class FhaConn : ConnRec
    {
        public Connector Nb;
    }

    /// <summary>
    /// fha_core part record plus the Revit bits the jobs need (the Python part_record dict):
    /// Cobj (connector objects in conns order), Pts (their origins), Cid (connector Id -> index),
    /// Sides (origins of tap connectors cut into a straight), SideIds (their connector Ids).
    /// </summary>
    public class FhaPart : PartRec
    {
        public List<Connector> Cobj = new List<Connector>();
        public List<V3> Pts = new List<V3>();
        public Dictionary<int, int> Cid = new Dictionary<int, int>();
        public List<V3> Sides = new List<V3>();
        public HashSet<int> SideIds = new HashSet<int>();
    }

    /// <summary>What BuildGraph returns: parts (fha_core shape; FhaPart for real parts, plain PartRec for the takeoff markers keyed -id), elems and the selected ids.</summary>
    public class FhaGraph
    {
        public Dictionary<long, PartRec> Parts = new Dictionary<long, PartRec>();
        public Dictionary<long, FabricationPart> Elems = new Dictionary<long, FabricationPart>();
        public HashSet<long> Selected = new HashSet<long>();
    }

    /// <summary>A horizontal duct straight and its two end connectors (the Python info[id] = (element, ends)).</summary>
    public class StraightInfo
    {
        public FabricationPart Element;
        public List<Connector> Ends;
    }

    public static partial class FhaRevit
    {
        // ============================================================ connectors
        public static List<Connector> AllConns(FabricationPart part)
        {
            var o = new List<Connector>();
            try
            {
                foreach (Connector c in part.ConnectorManager.Connectors) o.Add(c);
            }
            catch (Exception) { }
            return o.Select((c, i) => new { c, i }).OrderBy(z => z.c.Id).ThenBy(z => z.i).Select(z => z.c).ToList();
        }

        public static V3 Axis(Connector c)
        {
            try { return Pt(c.CoordinateSystem.BasisZ); }
            catch (Exception) { return new V3(0.0, 0.0, 0.0); }
        }

        /// <summary>(ends, sides): the two end connectors of a straight, and any side
        /// (tap) connectors cut into it. Ends are the anti-parallel pair furthest apart.</summary>
        public static List<Connector> EndPair(FabricationPart part, List<Connector> cons, out List<Connector> sides)
        {
            if (cons.Count <= 2)
            {
                sides = new List<Connector>();
                return cons;
            }
            bool have = false;
            double bestD = 0; int bi = 0, bj = 0;
            for (int i = 0; i < cons.Count; i++)
            {
                for (int j = i + 1; j < cons.Count; j++)
                {
                    if (FhaCore.VDot(Axis(cons[i]), Axis(cons[j])) < -0.98)
                    {
                        double d = cons[i].Origin.DistanceTo(cons[j].Origin);
                        if (!have || d > bestD)
                        {
                            have = true; bestD = d; bi = i; bj = j;
                        }
                    }
                }
            }
            if (!have)
            {
                sides = cons.Skip(2).ToList();
                return cons.Take(2).ToList();
            }
            var ends = new List<Connector> { cons[bi], cons[bj] };
            sides = new List<Connector>();
            for (int k = 0; k < cons.Count; k++)
                if (k != bi && k != bj) sides.Add(cons[k]);
            return ends;
        }

        /// <summary>The connector joined to c on another fabrication part, or null.</summary>
        public static Connector Neighbour(Connector c)
        {
            try
            {
                long own = EidValue(c.Owner.Id);
                foreach (Connector r in c.AllRefs)
                {
                    Element o = r.Owner;
                    if (o != null && EidValue(o.Id) != own && IsFab(o) && !IsHanger(o))
                        return r;
                }
            }
            catch (Exception) { }
            return null;
        }

        public static string Classify(FabricationPart part, List<Connector> cons)
        {
            if (IsTap(part)) return "tap";
            int n = cons.Count;
            if (IsStraight(part)) return "straight";
            if (n == 1) return "tap";
            if (n == 2) return FhaCore.VDot(Axis(cons[0]), Axis(cons[1])) < -0.98 ? "inline" : "bend";
            if (n >= 3) return "tee";
            return "other";
        }

        /// <summary>fha_core part record, plus the Revit bits the jobs need (see FhaPart).</summary>
        public static FhaPart PartRecord(FabricationPart part)
        {
            List<Connector> cons = AllConns(part);
            string kind = Classify(part, cons);
            var sides = new List<V3>();
            if (kind == "straight")
            {
                List<Connector> side;
                cons = EndPair(part, cons, out side);
                sides = side.Select(c => Pt(c.Origin)).ToList();
            }
            var rec = new FhaPart { Kind = kind, Len = 0.0, Horizontal = true, Cobj = cons, Sides = sides };
            rec.Pts = cons.Select(c => Pt(c.Origin)).ToList();
            for (int k = 0; k < cons.Count; k++) rec.Cid[cons[k].Id] = k;
            if (kind == "straight" && cons.Count == 2)
            {
                V3 a = rec.Pts[0], b = rec.Pts[1];
                rec.Len = FhaCore.VLen(FhaCore.VSub(b, a));
                rec.Horizontal = Math.Abs(b.Z - a.Z) < 0.1 * Math.Max(rec.Len, 1e-6);
                var endIds = new HashSet<int>(cons.Select(c => c.Id));
                foreach (Connector c in AllConns(part))
                    if (!endIds.Contains(c.Id)) rec.SideIds.Add(c.Id);
            }
            else if (cons.Count >= 2)
            {
                rec.Len = FhaCore.VLen(FhaCore.VSub(rec.Pts[1], rec.Pts[0]));
            }
            foreach (Connector c in cons)
            {
                string role = null;
                if (kind == "tee")
                {
                    role = "branch";
                    foreach (Connector o in cons)
                        if (!ReferenceEquals(o, c) && Math.Abs(FhaCore.VDot(Axis(c), Axis(o))) > 0.98)
                            role = "main";
                }
                rec.Conns.Add(new FhaConn { To = null, ToConn = null, Role = role, Nb = Neighbour(c) });
            }
            return rec;
        }

        /// <summary>parts (fha_core shape) and elems, for the selected ducts.
        ///
        /// 'Selected run only' keeps the selection plus one ring of neighbours, which
        /// only type the ends of the spans (a neighbouring straight becomes a plain
        /// boundary so it never gets hangers of its own). 'Whole connected system'
        /// walks everything connected.</summary>
        public static FhaGraph BuildGraph(IEnumerable<FabricationPart> seeds, bool wholeSystem, FhaDebugLog log)
        {
            var g = new FhaGraph();
            var elems = g.Elems;
            var parts = g.Parts;
            var todo = new List<FabricationPart>(seeds);
            var seen = new HashSet<long>(todo.Select(e => EidValue(e.Id)));
            var selected = g.Selected;
            foreach (long s in seen) selected.Add(s);
            while (todo.Count > 0)
            {
                FabricationPart e = todo[todo.Count - 1];
                todo.RemoveAt(todo.Count - 1);
                long pid = EidValue(e.Id);
                elems[pid] = e;
                FhaPart prec = PartRecord(e);
                parts[pid] = prec;
                foreach (ConnRec cr in prec.Conns)
                {
                    FhaConn c = (FhaConn)cr;
                    Connector nb = c.Nb;
                    if (nb == null) continue;
                    FabricationPart o = nb.Owner as FabricationPart;
                    long nid = EidValue(nb.Owner.Id);
                    if (seen.Contains(nid)) continue;
                    seen.Add(nid);
                    if (wholeSystem && IsDuct(nb.Owner))
                    {
                        selected.Add(nid);
                        todo.Add(o);
                    }
                    else
                    {
                        elems[nid] = o;
                        FhaPart rec = PartRecord(o);
                        if (rec.Kind == "straight" || !IsDuct(nb.Owner)) rec.Kind = "other";
                        parts[nid] = rec;
                    }
                }
            }
            // resolve links now every record exists
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
                    if (nb == null) continue;
                    long nid = EidValue(nb.Owner.Id);
                    if (!parts.ContainsKey(nid) || !selected.Contains(pid)) continue;
                    FhaPart other = (FhaPart)parts[nid];
                    int ci;
                    if (other.Cid.TryGetValue(nb.Id, out ci))
                    {
                        c.To = nid; c.ToConn = ci;
                    }
                    else if (other.SideIds.Contains(nb.Id))
                    {
                        // this run starts at a tap cut into another straight: a takeoff
                        long key = -nid;
                        taps[key] = new PartRec { Kind = "tap", Len = 0.0, Horizontal = true };
                        c.To = key; c.ToConn = null;
                    }
                }
            }
            foreach (KeyValuePair<long, PartRec> kv in taps) parts[kv.Key] = kv.Value;
            log.Add("graph: " + parts.Count.ToString(CultureInfo.InvariantCulture) + " parts, "
                    + selected.Count.ToString(CultureInfo.InvariantCulture) + " selected, "
                    + taps.Count.ToString(CultureInfo.InvariantCulture) + " takeoff ends");
            return g;
        }

        /// <summary>Origins of every fabrication tap in the model (taps hosted on a straight
        /// are not always joined to it through a connector).</summary>
        public static List<V3> AllTapPoints(Document doc)
        {
            var o = new List<V3>();
            try
            {
                var col = new FilteredElementCollector(doc).OfCategory(Bic("OST_FabricationDuctwork")).WhereElementIsNotElementType();
                foreach (Element e in col)
                {
                    if (IsFab(e) && IsTap(e))
                    {
                        try { o.Add(PartOrigin((FabricationPart)e)); }
                        catch (Exception) { }
                    }
                }
            }
            catch (Exception) { }
            return o;
        }

        /// <summary>FabricationPart.Origin (the Python e.Origin); throws if the part has none.</summary>
        public static V3 PartOrigin(FabricationPart p)
        {
            return Pt(p.Origin);
        }

        /// <summary>Horizontal fabrication duct straights as fha_core hosts, plus id -> (element, ends).</summary>
        public static List<HostSeg> StraightHosts(Document doc, out Dictionary<long, StraightInfo> info)
        {
            var hosts = new List<HostSeg>();
            info = new Dictionary<long, StraightInfo>();
            var col = new FilteredElementCollector(doc).OfCategory(Bic("OST_FabricationDuctwork")).WhereElementIsNotElementType();
            foreach (Element e in col)
            {
                if (!IsDuct(e) || !IsStraight(e)) continue;
                FabricationPart fp = (FabricationPart)e;
                List<Connector> side;
                List<Connector> ends = EndPair(fp, AllConns(fp), out side);
                if (ends.Count != 2) continue;
                V3 a = Pt(ends[0].Origin), b = Pt(ends[1].Origin);
                double L = FhaCore.VLen(FhaCore.VSub(b, a));
                long hid = EidValue(e.Id);
                hosts.Add(new HostSeg { Id = hid, A = a, B = b, Horizontal = Math.Abs(a.Z - b.Z) < 0.1 * Math.Max(L, 1e-6) });
                info[hid] = new StraightInfo { Element = fp, Ends = ends };
            }
            return hosts;
        }
    }
}
