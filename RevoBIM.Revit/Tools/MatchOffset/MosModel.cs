using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.DB.Structure;

namespace RevoBIM.Tools.MatchOffset
{
    /// <summary>A connector found again later: its owner's id and its own id. Never a held handle, which fails silently across a regenerate.</summary>
    public sealed class MosConKey
    {
        public readonly long Owner;
        public readonly int Id;

        public MosConKey(long owner, int id)
        {
            Owner = owner;
            Id = id;
        }
    }

    /// <summary>An upright hanging off the body, and where it met it.</summary>
    public sealed class MosUprightLink
    {
        public ElementId UprightId;
        public MosConKey UprightKey, BodyKey;
        public MosPt FixedEnd;
    }

    /// <summary>Everything that travels with the clicked pipe, as one rigid body.</summary>
    public sealed class MosRunBody
    {
        public readonly List<ElementId> Ids = new List<ElementId>();
        public readonly List<Element> Pipes = new List<Element>();
        public readonly List<MosUprightLink> Uprights = new List<MosUprightLink>();
        public string Refusal = "";
        public int Count;
    }

    /// <summary>The end pipe and connector that will be stretched to the junction.</summary>
    public sealed class MosEndPick
    {
        public Element Pipe;
        public Connector Connector;
        /// <summary>True when the run had no spare end, so the joint nearest the main was freed and used.</summary>
        public bool Borrowed;
    }

    /// <summary>The result of trying to put a tee (or its hand-placed equivalent) across three ends.</summary>
    public sealed class MosTeeResult
    {
        public Element Fitting;
        public string Method = "";
        public readonly List<string> Notes = new List<string>();
    }

    /// <summary>The routing preference rules a pipe type carries, by group.</summary>
    public sealed class MosRoutingOffer
    {
        public readonly List<string> Names = new List<string>();
        public readonly Dictionary<string, int> Counts = new Dictionary<string, int>();
        public string Detail = "";
    }

    /// <summary>
    /// Match Offset Slope: everything that touches the Revit model. Three jobs: walk the branch run and work out what
    /// may move, apply the rigid transforms that put it on the main's fall at the crossing point, and put a fitting in.
    /// Rigid transforms rather than curve edits: RotateElements and MoveElements keep connectors joined, rewriting a
    /// LocationCurve on one pipe of a connected run does not. Port of mos_model.py.
    /// </summary>
    public static class MosModel
    {
        private const double TolFt = 0.1 / MosGeom.MmPerFt;
        private const double JoinTolFt = 1.0 / MosGeom.MmPerFt;

        private static readonly string[] FittingCategories = { "OST_PipeFitting", "OST_PipeAccessory" };

        private static long Eid(ElementId id) { return MoModel.Eid(id); }

        // ======================================================================
        // categories
        // ======================================================================

        private static bool CategoryIs(Element element, string name)
        {
            try
            {
                BuiltInCategory? bic = MoModel.BuiltinCategory(name);
                return bic.HasValue && element.Category != null && element.Category.Id.Value == new ElementId(bic.Value).Value;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static bool IsPipe(Element element) { return CategoryIs(element, "OST_PipeCurves"); }

        public static bool IsFitting(Element element) { return FittingCategories.Any(name => CategoryIs(element, name)); }

        // ======================================================================
        // curves and connectors
        // ======================================================================

        public static string NameOf(Element element)
        {
            try
            {
                return element.Name;
            }
            catch (Exception)
            {
                return "the pipe type";
            }
        }

        public static Curve CurveOf(Element element)
        {
            try
            {
                LocationCurve location = element.Location as LocationCurve;
                return location == null ? null : location.Curve;
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static MosPt ToPt(XYZ point) { return new MosPt(point.X, point.Y, point.Z); }
        public static XYZ ToXyz(MosPt point) { return new XYZ(point.X, point.Y, point.Z); }

        /// <summary>The two ends of a straight segment as points, or null.</summary>
        public static MosPt[] EndsOf(Element element)
        {
            Curve curve = CurveOf(element);
            if (curve == null) return null;
            try
            {
                return new[] { ToPt(curve.GetEndPoint(0)), ToPt(curve.GetEndPoint(1)) };
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static bool IsStraight(Element element) { return CurveOf(element) is Line; }

        public static double PitchOf(Element element)
        {
            MosPt[] ends = EndsOf(element);
            return ends == null ? 0.0 : MosGeom.PitchDegrees(ends[0], ends[1]);
        }

        /// <summary>
        /// The connector manager, whichever kind of element this is. A pipe is an MEPCurve and carries it directly; a
        /// fitting is a FamilyInstance and keeps it on MEPModel. Asking only for the first gives a fitting no connectors,
        /// which would stop the run walk dead at the first bend.
        /// </summary>
        private static ConnectorManager ManagerOf(Element element)
        {
            try
            {
                MEPCurve curve = element as MEPCurve;
                if (curve != null && curve.ConnectorManager != null) return curve.ConnectorManager;
            }
            catch (Exception)
            {
            }
            try
            {
                FamilyInstance instance = element as FamilyInstance;
                if (instance != null && instance.MEPModel != null) return instance.MEPModel.ConnectorManager;
            }
            catch (Exception)
            {
            }
            return null;
        }

        public static List<Connector> Connectors(Element element)
        {
            var output = new List<Connector>();
            ConnectorManager manager = ManagerOf(element);
            if (manager == null) return output;
            try
            {
                foreach (Connector connector in manager.Connectors) output.Add(connector);
            }
            catch (Exception)
            {
            }
            return output;
        }

        public static MosConKey ConnectorKey(Connector connector)
        {
            try
            {
                return new MosConKey(Eid(connector.Owner.Id), connector.Id);
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static Connector ConnectorByKey(Document doc, MosConKey key)
        {
            if (key == null) return null;
            Element owner = doc.GetElement(new ElementId(key.Owner));
            if (owner == null) return null;
            foreach (Connector connector in Connectors(owner))
            {
                try
                {
                    if (connector.Id == key.Id) return connector;
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        private static MosPt OriginOf(Connector connector)
        {
            try
            {
                return ToPt(connector.Origin);
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static bool IsJoined(Connector connector)
        {
            try
            {
                return connector.IsConnected;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>The connector of an element sitting at a point.</summary>
        public static Connector ConnectorAt(Element element, MosPt point, double tolerance = JoinTolFt)
        {
            Connector best = null;
            double bestDistance = tolerance;
            foreach (Connector connector in Connectors(element))
            {
                MosPt origin = OriginOf(connector);
                if (origin == null) continue;
                double distance = MosGeom.Length(origin, point);
                if (distance <= bestDistance)
                {
                    best = connector;
                    bestDistance = distance;
                }
            }
            return best;
        }

        /// <summary>
        /// A free connector of an element, at a point. By position rather than by a key captured earlier, because
        /// rewriting a LocationCurve can renumber an element's connectors.
        /// </summary>
        public static Connector OpenConnectorAt(Document doc, ElementId elementId, MosPt point, double tolerance = JoinTolFt)
        {
            Element element = doc.GetElement(elementId);
            if (element == null) return null;
            Connector best = null;
            double bestDistance = tolerance;
            foreach (Connector connector in Connectors(element))
            {
                MosPt origin = OriginOf(connector);
                if (origin == null) continue;
                double distance = MosGeom.Length(origin, point);
                if (distance <= bestDistance && !IsJoined(connector))
                {
                    best = connector;
                    bestDistance = distance;
                }
            }
            if (best != null) return best;
            // Nothing free at that point: fall back to the nearest one at all, so the caller gets a connector to complain about.
            return ConnectorAt(element, point, tolerance);
        }

        private static List<Connector> JoinedRefs(Connector connector)
        {
            var output = new List<Connector>();
            try
            {
                foreach (Connector reference in connector.AllRefs)
                {
                    try
                    {
                        if (reference.Owner != null) output.Add(reference);
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
            }
            return output;
        }

        public static bool Unjoin(Connector first, Connector second)
        {
            try
            {
                first.DisconnectFrom(second);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static List<MosConKey> UnjoinAll(Connector connector)
        {
            var freed = new List<MosConKey>();
            foreach (Connector reference in JoinedRefs(connector))
            {
                if (Eid(reference.Owner.Id) == Eid(connector.Owner.Id)) continue;
                MosConKey key = ConnectorKey(reference);
                if (Unjoin(connector, reference)) freed.Add(key);
            }
            return freed;
        }

        // ======================================================================
        // walking the branch run
        // ======================================================================

        /// <summary>
        /// Everything that travels with the clicked pipe, as one rigid body. The walk stops at any pipe pitched more
        /// than steepDeg: anything past an upright is not walked at all. Fittings are never classed as uprights, so the
        /// bend between a run and its stack travels with the run and the stack stretches up to meet it.
        /// </summary>
        public static MosRunBody WalkRun(Document doc, Element start, double steepDeg, int limit)
        {
            var body = new MosRunBody();
            var seen = new HashSet<long>();
            var pending = new List<Element> { start };
            var uprightSeen = new HashSet<long>();

            while (pending.Count > 0)
            {
                Element element = pending[pending.Count - 1];
                pending.RemoveAt(pending.Count - 1);
                long key = Eid(element.Id);
                if (!seen.Add(key)) continue;

                try
                {
                    if (Eid(element.GroupId) > 0)
                    {
                        body.Refusal = "the run reaches into a Revit group";
                        return body;
                    }
                }
                catch (Exception)
                {
                }

                body.Ids.Add(element.Id);
                if (IsPipe(element)) body.Pipes.Add(element);
                body.Count = seen.Count;
                if (body.Count > limit)
                {
                    body.Refusal = "the run reaches more than " + limit + " elements";
                    return body;
                }

                foreach (Connector connector in Connectors(element))
                {
                    foreach (Connector reference in JoinedRefs(connector))
                    {
                        Element owner = reference.Owner;
                        long otherKey = Eid(owner.Id);
                        if (otherKey == key || seen.Contains(otherKey)) continue;
                        if (!(IsPipe(owner) || IsFitting(owner))) continue;
                        if (IsPipe(owner) && PitchOf(owner) > steepDeg)
                        {
                            if (!uprightSeen.Add(otherKey)) continue;
                            MosPt[] ends = EndsOf(owner);
                            MosPt fixedEnd = null;
                            if (ends != null)
                            {
                                MosPt origin = ToPt(connector.Origin);
                                fixedEnd = MosGeom.Length(ends[0], origin) <= MosGeom.Length(ends[1], origin) ? ends[1] : ends[0];
                            }
                            body.Uprights.Add(new MosUprightLink
                            {
                                UprightId = owner.Id,
                                UprightKey = ConnectorKey(reference),
                                BodyKey = ConnectorKey(connector),
                                FixedEnd = fixedEnd,
                            });
                            continue;
                        }
                        pending.Add(owner);
                    }
                }
            }
            return body;
        }

        /// <summary>
        /// The end pipe and connector that will be stretched to the junction: a free connector first. A run with no
        /// spare end has the joint nearest the main freed and used instead, rather than the run being refused.
        /// </summary>
        public static MosEndPick FreeEndOf(MosRunBody body, MosPt towards)
        {
            MosEndPick best = null, fallback = null;
            double? bestDistance = null, fallbackDistance = null;
            foreach (Element pipe in body.Pipes)
            {
                foreach (Connector connector in Connectors(pipe))
                {
                    MosPt origin = OriginOf(connector);
                    if (origin == null) continue;
                    double distance = MosGeom.PlanLength(origin, towards);
                    if (!IsJoined(connector))
                    {
                        if (bestDistance == null || distance < bestDistance.Value)
                        {
                            best = new MosEndPick { Pipe = pipe, Connector = connector, Borrowed = false };
                            bestDistance = distance;
                        }
                    }
                    else if (fallbackDistance == null || distance < fallbackDistance.Value)
                    {
                        fallback = new MosEndPick { Pipe = pipe, Connector = connector, Borrowed = true };
                        fallbackDistance = distance;
                    }
                }
            }
            return best ?? fallback;
        }

        /// <summary>The end of the end pipe that is not moving.</summary>
        public static MosPt AnchorOf(Element pipe, Connector freeConnector)
        {
            MosPt[] ends = EndsOf(pipe);
            if (ends == null) return null;
            MosPt origin = OriginOf(freeConnector);
            if (origin == null) return ends[0];
            return MosGeom.Length(ends[0], origin) <= MosGeom.Length(ends[1], origin) ? ends[1] : ends[0];
        }

        // ======================================================================
        // the transforms
        // ======================================================================

        private static List<ElementId> IdList(IEnumerable<ElementId> ids) { return new List<ElementId>(ids); }

        /// <summary>Tilt the whole body about a horizontal axis through the anchor.</summary>
        public static bool RotateBody(Document doc, IEnumerable<ElementId> ids, MosPt anchor, double[] axisUnit, double angle)
        {
            if (Math.Abs(angle) < 1e-9) return false;
            XYZ start = new XYZ(anchor.X, anchor.Y, anchor.Z);
            XYZ end = new XYZ(anchor.X + axisUnit[0], anchor.Y + axisUnit[1], anchor.Z);
            try
            {
                ElementTransformUtils.RotateElements(doc, IdList(ids), Line.CreateBound(start, end), angle);
                return true;
            }
            catch (Exception err)
            {
                throw new Exception("Revit refused the tilt: " + err.Message);
            }
        }

        /// <summary>
        /// Shift the whole body, in all three directions: the in-line case needs a sideways nudge as well as a lift, and
        /// a union will not take two ends a few millimetres apart.
        /// </summary>
        public static bool MoveBody(Document doc, IEnumerable<ElementId> ids, double dx, double dy, double dz)
        {
            if (Math.Abs(dx) <= TolFt && Math.Abs(dy) <= TolFt && Math.Abs(dz) <= TolFt) return false;
            try
            {
                ElementTransformUtils.MoveElements(doc, IdList(ids), new XYZ(dx, dy, dz));
                return true;
            }
            catch (Exception err)
            {
                throw new Exception("Revit refused the move: " + err.Message);
            }
        }

        private static bool SetLine(Element element, MosPt first, MosPt second)
        {
            try
            {
                ((LocationCurve)element.Location).Curve = Line.CreateBound(ToXyz(first), ToXyz(second));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Move one end of a pipe, leaving the curve pointing the way it did. A pipe's connectors are bound to the ends
        /// of its curve by index, so writing the curve the other way round swaps which connector is which and Revit
        /// disconnects whatever was joined to it. So work out which index the staying end is and write in that order.
        /// </summary>
        public static bool Restretch(Element element, MosPt fixedEnd, MosPt landing, out string order)
        {
            MosPt[] ends = EndsOf(element);
            if (ends == null)
            {
                order = "no curve";
                return false;
            }
            MosPt first, second;
            if (MosGeom.Length(ends[0], fixedEnd) <= MosGeom.Length(ends[1], fixedEnd))
            {
                first = fixedEnd;
                second = landing;
                order = "0 stays";
            }
            else
            {
                first = landing;
                second = fixedEnd;
                order = "1 stays";
            }
            if (MosGeom.Length(first, second) < JoinTolFt)
            {
                order = "the pipe would have no length left";
                return false;
            }
            if (!SetLine(element, first, second))
            {
                order = "Revit refused the new curve";
                return false;
            }
            return true;
        }

        /// <summary>Let every boundary upright go before the body moves: it is released, the run goes where it has to, and the upright is re-cut to follow.</summary>
        public static List<MosUprightLink> ReleaseUprights(Document doc, MosRunBody body)
        {
            var released = new List<MosUprightLink>();
            foreach (MosUprightLink link in body.Uprights)
            {
                Connector connector = ConnectorByKey(doc, link.BodyKey);
                Connector partner = ConnectorByKey(doc, link.UprightKey);
                if (connector == null || partner == null) continue;
                if (Unjoin(connector, partner)) released.Add(link);
            }
            return released;
        }

        /// <summary>Re-cut each upright so the end that met the run lands on its new position and the other end stays exactly where it was.</summary>
        public static void RefitUprights(Document doc, List<MosUprightLink> links, MoReport report)
        {
            doc.Regenerate();
            foreach (MosUprightLink link in links)
            {
                Connector connector = ConnectorByKey(doc, link.BodyKey);
                Element upright = doc.GetElement(link.UprightId);
                if (connector == null || upright == null || link.FixedEnd == null)
                {
                    report.Problem("an upright could not be found again and was left loose");
                    continue;
                }
                MosPt landing = OriginOf(connector);
                if (landing == null)
                {
                    report.Problem("an upright could not be re-cut and was left loose");
                    continue;
                }
                string why;
                if (!Restretch(upright, link.FixedEnd, landing, out why))
                {
                    report.Problem("upright " + Eid(link.UprightId) + " was left loose: " + why);
                    continue;
                }
                doc.Regenerate();
                Connector partner = ConnectorByKey(doc, link.UprightKey);
                connector = ConnectorByKey(doc, link.BodyKey);
                if (partner == null || connector == null) continue;
                try
                {
                    partner.ConnectTo(connector);
                }
                catch (Exception)
                {
                    report.Problem("an upright was re-cut but would not reconnect");
                }
            }
        }

        // ======================================================================
        // the junction
        // ======================================================================

        /// <summary>Put the crossing point exactly on a centreline: BreakCurve and the fitting calls reject a point a fraction off the curve.</summary>
        public static MosPt ProjectOnto(Element element, MosPt point)
        {
            Curve curve = CurveOf(element);
            if (curve == null) return point;
            try
            {
                IntersectionResult result = curve.Project(ToXyz(point));
                if (result != null) return ToPt(result.XYZPoint);
            }
            catch (Exception)
            {
            }
            return point;
        }

        /// <summary>Carry the main out to an apparent intersection, through Restretch so the main's own curve direction survives.</summary>
        public static bool ExtendMain(Document doc, Element main, MosPt point)
        {
            MosPt[] ends = EndsOf(main);
            if (ends == null) return false;
            MosPt keep = MosGeom.Length(ends[0], point) > MosGeom.Length(ends[1], point) ? ends[0] : ends[1];
            string why;
            return Restretch(main, keep, point, out why);
        }

        private static readonly Tuple<string, RoutingPreferenceRuleGroupType>[] RoutingGroups =
        {
            Tuple.Create("Junction", RoutingPreferenceRuleGroupType.Junctions),
            Tuple.Create("Elbow", RoutingPreferenceRuleGroupType.Elbows),
            Tuple.Create("Cross", RoutingPreferenceRuleGroupType.Crosses),
            Tuple.Create("Union", RoutingPreferenceRuleGroupType.Unions),
            Tuple.Create("Transition", RoutingPreferenceRuleGroupType.Transitions),
        };

        /// <summary>
        /// What the pipe type's routing preferences actually offer. The detail says why a read failed, when it did:
        /// "no junction families at all" and "the read threw" look the same in a bare list and mean different things.
        /// </summary>
        public static MosRoutingOffer RoutingOffer(Document doc, Element pipe)
        {
            var offer = new MosRoutingOffer();
            PipeType pipeType;
            try
            {
                pipeType = doc.GetElement(pipe.GetTypeId()) as PipeType;
            }
            catch (Exception err)
            {
                offer.Detail = "the pipe type could not be read: " + err.Message;
                return offer;
            }
            if (pipeType == null)
            {
                offer.Detail = "the pipe has no type";
                return offer;
            }
            RoutingPreferenceManager manager;
            try
            {
                manager = pipeType.RoutingPreferenceManager;
            }
            catch (Exception err)
            {
                offer.Detail = NameOf(pipeType) + " has no RoutingPreferenceManager on this release: " + err.Message;
                return offer;
            }
            if (manager == null)
            {
                offer.Detail = "the pipe type has no routing preferences";
                return offer;
            }

            var troubles = new List<string>();
            foreach (Tuple<string, RoutingPreferenceRuleGroupType> group in RoutingGroups)
            {
                int count;
                try
                {
                    count = manager.GetNumberOfRules(group.Item2);
                }
                catch (Exception err)
                {
                    troubles.Add("counting the " + group.Item1 + " rules threw: " + err.Message);
                    continue;
                }
                offer.Counts[group.Item1] = count;
                for (int index = 0; index < count; index++)
                {
                    try
                    {
                        RoutingPreferenceRule rule = manager.GetRule(group.Item2, index);
                        FamilySymbol symbol = doc.GetElement(rule.MEPPartId) as FamilySymbol;
                        if (symbol != null) offer.Names.Add(group.Item1 + ": " + symbol.Family.Name);
                    }
                    catch (Exception err)
                    {
                        troubles.Add("reading a " + group.Item1 + " rule threw: " + err.Message);
                    }
                }
            }
            offer.Detail = string.Join("; ", troubles);
            return offer;
        }

        /// <summary>Every junction family symbol the main's pipe type will route to.</summary>
        private static List<KeyValuePair<string, FamilySymbol>> JunctionSymbols(Document doc, Element pipe)
        {
            var output = new List<KeyValuePair<string, FamilySymbol>>();
            RoutingPreferenceManager manager;
            try
            {
                manager = ((PipeType)doc.GetElement(pipe.GetTypeId())).RoutingPreferenceManager;
            }
            catch (Exception)
            {
                return output;
            }
            if (manager == null) return output;
            int count;
            try
            {
                count = manager.GetNumberOfRules(RoutingPreferenceRuleGroupType.Junctions);
            }
            catch (Exception)
            {
                return output;
            }
            for (int index = 0; index < count; index++)
            {
                try
                {
                    FamilySymbol symbol = doc.GetElement(manager.GetRule(RoutingPreferenceRuleGroupType.Junctions, index).MEPPartId) as FamilySymbol;
                    if (symbol != null) output.Add(new KeyValuePair<string, FamilySymbol>(symbol.Family.Name, symbol));
                }
                catch (Exception)
                {
                }
            }
            return output;
        }

        /// <summary>
        /// How many junction rules the main's pipe type carries (-1 when unreadable). Asked before the main is split,
        /// not after the tee is refused: breaking a pipe in half for a tee that was never going to place costs a regenerate.
        /// </summary>
        public static int JunctionRules(Document doc, Element pipe, out string detail)
        {
            MosRoutingOffer offer = RoutingOffer(doc, pipe);
            detail = offer.Detail;
            int count;
            return offer.Counts.TryGetValue("Junction", out count) ? count : -1;
        }

        /// <summary>Split the main at the crossing and put a tee across the three ends, in a sub-transaction so a refused tee never leaves the main cut in half.</summary>
        public static MosTeeResult PlaceTee(Document doc, Element main, ElementId branchId, MosPt point, bool byHand)
        {
            var result = new MosTeeResult();
            var sub = new SubTransaction(doc);
            sub.Start();
            try
            {
                MosPt landing = ProjectOnto(main, point);
                ElementId newId = PlumbingUtils.BreakCurve(doc, main.Id, ToXyz(landing));
                doc.Regenerate();
                Element other = doc.GetElement(newId);
                if (other == null)
                {
                    sub.RollBack();
                    result.Notes.Add("Revit would not split the main");
                    return result;
                }

                Connector first = ConnectorAt(main, landing);
                Connector second = ConnectorAt(other, landing);
                if (first == null || second == null)
                {
                    sub.RollBack();
                    result.Notes.Add("the split main had no connector at the crossing");
                    return result;
                }

                // Some releases leave the two halves joined after the break, and a tee will not take connectors already connected.
                Unjoin(first, second);
                doc.Regenerate();
                first = ConnectorAt(main, landing);
                second = ConnectorAt(other, landing);
                Connector branch = OpenConnectorAt(doc, branchId, landing, JoinTolFt * 25);
                if (first == null || second == null || branch == null)
                {
                    sub.RollBack();
                    result.Notes.Add("the split worked but one of the three connectors was not at the crossing afterwards");
                    return result;
                }

                FamilyInstance fitting = null;
                for (int attempt = 0; attempt < 2; attempt++)
                {
                    // The halves are not always interchangeable, so the other order is tried rather than assumed to be the same call.
                    Connector one = attempt == 0 ? first : second;
                    Connector two = attempt == 0 ? second : first;
                    try
                    {
                        fitting = doc.Create.NewTeeFitting(one, two, branch);
                        break;
                    }
                    catch (Exception err)
                    {
                        result.Notes.Add("NewTeeFitting: " + err.Message);
                        fitting = null;
                        first = ConnectorAt(main, landing);
                        second = ConnectorAt(other, landing);
                        branch = OpenConnectorAt(doc, branchId, landing, JoinTolFt * 25);
                        if (first == null || second == null || branch == null) break;
                    }
                }
                if (fitting != null)
                {
                    sub.Commit();
                    result.Fitting = fitting;
                    result.Method = "tee";
                    return result;
                }

                // Revit's own call only ever places a square tee. Everything else - every swept junction, every 45 degree
                // drainage branch - has to be placed as a family and turned onto the three directions.
                if (!byHand)
                {
                    result.Notes.Add("placing the junction family by hand is turned off in Settings");
                    sub.RollBack();
                    return result;
                }
                List<string> attempts;
                Element instance = PlaceJunctionByHand(doc, main, other, branchId, landing, out attempts);
                result.Notes.AddRange(attempts);
                if (instance != null)
                {
                    sub.Commit();
                    result.Fitting = instance;
                    result.Method = "junction family placed by hand";
                    return result;
                }

                sub.RollBack();
                return result;
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
                result.Fitting = null;
                result.Notes.Add(err.Message);
                return result;
            }
        }

        // ======================================================================
        // placing the junction family by hand
        // ======================================================================

        /// <summary>A connector points out of the element it belongs to.</summary>
        private static double[] ConnectorDirection(Connector connector)
        {
            try
            {
                XYZ basis = connector.CoordinateSystem.BasisZ;
                return new[] { basis.X, basis.Y, basis.Z };
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static double[] Opposite(double[] direction)
        {
            return direction == null ? null : new[] { -direction[0], -direction[1], -direction[2] };
        }

        private static int ConnectorId(Connector connector)
        {
            try
            {
                return connector.Id;
            }
            catch (Exception)
            {
                return -1;
            }
        }

        private static Connector ConnectorById(Element element, int wanted)
        {
            return Connectors(element).FirstOrDefault(c => ConnectorId(c) == wanted);
        }

        /// <summary>
        /// The run pair and the branch: the two connectors pointing most nearly opposite each other are the run,
        /// whatever is left is the branch. True of a tee, a lateral and a swept junction alike.
        /// </summary>
        private static Connector[] ClassifyThree(List<Connector> cons)
        {
            double bestAngle = -1;
            int bestFirst = -1, bestSecond = -1;
            for (int first = 0; first < cons.Count; first++)
                for (int second = first + 1; second < cons.Count; second++)
                {
                    double[] one = ConnectorDirection(cons[first]), two = ConnectorDirection(cons[second]);
                    if (one == null || two == null) continue;
                    double angle = MosGeom.AngleBetween(one, two);
                    if (bestFirst < 0 || angle > bestAngle)
                    {
                        bestAngle = angle;
                        bestFirst = first;
                        bestSecond = second;
                    }
                }
            if (bestFirst < 0) return null;
            for (int index = 0; index < cons.Count; index++)
                if (index != bestFirst && index != bestSecond) return new[] { cons[bestFirst], cons[bestSecond], cons[index] };
            return null;
        }

        /// <summary>Drive the family's own angle, where it has one.</summary>
        private static bool SetAngleParameter(Element instance, double radians)
        {
            List<Parameter> parameters;
            try
            {
                parameters = instance.Parameters.Cast<Parameter>().ToList();
            }
            catch (Exception)
            {
                return false;
            }
            foreach (Parameter parameter in parameters)
            {
                try
                {
                    if (parameter.IsReadOnly || parameter.StorageType != StorageType.Double) continue;
                    if (parameter.Definition.Name.ToLowerInvariant().IndexOf("angle", StringComparison.Ordinal) < 0) continue;
                    parameter.Set(radians);
                    return true;
                }
                catch (Exception)
                {
                }
            }
            return false;
        }

        private static MosPt FarEndOf(Element element, MosPt point)
        {
            MosPt[] ends = EndsOf(element);
            if (ends == null) return null;
            return MosGeom.Length(ends[0], point) > MosGeom.Length(ends[1], point) ? ends[0] : ends[1];
        }

        private static bool Turn(Document doc, ElementId elementId, MosPt about, double[] axis, double angle)
        {
            if (axis == null || Math.Abs(angle) < 1e-9) return true;
            try
            {
                XYZ start = new XYZ(about.X, about.Y, about.Z);
                XYZ end = new XYZ(about.X + axis[0], about.Y + axis[1], about.Z + axis[2]);
                ElementTransformUtils.RotateElement(doc, elementId, Line.CreateBound(start, end), angle);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static string ConnectorSize(Connector connector)
        {
            try
            {
                return "r" + (connector.Radius * 304.8).ToString("F1");
            }
            catch (Exception)
            {
            }
            try
            {
                return (connector.Width * 304.8).ToString("F0") + "x" + (connector.Height * 304.8).ToString("F0");
            }
            catch (Exception)
            {
                return "?";
            }
        }

        /// <summary>
        /// Make a fitting's connector the size of the pipe it has to meet. NewFamilyInstance places a fitting at its
        /// type's default size; Revit's own NewTeeFitting sizes it from the pipes, placing by hand does not, so the
        /// junction would come out right in every way except that it is the wrong size.
        /// </summary>
        private static bool MatchSize(Connector target, Connector source)
        {
            try
            {
                target.Radius = source.Radius;
                return true;
            }
            catch (Exception)
            {
            }
            try
            {
                target.Height = source.Height;
                target.Width = source.Width;
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>One way round of the two halves of the main: the fitting's run directions, the far ends and the halves themselves.</summary>
        private sealed class WayRound
        {
            public double[] WantFirst, WantSecond;
            public MosPt FarFirst, FarSecond;
            public Element HalfFirst, HalfSecond;
        }

        private sealed class JunctionSetup
        {
            public WayRound[] Options;
            public double[] Wanted;
            public double[] WantC;
            public MosPt FarC;
            public Element Branch;
            public Connector[] Pipes;
            public int Upstream;
            public double[] Flow, Travel;
        }

        /// <summary>Everything about the junction that does not depend on the family: the two ways round, the run-to-branch angle each way, which half the water comes from.</summary>
        private static JunctionSetup MakeSetup(Document doc, Element halfA, Element halfB, ElementId branchId, MosPt point, out string trouble)
        {
            double wide = JoinTolFt * 25;
            Element branch = doc.GetElement(branchId);
            Connector pipeA = ConnectorAt(halfA, point, wide);
            Connector pipeB = ConnectorAt(halfB, point, wide);
            Connector pipeC = OpenConnectorAt(doc, branchId, point, wide);
            trouble = "";
            if (pipeA == null || pipeB == null || pipeC == null || branch == null)
            {
                trouble = "a pipe had no connector at the crossing";
                return null;
            }

            // What the fitting's own connectors have to point, which is the opposite of what the pipes' connectors point.
            double[] wantA = Opposite(ConnectorDirection(pipeA));
            double[] wantB = Opposite(ConnectorDirection(pipeB));
            double[] wantC = Opposite(ConnectorDirection(pipeC));
            MosPt farA = FarEndOf(halfA, point), farB = FarEndOf(halfB, point), farC = FarEndOf(branch, point);
            if (wantA == null || wantB == null || wantC == null || farA == null || farB == null || farC == null)
            {
                trouble = "a connector would not give up its direction";
                return null;
            }

            var options = new[]
            {
                new WayRound { WantFirst = wantA, WantSecond = wantB, FarFirst = farA, FarSecond = farB, HalfFirst = halfA, HalfSecond = halfB },
                new WayRound { WantFirst = wantB, WantSecond = wantA, FarFirst = farB, FarSecond = farA, HalfFirst = halfB, HalfSecond = halfA },
            };
            return new JunctionSetup
            {
                Options = options,
                Wanted = options.Select(o => MosGeom.AngleBetween(o.WantFirst, wantC)).ToArray(),
                WantC = wantC,
                FarC = farC,
                Branch = branch,
                Pipes = new[] { pipeA, pipeB, pipeC },
                Upstream = MosGeom.UpstreamOf(farA, farB),
                Flow = farA.Z >= farB.Z ? MosGeom.Unit3(farA, farB) : MosGeom.Unit3(farB, farA),
                Travel = MosGeom.Unit3(farC, point),
            };
        }

        /// <summary>
        /// The two ways round, flow-correct one first. A swept junction's arm leans back towards where the water comes
        /// from, so the run connector making the acute angle with the arm belongs on the upstream half.
        /// </summary>
        private static List<int> WaysRound(JunctionSetup setup, out string note)
        {
            note = "";
            if (setup.Upstream == MosGeom.UpstreamUnknown)
            {
                note = "the main is level, so the flow could not be read";
                return new List<int> { 0, 1 };
            }
            var right = new List<int>();
            var wrong = new List<int>();
            for (int index = 0; index < 2; index++)
            {
                bool firstIsUpstream = setup.Upstream == index;
                if (MosGeom.SweepsWithTheFlow(setup.Wanted[index], firstIsUpstream)) right.Add(index);
                else wrong.Add(index);
            }
            right.AddRange(wrong);
            return right;
        }

        /// <summary>Did the fitting actually land pointing where it had to? Checked rather than assumed: every failure so far has looked finished.</summary>
        private static bool VerifyPlacement(Element instance, int[] ids, double[][] wants, double toleranceDeg, out double worst)
        {
            worst = 0.0;
            for (int index = 0; index < ids.Length; index++)
            {
                Connector connector = ConnectorById(instance, ids[index]);
                if (connector == null)
                {
                    worst = 180.0;
                    return false;
                }
                double off = MosGeom.AngleBetween(ConnectorDirection(connector), wants[index]);
                if (off > worst) worst = off;
            }
            return worst <= toleranceDeg * 2.0;
        }

        /// <summary>
        /// Place one junction family one way round, size it, turn it, join it. Everything sits in a sub-transaction that
        /// rolls back unless all three connections take and the fitting points where it was asked, so a family that
        /// does not suit costs nothing and the next is tried.
        /// </summary>
        private static Element TryJunctionSymbol(Document doc, FamilySymbol symbol, Element halfA, Element halfB, ElementId branchId,
                                                 MosPt point, double toleranceDeg, int wayRound, out string message)
        {
            var sub = new SubTransaction(doc);
            sub.Start();
            try
            {
                string trouble;
                JunctionSetup setup = MakeSetup(doc, halfA, halfB, branchId, point, out trouble);
                if (setup == null)
                {
                    sub.RollBack();
                    message = trouble;
                    return null;
                }
                double[] wantC = setup.WantC;
                MosPt farC = setup.FarC;
                Element branch = setup.Branch;
                WayRound option = setup.Options[wayRound];
                double required = setup.Wanted[wayRound];

                try
                {
                    if (!symbol.IsActive)
                    {
                        symbol.Activate();
                        doc.Regenerate();
                    }
                }
                catch (Exception)
                {
                }

                FamilyInstance instance = doc.Create.NewFamilyInstance(ToXyz(point), symbol, StructuralType.NonStructural);
                doc.Regenerate();

                List<Connector> cons = Connectors(instance);
                if (cons.Count != 3)
                {
                    sub.RollBack();
                    message = "the family has " + cons.Count + " connectors, not three";
                    return null;
                }
                Connector[] picked = ClassifyThree(cons);
                if (picked == null)
                {
                    sub.RollBack();
                    message = "the family's connectors could not be sorted";
                    return null;
                }

                // Size it before anything else: a bigger fitting is a longer one, so every position read before the resize would be wrong afterwards.
                for (int index = 0; index < 3; index++) MatchSize(picked[index], setup.Pipes[index]);
                doc.Regenerate();
                picked = ClassifyThree(Connectors(instance));
                if (picked == null)
                {
                    sub.RollBack();
                    message = "the family's connectors could not be sorted after it was sized";
                    return null;
                }

                double natural = MosGeom.AngleBetween(ConnectorDirection(picked[0]), ConnectorDirection(picked[2]));
                if (Math.Abs(required - natural) > toleranceDeg)
                {
                    // The family's own angle, where it has one. Tried only after the way round has been fixed, so it can
                    // never be used to force a family onto the way round it does not suit.
                    if (SetAngleParameter(instance, required * Math.PI / 180.0))
                    {
                        doc.Regenerate();
                        picked = ClassifyThree(Connectors(instance));
                        if (picked == null)
                        {
                            sub.RollBack();
                            message = "its connectors moved when its angle was set";
                            return null;
                        }
                        natural = MosGeom.AngleBetween(ConnectorDirection(picked[0]), ConnectorDirection(picked[2]));
                    }
                }
                if (Math.Abs(required - natural) > toleranceDeg)
                {
                    sub.RollBack();
                    message = "its branch sits at " + natural.ToString("F1") + " degrees to its run and this way round needs " + required.ToString("F1");
                    return null;
                }

                Connector runOne = picked[0], runTwo = picked[1], branchCon = picked[2];
                int[] ids = { ConnectorId(runOne), ConnectorId(runTwo), ConnectorId(branchCon) };
                double[][] wants = { option.WantFirst, option.WantSecond, wantC };

                MosOrientation turns = MosGeom.OrientationFor(ConnectorDirection(runOne), ConnectorDirection(branchCon), option.WantFirst, wantC);
                if (turns.Left > toleranceDeg * 2.0)
                {
                    sub.RollBack();
                    message = "it could not be turned onto the branch, " + turns.Left.ToString("F1") + " degrees out";
                    return null;
                }

                Turn(doc, instance.Id, point, turns.AxisOne, turns.AngleOne);
                doc.Regenerate();
                Turn(doc, instance.Id, point, turns.AxisTwo, turns.AngleTwo);
                doc.Regenerate();

                runOne = ConnectorById(instance, ids[0]);
                runTwo = ConnectorById(instance, ids[1]);
                branchCon = ConnectorById(instance, ids[2]);
                if (runOne == null || runTwo == null || branchCon == null)
                {
                    sub.RollBack();
                    message = "the fitting's connectors went missing after the turn";
                    return null;
                }

                // Register it on where its own axes cross, not on its insertion point: a swept junction's branch meets its run part way along.
                MosPt meeting = MosGeom.ClosestPointBetween(OriginOf(runOne), Opposite(ConnectorDirection(runOne)),
                                                            OriginOf(branchCon), Opposite(ConnectorDirection(branchCon)));
                try
                {
                    ElementTransformUtils.MoveElement(doc, instance.Id, new XYZ(point.X - meeting.X, point.Y - meeting.Y, point.Z - meeting.Z));
                }
                catch (Exception err)
                {
                    sub.RollBack();
                    message = "it would not move onto the crossing: " + err.Message;
                    return null;
                }
                doc.Regenerate();

                double worst;
                if (!VerifyPlacement(instance, ids, wants, toleranceDeg, out worst))
                {
                    sub.RollBack();
                    message = "it ended up " + worst.ToString("F1") + " degrees off after the turn";
                    return null;
                }

                runOne = ConnectorById(instance, ids[0]);
                runTwo = ConnectorById(instance, ids[1]);
                branchCon = ConnectorById(instance, ids[2]);

                // Cut the three pipes back to the fitting's own ends, which is the half of trim and extend that placing a family does not do.
                var cutting = new[]
                {
                    new { Element = option.HalfFirst, Far = option.FarFirst, Connector = runOne },
                    new { Element = option.HalfSecond, Far = option.FarSecond, Connector = runTwo },
                    new { Element = branch, Far = farC, Connector = branchCon },
                };
                foreach (var cut in cutting)
                {
                    MosPt landing = OriginOf(cut.Connector);
                    if (landing == null)
                    {
                        sub.RollBack();
                        message = "a fitting connector had no position";
                        return null;
                    }
                    string why;
                    if (!Restretch(cut.Element, cut.Far, landing, out why))
                    {
                        sub.RollBack();
                        message = "a pipe would not cut back: " + why;
                        return null;
                    }
                }
                doc.Regenerate();

                double wide = JoinTolFt * 25;
                int joined = 0;
                var joins = new[]
                {
                    new { Element = option.HalfFirst, Ref = ids[0] },
                    new { Element = option.HalfSecond, Ref = ids[1] },
                    new { Element = branch, Ref = ids[2] },
                };
                foreach (var join in joins)
                {
                    Connector fittingConnector = ConnectorById(instance, join.Ref);
                    if (fittingConnector == null) continue;
                    Connector pipeConnector = ConnectorAt(join.Element, OriginOf(fittingConnector), wide);
                    if (pipeConnector == null) continue;
                    try
                    {
                        pipeConnector.ConnectTo(fittingConnector);
                        joined++;
                    }
                    catch (Exception)
                    {
                    }
                }
                doc.Regenerate();

                if (joined < 3)
                {
                    sub.RollBack();
                    message = "only " + joined + " of the three ends would join";
                    return null;
                }

                if (!VerifyPlacement(instance, ids, wants, toleranceDeg, out worst))
                {
                    sub.RollBack();
                    message = "joining pulled it " + worst.ToString("F1") + " degrees off";
                    return null;
                }

                string sizes = string.Join("/", ids.Select(one => ConnectorSize(ConnectorById(instance, one))));
                sub.Commit();
                message = "arm at " + natural.ToString("F1") + " degrees to the run, sized " + sizes + ", " + worst.ToString("F2") + " degrees off, joined";
                return instance;
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

        /// <summary>Try every junction family the pipe type offers, the right way round first.</summary>
        private static Element PlaceJunctionByHand(Document doc, Element halfA, Element halfB, ElementId branchId, MosPt point,
                                                   out List<string> attempts, double toleranceDeg = 1.5)
        {
            attempts = new List<string>();
            string trouble;
            JunctionSetup setup = MakeSetup(doc, halfA, halfB, branchId, point, out trouble);
            if (setup == null)
            {
                attempts.Add(trouble);
                return null;
            }

            string note;
            List<int> order = WaysRound(setup, out note);
            if (note.Length > 0) attempts.Add(note);
            bool withFlow = setup.Flow != null && setup.Travel != null && MosGeom.BranchArrivesWithTheFlow(setup.Flow, setup.Travel);
            attempts.Add("the main falls towards its " +
                         (setup.Upstream == 1 ? "first" : (setup.Upstream == 0 ? "second" : "neither")) + " end; the branch arrives " +
                         (withFlow ? "with" : "against") + " the flow");
            if (setup.Flow != null && setup.Travel != null && !withFlow)
                attempts.Add("a branch arriving against the flow cannot be swept in - a junction facing the other way is a different " +
                             "fitting and a different piece of design");

            foreach (KeyValuePair<string, FamilySymbol> family in JunctionSymbols(doc, halfA))
            {
                foreach (int wayRound in order)
                {
                    string why;
                    Element instance = TryJunctionSymbol(doc, family.Value, halfA, halfB, branchId, point, toleranceDeg, wayRound, out why);
                    attempts.Add(family.Key + " [way " + wayRound + ", needs " + setup.Wanted[wayRound].ToString("F1") + " degrees]: " + why);
                    if (instance != null) return instance;
                }
            }
            if (attempts.Count <= 2) attempts.Add("the pipe type offers no junction family to try");
            return null;
        }

        // ======================================================================
        // squaring an angled branch into the main
        // ======================================================================
        // The last resort, for a pipe type whose only junction family is a plain square tee. The tee slides a little way
        // along the main, a short stub runs square out of it, and a bend turns the branch into the stub.

        private static ElementId IdParameter(Element element, params string[] names)
        {
            foreach (string name in names)
            {
                BuiltInParameter? member = MoModel.BuiltinParameter(name);
                if (!member.HasValue) continue;
                try
                {
                    Parameter parameter = element.get_Parameter(member.Value);
                    if (parameter != null) return parameter.AsElementId();
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        private static double? DoubleParameter(Element element, params string[] names)
        {
            foreach (string name in names)
            {
                BuiltInParameter? member = MoModel.BuiltinParameter(name);
                if (!member.HasValue) continue;
                try
                {
                    Parameter parameter = element.get_Parameter(member.Value);
                    if (parameter != null) return parameter.AsDouble();
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        public static double OutsideDiameter(Element pipe)
        {
            double? value = DoubleParameter(pipe, "RBS_PIPE_OUTER_DIAMETER", "RBS_PIPE_DIAMETER_PARAM");
            return value.HasValue && value.Value > 0 ? value.Value : 0.0;
        }

        /// <summary>A new pipe on the same system, type, level and size as another.</summary>
        private static Pipe CopyPipe(Document doc, Element template, MosPt start, MosPt end, out string error)
        {
            error = "";
            ElementId systemId = IdParameter(template, "RBS_PIPING_SYSTEM_TYPE_PARAM");
            ElementId levelId = IdParameter(template, "RBS_START_LEVEL_PARAM");
            if (systemId == null || levelId == null)
            {
                error = "the branch has no system or level to copy";
                return null;
            }
            Pipe made;
            try
            {
                made = Pipe.Create(doc, systemId, template.GetTypeId(), levelId, ToXyz(start), ToXyz(end));
            }
            catch (Exception err)
            {
                error = "the stub would not be created: " + err.Message;
                return null;
            }
            double? size = DoubleParameter(template, "RBS_PIPE_DIAMETER_PARAM");
            if (size.HasValue && size.Value != 0)
            {
                BuiltInParameter? member = MoModel.BuiltinParameter("RBS_PIPE_DIAMETER_PARAM");
                try
                {
                    Parameter parameter = member.HasValue ? made.get_Parameter(member.Value) : null;
                    if (parameter != null && !parameter.IsReadOnly) parameter.Set(size.Value);
                }
                catch (Exception)
                {
                }
            }
            return made;
        }

        /// <summary>Tee on the main, stub square out of it, bend into the branch. Returns the tee, or null with the notes saying why.</summary>
        public static Element SquareIntoMain(Document doc, Element main, ElementId branchId, MosPt crossing, double stubFt, out List<string> notes)
        {
            notes = new List<string>();
            var sub = new SubTransaction(doc);
            sub.Start();
            try
            {
                Element branch = doc.GetElement(branchId);
                MosPt[] mainEnds = EndsOf(main);
                MosPt[] branchEnds = EndsOf(branch);
                if (mainEnds == null || branchEnds == null)
                {
                    sub.RollBack();
                    notes.Add("a centreline could not be read");
                    return null;
                }

                double[] mainDir = MosGeom.Unit3(mainEnds[0], mainEnds[1]);
                MosPt near, far;
                if (MosGeom.Length(branchEnds[0], crossing) < MosGeom.Length(branchEnds[1], crossing))
                {
                    near = branchEnds[0];
                    far = branchEnds[1];
                }
                else
                {
                    near = branchEnds[1];
                    far = branchEnds[0];
                }
                double[] branchDir = MosGeom.Unit3(far, near);
                if (mainDir == null || branchDir == null)
                {
                    sub.RollBack();
                    notes.Add("a direction could not be worked out");
                    return null;
                }

                MosPt teePoint, bendPoint;
                if (!MosGeom.SquareJunction(crossing, mainDir, branchDir, stubFt, out teePoint, out bendPoint))
                {
                    sub.RollBack();
                    notes.Add("the branch is in line with the main, so there is nothing to square it into");
                    return null;
                }

                double run = MosGeom.PlanLength(mainEnds[0], mainEnds[1]);
                double along = MosGeom.PlanLength(mainEnds[0], teePoint);
                if (run < MosGeom.Eps || along < JoinTolFt || along > run - JoinTolFt)
                {
                    sub.RollBack();
                    notes.Add("a square tee would fall off the end of the main; shorten the stub in Settings or bring the branch in further along");
                    return null;
                }

                string why;
                if (!Restretch(branch, far, bendPoint, out why))
                {
                    sub.RollBack();
                    notes.Add("the branch would not pull back to the bend: " + why);
                    return null;
                }
                doc.Regenerate();

                string copyError;
                Pipe stub = CopyPipe(doc, branch, bendPoint, teePoint, out copyError);
                if (stub == null)
                {
                    sub.RollBack();
                    notes.Add(copyError);
                    return null;
                }
                doc.Regenerate();
                ElementId stubId = stub.Id;

                double wide = JoinTolFt * 25;
                Connector atBendBranch = OpenConnectorAt(doc, branchId, bendPoint, wide);
                Connector atBendStub = OpenConnectorAt(doc, stubId, bendPoint, wide);
                if (atBendBranch == null || atBendStub == null)
                {
                    sub.RollBack();
                    notes.Add("the branch and the stub did not meet at the bend");
                    return null;
                }
                try
                {
                    doc.Create.NewElbowFitting(atBendBranch, atBendStub);
                }
                catch (Exception err)
                {
                    sub.RollBack();
                    notes.Add("the bend was refused: " + err.Message);
                    return null;
                }
                doc.Regenerate();

                MosPt landing = ProjectOnto(doc.GetElement(main.Id), teePoint);
                ElementId newId;
                try
                {
                    newId = PlumbingUtils.BreakCurve(doc, main.Id, ToXyz(landing));
                }
                catch (Exception err)
                {
                    sub.RollBack();
                    notes.Add("the main would not split at the tee: " + err.Message);
                    return null;
                }
                doc.Regenerate();
                Element liveMain = doc.GetElement(main.Id);
                Element other = doc.GetElement(newId);
                if (liveMain == null || other == null)
                {
                    sub.RollBack();
                    notes.Add("the main would not split at the tee");
                    return null;
                }

                Connector first = ConnectorAt(liveMain, landing, wide);
                Connector second = ConnectorAt(other, landing, wide);
                if (first == null || second == null)
                {
                    sub.RollBack();
                    notes.Add("the split main had no connector at the tee");
                    return null;
                }
                Unjoin(first, second);
                doc.Regenerate();

                FamilyInstance fitting = null;
                for (int attempt = 0; attempt < 2; attempt++)
                {
                    first = ConnectorAt(doc.GetElement(main.Id), landing, wide);
                    second = ConnectorAt(doc.GetElement(newId), landing, wide);
                    Connector atTee = OpenConnectorAt(doc, stubId, landing, wide);
                    if (first == null || second == null || atTee == null)
                    {
                        notes.Add("a connector was not at the tee after the split");
                        break;
                    }
                    try
                    {
                        fitting = doc.Create.NewTeeFitting(attempt == 0 ? first : second, attempt == 0 ? second : first, atTee);
                        break;
                    }
                    catch (Exception err)
                    {
                        notes.Add("square NewTeeFitting: " + err.Message);
                        fitting = null;
                    }
                }
                if (fitting == null)
                {
                    sub.RollBack();
                    if (notes.Count == 0) notes.Add("the square tee was refused");
                    return null;
                }

                sub.Commit();
                return fitting;
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
                notes.Add(err.Message);
                return null;
            }
        }

        /// <summary>The fallback: a takeoff on the uncut main.</summary>
        public static Element PlaceTakeoff(Document doc, Element main, ElementId branchId, MosPt point, out string error)
        {
            error = "";
            try
            {
                Connector branch = OpenConnectorAt(doc, branchId, point, JoinTolFt * 25);
                if (branch == null)
                {
                    error = "the branch has no connector at the crossing";
                    return null;
                }
                return doc.Create.NewTakeoffFitting(branch, (MEPCurve)main);
            }
            catch (Exception err)
            {
                error = err.Message;
                return null;
            }
        }

        /// <summary>An elbow where the two runs turn into each other, a union where they turn out to be in line.</summary>
        public static Element PlaceBend(Document doc, MosConKey mainConnector, ElementId branchId, MosPt point, bool union, out string error)
        {
            error = "";
            try
            {
                Connector first = ConnectorByKey(doc, mainConnector);
                Connector second = OpenConnectorAt(doc, branchId, point, JoinTolFt * 25);
                if (first == null || second == null)
                {
                    error = "a connector went missing before the fitting";
                    return null;
                }
                return union ? doc.Create.NewUnionFitting(first, second) : doc.Create.NewElbowFitting(first, second);
            }
            catch (Exception err)
            {
                error = err.Message;
                return null;
            }
        }

        public static MosRoutingOffer LogOffer(Document doc, Element pipe, double angle)
        {
            MosRoutingOffer offer = RoutingOffer(doc, pipe);
            MoCore.Log("junction refused at " + angle.ToString("F1") + " degrees; routing offers " +
                       (offer.Names.Count > 0 ? string.Join(", ", offer.Names) : "nothing") +
                       (offer.Detail.Length > 0 ? " (" + offer.Detail + ")" : ""));
            return offer;
        }
    }
}
