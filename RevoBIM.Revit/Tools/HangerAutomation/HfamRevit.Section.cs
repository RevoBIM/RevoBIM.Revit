using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.DB.Mechanical;
using Autodesk.Revit.DB.Plumbing;

namespace RevoBIM.Tools.HangerAutomation
{
    public static partial class HfamRevit
    {
        // ============================================================ duct geometry
        /// <summary>Insulation thickness on a duct (0 when none). Revit ducts: the
        /// DuctInsulation elements hosted on it; FAB parts: their own InsulationThickness.</summary>
        public static double InsulationThickness(Element el)
        {
            if (el is CableTray || el is Conduit) return 0.0;   // conduit: no insulation
            FabricationPart fp = el as FabricationPart;
            if (fp != null)
            {
                try
                {
                    if (fp.HasInsulation) return fp.InsulationThickness;
                }
                catch (Exception) { }
                try { return fp.InsulationThickness; }
                catch (Exception) { return 0.0; }
            }
            double t = 0.0;
            try
            {
                Document doc = el.Document;
                foreach (ElementId iid in InsulationLiningBase.GetInsulationIds(doc, el.Id))
                {
                    Element ins = doc.GetElement(iid);
                    double v;
                    try { v = ((InsulationLiningBase)ins).Thickness; }
                    catch (Exception)
                    {
                        v = Truthy(ParamDouble(ins, "RBS_INSULATION_THICKNESS_FOR_DUCT"))
                            ?? Truthy(ParamDouble(ins, "RBS_INSULATION_THICKNESS_FOR_PIPE")) ?? 0.0;
                    }
                    t = Math.Max(t, v);
                }
            }
            catch (Exception) { }
            return t;
        }

        /// <summary>The section of a Revit duct / pipe / cable tray or fabrication straight, with its insulation thickness.</summary>
        public static Section Section(Element el)
        {
            Section sec = RawSection(el);
            sec.Ins = InsulationThickness(el);
            return sec;
        }

        /// <summary>Section(el) read once per job (a service's size does not change while a job runs); every call gets its own
        /// copy. The cache is cleared at each job start (LogContext).</summary>
        public static Section SectionCached(Element el)
        {
            long k = Eid(el.Id);
            Section s;
            if (!HaCache.Sections.TryGetValue(k, out s))
            {
                s = Section(el);
                HaCache.Sections[k] = s;
            }
            return s.Clone();
        }

        /// <summary>{'a','b','width','depth','round'} for a Revit duct or fabrication straight (Python _section).</summary>
        public static Section RawSection(Element el)
        {
            if (el is Pipe)
            {
                Curve c = ((LocationCurve)el.Location).Curve;
                V3 a = Pt(c.GetEndPoint(0)), b = Pt(c.GetEndPoint(1));
                double d = Truthy(ParamDouble(el, "RBS_PIPE_OUTER_DIAMETER")) ?? Truthy(ParamDouble(el, "RBS_PIPE_DIAMETER_PARAM")) ?? 0.0;
                return new Section { A = a, B = b, Width = d, Depth = d, Round = true };
            }
            if (el is Conduit)
            {
                // round: the outside diameter (the size a hanger wraps), else the trade size
                Curve c = ((LocationCurve)el.Location).Curve;
                V3 a = Pt(c.GetEndPoint(0)), b = Pt(c.GetEndPoint(1));
                double d = Truthy(ParamDouble(el, "RBS_CONDUIT_OUTER_DIAM_PARAM")) ?? Truthy(ParamDouble(el, "RBS_CONDUIT_DIAMETER_PARAM")) ?? 0.0;
                return new Section { A = a, B = b, Width = d, Depth = d, Round = true };
            }
            if (el is CableTray)
            {
                Curve c = ((LocationCurve)el.Location).Curve;
                V3 a = Pt(c.GetEndPoint(0)), b = Pt(c.GetEndPoint(1));
                double w = Truthy(ParamDouble(el, "RBS_CABLETRAY_WIDTH_PARAM")) ?? 0.0;
                double h = Truthy(ParamDouble(el, "RBS_CABLETRAY_HEIGHT_PARAM")) ?? 0.0;
                return new Section { A = a, B = b, Width = w, Depth = h, Round = false };
            }
            if (IsRvtDuct(el))
            {
                Curve c = ((LocationCurve)el.Location).Curve;
                V3 a = Pt(c.GetEndPoint(0)), b = Pt(c.GetEndPoint(1));
                double? d = Truthy(ParamDouble(el, "RBS_CURVE_DIAMETER_PARAM"));
                if (d != null)
                    return new Section { A = a, B = b, Width = d.Value, Depth = d.Value, Round = true };
                double w = Truthy(ParamDouble(el, "RBS_CURVE_WIDTH_PARAM")) ?? 0.0;
                double h = Truthy(ParamDouble(el, "RBS_CURVE_HEIGHT_PARAM")) ?? 0.0;
                return new Section { A = a, B = b, Width = w, Depth = h, Round = false };
            }
            FabricationPart fp = (FabricationPart)el;
            List<Connector> sides;
            List<Connector> ends = FhaRevit.EndPair(fp, FhaRevit.AllConns(fp), out sides);
            V3 fa = Pt(ends[0].Origin), fb = Pt(ends[1].Origin);
            var vals = new Dictionary<string, double>(StringComparer.Ordinal);
            try
            {
                foreach (FabricationDimensionDefinition dd in fp.GetDimensions())
                {
                    try { vals[(dd.Name ?? "").Trim().ToLowerInvariant()] = fp.GetDimensionValue(dd); }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            double? w2 = Truthy(Val(vals, "width")) ?? Val(vals, "main width");
            double? dia = Truthy(Val(vals, "outside diameter")) ?? Truthy(Val(vals, "diameter"))
                          ?? Truthy(Val(vals, "main diameter")) ?? Val(vals, "nominal diameter");
            if (!Truthy(w2).HasValue && Truthy(dia).HasValue)
                return new Section { A = fa, B = fb, Width = dia.Value, Depth = dia.Value, Round = true };
            double h2 = Truthy(Val(vals, "depth")) ?? Truthy(Val(vals, "height")) ?? Truthy(Val(vals, "main depth")) ?? 0.0;
            if (!Truthy(w2).HasValue && h2 == 0.0)
            {
                // no usable dimension names: a round connector tells the size (FAB round ducts / pipes)
                try
                {
                    if (ends[0].Shape == ConnectorProfileType.Round && ends[0].Radius > 0.0)
                        return new Section { A = fa, B = fb, Width = ends[0].Radius * 2.0, Depth = ends[0].Radius * 2.0, Round = true };
                }
                catch (Exception) { }
            }
            return new Section { A = fa, B = fb, Width = Truthy(w2) ?? 0.0, Depth = h2, Round = false };
        }

        private static double? Val(Dictionary<string, double> d, string key)
        {
            double v;
            return d.TryGetValue(key, out v) ? (double?)v : null;
        }

        /// <summary>A level and its elevation (the Python (level, elevation) pairs).</summary>
        public class LevelElev
        {
            public Level Level;
            public double Elev;
        }

        /// <summary>Every level with its project elevation, lowest first.</summary>
        public static List<LevelElev> Levels(Document doc)
        {
            // read once per job (the list is only ever enumerated by the callers)
            if (HaCache.LevelList != null && ReferenceEquals(HaCache.LevelsDoc, doc)) return HaCache.LevelList;
            List<LevelElev> read = ReadLevels(doc);
            HaCache.LevelsDoc = doc;
            HaCache.LevelList = read;
            return read;
        }

        private static List<LevelElev> ReadLevels(Document doc)
        {
            var o = new List<LevelElev>();
            foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(Level)))
            {
                try
                {
                    Level lv = (Level)e;
                    o.Add(new LevelElev { Level = lv, Elev = lv.ProjectElevation });
                }
                catch (Exception) { }
            }
            return o.Select((x, i) => new { x, i }).OrderBy(z => z.x.Elev).ThenBy(z => z.i).Select(z => z.x).ToList();
        }

        private static Level LevelFromId(Document doc, ElementId lid)
        {
            try
            {
                if (lid != null && Eid(lid) > 0)
                {
                    Level lv = doc.GetElement(lid) as Level;
                    if (lv != null) return lv;
                }
            }
            catch (Exception) { }
            return null;
        }

        /// <summary>The level an element is assigned to (reference / start / schedule level),
        /// else the level at or below z.</summary>
        public static Level ElementLevel(Document doc, Element el, double? z = null)
        {
            try
            {
                Level lv = Prop(el, "ReferenceLevel") as Level;
                if (lv != null) return lv;
            }
            catch (Exception) { }
            try
            {
                Level lv = LevelFromId(doc, el.LevelId);
                if (lv != null) return lv;
            }
            catch (Exception) { }
            foreach (string name in new[] { "RBS_START_LEVEL_PARAM", "FABRICATION_LEVEL_PARAM", "FAMILY_LEVEL_PARAM",
                                            "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM" })
            {
                try
                {
                    BuiltInParameter? b = Bip(name);
                    Parameter p = b != null ? el.get_Parameter(b.Value) : null;
                    Level lv = p != null ? LevelFromId(doc, p.AsElementId()) : null;
                    if (lv != null) return lv;
                }
                catch (Exception) { }
            }
            foreach (string nm in new[] { "Reference Level", "Level", "Schedule Level" })
            {
                try
                {
                    Parameter p = el.LookupParameter(nm);
                    Level lv = p != null ? LevelFromId(doc, p.AsElementId()) : null;
                    if (lv != null) return lv;
                }
                catch (Exception) { }
            }
            try
            {
                FamilyInstance fi = el as FamilyInstance;
                Level host = fi != null ? fi.Host as Level : null;
                if (host != null) return host;
            }
            catch (Exception) { }
            if (z != null)
            {
                List<LevelElev> lvls = Levels(doc);
                List<LevelElev> below = lvls.Where(le => le.Elev <= z.Value + Tol).ToList();
                if (below.Count > 0) return below[below.Count - 1].Level;
                if (lvls.Count > 0) return lvls[0].Level;
            }
            return null;
        }

        // ============================================================ parameters
        public static readonly string[] OffsetBips = { "INSTANCE_ELEVATION_PARAM", "INSTANCE_FREE_HOST_OFFSET_PARAM" };
        public static readonly string[] OffsetNames = { "Elevation from Level", "Offset from Host", "Offset" };

        /// <summary>The writable elevation / offset parameter of a hanger, or null.</summary>
        public static Parameter OffsetParam(Element inst)
        {
            foreach (string name in OffsetBips)
            {
                try
                {
                    BuiltInParameter? b = Bip(name);
                    Parameter p = b != null ? inst.get_Parameter(b.Value) : null;
                    if (p != null && !p.IsReadOnly) return p;
                }
                catch (Exception) { }
            }
            foreach (string nm in OffsetNames)
            {
                try
                {
                    Parameter p = inst.LookupParameter(nm);
                    if (p != null && !p.IsReadOnly) return p;
                }
                catch (Exception) { }
            }
            return null;
        }

        /// <summary>True if the instance has a writable numeric parameter `name` and took value.</summary>
        public static bool SetLength(Element inst, string name, double value)
        {
            if (string.IsNullOrEmpty(name)) return false;
            try
            {
                Parameter p = inst.LookupParameter(name);
                if (p == null || p.IsReadOnly || p.StorageType != StorageType.Double) return false;
                p.Set(value);
                return true;
            }
            catch (Exception) { return false; }
        }

        public static double? GetLength(Element inst, string name)
        {
            try
            {
                Parameter p = inst.LookupParameter(name);
                return p != null ? (double?)p.AsDouble() : null;
            }
            catch (Exception) { return null; }
        }

        public static bool SetLevel(Element inst, Level level)
        {
            foreach (string name in new[] { "FAMILY_LEVEL_PARAM", "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM" })
            {
                try
                {
                    BuiltInParameter? b = Bip(name);
                    Parameter p = b != null ? inst.get_Parameter(b.Value) : null;
                    if (p != null && !p.IsReadOnly)
                    {
                        p.Set(level.Id);
                        return true;
                    }
                }
                catch (Exception) { }
            }
            return false;
        }

        /// <summary>True for the Family Floor Support tab (settings['_mode'] or cfg['mode'] == floor).</summary>
        public static bool IsFloor(IDictionary<string, string> settings)
        {
            try
            {
                string m = SGet(settings, "mode", "");
                if (m.Length == 0) m = SGet(settings, "_mode", "");
                return m == "floor";
            }
            catch (Exception) { return false; }
        }

        public static bool IsFloor(FamConfig cfg)
        {
            try { return cfg != null && cfg.Mode == "floor"; }
            catch (Exception) { return false; }
        }

        public static string NounOf(IDictionary<string, string> settings)
        {
            return IsFloor(settings) ? "floor support" : "hanger";
        }

        /// <summary>The level a floor support stands on: the service's own level, unless
        /// that is above the service's invert - then the highest level below it.</summary>
        public static Level FloorLevel(Document doc, Element service, double zInvert, FhaDebugLog log = null)
        {
            Level level = ElementLevel(doc, service, zInvert);
            if (level != null && level.ProjectElevation <= zInvert + Tol) return level;
            List<LevelElev> below = Levels(doc).Where(le => le.Elev <= zInvert + Tol).ToList();
            if (below.Count > 0)
            {
                if (log != null)
                    log.Add("   the service's level " + (level != null ? ElName(level) : "?") + " is above its invert - standing on "
                            + ElName(below[below.Count - 1].Level));
                return below[below.Count - 1].Level;
            }
            return level;
        }

        // ============================================================ soffit
        /// <summary>Where a drop rod should stop: the base of the level above (default) or
        /// the underside of structure above (ray, through FhaRevit.Soffit).</summary>
        public class SoffitFinder
        {
            public Document Doc;
            public List<double> Lvls;
            public FhaRevit.Soffit Ray;

            /// <summary>Names of the hanger families (Family settings + the one being placed): a rod never stops at one of
            /// their instances - MEP Ancillary Framing / Casework can be rod targets and hangers are MEP Ancillary Framing.</summary>
            public HashSet<string> IgnoreFamilies = new HashSet<string>(StringComparer.Ordinal);

            /// <summary>Element ids a rod ray ignores for this whole job (e.g. the fabrication hanger being swapped out).</summary>
            public HashSet<long> Skip = new HashSet<long>();

            public SoffitFinder(Document doc, FhaSettings settings, FhaDebugLog log, bool wantStructure)
            {
                Doc = doc;
                Lvls = Levels(doc).Select(le => le.Elev).ToList();
                Ray = wantStructure ? new FhaRevit.Soffit(doc, settings, log) : null;
                if (Ray != null)
                {
                    try
                    {
                        foreach (string fam in FamsOf(settings).Keys) IgnoreFamilies.Add(fam);
                        HfamChoice ch = ChoiceOf(settings);
                        if (ch != null && !string.IsNullOrEmpty(ch.Family)) IgnoreFamilies.Add(ch.Family);
                    }
                    catch (Exception) { }
                    FhaRevit.Soffit ray = Ray;
                    ray.IgnoreElement = e =>
                    {
                        if (e is FabricationPart) return FhaRevit.IsHanger(e);
                        FamilyInstance fi = e as FamilyInstance;
                        if (fi == null) return false;
                        try { return IgnoreFamilies.Contains(ElName(fi.Symbol.Family)); }
                        catch (Exception) { return false; }
                    };
                }
            }

            /// <summary>Z of the base of the level above or the structure above; a rod ray never stops at the elements in
            /// `exclude` (the hanger being fitted and its group), at Skip, or at any hanger of a known hanger family.</summary>
            public double? Above(string mode, double x, double y, double z, ICollection<long> exclude = null)
            {
                if (mode == "structure" && Ray != null && Ray.Ok())
                {
                    ICollection<long> ex = exclude;
                    if (Skip.Count > 0)
                    {
                        var m = new HashSet<long>(Skip);
                        if (exclude != null) foreach (long k in exclude) m.Add(k);
                        ex = m;
                    }
                    double? hit = Ray.Above(x, y, z + 0.01, ex);
                    if (hit != null) return hit;
                }
                return HfamCore.LevelAbove(Lvls, z);
            }

            /// <summary>The ids a rod ray must ignore for this hanger: itself and, when it is in a group, the group's members.</summary>
            public static HashSet<long> ExcludeIds(Element inst)
            {
                var set = new HashSet<long>();
                if (inst == null) return set;
                set.Add(Eid(inst.Id));
                try
                {
                    ElementId gid = inst.GroupId;
                    if (gid != null && Eid(gid) > 0)
                    {
                        Group g = inst.Document.GetElement(gid) as Group;
                        if (g != null)
                            foreach (ElementId m in g.GetMemberIds()) set.Add(Eid(m));
                    }
                }
                catch (Exception) { }
                return set;
            }

            public void Close()
            {
                if (Ray != null) Ray.Close();
            }
        }
    }
}
