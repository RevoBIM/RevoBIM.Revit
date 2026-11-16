using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HcircRevit
    {
        // ================================================================== jobs
        public static JobResult JobPlace(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = FhaRevit.NewResult("Place circular " + HfamRevit.NounOf(settings) + " on service");
            FamConfig cfg;
            FamilySymbol symbol = Chosen(uidoc, settings, res, out cfg);
            if (symbol == null)
                return res;
            bool outside = FhaCore.AsBool(settings, "fam_ins_place");
            HfamRevit.LogContext(uidoc, settings, log, "Place " + Title(cfg) + " on service", symbol, cfg);
            HfamRevit.SoffitFinder finder;
            bool rod = RodOf(settings, "fam_rod_place", cfg, log, doc, out finder);
            HfamRevit.Locker locker = FhaCore.AsBool(settings, "fam_lock_place") ? new HfamRevit.Locker(doc, uidoc.ActiveView, log) : null;
            FhaRevit.Worksets ws = new FhaRevit.Worksets(doc, SGet(settings, "fam_workset", ""), log);
            HfamRevit.BasePick pickedBase = HfamRevit.FloorBasePick(uidoc, settings, res, log);
            HfamRevit.BaseSurface baseEl = pickedBase != null ? new HfamRevit.BaseSurface(doc, pickedBase.El, pickedBase.Link, log) : null;
            if (baseEl != null)
                log.Add("supports stand on " + baseEl.Label());
            var issues = new List<string>();
            try
            {
                while (true)
                {
                    HfamRevit.PickedPoint pp;
                    try
                    {
                        pp = HfamRevit.PickDuctPoint(uidoc, "Click on a pipe or round duct where the " + Title(cfg) + " goes (Esc to finish)",
                                                     HfamRevit.IsHostDuct);
                    }
                    catch (Exception)
                    {
                        break;   // Esc
                    }
                    Element svc = pp.Element;
                    V3? pn = pp.Point;
                    log.Add("click on " + Describe(svc) + " at " + (pn != null ? Fpt(pn) : "(no point - using the middle)"));
                    Section sec = RoundSection(svc, outside);
                    if (sec == null)
                    {
                        issues.Add(NotRoundText(Describe(svc), Noun(cfg)));
                        res.Skipped++;
                        continue;
                    }
                    V3 p = pn != null ? pn.Value : FhaCore.VScale(FhaCore.VAdd(sec.A, sec.B), 0.5);
                    V3 q = HfamCore.OnCentreline(sec.A, sec.B, p, HfamRevit.EndMargin);
                    sec.Keys = new List<long> { Eid(svc.Id) };
                    Transaction t = FhaRevit.StartTxn(doc, "Place circular support");
                    try
                    {
                        HfamRevit.PlaceOutcome po = PlaceCirc(doc, symbol, svc, sec, q, cfg, log, ws, baseEl, rod, finder);
                        List<string> problems = po.Problems;
                        HfamRevit.LockIf(locker, po.Inst, svc, sec, q, problems, log);
                        if (po.Inst == null || !FhaRevit.Committed(t))
                        {
                            FhaRevit.Rollback(t);
                            res.Failed++;
                            issues.AddRange(problems);
                            continue;
                        }
                        if (VerifyCirc(po.Inst, cfg, sec, problems))
                            res.Done++;
                        issues.AddRange(problems);
                    }
                    catch (Exception ex)
                    {
                        log.Add("place: " + ex.Message);
                        FhaRevit.Rollback(t);
                        res.Failed++;
                    }
                }
            }
            finally
            {
                Close(finder);
                if (baseEl != null)
                    baseEl.Close();
            }
            res.Lines.AddRange(SortedDistinct(issues));
            res.Lines.AddRange(ws.Problems);
            return res;
        }

        /// <summary>A support re-aligned this run, kept for the read-back (the Python (h, cfg, sec) tuples).</summary>
        private class DoneItem
        {
            public FamilyInstance Inst;
            public FamConfig Cfg;
            public Section Sec;
        }

        public static JobResult JobRealign(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = FhaRevit.NewResult("Re-align circular " + HfamRevit.NounOf(settings) + "s to service");
            FamConfig chosenCfg;
            FamilySymbol symbol = Chosen(uidoc, settings, res, out chosenCfg);
            if (symbol == null)
                return res;
            Dictionary<string, FamConfig> fams = HfamRevit.FamsOf(settings);
            string chosenFamily = ElName(symbol.Family);
            List<Element> picked = HfamRevit.SelectedServices(uidoc, true).Select(s => s.El).ToList();
            if (picked.Count == 0)
            {
                try
                {
                    IList<Reference> refs = uidoc.Selection.PickObjects(ObjectType.Element, new HfamRevit.HfamFilter(HfamRevit.IsHostDuct),
                                                                        "Pick the pipe or round duct, then Finish");
                    picked = refs.Select(r => doc.GetElement(r.ElementId)).ToList();
                }
                catch (Exception)
                {
                    picked = new List<Element>();
                }
            }
            if (picked.Count == 0)
            {
                res.Lines.Add("No service picked.");
                return res;
            }
            List<Element> supports;
            try
            {
                IList<Reference> refs = uidoc.Selection.PickObjects(ObjectType.Element, new HfamRevit.HfamFilter(HfamRevit.IsHangerFamily),
                                                                    "Pick the circular " + Noun(chosenCfg) + "s to re-align, then Finish");
                supports = refs.Select(r => doc.GetElement(r.ElementId)).ToList();
            }
            catch (Exception)
            {
                supports = new List<Element>();
            }
            if (supports.Count == 0)
            {
                res.Lines.Add("No supports picked.");
                return res;
            }
            HfamRevit.LogContext(uidoc, settings, log, "Re-align " + Title(chosenCfg) + "s to service", symbol, chosenCfg);
            HfamRevit.SoffitFinder finder;
            bool rod = RodOf(settings, "fam_rod_realign", chosenCfg, log, doc, out finder);
            log.Add("picked " + string.Join(", ", picked.Select(e => Describe(e))) + "; " + Inv(supports.Count) + " supports");
            var straights = new List<HfamRevit.ServiceSec>();
            var seen = new HashSet<long>();
            foreach (Element svc in picked)
            {
                foreach (HfamRevit.ServiceSec ss in HfamRevit.RunStraights(doc, svc))
                {
                    if (!seen.Contains(Eid(ss.El.Id)))
                    {
                        seen.Add(Eid(ss.El.Id));
                        straights.Add(ss);
                    }
                }
            }
            var byId = new Dictionary<long, HfamRevit.ServiceSec>();
            foreach (HfamRevit.ServiceSec s in straights) byId[Eid(s.El.Id)] = s;
            var segs = straights.Select(s => new KeySeg(Eid(s.El.Id), s.Sec.A, s.Sec.B)).ToList();
            bool outside = FhaCore.AsBool(settings, "fam_ins_realign");
            HfamRevit.Locker locker = FhaCore.AsBool(settings, "fam_lock_realign") ? new HfamRevit.Locker(doc, uidoc.ActiveView, log) : null;
            FhaRevit.Worksets ws = new FhaRevit.Worksets(doc, SGet(settings, "fam_workset", ""), log);
            FhaRevit.Checkout(doc, supports, log);
            HfamRevit.BasePick pickedBase = HfamRevit.FloorBasePick(uidoc, settings, res, log);
            TransactionGroup tg = new TransactionGroup(doc, "Hanger Automation - re-align circular supports");
            tg.Start();
            HfamRevit.BaseSurface baseEl = pickedBase != null ? new HfamRevit.BaseSurface(doc, pickedBase.El, pickedBase.Link, log) : null;
            var issues = new List<string>();
            var done = new List<DoneItem>();
            try
            {
                foreach (Element he in supports)
                {
                    FamilyInstance h = (FamilyInstance)he;
                    string fam = ElName(h.Symbol.Family);
                    FamConfig cfg;
                    FamConfig famCfg;
                    if (fam == chosenFamily)
                    {
                        cfg = chosenCfg.Clone();
                    }
                    else if (fams.TryGetValue(fam, out famCfg) && HcircCore.IsCirc(famCfg))
                    {
                        cfg = HfamCore.FamConfigFor(fams, fam);   // dict(fc.fam_config(fams, fam), mode=...)
                        cfg.Mode = chosenCfg.Get("mode", "hang");
                    }
                    else
                    {
                        issues.Add(Capitalize(Noun(chosenCfg)) + " " + Inv(Eid(h.Id)) + " (" + fam + ") is not a Circular System Based family - left alone.");
                        res.Skipped++;
                        continue;
                    }
                    V3? p = HfamRevit.InstancePoint(h);
                    long? key = p != null ? HfamCore.PickSegment(p.Value, segs, 300.0 / MM) : null;
                    Element segEl;
                    Section sec;
                    Section pickedSec = HfamRevit.Section(picked[0]);   // by_id.get(key, (picked[0], section(picked[0]))): the default is built either way
                    HfamRevit.ServiceSec found;
                    if (key != null && byId.TryGetValue(key.Value, out found)) { segEl = found.El; sec = found.Sec; }
                    else { segEl = picked[0]; sec = pickedSec; }
                    sec = HfamCore.ApplyInsulation(sec, outside);
                    if (!sec.Round)
                    {
                        issues.Add(NotRoundText(Describe(segEl), Noun(cfg)));
                        res.Skipped++;
                        continue;
                    }
                    if (key == null)
                        log.Add("support " + Inv(Eid(h.Id)) + ": not over any straight of the run - using the picked service");
                    sec.Keys = new List<long> { Eid(segEl.Id) };
                    Transaction t = FhaRevit.StartTxn(doc, "Re-align circular support");
                    try
                    {
                        List<string> problems = RealignCirc(doc, h, segEl, sec, cfg, log, ws, baseEl, rod, finder);
                        if (p != null)
                            HfamRevit.LockIf(locker, h, segEl, sec, HfamCore.OnLine(sec.A, sec.B, p.Value), problems, log);
                        if (FhaRevit.Committed(t))
                            done.Add(new DoneItem { Inst = h, Cfg = cfg, Sec = sec });
                        else
                            res.Failed++;
                        issues.AddRange(problems);
                    }
                    catch (Exception ex)
                    {
                        log.Add("realign " + Inv(Eid(h.Id)) + ": " + ex.Message);
                        FhaRevit.Rollback(t);
                        res.Failed++;
                    }
                }
            }
            finally
            {
                Close(finder);
                if (baseEl != null)
                    baseEl.Close();
                tg.Assimilate();
            }
            foreach (DoneItem d in done)
            {
                if (VerifyCirc(d.Inst, d.Cfg, d.Sec, issues))
                    res.Done++;
            }
            res.Lines.AddRange(SortedDistinct(issues));
            res.Lines.AddRange(ws.Problems);
            return res;
        }

        /// <summary>A place along a span: the straight it is on and the point on its centreline.</summary>
        private class PlacePt
        {
            public Element Host;
            public V3 Q;
        }

        /// <summary>Ring supports along a selected pipe / round duct run, by the same placement rules as the other
        /// supports (spans between bends, tees and set downs, start / end offsets, maximum spacing, clear of takeoffs,
        /// joints and existing supports). One ring per service - never shared.</summary>
        public static JobResult JobAuto(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = FhaRevit.NewResult("Auto place circular " + HfamRevit.NounOf(settings) + "s along run");
            FamConfig cfg;
            FamilySymbol symbol = Chosen(uidoc, settings, res, out cfg);
            if (symbol == null)
                return res;
            List<Element> seeds = uidoc.Selection.GetElementIds().Select(i => doc.GetElement(i)).ToList();
            seeds = seeds.Where(e => e != null && HfamRevit.IsRunMember(e)).ToList();
            if (seeds.Count == 0)
            {
                try
                {
                    IList<Reference> refs = uidoc.Selection.PickObjects(ObjectType.Element, new HfamRevit.HfamFilter(HfamRevit.IsRunMember),
                                                                        "Select the run(s) - pipes or round ducts and their fittings - then Finish");
                    seeds = refs.Select(r => doc.GetElement(r.ElementId)).ToList();
                }
                catch (Exception)
                {
                    seeds = new List<Element>();
                }
            }
            if (seeds.Count == 0)
            {
                res.Lines.Add("No pipes selected.");
                return res;
            }
            bool accessories = FhaCore.AsBool(settings, "fam_accessory");
            HfamRevit.LogContext(uidoc, settings, log, "Auto place " + Title(cfg) + "s along run", symbol, cfg);
            log.Add("selected: " + string.Join(", ", seeds.Take(60).Select(e => Describe(e))) + (seeds.Count > 60 ? " ..." : ""));
            HfamRevit.FamGraph graph = HfamRevit.BuildGraph(seeds, accessories, log);
            Dictionary<long, PartRec> parts = graph.Parts;
            Dictionary<long, Element> elems = graph.Elems;
            HashSet<long> selected = graph.Selected;
            List<Span> spans = FhaCore.BuildSpans(parts)
                .Where(s => s.Chain.Any(it => it.Kind == "straight" && selected.Contains(it.Id))).ToList();
            if (spans.Count == 0)
            {
                res.Lines.Add("No level straight runs in the selection.");
                return res;
            }
            double flange = FhaCore.AsFloat(settings, "fam_flange_clear", 150.0) / MM;
            double userMax = FhaCore.AsFloat(settings, "fam_spacing", 3000.0);
            bool useDw = FhaCore.AsBool(settings, "fam_dw144");
            double takeoffClear = FhaCore.AsFloat(settings, "fam_takeoff_clear", 400.0) / MM;
            List<V3> existing = FhaCore.AsBool(settings, "fam_skip_existing") ? HfamRevit.ExistingPoints(doc, symbol) : new List<V3>();
            double existClear = FhaCore.AsFloat(settings, "existing_clear", 300.0) / MM;
            List<V3> tapPts = FhaRevit.AllTapPoints(doc);
            bool outside = FhaCore.AsBool(settings, "fam_ins_auto");
            HfamRevit.Locker locker = FhaCore.AsBool(settings, "fam_lock_auto") ? new HfamRevit.Locker(doc, uidoc.ActiveView, log) : null;
            DimTargets targets = FhaRevit.DimTargets(uidoc, settings, "fam_dims", res, log);   // asks in a 3D view
            bool wantDims = targets != null;
            DimensionType dimType = FhaRevit.FindDimType(doc, SGet(settings, "fam_dim_type", ""));
            HfamRevit.BasePick pickedBase = HfamRevit.FloorBasePick(uidoc, settings, res, log);
            TransactionGroup tg = new TransactionGroup(doc, "Hanger Automation - circular supports along run");
            tg.Start();
            HfamRevit.BaseSurface baseEl = pickedBase != null ? new HfamRevit.BaseSurface(doc, pickedBase.El, pickedBase.Link, log) : null;
            if (baseEl != null)
                log.Add("supports stand on " + baseEl.Label());
            FhaRevit.Worksets ws = new FhaRevit.Worksets(doc, SGet(settings, "fam_workset", ""), log);
            HfamRevit.SoffitFinder finder;
            bool rod = RodOf(settings, "fam_rod_auto", cfg, log, doc, out finder);
            var issues = new List<string>();
            var madeAll = new List<KeyValuePair<FamilyInstance, Section>>();
            int dimmed = 0, nJobs = 0;
            var notRound = new HashSet<string>(StringComparer.Ordinal);
            try
            {
                foreach (Span span in spans)
                {
                    List<ChainItem> chain = span.Chain;
                    List<Element> straightEls = chain.Where(it => it.Kind == "straight").Select(it => elems[it.Id]).ToList();
                    List<Section> secs = straightEls.Select(e => HfamRevit.Section(e)).ToList();
                    if (!secs.All(sc => sc.Round))
                    {
                        for (int i = 0; i < straightEls.Count; i++)
                        {
                            if (!secs[i].Round)
                                notRound.Add(Describe(straightEls[i]));
                        }
                        log.Add("span [" + string.Join(",", chain.Select(it => Inv(it.Id))) + "] skipped - not all pipe / round duct");
                        continue;
                    }
                    var points = new Dictionary<long, KeyValuePair<V3, V3>>();
                    foreach (ChainItem it in chain)
                    {
                        FhaPart rec = (FhaPart)parts[it.Id];
                        if (rec.Pts.Count >= 2)
                            points[it.Id] = new KeyValuePair<V3, V3>(rec.Pts[it.Entry], rec.Pts[it.Exit]);
                    }
                    List<SpanSeg> segs = FhaCore.SpanSegments(chain, points);
                    if (segs.Count == 0)
                        continue;
                    double width = secs.Max(sc => sc.Width);
                    bool ductRun = straightEls.All(e => HfamRevit.IsDuctwork(e));
                    double spacing = HfamCore.SpanSpacingMm(userMax, useDw && ductRun, width * MM, width * MM, true);
                    PlanConfig pcfg = HfamCore.AutoConfig(settings, spacing);
                    double length = FhaCore.SpanLength(span);
                    List<double> planned = FhaCore.PlanStations(length, span.StartEnd.Type, span.EndEnd.Type, pcfg);
                    var blocks = new List<V3>();
                    foreach (ChainItem it in chain)
                        blocks.AddRange(((FhaPart)parts[it.Id]).Sides);
                    blocks.AddRange(tapPts);
                    var blockSt = new List<double>();
                    foreach (V3 b in blocks)
                    {
                        double? x = FhaCore.StationOfPoint(segs, b, FhaRevit.TapReach);
                        if (x != null) blockSt.Add(x.Value);
                    }
                    List<double> st = FhaCore.AvoidBlocks(planned, blockSt, takeoffClear, length, pcfg.Edge / MM);
                    st = FhaCore.Dedupe(st, pcfg.MinGap / MM / 2.0);
                    if (existing.Count > 0)
                    {
                        double reach = width / 2.0 + 150.0 / MM;
                        var exSt = new List<double>();
                        foreach (V3 e in existing)
                        {
                            double? x = FhaCore.StationOnRun(segs, e, reach, maxDzFt: 1000.0);
                            if (x != null) exSt.Add(x.Value);
                        }
                        List<double> before = new List<double>(st);
                        st = FhaCore.DropNear(st, exSt, existClear);
                        if (st.Count < before.Count)
                            log.Add("   dropped " + ReprList(before.Select(x => Fmm(x))) + " -> " + ReprList(st.Select(x => Fmm(x))) + " (within "
                                    + Fmm(existClear) + " mm of supports already in the model at " + ReprList(exSt.Select(x => Fmm(x))) + ")");
                        res.Skipped += before.Count - st.Count;
                    }
                    var places = new List<PlacePt>();
                    foreach (double x in st)
                    {
                        Located loc = FhaCore.Locate(chain, x, flange);
                        if (loc == null) continue;
                        FhaPart rec = (FhaPart)parts[loc.Id];
                        V3 a = rec.Pts[loc.Entry], b = rec.Pts[1 - loc.Entry];
                        V3 d = FhaCore.VNorm(FhaCore.VSub(b, a));
                        places.Add(new PlacePt { Host = elems[loc.Id], Q = FhaCore.VAdd(a, FhaCore.VScale(d, loc.Dist)) });
                    }
                    log.Add("span " + Fmm(length) + " mm [" + string.Join(",", chain.Select(it => Inv(it.Id))) + "] " + HfamRevit.ServiceKind(straightEls[0]) + " "
                            + span.StartEnd.Type + "->" + span.EndEnd.Type + " | dia " + Fmm(width) + " | spacing " + Fm(spacing, 0)
                            + " | planned " + ReprList(planned.Select(x => Fmm(x))) + " | placing at " + ReprList(places.Select(pl => Fpt(pl.Q))));
                    if (places.Count == 0)
                        continue;
                    nJobs++;
                    var made = new List<KeyValuePair<FamilyInstance, Section>>();
                    foreach (PlacePt pl in places)
                    {
                        Element host = pl.Host;
                        V3 q = pl.Q;
                        Section sec = HfamRevit.Fitted(host, outside);
                        sec.Keys = new List<long> { Eid(host.Id) };
                        Transaction t = FhaRevit.StartTxn(doc, "Place circular support");
                        try
                        {
                            HfamRevit.PlaceOutcome po = PlaceCirc(doc, symbol, host, sec, q, cfg, log, ws, baseEl, rod, finder);
                            HfamRevit.LockIf(locker, po.Inst, host, sec, q, po.Problems, log);
                            issues.AddRange(po.Problems);
                            if (po.Inst != null && FhaRevit.Committed(t))
                            {
                                made.Add(new KeyValuePair<FamilyInstance, Section>(po.Inst, sec));
                            }
                            else
                            {
                                FhaRevit.Rollback(t);
                                res.Failed++;
                            }
                        }
                        catch (Exception ex)
                        {
                            log.Add("auto place: " + ex.Message);
                            FhaRevit.Rollback(t);
                            res.Failed++;
                        }
                    }
                    if (made.Count > 0 && wantDims)
                    {
                        long firstId = chain[0].Id, lastId = chain[chain.Count - 1].Id;
                        V3 pStart = points.ContainsKey(firstId) ? points[firstId].Key : segs[0].A;
                        V3 pEnd = points.ContainsKey(lastId) ? points[lastId].Value : segs[segs.Count - 1].B;
                        List<Element> hs = made.Select(m => (Element)m.Key).ToList();
                        Element firstEl = straightEls[0], lastEl = straightEls[straightEls.Count - 1];
                        string axis = HcircCore.WidthAxis(cfg.Get("circ_axis", "X"));
                        if (FhaRevit.DimensionInTargets(doc, targets, pStart, pEnd,
                                v => HfamRevit.ChainDimension(doc, v, pStart, pEnd, hs, firstEl, lastEl, axis, settings, log, dimType), log))
                            dimmed++;
                    }
                    madeAll.AddRange(made);
                }
            }
            finally
            {
                Close(finder);
                if (baseEl != null)
                    baseEl.Close();
                tg.Assimilate();
            }
            if (madeAll.Count == 0 && res.Failed == 0 && notRound.Count == 0)
                res.Lines.Add("Nothing to place - every span already has its " + Noun(cfg) + "s or is too short.");
            foreach (var m in madeAll)
            {
                if (VerifyCirc(m.Key, cfg, m.Value, issues))
                    res.Done++;
                else
                    res.Failed++;
            }
            foreach (string name in SortedDistinct(notRound))
                issues.Add(NotRoundText(name, Noun(cfg)));
            if (res.Skipped != 0)
                res.Lines.Add(Inv(res.Skipped) + " skipped where a " + Noun(cfg) + " already was (untick \"Skip existing " + Noun(cfg) + "s\" to place anyway).");
            if (wantDims)
            {
                res.Lines.Add(targets.Summary(dimmed, nJobs));
                FhaRevit.OfferOpen(uidoc, settings, targets, dimmed, log);
            }
            res.Lines.AddRange(SortedDistinct(issues));
            res.Lines.AddRange(ws.Problems);
            return res;
        }

        /// <summary>The dimension placer, with every circular family read by the way its service runs (the placer reads
        /// hangers by their width axis). The settings it hands HfamRevit.JobDims carry copies of the chosen family and the
        /// per-family settings in which a circular family's Axis is the width axis of its circ_axis; the originals are
        /// not touched, and HfamRevit's "last choice" fallback is restored afterwards.</summary>
        public static JobResult JobDims(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            FhaSettings st = new FhaSettings(settings);
            var fams = new Dictionary<string, FamConfig>(StringComparer.Ordinal);
            foreach (KeyValuePair<string, FamConfig> kv in HfamRevit.FamsOf(settings))
            {
                FamConfig cfg = kv.Value;
                if (HcircCore.IsCirc(cfg))
                {
                    cfg = cfg.Clone();
                    cfg.Axis = HcircCore.WidthAxis(cfg.Get("circ_axis", "X"));
                }
                fams[kv.Key] = cfg;
            }
            HfamRevit.HfamChoice src = HfamRevit.ChoiceOf(settings);
            HfamRevit.HfamChoice chosen = src == null ? null : new HfamRevit.HfamChoice { Id = src.Id, Family = src.Family, Cfg = src.Cfg };
            if (chosen != null && chosen.Cfg != null && HcircCore.IsCirc(chosen.Cfg))
            {
                FamConfig ccfg = chosen.Cfg.Clone();
                ccfg.Axis = HcircCore.WidthAxis(chosen.Cfg.Get("circ_axis", "X"));
                chosen.Cfg = ccfg;
            }
            HfamRevit.HfamChoice lastChoice = HfamRevit.LastChoice;
            Dictionary<string, FamConfig> lastFams = HfamRevit.LastFams;
            HfamRevit.SetFamilies(st, chosen, fams);
            try
            {
                return HfamRevit.JobDims(uidoc, st, log);
            }
            finally
            {
                HfamRevit.LastChoice = lastChoice;
                HfamRevit.LastFams = lastFams;
            }
        }
    }
}
