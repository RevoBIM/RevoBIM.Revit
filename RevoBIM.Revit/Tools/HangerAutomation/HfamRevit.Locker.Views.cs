using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        /// <summary>The tool's own lock views (sections and centre-lock plans) already in the model, read once per Locker,
        /// plus the view family types needed to make more.</summary>
        public class LockViews
        {
            public const string Prefix = "Hanger Automation - ";
            public Dictionary<string, View> Named = new Dictionary<string, View>(StringComparer.Ordinal);
            public ViewFamilyType SectionVft, PlanVft;
            public Dictionary<long, ViewPlan> Plans = new Dictionary<long, ViewPlan>();
            public HashSet<long> PlanFailed = new HashSet<long>();
            private bool _loaded;

            public void Load(Document doc)
            {
                if (_loaded) return;
                _loaded = true;
                foreach (Type t in new[] { typeof(ViewSection), typeof(ViewPlan) })
                {
                    try
                    {
                        foreach (Element e in new FilteredElementCollector(doc).OfClass(t))
                        {
                            View v = (View)e;
                            try
                            {
                                if (v.IsTemplate) continue;
                            }
                            catch (Exception) { }
                            string nm = ElName(v);
                            if (nm.StartsWith(Prefix, StringComparison.Ordinal) && !Named.ContainsKey(nm)) Named[nm] = v;
                        }
                    }
                    catch (Exception) { }
                }
                try
                {
                    foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)))
                    {
                        ViewFamilyType v = (ViewFamilyType)e;
                        if (SectionVft == null && v.ViewFamily == ViewFamily.Section) SectionVft = v;
                        if (PlanVft == null && v.ViewFamily == ViewFamily.FloorPlan) PlanVft = v;
                        if (SectionVft != null && PlanVft != null) break;
                    }
                }
                catch (Exception) { }
            }

            /// <summary>A view made on an earlier run (exact name, else its first '(n)' copy).</summary>
            public View Find(string name)
            {
                // a view made in a placement Revit later undid (a rolled-back transaction) is gone: forget it, never hand it out
                List<string> dead = null;
                foreach (KeyValuePair<string, View> kv in Named)
                {
                    if (!Alive(kv.Value))
                    {
                        if (dead == null) dead = new List<string>();
                        dead.Add(kv.Key);
                    }
                }
                if (dead != null)
                    foreach (string d in dead) Named.Remove(d);
                View best = null;
                foreach (KeyValuePair<string, View> kv in Named)
                {
                    if (kv.Key == name) return kv.Value;
                    if (best == null && kv.Key.StartsWith(name + " (", StringComparison.Ordinal)) best = kv.Value;
                }
                return best;
            }
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

        public static ViewSection MakeLockSection(Document doc, Element service, Section sec, FhaDebugLog log)
        {
            return MakeLockSection(doc, service, sec, log, null);
        }

        /// <summary>A section along the service that holds its hangers' bottom locks
        /// (a lock on a horizontal face lives in a section / elevation view and is
        /// deleted with it). Reuses the one made on an earlier run. `views` (optional): the Locker's
        /// read-once list of the tool's views, so a run over many services does not scan every section for each.</summary>
        public static ViewSection MakeLockSection(Document doc, Element service, Section sec, FhaDebugLog log, LockViews views)
        {
            string baseName = LockSectionName(service);
            ViewSection old;
            if (views != null)
            {
                views.Load(doc);
                old = views.Find(baseName) as ViewSection;
            }
            else
                old = FindLockSection(doc, baseName);
            if (old != null)
            {
                log.Add("   lock section: reusing " + ElName(old));
                return old;
            }
            ViewFamilyType vft = null;
            if (views != null)
                vft = views.SectionVft;
            else
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)))
                {
                    ViewFamilyType v = (ViewFamilyType)e;
                    if (v.ViewFamily == ViewFamily.Section)
                    {
                        vft = v;
                        break;
                    }
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
            if (views != null) views.Named[ElName(view)] = view;
            log.Add("   lock section: " + ElName(view));
            return view;
        }
    }
}
