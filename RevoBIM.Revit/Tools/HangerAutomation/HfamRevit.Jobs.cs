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
        // ============================================================= bundles
        /// <summary>fitted section of an element: its section with the insulation rule applied.</summary>
        public static Section Fitted(Element el, bool outside)
        {
            return HfamCore.ApplyInsulation(SectionCached(el), outside);
        }

        /// <summary>The (section, point) pair bundle_for returns.</summary>
        public class BundleResult
        {
            public Section Sec;
            public V3 Point;
        }

        /// <summary>Python str() of a float in a log line: 2.0 -> '2.0'.</summary>
        private static string PyFloat(double v)
        {
            if (v == Math.Floor(v) && Math.Abs(v) < 1e15) return v.ToString("0.0", CultureInfo.InvariantCulture);
            return v.ToString("R", CultureInfo.InvariantCulture);
        }

        /// <summary>One hanger round the lead service and any of the `others` that sit with it, by the
        /// Hanger rules (parallel, bottoms within the height limit, clear gaps under the gap limit).
        /// `others`: [(element, fitted section)]. Every decision is logged.</summary>
        public static BundleResult BundleFor(Element lead, Section leadSec, V3 point, IEnumerable<ServiceSec> others, bool outside,
                                             FhaDebugLog log, GroupRules rules = null)
        {
            GroupRules r = rules ?? GroupRules.Default();
            double zTol = r.ZTolFt, gapTol = r.GapTolFt, ang = r.AngleDeg;
            string centre = r.Centre;
            var members = new List<BundleMember> { new BundleMember(Eid(lead.Id), leadSec.A, leadSec.B, leadSec.Width, leadSec.Depth) };
            foreach (ServiceSec o in others)
            {
                if (Eid(o.El.Id) != Eid(lead.Id))
                    members.Add(new BundleMember(Eid(o.El.Id), o.Sec.A, o.Sec.B, o.Sec.Width, o.Sec.Depth));
            }
            HangerBundle b = HfamCore.Bundle(point, members, zTol, gapTol, ang, centre);
            if (members.Count > 1)
            {
                if (b.Keys.Count > 1)
                    log.Add("   shared hanger: " + ReprIds(b.Keys) + " | " + centre + " centre | reaches " + Fmm(b.ExtNeg) + " / " + Fmm(b.ExtPos)
                            + " mm either side | " + Fmm(b.Width) + " mm wide at the lowest invert " + Fmm(b.Bottom));
                else
                    log.Add("   no shared hanger here (rules: height " + Fmm(zTol) + " mm, gap " + Fmm(gapTol) + " mm, " + PyFloat(ang) + " deg)");
                foreach (string n in b.Notes)
                    log.Add("      " + n);
            }
            return new BundleResult { Sec = HfamCore.BundleSection(b, leadSec), Point = HfamCore.BundlePoint(b, leadSec, point) };
        }

        /// <summary>The selected host services with their fitted sections.</summary>
        public static List<ServiceSec> SelectedServices(UIDocument uidoc, bool outside)
        {
            var o = new List<ServiceSec>();
            foreach (ElementId i in uidoc.Selection.GetElementIds())
            {
                Element e = uidoc.Document.GetElement(i);
                if (e != null && IsHostDuct(e))
                    o.Add(new ServiceSec(e, Fitted(e, outside)));
            }
            return o;
        }

        /// <summary>Section of a unit (equipment / duct accessory) for a hanger under it:
        /// its bottom face, its width across, the way it runs (in-line connectors,
        /// else its longer side). Null when its size cannot be read.</summary>
        public static Section UnitSectionOf(Element el, FhaDebugLog log)
        {
            var pts = new List<V3>();
            List<FaceZ> faces = ElementFaces(el, null, pts);
            var downs = faces.Where(fz => fz.Nz < -0.99).Select(fz => fz.Z).ToList();
            double? bottom = downs.Count > 0 ? (double?)downs.Min() : null;
            if (pts.Count == 0)
            {
                try
                {
                    BoundingBoxXYZ bb = el.get_BoundingBox(null);
                    pts = new List<V3>();
                    foreach (double x in new[] { bb.Min.X, bb.Max.X })
                        foreach (double y in new[] { bb.Min.Y, bb.Max.Y })
                            foreach (double z in new[] { bb.Min.Z, bb.Max.Z })
                                pts.Add(new V3(x, y, z));
                    log.Add("   no solid geometry read - sized from its bounding box");
                }
                catch (Exception) { return null; }
            }
            var conns = new List<InlineConn>();
            foreach (Connector c in GConns(el))
            {
                try
                {
                    XYZ bz = c.CoordinateSystem.BasisZ;
                    conns.Add(new InlineConn(Pt(c.Origin), new V3(bz.X, bz.Y, bz.Z)));
                }
                catch (Exception) { }
            }
            V3? hint = HfamCore.InlineDirection(conns);
            V3 hand, facing;
            try
            {
                FamilyInstance fi = (FamilyInstance)el;
                XYZ h = fi.HandOrientation, f = fi.FacingOrientation;
                hand = new V3(h.X, h.Y, 0.0);
                facing = new V3(f.X, f.Y, 0.0);
            }
            catch (Exception)
            {
                hand = new V3(1.0, 0.0, 0.0);
                facing = new V3(0.0, 1.0, 0.0);
            }
            Section sec = HfamCore.UnitSection(hand, facing, pts, bottom, hint);
            if (bottom == null)
                log.Add("   no flat bottom face - using the lowest point of the unit");
            return sec;
        }

        // ================================================================== jobs
        /// <summary>The hanger type the window has chosen (null when none, with a line added to res), and its
        /// settings (with Mode = settings['_mode'], default "hang"). Python _chosen returned (symbol, cfg).</summary>
        public static FamilySymbol Chosen(UIDocument uidoc, FhaSettings settings, JobResult res, out FamConfig cfg)
        {
            HfamChoice fam = ChoiceOf(settings);
            ElementId sid = fam != null ? fam.Id : null;
            FamilySymbol symbol = sid != null ? uidoc.Document.GetElement(sid) as FamilySymbol : null;
            if (symbol == null)
            {
                res.Lines.Add("Choose a hanger family and type first.");
                cfg = null;
                return null;
            }
            FamConfig c = (fam.Cfg ?? new FamConfig()).Clone();
            c.Mode = SGet(settings, "_mode", "hang");
            cfg = c;
            return symbol;
        }

        /// <summary>Read back after commit: the width parameters must hold half the duct.</summary>
        public static bool Verify(Element inst, FamConfig cfg, Section sec, JobResult res, List<string> problems, FhaDebugLog log)
        {
            try
            {
                if (!inst.IsValidObject) return false;
            }
            catch (Exception) { return false; }
            double half = HfamCore.HalfWidth(sec.Width, FhaCore.ParseMm(cfg.Get("clearance", "0"), 0.0));
            foreach (string key in new[] { "left", "right" })
            {
                double want = (key == "left" ? sec.SetLeft : sec.SetRight) ?? half;
                double? v = GetLength(inst, cfg[key]);
                if (v != null && Math.Abs(v.Value - want) > Tol)
                    problems.Add(cfg[key] + " reads " + Fm(v.Value * MM, 0) + " mm, not " + Fm(want * MM, 0) + " mm");
            }
            return true;
        }

        public static JobResult JobPlace(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = FhaRevit.NewResult("Place " + NounOf(settings) + " on service");
            FamConfig cfg;
            FamilySymbol symbol = Chosen(uidoc, settings, res, out cfg);
            if (symbol == null)
                return res;
            bool rod = FhaCore.AsBool(settings, "fam_rod_place") && !IsFloor(settings);
            bool outside = FhaCore.AsBool(settings, "fam_ins_place");
            LogContext(uidoc, settings, log, "Place " + NounOf(settings) + " on service", symbol, cfg);
            // Services selected before pressing the button are hung TOGETHER: one hanger
            // round every one of them that runs parallel alongside the click, however far
            // apart or uneven in height (you chose them) - at the lowest invert.
            GroupRules rules = HfamCore.WrapRules(HfamCore.GroupRulesFrom(settings));
            Locker locker = FhaCore.AsBool(settings, "fam_lock_place") ? new Locker(doc, uidoc.ActiveView, log) : null;
            List<ServiceSec> group = SelectedServices(uidoc, outside);
            if (group.Count > 0)
                log.Add("pre-selected services - one " + NounOf(settings) + " goes round all of them at each click: "
                        + string.Join(", ", group.Select(g => Describe(g.El))));
            FhaRevit.Worksets ws = new FhaRevit.Worksets(doc, SGet(settings, "fam_workset", ""), log);
            BasePick pickedBase = FloorBasePick(uidoc, settings, res, log);
            BaseSurface baseEl = pickedBase != null ? new BaseSurface(doc, pickedBase.El, pickedBase.Link, log) : null;
            if (baseEl != null)
                log.Add("supports stand on " + baseEl.Label());
            SoffitFinder finder = new SoffitFinder(doc, settings, log, rod && cfg.Get("soffit", "") == "structure");
            var issues = new List<string>();
            long famId = Eid(symbol.Family.Id);

            Func<Element, bool> pickTest = e =>
            {
                if (IsHostDuct(e)) return true;
                if (!IsUnit(e)) return false;
                try { return Eid(((FamilyInstance)e).Symbol.Family.Id) != famId; }   // not a hanger of the chosen family
                catch (Exception) { return true; }
            };
            try
            {
                while (true)
                {
                    PickedPoint pp;
                    try
                    {
                        string prompt = group.Count > 0
                            ? "Click on one of the selected services where the " + NounOf(settings) + " goes - it goes round all of them (Esc to finish)"
                            : "Click on a duct, pipe, cable tray, conduit, mechanical equipment or duct accessory where the " + NounOf(settings) + " goes (Esc to finish)";
                        pp = PickDuctPoint(uidoc, prompt, pickTest);
                    }
                    catch (Exception)
                    {
                        break;   // Esc
                    }
                    Element duct = pp.Element;
                    V3? p = pp.Point;
                    log.Add("click on " + Describe(duct) + " at " + (p != null ? Fpt(p) : "(no point - using the middle)"));
                    bool unit = !IsHostDuct(duct);
                    Section sec;
                    if (unit)
                    {
                        sec = UnitSectionOf(duct, log);
                        if (sec == null)
                        {
                            issues.Add("Could not read the size of " + Describe(duct) + ".");
                            continue;
                        }
                    }
                    else
                        sec = HfamCore.ApplyInsulation(Section(duct), outside);
                    V3 pt0 = p ?? FhaCore.VScale(FhaCore.VAdd(sec.A, sec.B), 0.5);
                    V3 q = HfamCore.OnCentreline(sec.A, sec.B, pt0, EndMargin);
                    sec.Keys = new List<long> { Eid(duct.Id) };
                    if (group.Count > 0 && !unit)
                    {
                        BundleResult br = BundleFor(duct, sec, q, group, outside, log, rules);
                        sec = br.Sec;
                        q = br.Point;
                        List<Element> left = group.Where(g => !sec.Keys.Contains(Eid(g.El.Id))).Select(g => g.El).ToList();
                        if (left.Count > 0)
                            issues.Add("Left out of the combined " + NounOf(settings) + ": " + string.Join(", ", left.Select(e => Describe(e)))
                                       + " - not parallel to the clicked service, or not running alongside it where you clicked.");
                    }
                    Transaction t = FhaRevit.StartTxn(doc, "Place hanger on duct");
                    try
                    {
                        PlaceOutcome po = PlaceOne(doc, symbol, duct, sec, q, cfg, rod, finder, log, ws, baseEl);
                        List<string> problems = po.Problems;
                        LockIf(locker, po.Inst, duct, sec, q, problems, log);
                        bool committed;
                        using (HaTiming.Time("commit"))
                            committed = po.Inst != null && FhaRevit.Committed(t);
                        if (!committed)
                        {
                            FhaRevit.Rollback(t);
                            res.Failed++;
                            issues.AddRange(problems);
                            continue;
                        }
                        using (HaTiming.Time("verify"))
                        {
                            if (Verify(po.Inst, cfg, sec, res, problems, log))
                                res.Done++;
                        }
                        issues.AddRange(problems);
                    }
                    catch (Exception ex)
                    {
                        log.Add("place: " + ex.Message);
                        FhaRevit.Rollback(t);
                        res.Failed++;
                    }
                    finally
                    {
                        HaTiming.Flush(log);
                    }
                }
            }
            finally
            {
                finder.Close();
                if (baseEl != null) baseEl.Close();
                HaTiming.EndJob(log, "Pick and place");
            }
            res.Lines.AddRange(SortedDistinct(issues));
            res.Lines.AddRange(ws.Problems);
            return res;
        }

        /// <summary>sorted(set(items)) of strings, by code point.</summary>
        private static List<string> SortedDistinct(IEnumerable<string> items)
        {
            var l = items.Distinct(StringComparer.Ordinal).ToList();
            l.Sort(StringComparer.Ordinal);
            return l;
        }

        /// <summary>A hanger placed or re-aligned this run, kept for the read-back (the Python (hanger, cfg, sec) tuples).</summary>
        private class DoneItem
        {
            public FamilyInstance Inst;
            public FamConfig Cfg;
            public Section Sec;
        }

        public static JobResult JobRealign(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = FhaRevit.NewResult("Re-align " + NounOf(settings) + "s to service");
            FamConfig chosenCfg;
            FamilySymbol symbol = Chosen(uidoc, settings, res, out chosenCfg);
            Dictionary<string, FamConfig> fams = FamsOf(settings);
            List<Element> picked = SelectedServices(uidoc, true).Select(s => s.El).ToList();
            if (picked.Count == 0)
            {
                try
                {
                    IList<Reference> refs = FhaFinish.PickObjects(uidoc, new HfamFilter(IsHostDuct),
                                                                  "Pick the duct, pipe, cable tray or conduit (several to hang together), then Finish",
                                                                  "Select the services", FhaFinish.Detail("Pick the duct, pipe, cable tray or conduit the hangers are to follow (several to hang together)"));
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
            Element duct = picked[0];
            List<Element> hangers;
            try
            {
                IList<Reference> refs = FhaFinish.PickObjects(uidoc, new HfamFilter(IsHangerFamily),
                                                              "Pick the hangers to re-align, then Finish",
                                                              "Select the hangers", FhaFinish.Detail("Pick the hangers to re-align to the service"));
                hangers = refs.Select(r => doc.GetElement(r.ElementId)).ToList();
            }
            catch (Exception)
            {
                hangers = new List<Element>();
            }
            if (hangers.Count == 0)
            {
                res.Lines.Add("No hangers picked.");
                return res;
            }
            LogContext(uidoc, settings, log, "Re-align " + NounOf(settings) + "s to service", symbol, chosenCfg);
            log.Add("picked " + string.Join(", ", picked.Select(e => Describe(e))) + "; " + Inv(hangers.Count) + " hangers");
            var straights = new List<ServiceSec>();
            var seen = new HashSet<long>();
            foreach (Element svc in picked)
            {
                foreach (ServiceSec ss in RunStraights(doc, svc))
                {
                    if (!seen.Contains(Eid(ss.El.Id)))
                    {
                        seen.Add(Eid(ss.El.Id));
                        straights.Add(ss);
                    }
                }
            }
            log.Add("run: " + Inv(straights.Count) + " straights - " + string.Join(", ",
                    straights.Select(s => Inv(Eid(s.El.Id)) + " " + Fmm(s.Sec.Width) + "x" + Fmm(s.Sec.Depth))));
            var byId = new Dictionary<long, ServiceSec>();
            foreach (ServiceSec s in straights) byId[Eid(s.El.Id)] = s;
            var segs = straights.Select(s => new KeySeg(Eid(s.El.Id), s.Sec.A, s.Sec.B)).ToList();
            bool rod = FhaCore.AsBool(settings, "fam_rod_realign") && !IsFloor(settings);
            bool outside = FhaCore.AsBool(settings, "fam_ins_realign");
            GroupRules rules = HfamCore.GroupRulesFrom(settings);
            Locker locker = FhaCore.AsBool(settings, "fam_lock_realign") ? new Locker(doc, uidoc.ActiveView, log) : null;
            FhaRevit.Worksets ws = new FhaRevit.Worksets(doc, SGet(settings, "fam_workset", ""), log);
            FhaRevit.Checkout(doc, hangers, log);
            BasePick pickedBase = FloorBasePick(uidoc, settings, res, log);
            TransactionGroup tg = new TransactionGroup(doc, "Hanger Automation - re-align hangers");
            tg.Start();
            BaseSurface baseEl = pickedBase != null ? new BaseSurface(doc, pickedBase.El, pickedBase.Link, log) : null;
            SoffitFinder finder = null;
            var issues = new List<string>();
            var done = new List<DoneItem>();
            try
            {
                var cfgs = new List<FamConfig>();
                foreach (Element he in hangers)
                {
                    FamilyInstance h = (FamilyInstance)he;
                    string fam = ElName(h.Symbol.Family);
                    FamConfig cfg = (fams.ContainsKey(fam) ? HfamCore.FamConfigFor(fams, fam) : (chosenCfg ?? HfamCore.FamConfigFor(fams, fam))).Clone();
                    cfg.Mode = SGet(settings, "_mode", "hang");
                    cfgs.Add(cfg);
                }
                finder = new SoffitFinder(doc, settings, log, rod && cfgs.Any(c => c.Get("soffit", "") == "structure"));
                // per-job work done once (it did not change from hanger to hanger): the picked service's section and,
                // with several services picked, every straight with the insulation rule applied
                Section ductSec0 = Section(duct);
                List<ServiceSec> othersAll = null;
                if (picked.Count > 1)
                    othersAll = straights.Select(s => new ServiceSec(s.El, HfamCore.ApplyInsulation(s.Sec, outside))).ToList();
                for (int hi = 0; hi < hangers.Count; hi++)
                {
                    FamilyInstance h = (FamilyInstance)hangers[hi];
                    FamConfig cfg = cfgs[hi];
                    V3? p = InstancePoint(h);
                    long? key = p != null ? HfamCore.PickSegment(p.Value, segs, 300.0 / MM) : null;
                    Element segEl;
                    Section sec;
                    Section ductSec = ductSec0;   // by_id.get(key, (duct, section(duct))): read once above
                    ServiceSec found;
                    if (key != null && byId.TryGetValue(key.Value, out found)) { segEl = found.El; sec = found.Sec; }
                    else { segEl = duct; sec = ductSec; }
                    sec = HfamCore.ApplyInsulation(sec, outside);
                    if (p != null && picked.Count > 1)
                    {
                        V3 q0 = HfamCore.OnLine(sec.A, sec.B, p.Value);
                        sec = BundleFor(segEl, sec, q0, othersAll, outside, log, rules).Sec;
                    }
                    if (key == null)
                        log.Add("hanger " + Inv(Eid(h.Id)) + ": not over any straight of the run - using the picked duct");
                    Transaction t = FhaRevit.StartTxn(doc, "Re-align hanger");
                    try
                    {
                        List<string> problems = RealignOne(doc, h, segEl, sec, cfg, rod, finder, log, ws, baseEl);
                        if (p != null)
                            LockIf(locker, h, segEl, sec, HfamCore.OnLine(sec.A, sec.B, p.Value), problems, log);
                        bool committed;
                        using (HaTiming.Time("commit"))
                            committed = FhaRevit.Committed(t);
                        if (committed)
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
                    finally
                    {
                        HaTiming.Flush(log);
                    }
                }
            }
            finally
            {
                if (finder != null) finder.Close();
                if (baseEl != null) baseEl.Close();
                tg.Assimilate();
                HaTiming.EndJob(log, "Re-align");
            }
            foreach (DoneItem d in done)
            {
                if (Verify(d.Inst, d.Cfg, d.Sec, res, issues, log))
                    res.Done++;
            }
            res.Lines.AddRange(SortedDistinct(issues));
            res.Lines.AddRange(ws.Problems);
            return res;
        }

        /// <summary>Locations of hangers already in the model: the chosen family and fab hangers.</summary>
        public static List<V3> ExistingPoints(Document doc, FamilySymbol symbol)
        {
            var o = new List<V3>();
            long fid = Eid(symbol.Family.Id);
            FilteredElementCollector col = new FilteredElementCollector(doc).OfClass(typeof(FamilyInstance));
            try { col = col.OfCategoryId(symbol.Category.Id); }
            catch (Exception) { }
            foreach (Element e in col)
            {
                try
                {
                    FamilyInstance inst = (FamilyInstance)e;
                    if (Eid(inst.Symbol.Family.Id) == fid)
                    {
                        V3? p = InstancePoint(inst);
                        if (p != null) o.Add(p.Value);
                    }
                }
                catch (Exception) { }
            }
            try
            {
                foreach (Element h in new FilteredElementCollector(doc).OfCategory(FhaRevit.Bic("OST_FabricationHangers")).WhereElementIsNotElementType())
                {
                    V3? p = FhaRevit.HangerPoint(h);
                    if (p != null) o.Add(p.Value);
                }
            }
            catch (Exception) { }
            return o;
        }

        /// <summary>A shared hanger placed this run: its centre and the service ids it carries.</summary>
        private class Covered
        {
            public V3 Centre;
            public List<long> Keys;
        }

        /// <summary>A place along a span: the straight it is on and the point on its centreline.</summary>
        private class PlacePt
        {
            public Element Host;
            public V3 Q;
        }

        /// <summary>Hangers along a selected duct run.
        ///
        /// Spans of horizontal straights run between bends, tees, takeoffs, set downs
        /// and (ticked) in-line accessories. Per span: the first hanger at the start
        /// offset, then at most the span's spacing apart (your maximum, capped by
        /// DW/144 for the duct size), a hanger at the end offset before a bend, set
        /// down or accessory with the spacing shrunk to fit, nothing on takeoff stubs,
        /// hangers moved clear of taps, kept off joints and flanges by the flange
        /// clearance, and skipped where a hanger already is.</summary>
        public static JobResult JobAuto(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = FhaRevit.NewResult("Auto place " + NounOf(settings) + "s along run");
            FamConfig cfg;
            FamilySymbol symbol = Chosen(uidoc, settings, res, out cfg);
            if (symbol == null)
                return res;
            List<Element> seeds = uidoc.Selection.GetElementIds().Select(i => doc.GetElement(i)).ToList();
            seeds = seeds.Where(e => e != null && IsRunMember(e)).ToList();
            if (seeds.Count == 0)
            {
                try
                {
                    IList<Reference> refs = FhaFinish.PickObjects(uidoc, new HfamFilter(IsRunMember),
                                                                  "Select the run(s) - ducts, pipes, cable trays or conduits and their fittings - then Finish",
                                                                  "Select the run", FhaFinish.Detail("Pick the run(s) to hang - ducts, pipes, cable trays or conduits and their fittings"));
                    seeds = refs.Select(r => doc.GetElement(r.ElementId)).ToList();
                }
                catch (Exception)
                {
                    seeds = new List<Element>();
                }
            }
            if (seeds.Count == 0)
            {
                res.Lines.Add("No ducts selected.");
                return res;
            }
            bool accessories = FhaCore.AsBool(settings, "fam_accessory");
            LogContext(uidoc, settings, log, "Auto place " + NounOf(settings) + "s along run", symbol, cfg);
            log.Add("selected: " + string.Join(", ", seeds.Take(60).Select(e => Describe(e))) + (seeds.Count > 60 ? " ..." : ""));
            FamGraph graph = BuildGraph(seeds, accessories, log);
            Dictionary<long, PartRec> parts = graph.Parts;
            Dictionary<long, Element> elems = graph.Elems;
            HashSet<long> selected = graph.Selected;
            foreach (long pid in parts.Keys.OrderBy(k => k))
            {
                PartRec rec = parts[pid];
                log.Add("   part " + Inv(pid) + ": " + rec.Kind + " len " + Fmm(rec.Len) + " " + (rec.Horizontal ? "" : "(not flat) ") + "| links "
                        + "[" + string.Join(", ", rec.Conns.Select(c => c.To != null ? Inv(c.To.Value) : "None")) + "]");
            }
            List<Span> spans = FhaCore.BuildSpans(parts)
                .Where(s => s.Chain.Any(it => it.Kind == "straight" && selected.Contains(it.Id))).ToList();
            if (spans.Count == 0)
            {
                res.Lines.Add("No horizontal straight runs in the selection.");
                return res;
            }
            double flange = FhaCore.AsFloat(settings, "fam_flange_clear", 150.0) / MM;
            double userMax = FhaCore.AsFloat(settings, "fam_spacing", 3000.0);
            bool useDw = FhaCore.AsBool(settings, "fam_dw144");
            double takeoffClear = FhaCore.AsFloat(settings, "fam_takeoff_clear", 400.0) / MM;
            List<V3> existing = FhaCore.AsBool(settings, "fam_skip_existing") ? ExistingPoints(doc, symbol) : new List<V3>();
            double existClear = FhaCore.AsFloat(settings, "existing_clear", 300.0) / MM;
            List<V3> tapPts = FhaRevit.AllTapPoints(doc);
            bool rod = FhaCore.AsBool(settings, "fam_rod_auto") && !IsFloor(settings);
            bool outside = FhaCore.AsBool(settings, "fam_ins_auto");
            GroupRules rules = HfamCore.GroupRulesFrom(settings);
            Locker locker = FhaCore.AsBool(settings, "fam_lock_auto") ? new Locker(doc, uidoc.ActiveView, log) : null;
            DimTargets targets = FhaRevit.DimTargets(uidoc, settings, "fam_dims", res, log);   // asks in a 3D view
            bool wantDims = targets != null;
            DimensionType dimType = FhaRevit.FindDimType(doc, SGet(settings, "fam_dim_type", ""));

            // services that can share a hanger: every selected straight
            var pool = new List<ServiceSec>();
            foreach (long pid in selected.OrderBy(k => k))
                if (elems.ContainsKey(pid) && IsHostDuct(elems[pid]))
                    pool.Add(new ServiceSec(elems[pid], Fitted(elems[pid], outside)));
            var sized = new List<KeyValuePair<double, Span>>();
            foreach (Span span in spans)
            {
                double maxW = span.Chain.Where(it => it.Kind == "straight").Select(it => SectionCached(elems[it.Id]).Width).Max();
                sized.Add(new KeyValuePair<double, Span>(-maxW, span));
            }
            spans = sized.Select((x, i) => new { x, i }).OrderBy(z => z.x.Key).ThenBy(z => z.i).Select(z => z.x.Value).ToList();   // widest first leads a group
            var covered = new List<Covered>();   // (centre, service ids) of shared hangers placed this run

            BasePick pickedBase = FloorBasePick(uidoc, settings, res, log);
            TransactionGroup tg = new TransactionGroup(doc, "Hanger Automation - hangers along run");
            tg.Start();
            BaseSurface baseEl = pickedBase != null ? new BaseSurface(doc, pickedBase.El, pickedBase.Link, log) : null;
            if (baseEl != null)
                log.Add("supports stand on " + baseEl.Label());
            FhaRevit.Worksets ws = new FhaRevit.Worksets(doc, SGet(settings, "fam_workset", ""), log);
            SoffitFinder finder = new SoffitFinder(doc, settings, log, rod && cfg.Get("soffit", "") == "structure");
            var issues = new List<string>();
            var madeAll = new List<KeyValuePair<FamilyInstance, Section>>();
            int dimmed = 0;
            int nJobs = 0;
            try
            {
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
                    if (segs.Count == 0)
                        continue;
                    List<Element> straightEls = chain.Where(it => it.Kind == "straight").Select(it => elems[it.Id]).ToList();
                    List<Section> secs = straightEls.Select(e => SectionCached(e)).ToList();
                    double width = secs.Max(sc => sc.Width);
                    double depth = secs.Max(sc => sc.Depth);
                    bool isRound = secs.All(sc => sc.Round);
                    bool ductRun = straightEls.All(e => IsDuctwork(e));
                    double spacing = HfamCore.SpanSpacingMm(userMax, useDw && ductRun, width * MM, depth * MM, isRound);
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
                    // only hangers that really sit on THIS span count: on it (not round a
                    // bend on the next duct), within reach of its centreline; shared
                    // hangers placed this run only where this span is one of their services
                    var spanKeys = new HashSet<long>(chain.Where(it => it.Kind == "straight").Select(it => it.Id));
                    double reach = width / 2.0 + rules.GapTolFt / 2.0;
                    double dzReach = IsFloor(cfg) ? 1000.0 : 5.0;   // floor supports stand far below their service
                    List<V3> mine = covered.Where(cv => cv.Keys.Any(k => spanKeys.Contains(k))).Select(cv => cv.Centre).ToList();
                    for (int pass = 0; pass < 2; pass++)
                    {
                        List<V3> ptsList = pass == 0 ? existing : mine;
                        bool counted = pass == 0;
                        string what = pass == 0 ? "hangers already in the model" : "shared hangers placed this run";
                        double off = pass == 0 ? reach : 10.0;
                        if (ptsList.Count > 0)
                        {
                            var exSt = new List<double>();
                            foreach (V3 e in ptsList)
                            {
                                double? x = FhaCore.StationOnRun(segs, e, off, maxDzFt: dzReach);
                                if (x != null) exSt.Add(x.Value);
                            }
                            List<double> before = new List<double>(st);
                            st = FhaCore.DropNear(st, exSt, existClear);
                            if (st.Count < before.Count)
                                log.Add("   dropped " + ReprList(before.Select(x => Fmm(x))) + " -> " + ReprList(st.Select(x => Fmm(x)))
                                        + " (within " + Fmm(existClear) + " mm of " + what + " at " + ReprList(exSt.Select(x => Fmm(x))) + ")");
                            if (counted)
                                res.Skipped += before.Count - st.Count;
                        }
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
                    log.Add("span " + Fmm(length) + " mm [" + string.Join(",", chain.Select(it => Inv(it.Id))) + "] " + ServiceKind(straightEls[0]) + " "
                            + span.StartEnd.Type + "->" + span.EndEnd.Type + " | " + Fmm(width) + "x" + Fmm(depth) + (isRound ? " round" : "")
                            + " | spacing " + Fm(spacing, 0) + (ductRun ? "" : " (not ductwork: no DW/144 cap)") + " | planned "
                            + ReprList(planned.Select(x => Fmm(x))) + " | takeoffs at " + ReprList(blockSt.Select(x => Fmm(x)))
                            + " | placing at " + ReprList(places.Select(pl => Fpt(pl.Q))));
                    if (places.Count == 0)
                        continue;
                    nJobs++;
                    var made = new List<KeyValuePair<FamilyInstance, Section>>();
                    foreach (PlacePt pl in places)
                    {
                        Element host = pl.Host;
                        V3 q = pl.Q;
                        Section sec = Fitted(host, outside);
                        if (pool.Count > 1)
                        {
                            BundleResult br = BundleFor(host, sec, q, pool, outside, log, rules);
                            sec = br.Sec;
                            q = br.Point;
                        }
                        Transaction t = FhaRevit.StartTxn(doc, "Place hanger");
                        try
                        {
                            PlaceOutcome po = PlaceOne(doc, symbol, host, sec, q, cfg, rod, finder, log, ws, baseEl);
                            LockIf(locker, po.Inst, host, sec, q, po.Problems, log);
                            issues.AddRange(po.Problems);
                            bool committed;
                            using (HaTiming.Time("commit"))
                                committed = po.Inst != null && FhaRevit.Committed(t);
                            if (committed)
                            {
                                made.Add(new KeyValuePair<FamilyInstance, Section>(po.Inst, sec));
                                if ((sec.Keys != null ? sec.Keys.Count : 0) > 1)
                                    covered.Add(new Covered { Centre = q, Keys = sec.Keys });
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
                        finally
                        {
                            HaTiming.Flush(log);
                        }
                    }
                    if (made.Count > 0 && wantDims)
                    {
                        long firstId = chain[0].Id, lastId = chain[chain.Count - 1].Id;
                        V3 pStart = points.ContainsKey(firstId) ? points[firstId].Key : segs[0].A;
                        V3 pEnd = points.ContainsKey(lastId) ? points[lastId].Value : segs[segs.Count - 1].B;
                        List<Element> hs = made.Select(m => (Element)m.Key).ToList();
                        Element firstEl = straightEls[0], lastEl = straightEls[straightEls.Count - 1];
                        using (HaTiming.Time("dims"))
                        {
                            if (FhaRevit.DimensionInTargets(doc, targets, pStart, pEnd,
                                    v => ChainDimension(doc, v, pStart, pEnd, hs, firstEl, lastEl, cfg.Axis, settings, log, dimType), log))
                                dimmed++;
                        }
                        HaTiming.Flush(log, "dimensions of the span");
                    }
                    madeAll.AddRange(made);
                }
            }
            finally
            {
                finder.Close();
                if (baseEl != null) baseEl.Close();
                tg.Assimilate();
                HaTiming.EndJob(log, "Auto place");
            }
            if (madeAll.Count == 0 && res.Failed == 0)
                res.Lines.Add("Nothing to place - every span already has its hangers or is too short.");
            foreach (var m in madeAll)
            {
                if (Verify(m.Key, cfg, m.Value, res, issues, log))
                    res.Done++;
                else
                    res.Failed++;
            }
            if (res.Skipped != 0)
                res.Lines.Add(Inv(res.Skipped) + " skipped where a hanger already was (untick \"Skip existing hangers\" to place anyway).");
            if (wantDims)
            {
                res.Lines.Add(targets.Summary(dimmed, nJobs));
                FhaRevit.OfferOpen(uidoc, settings, targets, dimmed, log);
            }
            res.Lines.AddRange(SortedDistinct(issues));
            res.Lines.AddRange(ws.Problems);
            return res;
        }

        // ============================================================ quiet jobs
        /// <summary>Quiet job: the family types for the list. Returns List&lt;FamTypeItem&gt;.</summary>
        public static List<FamTypeItem> ListJob(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            return ListFamilyTypes(uidoc.Document);
        }

        /// <summary>Quiet job builder: the returned job returns byte[] (PNG of the type's preview) or null.</summary>
        public static FhaJob PreviewJobFor(ElementId symbolId)
        {
            return (uidoc, settings, log) => PreviewBytes(uidoc.Document, symbolId);
        }

        /// <summary>Quiet job builder: the returned job returns a FamParamNames (names, source).</summary>
        public static FhaJob ParamsJobFor(ElementId symbolId)
        {
            return (uidoc, settings, log) => FamilyParamNames(uidoc.Document, symbolId, log);
        }
    }
}

