using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        // ============================================================= locks
        public static readonly string[] PlanTypes = { "FloorPlan", "CeilingPlan", "EngineeringPlan" };

        /// <summary>(lines, planar faces) of an element with references (centreline included).</summary>
        public class GeoItemsResult
        {
            public List<Line> Lines = new List<Line>();
            public List<PlanarFace> Faces = new List<PlanarFace>();
        }

        public static GeoItemsResult GeoItems(Element el, View view)
        {
            var res = new GeoItemsResult();
            Options opt = new Options();
            opt.ComputeReferences = true;
            opt.IncludeNonVisibleObjects = true;
            if (view != null) opt.View = view;
            try
            {
                GeometryElement geo = el.get_Geometry(opt);
                if (geo != null) GeoWalk(geo, res);
            }
            catch (Exception) { }
            return res;
        }

        private static void GeoWalk(IEnumerable<GeometryObject> geo, GeoItemsResult res)
        {
            foreach (GeometryObject g in geo)
            {
                GeometryInstance gi = g as GeometryInstance;
                Solid so = g as Solid;
                Line ln = g as Line;
                if (gi != null)
                    GeoWalk(gi.GetInstanceGeometry(), res);
                else if (so != null)
                {
                    foreach (Face f in so.Faces)
                    {
                        PlanarFace pf = f as PlanarFace;
                        if (pf != null && pf.Reference != null) res.Faces.Add(pf);
                    }
                }
                else if (ln != null)
                {
                    try
                    {
                        if (ln.Reference != null) res.Lines.Add(ln);
                    }
                    catch (Exception) { }
                }
            }
        }

        /// <summary>'duct', 'pipe', ... for services; the category name for anything else.</summary>
        public static string HostKind(Element el)
        {
            if (IsRvtDuct(el) || el is FabricationPart) return ServiceKind(el);
            try { return el.Category.Name.ToLowerInvariant(); }
            catch (Exception) { return "element"; }
        }

        public static string LockSectionName(Element host)
        {
            return "Hanger Automation - bottom locks " + HostKind(host) + " " + Inv(Eid(host.Id));
        }

        /// <summary>A bottom-lock section made on an earlier run (exact name, else its
        /// first '(n)' copy), so each service keeps one.</summary>
        public static ViewSection FindLockSection(Document doc, string name)
        {
            ViewSection best = null;
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ViewSection)))
                {
                    ViewSection v = (ViewSection)e;
                    try
                    {
                        if (v.IsTemplate) continue;
                    }
                    catch (Exception) { }
                    string nm = ElName(v);
                    if (nm == name) return v;
                    if (best == null && nm.StartsWith(name + " (", StringComparison.Ordinal)) best = v;
                }
            }
            catch (Exception) { }
            return best;
        }

        /// <summary>A section along the service that holds its hangers' bottom locks
        /// (a lock on a horizontal face lives in a section / elevation view and is
        /// deleted with it). Reuses the one made on an earlier run.</summary>
        public static ViewSection MakeLockSection(Document doc, Element service, Section sec, FhaDebugLog log)
        {
            string baseName = LockSectionName(service);
            ViewSection old = FindLockSection(doc, baseName);
            if (old != null)
            {
                log.Add("   lock section: reusing " + ElName(old));
                return old;
            }
            ViewFamilyType vft = null;
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)))
            {
                ViewFamilyType v = (ViewFamilyType)e;
                if (v.ViewFamily == ViewFamily.Section)
                {
                    vft = v;
                    break;
                }
            }
            if (vft == null) return null;
            V3 along, across;
            HfamCore.PlanDirs(sec.A, sec.B, out along, out across);
            double L = FhaCore.VLen(FhaCore.VSub(sec.B, sec.A));
            V3 mid = FhaCore.VScale(FhaCore.VAdd(sec.A, sec.B), 0.5);
            Transform tf = Transform.Identity;
            tf.Origin = ToXyz(mid);
            tf.BasisX = new XYZ(along.X, along.Y, 0.0);
            tf.BasisY = XYZ.BasisZ;
            tf.BasisZ = new XYZ(along.Y, -along.X, 0.0);
            BoundingBoxXYZ box = new BoundingBoxXYZ();
            box.Transform = tf;
            double half = L / 2.0 + 1.0;
            box.Min = new XYZ(-half, -(sec.Depth / 2.0 + 3.0), -(sec.Width / 2.0 + 2.0));
            box.Max = new XYZ(half, sec.Depth / 2.0 + 8.0, sec.Width / 2.0 + 2.0);
            ViewSection view = ViewSection.CreateSection(doc, vft.Id, box);
            for (int n = 0; n < 20; n++)
            {
                try
                {
                    view.Name = n == 0 ? baseName : baseName + " (" + Inv(n) + ")";
                    break;
                }
                catch (Exception) { continue; }
            }
            try { doc.Regenerate(); }   // so the new view has geometry to take references from
            catch (Exception) { }
            log.Add("   lock section: " + ElName(view));
            return view;
        }

        public static readonly string[] RefTypes =
        {
            "CenterLeftRight", "CenterFrontBack", "CenterElevation", "Left", "Right", "Front", "Back",
            "Top", "Bottom", "StrongReference", "WeakReference",
        };

        public static readonly Dictionary<string, string> RefLabels = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "CenterLeftRight", "Center (Left/Right)" }, { "CenterFrontBack", "Center (Front/Back)" },
            { "CenterElevation", "Center (Elevation)" }, { "StrongReference", "Strong Reference" },
            { "WeakReference", "Weak Reference" },
        };

        /// <summary>A reference and its label (the Python (reference, label) pairs).</summary>
        public class RefItem
        {
            public Reference Ref;
            public string Label;
            public RefItem() { }
            public RefItem(Reference r, string label) { Ref = r; Label = label; }
        }

        /// <summary>[(reference, label)] of a family instance's reference planes of these
        /// FamilyInstanceReferenceTypes, in that order.</summary>
        public static List<RefItem> InstanceRefs(Element inst, IEnumerable<string> kinds)
        {
            var o = new List<RefItem>();
            foreach (string k in kinds)
            {
                FamilyInstanceReferenceType e;
                if (!Enum.TryParse<FamilyInstanceReferenceType>(k, out e) || !Enum.IsDefined(typeof(FamilyInstanceReferenceType), e)) continue;
                IList<Reference> refs;
                try { refs = ((FamilyInstance)inst).GetReferences(e); }
                catch (Exception) { refs = null; }
                if (refs == null) continue;
                foreach (Reference r in refs)
                {
                    string nm = "";
                    try { nm = ((FamilyInstance)inst).GetReferenceName(r) ?? ""; }
                    catch (Exception) { }
                    string lbl;
                    if (!RefLabels.TryGetValue(k, out lbl)) lbl = k;
                    o.Add(new RefItem(r, lbl + (nm.Length > 0 ? " \"" + nm + "\"" : "")));
                }
            }
            return o;
        }

        /// <summary>'Center (Left/Right) "CL", Strong Reference x2 ...' - what the family offers.</summary>
        public static string FamilyReferenceSummary(Element inst)
        {
            var parts = new List<string>();
            foreach (string k in RefTypes)
            {
                List<RefItem> got = InstanceRefs(inst, new[] { k });
                if (got.Count > 0)
                    parts.Add(string.Join(", ", got.Select(g => g.Label)));
            }
            string s = string.Join("; ", parts);
            return s.Length > 0 ? s : "none (every reference plane is Not a Reference)";
        }

        /// <summary>A planar face with its origin z and normal z, in model coordinates (Python (face, z, nz)).</summary>
        public class FaceZ
        {
            public PlanarFace Face;
            public double Z, Nz;
        }

        /// <summary>Planar faces with references and edge points of a geometry tree, in
        /// model coordinates: (face, origin z, normal z).</summary>
        public static void WalkFaces(IEnumerable<GeometryObject> geo, List<FaceZ> faces, List<V3> pts)
        {
            foreach (GeometryObject g in geo)
            {
                GeometryInstance gi = g as GeometryInstance;
                Solid so = g as Solid;
                if (gi != null)
                {
                    try { WalkFaces(gi.GetInstanceGeometry(), faces, pts); }
                    catch (Exception) { }
                }
                else if (so != null)
                {
                    try
                    {
                        foreach (Face f in so.Faces)
                        {
                            PlanarFace pf = f as PlanarFace;
                            if (pf != null && pf.Reference != null)
                                faces.Add(new FaceZ { Face = pf, Z = pf.Origin.Z, Nz = pf.FaceNormal.Z });
                        }
                    }
                    catch (Exception) { }
                    if (pts != null)
                    {
                        try
                        {
                            foreach (Edge ed in so.Edges)
                                foreach (XYZ p in ed.Tessellate())
                                    pts.Add(new V3(p.X, p.Y, p.Z));
                        }
                        catch (Exception) { }
                    }
                }
            }
        }

        public static List<FaceZ> ElementFaces(Element el, View view = null, List<V3> pts = null)
        {
            Options opt = new Options();
            opt.ComputeReferences = true;
            opt.IncludeNonVisibleObjects = false;
            if (view != null)
                opt.View = view;
            else
            {
                try { opt.DetailLevel = ViewDetailLevel.Fine; }
                catch (Exception) { }
            }
            var faces = new List<FaceZ>();
            try
            {
                GeometryElement geo = el.get_Geometry(opt);
                if (geo != null) WalkFaces(geo, faces, pts);
            }
            catch (Exception) { }
            return faces;
        }

        /// <summary>The (target label, candidate label) pair try_align reports for the alignment Revit accepted.</summary>
        public class AlignHit
        {
            public string TargetLabel, CandidateLabel;
        }

        /// <summary>NewAlignment for the first (target, candidate) pair Revit accepts.
        /// Revit only aligns references that already coincide, so a wrong pair is
        /// simply refused. Returns the pair or null; err = the last refusal (null if none).</summary>
        public static AlignHit TryAlign(Document doc, View view, List<RefItem> targets, List<RefItem> candidates, FhaDebugLog log, int maxTries, out string err)
        {
            int n = 0;
            string last = null;
            foreach (RefItem t in targets)
            {
                foreach (RefItem c in candidates)
                {
                    n++;
                    if (n > maxTries)
                    {
                        err = last;
                        return null;
                    }
                    try
                    {
                        doc.Create.NewAlignment(view, t.Ref, c.Ref);
                        err = null;
                        return new AlignHit { TargetLabel = t.Label, CandidateLabel = c.Label };
                    }
                    catch (Exception ex)
                    {
                        last = ex.Message;
                    }
                }
            }
            err = last;
            return null;
        }

        private static bool Alive(Element el)
        {
            try { return el == null || el.IsValidObject; }
            catch (Exception) { return true; }
        }

        /// <summary>Align-locks a hanger to what it carries.
        ///
        /// Services: the hanger's centre plane along the run to the service centreline
        /// (plan view), and its face / plane at the invert to the service's bottom
        /// face - or its insulation's, when the hanger sits outside it (in a section
        /// kept per service). Units (equipment, duct accessories): to the unit's
        /// centre planes and bottom face. Single services only; shared hangers are
        /// never locked. Every reference the family offers is tried, so a family
        /// whose centre plane is a Strong / Weak reference still locks.</summary>
        public class Locker
        {
            public Document Doc;
            public FhaDebugLog Log;
            public View Plan;
            public Dictionary<long, ViewSection> Sections = new Dictionary<long, ViewSection>();
            public HashSet<long?> Told = new HashSet<long?>();

            public Locker(Document doc, View view, FhaDebugLog log)
            {
                Doc = doc; Log = log;
                Plan = (view != null && Array.IndexOf(PlanTypes, view.ViewType.ToString()) >= 0) ? view : null;
            }

            private ViewSection SectionFor(Element service, Section sec)
            {
                long key = Eid(service.Id);
                if (Sections.ContainsKey(key) && !Alive(Sections[key]))
                    Sections.Remove(key);   // made in a placement Revit then undid: make it again
                if (!Sections.ContainsKey(key))
                {
                    try
                    {
                        Sections[key] = MakeLockSection(Doc, service, sec, Log);
                    }
                    catch (Exception ex)
                    {
                        Log.Add("   lock section: " + ex.Message);
                        Sections[key] = null;
                    }
                }
                return Sections[key];
            }

            private void TellFamily(FamilyInstance inst)
            {
                long? key;
                try { key = Eid(inst.Symbol.Family.Id); }
                catch (Exception) { key = null; }
                if (Told.Contains(key)) return;
                Told.Add(key);
                Log.Add("   family reference planes: " + FamilyReferenceSummary(inst));
            }

            /// <summary>Lock one hanger to its service (or unit); returns the notes for whatever could not be locked.</summary>
            public List<string> Lock(FamilyInstance inst, Element host, Section sec, V3 q)
            {
                var notes = new List<string>();
                TellFamily(inst);
                V3 along, across;
                HfamCore.PlanDirs(sec.A, sec.B, out along, out across);
                bool unit = sec.Unit;
                string what = HostKind(host);
                // ---- centre: hanger plane along the run <-> service centreline / unit centre plane
                XYZ h = inst.HandOrientation, f = inst.FacingOrientation;
                string square = HfamCore.ReferenceTypeAcross(new V3(h.X, h.Y, 0.0), new V3(f.X, f.Y, 0.0), along);
                string alongType = square == "CenterLeftRight" ? "CenterFrontBack" : "CenterLeftRight";
                if (Plan == null)
                    notes.Add("centre lock needs a plan view open");
                else
                {
                    List<RefItem> cands = InstanceRefs(inst, new[] { alongType, square, "StrongReference", "WeakReference",
                                                                       "Left", "Right", "Front", "Back" });
                    List<RefItem> targets;
                    if (unit)
                        targets = InstanceRefs(host, new[] { "CenterLeftRight", "CenterFrontBack", "StrongReference", "WeakReference" });
                    else
                    {
                        GeoItemsResult gi = GeoItems(host, Plan);
                        targets = new List<RefItem>();
                        foreach (Line ln in gi.Lines)
                        {
                            try
                            {
                                XYZ d = ln.Direction;
                                if (Math.Abs(d.X * along.X + d.Y * along.Y) > 0.999)
                                    targets.Add(new RefItem(ln.Reference, "centreline"));
                            }
                            catch (Exception) { }
                        }
                    }
                    if (targets.Count == 0)
                        notes.Add(!unit ? "no centreline reference on the " + what : "the " + what + " family has no centre reference planes");
                    else if (cands.Count == 0)
                        notes.Add("the hanger family has no reference planes to lock with - in the family editor set the centre plane that runs along the "
                                  + what + " to Is Reference: " + RefLabels[alongType]);
                    else
                    {
                        string err;
                        AlignHit hit = TryAlign(Doc, Plan, targets, cands, Log, 80, out err);
                        if (hit != null)
                            Log.Add("   locked to the " + (unit ? "unit centre" : "centreline") + ": hanger " + hit.CandidateLabel + " <-> " + hit.TargetLabel);
                        else if (unit)
                            notes.Add("the hanger is centred on the " + what + "'s geometry, which is off its centre reference planes - no centre lock");
                        else
                            notes.Add("no reference plane of the hanger lies on the " + what + " centreline (" + Inv(cands.Count) + " tried) - in the "
                                      + "family editor set the centre plane that runs along the " + what + " to Is Reference: "
                                      + RefLabels[alongType] + (!string.IsNullOrEmpty(err) ? " (last refusal: " + err + ")" : ""));
                    }
                }
                // ---- bottom: hanger at the invert <-> service / insulation / unit bottom face
                if (sec.Round)
                {
                    Log.Add("   round " + what + ": centre lock only (no flat bottom face)");
                    return notes;
                }
                double zInv = q.Z - sec.Depth / 2.0;
                var owners = new List<Element> { host };
                if (sec.InsUsed)
                {
                    try
                    {
                        var ins = InsulationLiningBase.GetInsulationIds(Doc, host.Id).Select(i => Doc.GetElement(i)).ToList();
                        if (ins.Count > 0) owners = ins;
                    }
                    catch (Exception) { }
                }
                var downs = new List<FaceZ>();
                foreach (Element el in owners)
                    downs.AddRange(ElementFaces(el).Where(fz => fz.Nz < -0.99));
                if (downs.Count == 0)
                {
                    notes.Add("no flat bottom face found on the " + what);
                    return notes;
                }
                double zLow = downs.Min(fz => fz.Z);
                var bottoms = downs.Where(fz => Math.Abs(fz.Z - zLow) < 2.0 / MM)
                                   .Select(fz => new RefItem(fz.Face.Reference, "bottom face at " + Fmm(fz.Z))).ToList();
                if (unit)
                    bottoms.AddRange(InstanceRefs(host, new[] { "Bottom" }));
                ViewSection view = SectionFor(host, sec);
                if (view == null)
                {
                    notes.Add("no section view type for the bottom lock");
                    return notes;
                }
                List<FaceZ> hfaces = ElementFaces(inst, view);
                if (hfaces.Count == 0) hfaces = ElementFaces(inst);
                var flats = hfaces.Where(fz => Math.Abs(fz.Nz) > 0.99 && Math.Abs(fz.Z - zInv) < 2.0 / MM)
                                  .Select((fz, i) => new { fz, i }).OrderBy(z => -z.fz.Nz).ThenBy(z => z.i).Select(z => z.fz).ToList();   // the upward face (bearer top) first
                var cands2 = flats.Select(fz => new RefItem(fz.Face.Reference, "face at " + Fmm(fz.Z))).ToList();
                cands2.AddRange(InstanceRefs(inst, new[] { "Bottom", "Top", "CenterElevation", "StrongReference", "WeakReference" }));
                if (cands2.Count == 0)
                {
                    string heights = FlatHeights(hfaces);
                    notes.Add("no face or reference plane of the hanger at the invert " + Fmm(zInv) + " (its flat faces are at "
                              + (heights.Length > 0 ? heights : "-") + ")");
                    return notes;
                }
                string err2;
                AlignHit hit2 = TryAlign(Doc, view, bottoms, cands2, Log, 80, out err2);
                if (hit2 != null)
                    Log.Add("   locked to the bottom: hanger " + hit2.CandidateLabel + " <-> " + what + " " + hit2.TargetLabel);
                else
                {
                    string heights = FlatHeights(hfaces);
                    notes.Add("bottom lock refused - the hanger has nothing exactly at the invert " + Fmm(zInv) + " (its flat faces are at "
                              + (heights.Length > 0 ? heights : "-") + ")" + (!string.IsNullOrEmpty(err2) ? "; Revit: " + err2 : ""));
                }
                return notes;
            }

            /// <summary>', '.join(sorted(set(fmm(z) ...))) of the flat faces - sorted as text, as the Python did.</summary>
            private static string FlatHeights(List<FaceZ> hfaces)
            {
                return string.Join(", ", hfaces.Where(fz => Math.Abs(fz.Nz) > 0.99).Select(fz => Fmm(fz.Z))
                                               .Distinct().OrderBy(s => s, StringComparer.Ordinal));
            }
        }

        /// <summary>Lock a single-service hanger; shared hangers are never locked.</summary>
        public static void LockIf(Locker locker, FamilyInstance inst, Element service, Section sec, V3 q, List<string> problems, FhaDebugLog log)
        {
            if (locker == null || inst == null) return;
            if ((sec.Keys != null ? sec.Keys.Count : 1) > 1)
            {
                log.Add("   not locked: shared hanger");
                return;
            }
            foreach (string n in locker.Lock(inst, service, sec, q))
            {
                log.Add("   lock: " + n);
                problems.Add("Lock: " + n);
            }
        }
    }
}
