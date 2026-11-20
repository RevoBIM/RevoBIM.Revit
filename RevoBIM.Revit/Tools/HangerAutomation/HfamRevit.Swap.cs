using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.HangerAutomation
{
    // =====================================================================================================
    // Fab Hanger to Family Swap (Family Hangers tab): select MEP Fabrication hangers already in the model and
    // swap each for the chosen family hanger. The fabrication hanger gives the position along the run, the
    // service(s) it carries and (through them) the size; the family hanger is then placed exactly as Pick and
    // place does it (PlaceOne / HcircRevit.PlaceCirc: width, invert, rod, workset, Comments, locks) on the
    // service itself - never sized from the old hanger. A fab hanger that was not hosted on the right
    // service is re-hosted: the family hanger goes on the service the fab hanger really sits under. The fab
    // hanger is deleted in the same transaction as the placement, so a failed placement leaves it untouched.
    // =====================================================================================================
    public static partial class HfamRevit
    {
        /// <summary>The services a fabrication hanger is swapped onto (what ResolveSwap decides).</summary>
        private class SwapPick
        {
            public Element Lead;
            public List<ServiceRec> Group = new List<ServiceRec>();
            public bool Rehosted;
            public string Why = "";        // how the association was judged, for the log and the result
            public string Skip;            // why the hanger cannot be swapped (null = it can)
        }

        private static readonly string[] SwapCats = { "OST_DuctCurves", "OST_PipeCurves", "OST_CableTray", "OST_Conduit" };

        /// <summary>Level (horizontal) services within `pad` of a box: Revit ducts, pipes, cable trays, conduits and FAB straights,
        /// by bounding box so only the neighbourhood of one hanger is read.</summary>
        private static List<ServiceRec> ServicesNear(Document doc, V3 lo, V3 hi, double pad, FhaDebugLog log)
        {
            var o = new List<ServiceRec>();
            var seen = new HashSet<long>();
            var els = new List<Element>();
            Outline ol = new Outline(new XYZ(lo.X - pad, lo.Y - pad, lo.Z - pad), new XYZ(hi.X + pad, hi.Y + pad, hi.Z + pad));
            BoundingBoxIntersectsFilter bbf = new BoundingBoxIntersectsFilter(ol);
            try
            {
                var cats = new List<BuiltInCategory>();
                foreach (string n in SwapCats)
                {
                    BuiltInCategory? b = BicOrNone(n);
                    if (b != null) cats.Add(b.Value);
                }
                foreach (Element e in new FilteredElementCollector(doc).WherePasses(new ElementMulticategoryFilter(cats)).WherePasses(bbf).WhereElementIsNotElementType())
                    els.Add(e);
            }
            catch (Exception ex)
            {
                log.Add("   swap: services near the hanger: " + ex.Message);
            }
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FabricationPart)).WherePasses(bbf))
                    els.Add(e);
            }
            catch (Exception ex)
            {
                log.Add("   swap: FAB services near the hanger: " + ex.Message);
            }
            foreach (Element e in els)
            {
                try
                {
                    if (!IsHostDuct(e) || !seen.Add(Eid(e.Id))) continue;
                    Section s = SectionCached(e);
                    double len = FhaCore.VLen(FhaCore.VSub(s.B, s.A));
                    if (len < 1e-6 || Math.Abs(s.B.Z - s.A.Z) >= 0.1 * len) continue;   // level straights only
                    o.Add(new ServiceRec { El = e, A = s.A, B = s.B, Width = s.Width, Depth = s.Depth, Ins = s.Ins });
                }
                catch (Exception) { }
            }
            return o;
        }

        /// <summary>Why a service is not what a fab hanger at (hp, box lo..hi, bar at barZ) hangs from; null when it is: its centreline
        /// passes through the hanger's footprint (inside the straight's length) and its underside rests on the bar (or it sits in the
        /// lowest 600 mm of the hanger).</summary>
        private static string AssociationProblem(ServiceRec s, V3 hp, V3 lo, V3 hi, double barZ, double tol)
        {
            double slack = 50.0 / MM;
            double t, len;
            HsvcCore.Station(s.A, s.B, hp, out t, out len);
            if (t < -slack || t > len + slack) return "the hanger is not along that straight (" + Fmm(t) + " mm along a " + Fmm(len) + " mm straight)";
            V3 d = FhaCore.VNorm(FhaCore.VSub(s.B, s.A));
            V3 q = FhaCore.VAdd(s.A, FhaCore.VScale(d, t));
            if (!HsvcCore.InPlanBox(q, lo, hi, slack)) return "its centreline does not pass through the hanger";
            double bottom = q.Z - s.Depth / 2.0;
            bool rest = HsvcCore.RestsOn(bottom, barZ, tol) || HsvcCore.RestsOn(bottom - s.Ins, barZ, tol);
            bool low = q.Z + s.Depth / 2.0 >= lo.Z - tol && bottom <= lo.Z + 600.0 / MM;
            if (!rest && !low)
                return "its underside is at " + Fmm(bottom) + " mm, the hanger's bar at " + Fmm(barZ) + " mm";
            return null;
        }

        /// <summary>Decide which service(s) a fabrication hanger is swapped onto: its own host when that is right, else the
        /// service(s) its bar really carries (the rules HsvcCore.Carried uses for hangers), else the nearest level service within
        /// the search radius.</summary>
        private static SwapPick ResolveSwap(Document doc, FabricationPart fab, FhaSettings settings, double radius, FhaDebugLog log)
        {
            var pick = new SwapPick();
            long fid = Eid(fab.Id);
            V3? hpn = FhaRevit.HangerPoint(fab);
            BoundingBoxXYZ bb = null;
            try { bb = fab.get_BoundingBox(null); }
            catch (Exception) { }
            if (hpn == null || bb == null)
            {
                pick.Skip = "its position could not be read";
                return pick;
            }
            V3 hp = hpn.Value;
            V3 lo = new V3(bb.Min.X, bb.Min.Y, bb.Min.Z), hi = new V3(bb.Max.X, bb.Max.Y, bb.Max.Z);
            double barZ = lo.Z;
            double tol = (FhaCore.AsFloat(settings, "svc_tol", HsvcCore.RestTolMm) + 100.0) / MM;
            double pad = Math.Max(radius, 600.0 / MM);
            List<ServiceRec> near = ServicesNear(doc, lo, hi, pad, log);
            Element host = FhaRevit.HangerHost(doc, fab);
            log.Add("swap: fab hanger " + Inv(fid) + " (" + ElName(fab) + ") at " + Fpt(hp) + " | box z " + Fmm(lo.Z) + " .. " + Fmm(hi.Z) + " | host "
                    + (host != null ? Describe(host) : "none") + " | " + Inv(near.Count) + " level service(s) within " + Fmm(pad) + " mm");
            ServiceRec hostRec = host != null ? near.FirstOrDefault(s => Eid(s.El.Id) == Eid(host.Id)) : null;
            string hostWhy;
            if (host == null) hostWhy = "it has no host";
            else if (!IsHostDuct(host)) hostWhy = "its host is not a duct, pipe, cable tray, conduit or FAB straight";
            else if (hostRec == null)
            {
                // a valid straight the box search missed (or one that is not level): judge it on its own
                hostWhy = null;
                try
                {
                    Section hs = SectionCached(host);
                    double hl = FhaCore.VLen(FhaCore.VSub(hs.B, hs.A));
                    if (hl < 1e-6 || Math.Abs(hs.B.Z - hs.A.Z) >= 0.1 * hl) hostWhy = "its host is not a level straight";
                    else
                    {
                        hostRec = new ServiceRec { El = host, A = hs.A, B = hs.B, Width = hs.Width, Depth = hs.Depth, Ins = hs.Ins };
                        near.Add(hostRec);
                    }
                }
                catch (Exception ex) { hostWhy = "its host could not be read (" + ex.Message + ")"; }
            }
            else hostWhy = null;
            if (hostWhy == null && hostRec != null) hostWhy = AssociationProblem(hostRec, hp, lo, hi, barZ, tol);
            // what the bar really carries
            List<ServiceRec> carried = HsvcCore.Carried(new HangerBox(hp, lo, hi), near, CarryRule.Bar(barZ), tol, 50.0 / MM);
            log.Add("   swap: bar at " + Fmm(barZ) + " carries [" + string.Join(", ", carried.Select(s => Describe(s.El))) + "] | host "
                    + (hostWhy == null ? "is right" : "is wrong: " + hostWhy));
            if (hostWhy == null && hostRec != null)
            {
                pick.Lead = hostRec.El;
                pick.Group = carried.Where(s => Eid(s.El.Id) != Eid(hostRec.El.Id)).ToList();
                pick.Group.Insert(0, hostRec);
                pick.Why = "its host is right";
                return pick;
            }
            pick.Rehosted = true;
            ServiceRec lead = null;
            if (carried.Count > 0)
            {
                double best = double.MaxValue;
                foreach (ServiceRec s in carried)
                {
                    double tt; V3 qq; double dd;
                    FhaCore.ClosestOnSegment(new V3(hp.X, hp.Y, 0.0), new V3(s.A.X, s.A.Y, 0.0), new V3(s.B.X, s.B.Y, 0.0), out tt, out qq, out dd);
                    if (dd < best) { best = dd; lead = s; }
                }
                pick.Group = carried;
                pick.Why = "carried by its bar";
            }
            else
            {
                var segs = near.Select(s => new HostSeg { Id = Eid(s.El.Id), A = s.A, B = s.B, Horizontal = true, Tag = s }).ToList();
                NearestHostResult nh = FhaCore.NearestHost(hp, segs, radius, EndMargin);
                if (nh != null)
                {
                    lead = (ServiceRec)nh.Host.Tag;
                    pick.Group = new List<ServiceRec> { lead };
                    pick.Why = "nearest service (" + Fmm(nh.D) + " mm away)";
                }
            }
            if (lead == null)
            {
                pick.Skip = "no duct, pipe, cable tray or conduit under it within " + Fmm(radius) + " mm"
                            + (hostWhy != null ? " (" + hostWhy + ")" : "");
                return pick;
            }
            pick.Lead = lead.El;
            return pick;
        }

        /// <summary>The (family hanger, service) pairs the swap made, for the read-back after the group closes.</summary>
        private class SwapDone
        {
            public FamilyInstance Inst;
            public Section Sec;
        }

        /// <summary>Fab Hanger to Family Swap: select fabrication hangers, swap each for the chosen family hanger placed with the
        /// Pick and place rules on the service it hangs from (re-hosting it when the fab hanger was on the wrong one).</summary>
        public static JobResult JobSwap(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = FhaRevit.NewResult("Fab Hanger to Family Swap");
            if (IsFloor(settings))
            {
                res.Lines.Add("Fab Hanger to Family Swap works on the Family Hangers tab - switch tabs and try again.");
                return res;
            }
            FamConfig cfg;
            FamilySymbol symbol = Chosen(uidoc, settings, res, out cfg);
            if (symbol == null)
                return res;
            List<FabricationPart> fabs = FhaRevit.GetSelection(uidoc, "hanger", "Select the fabrication hangers to swap for the chosen family hanger");
            if (fabs.Count == 0)
            {
                res.Lines.Add("No fabrication hangers selected.");
                return res;
            }
            fabs = fabs.GroupBy(f => Eid(f.Id)).Select(g => g.First()).OrderBy(f => Eid(f.Id)).ToList();
            bool circ = HcircCore.IsCirc(cfg);
            bool rod = FhaCore.AsBool(settings, "fam_rod_place");
            bool outside = FhaCore.AsBool(settings, "fam_ins_place");
            LogContext(uidoc, settings, log, "Fab Hanger to Family Swap", symbol, cfg);
            log.Add("swap: " + Inv(fabs.Count) + " fabrication hanger(s) -> " + ElName(symbol.Family) + " : " + ElName(symbol)
                    + (circ ? " (Circular System Based: round services only)" : "") + " | rod " + (rod ? "on" : "off") + " | hanger "
                    + (outside ? "outside" : "inside") + " the insulation");
            double radius = FhaCore.AsFloat(settings, "search_radius", 1500.0) / MM;
            GroupRules rules = HfamCore.WrapRules(HfamCore.GroupRulesFrom(settings));
            Locker locker = FhaCore.AsBool(settings, "fam_lock_place") ? new Locker(doc, uidoc.ActiveView, log) : null;
            if (locker != null && circ) locker.ElevationCentre = true;
            if (FhaCore.AsBool(settings, "fam_dims"))
                log.Add("swap: dimensions are not made by Pick and place - skipped");
            FhaRevit.Checkout(doc, fabs.Cast<Element>().ToList(), log);
            FhaRevit.Worksets ws = new FhaRevit.Worksets(doc, SGet(settings, "fam_workset", ""), log);
            var issues = new List<string>();
            var rehostLines = new List<string>();
            var skipLines = new List<string>();
            var done = new List<SwapDone>();
            int swapped = 0, rehosted = 0;
            TransactionGroup tg = new TransactionGroup(doc, "Hanger Automation - swap fab hangers for family hangers");
            tg.Start();
            SoffitFinder finder = null;
            try
            {
                // inside the try: the transaction group is already open and must always be closed
                finder = new SoffitFinder(doc, settings, log, rod && cfg.Get("soffit", "") == "structure");
                foreach (FabricationPart fab in fabs)
                {
                    try
                    {
                        if (!fab.IsValidObject) continue;   // gone with an earlier swap (a hanger in a group, say)
                    }
                    catch (Exception) { continue; }
                    long fid = Eid(fab.Id);
                    Transaction t = null;
                    int rehostMark = rehostLines.Count;
                    try
                    {
                        SwapPick pick;
                        using (HaTiming.Time("read"))
                            pick = ResolveSwap(doc, fab, settings, radius, log);
                        if (pick.Skip != null)
                        {
                            log.Add("   swap: left in the model - " + pick.Skip);
                            skipLines.Add("Fab hanger " + Inv(fid) + " stays in the model: " + pick.Skip + ".");
                            res.Skipped++;
                            continue;
                        }
                        Element lead = pick.Lead;
                        V3 hp = FhaRevit.HangerPoint(fab).Value;
                        Section sec;
                        V3 q;
                        if (circ)
                        {
                            sec = HfamCore.ApplyInsulation(SectionCached(lead), outside);
                            if (!sec.Round)
                            {
                                string msg = "Fab hanger " + Inv(fid) + " stays in the model: " + HcircRevit.NotRoundText(Describe(lead), "hanger");
                                log.Add("   swap: left in the model - " + msg);
                                skipLines.Add(msg);
                                res.Skipped++;
                                continue;
                            }
                            q = HfamCore.OnCentreline(sec.A, sec.B, hp, EndMargin);
                            sec.Keys = new List<long> { Eid(lead.Id) };
                        }
                        else
                        {
                            sec = Fitted(lead, outside);
                            q = HfamCore.OnCentreline(sec.A, sec.B, hp, EndMargin);
                            sec.Keys = new List<long> { Eid(lead.Id) };
                            if (pick.Group.Count > 1)
                            {
                                var others = pick.Group.Select(g => new ServiceSec(g.El, Fitted(g.El, outside))).ToList();
                                BundleResult br = BundleFor(lead, sec, q, others, outside, log, rules);
                                sec = br.Sec;
                                q = br.Point;
                                List<Element> left = pick.Group.Where(g => !sec.Keys.Contains(Eid(g.El.Id))).Select(g => g.El).ToList();
                                if (left.Count > 0)
                                    log.Add("   swap: not round the same hanger (not parallel / not alongside): " + string.Join(", ", left.Select(e => Describe(e))));
                            }
                        }
                        if (pick.Rehosted)
                        {
                            string rl = "Fab hanger " + Inv(fid) + ": wrong association -> re-hosted to "
                                        + string.Join(" + ", (sec.Keys ?? new List<long>()).Select(k => Describe(doc.GetElement(new ElementId(k)) ?? lead)));
                            log.Add("   swap: " + rl.Substring(rl.IndexOf(':') + 2) + " (" + pick.Why + ")");
                            rehostLines.Add(rl);
                        }
                        t = FhaRevit.StartTxn(doc, "Swap fab hanger for family hanger");
                        finder.Skip.Add(fid);   // the old hanger's rods are not a soffit
                        PlaceOutcome po = circ
                            ? HcircRevit.PlaceCirc(doc, symbol, lead, sec, q, cfg, log, ws, null, rod, finder)
                            : PlaceOne(doc, symbol, lead, sec, q, cfg, rod, finder, log, ws, null);
                        List<string> problems = po.Problems;
                        LockIf(locker, po.Inst, lead, sec, q, problems, log);
                        if (po.Inst != null)
                        {
                            using (HaTiming.Time("delete"))
                                doc.Delete(fab.Id);   // same transaction: if this does not commit the fab hanger is still there
                        }
                        bool committed;
                        using (HaTiming.Time("commit"))
                            committed = po.Inst != null && FhaRevit.Committed(t);
                        if (!committed)
                        {
                            FhaRevit.Rollback(t);
                            res.Failed++;
                            string why = po.Inst == null && problems.Count > 0 ? string.Join("; ", problems) : "Revit did not accept the swap";
                            skipLines.Add("Fab hanger " + Inv(fid) + " stays in the model: " + why + ".");
                            log.Add("   swap: failed - " + why);
                            if (pick.Rehosted) rehostLines.RemoveAt(rehostLines.Count - 1);
                            continue;
                        }
                        t = null;
                        swapped++;
                        if (pick.Rehosted) rehosted++;
                        issues.AddRange(problems);
                        done.Add(new SwapDone { Inst = po.Inst, Sec = sec });
                        log.Add("   swap: fab hanger " + Inv(fid) + " -> family hanger " + Inv(Eid(po.Inst.Id)));
                    }
                    catch (Exception ex)
                    {
                        log.Add("swap " + Inv(fid) + ": " + ex.Message);
                        if (t != null) FhaRevit.Rollback(t);
                        while (rehostLines.Count > rehostMark) rehostLines.RemoveAt(rehostLines.Count - 1);   // it was not re-hosted after all
                        res.Failed++;
                        skipLines.Add("Fab hanger " + Inv(fid) + " stays in the model: " + ex.Message + ".");
                    }
                    finally
                    {
                        HaTiming.Flush(log);
                    }
                }
            }
            finally
            {
                if (finder != null) finder.Close();
                tg.Assimilate();
                HaTiming.EndJob(log, "Fab Hanger to Family Swap");
            }
            var newIds = new List<ElementId>();
            foreach (SwapDone d in done)   // read back after the group has closed
            {
                bool ok = circ ? HcircRevit.VerifyCirc(d.Inst, cfg, d.Sec, issues) : Verify(d.Inst, cfg, d.Sec, res, issues, log);
                if (ok)
                {
                    res.Done++;
                    newIds.Add(d.Inst.Id);
                }
                else
                    res.Failed++;
            }
            if (newIds.Count > 0)
            {
                try { uidoc.Selection.SetElementIds(newIds); }
                catch (Exception) { }
            }
            res.Lines.Insert(0, Inv(swapped) + " swapped, " + Inv(rehosted) + " re-hosted to the right service");
            res.Lines.AddRange(rehostLines.Take(12));
            if (rehostLines.Count > 12) res.Lines.Add("... and " + Inv(rehostLines.Count - 12) + " more re-hosted.");
            res.Lines.AddRange(skipLines);
            res.Lines.AddRange(SortedDistinct(issues));
            res.Lines.AddRange(ws.Problems);
            return res;
        }
    }
}
