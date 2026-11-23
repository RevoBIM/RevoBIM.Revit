using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        /// <summary>A reference and its label (the Python (reference, label) pairs).</summary>
        public class RefItem
        {
            public Reference Ref;
            public string Label;
            /// <summary>FamilyInstanceReferenceType name (instance references) and the reference plane's own name.</summary>
            public string Type = "", Name = "";
            /// <summary>The geometry line a centreline reference came from (for its exact position).</summary>
            public Line Geo;
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
                    o.Add(new RefItem(r, lbl + (nm.Length > 0 ? " \"" + nm + "\"" : "")) { Type = k, Name = nm });
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
            int attempts;
            return TryAlign(doc, view, targets, candidates, log, maxTries, out err, out attempts);
        }

        /// <summary>As above, also saying how many pairs were tried.</summary>
        public static AlignHit TryAlign(Document doc, View view, List<RefItem> targets, List<RefItem> candidates, FhaDebugLog log, int maxTries, out string err, out int attempts)
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
                        attempts = n - 1;
                        return null;
                    }
                    try
                    {
                        doc.Create.NewAlignment(view, t.Ref, c.Ref);
                        err = null;
                        attempts = n;
                        return new AlignHit { TargetLabel = t.Label, CandidateLabel = c.Label };
                    }
                    catch (Exception ex)
                    {
                        last = ex.Message;
                    }
                }
            }
            err = last;
            attempts = n;
            return null;
        }

        private static bool Alive(Element el)
        {
            try { return el == null || el.IsValidObject; }
            catch (Exception) { return true; }
        }
    }
}
