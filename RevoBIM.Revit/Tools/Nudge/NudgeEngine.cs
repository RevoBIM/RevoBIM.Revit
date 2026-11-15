using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.DB.Mechanical;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.Exceptions;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.Nudge
{
    /// <summary>
    /// Move elements up or down by a fixed amount. Port of revobim.nudge.
    ///
    /// What can be nudged:
    ///   pipes, ducts, cable tray, conduit and flex                       always
    ///   fabrication ductwork, pipework and containment straights         always
    ///   their fittings and accessories, equipment, fixtures, sprinklers,
    ///   generic models                                                   "fittings"
    ///   fabrication fittings, fabrication hangers, MEP ancillary framing "fabrication"
    ///
    /// How the elevation is written, first route that applies wins:
    ///   1 Middle Elevation; 2 Start + End Elevation; 3 Offset from host / level;
    ///   4 Start + End Level Offset (line-based framing); 5 measured move in Z.
    /// Fabrication parts always take route 5: their Top/Bottom of Part are measured from the
    /// part's level on some releases and from the project base on others, so the part's own
    /// centreline is measured against its level and the difference moved instead.
    /// A fabrication hanger hangs from the soffit, so after it moves its manual rods are re-cut.
    /// </summary>
    public static class NudgeEngine
    {
        public const double Mm = 1.0 / 304.8;
        public const string TransactionName = "RevoBIM Nudge";

        // a manual hanger rod shorter than this after a re-cut is left alone
        private const double MinRodMm = 10.0;

        private static readonly HashSet<long> FittingCats = Ids(
            BuiltInCategory.OST_PipeFitting, BuiltInCategory.OST_DuctFitting,
            BuiltInCategory.OST_CableTrayFitting, BuiltInCategory.OST_ConduitFitting,
            BuiltInCategory.OST_PipeAccessory, BuiltInCategory.OST_DuctAccessory,
            BuiltInCategory.OST_MechanicalEquipment, BuiltInCategory.OST_ElectricalEquipment,
            BuiltInCategory.OST_ElectricalFixtures, BuiltInCategory.OST_PlumbingFixtures,
            BuiltInCategory.OST_LightingFixtures, BuiltInCategory.OST_Sprinklers,
            BuiltInCategory.OST_GenericModel);

        private static readonly HashSet<long> FabRunCats = Ids(
            BuiltInCategory.OST_FabricationDuctwork, BuiltInCategory.OST_FabricationPipework,
            BuiltInCategory.OST_FabricationContainment);

        private static readonly HashSet<long> HangerCats = Ids(BuiltInCategory.OST_FabricationHangers);
        private static readonly HashSet<long> FramingCats = Ids(BuiltInCategory.OST_MEPAncillaryFraming);

        private static HashSet<long> Ids(params BuiltInCategory[] categories)
        {
            return new HashSet<long>(categories.Select(c => (long)c));
        }

        // ------------------------------------------------------------------ classification

        private static long CategoryId(Element element)
        {
            try
            {
                Category category = element.Category;
                return category == null ? long.MinValue : category.Id.Value;
            }
            catch (Exception)
            {
                return long.MinValue;
            }
        }

        private static bool IsFabPart(Element element) => element is FabricationPart;

        private static bool IsHanger(Element element)
        {
            if (!(element is FabricationPart part)) return false;
            try
            {
                return part.IsAHanger();
            }
            catch (Exception)
            {
                return HangerCats.Contains(CategoryId(element));
            }
        }

        private static bool IsFabStraight(Element element)
        {
            try
            {
                return ((FabricationPart)element).IsAStraight();
            }
            catch (Exception)
            {
                // no answer either way: treat it as a run rather than hide it
                return true;
            }
        }

        private static bool IsRun(Element element) =>
            element is Pipe || element is Duct || element is CableTray || element is Conduit ||
            element is FlexPipe || element is FlexDuct;

        public static bool IsNudgeable(Element element, bool allowFittings, bool allowFabrication)
        {
            if (element == null) return false;
            if (IsRun(element)) return true;

            long cat = CategoryId(element);
            if (cat == long.MinValue) return false;

            // a fabrication straight is a run and always allowed; its fittings go with the fabrication setting
            if (FabRunCats.Contains(cat)) return IsFabStraight(element) || allowFabrication;
            if (HangerCats.Contains(cat) || FramingCats.Contains(cat)) return allowFabrication;
            if (FittingCats.Contains(cat)) return allowFittings;
            return false;
        }

        private class NudgeFilter : ISelectionFilter
        {
            private readonly bool fittings;
            private readonly bool fabrication;

            public NudgeFilter(bool allowFittings, bool allowFabrication)
            {
                fittings = allowFittings;
                fabrication = allowFabrication;
            }

            public bool AllowElement(Element element) => IsNudgeable(element, fittings, fabrication);
            public bool AllowReference(Reference reference, XYZ position) => false;
        }

        // ------------------------------------------------------------------ rounding

        private static double SnapTo(double valueFt, double snapFt)
        {
            if (snapFt <= 0) return valueFt;
            return Math.Floor(valueFt / snapFt + 0.5) * snapFt;
        }

        /// <summary>Where the element should end up, snapped, given where it is now.</summary>
        private static double SnappedTarget(double currentFt, double deltaFt, double snapFt)
        {
            double target = currentFt + deltaFt;
            if (snapFt <= 0) return target;

            double direction = deltaFt > 0 ? 1.0 : -1.0;
            double snapped = SnapTo(target, snapFt);

            // a small step against an untidy start can round back to the original position:
            // move it a whole snap rather than appear to do nothing
            if (Math.Abs(snapped - currentFt) < 1e-9)
            {
                snapped = SnapTo(currentFt + direction * snapFt, snapFt);
                if (Math.Abs(snapped - currentFt) < 1e-9)
                    snapped = currentFt + direction * snapFt;
            }
            return snapped;
        }

        // ------------------------------------------------------------------ measuring

        /// <summary>Project elevation of the element's own level, or 0. Never Level.Elevation: on a
        /// survey-point-based project that reports shared coordinates and comes back tens of metres out.</summary>
        private static double LevelElevation(Element element)
        {
            try
            {
                ElementId levelId = element.LevelId;
                if (levelId == null || levelId == ElementId.InvalidElementId) return 0.0;
                return element.Document.GetElement(levelId) is Level level ? level.ProjectElevation : 0.0;
            }
            catch (Exception)
            {
                return 0.0;
            }
        }

        private static double? ConnectorMidZ(Element element)
        {
            ConnectorManager manager = null;
            try
            {
                if (element is FabricationPart part) manager = part.ConnectorManager;
                else if (element is FamilyInstance instance) manager = instance.MEPModel?.ConnectorManager;
            }
            catch (Exception)
            {
                manager = null;
            }
            if (manager == null) return null;
            double total = 0.0;
            int count = 0;
            try
            {
                foreach (Connector connector in manager.Connectors)
                {
                    try
                    {
                        total += connector.Origin.Z;
                        count++;
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
                return null;
            }
            return count > 0 ? total / count : (double?)null;
        }

        /// <summary>A height that moves one-for-one with the element, in project terms.</summary>
        private static double? ReferenceZ(Element element)
        {
            if (IsFabPart(element) && !IsHanger(element))
            {
                double? z = ConnectorMidZ(element);
                if (z != null) return z;
            }

            Location location = element.Location;
            if (location is LocationPoint point) return point.Point.Z;
            if (location is LocationCurve curve)
            {
                try
                {
                    return curve.Curve.Evaluate(0.5, true).Z;
                }
                catch (Exception)
                {
                }
            }

            double? mid = ConnectorMidZ(element);
            if (mid != null) return mid;

            try
            {
                BoundingBoxXYZ box = element.get_BoundingBox(null);
                if (box != null) return (box.Min.Z + box.Max.Z) / 2.0;
            }
            catch (Exception)
            {
            }
            return null;
        }

        // ------------------------------------------------------------------ the move

        private static Parameter Writable(Element element, BuiltInParameter id)
        {
            Parameter param;
            try
            {
                param = element.get_Parameter(id);
            }
            catch (Exception)
            {
                return null;
            }
            if (param == null || param.IsReadOnly || param.StorageType != StorageType.Double) return null;
            return param;
        }

        /// <summary>Snap the first of a pair and shift the second by the same amount.</summary>
        private static bool ShiftPair(Element element, BuiltInParameter firstId, BuiltInParameter secondId,
                                      double deltaFt, double snapFt)
        {
            Parameter first = Writable(element, firstId);
            Parameter second = Writable(element, secondId);
            if (first == null || second == null) return false;
            double was = first.AsDouble();
            double now = SnappedTarget(was, deltaFt, snapFt);
            first.Set(now);
            second.Set(second.AsDouble() + (now - was));
            return true;
        }

        /// <summary>Measure the element against its level, snap that, move the difference.
        /// Returns the distance actually moved, or null.</summary>
        private static double? MoveMeasured(Element element, double deltaFt, double snapFt)
        {
            double? reference = ReferenceZ(element);
            double move;
            if (reference == null)
            {
                // nothing to measure: snap the step instead of the result
                move = deltaFt;
                if (snapFt > 0)
                {
                    double direction = deltaFt > 0 ? 1.0 : -1.0;
                    move = SnapTo(deltaFt, snapFt);
                    if (Math.Abs(move) < 1e-9) move = direction * snapFt;
                }
            }
            else
            {
                double offset = reference.Value - LevelElevation(element);
                move = SnappedTarget(offset, deltaFt, snapFt) - offset;
            }

            if (Math.Abs(move) < 1e-9) return null;

            bool repin = false;
            try
            {
                if (element.Pinned)
                {
                    element.Pinned = false;
                    repin = true;
                }
            }
            catch (Exception)
            {
            }
            try
            {
                ElementTransformUtils.MoveElement(element.Document, element.Id, new XYZ(0, 0, move));
            }
            finally
            {
                if (repin)
                {
                    try
                    {
                        element.Pinned = true;
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            return move;
        }

        /// <summary>Keep a hanger's rod tops at the soffit after it moved: raising shortens the rods,
        /// lowering lengthens them. Hosted rods re-solve themselves, so only manual rods are touched.
        /// A rod that would come out shorter than MinRodMm is left as it was. Returns (recut, left).</summary>
        private static (int Recut, int Left) RecutRods(FabricationPart hanger, double movedFt)
        {
            int recut = 0, left = 0;
            FabricationRodInfo info;
            try
            {
                info = hanger.GetRodInfo();
            }
            catch (Exception)
            {
                return (0, 0);
            }
            if (info == null) return (0, 0);
            try
            {
                if (info.CanRodsBeHosted) return (0, 0);
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
                return (0, 0);
            }

            for (int index = 0; index < count; index++)
            {
                double length;
                try
                {
                    length = info.GetRodLength(index);
                }
                catch (Exception)
                {
                    left++;
                    continue;
                }
                double newLength = length - movedFt;
                if (newLength < MinRodMm * Mm)
                {
                    left++;
                    continue;
                }
                try
                {
                    info.SetRodLength(index, newLength);
                    recut++;
                }
                catch (Exception)
                {
                    left++;
                }
            }
            return (recut, left);
        }

        /// <summary>Move one element by deltaFt (signed, internal feet). Must be called inside an open
        /// transaction. Returns the route used, or null if nothing could be written.</summary>
        public static string Shift(Element element, double deltaFt, double snapFt = 0.0, bool recutRods = true)
        {
            if (element == null) return null;

            // fabrication parts: measured, never written through Top/Bottom of Part
            if (IsFabPart(element))
            {
                double? moved = MoveMeasured(element, deltaFt, snapFt);
                if (moved == null) return null;
                if (recutRods && IsHanger(element))
                {
                    var (recut, left) = RecutRods((FabricationPart)element, moved.Value);
                    if (left > 0) return "fabrication hanger, " + left + " rod(s) left - too short";
                    if (recut > 0) return "fabrication hanger, " + recut + " rod(s) re-cut";
                    return "fabrication hanger";
                }
                return "fabrication part";
            }

            // 1. middle elevation: the normal case for a level run
            Parameter mid = Writable(element, BuiltInParameter.RBS_OFFSET_PARAM);
            if (mid != null)
            {
                mid.Set(SnappedTarget(mid.AsDouble(), deltaFt, snapFt));
                return "middle elevation";
            }

            // 2. sloped run: start snapped, end shifted the same, slope kept
            if (ShiftPair(element, BuiltInParameter.RBS_START_OFFSET_PARAM, BuiltInParameter.RBS_END_OFFSET_PARAM,
                          deltaFt, snapFt))
                return "start and end elevation";

            // 3. offset from host or level: fittings, accessories, family instances, face-hosted framing
            foreach (BuiltInParameter id in new[] { BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM,
                                                    BuiltInParameter.INSTANCE_ELEVATION_PARAM })
            {
                Parameter param = Writable(element, id);
                if (param != null)
                {
                    param.Set(SnappedTarget(param.AsDouble(), deltaFt, snapFt));
                    return "offset from level";
                }
            }

            // 4. line-based ancillary framing: both end offsets together
            if (ShiftPair(element, BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION,
                          BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION, deltaFt, snapFt))
                return "start and end level offset";

            // 5. measured move in Z
            try
            {
                if (MoveMeasured(element, deltaFt, snapFt) != null) return "moved in Z";
            }
            catch (Exception)
            {
            }
            return null;
        }

        private static string Describe(Element element)
        {
            string name = "Element", category = "Element";
            try { name = element.Name; } catch (Exception) { }
            try { category = element.Category.Name; } catch (Exception) { }
            return category + ": " + name;
        }

        // ------------------------------------------------------------------ mode one: the selection

        /// <summary>Shift every currently selected element once. Returns (moved, skipped). The
        /// selection is put back afterwards, so pressing again moves the same elements again.</summary>
        public static (int Moved, int Skipped) NudgeSelection(UIDocument uidoc, double stepMm, bool up, double snapMm,
                                                              bool allowFittings, bool keepSelection,
                                                              bool allowFabrication, bool recutRods)
        {
            Document doc = uidoc.Document;
            Selection selection = uidoc.Selection;
            ICollection<ElementId> ids = selection.GetElementIds();
            if (ids == null || ids.Count == 0) return (0, 0);

            double delta = stepMm * Mm * (up ? 1.0 : -1.0);
            double snap = Math.Max(0.0, snapMm) * Mm;

            // resolve the elements once, outside the transaction, so it is open for as short a time as possible
            var targets = new List<Element>();
            int skipped = 0;
            foreach (ElementId id in ids)
            {
                Element element = doc.GetElement(id);
                if (IsNudgeable(element, allowFittings, allowFabrication)) targets.Add(element);
                else skipped++;
            }
            if (targets.Count == 0) return (0, skipped);

            // A hanger selected with the part it carries may be dragged up by Revit when the part moves, and
            // nudging it as well would move it twice. So hangers go last: their heights are read first, the
            // model is regenerated once the parts are done, and a hanger that has already travelled is
            // counted as moved and left alone.
            List<Element> hangers = targets.Where(IsHanger).ToList();
            List<Element> others = targets.Where(e => !IsHanger(e)).ToList();
            var before = new Dictionary<ElementId, double?>();
            foreach (Element hanger in hangers) before[hanger.Id] = ReferenceZ(hanger);

            int moved = 0;
            using (var transaction = new Transaction(doc, TransactionName))
            {
                transaction.Start();
                try
                {
                    foreach (Element element in others)
                    {
                        if (TryShift(element, delta, snap, recutRods)) moved++;
                        else skipped++;
                    }

                    if (hangers.Count > 0 && others.Count > 0)
                    {
                        try
                        {
                            doc.Regenerate();
                        }
                        catch (Exception)
                        {
                        }
                    }

                    foreach (Element hanger in hangers)
                    {
                        double? was = before[hanger.Id];
                        double? now = ReferenceZ(hanger);
                        if (was != null && now != null && Math.Abs(now.Value - was.Value) > 0.5 * Mm)
                        {
                            moved++;   // carried with its part already
                            continue;
                        }
                        if (TryShift(hanger, delta, snap, recutRods)) moved++;
                        else skipped++;
                    }
                    transaction.Commit();
                }
                catch (Exception)
                {
                    if (transaction.HasStarted()) transaction.RollBack();
                    throw;
                }
            }

            // Revit normally keeps the selection through a parameter change, so write it back only when it
            // has been dropped: SetElementIds is not free and this runs on every press.
            if (keepSelection)
            {
                try
                {
                    ICollection<ElementId> current = selection.GetElementIds();
                    if (current == null || current.Count != ids.Count)
                        selection.SetElementIds(targets.Select(e => e.Id).ToList());
                }
                catch (Exception)
                {
                }
            }
            return (moved, skipped);
        }

        private static bool TryShift(Element element, double delta, double snap, bool recutRods)
        {
            try
            {
                return Shift(element, delta, snap, recutRods) != null;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ------------------------------------------------------------------ mode two: click one at a time

        /// <summary>Ask for an element, move it, ask again. Escape ends the loop. Each click is its own
        /// transaction, so Ctrl+Z steps back one element at a time. Returns how many were moved.</summary>
        public static int RunClickLoop(UIDocument uidoc, double stepMm, bool up, double snapMm, bool allowFittings,
                                       bool repeat, bool allowFabrication, bool recutRods)
        {
            Document doc = uidoc.Document;
            double delta = stepMm * Mm * (up ? 1.0 : -1.0);
            double snap = Math.Max(0.0, snapMm) * Mm;
            var filter = new NudgeFilter(allowFittings, allowFabrication);
            string prompt = (up ? "Raise" : "Lower") + " by " + stepMm.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
                            + " mm - click an element" + (repeat ? " (Esc when finished)" : "");

            int moved = 0;
            while (true)
            {
                Reference reference;
                try
                {
                    reference = uidoc.Selection.PickObject(ObjectType.Element, filter, prompt);
                }
                catch (Autodesk.Revit.Exceptions.OperationCanceledException)
                {
                    break;   // Escape
                }
                catch (Exception)
                {
                    break;
                }
                if (reference == null) break;

                Element element = doc.GetElement(reference.ElementId);
                using (var transaction = new Transaction(doc, TransactionName))
                {
                    transaction.Start();
                    try
                    {
                        if (Shift(element, delta, snap, recutRods) != null)
                        {
                            transaction.Commit();
                            moved++;
                        }
                        else
                        {
                            transaction.RollBack();
                        }
                    }
                    catch (Exception)
                    {
                        if (transaction.HasStarted()) transaction.RollBack();
                    }
                }
                if (!repeat) break;
            }
            return moved;
        }

        // ------------------------------------------------------------------ what the buttons call

        /// <summary>Selection first, click loop second. The whole button; finishes silently.</summary>
        public static void Run(UIDocument uidoc, bool up)
        {
            NudgeConfig config = NudgeSettings.Load();
            double snap = config.SnapEnabled ? config.SnapMm : 0.0;
            if (uidoc.Selection.GetElementIds().Count > 0)
            {
                NudgeSelection(uidoc, config.StepMm, up, snap, config.AllowFittings, config.KeepSelection,
                               config.AllowFabrication, config.RecutRods);
                return;
            }
            RunClickLoop(uidoc, config.StepMm, up, snap, config.AllowFittings, config.RepeatLoop,
                         config.AllowFabrication, config.RecutRods);
        }
    }
}
