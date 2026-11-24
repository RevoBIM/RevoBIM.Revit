using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;

namespace RevoBIM.Tools.FamilyFindReplace
{
    /// <summary>Where the replacement goes: point, level, host or work plane, and which way round it reads.</summary>
    public static partial class FfrCore
    {
        public const string RefFacing = "facing";
        public const string RefHand = "hand";
        public const string RefBasisX = "basisx";

        private static XYZ PlanVector(Element instance, string kind)
        {
            XYZ vector = null;
            try
            {
                var fi = instance as FamilyInstance;
                if (kind == RefFacing) vector = fi == null ? null : fi.FacingOrientation;
                else if (kind == RefHand) vector = fi == null ? null : fi.HandOrientation;
                else
                {
                    var inst = instance as Instance;
                    vector = inst == null ? null : inst.GetTransform().BasisX;
                }
            }
            catch (Exception)
            {
                return null;
            }
            if (vector == null) return null;
            var flat = new XYZ(vector.X, vector.Y, 0.0);
            try
            {
                if (flat.GetLength() < 1.0e-7) return null;
                return flat.Normalize();
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>
        /// Which axis to read the plan rotation off. A wall-hosted device faces out of the wall, so its facing
        /// direction is the one worth keeping. A ceiling-hosted fitting faces straight down and has no plan
        /// facing at all, so its hand direction stands in.
        /// </summary>
        public static string ReferenceKind(Element instance)
        {
            foreach (string kind in new[] { RefFacing, RefHand, RefBasisX })
                if (PlanVector(instance, kind) != null) return kind;
            return RefBasisX;
        }

        public static XYZ InstancePoint(Element instance)
        {
            if (instance == null) return null;
            var location = instance.Location as LocationPoint;
            return location == null ? null : location.Point;
        }

        /// <summary>
        /// Which level the replacement is associated with. A face-based family hosted to a face often carries no
        /// usable level, and where it does the level frequently belongs to the host rather than the element, so
        /// the nearest level at or below the insertion point is the rule that gets both cases right.
        /// With preferBelow off the original's own level association is kept where it has one.
        /// </summary>
        public static Level ResolveLevel(Document doc, Element instance, XYZ point, bool preferBelow)
        {
            if (preferBelow)
            {
                Level below = LevelBelow(doc, point);
                if (below != null) return below;
            }
            try
            {
                ElementId levelId = instance.LevelId;
                if (levelId != null && Eid(levelId) > 0)
                {
                    var level = doc.GetElement(levelId) as Level;
                    if (level != null) return level;
                }
            }
            catch (Exception)
            {
            }
            foreach (BuiltInParameter bip in new[] { BuiltInParameter.FAMILY_LEVEL_PARAM, BuiltInParameter.SCHEDULE_LEVEL_PARAM,
                                                     BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM })
            {
                try
                {
                    Parameter param = instance.get_Parameter(bip);
                    if (param != null && param.HasValue)
                    {
                        var level = doc.GetElement(param.AsElementId()) as Level;
                        if (level != null) return level;
                    }
                }
                catch (Exception)
                {
                }
            }
            try
            {
                var fi = instance as FamilyInstance;
                if (fi != null && fi.Host != null)
                {
                    var level = doc.GetElement(fi.Host.LevelId) as Level;
                    if (level != null) return level;
                }
            }
            catch (Exception)
            {
            }
            return LevelBelow(doc, point) ?? NearestLevel(doc, point);
        }

        /// <summary>A level within this of the insertion point counts as being at it (1mm in feet).</summary>
        private static readonly double LevelTolFt = 1.0 / MmPerFt;

        /// <summary>
        /// The highest level at or below the point; falls back to the lowest level in the model where the point
        /// sits below all of them - a basement slab modelled below its own level still has to be associated.
        /// </summary>
        public static Level LevelBelow(Document doc, XYZ point)
        {
            if (point == null) return null;
            double z = point.Z;
            Level best = null, lowest = null;
            double bestElev = 0, lowestElev = 0;
            foreach (Element element in new FilteredElementCollector(doc).OfClass(typeof(Level)))
            {
                var level = element as Level;
                if (level == null) continue;
                double elev;
                try
                {
                    elev = level.ProjectElevation;
                }
                catch (Exception)
                {
                    continue;
                }
                if (lowest == null || elev < lowestElev)
                {
                    lowest = level;
                    lowestElev = elev;
                }
                if (elev > z + LevelTolFt) continue;
                if (best == null || elev > bestElev)
                {
                    best = level;
                    bestElev = elev;
                }
            }
            return best ?? lowest;
        }

        public static Level NearestLevel(Document doc, XYZ point)
        {
            Level best = null;
            double bestGap = 0;
            double z = point != null ? point.Z : 0.0;
            foreach (Element element in new FilteredElementCollector(doc).OfClass(typeof(Level)))
            {
                var level = element as Level;
                if (level == null) continue;
                try
                {
                    double gap = Math.Abs(level.ProjectElevation - z);
                    if (best == null || gap < bestGap)
                    {
                        best = level;
                        bestGap = gap;
                    }
                }
                catch (Exception)
                {
                }
            }
            return best;
        }

        /// <summary>
        /// Write the level onto every writable level parameter the family has. Passing a level to
        /// NewFamilyInstance does not always take, and a family can carry both Level and Schedule Level.
        /// </summary>
        private static string ForceLevel(Element element, Level level)
        {
            if (level == null || element == null) return null;
            bool written = false;
            foreach (BuiltInParameter bip in new[] { BuiltInParameter.FAMILY_LEVEL_PARAM, BuiltInParameter.SCHEDULE_LEVEL_PARAM,
                                                     BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM,
                                                     BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM })
            {
                Parameter param;
                try
                {
                    param = element.get_Parameter(bip);
                }
                catch (Exception)
                {
                    continue;
                }
                if (param == null || param.IsReadOnly || param.StorageType != StorageType.ElementId) continue;
                try
                {
                    if (Eid(param.AsElementId()) != Eid(level.Id)) param.Set(level.Id);
                    written = true;
                }
                catch (Exception)
                {
                }
            }
            return written ? Name(level) : null;
        }

        /// <summary>Placement types that genuinely want a host element. Everything else must never be handed one.</summary>
        private static bool WantsHost(string placement) { return placement == "OneLevelBasedHosted"; }

        /// <summary>Placement types that want a work plane or a face rather than a host element.</summary>
        private static bool WantsPlane(string placement) { return placement == "WorkPlaneBased"; }

        private static readonly Dictionary<long, SketchPlane> SketchCache = new Dictionary<long, SketchPlane>();

        /// <summary>A horizontal work plane at the point, one per elevation per run, so a run over three hundred fittings leaves a handful.</summary>
        private static SketchPlane SketchPlaneAt(Document doc, XYZ point)
        {
            long key = (long)Math.Round(point.Z * MmPerFt);
            SketchPlane cached;
            if (SketchCache.TryGetValue(key, out cached))
            {
                try
                {
                    if (doc.GetElement(cached.Id) != null) return cached;
                }
                catch (Exception)
                {
                }
            }
            try
            {
                Plane plane = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(point.X, point.Y, point.Z));
                SketchPlane sketch = SketchPlane.Create(doc, plane);
                SketchCache[key] = sketch;
                return sketch;
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static List<GeometryObject> WalkGeometry(IEnumerable<GeometryObject> items)
        {
            var result = new List<GeometryObject>();
            foreach (GeometryObject item in items)
            {
                var instance = item as GeometryInstance;
                if (instance != null)
                {
                    GeometryElement nested = null;
                    try
                    {
                        nested = instance.GetInstanceGeometry();
                    }
                    catch (Exception)
                    {
                    }
                    if (nested != null)
                    {
                        result.AddRange(WalkGeometry(nested));
                        continue;
                    }
                }
                result.Add(item);
            }
            return result;
        }

        /// <summary>The face of the original's host nearest the insertion point, with a direction lying in it.</summary>
        private static Reference HostFaceReference(Element host, XYZ point, out XYZ direction)
        {
            direction = null;
            if (host == null) return null;
            GeometryElement geometry;
            try
            {
                var options = new Options { ComputeReferences = true, IncludeNonVisibleObjects = true };
                geometry = host.get_Geometry(options);
            }
            catch (Exception)
            {
                return null;
            }
            if (geometry == null) return null;

            Face best = null;
            double bestGap = double.MaxValue;
            foreach (GeometryObject item in WalkGeometry(geometry))
            {
                var solid = item as Solid;
                if (solid == null) continue;
                foreach (Face face in solid.Faces)
                {
                    try
                    {
                        if (face.Reference == null) continue;
                        IntersectionResult projected = face.Project(point);
                        if (projected == null) continue;
                        if (best == null || projected.Distance < bestGap)
                        {
                            best = face;
                            bestGap = projected.Distance;
                        }
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            if (best == null) return null;
            XYZ normal;
            try
            {
                normal = best.ComputeNormal(best.Project(point).UVPoint);
            }
            catch (Exception)
            {
                normal = XYZ.BasisZ;
            }
            direction = new XYZ(-normal.Y, normal.X, 0.0);
            try
            {
                direction = direction.GetLength() < 1.0e-7 ? XYZ.BasisX : direction.Normalize();
            }
            catch (Exception)
            {
                direction = XYZ.BasisX;
            }
            return best.Reference;
        }

        /// <summary>
        /// One placement route, isolated. A route can return an element and only then have Revit post an error at
        /// regeneration; without a sub-transaction round each attempt that failure lands on the whole run and the
        /// cascade never gets to try the next route. Regenerating inside the attempt forces the error to surface here.
        /// </summary>
        private static Element AttemptPlace(Document doc, Func<Element> make, out string message)
        {
            message = "";
            var sub = new SubTransaction(doc);
            try
            {
                sub.Start();
            }
            catch (Exception err)
            {
                message = err.Message;
                return null;
            }
            try
            {
                Element created = make();
                if (created == null)
                {
                    sub.RollBack();
                    message = "the call returned nothing";
                    return null;
                }
                doc.Regenerate();
                sub.Commit();
                return created;
            }
            catch (Exception err)
            {
                try
                {
                    sub.RollBack();
                }
                catch (Exception)
                {
                }
                message = err.Message;
                return null;
            }
        }

        /// <summary>
        /// Place the replacement, choosing routes by the target's placement type. A host element is only ever
        /// offered to a family whose placement type takes one: handing the original's ceiling to a level based
        /// or work plane based family is what Revit refuses with "Can't use this type of host".
        /// </summary>
        public static Element CreateReplacement(Document doc, FamilySymbol symbol, XYZ point, Level level, Element host, string placement,
                                                out string route, List<string> errors)
        {
            var creator = doc.Create;
            var attempts = new List<KeyValuePair<string, Func<Element>>>();
            bool wantsHost = WantsHost(placement);
            bool wantsPlane = WantsPlane(placement);

            if (wantsHost && host != null)
            {
                if (level != null)
                    attempts.Add(new KeyValuePair<string, Func<Element>>("host and level",
                        () => creator.NewFamilyInstance(point, symbol, host, level, StructuralType.NonStructural)));
                attempts.Add(new KeyValuePair<string, Func<Element>>("host",
                    () => creator.NewFamilyInstance(point, symbol, host, StructuralType.NonStructural)));
            }

            if (wantsPlane)
            {
                // the work plane route first, then the original's own face
                SketchPlane sketch = SketchPlaneAt(doc, point);
                if (sketch != null)
                    attempts.Add(new KeyValuePair<string, Func<Element>>("work plane",
                        () => creator.NewFamilyInstance(point, symbol, (Element)sketch, StructuralType.NonStructural)));
            }

            if (wantsHost || wantsPlane)
            {
                XYZ direction;
                Reference reference = HostFaceReference(host, point, out direction);
                if (reference != null)
                    attempts.Add(new KeyValuePair<string, Func<Element>>("host face",
                        () => creator.NewFamilyInstance(reference, point, direction, symbol)));
            }

            // un-hosted routes: the ones a level based replacement wants, and no host is passed to any of them
            if (level != null)
                attempts.Add(new KeyValuePair<string, Func<Element>>("level",
                    () => creator.NewFamilyInstance(point, symbol, level, StructuralType.NonStructural)));
            attempts.Add(new KeyValuePair<string, Func<Element>>("point",
                () => creator.NewFamilyInstance(point, symbol, StructuralType.NonStructural)));

            // last resort for a family reporting a placement type we did not expect: a wrong work plane can be moved, a wrong host cannot
            if (!wantsPlane && !wantsHost)
            {
                SketchPlane sketch = SketchPlaneAt(doc, point);
                if (sketch != null)
                    attempts.Add(new KeyValuePair<string, Func<Element>>("work plane",
                        () => creator.NewFamilyInstance(point, symbol, (Element)sketch, StructuralType.NonStructural)));
            }

            foreach (KeyValuePair<string, Func<Element>> attempt in attempts)
            {
                string message;
                Element created = AttemptPlace(doc, attempt.Value, out message);
                if (created != null)
                {
                    route = attempt.Key;
                    return created;
                }
                errors.Add(attempt.Key + ": " + message);
            }
            route = "";
            return null;
        }

        /// <summary>Nudge the placed element onto the exact point, plus any Z offset.</summary>
        private static bool PlaceAt(Document doc, Element newElement, XYZ point, double zOffsetFt)
        {
            var target = new XYZ(point.X, point.Y, point.Z + zOffsetFt);
            try
            {
                XYZ actual = InstancePoint(newElement);
                if (actual == null) return false;
                var delta = new XYZ(target.X - actual.X, target.Y - actual.Y, target.Z - actual.Z);
                if (delta.GetLength() > PointTolFt) ElementTransformUtils.MoveElement(doc, newElement.Id, delta);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Turn the replacement so it reads the same way round as the original, measured on the same axis.</summary>
        private static double MatchRotation(Document doc, Element source, Element newElement, string kind, double extraRadians)
        {
            XYZ point = InstancePoint(newElement);
            if (point == null) return 0.0;
            XYZ sourceDir = PlanVector(source, kind);
            XYZ newDir = PlanVector(newElement, kind);
            double angle = 0.0;
            if (sourceDir != null && newDir != null) angle = SignedPlanAngle(newDir, sourceDir);
            angle += extraRadians;
            if (Math.Abs(angle) < 1.0e-9) return 0.0;
            Line axis = Line.CreateBound(point, new XYZ(point.X, point.Y, point.Z + 1.0));
            ElementTransformUtils.RotateElement(doc, newElement.Id, axis, angle);
            return angle;
        }

        // ---- probing an unplaced replacement family ---------------------------------------------------

        public sealed class Probe
        {
            public bool Ok;
            public Dictionary<string, ParamInfo> ParamInfos = new Dictionary<string, ParamInfo>();
            public ElecProfile Elec = new ElecProfile();
            public string Placement = "Unknown";
            public string Note = "";
        }

        /// <summary>
        /// Read the replacement family's instance parameters and connectors. An already placed instance is read
        /// for free. Where the family is not placed anywhere yet, one is put down inside a transaction that is
        /// then rolled back, so the model is left exactly as it was.
        /// </summary>
        public static Probe ProbeSymbol(Document doc, ElementId symbolId, View view)
        {
            var probe = new Probe();
            var symbol = doc.GetElement(symbolId) as FamilySymbol;
            if (symbol == null)
            {
                probe.Note = "The replacement type could not be read.";
                return probe;
            }
            probe.Placement = PlacementName(symbol);

            Element existing = null;
            try
            {
                existing = new FilteredElementCollector(doc).WherePasses(new FamilyInstanceFilter(doc, symbolId)).FirstOrDefault();
            }
            catch (Exception)
            {
                existing = null;
            }
            if (existing != null)
            {
                probe.ParamInfos = ReadParamInfos(existing);
                probe.Elec = ElectricalProfile(existing);
                probe.Ok = true;
                probe.Note = "Read from a placed instance.";
                return probe;
            }

            var transaction = new Transaction(doc, "RevoBIM probe replacement family");
            try
            {
                transaction.Start();
                if (!symbol.IsActive)
                {
                    symbol.Activate();
                    doc.Regenerate();
                }
                Element created;
                var errors = new List<string>();
                if (probe.Placement == "ViewBased" && view != null)
                {
                    // a detail item is placed in a view, not on a level
                    string message;
                    created = AttemptPlace(doc, () => doc.Create.NewFamilyInstance(XYZ.Zero, symbol, view), out message);
                    if (message.Length > 0) errors.Add(message);
                }
                else
                {
                    Level level = NearestLevel(doc, XYZ.Zero);
                    string route;
                    created = CreateReplacement(doc, symbol, XYZ.Zero, level, null, probe.Placement, out route, errors);
                }
                if (created == null)
                {
                    probe.Note = "The replacement family could not be test-placed, so its parameters are unknown until it is used. " +
                                 "Place one in the model and reselect it.";
                    if (errors.Count > 0) probe.Note += " (" + errors[errors.Count - 1] + ")";
                }
                else
                {
                    doc.Regenerate();
                    probe.ParamInfos = ReadParamInfos(created);
                    probe.Elec = ElectricalProfile(created);
                    probe.Ok = true;
                    probe.Note = "Read from a temporary instance, rolled back.";
                }
            }
            catch (Exception err)
            {
                probe.Note = "The replacement family could not be read: " + err.Message;
            }
            finally
            {
                try
                {
                    transaction.RollBack();
                }
                catch (Exception)
                {
                }
            }
            return probe;
        }
    }
}
