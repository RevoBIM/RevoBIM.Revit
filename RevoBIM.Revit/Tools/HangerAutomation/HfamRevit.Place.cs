using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        // ============================================================ placing
        /// <summary>Turn the instance about its own vertical axis so its X axis lies along wantX.
        /// Returns the angle turned (radians), or null when the rotation failed.</summary>
        public static double? AlignRotation(Document doc, Element inst, V3 wantX)
        {
            try
            {
                XYZ cur = ((FamilyInstance)inst).HandOrientation;
                double ang = HfamCore.RotationTo(cur.X, cur.Y, wantX.X, wantX.Y);
                if (Math.Abs(ang) > 1e-6)
                {
                    XYZ o = ((LocationPoint)inst.Location).Point;
                    Line axis = Line.CreateBound(o, new XYZ(o.X, o.Y, o.Z + 1.0));
                    ElementTransformUtils.RotateElement(doc, inst.Id, axis, ang);
                }
                return ang;
            }
            catch (Exception) { return null; }
        }

        /// <summary>Offset to the invert, square to the duct, width to the duct, rod to the
        /// soffit. Caller holds the transaction. Returns a list of problems.</summary>
        public static List<string> FitToDuct(Document doc, FamilyInstance inst, Section sec, V3 q, Level level, FamConfig cfg, bool rod,
                                             SoffitFinder finder, FhaDebugLog log, BaseSurface baseEl = null)
        {
            var problems = new List<string>();
            double zBot = q.Z - sec.Depth / 2.0;
            V3 along, across;
            HfamCore.PlanDirs(sec.A, sec.B, out along, out across);
            double? ang = AlignRotation(doc, inst, HfamCore.FamilyXDir(cfg.Axis, along, across));
            log.Add("   level " + ElName(level) + " @ " + Fmm(level.ProjectElevation) + " | invert " + Fmm(zBot) + " | turned "
                    + (ang != null ? Fm(ang.Value * 57.29577951, 1) : "? (rotation failed)") + " deg");
            bool floor = IsFloor(cfg);
            double stand = level.ProjectElevation;   // where a floor support's base sits: its level ...
            Parameter p = OffsetParam(inst);
            if (floor && baseEl != null && p != null)   // ... or the top of the floor / roof / equipment picked
                stand = FloorStand(baseEl, sec, q, zBot, cfg, level, problems, log);
            else if (floor && baseEl != null)
                problems.Add("no writable offset parameter - the support could not be lifted onto the picked element");
            double baseOff = floor ? stand - level.ProjectElevation : zBot - level.ProjectElevation;
            if (p == null)
            {
                if (!floor)
                    problems.Add("no writable offset / elevation parameter");
                log.Add("   offset: no writable Elevation from Level / Offset from Host");
            }
            else
            {
                p.Set(baseOff);
                log.Add("   offset: " + p.Definition.Name + " = " + Fmm(baseOff) + (floor
                        ? (Math.Abs(baseOff) < Tol ? " (stands on the level)" : " (stands on the picked element, hosted on the level)")
                        : ""));
            }
            if (floor)
            {
                double first, height;
                HfamCore.FloorValues(zBot, stand, sec, FhaCore.ParseMm(cfg.Get("height_clear", "0"), 0.0) / MM, out first, out height);
                if (first < -Tol)
                    problems.Add("the service is below what the support stands on");
                var pairs = new[]
                {
                    new { key = "first_bar", label = "first bar", val = first },
                    new { key = "height", label = "support height", val = height },
                };
                foreach (var pr in pairs)
                {
                    bool ok = SetLength(inst, cfg[pr.key], pr.val);
                    string nm = string.IsNullOrEmpty(cfg[pr.key]) ? "(not set)" : cfg[pr.key];
                    log.Add("   " + pr.label + ": " + nm + " = " + Fmm(pr.val) + (ok ? "" : "  <- NOT SET"));
                    if (!ok)
                        problems.Add(pr.label + " parameter \"" + nm + "\" not found or read only - set it in Family settings");
                }
            }
            double clear = FhaCore.ParseMm(cfg.Get("clearance", "0"), 0.0) / MM;
            V3 axisVec = new V3(1.0, 0.0, 0.0);
            try
            {
                using (HaTiming.Time("fit.regen"))
                    doc.Regenerate();
                XYZ v = cfg.Get("axis", "X") == "X" ? inst.HandOrientation : inst.FacingOrientation;
                axisVec = new V3(v.X, v.Y, 0.0);
            }
            catch (Exception) { }
            double vl, vr;
            HfamCore.SideValues(sec, axisVec, clear, out vl, out vr, cfg.Get("swap", "") == "1");
            var vals = new SideVals { Left = vl, Right = vr };
            sec.SetLeft = vals.Left;
            sec.SetRight = vals.Right;
            foreach (string key in new[] { "left", "right" })
            {
                double val = key == "left" ? vals.Left : vals.Right;
                bool ok = SetLength(inst, cfg[key], val);
                string nm = string.IsNullOrEmpty(cfg[key]) ? "(not set)" : cfg[key];
                log.Add("   width " + key + ": " + nm + " = " + Fmm(val) + (ok ? "" : "  <- NOT SET"));
                if (!ok)
                    problems.Add("width parameter \"" + nm + "\" not found or read only - set it in Family settings");
            }
            if (sec.ExtNeg != null && Math.Abs(sec.ExtNeg.Value - sec.ExtPos.Value) > 1.0 / MM)
                CheckSides(doc, inst, sec, q, cfg, vals, clear, log);
            if (rod)
            {
                string soffit = cfg.Get("soffit", "level");
                double? top;
                using (HaTiming.Time("fit.rod"))
                    top = finder.Above(soffit, q.X, q.Y, zBot, SoffitFinder.ExcludeIds(inst));   // never stops at this hanger
                double? L = HfamCore.RodLength(zBot, top);
                if (L == null)
                {
                    problems.Add("no level / soffit above the hanger for the drop rod");
                    log.Add("   rod: nothing above " + Fmm(zBot) + " (" + soffit + ")");
                }
                else
                {
                    bool ok = SetLength(inst, cfg.Rod, L.Value);
                    log.Add("   rod: " + cfg.Rod + " = " + Fmm(L) + " (soffit " + Fmm(top) + " by " + soffit + ")" + (ok ? "" : "  <- NOT SET"));
                    if (!ok)
                        problems.Add("drop rod parameter \"" + cfg.Rod + "\" not found");
                }
            }
            return problems;
        }

        /// <summary>The two stretch values a hanger is set to (the Python dict vals['left'] / vals['right']).</summary>
        public class SideVals
        {
            public double Left, Right;
        }

        /// <summary>A shared hanger reaches further one way than the other. Measure where
        /// it actually went (its bounding box across the run) and, if the long side
        /// came out on the short side, swap the two width values.</summary>
        public static void CheckSides(Document doc, FamilyInstance inst, Section sec, V3 q, FamConfig cfg, SideVals vals, double clear, FhaDebugLog log)
        {
            try
            {
                doc.Regenerate();
                BoundingBoxXYZ bb = inst.get_BoundingBox(null);
                List<V3> corners = BoxCorners(bb);
                V3 ac = sec.Across.Value;
                double rp, rn;
                HfamCore.Reaches(corners, q, ac, out rp, out rn);
                double wp = sec.ExtPos.Value + clear, wn = sec.ExtNeg.Value + clear;
                log.Add("   reaches " + Fmm(rp) + " / " + Fmm(rn) + " mm either side (wanted " + Fmm(wp) + " / " + Fmm(wn) + ")");
                if (HfamCore.SidesMirrored(rp, rn, wp, wn))
                {
                    double tmp = vals.Left; vals.Left = vals.Right; vals.Right = tmp;
                    foreach (string key in new[] { "left", "right" })
                        SetLength(inst, cfg[key], key == "left" ? vals.Left : vals.Right);
                    sec.SetLeft = vals.Left;
                    sec.SetRight = vals.Right;
                    doc.Regenerate();
                    bb = inst.get_BoundingBox(null);
                    corners = BoxCorners(bb);
                    HfamCore.Reaches(corners, q, ac, out rp, out rn);
                    log.Add("   came out mirrored - swapped the widths: now " + Fmm(rp) + " / " + Fmm(rn) + " mm");
                }
            }
            catch (Exception ex)
            {
                log.Add("   could not measure the hanger to check its sides: " + ex.Message);
            }
        }

        /// <summary>[(x, y) for x in (min, max) for y in (min, max)] of a bounding box, as plan points (z = 0).</summary>
        private static List<V3> BoxCorners(BoundingBoxXYZ bb)
        {
            var o = new List<V3>();
            foreach (double x in new[] { bb.Min.X, bb.Max.X })
                foreach (double y in new[] { bb.Min.Y, bb.Max.Y })
                    o.Add(new V3(x, y, 0.0));
            return o;
        }

        /// <summary>The (instance, problems) pair place_one returns. Instance is null when nothing was placed.</summary>
        public class PlaceOutcome
        {
            public FamilyInstance Inst;
            public List<string> Problems = new List<string>();
        }

        /// <summary>Create one hanger at centreline point q. Caller holds the transaction.</summary>
        public static PlaceOutcome PlaceOne(Document doc, FamilySymbol symbol, Element duct, Section sec, V3 q, FamConfig cfg, bool rod,
                                            SoffitFinder finder, FhaDebugLog log, FhaRevit.Worksets ws = null, BaseSurface baseEl = null)
        {
            HaTiming.Scope placeScope = HaTiming.Time("place");
            Level level;
            if (IsFloor(cfg))
                level = FloorLevel(doc, duct, q.Z - sec.Depth / 2.0, log);
            else
                level = ElementLevel(doc, duct, q.Z);
            if (level == null)
            {
                placeScope.Dispose();
                return new PlaceOutcome { Inst = null, Problems = new List<string> { "the duct has no level" } };
            }
            try
            {
                if (!symbol.IsActive)
                {
                    symbol.Activate();
                    doc.Regenerate();
                }
            }
            catch (Exception) { }
            V3 along, across;
            HfamCore.PlanDirs(sec.A, sec.B, out along, out across);
            V3 wantX = HfamCore.FamilyXDir(cfg.Axis, along, across);
            XYZ loc = new XYZ(q.X, q.Y, level.ProjectElevation);
            string placement = "";
            try { placement = symbol.Family.FamilyPlacementType.ToString(); }
            catch (Exception) { }
            FamilyInstance inst = null;
            if (placement == "WorkPlaneBased")
            {
                try
                {
                    inst = doc.Create.NewFamilyInstance(level.GetPlaneReference(), loc, ToXyz(wantX), symbol);
                }
                catch (Exception ex)
                {
                    log.Add("work plane placement: " + ex.Message);
                }
            }
            if (inst == null)
            {
                try
                {
                    inst = doc.Create.NewFamilyInstance(loc, symbol, level, StructuralType.NonStructural);
                }
                catch (Exception ex)
                {
                    placeScope.Dispose();
                    return new PlaceOutcome { Inst = null, Problems = new List<string> { "Revit refused to place " + ElName(symbol) + ": " + ex.Message } };
                }
            }
            doc.Regenerate();
            if (ws != null)
                ws.Apply(inst, duct, true);
            else
                FhaRevit.MatchWorkset(inst, duct);
            placeScope.Dispose();
            log.Add("+ hanger " + Inv(Eid(inst.Id)) + " on " + Describe(duct) + " at " + Fpt(q) + " (" + (placement.Length > 0 ? placement : "?") + ")");
            LogSection(log, sec);
            log.Add("   service category: " + CategoryText(duct));
            List<string> problems;
            using (HaTiming.Time("fit"))
                problems = FitToDuct(doc, inst, sec, q, level, cfg, rod, finder, log, baseEl);
            using (HaTiming.Time("comment"))
                FhaRevit.WriteServiceComment(inst, FhaRevit.ServicesOf(doc, sec.Keys, duct), log);
            return new PlaceOutcome { Inst = inst, Problems = problems };
        }

        /// <summary>'Pipes (pipe)', 'Conduits (conduit)', 'Fabrication Ductwork (FAB duct)' - the category of a service for the log.</summary>
        public static string CategoryText(Element el)
        {
            string cat;
            try { cat = el.Category != null ? el.Category.Name : "?"; }
            catch (Exception) { cat = "?"; }
            return cat + " (" + ServiceKind(el) + ")";
        }

        /// <summary>The instance's location point, or null.</summary>
        public static V3? InstancePoint(Element inst)
        {
            try { return Pt(((LocationPoint)inst.Location).Point); }
            catch (Exception) { return null; }
        }

        /// <summary>A straight on a run and its section (the Python (element, section) pairs).</summary>
        public class ServiceSec
        {
            public Element El;
            public Section Sec;
            public ServiceSec() { }
            public ServiceSec(Element el, Section sec) { El = el; Sec = sec; }
        }

        /// <summary>(element, section) for every straight on the picked duct's run, walking
        /// through fittings and accessories, so each hanger can be fitted to the
        /// segment it actually hangs from (sizes change along a run).</summary>
        public static List<ServiceSec> RunStraights(Document doc, Element duct, int limit = 600)
        {
            var o = new List<ServiceSec>();
            var seen = new HashSet<long> { Eid(duct.Id) };
            var todo = new List<Element> { duct };
            while (todo.Count > 0 && seen.Count < limit)
            {
                Element el = todo[todo.Count - 1];
                todo.RemoveAt(todo.Count - 1);
                if (IsHostDuct(el))
                {
                    try { o.Add(new ServiceSec(el, Section(el))); }
                    catch (Exception) { }
                }
                foreach (Connector c in GConns(el))
                {
                    Connector nb = GNeighbour(c);
                    if (nb == null) continue;
                    Element ow = nb.Owner;
                    long oid = Eid(ow.Id);
                    if (!seen.Contains(oid))
                    {
                        seen.Add(oid);
                        todo.Add(ow);
                    }
                }
            }
            return o;
        }

        /// <summary>Square a hanger up to its duct WITHOUT moving it along the run: it only
        /// slides sideways onto the centreline (the line is not clipped to the
        /// segment), then its level, invert, rotation, width and rod are refitted.
        /// Caller holds the transaction. Returns the problems.</summary>
        public static List<string> RealignOne(Document doc, FamilyInstance inst, Element duct, Section sec, FamConfig cfg, bool rod,
                                              SoffitFinder finder, FhaDebugLog log, FhaRevit.Worksets ws = null, BaseSurface baseEl = null)
        {
            V3? pn = InstancePoint(inst);
            if (pn == null)
                return new List<string> { "the hanger has no location point" };
            HaTiming.Scope moveScope = HaTiming.Time("realign");
            V3 p = pn.Value;
            V3 q = HfamCore.OnLine(sec.A, sec.B, p);
            log.Add("~ hanger " + Inv(Eid(inst.Id)) + " at " + Fpt(p) + " -> " + Fpt(q) + " | sideways "
                    + Fmm(HfamCore.PlanOffset(sec.A, sec.B, p)) + " mm | on " + Describe(duct));
            LogSection(log, sec);
            log.Add("   service category: " + CategoryText(duct));
            try
            {
                ElementTransformUtils.MoveElement(doc, inst.Id, new XYZ(q.X - p.X, q.Y - p.Y, 0.0));
            }
            catch (Exception ex)
            {
                moveScope.Dispose();
                return new List<string> { "could not move it: " + ex.Message };
            }
            Level ductLevel;
            if (IsFloor(cfg))
                ductLevel = FloorLevel(doc, duct, q.Z - sec.Depth / 2.0, log);
            else
                ductLevel = ElementLevel(doc, duct, q.Z);
            Level level = ElementLevel(doc, inst, p.Z);
            var problems = new List<string>();
            if (ductLevel != null && (level == null || Eid(level.Id) != Eid(ductLevel.Id)))
            {
                if (SetLevel(inst, ductLevel))
                {
                    log.Add("   level " + (level != null ? ElName(level) : "?") + " -> " + ElName(ductLevel));
                    level = ductLevel;
                }
                else
                    problems.Add("kept its own level (level is not editable on this family)");
            }
            if (ws != null)
                ws.Apply(inst, duct, false);
            doc.Regenerate();
            moveScope.Dispose();
            if (level == null)
            {
                problems.Add("no level");
                return problems;
            }
            using (HaTiming.Time("fit"))
                problems.AddRange(FitToDuct(doc, inst, sec, q, level, cfg, rod, finder, log, baseEl));
            return problems;
        }
    }
}
