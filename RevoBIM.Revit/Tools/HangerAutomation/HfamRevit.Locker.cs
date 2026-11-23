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

        /// <summary>Align-locks a hanger to what it carries.
        ///
        /// Services: the hanger's centre plane along the run to the service centreline
        /// (plan view), and its face / plane at the invert to the service's bottom
        /// face - or its insulation's, when the hanger sits outside it (in a section
        /// kept per service). Units (equipment, duct accessories): to the unit's
        /// centre planes and bottom face. Single services only; shared hangers are
        /// never locked. Every reference the family offers is tried, so a family
        /// whose centre plane is a Strong / Weak reference still locks.
        ///
        /// Centre lock (rewritten): the centreline is looked for in several ways and the alignment is tried in the active plan (when
        /// it shows the service) and in a plan of the tool's own with a view range that shows everything on the level - the
        /// centre plane of the hanger family is aligned to the service's CENTRELINE reference. Every step is logged. Each
        /// attempt group runs in a sub-transaction that is rolled back unless an alignment was made.</summary>
        public partial class Locker
        {
            public Document Doc;
            public FhaDebugLog Log;
            public View Plan;
            public Dictionary<long, ViewSection> Sections = new Dictionary<long, ViewSection>();
            public HashSet<long?> Told = new HashSet<long?>();
            /// <summary>Round services only: also lock the family's Center (Elevation) plane to the centreline in the lock
            /// section (circular hangers, whose reference sits at the service centre). Best effort, never reported as a note.</summary>
            public bool ElevationCentre;

            private readonly LockViews _views = new LockViews();
            private readonly Dictionary<string, List<RefItem>> _targets = new Dictionary<string, List<RefItem>>(StringComparer.Ordinal);
            private readonly Dictionary<string, string> _worked = new Dictionary<string, string>(StringComparer.Ordinal);
            private readonly Dictionary<string, int> _fails = new Dictionary<string, int>(StringComparer.Ordinal);
            private string _lastSource;

            private class TargetSource
            {
                public string Key, Label;
                public Func<List<RefItem>> Get;
            }

            public Locker(Document doc, View view, FhaDebugLog log)
            {
                Doc = doc; Log = log;
                Plan = (view != null && Array.IndexOf(PlanTypes, view.ViewType.ToString()) >= 0) ? view : null;
                // what worked (hanger reference per family, service line kind per category) carries over to the next job in the
                // same model, so a later job goes straight to the working pair instead of probing again
                if (!ReferenceEquals(_learnedDoc, doc))
                {
                    _learnedDoc = doc;
                    _symKind.Clear();
                    _symWorked.Clear();
                }
            }

            private static Document _learnedDoc;

            private ViewSection SectionFor(Element service, Section sec)
            {
                long key = Eid(service.Id);
                if (Sections.ContainsKey(key) && !Alive(Sections[key]))
                    Sections.Remove(key);   // made in a placement Revit then undid: make it again
                if (!Sections.ContainsKey(key))
                {
                    try
                    {
                        Sections[key] = MakeLockSection(Doc, service, sec, Log, _views);
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

            private static string FamKey(FamilyInstance inst)
            {
                try { return Inv(Eid(inst.Symbol.Family.Id)); }
                catch (Exception) { return "?"; }
            }

            /// <summary>The hanger references with the one that worked last time for this family first (labels of faces are
            /// compared without their height).</summary>
            private List<RefItem> Prefer(List<RefItem> items, string key)
            {
                string w;
                if (!_worked.TryGetValue(key, out w)) return items;
                var first = items.Where(i => NormLabel(i.Label) == w).ToList();
                if (first.Count == 0) return items;
                var o = new List<RefItem>(first);
                o.AddRange(items.Where(i => NormLabel(i.Label) != w));
                return o;
            }

            private static string NormLabel(string label)
            {
                return label.StartsWith("face at ", StringComparison.Ordinal) ? "face" : label;
            }

            /// <summary>How many pairs one lock may try: all 80 normally; 16 once this family has refused twice running (a family
            /// that cannot lock would otherwise cost 80 refusals for every hanger).</summary>
            private int MaxTries(string key)
            {
                int n;
                return _fails.TryGetValue(key, out n) && n >= 2 ? 16 : 80;
            }

            private void Outcome(string key, bool ok)
            {
                int n;
                _fails.TryGetValue(key, out n);
                _fails[key] = ok ? 0 : n + 1;
            }

            // ------------------------------------------------------------ the lock
            /// <summary>Lock one hanger to its service (or unit); returns the notes for whatever could not be locked.
            /// Services, centre: (a) the hanger's centre plane aligned to the SYMBOL-level centreline line of the service (what Revit's own
            /// Align uses); (b) the face-based EQ lock, only when the service has side faces; (c) the old instance-level centreline
            /// attempt, only when nothing else worked and it was never refused for this category. Units: the unit's centre planes.</summary>
            public List<string> Lock(FamilyInstance inst, Element host, Section sec, V3 q, string axis = null)
            {
                var notes = new List<string>();
                string cenWhy = null;
                bool cenOk = false;
                string botSummary = "skipped (not reached)";
                try
                {
                    LockInner(inst, host, sec, q, axis, notes, out cenOk, out cenWhy, out botSummary);
                }
                finally
                {
                    Log.Add("   lock summary: centre " + (cenOk ? "yes" + (cenWhy != null ? " (" + cenWhy + ")" : "") : "no (" + (cenWhy ?? "not made") + ")")
                            + ", bottom " + botSummary);
                }
                return notes;
            }

            private void LockInner(FamilyInstance inst, Element host, Section sec, V3 q, string axis, List<string> notes,
                                   out bool cenOk, out string cenWhy, out string botSummary)
            {
                cenOk = false; cenWhy = null; botSummary = "skipped (not reached)";
                TellFamily(inst);
                V3 along, across;
                HfamCore.PlanDirs(sec.A, sec.B, out along, out across);
                bool unit = sec.Unit;
                string what = HostKind(host);
                // ---- centre: hanger plane along the run <-> service centreline / unit centre plane
                // the hanger was just rotated / moved / re-parameterised in this transaction: its orientation and references are stale
                // until the document regenerates
                try { Doc.Regenerate(); }
                catch (Exception ex) { Log.Add("   centre lock: regenerate before locking: " + ex.Message); }
                XYZ h = inst.HandOrientation, f = inst.FacingOrientation;
                string square = HfamCore.ReferenceTypeAcross(new V3(h.X, h.Y, 0.0), new V3(f.X, f.Y, 0.0), along);
                string alongType = square == "CenterLeftRight" ? "CenterFrontBack" : "CenterLeftRight";
                string byOrient = RefLabels[alongType];
                // the family settings decide: the run axis of the family is its Y (axis=Y) -> its Center (Left/Right) plane is the one
                // along the run; axis=X -> Center (Front/Back). The orientation vectors are only the fallback (no setting / units).
                if (!unit && (axis == "Y" || axis == "X"))
                {
                    alongType = axis == "Y" ? "CenterLeftRight" : "CenterFrontBack";
                    square = axis == "Y" ? "CenterFrontBack" : "CenterLeftRight";
                }
                Log.Add("   centre lock: family axis=" + (axis ?? "?") + "; hanger hand (" + Fm(h.X, 5) + ", " + Fm(h.Y, 5) + ") facing (" + Fm(f.X, 5) + ", " + Fm(f.Y, 5)
                        + "), run (" + Fm(along.X, 5) + ", " + Fm(along.Y, 5) + ") -> plane along the run: " + RefLabels[alongType]
                        + " (orientation alone would say " + byOrient + ")");
                using (HaTiming.Time("lock.centre"))
                {
                    if (unit)
                    {
                        int before = notes.Count;
                        LockCentre(inst, host, sec, q, along, alongType, square, unit, what, notes);
                        cenOk = notes.Count == before;
                        cenWhy = cenOk ? "unit centre planes" : notes[before];
                    }
                    else
                    {
                        string cat = CatKey(host);
                        string shape = cat + (sec.Round ? "|round" : "|rect");
                        string symWhy = null, eqWhy = null;
                        bool done = false;
                        // (a) the symbol-level centreline line <-> the hanger's centre plane (the pair Revit's own Align uses)
                        using (HaTiming.Time("lock.centre.sym"))
                        {
                            try { done = LockSym(inst, host, sec, q, along, across, what, out symWhy); }
                            catch (Exception ex)
                            {
                                symWhy = ExText(ex);
                                Log.Add("   centre lock: symbol-centreline lock failed unexpectedly - " + symWhy);
                            }
                        }
                        if (done)
                        {
                            cenOk = true;
                            cenWhy = "symbol centreline alignment";
                            if (sec.Round && ElevationCentre) LockElevationCentre(inst, host, sec, along, what);
                        }
                        else
                        {
                            // (b) the face-based EQ lock, only when the service has side faces
                            string eqSkip = null;
                            if (host is FabricationPart) eqSkip = "a fabrication part has no side faces with references";
                            else if (_noFaces.Contains(shape)) eqSkip = "an earlier " + cat + (sec.Round ? " (round)" : "") + " had no side faces";
                            bool eq = false;
                            if (eqSkip != null)
                            {
                                Log.Add("   centre lock: face-based EQ lock skipped - " + eqSkip);
                                eqWhy = eqSkip;
                            }
                            else
                            {
                                _eqSawSides = false;
                                using (HaTiming.Time("lock.centre.eq"))
                                {
                                    try { eq = LockEq(inst, host, sec, q, along, across, alongType, square, what, out eqWhy); }
                                    catch (Exception ex)
                                    {
                                        eqWhy = ExText(ex);
                                        Log.Add("   centre lock: EQ lock failed unexpectedly - " + eqWhy);
                                    }
                                }
                                if (!eq && !_eqSawSides)
                                {
                                    _noFaces.Add(shape);
                                    Log.Add("   centre lock: no side faces for " + shape + " - the face-based EQ lock will not be tried again for it");
                                }
                            }
                            if (eq)
                            {
                                cenOk = true;
                                cenWhy = "face-based EQ lock";
                                if (sec.Round && ElevationCentre) LockElevationCentre(inst, host, sec, along, what);
                            }
                            else
                            {
                                // (c) the old instance-level centreline attempt, never repeated for a category it was refused for
                                if (_oldRefused.Contains(cat))
                                {
                                    Log.Add("   centre lock: old instance-level centreline attempt skipped - refused for every earlier " + cat);
                                    cenWhy = "symbol centreline: " + symWhy + "; EQ: " + eqWhy;
                                    notes.Add("centre not locked - " + symWhy);
                                }
                                else
                                {
                                    Log.Add("   centre lock: falling back to the old instance-level centreline attempt (" + symWhy + "; EQ: " + eqWhy + ")");
                                    int before = notes.Count;
                                    LockCentre(inst, host, sec, q, along, alongType, square, unit, what, notes);
                                    if (notes.Count > before)
                                    {
                                        _oldRefused.Add(cat);
                                        notes[before] = "symbol centreline alignment: " + symWhy + "; " + notes[before];
                                        cenWhy = "symbol centreline: " + symWhy + "; EQ: " + eqWhy + "; old attempt refused";
                                    }
                                    else
                                    {
                                        cenOk = true;
                                        cenWhy = "old instance-level centreline";
                                    }
                                }
                            }
                        }
                    }
                }
                // ---- bottom: hanger at the invert <-> service / insulation / unit bottom face
                if (sec.Round)
                {
                    Log.Add("   round " + what + ": centre lock only (no flat bottom face)");
                    botSummary = "skipped (round " + what + ")";
                    return;
                }
                // only Ducts and Cable Trays have a physical bottom face to lock to (fabrication parts and the rest: skipped, no attempt, no note)
                if (!unit)
                {
                    long cid = 0;
                    string cname = "(no category)";
                    try
                    {
                        if (host.Category != null) { cid = Eid(host.Category.Id); cname = host.Category.Name; }
                    }
                    catch (Exception) { }
                    if (cid != (long)BuiltInCategory.OST_DuctCurves && cid != (long)BuiltInCategory.OST_CableTray)
                    {
                        Log.Add("   lock: bottom lock skipped: " + cname + " has no usable bottom face (only Ducts and Cable Trays are locked at the bottom)");
                        botSummary = "skipped (" + cname + ")";
                        return;
                    }
                    if (host is FabricationPart)
                    {
                        Log.Add("   lock: bottom lock skipped: a fabrication part has no usable bottom face");
                        botSummary = "skipped (fabrication part)";
                        return;
                    }
                }
                using (HaTiming.Time("lock.bottom"))
                    botSummary = LockBottom(inst, host, sec, q, along, across, unit, what, notes);
            }

            // LockBottom: see HfamRevit.Locker.Sym.cs

            /// <summary>', '.join(sorted(set(fmm(z) ...))) of the flat faces - sorted as text, as the Python did.</summary>
            private static string FlatHeights(List<FaceZ> hfaces)
            {
                return string.Join(", ", hfaces.Where(fz => Math.Abs(fz.Nz) > 0.99).Select(fz => Fmm(fz.Z))
                                               .Distinct().OrderBy(s => s, StringComparer.Ordinal));
            }
        }

        /// <summary>Lock a single-service hanger; shared hangers are never locked.</summary>
        public static void LockIf(Locker locker, FamilyInstance inst, Element service, Section sec, V3 q, List<string> problems, FhaDebugLog log, FamConfig cfg = null)
        {
            if (locker == null || inst == null) return;
            if ((sec.Keys != null ? sec.Keys.Count : 1) > 1)
            {
                log.Add("   not locked: shared hanger");
                return;
            }
            using (HaTiming.Time("lock"))
            {
                foreach (string n in locker.Lock(inst, service, sec, q, cfg != null ? cfg.Get("axis", "X") : null))
                {
                    log.Add("   lock: " + n);
                    problems.Add("Lock: " + n);
                }
            }
        }
    }
}
