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
        // ===================================================== drop rod extender
        /// <summary>The (view, made_here) pair make_temp_3d returns.</summary>
        public class Temp3D
        {
            public View3D View;
            public bool Made;
        }

        /// <summary>A clean isometric view (no template, no section box) for ray casting.
        /// Made here = a view this run created (and must delete); otherwise an existing 3D view or null.</summary>
        public static Temp3D MakeTemp3D(Document doc, FhaDebugLog log)
        {
            Transaction t = FhaRevit.StartTxn(doc, "Temporary 3D view");
            try
            {
                ViewFamilyType vft = null;
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)))
                {
                    ViewFamilyType v = (ViewFamilyType)e;
                    if (v.ViewFamily == ViewFamily.ThreeDimensional)
                    {
                        vft = v;
                        break;
                    }
                }
                View3D view = View3D.CreateIsometric(doc, vft.Id);
                try { view.ViewTemplateId = ElementId.InvalidElementId; }
                catch (Exception) { }
                if (FhaRevit.Committed(t))
                    return new Temp3D { View = view, Made = true };
            }
            catch (Exception ex)
            {
                FhaRevit.Rollback(t);
                log.Add("temporary 3D view: " + ex.Message);
            }
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(View3D)))
            {
                View3D v = (View3D)e;
                if (!v.IsTemplate) return new Temp3D { View = v, Made = false };
            }
            return new Temp3D { View = null, Made = false };
        }

        public static void DropTempView(Document doc, View3D view, bool made, FhaDebugLog log)
        {
            if (view == null || !made) return;
            Transaction t = FhaRevit.StartTxn(doc, "Remove temporary 3D view");
            try
            {
                doc.Delete(view.Id);
                FhaRevit.Committed(t);
            }
            catch (Exception ex)
            {
                FhaRevit.Rollback(t);
                log.Add("remove temporary view: " + ex.Message);
            }
        }

        /// <summary>The (z, how) pair Target.underside returns; Z is null when there is no hit.</summary>
        public class UndersideResult
        {
            public double? Z;
            public string How;
        }

        /// <summary>The element the drop rods go up to, in this model or a linked one.
        ///
        /// Underside(x, y, z): the first face of that element straight above the
        /// point (a ray through a clean temporary 3D view, links included); when the
        /// element is not directly above, its lowest point (its invert) instead.</summary>
        public class Target
        {
            public Document Doc;
            public Element El;
            public RevitLinkInstance Link;
            public FhaDebugLog Log;
            public View3D View;
            public bool Made;
            public ReferenceIntersector Ri;

            public Target(Document doc, Element el, RevitLinkInstance link, FhaDebugLog log)
            {
                Doc = doc; El = el; Link = link; Log = log;
                Temp3D t = MakeTemp3D(doc, log);
                View = t.View;
                Made = t.Made;
                Ri = null;
                try
                {
                    if (View != null)
                    {
                        if (link == null)
                            Ri = new ReferenceIntersector(el.Id, FindReferenceTarget.Face, View);
                        else
                        {
                            Ri = new ReferenceIntersector(new ElementCategoryFilter(el.Category.Id), FindReferenceTarget.Face, View);
                            Ri.FindReferencesInRevitLinks = true;
                        }
                    }
                }
                catch (Exception ex)
                {
                    log.Add("target ray: " + ex.Message);
                }
            }

            public string Label()
            {
                string where = Link != null ? "link " + ElName(Link) : "this model";
                string cat;
                try { cat = El.Category.Name; }
                catch (Exception) { cat = "element"; }
                return cat + " " + Inv(Eid(El.Id)) + " (" + ElName(El) + ") in " + where;
            }

            public double? Lowest()
            {
                try
                {
                    BoundingBoxXYZ bb = El.get_BoundingBox(null);
                    if (Link == null) return bb.Min.Z;
                    Transform tf = Link.GetTotalTransform();
                    return Math.Min(tf.OfPoint(bb.Min).Z, tf.OfPoint(bb.Max).Z);
                }
                catch (Exception) { return null; }
            }

            public UndersideResult Underside(double x, double y, double z)
            {
                XYZ origin = new XYZ(x, y, z + 0.01);
                if (Ri != null)
                {
                    try
                    {
                        if (Link == null)
                        {
                            ReferenceWithContext hit = Ri.FindNearest(origin, XYZ.BasisZ);
                            if (hit != null) return new UndersideResult { Z = hit.GetReference().GlobalPoint.Z, How = "ray" };
                        }
                        else
                        {
                            var hits = Ri.Find(origin, XYZ.BasisZ).OrderBy(h => h.Proximity).ToList();
                            foreach (ReferenceWithContext h in hits)
                            {
                                Reference r = h.GetReference();
                                if (Eid(r.ElementId) == Eid(Link.Id) && Eid(r.LinkedElementId) == Eid(El.Id))
                                    return new UndersideResult { Z = r.GlobalPoint.Z, How = "ray" };
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        Log.Add("target ray: " + ex.Message);
                    }
                }
                double? low = Lowest();
                return low != null && low.Value > z ? new UndersideResult { Z = low, How = "lowest point" } : new UndersideResult { Z = null, How = "not above" };
            }

            public void Close()
            {
                DropTempView(Doc, View, Made, Log);
            }
        }

        /// <summary>The (element, link instance or null) pair the pick functions return.</summary>
        public class BasePick
        {
            public Element El;
            public RevitLinkInstance Link;
        }

        /// <summary>(element, link instance or null). Clicking a linked model goes on to
        /// a second click on the element inside it.</summary>
        public static BasePick PickTarget(UIDocument uidoc, bool linkedFirst, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            string prompt = "Click the element to extend the drop rods to (floor, beam, steel, service...)";
            if (!linkedFirst)
            {
                Reference r0 = uidoc.Selection.PickObject(ObjectType.Element, prompt);
                Element el = doc.GetElement(r0.ElementId);
                if (!(el is RevitLinkInstance))
                    return new BasePick { El = el, Link = null };
                log.Add("clicked link " + ElName(el) + " - now picking inside it");
            }
            Reference r1 = uidoc.Selection.PickObject(ObjectType.LinkedElement, "Click the element in the linked model");
            RevitLinkInstance link = (RevitLinkInstance)doc.GetElement(r1.ElementId);
            Document ldoc = link.GetLinkDocument();
            return new BasePick { El = ldoc.GetElement(r1.LinkedElementId), Link = link };
        }

        // ============================================================ floor base
        public static readonly string[] BaseCats = { "OST_Floors", "OST_Roofs", "OST_MechanicalEquipment", "OST_StructuralFoundation" };

        public static bool BaseOk(Element e)
        {
            return e is RevitLinkInstance || BaseCats.Any(c => CatIs(e, c));
        }

        /// <summary>The (z, how, under) triple BaseSurface.stand returns: Z null when the support is not over the surface;
        /// Under = the surface height under each post (null where there is none).</summary>
        public class StandResult
        {
            public double? Z;
            public string How;
            public List<double?> Under = new List<double?>();
        }

        /// <summary>The floor, roof or mechanical equipment floor supports stand on, in this
        /// model or a linked one. Stand(): the top surface straight below a support's
        /// centre (a ray down through a clean temporary 3D view, links included) - on
        /// a slope that is the height where the centre meets it. If the centre is off
        /// the surface, the highest hit under either post (its edge); then the top of
        /// its bounding box when the support is over it.</summary>
        public class BaseSurface : Target
        {
            public BaseSurface(Document doc, Element el, RevitLinkInstance link, FhaDebugLog log) : base(doc, el, link, log) { }

            public double? TopAt(double x, double y, double zFrom)
            {
                if (Ri == null) return null;
                XYZ origin = new XYZ(x, y, zFrom - 0.003);
                XYZ down = new XYZ(0.0, 0.0, -1.0);
                try
                {
                    if (Link == null)
                    {
                        ReferenceWithContext hit = Ri.FindNearest(origin, down);
                        return hit != null ? (double?)hit.GetReference().GlobalPoint.Z : null;
                    }
                    var hits = Ri.Find(origin, down).OrderBy(h => h.Proximity).ToList();
                    foreach (ReferenceWithContext h in hits)
                    {
                        Reference r = h.GetReference();
                        if (Eid(r.ElementId) == Eid(Link.Id) && Eid(r.LinkedElementId) == Eid(El.Id))
                            return r.GlobalPoint.Z;
                    }
                }
                catch (Exception ex)
                {
                    Log.Add("   base ray: " + ex.Message);
                }
                return null;
            }

            public double? BoxTop(double x, double y)
            {
                try
                {
                    BoundingBoxXYZ bb = El.get_BoundingBox(null);
                    var pts = new List<XYZ>();
                    foreach (double px in new[] { bb.Min.X, bb.Max.X })
                        foreach (double py in new[] { bb.Min.Y, bb.Max.Y })
                            foreach (double pz in new[] { bb.Min.Z, bb.Max.Z })
                                pts.Add(new XYZ(px, py, pz));
                    if (Link != null)
                    {
                        Transform tf = Link.GetTotalTransform();
                        pts = pts.Select(p => tf.OfPoint(p)).ToList();
                    }
                    double minX = pts.Min(p => p.X), maxX = pts.Max(p => p.X);
                    double minY = pts.Min(p => p.Y), maxY = pts.Max(p => p.Y);
                    if (minX <= x && x <= maxX && minY <= y && y <= maxY)
                        return pts.Max(p => p.Z);
                }
                catch (Exception) { }
                return null;
            }

            /// <summary>(z or null, how, [z under each post]); posts are plan points (x, y).</summary>
            public StandResult Stand(V3 q, double zFrom, IList<V3> posts)
            {
                double? zc = TopAt(q.X, q.Y, zFrom);
                var under = posts.Select(p => TopAt(p.X, p.Y, zFrom)).ToList();
                if (zc != null)
                    return new StandResult { Z = zc, How = "its top surface under the centre", Under = under };
                var hits = under.Where(z => z != null).Select(z => z.Value).ToList();
                if (hits.Count > 0)
                    return new StandResult { Z = hits.Max(), How = "its edge (the centre is off the surface)", Under = under };
                double? zb = BoxTop(q.X, q.Y);
                if (zb != null && zb.Value <= zFrom)
                    return new StandResult { Z = zb, How = "the top of its box (no face hit)", Under = under };
                return new StandResult { Z = null, How = "not under this support", Under = under };
            }
        }

        /// <summary>Height a floor support's base stands at on the picked element, or its
        /// level (with a problem) when the element is not under it.</summary>
        public static double FloorStand(BaseSurface baseEl, Section sec, V3 q, double zBot, FamConfig cfg, Level level, List<string> problems, FhaDebugLog log)
        {
            V3 along, across;
            HfamCore.PlanDirs(sec.A, sec.B, out along, out across);
            double clear = FhaCore.ParseMm(cfg.Get("clearance", "0"), 0.0) / MM;
            double hn = (sec.ExtNeg ?? sec.Width / 2.0) + clear;
            double hp = (sec.ExtPos ?? sec.Width / 2.0) + clear;
            var posts = new List<V3>
            {
                new V3(q.X - across.X * hn, q.Y - across.Y * hn, 0.0),
                new V3(q.X + across.X * hp, q.Y + across.Y * hp, 0.0),
            };
            StandResult sr = baseEl.Stand(q, zBot, posts);
            double? z = sr.Z;
            List<double?> under = sr.Under;
            List<string> shown = under.Select(u => u != null ? Fmm(u) : "-").ToList();
            if (z == null)
            {
                problems.Add("the picked base is not under every support - those stand on the level");
                log.Add("   base: " + baseEl.Label() + " is not under it - standing on the level");
                return level.ProjectElevation;
            }
            List<double> fall = under.Where(u => u != null).Select(u => u.Value).ToList();
            string slope = fall.Count == 2 && Math.Abs(fall[0] - fall[1]) > 1.0 / MM
                ? " | falls " + Fmm(fall.Max() - fall.Min()) + " mm across the frame" : "";
            log.Add("   base: stands at " + Fmm(z) + " on " + baseEl.Label() + " (" + sr.How + ") | under the posts " + string.Join(" / ", shown) + slope);
            if (z.Value > zBot + Tol)
            {
                problems.Add("the picked base is above the service there - that support stands on the level");
                return level.ProjectElevation;
            }
            return z.Value;
        }

        /// <summary>(element, link instance or null) the floor supports stand on.</summary>
        public static BasePick PickBase(UIDocument uidoc, bool linkedFirst, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            if (!linkedFirst)
            {
                Reference r0 = uidoc.Selection.PickObject(ObjectType.Element, new HfamFilter(BaseOk),
                                                           "Click the floor, roof or mechanical equipment the supports stand on "
                                                           + "(or a linked model) - Esc stands them on the level");
                Element el = doc.GetElement(r0.ElementId);
                if (!(el is RevitLinkInstance))
                    return new BasePick { El = el, Link = null };
                log.Add("clicked link " + ElName(el) + " - now picking inside it");
            }
            Reference r1 = uidoc.Selection.PickObject(ObjectType.LinkedElement, "Click the floor, roof or equipment in the linked model");
            RevitLinkInstance link = (RevitLinkInstance)doc.GetElement(r1.ElementId);
            return new BasePick { El = link.GetLinkDocument().GetElement(r1.LinkedElementId), Link = link };
        }

        /// <summary>Floor Support tab with 'Supports stand on: a picked element': ask for it.
        /// (element, link) or null (the level). Call before any transaction group.</summary>
        public static BasePick FloorBasePick(UIDocument uidoc, FhaSettings settings, JobResult res, FhaDebugLog log)
        {
            if (!IsFloor(settings) || SGet(settings, "flr_base", "level") != "element")
                return null;
            bool linked = FhaCore.AsBool(settings, "flr_base_linked");
            IFhaPrompts ui = settings.Prompts;
            if (ui != null)   // say so first: a pick with only Revit's status bar to tell you looks like a hang
            {
                string ans;
                try
                {
                    ans = ui.AskBasePick(linked);
                }
                catch (Exception ex)
                {
                    log.Add("base prompt: " + ex.Message);
                    ans = "pick";
                }
                log.Add("base: asked to pick - " + (string.IsNullOrEmpty(ans) ? "closed" : ans));
                if (ans != "pick")
                {
                    res.Lines.Add("No base picked - the supports stand on the level.");
                    return null;
                }
            }
            BasePick bp;
            try
            {
                bp = PickBase(uidoc, linked, log);
            }
            catch (Exception)
            {
                res.Lines.Add("No base picked - the supports stand on the level.");
                return null;
            }
            if (bp == null || bp.El == null)
                return null;
            if (!BaseCats.Any(c => CatIs(bp.El, c)))
                log.Add("base: " + Describe(bp.El) + " is not a floor, roof or equipment - using it anyway");
            return bp;
        }

        /// <summary>Drop rod extender: pick hangers, then any element above them (this
        /// model or a link); each hanger's drop rod runs from its reference level up
        /// to that element's underside above it, or its lowest point.</summary>
        public static JobResult JobRods(UIDocument uidoc, FhaSettings settings, FhaDebugLog log)
        {
            Document doc = uidoc.Document;
            JobResult res = FhaRevit.NewResult("Drop rod extender");
            LogContext(uidoc, settings, log, "Drop rod extender");
            Dictionary<string, FamConfig> fams = FamsOf(settings);
            HfamChoice chosen = ChoiceOf(settings);
            List<Element> hangers = uidoc.Selection.GetElementIds().Select(i => doc.GetElement(i)).ToList();
            hangers = hangers.Where(h => h != null && IsHangerFamily(h)).ToList();
            if (hangers.Count == 0)
            {
                try
                {
                    IList<Reference> refs = uidoc.Selection.PickObjects(ObjectType.Element, new HfamFilter(IsHangerFamily),
                                                                        "Pick the hangers (box or click), then Finish");
                    hangers = refs.Select(r => doc.GetElement(r.ElementId)).ToList();
                }
                catch (Exception)
                {
                    hangers = new List<Element>();
                }
            }
            if (hangers.Count == 0)
            {
                res.Lines.Add("No hangers picked.");
                return res;
            }
            BasePick tp;
            try
            {
                tp = PickTarget(uidoc, FhaCore.AsBool(settings, "fam_rod_linked"), log);
            }
            catch (Exception)
            {
                res.Lines.Add("No target picked.");
                return res;
            }
            FhaRevit.Checkout(doc, hangers, log);
            FhaRevit.Worksets ws = new FhaRevit.Worksets(doc, SGet(settings, "fam_workset", ""), log);
            TransactionGroup tg = new TransactionGroup(doc, "Hanger Automation - extend drop rods");
            tg.Start();
            Target target = new Target(doc, tp.El, tp.Link, log);
            log.Add("target: " + target.Label() + " | lowest point " + Fmm(target.Lowest()));
            try
            {
                foreach (Element h in hangers)
                {
                    string fam = ElName(((FamilyInstance)h).Symbol.Family);
                    FamConfig cfg;
                    if (!fams.TryGetValue(fam, out cfg) || cfg == null)
                        cfg = (chosen != null && chosen.Family == fam ? chosen.Cfg : null) ?? HfamCore.FamConfigFor(fams, fam);
                    V3? pn = InstancePoint(h);
                    if (pn == null)
                    {
                        res.Failed++;
                        continue;
                    }
                    V3 p = pn.Value;
                    UndersideResult us = target.Underside(p.X, p.Y, p.Z);
                    double? top = us.Z;
                    double? L = HfamCore.RodToTarget(p.Z, top);
                    log.Add("hanger " + Inv(Eid(h.Id)) + " (" + fam + ") ref " + Fmm(p.Z) + " -> target " + Fmm(top) + " by " + us.How
                            + ": rod " + cfg.Rod + " = " + Fmm(L));
                    if (L == null)
                    {
                        res.Skipped++;
                        res.Lines.Add("Hanger " + Inv(Eid(h.Id)) + ": the target is not above it.");
                        continue;
                    }
                    Transaction t = FhaRevit.StartTxn(doc, "Extend drop rod");
                    bool okRod = SetLength(h, cfg.Rod, L.Value);
                    if (okRod)
                        ws.Apply(h, null, false);
                    if (okRod && FhaRevit.Committed(t))
                    {
                        if (Math.Abs((GetLength(h, cfg.Rod) ?? 0.0) - L.Value) < Tol)
                            res.Done++;
                        else
                            res.Failed++;
                    }
                    else
                    {
                        FhaRevit.Rollback(t);
                        res.Failed++;
                        res.Lines.Add("Hanger " + Inv(Eid(h.Id)) + ": no writable \"" + cfg.Rod + "\" parameter - check Family settings.");
                    }
                }
            }
            finally
            {
                target.Close();
                tg.Assimilate();
            }
            res.Lines.Insert(0, "Target: " + target.Label());
            res.Lines.AddRange(ws.Problems);
            return res;
        }
    }
}
