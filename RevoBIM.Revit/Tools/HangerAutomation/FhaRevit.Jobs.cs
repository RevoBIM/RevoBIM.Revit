using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using DimTargetsT = RevoBIM.Tools.HangerAutomation.DimTargets;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class FhaRevit
    {
        // ================================================================== jobs
        /// <summary>A span's hangers to place, planned before anything is written (the Python job dict).</summary>
        private class PlaceSpec
        {
            public FabricationPart Host;
            public Connector Conn;
            public double Dist;
        }

        private class PlaceJob
        {
            public List<PlaceSpec> Places;
            public V3 PStart, PEnd;
            public FabricationPart First, Last;
            public double Length;
        }

        private class RehostPlan
        {
            public FabricationPart Hanger, Host;
            public Connector Conn;
            public double Dist;
        }

        private class RehostOutcome
        {
            public FabricationPart Hanger, Host;
            public string How;
        }

        /// <summary>Plain dictionary get, as Python's settings.get(key, default).</summary>
        private static string SGet(FhaSettings s, string key, string dflt)
        {
            string v;
            if (s != null && s.TryGetValue(key, out v)) return v;
            return dflt;
        }

        /// <summary>Job entry for the window: extend the selected hangers' rods to structure.</summary>
        public static JobResult JobExtend(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            return JobExtend(uidoc, settings, log, null);
        }

        public static JobResult JobExtend(UIDocument uidoc, FhaSettings settings, FhaDebugLog log, List<FabricationPart> hangers)
        {
            Document doc = uidoc.Document;
            JobResult res = NewResult("Extend hangers to structure");
            if (hangers == null)
                hangers = GetSelection(uidoc, "hanger", "Select fabrication hangers to extend to structure");
            if (hangers.Count == 0)
            {
                res.Lines.Add("No fabrication hangers selected.");
                return res;
            }
            Checkout(doc, hangers, log);
            Worksets ws = new Worksets(doc, SGet(settings, "workset", ""), log);
            var tally = new Dictionary<string, int> { { "extended", 0 }, { "already", 0 }, { "attached", 0 }, { "failed", 0 } };
            TransactionGroup tg = new TransactionGroup(doc, "Hanger Automation - extend rods");
            tg.Start();
            Soffit soffit = new Soffit(doc, settings, log);
            try
            {
                if (!soffit.Ok())
                    res.Lines.Add("Using Revit attach to structure only: " + soffit.Reason + ".");
                foreach (FabricationPart h in hangers)
                {
                    Transaction t = StartTxn(doc, "Extend rods");
                    bool moved = false;
                    string outcome;
                    try
                    {
                        ws.Apply(h, HangerHost(doc, h), false);
                        moved = ws.LastMoved;
                        outcome = ExtendRods(doc, h, soffit, log);
                    }
                    catch (Exception ex)
                    {
                        log.Add("extend " + Inv(EidValue(h.Id)) + ": " + ex.Message);
                        outcome = "failed";
                    }
                    if (outcome == "already" && moved)
                        Committed(t);   // rods fine, but it changed workset
                    else if (outcome == "failed" || outcome == "already")
                        Rollback(t);
                    else if (!Committed(t))
                        outcome = "failed";
                    int cur;
                    tally.TryGetValue(outcome, out cur);
                    tally[outcome] = cur + 1;
                }
            }
            finally
            {
                soffit.Close();
                tg.Assimilate();
            }
            res.Done = tally["extended"] + tally["attached"];
            res.Skipped = tally["already"];
            res.Failed = tally["failed"];
            if (tally["attached"] != 0)
                res.Lines.Add(tally["attached"].ToString(CultureInfo.InvariantCulture) + " attached with Revit attach to structure (no soffit found by ray).");
            if (tally["already"] != 0)
                res.Lines.Add(tally["already"].ToString(CultureInfo.InvariantCulture) + " already at structure.");
            if (tally["failed"] != 0)
                res.Lines.Add(tally["failed"].ToString(CultureInfo.InvariantCulture) + " found no structure above - check the ticked categories and that the slab is loaded.");
            res.Lines.AddRange(ws.Problems);
            return res;
        }

        /// <summary>Re-host each selected hanger on its nearest duct.
        ///
        /// Replace mode (default): the hanger is replaced by a new one placed on the
        /// duct exactly as if it had just been placed - so it takes the duct's width,
        /// depth and condition - keeping workset, Comments, Mark, shared parameters
        /// and rod tops. Move mode: PlaceOnHost only (Revit keeps the old size).</summary>
        public static JobResult JobRehost(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = NewResult("Auto rehost and size");
            List<FabricationPart> hangers = GetSelection(uidoc, "hanger", "Select fabrication hangers to rehost");
            if (hangers.Count == 0)
            {
                res.Lines.Add("No fabrication hangers selected.");
                return res;
            }
            bool replace = FhaCore.AsBool(settings, "rehost_replace");
            double radius = FhaCore.AsFloat(settings, "search_radius", 1500.0) / MM;
            Dictionary<long, StraightInfo> info;
            List<HostSeg> hosts = StraightHosts(doc, out info);
            log.Add(hosts.Count.ToString(CultureInfo.InvariantCulture) + " horizontal straights; mode " + (replace ? "replace" : "move"));
            var plan = new List<RehostPlan>();
            foreach (FabricationPart h in hangers)
            {
                V3? p = HangerPoint(h);
                NearestHostResult near = p != null ? FhaCore.NearestHost(p.Value, hosts, radius, EndMargin) : null;
                if (near == null)
                {
                    res.Skipped++;
                    log.Add("hanger " + Inv(EidValue(h.Id)) + ": no duct within " + Fmt(radius * MM, 0) + " mm");
                    continue;
                }
                StraightInfo si = info[near.Host.Id];
                plan.Add(new RehostPlan { Hanger = h, Host = si.Element, Conn = si.Ends[0], Dist = near.Dist });
            }
            if (plan.Count == 0)
            {
                res.Lines.Add("No duct straight within " + Fmt(radius * MM, 0) + " mm of the selected hangers.");
                return res;
            }
            HangerMatcher matcher = replace ? new HangerMatcher(doc, SGet(settings, "button", ""), log) : null;
            if (replace && matcher.Picker.All.Count == 0)
            {
                res.Lines.Add("No hanger buttons in the loaded fabrication services - moving the hangers instead.");
                replace = false;
            }
            var toCheckout = new List<Element>();
            toCheckout.AddRange(plan.Select(x => (Element)x.Hanger));
            toCheckout.AddRange(plan.Select(x => (Element)x.Host));
            Checkout(doc, toCheckout, log);
            Worksets ws = new Worksets(doc, SGet(settings, "workset", ""), log);
            TransactionGroup tg = new TransactionGroup(doc, "Hanger Automation - rehost");
            tg.Start();
            var outcome = new List<RehostOutcome>();   // (hanger to read back, host, how)
            foreach (RehostPlan rp in plan)
            {
                FabricationPart old = rp.Hanger;
                FabricationPart host = rp.Host;
                Connector conn = rp.Conn;
                double dist = rp.Dist;
                Transaction t = StartTxn(doc, "Rehost hanger");
                try
                {
                    FabricationPart nw = null;
                    string note = "";
                    if (replace)
                        nw = ReplaceHanger(doc, old, host, conn, dist, matcher, log, ws, out note);
                    if (nw != null)
                    {
                        if (Committed(t))
                            outcome.Add(new RehostOutcome { Hanger = nw, Host = host, How = "replaced" });
                        else
                            res.Failed++;
                        continue;
                    }
                    if (replace)
                    {
                        log.Add("hanger " + Inv(EidValue(old.Id)) + ": " + note + "; moving it instead");
                        Rollback(t);
                        t = StartTxn(doc, "Rehost hanger");
                    }
                    bool placed = PlaceOnHost(old, host, conn, dist, log);
                    if (placed) ws.Apply(old, host, false);
                    if (placed && Committed(t))
                        outcome.Add(new RehostOutcome { Hanger = old, Host = host, How = "moved" });
                    else
                    {
                        Rollback(t);
                        res.Failed++;
                    }
                }
                catch (Exception ex)
                {
                    log.Add("rehost " + Inv(EidValue(old.Id)) + ": " + ex.Message);
                    Rollback(t);
                    res.Failed++;
                }
            }
            tg.Assimilate();
            var good = new List<FabricationPart>();
            int replaced = 0, moved = 0;
            foreach (RehostOutcome oc in outcome)   // read back after the group has closed
            {
                bool ok;
                try { ok = oc.Hanger.IsValidObject && HostOf(oc.Hanger) == EidValue(oc.Host.Id); }
                catch (Exception) { ok = false; }
                if (ok)
                {
                    good.Add(oc.Hanger);
                    res.Done++;
                    replaced += oc.How == "replaced" ? 1 : 0;
                    moved += oc.How == "moved" ? 1 : 0;
                }
                else
                {
                    res.Failed++;
                }
            }
            if (replaced != 0)
                res.Lines.Add(replaced.ToString(CultureInfo.InvariantCulture) + " replaced with a new hanger sized to its duct.");
            if (moved != 0)
                res.Lines.Add(moved.ToString(CultureInfo.InvariantCulture) + " moved only (kept their old size)"
                              + (replace ? " - see Copy debug for why" : "") + ".");
            if (good.Count > 0)
            {
                try
                {
                    List<ElementId> ids = new List<ElementId>();
                    foreach (FabricationPart h in good) ids.Add(h.Id);
                    uidoc.Selection.SetElementIds(ids);
                }
                catch (Exception) { }
            }
            if (good.Count > 0 && FhaCore.AsBool(settings, "extend_after"))
            {
                JobResult r2 = JobExtend(uidoc, settings, log, good);
                res.Lines.Add("Rods: " + r2.Done.ToString(CultureInfo.InvariantCulture) + " to structure, "
                              + r2.Skipped.ToString(CultureInfo.InvariantCulture) + " already there, "
                              + r2.Failed.ToString(CultureInfo.InvariantCulture) + " not found.");
            }
            foreach (string p in ws.Problems)
                if (!res.Lines.Contains(p)) res.Lines.Add(p);
            return res;
        }

        public static JobResult JobPlace(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = NewResult("Auto place hangers");
            List<FabricationPart> seeds = GetSelection(uidoc, "duct", "Select the fabrication duct run to hang");
            if (seeds.Count == 0)
            {
                res.Lines.Add("No fabrication duct selected.");
                return res;
            }
            bool whole = SGet(settings, "scope", "run") == "system";
            FhaGraph graph = BuildGraph(seeds, whole, log);
            Dictionary<long, PartRec> parts = graph.Parts;
            Dictionary<long, FabricationPart> elems = graph.Elems;
            HashSet<long> selected = graph.Selected;
            List<Span> spans = FhaCore.BuildSpans(parts)
                .Where(s => s.Chain.Any(it => it.Kind == "straight" && selected.Contains(it.Id))).ToList();
            if (spans.Count == 0)
            {
                res.Lines.Add("No horizontal straight runs in the selection.");
                return res;
            }
            PlanConfig cfg = FhaCore.PlanConfigFrom(settings);
            double clearTk = cfg.TakeoffClear / MM;
            double edge = cfg.Edge / MM;
            ButtonPicker picker = new ButtonPicker(doc, SGet(settings, "button", ""), log);
            if (picker.All.Count == 0)
            {
                res.Lines.Add("No hanger buttons in the loaded fabrication services - load a hanger service first.");
                return res;
            }
            List<V3> tapPts = AllTapPoints(doc);
            var existing = new List<V3>();
            if (FhaCore.AsBool(settings, "skip_existing"))
            {
                foreach (Element h in new FilteredElementCollector(doc).OfCategory(Bic("OST_FabricationHangers")).WhereElementIsNotElementType())
                {
                    V3? p = HangerPoint(h);
                    if (p != null) existing.Add(p.Value);
                }
            }
            double existClear = FhaCore.AsFloat(settings, "existing_clear", 300.0) / MM;
            DimTargetsT targets = DimTargets(uidoc, settings, "dims", res, log);
            bool wantDims = targets != null;
            DimensionType dimType = FindDimType(doc, SGet(settings, "dim_type", ""));
            bool wantRods = FhaCore.AsBool(settings, "extend_place");

            // ---- plan everything before writing anything
            var jobs = new List<PlaceJob>();
            foreach (Span span in spans)
            {
                List<ChainItem> chain = span.Chain;
                var points = new Dictionary<long, KeyValuePair<V3, V3>>();
                foreach (ChainItem it in chain)
                {
                    FhaPart rec = (FhaPart)parts[it.Id];
                    if (rec.Pts.Count >= 2)
                        points[it.Id] = new KeyValuePair<V3, V3>(rec.Pts[it.Entry], rec.Pts[it.Exit]);
                }
                List<SpanSeg> segs = FhaCore.SpanSegments(chain, points);
                if (segs.Count == 0) continue;
                double length = FhaCore.SpanLength(span);
                List<double> st = FhaCore.PlanStations(length, span.StartEnd.Type, span.EndEnd.Type, cfg);
                var blocks = new List<V3>();
                foreach (ChainItem it in chain)
                    foreach (V3 sp in ((FhaPart)parts[it.Id]).Sides) blocks.Add(sp);
                blocks.AddRange(tapPts);
                var blockSt = new List<double>();
                foreach (V3 b in blocks)
                {
                    double? s = FhaCore.StationOfPoint(segs, b, TapReach);
                    if (s != null) blockSt.Add(s.Value);
                }
                st = FhaCore.AvoidBlocks(st, blockSt, clearTk, length, edge);
                st = FhaCore.Dedupe(st, cfg.MinGap / MM / 2.0);
                if (existing.Count > 0)
                {
                    var exSt = new List<double>();
                    foreach (V3 e in existing)
                    {
                        double? s = FhaCore.StationOfPoint(segs, e, TapReach);
                        if (s != null) exSt.Add(s.Value);
                    }
                    int before = st.Count;
                    st = FhaCore.DropNear(st, exSt, existClear);
                    res.Skipped += before - st.Count;
                }
                long firstId = chain[0].Id;
                long lastId = chain[chain.Count - 1].Id;
                V3 pStart = points.ContainsKey(firstId) ? points[firstId].Key : segs[0].A;
                V3 pEnd = points.ContainsKey(lastId) ? points[lastId].Value : segs[segs.Count - 1].B;
                List<ChainItem> straights = chain.Where(it => it.Kind == "straight").ToList();
                long firstSt = straights[0].Id;
                long lastSt = straights[straights.Count - 1].Id;
                var places = new List<PlaceSpec>();
                foreach (double s in st)
                {
                    Located loc = FhaCore.Locate(chain, s, EndMargin);
                    if (loc == null) continue;
                    FhaPart rec = (FhaPart)parts[loc.Id];
                    places.Add(new PlaceSpec { Host = elems[loc.Id], Conn = rec.Cobj[loc.Entry], Dist = loc.Dist });
                }
                if (places.Count > 0)
                    jobs.Add(new PlaceJob { Places = places, PStart = pStart, PEnd = pEnd, First = elems[firstSt], Last = elems[lastSt], Length = length });
                log.Add("span " + Fmt(length * MM, 0) + " mm (" + span.StartEnd.Type + " -> " + span.EndEnd.Type + "): "
                        + places.Count.ToString(CultureInfo.InvariantCulture) + " hangers, "
                        + blockSt.Count.ToString(CultureInfo.InvariantCulture) + " takeoffs on it");
            }
            if (jobs.Count == 0)
            {
                res.Lines.Add("Nothing to place - every span already has its hangers or is a takeoff stub.");
                return res;
            }

            // ---- write
            var hostEls = new List<Element>();
            foreach (PlaceJob j in jobs)
                hostEls.AddRange(j.Places.Select(p => (Element)p.Host));
            Checkout(doc, hostEls, log);
            Worksets ws = new Worksets(doc, SGet(settings, "workset", ""), log);
            TransactionGroup tg = new TransactionGroup(doc, "Hanger Automation - place hangers");
            tg.Start();
            Soffit soffit = wantRods ? new Soffit(doc, settings, log) : null;
            var created = new List<KeyValuePair<FabricationPart, FabricationPart>>();   // (hanger, host)
            var rods = new Dictionary<string, int> { { "extended", 0 }, { "already", 0 }, { "attached", 0 }, { "failed", 0 } };
            int dimmed = 0;
            try
            {
                foreach (PlaceJob j in jobs)
                {
                    var made = new List<KeyValuePair<FabricationPart, FabricationPart>>();
                    foreach (PlaceSpec pl in j.Places)
                    {
                        FabricationPart host = pl.Host;
                        ButtonChoice pk = picker.Pick(host);
                        if (pk.Button == null)
                        {
                            res.Failed++;
                            continue;
                        }
                        Transaction t = StartTxn(doc, "Place hanger");
                        try
                        {
                            FabricationPart h = CreateHanger(doc, pk.Button, pk.Cond, host, pl.Conn, pl.Dist, log);
                            if (h == null)
                            {
                                Rollback(t);
                                res.Failed++;
                                continue;
                            }
                            ws.Apply(h, host, true);
                            if (Committed(t))
                                made.Add(new KeyValuePair<FabricationPart, FabricationPart>(h, host));
                            else
                                res.Failed++;
                        }
                        catch (Exception ex)
                        {
                            log.Add("place on " + Inv(EidValue(host.Id)) + ": " + ex.Message);
                            Rollback(t);
                            res.Failed++;
                        }
                    }
                    if (soffit != null)
                    {
                        foreach (var m in made)
                        {
                            FabricationPart h = m.Key;
                            Transaction t = StartTxn(doc, "Extend rods");
                            string outcome;
                            try
                            {
                                outcome = ExtendRods(doc, h, soffit, log);
                            }
                            catch (Exception ex)
                            {
                                log.Add("rods " + Inv(EidValue(h.Id)) + ": " + ex.Message);
                                outcome = "failed";
                            }
                            if (outcome == "failed" || outcome == "already")
                                Rollback(t);
                            else if (!Committed(t))
                                outcome = "failed";
                            rods[outcome] += 1;
                        }
                    }
                    if (made.Count > 0 && wantDims)
                    {
                        List<Element> hs = made.Select(m => (Element)m.Key).ToList();
                        PlaceJob jj = j;
                        if (DimensionInTargets(doc, targets, jj.PStart, jj.PEnd,
                                               v => ChainDimension(doc, v, jj.PStart, jj.PEnd, hs, jj.First, jj.Last, settings, dimType, log), log))
                            dimmed++;
                    }
                    created.AddRange(made);
                }
            }
            finally
            {
                if (soffit != null) soffit.Close();
                tg.Assimilate();
            }
            foreach (var c in created)   // read back after the group has closed
            {
                try
                {
                    if (c.Key.IsValidObject && HostOf(c.Key) == EidValue(c.Value.Id))
                        res.Done++;
                    else
                        res.Failed++;
                }
                catch (Exception)
                {
                    res.Failed++;
                }
            }
            if (res.Skipped != 0)
                res.Lines.Add(res.Skipped.ToString(CultureInfo.InvariantCulture) + " skipped where a hanger already was.");
            if (soffit != null)
            {
                if (!soffit.Ok())
                    res.Lines.Add("Rods: ray cast unavailable (" + soffit.Reason + "); used Revit attach to structure.");
                res.Lines.Add("Rods: " + rods["extended"].ToString(CultureInfo.InvariantCulture) + " to structure, "
                              + rods["attached"].ToString(CultureInfo.InvariantCulture) + " attached by Revit, "
                              + rods["failed"].ToString(CultureInfo.InvariantCulture) + " found no structure.");
            }
            if (wantDims)
            {
                res.Lines.Add(targets.Summary(dimmed, jobs.Count));
                OfferOpen(uidoc, settings, targets, dimmed, log);
            }
            res.Lines.AddRange(ws.Problems);
            return res;
        }
    }
}
