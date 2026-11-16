using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.HangerAutomation
{
    // =====================================================================================================
    // Hanger Automation - Circular System Based floor supports and (1.14.0) hangers: everything that
    // touches Revit. Port of hcirc_revit.py.
    //
    // A path of its own. The Family Floor Support and Family Hangers tabs only come here when the chosen
    // family is saved as Circular System Based in Family settings; the rectangular supports and the
    // Rectangular Hanger System families stay entirely in HfamRevit, which this module reads from
    // (sections, levels, picking, the run graph, locks, the base pick, worksets) but never changes.
    //
    // Jobs (run from the window through the shared ExternalEvent):
    //   JobPlace    click pipes / round ducts one after another: a ring at each click
    //   JobRealign  pick the service, then the supports: each slides sideways onto the centreline and is refitted
    //   JobAuto     select a run: rings along it by the Auto placement rules
    //   JobDims     the dimension placer, reading a ring by the way its service runs
    //
    // Each support:
    //   - stands on the service's level (or the floor / roof / equipment picked), at the service
    //     centreline, turned so the service runs along the family's X or Y (Family settings);
    //   - diameter parameter = the service's outside diameter (+ insulation, ticked);
    //   - support height parameter = base up to the service centre AT THAT SUPPORT (the intersecting
    //     midpoint: a sloping pipe gets a different height at every support) - the family is placed at its
    //     reference level and its height parameter runs up to the ring centre (1.13.0);
    //   - then the ring is measured in the placed support (its round faces and arcs) as a check: if it is
    //     not on the service centre the results say so. The height is never changed by the check. Every
    //     step is in the debug log.
    //
    // Each circular hanger (Family Hangers tab) goes on the service's level with its reference on the
    // service CENTRELINE (1.14.1: the pipe / round duct / round FAB duct centre where it hangs), turned to
    // the X / Y set, its diameter parameter set to the service's diameter, its drop rod run from there up
    // to the level or structure above (ticked). The same ring check follows.
    //
    // Files: HcircRevit.cs (the ring, fitting, placing), HcircRevit.Jobs.cs (the four jobs).
    // =====================================================================================================
    public static partial class HcircRevit
    {
        public const double MM = FhaCore.MM;
        public const double Tol = HfamRevit.Tol;    // TOL = hr.TOL
        public const string NotRound = "A Circular System Based {1} goes on a pipe or round duct - {0} was skipped.";   // NOT_ROUND

        // ---------------------------------------------------------------- private plumbing
        private static long Eid(ElementId id) { return FhaRevit.EidValue(id); }
        private static string ElName(Element el) { return FhaRevit.ElName(el); }
        private static V3 Pt(XYZ v) { return FhaRevit.Pt(v); }
        private static XYZ ToXyz(V3 v) { return FhaRevit.ToXyz(v); }
        private static string Fmm(double? v) { return HfamRevit.Fmm(v); }
        private static string Fpt(V3? p) { return HfamRevit.Fpt(p); }
        private static string Describe(Element el) { return HfamRevit.Describe(el); }

        /// <summary>NOT_ROUND.format(name, noun).</summary>
        private static string NotRoundText(string name, string noun)
        {
            // {1} first: the noun never holds a placeholder, an element name might ("{1}" in a name must stay as typed)
            return NotRound.Replace("{1}", noun).Replace("{0}", name);
        }

        /// <summary>Python "{0:.Nf}" for log lines.</summary>
        private static string Fm(double v, int decimals)
        {
            if (decimals == 0)
            {
                // Python's '{0:.0f}' rounds an exact .5 to even ("-0" for a small negative); .NET "F0" rounds it away from zero
                string s0 = Math.Round(v, MidpointRounding.ToEven).ToString("0", CultureInfo.InvariantCulture);
                if ((s0 == "0" || s0 == "-0") && (v < 0 || (v == 0 && 1.0 / v < 0))) s0 = "-0";
                else if (s0 == "-0") s0 = "0";
                return s0;
            }
            return v.ToString("F" + decimals.ToString(CultureInfo.InvariantCulture), CultureInfo.InvariantCulture);
        }

        /// <summary>Python "{0:+.1f}".</summary>
        private static string FmSigned1(double v)
        {
            return (v < 0.0 ? "-" : "+") + Math.Abs(v).ToString("F1", CultureInfo.InvariantCulture);
        }

        private static string Inv(long v) { return v.ToString(CultureInfo.InvariantCulture); }
        private static string Inv(int v) { return v.ToString(CultureInfo.InvariantCulture); }

        /// <summary>A possibly-None string formatted with str.format: None -> 'None'.</summary>
        private static string Str(string s) { return s ?? "None"; }

        /// <summary>x or '(not set)'.</summary>
        private static string OrNotSet(string s) { return string.IsNullOrEmpty(s) ? "(not set)" : s; }

        /// <summary>settings.get(key, dflt): the dictionary's own value, no FhaCore defaults.</summary>
        private static string SGet(IDictionary<string, string> d, string key, string dflt)
        {
            string v;
            if (d != null && d.TryGetValue(key, out v) && v != null) return v;
            return dflt;
        }

        /// <summary>Python repr of a unicode string in a list (IronPython 2: u'...').</summary>
        private static string ReprStr(string s) { return s == null ? "None" : "u'" + s + "'"; }
        private static string ReprList(IEnumerable<string> items) { return "[" + string.Join(", ", items.Select(ReprStr)) + "]"; }

        /// <summary>sorted(set(items)) of strings, by code point.</summary>
        private static List<string> SortedDistinct(IEnumerable<string> items)
        {
            var l = items.Distinct(StringComparer.Ordinal).ToList();
            l.Sort(StringComparer.Ordinal);
            return l;
        }

        /// <summary>'support' on the Family Floor Support tab, 'hanger' on Family Hangers.</summary>
        public static string Noun(FamConfig cfg)
        {
            return HfamRevit.IsFloor(cfg) ? "support" : "hanger";
        }

        public static string Title(FamConfig cfg)
        {
            return HfamRevit.IsFloor(cfg) ? "circular floor support" : "circular hanger";
        }

        /// <summary>str.capitalize(): first character upper case, the rest lower case.</summary>
        private static string Capitalize(string s)
        {
            if (string.IsNullOrEmpty(s)) return s;
            return s.Substring(0, 1).ToUpperInvariant() + s.Substring(1).ToLowerInvariant();
        }

        // ============================================================ the ring
        /// <summary>A round face's radius, or null (the Python tried get_Radius(0) then Radius[0]; C# has the first only).</summary>
        private static double? RadiusOf(CylindricalFace face)
        {
            try
            {
                return face.get_Radius(0).GetLength();
            }
            catch (Exception) { }
            return null;
        }

        private static void WalkRings(IEnumerable<GeometryObject> geo, List<RingCandidate> output)
        {
            foreach (GeometryObject g in geo)
            {
                GeometryInstance gi = g as GeometryInstance;
                Solid solid = g as Solid;
                Arc arcLine = g as Arc;
                if (gi != null)
                {
                    try
                    {
                        WalkRings(gi.GetInstanceGeometry(), output);
                    }
                    catch (Exception) { }
                }
                else if (solid != null)
                {
                    try
                    {
                        foreach (Face f in solid.Faces)
                        {
                            CylindricalFace cf = f as CylindricalFace;
                            if (cf != null)
                            {
                                double? r = RadiusOf(cf);
                                if (r != null && r.Value != 0.0)   // Python: if r:
                                {
                                    XYZ a = cf.Axis;
                                    output.Add(new RingCandidate(r.Value, Pt(cf.Origin), new V3(a.X, a.Y, a.Z), "round face"));
                                }
                            }
                        }
                    }
                    catch (Exception) { }
                    try
                    {
                        foreach (Edge ed in solid.Edges)
                        {
                            Arc c = ed.AsCurve() as Arc;
                            if (c != null)
                            {
                                XYZ n = c.Normal;
                                output.Add(new RingCandidate(c.Radius, Pt(c.Center), new V3(n.X, n.Y, n.Z), "arc"));
                            }
                        }
                    }
                    catch (Exception) { }
                }
                else if (arcLine != null)
                {
                    try
                    {
                        XYZ n = arcLine.Normal;
                        output.Add(new RingCandidate(arcLine.Radius, Pt(arcLine.Center), new V3(n.X, n.Y, n.Z), "arc line"));
                    }
                    catch (Exception) { }
                }
            }
        }

        /// <summary>(radius, centre, axis, kind) for every round face and arc of the placed support.</summary>
        public static List<RingCandidate> RingCandidates(Element inst)
        {
            Options opt = new Options();
            opt.ComputeReferences = false;
            try
            {
                opt.DetailLevel = ViewDetailLevel.Fine;
            }
            catch (Exception) { }
            var output = new List<RingCandidate>();
            try
            {
                GeometryElement geo = inst.get_Geometry(opt);
                if (geo != null)
                    WalkRings(geo, output);
            }
            catch (Exception) { }
            return output;
        }

        /// <summary>Regenerate, then find the ring in the placed support (HcircCore.PickRing); null when there is none.</summary>
        public static RingMeasure MeasureRing(Document doc, Element inst, double dia, V3 q, V3 along)
        {
            try
            {
                doc.Regenerate();
            }
            catch (Exception) { }
            return HcircCore.PickRing(RingCandidates(inst), dia / 2.0, q, along);
        }

        /// <summary>The instance's location point, or null.</summary>
        public static V3? BasePoint(Element inst)
        {
            try
            {
                return Pt(((LocationPoint)inst.Location).Point);
            }
            catch (Exception) { return null; }
        }

        // ============================================================ fitting
        /// <summary>Where a ring support's base stands on the picked element: straight below the service centre
        /// (its single post), else its level.</summary>
        public static double CircStand(HfamRevit.BaseSurface baseEl, V3 q, double zBot, Level level, List<string> problems, FhaDebugLog log)
        {
            HfamRevit.StandResult sr = baseEl.Stand(q, zBot, new List<V3> { new V3(q.X, q.Y, 0.0) });
            double? z = sr.Z;
            if (z == null)
            {
                problems.Add("the picked base is not under every support - those stand on the level");
                log.Add("   base: " + baseEl.Label() + " is not under it - standing on the level");
                return level.ProjectElevation;
            }
            log.Add("   base: stands at " + Fmm(z) + " on " + baseEl.Label() + " (" + sr.How + ")");
            if (z.Value > zBot + Tol)
            {
                problems.Add("the picked base is above the service there - that support stands on the level");
                return level.ProjectElevation;
            }
            return z.Value;
        }

        private static double Acos(double c)
        {
            return Math.Acos(Math.Max(-1.0, Math.Min(1.0, c)));
        }

        /// <summary>Turn, lift and size one ring support, the ring centre at the service centre, then check where the
        /// ring went. Caller holds the transaction. Returns a list of problems.</summary>
        public static List<string> FitCirc(Document doc, FamilyInstance inst, Section sec, V3 q, Level level, FamConfig cfg,
                                           FhaDebugLog log, HfamRevit.BaseSurface baseEl = null)
        {
            var problems = new List<string>();
            V3 along, across;
            HfamCore.PlanDirs(sec.A, sec.B, out along, out across);
            string runAxis = cfg.Get("circ_axis", "X");
            double? ang = HfamRevit.AlignRotation(doc, inst, HcircCore.CircXDir(runAxis, along, across));
            double zBot = q.Z - sec.Depth / 2.0;
            log.Add("   level " + ElName(level) + " @ " + Fmm(level.ProjectElevation) + " | service centre here " + Fmm(q.Z) + ", underside "
                    + Fmm(zBot) + " | runs along the family " + runAxis + " | turned "
                    + (ang != null ? Fm(ang.Value * 57.29577951, 1) : "? (rotation failed)") + " deg");
            double stand = level.ProjectElevation;
            Parameter p = HfamRevit.OffsetParam(inst);
            if (baseEl != null && p != null)
                stand = CircStand(baseEl, q, zBot, level, problems, log);
            else if (baseEl != null)
                problems.Add("no writable offset parameter - the support could not be lifted onto the picked element");
            double baseOff = stand - level.ProjectElevation;
            if (p == null)
            {
                log.Add("   offset: no writable Elevation from Level / Offset from Host");
            }
            else
            {
                p.Set(baseOff);
                log.Add("   offset: " + p.Definition.Name + " = " + Fmm(baseOff) + (Math.Abs(baseOff) < Tol ? " (stands on the level)"
                        : " (stands on the picked element, hosted on the level)"));
            }
            double dia = sec.Width;
            if (q.Z < stand - Tol)
                problems.Add("the service is below what the support stands on");
            double height = HcircCore.SupportHeight(q.Z, stand);
            sec.SetDia = dia;
            bool okDia = HfamRevit.SetLength(inst, cfg.Get("dia", null), dia);
            log.Add("   diameter: " + OrNotSet(cfg.Get("dia", null)) + " = " + Fmm(dia) + (okDia ? "" : "  <- NOT SET"));
            if (!okDia)
                problems.Add("diameter parameter \"" + OrNotSet(cfg.Get("dia", null)) + "\" not found or read only - set it in Family settings");
            string hname = cfg.Get("circ_height", null);
            bool okH = HfamRevit.SetLength(inst, hname, height);
            log.Add("   support height: " + OrNotSet(hname) + " = " + Fmm(height) + " (base " + Fmm(stand) + " up to the service centre here "
                    + Fmm(q.Z) + ")" + (okH ? "" : "  <- NOT SET"));
            sec.SetHeight = height;
            if (!okH)
            {
                problems.Add("support height parameter \"" + OrNotSet(hname) + "\" not found or read only - set it in Family settings");
                return problems;
            }
            V3? bp = BasePoint(inst);
            if (bp != null)
                log.Add("   placed: base point " + Fpt(bp) + " (wanted " + Fmm(stand) + " on " + ElName(level) + ")");
            // ---- check: where did the ring end up? (reported, never corrected)
            RingMeasure m = MeasureRing(doc, inst, dia, q, along);
            if (m == null)
            {
                log.Add("   ring check: no round face or arc of about " + Fmm(dia / 2.0) + " radius found in the family - not checked");
                return problems;
            }
            double off = HcircCore.RingOff(m.Z, q.Z);
            log.Add("   ring check: " + m.Kind + ", radius " + Fmm(m.R) + ", centre at " + Fmm(m.Z) + " (" + FmSigned1(off * MM)
                    + " mm off the service centre) | " + Fm(m.Off * MM, 1) + " mm off the centreline in plan | the service runs "
                    + (m.Along > 0.9 ? "straight" : "at " + Fm(57.29577951 * Acos(m.Along), 0) + " deg") + " through it");
            if (Math.Abs(off) > HcircCore.CentreOkMm / MM)
                problems.Add("the ring came out " + Fm(Math.Abs(off) * MM, 0) + " mm " + (off > 0 ? "above" : "below")
                             + " the service centre - check that \"" + Str(hname) + "\" runs from the family's reference level to the ring centre");
            if (m.Along < 0.7)
                problems.Add("the ring faces across the service - switch \"The service runs along\" (X / Y) in Family settings");
            return problems;
        }

        /// <summary>A circular hanger: its reference on the service centreline (the centre where it hangs) on the
        /// service's level, turned to the X / Y set, the diameter parameter set, the drop rod from the centre up to
        /// the soffit. Then the ring check. Caller holds the transaction.</summary>
        public static List<string> FitCircHanger(Document doc, FamilyInstance inst, Section sec, V3 q, Level level, FamConfig cfg, bool rod,
                                                 HfamRevit.SoffitFinder finder, FhaDebugLog log)
        {
            var problems = new List<string>();
            V3 along, across;
            HfamCore.PlanDirs(sec.A, sec.B, out along, out across);
            string runAxis = cfg.Get("circ_axis", "X");
            double? ang = HfamRevit.AlignRotation(doc, inst, HcircCore.CircXDir(runAxis, along, across));
            double zBot = q.Z - sec.Depth / 2.0;
            log.Add("   level " + ElName(level) + " @ " + Fmm(level.ProjectElevation) + " | service centre here " + Fmm(q.Z) + ", invert "
                    + Fmm(zBot) + " | runs along the family " + runAxis + " | turned "
                    + (ang != null ? Fm(ang.Value * 57.29577951, 1) : "? (rotation failed)") + " deg");
            Parameter p = HfamRevit.OffsetParam(inst);
            double baseOff = HcircCore.HangerOffset(q.Z, level.ProjectElevation);
            if (p == null)
            {
                problems.Add("no writable offset / elevation parameter");
                log.Add("   offset: no writable Elevation from Level / Offset from Host");
            }
            else
            {
                p.Set(baseOff);
                log.Add("   offset: " + p.Definition.Name + " = " + Fmm(baseOff) + " (the service centreline)");
            }
            double dia = sec.Width;
            sec.SetDia = dia;
            bool okDia = HfamRevit.SetLength(inst, cfg.Get("dia", null), dia);
            log.Add("   diameter: " + OrNotSet(cfg.Get("dia", null)) + " = " + Fmm(dia) + (okDia ? "" : "  <- NOT SET"));
            if (!okDia)
                problems.Add("diameter parameter \"" + OrNotSet(cfg.Get("dia", null)) + "\" not found or read only - set it in Family settings");
            if (rod)   // from the hanger's reference (the centreline) up
            {
                double? top = finder.Above(cfg.Get("soffit", "level"), q.X, q.Y, q.Z);
                double? len = HfamCore.RodLength(q.Z, top);
                if (len == null)
                {
                    problems.Add("no level / soffit above the hanger for the drop rod");
                    log.Add("   rod: nothing above " + Fmm(q.Z) + " (" + Str(cfg.Get("soffit", null)) + ")");
                }
                else
                {
                    bool ok = HfamRevit.SetLength(inst, cfg.Get("rod", null), len.Value);
                    log.Add("   rod: " + Str(cfg.Get("rod", null)) + " = " + Fmm(len) + " (soffit " + Fmm(top) + " by " + Str(cfg.Get("soffit", null)) + ")"
                            + (ok ? "" : "  <- NOT SET"));
                    if (!ok)
                        problems.Add("drop rod parameter \"" + Str(cfg.Get("rod", null)) + "\" not found");
                }
            }
            // ---- check: where did the ring end up? (reported, never corrected)
            RingMeasure m = MeasureRing(doc, inst, dia, q, along);
            if (m == null)
            {
                log.Add("   ring check: no round face or arc of about " + Fmm(dia / 2.0) + " radius found in the family - not checked");
                return problems;
            }
            double off = HcircCore.RingOff(m.Z, q.Z);
            log.Add("   ring check: " + m.Kind + ", radius " + Fmm(m.R) + ", centre at " + Fmm(m.Z) + " (" + FmSigned1(off * MM)
                    + " mm off the service centre) | " + Fm(m.Off * MM, 1) + " mm off the centreline in plan");
            if (Math.Abs(off) > HcircCore.CentreOkMm / MM)
                problems.Add("the ring came out " + Fm(Math.Abs(off) * MM, 0) + " mm " + (off > 0 ? "above" : "below")
                             + " the service centre - the hanger is placed with its reference on the service centreline, so check that the family's "
                             + "reference level runs through the ring centre");
            if (m.Along < 0.7)
                problems.Add("the ring faces across the service - switch \"The service runs along\" (X / Y) in Family settings");
            return problems;
        }

        /// <summary>Create one ring support / hanger at centreline point q. Caller holds the transaction.
        /// Returns (instance, problems) as the HfamRevit.PlaceOutcome pair.</summary>
        public static HfamRevit.PlaceOutcome PlaceCirc(Document doc, FamilySymbol symbol, Element service, Section sec, V3 q, FamConfig cfg,
                                                       FhaDebugLog log, FhaRevit.Worksets ws = null, HfamRevit.BaseSurface baseEl = null,
                                                       bool rod = false, HfamRevit.SoffitFinder finder = null)
        {
            bool floor = HfamRevit.IsFloor(cfg);
            Level level;
            if (floor)
                level = HfamRevit.FloorLevel(doc, service, q.Z - sec.Depth / 2.0, log);
            else
                level = HfamRevit.ElementLevel(doc, service, q.Z);
            if (level == null)
                return new HfamRevit.PlaceOutcome { Inst = null, Problems = new List<string> { "the service has no level" } };
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
            V3 wantX = HcircCore.CircXDir(cfg.Get("circ_axis", "X"), along, across);
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
                    return new HfamRevit.PlaceOutcome { Inst = null, Problems = new List<string> { "Revit refused to place " + ElName(symbol) + ": " + ex.Message } };
                }
            }
            doc.Regenerate();
            if (ws != null)
                ws.Apply(inst, service, true);
            else
                FhaRevit.MatchWorkset(inst, service);
            log.Add("+ " + Title(cfg) + " " + Inv(Eid(inst.Id)) + " on " + Describe(service) + " at " + Fpt(q) + " ("
                    + (placement.Length > 0 ? placement : "?") + ")");
            HfamRevit.LogSection(log, sec);
            FhaRevit.WriteServiceComment(inst, new List<Element> { service }, log);
            if (!floor)
                return new HfamRevit.PlaceOutcome { Inst = inst, Problems = FitCircHanger(doc, inst, sec, q, level, cfg, rod, finder, log) };
            return new HfamRevit.PlaceOutcome { Inst = inst, Problems = FitCirc(doc, inst, sec, q, level, cfg, log, baseEl) };
        }

        /// <summary>Slide a ring support sideways onto the service centreline (never along the run), then refit it.
        /// Caller holds the transaction.</summary>
        public static List<string> RealignCirc(Document doc, FamilyInstance inst, Element service, Section sec, FamConfig cfg, FhaDebugLog log,
                                               FhaRevit.Worksets ws = null, HfamRevit.BaseSurface baseEl = null, bool rod = false,
                                               HfamRevit.SoffitFinder finder = null)
        {
            V3? pn = HfamRevit.InstancePoint(inst);
            if (pn == null)
                return new List<string> { "the support has no location point" };
            V3 p = pn.Value;
            V3 q = HfamCore.OnLine(sec.A, sec.B, p);
            log.Add("~ " + Title(cfg) + " " + Inv(Eid(inst.Id)) + " at " + Fpt(p) + " -> " + Fpt(q) + " | sideways "
                    + Fmm(HfamCore.PlanOffset(sec.A, sec.B, p)) + " mm | on " + Describe(service));
            HfamRevit.LogSection(log, sec);
            try
            {
                ElementTransformUtils.MoveElement(doc, inst.Id, new XYZ(q.X - p.X, q.Y - p.Y, 0.0));
            }
            catch (Exception ex)
            {
                return new List<string> { "could not move it: " + ex.Message };
            }
            Level want;
            if (HfamRevit.IsFloor(cfg))
                want = HfamRevit.FloorLevel(doc, service, q.Z - sec.Depth / 2.0, log);
            else
                want = HfamRevit.ElementLevel(doc, service, q.Z);
            Level level = HfamRevit.ElementLevel(doc, inst, p.Z);
            var problems = new List<string>();
            if (want != null && (level == null || Eid(level.Id) != Eid(want.Id)))
            {
                if (HfamRevit.SetLevel(inst, want))
                {
                    log.Add("   level " + (level != null ? ElName(level) : "?") + " -> " + ElName(want));
                    level = want;
                }
                else
                    problems.Add("kept its own level (level is not editable on this family)");
            }
            if (ws != null)
                ws.Apply(inst, service, false);
            doc.Regenerate();
            if (level == null)
            {
                problems.Add("no level");
                return problems;
            }
            if (!HfamRevit.IsFloor(cfg))
            {
                problems.AddRange(FitCircHanger(doc, inst, sec, q, level, cfg, rod, finder, log));
                return problems;
            }
            problems.AddRange(FitCirc(doc, inst, sec, q, level, cfg, log, baseEl));
            return problems;
        }

        /// <summary>Read back after commit: the diameter must hold the service's.</summary>
        public static bool VerifyCirc(Element inst, FamConfig cfg, Section sec, List<string> problems)
        {
            try
            {
                if (!inst.IsValidObject) return false;
            }
            catch (Exception) { return false; }
            double? v = HfamRevit.GetLength(inst, cfg.Get("dia", null));
            if (v != null && sec.SetDia != null && Math.Abs(v.Value - sec.SetDia.Value) > Tol)
                problems.Add(Str(cfg.Get("dia", null)) + " reads " + Fm(v.Value * MM, 0) + " mm, not " + Fm(sec.SetDia.Value * MM, 0) + " mm");
            return true;
        }

        /// <summary>(symbol, cfg) - cfg.Mode says which tab: 'floor' or 'hang'. (Python _chosen = hr._chosen.)</summary>
        private static FamilySymbol Chosen(UIDocument uidoc, FhaSettings settings, JobResult res, out FamConfig cfg)
        {
            return HfamRevit.Chosen(uidoc, settings, res, out cfg);
        }

        /// <summary>(rod ticked, SoffitFinder) for a hanger job; (False, None) for supports. Python _rod.</summary>
        private static bool RodOf(FhaSettings settings, string key, FamConfig cfg, FhaDebugLog log, Document doc, out HfamRevit.SoffitFinder finder)
        {
            bool rod = FhaCore.AsBool(settings, key) && !HfamRevit.IsFloor(cfg);
            finder = rod ? new HfamRevit.SoffitFinder(doc, settings, log, rod && cfg.Get("soffit", null) == "structure") : null;
            return rod;
        }

        private static void Close(HfamRevit.SoffitFinder finder)
        {
            if (finder != null)
                finder.Close();
        }

        /// <summary>The fitted section of a pipe / round duct, or null for anything else.</summary>
        private static Section RoundSection(Element el, bool outside)
        {
            if (!HfamRevit.IsHostDuct(el))
                return null;
            Section sec = HfamRevit.Fitted(el, outside);
            return sec.Round ? sec : null;
        }
    }
}
