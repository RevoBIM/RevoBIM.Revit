using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.MatchOffset
{
    /// <summary>The three elevations of an element in project feet, and how they were worked out.</summary>
    public sealed class MoMeasurement
    {
        public bool Ok;
        public string Reason = "";
        public double Bottom, Middle, Top, Slope;
        public string Route = "";
        public bool HasOffsetParam;

        public double Value(string anchor) { return MoCore.AnchorValue(Bottom, Middle, Top, anchor); }
    }

    /// <summary>An element's own level: its name and project elevation (null when it names none).</summary>
    public sealed class MoLevel
    {
        public string Name = "";
        public double? Elevation;
    }

    /// <summary>
    /// Everything in Match Offset that touches the Revit model. Measuring is separate from writing and both
    /// report the route they took, because a void API call is not evidence: every write is read back through a
    /// fresh measurement. Port of mo_model.py. BuiltInCategory and BuiltInParameter members are resolved once, by
    /// name, so a name a release does not have cannot take the tool down.
    /// </summary>
    public static class MoModel
    {
        private static readonly string[] RoundSizeParams =
            { "RBS_PIPE_OUTER_DIAMETER", "RBS_CURVE_DIAMETER_PARAM", "RBS_CONDUIT_OUTER_DIAM_PARAM", "RBS_CONDUIT_DIAMETER_PARAM" };
        private static readonly string[] BoxSizeParams = { "RBS_CURVE_HEIGHT_PARAM", "RBS_CABLETRAY_HEIGHT_PARAM" };
        private static readonly string[] InsulationParams = { "RBS_REFERENCE_INSULATION_THICKNESS" };
        private static readonly string[] OffsetParams = { "RBS_OFFSET_PARAM" };
        private static readonly string[] LevelOffsetParams = { "INSTANCE_ELEVATION_PARAM" };
        private static readonly string[] HostOffsetParams = { "INSTANCE_FREE_HOST_OFFSET_PARAM" };
        private static readonly string[] FabBottomParams = { "FABRICATION_BOTTOM_OF_PART", "FABRICATION_PART_BOTTOM_ELEVATION" };
        private static readonly string[] FabTopParams = { "FABRICATION_TOP_OF_PART", "FABRICATION_PART_TOP_ELEVATION" };
        private static readonly string[] FabBottomNames = { "Bottom of Part", "Bottom Elevation" };
        private static readonly string[] FabTopNames = { "Top of Part", "Top Elevation" };
        private static readonly string[] LevelParams =
            { "FABRICATION_LEVEL_PARAM", "RBS_START_LEVEL_PARAM", "FAMILY_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM",
              "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM", "LEVEL_PARAM" };

        // 50mm: close enough that a parameter and the solids describe the same face, far enough that a level offset
        // mistaken for a project elevation is never mistaken for agreement.
        private const double AgreeFt = 50.0 / 304.8;

        private static Dictionary<string, long> categoryIds;
        private static HashSet<long> pointIds, fabIds, hangerIds, framingIds;
        private static readonly Dictionary<string, BuiltInParameter?> BipCache = new Dictionary<string, BuiltInParameter?>();
        private static readonly Dictionary<string[], BuiltInParameter[]> BipSets = new Dictionary<string[], BuiltInParameter[]>();
        private static Document levelsDoc;
        private static readonly List<double> Levels = new List<double>();

        /// <summary>Forget anything cached against a document: level elevations belong to one document.</summary>
        public static void ResetCaches()
        {
            levelsDoc = null;
            Levels.Clear();
        }

        public static long Eid(ElementId id) { return id == null ? 0 : id.Value; }

        // ======================================================================
        // late enum lookup, resolved once
        // ======================================================================

        public static BuiltInCategory? BuiltinCategory(string name)
        {
            BuiltInCategory value;
            return Enum.TryParse(name, out value) && Enum.IsDefined(typeof(BuiltInCategory), value) ? value : (BuiltInCategory?)null;
        }

        public static BuiltInParameter? BuiltinParameter(string name)
        {
            lock (BipCache)
            {
                BuiltInParameter? cached;
                if (BipCache.TryGetValue(name, out cached)) return cached;
                BuiltInParameter value;
                BuiltInParameter? member = Enum.TryParse(name, out value) && Enum.IsDefined(typeof(BuiltInParameter), value)
                    ? value : (BuiltInParameter?)null;
                BipCache[name] = member;
                return member;
            }
        }

        private static BuiltInParameter[] BuiltinParameters(string[] names)
        {
            lock (BipSets)
            {
                BuiltInParameter[] cached;
                if (BipSets.TryGetValue(names, out cached)) return cached;
                cached = names.Select(BuiltinParameter).Where(m => m.HasValue).Select(m => m.Value).ToArray();
                BipSets[names] = cached;
                return cached;
            }
        }

        /// <summary>settings key -> the category's id, built once per session.</summary>
        public static Dictionary<string, long> CategoryIdMap()
        {
            if (categoryIds != null) return categoryIds;
            var map = new Dictionary<string, long>();
            foreach (MoCategory def in MoCore.CategoryDefs)
            {
                BuiltInCategory? bic = BuiltinCategory(def.Bic);
                if (!bic.HasValue) continue;
                try
                {
                    map[def.Key] = new ElementId(bic.Value).Value;
                }
                catch (Exception)
                {
                }
            }
            categoryIds = map;
            return map;
        }

        public static Dictionary<long, string> CategoryKeyMap()
        {
            var reverse = new Dictionary<long, string>();
            foreach (KeyValuePair<string, long> pair in CategoryIdMap()) reverse[pair.Value] = pair.Key;
            return reverse;
        }

        private static HashSet<long> IdsWhere(Func<string, bool> test)
        {
            return new HashSet<long>(CategoryIdMap().Where(p => test(p.Key)).Select(p => p.Value));
        }

        private static bool InSet(Element element, ref HashSet<long> set, Func<string, bool> test)
        {
            if (set == null) set = IdsWhere(test);
            try
            {
                return element.Category != null && set.Contains(Eid(element.Category.Id));
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static bool IsAFabricationPart(Element e) { return InSet(e, ref fabIds, MoCore.IsFabrication); }
        public static bool IsAncillaryFraming(Element e) { return InSet(e, ref framingIds, MoCore.IsFraming); }
        public static bool IsAHanger(Element e) { return InSet(e, ref hangerIds, MoCore.IsHanger); }
        public static bool MeasuredAtAPoint(Element e) { return InSet(e, ref pointIds, MoCore.IsPointBased); }

        /// <summary>A hanger or a piece of support steel: something a service sits on.</summary>
        public static bool IsASupport(Element e) { return IsAHanger(e) || IsAncillaryFraming(e); }

        // ======================================================================
        // real geometry, rather than the bounding box
        // ======================================================================

        private static Options GeometryOptions()
        {
            var options = new Options();
            try
            {
                options.DetailLevel = ViewDetailLevel.Fine;
                options.ComputeReferences = false;
                options.IncludeNonVisibleObjects = false;
            }
            catch (Exception)
            {
            }
            return options;
        }

        /// <summary>
        /// Every real solid in an element, following instance geometry. The bounding box takes in connectors,
        /// symbolic lines, insulation and anything else Revit calls geometry; the solids are the thing itself.
        /// </summary>
        public static List<Solid> SolidsOf(Element element)
        {
            var found = new List<Solid>();
            GeometryElement source;
            try
            {
                source = element.get_Geometry(GeometryOptions());
            }
            catch (Exception)
            {
                return found;
            }
            if (source != null) CollectSolids(source, found, 0);
            return found;
        }

        private static void CollectSolids(GeometryElement source, List<Solid> found, int depth)
        {
            if (depth > 3) return;
            try
            {
                foreach (GeometryObject item in source)
                {
                    Solid solid = item as Solid;
                    if (solid != null)
                    {
                        try
                        {
                            if (solid.Volume > MoCore.Eps) found.Add(solid);
                        }
                        catch (Exception)
                        {
                        }
                        continue;
                    }
                    GeometryInstance instance = item as GeometryInstance;
                    if (instance != null)
                    {
                        try
                        {
                            CollectSolids(instance.GetInstanceGeometry(), found, depth + 1);
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>The eight corners of a solid's own box, in project coordinates (Min and Max are in the solid's frame).</summary>
        private static List<XYZ> BoxCorners(BoundingBoxXYZ box)
        {
            var corners = new List<XYZ>();
            XYZ low, high;
            Transform transform = null;
            try
            {
                low = box.Min;
                high = box.Max;
                transform = box.Transform;
            }
            catch (Exception)
            {
                return corners;
            }
            foreach (double x in new[] { low.X, high.X })
                foreach (double y in new[] { low.Y, high.Y })
                    foreach (double z in new[] { low.Z, high.Z })
                    {
                        XYZ point = new XYZ(x, y, z);
                        if (transform != null)
                        {
                            try
                            {
                                point = transform.OfPoint(point);
                            }
                            catch (Exception)
                            {
                            }
                        }
                        corners.Add(point);
                    }
            return corners;
        }

        /// <summary>The lowest and highest point of an element's real solids, or null.</summary>
        public static double[] SolidExtent(Element element)
        {
            double? low = null, high = null;
            foreach (Solid solid in SolidsOf(element))
            {
                BoundingBoxXYZ box;
                try
                {
                    box = solid.GetBoundingBox();
                }
                catch (Exception)
                {
                    continue;
                }
                if (box == null) continue;
                foreach (XYZ corner in BoxCorners(box))
                {
                    if (low == null || corner.Z < low.Value) low = corner.Z;
                    if (high == null || corner.Z > high.Value) high = corner.Z;
                }
            }
            if (low == null || high == null) return null;
            return new[] { low.Value, high.Value };
        }

        /// <summary>One solid's flat faces, as (upness, area, height).</summary>
        private static List<double[]> FlatFaces(Solid solid)
        {
            var output = new List<double[]>();
            FaceArray faces;
            try
            {
                faces = solid.Faces;
            }
            catch (Exception)
            {
                return output;
            }
            foreach (Face face in faces)
            {
                PlanarFace planar = face as PlanarFace;
                if (planar == null) continue;
                try
                {
                    output.Add(new[] { planar.FaceNormal.Z, planar.Area, planar.Origin.Z });
                }
                catch (Exception)
                {
                }
            }
            return output;
        }

        private static List<double[]> UpwardFaces(Element element)
        {
            var output = new List<double[]>();
            foreach (Solid solid in SolidsOf(element)) output.AddRange(FlatFaces(solid));
            return output;
        }

        /// <summary>One solid's extents in project feet: low, high, plan span, plan area.</summary>
        private static double[] SolidFrame(Solid solid)
        {
            BoundingBoxXYZ box;
            try
            {
                box = solid.GetBoundingBox();
            }
            catch (Exception)
            {
                return null;
            }
            if (box == null) return null;
            List<XYZ> corners = BoxCorners(box);
            if (corners.Count == 0) return null;
            double across = corners.Max(c => c.X) - corners.Min(c => c.X);
            double along = corners.Max(c => c.Y) - corners.Min(c => c.Y);
            return new[] { corners.Min(c => c.Z), corners.Max(c => c.Z), Math.Max(across, along), across * along };
        }

        /// <summary>A hanger, one piece at a time: rods, a bearer, sometimes an anchor and a backing plate.</summary>
        private static List<MoCore.HangerMember> HangerMembers(Element element)
        {
            var output = new List<MoCore.HangerMember>();
            foreach (Solid solid in SolidsOf(element))
            {
                double[] frame = SolidFrame(solid);
                if (frame == null) continue;
                var member = new MoCore.HangerMember { Low = frame[0], High = frame[1], Span = frame[2], Area = frame[3] };
                member.Faces.AddRange(FlatFaces(solid));
                output.Add(member);
            }
            return output;
        }

        /// <summary>Where a hanger actually holds its services up, and how it was found.</summary>
        private static double? BearingTop(Element element, out string how)
        {
            double? height = MoCore.BearingFromMembers(HangerMembers(element));
            if (height.HasValue)
            {
                how = "the top of its bearer";
                return height;
            }
            height = MoCore.BestBearing(UpwardFaces(element));
            if (height.HasValue)
            {
                how = "its biggest upward face";
                return height;
            }
            how = "";
            return null;
        }

        /// <summary>The hanger's own geometry written out for the debug report: one line per piece and per upward face.</summary>
        public static List<string> HangerLines(Element element, int limit = 48)
        {
            var lines = new List<string>();
            List<MoCore.HangerMember> members = HangerMembers(element);
            if (members.Count == 0)
            {
                lines.Add("no solids to look at");
                return lines;
            }
            double ft2 = MoCore.MmPerFt * MoCore.MmPerFt;
            for (int index = 0; index < members.Count; index++)
            {
                MoCore.HangerMember member = members[index];
                lines.Add("piece " + (index + 1) + ": " + MoCore.FormatMm(MoCore.FtToMm(member.Low)) + " to " +
                          MoCore.FormatMm(MoCore.FtToMm(member.High)) + " mm, " + MoCore.FormatMm(MoCore.FtToMm(member.Span)) +
                          " mm across, footprint " + MoCore.FormatMm(member.Area * ft2) + " mm2, " +
                          (MoCore.IsUpright(member.Low, member.High, member.Span) ? "a rod" : "a bearer"));
                foreach (double[] face in member.Faces.Where(f => f[0] >= 0.9).OrderByDescending(f => f[2]))
                {
                    if (lines.Count >= limit)
                    {
                        lines.Add("... and more");
                        return lines;
                    }
                    lines.Add("    up face " + MoCore.FormatMm(face[1] * ft2) + " mm2 at " + MoCore.FormatMm(MoCore.FtToMm(face[2])) + " mm");
                }
            }
            return lines;
        }

        // ======================================================================
        // fabrication parts
        // ======================================================================

        private static double? NamedParameter(Element element, string[] names)
        {
            foreach (string name in names)
            {
                try
                {
                    Parameter parameter = element.LookupParameter(name);
                    if (parameter != null) return parameter.AsDouble();
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        private static double? FabValue(Element element, string[] builtins, string[] names)
        {
            Parameter parameter = ParamByBuiltin(element, builtins);
            double? value = null;
            if (parameter != null)
            {
                try
                {
                    value = parameter.AsDouble();
                }
                catch (Exception)
                {
                }
            }
            return value ?? NamedParameter(element, names);
        }

        /// <summary>
        /// Pick the reading of a parameter that the solids agree with. Top and Bottom of Part are measured from the
        /// part's level, not the project base - but not on every release - so both readings are compared against
        /// what the solids say and the one that agrees wins.
        /// </summary>
        private static double? Agreeing(List<KeyValuePair<string, double?>> candidates, double[] extent, out string how)
        {
            if (extent == null)
            {
                how = "no solids to check against";
                return null;
            }
            double bestGap = 0;
            string bestLabel = null;
            double bestValue = 0;
            foreach (KeyValuePair<string, double?> candidate in candidates)
            {
                if (!candidate.Value.HasValue) continue;
                double gap = Math.Min(Math.Abs(candidate.Value.Value - extent[0]), Math.Abs(candidate.Value.Value - extent[1]));
                if (bestLabel == null || gap < bestGap)
                {
                    bestGap = gap;
                    bestLabel = candidate.Key;
                    bestValue = candidate.Value.Value;
                }
            }
            if (bestLabel == null)
            {
                how = "no parameter to read";
                return null;
            }
            if (bestGap > AgreeFt)
            {
                how = "the parameters disagree with the solids by " + (bestGap * 304.8).ToString("F0") + "mm";
                return null;
            }
            how = bestLabel;
            return bestValue;
        }

        /// <summary>Bottom and top of a fabrication part from its own parameters, with how that was read.</summary>
        private static bool FabExtent(Document doc, Element element, out double bottom, out double top, out string how)
        {
            bottom = top = 0;
            double[] extent = SolidExtent(element);
            double? bottomRaw = FabValue(element, FabBottomParams, FabBottomNames);
            double? topRaw = FabValue(element, FabTopParams, FabTopNames);
            if (!bottomRaw.HasValue && !topRaw.HasValue)
            {
                how = "no top or bottom of part parameter";
                return false;
            }
            double level = LevelElevation(doc, element);
            string howBottom, howTop;
            double? b = Agreeing(new List<KeyValuePair<string, double?>>
            {
                new KeyValuePair<string, double?>("from its level", bottomRaw.HasValue ? level + bottomRaw.Value : (double?)null),
                new KeyValuePair<string, double?>("as a project elevation", bottomRaw),
            }, extent, out howBottom);
            double? t = Agreeing(new List<KeyValuePair<string, double?>>
            {
                new KeyValuePair<string, double?>("from its level", topRaw.HasValue ? level + topRaw.Value : (double?)null),
                new KeyValuePair<string, double?>("as a project elevation", topRaw),
            }, extent, out howTop);
            if (!b.HasValue || !t.HasValue)
            {
                how = !b.HasValue ? howBottom : howTop;
                return false;
            }
            bottom = b.Value;
            top = t.Value;
            if (top < bottom)
            {
                double swap = bottom;
                bottom = top;
                top = swap;
            }
            how = howBottom;
            return true;
        }

        /// <summary>A family's own insertion height, which is what its level offset is (read off the point, not a parameter).</summary>
        private static double? InsertionPoint(Element element)
        {
            try
            {
                LocationPoint location = element.Location as LocationPoint;
                if (location != null) return location.Point.Z;
            }
            catch (Exception)
            {
            }
            return null;
        }

        /// <summary>Only the categories the settings allow, and nothing in a link. The hot path: a set of longs and one attribute chain.</summary>
        public sealed class OffsetFilter : ISelectionFilter
        {
            private readonly HashSet<long> allowed;

            public OffsetFilter(IEnumerable<string> categoryKeys)
            {
                Dictionary<string, long> map = CategoryIdMap();
                allowed = new HashSet<long>();
                foreach (string key in categoryKeys)
                {
                    long id;
                    if (map.TryGetValue(key, out id)) allowed.Add(id);
                }
            }

            public bool AllowElement(Element element)
            {
                try
                {
                    Category category = element.Category;
                    return category != null && allowed.Contains(category.Id.Value);
                }
                catch (Exception)
                {
                    return false;
                }
            }

            public bool AllowReference(Reference reference, XYZ position) { return false; }
        }

        // ======================================================================
        // parameters
        // ======================================================================

        public static Parameter ParamByBuiltin(Element element, string[] names)
        {
            foreach (BuiltInParameter member in BuiltinParameters(names))
            {
                try
                {
                    Parameter parameter = element.get_Parameter(member);
                    if (parameter != null) return parameter;
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        private static double ParamNumber(Element element, string[] names, double fallback)
        {
            Parameter parameter = ParamByBuiltin(element, names);
            if (parameter == null) return fallback;
            try
            {
                return parameter.AsDouble();
            }
            catch (Exception)
            {
                return fallback;
            }
        }

        public static string Describe(Element element)
        {
            string category;
            try
            {
                category = element.Category.Name;
            }
            catch (Exception)
            {
                category = "Element";
            }
            return category + " " + Eid(element.Id);
        }

        // ======================================================================
        // levels
        // ======================================================================

        /// <summary>
        /// Every level's project elevation, read once per document per run. ProjectElevation, never Elevation: on a
        /// survey-point-based project the latter reports shared coordinates and comes back tens of metres out.
        /// </summary>
        private static List<double> LevelElevations(Document doc)
        {
            if (ReferenceEquals(levelsDoc, doc) && Levels.Count > 0) return Levels;
            var values = new List<double>();
            try
            {
                foreach (Element level in new FilteredElementCollector(doc).OfClass(typeof(Level)).ToElements())
                {
                    try
                    {
                        values.Add(((Level)level).ProjectElevation);
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
                values.Clear();
            }
            values.Sort();
            levelsDoc = doc;
            Levels.Clear();
            Levels.AddRange(values);
            return Levels;
        }

        private static Level LevelOfElement(Document doc, Element element)
        {
            Parameter parameter = ParamByBuiltin(element, LevelParams);
            if (parameter != null)
            {
                try
                {
                    Level level = doc.GetElement(parameter.AsElementId()) as Level;
                    if (level != null) return level;
                }
                catch (Exception)
                {
                }
            }
            try
            {
                return doc.GetElement(element.LevelId) as Level;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>Project elevation of the element's own reference level, in feet.</summary>
        public static double LevelElevation(Document doc, Element element)
        {
            Level level = LevelOfElement(doc, element);
            if (level != null)
            {
                try
                {
                    return level.ProjectElevation;
                }
                catch (Exception)
                {
                }
            }
            return NearestLevelBelow(doc, element);
        }

        /// <summary>Where an element names no level, the level at or below it stands in.</summary>
        private static double NearestLevelBelow(Document doc, Element element)
        {
            double z = 0.0;
            try
            {
                BoundingBoxXYZ box = element.get_BoundingBox(null);
                if (box != null) z = box.Min.Z;
            }
            catch (Exception)
            {
            }
            List<double> values = LevelElevations(doc);
            if (values.Count == 0) return 0.0;
            double? best = null;
            foreach (double elevation in values)
            {
                if (elevation <= z + MoCore.Eps) best = elevation;
                else break;
            }
            return best ?? values[0];
        }

        /// <summary>The element's own level: its name and project elevation.</summary>
        public static MoLevel LevelOf(Document doc, Element element)
        {
            var result = new MoLevel();
            Level level = LevelOfElement(doc, element);
            if (level != null)
            {
                try
                {
                    result.Name = level.Name;
                    result.Elevation = level.ProjectElevation;
                }
                catch (Exception)
                {
                }
            }
            return result;
        }

        // ======================================================================
        // measuring
        // ======================================================================

        private static BoundingBoxXYZ BoundingBox(Element element)
        {
            try
            {
                return element.get_BoundingBox(null);
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>The centreline of an MEP curve, or null.</summary>
        private static Curve MepCurveOf(Element element)
        {
            try
            {
                LocationCurve location = element.Location as LocationCurve;
                if (location == null) return null;
                bool hasConnectors = false;
                MEPCurve mep = element as MEPCurve;
                if (mep != null) hasConnectors = mep.ConnectorManager != null;
                else
                {
                    FabricationPart part = element as FabricationPart;
                    if (part != null) hasConnectors = part.ConnectorManager != null;
                }
                return hasConnectors ? location.Curve : null;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>
        /// Half the element's own vertical extent, from its size parameters, or null. The bounding box takes in
        /// insulation, lining and anything the family draws beyond the duct; the parameters are the bare service.
        /// </summary>
        private static double? HalfHeight(Element element, bool includeInsulation)
        {
            double height = ParamNumber(element, BoxSizeParams, 0.0);
            if (height <= MoCore.Eps) height = ParamNumber(element, RoundSizeParams, 0.0);
            if (height <= MoCore.Eps) return null;
            double half = height / 2.0;
            if (includeInsulation) half += ParamNumber(element, InsulationParams, 0.0);
            return half;
        }

        private static double HalfFromBox(BoundingBoxXYZ box, double centreZ)
        {
            if (box == null) return 0.0;
            try
            {
                return Math.Max(Math.Abs(box.Max.Z - centreZ), Math.Abs(centreZ - box.Min.Z));
            }
            catch (Exception)
            {
                return 0.0;
            }
        }

        /// <summary>Centreline Z of a sloping run directly under the picked point.</summary>
        private static double ElevationAt(Curve curve, XYZ point)
        {
            try
            {
                IntersectionResult result = curve.Project(point);
                if (result != null) return result.XYZPoint.Z;
            }
            catch (Exception)
            {
            }
            try
            {
                return curve.GetEndPoint(0).Z;
            }
            catch (Exception)
            {
                return 0.0;
            }
        }

        public sealed class MeasureOptions
        {
            public string Measure = "size";
            public bool IncludeInsulation;
            public double SlopeTolDeg = 0.5;
            public string PointMeasure = MoCore.FromSolid;
            public string FabMeasure = MoCore.FromParameters;
            public string HangerTop = MoCore.FromBearing;
            public string FramingMeasure = MoCore.FromTop;
        }

        /// <summary>
        /// Bottom, middle and top of an element in project feet. For a piece of equipment, a fixture, a device or a
        /// terminal, Middle is its offset from level (its insertion point), and Bottom and Top its real solid faces
        /// unless Settings says otherwise.
        /// </summary>
        public static MoMeasurement Measure(Document doc, Element element, MeasureOptions options, XYZ atPoint)
        {
            var result = new MoMeasurement();

            // Support steel first, before anything that reads a centreline: strut is drawn along a line, and a line is
            // exactly what made it measure at its middle and land half its depth proud of the duct it was put under.
            if (IsAncillaryFraming(element)) return MeasureFraming(element, options.FramingMeasure, result);

            Curve curve = MepCurveOf(element);
            if (curve != null)
            {
                XYZ start, end;
                try
                {
                    start = curve.GetEndPoint(0);
                    end = curve.GetEndPoint(1);
                }
                catch (Exception)
                {
                    result.Reason = "no usable centreline";
                    return result;
                }
                double rise = end.Z - start.Z;
                double run = Math.Sqrt((end.X - start.X) * (end.X - start.X) + (end.Y - start.Y) * (end.Y - start.Y));
                result.Slope = MoCore.SlopeDegrees(rise, run);

                double centre = (atPoint != null && Math.Abs(rise) > MoCore.Eps) ? ElevationAt(curve, atPoint) : (start.Z + end.Z) / 2.0;

                double? half = null;
                if (options.Measure != "box") half = HalfHeight(element, options.IncludeInsulation);
                if (!half.HasValue)
                {
                    half = HalfFromBox(BoundingBox(element), centre);
                    result.Route = "bounding box";
                }
                else result.Route = "size parameters";
                result.Bottom = centre - half.Value;
                result.Middle = centre;
                result.Top = centre + half.Value;
                result.HasOffsetParam = ParamByBuiltin(element, OffsetParams) != null;
                result.Ok = true;
                return result;
            }

            // A hanger is one height: the top face it holds its services on. Match a duct's bottom onto a hanger and
            // the bearer lands under the duct, which is the whole reason anybody aligns a hanger to anything.
            if (IsAHanger(element) && options.HangerTop != MoCore.FromBox)
            {
                double? height = null;
                string how = "";
                if (options.HangerTop == MoCore.FromBearing) height = BearingTop(element, out how);
                if (!height.HasValue)
                {
                    double[] extent = SolidExtent(element);
                    if (extent != null)
                    {
                        height = extent[1];
                        result.Route = "top of its solids";
                    }
                }
                else result.Route = how.Length > 0 ? how : "its bearing face";
                if (height.HasValue)
                {
                    result.Bottom = result.Middle = result.Top = height.Value;
                    result.Ok = true;
                    return result;
                }
            }

            // Hangers are fabrication parts too, but their own setting governs them from end to end.
            if (IsAFabricationPart(element) && !IsAHanger(element) && options.FabMeasure != MoCore.FromBox)
            {
                if (options.FabMeasure == MoCore.FromParameters)
                {
                    double bottom, top;
                    string how;
                    if (FabExtent(doc, element, out bottom, out top, out how))
                    {
                        result.Bottom = bottom;
                        result.Top = top;
                        result.Middle = (bottom + top) / 2.0;
                        result.Route = "top and bottom of part, " + how;
                        result.Ok = true;
                        return result;
                    }
                    result.Reason = how;
                }
                double[] solids = SolidExtent(element);
                if (solids != null)
                {
                    result.Bottom = solids[0];
                    result.Top = solids[1];
                    result.Middle = (solids[0] + solids[1]) / 2.0;
                    result.Route = "its solids";
                    result.Reason = "";
                    result.Ok = true;
                    return result;
                }
            }

            if (options.PointMeasure != MoCore.FromBox && MeasuredAtAPoint(element))
            {
                double? height = InsertionPoint(element);
                if (options.PointMeasure == MoCore.FromInsertion && height.HasValue)
                {
                    result.Bottom = result.Middle = result.Top = height.Value;
                    result.Route = "its offset from level";
                    result.Slope = 0.0;
                    result.Ok = true;
                    return result;
                }
                if (options.PointMeasure == MoCore.FromSolid)
                {
                    double[] extent = SolidExtent(element);
                    if (extent != null)
                    {
                        result.Bottom = extent[0];
                        result.Top = extent[1];
                        // Middle stays the family's own offset from level: the number in the properties palette, the one
                        // thing every family agrees on.
                        result.Middle = height ?? (extent[0] + extent[1]) / 2.0;
                        result.Route = height.HasValue ? "its solid faces, middle from its offset from level" : "its solid faces";
                        result.Slope = 0.0;
                        result.Ok = true;
                        return result;
                    }
                }
                if (height.HasValue)
                {
                    result.Bottom = result.Middle = result.Top = height.Value;
                    result.Route = "its offset from level";
                    result.Slope = 0.0;
                    result.Ok = true;
                    return result;
                }
            }

            BoundingBoxXYZ box = BoundingBox(element);
            if (box == null)
            {
                result.Reason = "no geometry to measure";
                return result;
            }
            result.Bottom = box.Min.Z;
            result.Top = box.Max.Z;
            result.Middle = (result.Bottom + result.Top) / 2.0;
            result.Route = "bounding box";
            result.Slope = 0.0;
            result.Ok = true;
            return result;
        }

        /// <summary>MEP ancillary framing: strut, channel, trapeze bars. Like a hanger it is one height, the face the service sits on.</summary>
        private static MoMeasurement MeasureFraming(Element element, string framingMeasure, MoMeasurement result)
        {
            result.Slope = 0.0;
            if (framingMeasure != MoCore.FromBox)
            {
                double[] extent = SolidExtent(element);
                if (extent != null)
                {
                    if (framingMeasure == MoCore.FromSolid)
                    {
                        result.Bottom = extent[0];
                        result.Top = extent[1];
                        result.Middle = (extent[0] + extent[1]) / 2.0;
                        result.Route = "its solids";
                    }
                    else
                    {
                        double? height = MoCore.BearingFromMembers(HangerMembers(element));
                        if (!height.HasValue)
                        {
                            height = extent[1];
                            result.Route = "the top face it supports on";
                        }
                        else result.Route = "the top of its bearer";
                        result.Bottom = result.Middle = result.Top = height.Value;
                    }
                    result.Ok = true;
                    return result;
                }
            }
            BoundingBoxXYZ box = BoundingBox(element);
            if (box == null)
            {
                result.Reason = "no geometry to measure";
                return result;
            }
            double low = box.Min.Z, high = box.Max.Z;
            if (framingMeasure == MoCore.FromBox)
            {
                result.Bottom = low;
                result.Middle = (low + high) / 2.0;
                result.Top = high;
                result.Route = "bounding box";
            }
            else
            {
                result.Bottom = result.Middle = result.Top = high;
                result.Route = "the top of its bounding box";
            }
            result.Ok = true;
            return result;
        }

        // ======================================================================
        // writing
        // ======================================================================

        /// <summary>
        /// How many of an element's connectors are joined to something. A fitting is a FamilyInstance and keeps its
        /// manager on MEPModel rather than on the element.
        /// </summary>
        public static int ConnectedCount(Element element)
        {
            ConnectorManager manager = null;
            try
            {
                MEPCurve curve = element as MEPCurve;
                if (curve != null) manager = curve.ConnectorManager;
            }
            catch (Exception)
            {
            }
            if (manager == null)
            {
                try
                {
                    FamilyInstance instance = element as FamilyInstance;
                    if (instance != null && instance.MEPModel != null) manager = instance.MEPModel.ConnectorManager;
                }
                catch (Exception)
                {
                }
            }
            if (manager == null) return 0;
            int count = 0;
            try
            {
                foreach (Connector connector in manager.Connectors)
                {
                    try
                    {
                        if (connector.IsConnected) count++;
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
                return 0;
            }
            return count;
        }

        public static bool InGroup(Element element)
        {
            try
            {
                return Eid(element.GroupId) > 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static bool IsPinned(Element element)
        {
            try
            {
                return element.Pinned;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static bool IsWorkshared(Document doc)
        {
            try
            {
                return doc.IsWorkshared;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static string Username(Document doc)
        {
            try
            {
                return doc.Application.Username.ToLowerInvariant();
            }
            catch (Exception)
            {
                return "";
            }
        }

        /// <summary>Who has this element, if anybody. Two locks are asked: its own checkout and its workset's owner.</summary>
        public static string OwnedByOther(Document doc, Element element, string me)
        {
            try
            {
                CheckoutStatus status = WorksharingUtils.GetCheckoutStatus(doc, element.Id);
                if (status == CheckoutStatus.OwnedByOtherUser)
                {
                    try
                    {
                        string owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, element.Id).Owner;
                        return string.IsNullOrEmpty(owner) ? "another user" : owner;
                    }
                    catch (Exception)
                    {
                        return "another user";
                    }
                }
            }
            catch (Exception)
            {
            }
            try
            {
                string owner = doc.GetWorksetTable().GetWorkset(element.WorksetId).Owner;
                if (!string.IsNullOrEmpty(owner) && owner.ToLowerInvariant() != (me ?? Username(doc))) return owner;
            }
            catch (Exception)
            {
            }
            return "";
        }

        private static Parameter Writable(Element element, string[] names)
        {
            Parameter parameter = ParamByBuiltin(element, names);
            if (parameter == null) return null;
            try
            {
                return parameter.IsReadOnly ? null : parameter;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>Something on the element that moves when it moves: its insertion point, or the bottom of its box.</summary>
        private static double? VerticalMarker(Element element)
        {
            double? height = InsertionPoint(element);
            if (height.HasValue) return height;
            BoundingBoxXYZ box = BoundingBox(element);
            return box == null ? (double?)null : box.Min.Z;
        }

        private static void Regenerate(Document doc)
        {
            try
            {
                doc.Regenerate();
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Move a hosted family through its offset from host. Which way that parameter runs depends on which way the
        /// host faces, so: write it one way, look at where the family went, turn it round if it went the other.
        /// Returns the route, or "" where it moved nothing either way.
        /// </summary>
        private static string ShiftOffHost(Document doc, Element element, Parameter parameter, double deltaFt)
        {
            double current;
            try
            {
                current = parameter.AsDouble();
            }
            catch (Exception)
            {
                return "";
            }
            double? before = VerticalMarker(element);
            try
            {
                parameter.Set(current + deltaFt);
            }
            catch (Exception)
            {
                return "";
            }
            Regenerate(doc);
            double? after = VerticalMarker(element);
            if (!before.HasValue || !after.HasValue) return "offset from host";
            int direction = MoCore.HostOffsetDirection(deltaFt, after.Value - before.Value);
            if (direction > 0) return "offset from host";
            try
            {
                if (direction < 0)
                {
                    parameter.Set(current - deltaFt);
                    Regenerate(doc);
                    return "offset from host, which runs down off its host";
                }
                parameter.Set(current);
                Regenerate(doc);
            }
            catch (Exception)
            {
            }
            return "";
        }

        /// <summary>
        /// Move an element up or down by delta. The offset parameter first (relative to the element's own level, keeps
        /// connections intact); then elevation from level; then offset from host; then the element is moved.
        /// </summary>
        public static string Shift(Document doc, Element element, double deltaFt)
        {
            if (Math.Abs(deltaFt) <= MoCore.TolFt) return "already there";

            Parameter parameter = Writable(element, OffsetParams);
            if (parameter != null)
            {
                try
                {
                    parameter.Set(parameter.AsDouble() + deltaFt);
                    return "offset parameter";
                }
                catch (Exception)
                {
                }
            }

            // A family on a level: its elevation from that level. Everything is in project elevations, so the delta is
            // the same number whichever level the datum came off.
            parameter = Writable(element, LevelOffsetParams);
            if (parameter != null)
            {
                try
                {
                    parameter.Set(parameter.AsDouble() + deltaFt);
                    return "elevation from level";
                }
                catch (Exception)
                {
                }
            }

            // A family on a face or a work plane: Revit will not move it off its host, so the move goes through its
            // offset from host, which runs along the host's normal and so downward under a ceiling.
            parameter = Writable(element, HostOffsetParams);
            if (parameter != null)
            {
                string route = ShiftOffHost(doc, element, parameter, deltaFt);
                if (route.Length > 0) return route;
            }

            try
            {
                ElementTransformUtils.MoveElement(doc, element.Id, new XYZ(0.0, 0.0, deltaFt));
                return "moved";
            }
            catch (Exception err)
            {
                throw new Exception("Revit refused the move: " + err.Message);
            }
        }

        /// <summary>
        /// After a hanger moves, hold its rod tops where they were: the hanger hangs from the soffit, so the rods
        /// change length by the move. Rods Revit hosts re-solve themselves; rods set to manual are re-cut here.
        /// </summary>
        public static string KeepRodTops(Element element, double deltaFt)
        {
            if (Math.Abs(deltaFt) <= MoCore.TolFt) return "";
            FabricationPart part = element as FabricationPart;
            if (part == null) return "";
            FabricationRodInfo info;
            try
            {
                info = part.GetRodInfo();
            }
            catch (Exception)
            {
                return "";
            }
            if (info == null) return "";
            try
            {
                if (info.CanRodsBeHosted) return "its rods are hosted, so Revit re-solved them";
            }
            catch (Exception)
            {
            }
            int count;
            try
            {
                count = info.RodCount;
            }
            catch (Exception)
            {
                return "";
            }
            int recut = 0, refused = 0;
            for (int index = 0; index < count; index++)
            {
                double length;
                try
                {
                    length = info.GetRodLength(index);
                }
                catch (Exception)
                {
                    continue;
                }
                double? wanted = MoCore.RodLengthAfter(length, deltaFt);
                if (!wanted.HasValue)
                {
                    refused++;
                    continue;
                }
                try
                {
                    info.SetRodLength(index, wanted.Value);
                    recut++;
                }
                catch (Exception)
                {
                    refused++;
                }
            }
            if (refused > 0 && recut == 0) return "its rods would have no length left and were not re-cut";
            if (refused > 0) return recut + " rod(s) re-cut, " + refused + " would have no length left";
            if (recut > 0) return recut + " rod(s) re-cut to keep their tops at the soffit";
            return "";
        }

        /// <summary>
        /// Borrow before writing, in one call for however many elements. On a workshared model a write to an element
        /// nobody has borrowed writes nothing and says nothing. Skipped on a model that is not workshared.
        /// </summary>
        public static bool Checkout(Document doc, IEnumerable<ElementId> ids)
        {
            if (!IsWorkshared(doc)) return false;
            try
            {
                WorksharingUtils.CheckoutElements(doc, new List<ElementId>(ids));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }
    }
}
