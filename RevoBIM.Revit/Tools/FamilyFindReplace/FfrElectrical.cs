using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;

namespace RevoBIM.Tools.FamilyFindReplace
{
    /// <summary>Circuits, tags and wires: everything that has to move onto the replacement before the original goes.</summary>
    public static partial class FfrCore
    {
        public const string ElecNone = "none";
        public const string ElecRetain = "retain";
        public const string ElecReview = "review";
        public const string ElecUncircuitable = "uncircuitable";

        public sealed class ElecProfile
        {
            public bool HasConnector;
            public List<string> SystemTypes = new List<string>();
            public int? Poles;
            public double? Voltage;
            public int Circuits;
        }

        private static List<Connector> ConnectorList(Element instance)
        {
            var connectors = new List<Connector>();
            try
            {
                var fi = instance as FamilyInstance;
                if (fi == null || fi.MEPModel == null) return connectors;
                ConnectorManager manager = fi.MEPModel.ConnectorManager;
                if (manager == null) return connectors;
                foreach (Connector connector in manager.Connectors) connectors.Add(connector);
            }
            catch (Exception)
            {
            }
            return connectors;
        }

        private static bool IsElectrical(Connector connector)
        {
            try
            {
                return connector.Domain == Domain.DomainElectrical;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Circuits the element sits on. Four routes, because which one answers varies with the release and with
        /// what the element is. The last is a document-wide scan that asks each circuit for its own members:
        /// slower, but it does not depend on MEPModel handing back anything at all.
        /// </summary>
        public static List<ElectricalSystem> ElectricalSystems(Element instance)
        {
            var found = new List<ElectricalSystem>();
            var seen = new HashSet<long>();
            Document doc;
            try
            {
                doc = instance.Document;
            }
            catch (Exception)
            {
                return found;
            }

            Action<object> keep = item =>
            {
                if (item == null) return;
                ElectricalSystem system = null;
                try
                {
                    var id = item as ElementId;
                    system = id != null ? doc.GetElement(id) as ElectricalSystem : item as ElectricalSystem;
                }
                catch (Exception)
                {
                    system = item as ElectricalSystem;
                }
                if (system == null) return;
                if (seen.Add(Eid(system.Id))) found.Add(system);
            };

            object model = null;
            try
            {
                var fi = instance as FamilyInstance;
                model = fi == null ? null : fi.MEPModel;
            }
            catch (Exception)
            {
                model = null;
            }

            if (model != null)
            {
                foreach (string route in new[] { "GetElectricalSystems", "GetAssignedElectricalSystems" })
                {
                    object raw = Call(model, route);
                    var list = raw as IEnumerable;
                    if (list == null) continue;
                    try
                    {
                        foreach (object item in list) keep(item);
                    }
                    catch (Exception)
                    {
                    }
                }
                if (found.Count == 0)
                {
                    var list = Prop(model, "ElectricalSystems") as IEnumerable;
                    if (list != null)
                    {
                        try
                        {
                            foreach (object item in list) keep(item);
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
            }
            if (found.Count > 0) return found;

            // Nothing came back: ask every circuit in the document whether it holds this element. Cached per
            // document, because the run calls this once per element.
            List<ElectricalSystem> held;
            if (CircuitIndex(doc).TryGetValue(Eid(instance.Id), out held))
                foreach (ElectricalSystem system in held) keep(system);
            return found;
        }

        private static readonly Dictionary<long, Dictionary<long, List<ElectricalSystem>>> CircuitIndexCache =
            new Dictionary<long, Dictionary<long, List<ElectricalSystem>>>();

        /// <summary>
        /// Drops everything cached for the length of one run: the circuit member map, the sketch planes made for
        /// work plane based replacements and the tag map. All are keyed on document state, so carrying any of
        /// them across a model edit would be wrong.
        /// </summary>
        public static void ResetRunCaches()
        {
            CircuitIndexCache.Clear();
            SketchCache.Clear();
            TagIndexCache.Clear();
        }

        private static long DocKey(Document doc)
        {
            return doc == null ? 0 : Eid(doc.ProjectInformation.Id);
        }

        private static Dictionary<long, List<ElectricalSystem>> CircuitIndex(Document doc)
        {
            long key = DocKey(doc);
            Dictionary<long, List<ElectricalSystem>> cached;
            if (CircuitIndexCache.TryGetValue(key, out cached)) return cached;
            var index = new Dictionary<long, List<ElectricalSystem>>();
            try
            {
                foreach (Element element in new FilteredElementCollector(doc).OfClass(typeof(ElectricalSystem)))
                {
                    var system = element as ElectricalSystem;
                    if (system == null) continue;
                    foreach (long memberId in CircuitMembers(system))
                    {
                        List<ElectricalSystem> list;
                        if (!index.TryGetValue(memberId, out list))
                        {
                            list = new List<ElectricalSystem>();
                            index[memberId] = list;
                        }
                        list.Add(system);
                    }
                }
            }
            catch (Exception)
            {
            }
            CircuitIndexCache[key] = index;
            return index;
        }

        /// <summary>The element ids on a circuit, whichever way the release reports them.</summary>
        public static List<long> CircuitMembers(ElectricalSystem system)
        {
            var ids = new List<long>();
            foreach (string route in new[] { "GetCircuitElements", "Elements" })
            {
                try
                {
                    object raw = route == "GetCircuitElements" ? Call(system, route) : Prop(system, route);
                    var list = raw as IEnumerable;
                    if (list == null) continue;
                    foreach (object item in list)
                    {
                        var id = item as ElementId;
                        if (id != null) ids.Add(Eid(id));
                        else
                        {
                            var element = item as Element;
                            if (element != null) ids.Add(Eid(element.Id));
                        }
                    }
                    if (ids.Count > 0) return ids;
                }
                catch (Exception)
                {
                }
            }
            return ids;
        }

        private static bool OnCircuit(ElectricalSystem system, ElementId elementId)
        {
            return CircuitMembers(system).Contains(Eid(elementId));
        }

        public static ElecProfile ElectricalProfile(Element instance)
        {
            var profile = new ElecProfile();
            foreach (Connector connector in ConnectorList(instance))
            {
                if (!IsElectrical(connector)) continue;
                profile.HasConnector = true;
                object systemType = Prop(connector, "ElectricalSystemType");
                if (systemType != null)
                {
                    string text = systemType.ToString();
                    if (!profile.SystemTypes.Contains(text)) profile.SystemTypes.Add(text);
                }
                foreach (string attr in new[] { "NumberOfPoles", "PolesNumber" })
                {
                    try
                    {
                        object value = Prop(connector, attr);
                        if (value != null && Convert.ToInt32(value) != 0)
                        {
                            profile.Poles = Convert.ToInt32(value);
                            break;
                        }
                    }
                    catch (Exception)
                    {
                    }
                }
                try
                {
                    object voltage = Prop(connector, "Voltage");
                    if (voltage != null && Convert.ToDouble(voltage) != 0.0) profile.Voltage = Convert.ToDouble(voltage);
                }
                catch (Exception)
                {
                }
            }
            if (profile.Poles == null) profile.Poles = ParamInt(instance, BuiltInParameter.RBS_ELEC_NUMBER_OF_POLES);
            if (profile.Voltage == null) profile.Voltage = ParamDouble(instance, BuiltInParameter.RBS_ELEC_VOLTAGE);
            profile.Circuits = ElectricalSystems(instance).Count;
            return profile;
        }

        private static IEnumerable<Element> InstanceAndType(Element element)
        {
            yield return element;
            Element type = null;
            try
            {
                type = element.Document.GetElement(element.GetTypeId());
            }
            catch (Exception)
            {
            }
            if (type != null) yield return type;
        }

        private static int? ParamInt(Element element, BuiltInParameter bip)
        {
            foreach (Element source in InstanceAndType(element))
            {
                try
                {
                    Parameter param = source.get_Parameter(bip);
                    if (param != null && param.HasValue) return param.AsInteger();
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        private static double? ParamDouble(Element element, BuiltInParameter bip)
        {
            foreach (Element source in InstanceAndType(element))
            {
                try
                {
                    Parameter param = source.get_Parameter(bip);
                    if (param != null && param.HasValue) return param.AsDouble();
                }
                catch (Exception)
                {
                }
            }
            return null;
        }

        /// <summary>Returns (state, headline, detail lines).</summary>
        public static string CompareElectrical(ElecProfile source, ElecProfile target, int circuitedCount, out string headline, out List<string> lines)
        {
            lines = new List<string>();
            if (circuitedCount <= 0)
            {
                headline = "No circuits on the originals";
                lines.Add("Nothing to carry across - the replacement is a plain swap.");
                return ElecNone;
            }
            if (!target.HasConnector)
            {
                headline = "Replacement cannot be circuited";
                lines.Add("The replacement family has no electrical connector, so the circuits on the originals cannot be carried across.");
                lines.Add("Running the replace will drop them.");
                return ElecUncircuitable;
            }

            bool mismatch = false;
            if (source.SystemTypes.Count > 0 && target.SystemTypes.Count > 0)
            {
                if (!source.SystemTypes.Any(s => target.SystemTypes.Contains(s)))
                {
                    mismatch = true;
                    lines.Add("System type: " + string.Join(", ", source.SystemTypes) + " on the original, " +
                              string.Join(", ", target.SystemTypes) + " on the replacement.");
                }
            }
            if (source.Poles != null && target.Poles != null && source.Poles.Value != target.Poles.Value)
            {
                mismatch = true;
                lines.Add("Poles: " + source.Poles + " on the original, " + target.Poles + " on the replacement.");
            }
            if (source.Voltage != null && target.Voltage != null && Math.Abs(source.Voltage.Value - target.Voltage.Value) > VoltageTol)
            {
                mismatch = true;
                lines.Add("Voltage: " + Math.Round(Volts(source.Voltage.Value), 1) + "V on the original, " +
                          Math.Round(Volts(target.Voltage.Value), 1) + "V on the replacement.");
            }
            if (mismatch)
            {
                lines.Add("Revit will refuse the circuit, or accept it and put the panel schedule out. Check the two families before you run.");
                headline = "Review electrical data";
                return ElecReview;
            }

            lines.Add(circuitedCount + " circuit(s) found on the originals.");
            if (target.SystemTypes.Count > 0) lines.Add("Connector: " + string.Join(", ", target.SystemTypes) + ".");
            if (target.Poles != null) lines.Add("Poles: " + target.Poles + ".");
            if (target.Voltage != null) lines.Add("Voltage: " + Math.Round(Volts(target.Voltage.Value), 1) + "V.");
            lines.Add("Each replacement joins its circuit before the original is deleted, so the circuit is never emptied.");
            headline = "Retain circuits";
            return ElecRetain;
        }

        /// <summary>
        /// Every AddToCircuit signature the API has carried, newest first. Found by reflection on the parameter
        /// type, so one build works against whichever release is loaded.
        /// </summary>
        private static List<KeyValuePair<string, Action>> AddRoutes(ElectricalSystem system, Element element)
        {
            var routes = new List<KeyValuePair<string, Action>>();
            foreach (MethodInfo method in typeof(ElectricalSystem).GetMethods().Where(m => m.Name == "AddToCircuit"))
            {
                ParameterInfo[] parameters = method.GetParameters();
                if (parameters.Length != 1) continue;
                Type type = parameters[0].ParameterType;
                MethodInfo captured = method;
                if (type == typeof(ElementSet))
                {
                    routes.Add(new KeyValuePair<string, Action>("element set", () =>
                    {
                        var set = new ElementSet();
                        set.Insert(element);
                        captured.Invoke(system, new object[] { set });
                    }));
                }
                else if (type == typeof(ElementId))
                {
                    routes.Add(new KeyValuePair<string, Action>("element id", () => captured.Invoke(system, new object[] { element.Id })));
                }
                else if (type == typeof(Element) || type == typeof(FamilyInstance))
                {
                    routes.Add(new KeyValuePair<string, Action>("element", () => captured.Invoke(system, new object[] { element })));
                }
                else if (type.IsAssignableFrom(typeof(HashSet<ElementId>)))
                {
                    routes.Add(new KeyValuePair<string, Action>("element id set", () =>
                        captured.Invoke(system, new object[] { new HashSet<ElementId> { element.Id } })));
                }
                else if (type.IsAssignableFrom(typeof(List<ElementId>)))
                {
                    routes.Add(new KeyValuePair<string, Action>("element id list", () =>
                        captured.Invoke(system, new object[] { new List<ElementId> { element.Id } })));
                }
            }
            // newest first: id collections, then the older forms
            routes.Sort((a, b) => RouteRank(a.Key).CompareTo(RouteRank(b.Key)));
            return routes;
        }

        private static int RouteRank(string name)
        {
            switch (name)
            {
                case "element id set": return 0;
                case "element id list": return 1;
                case "element set": return 2;
                case "element": return 3;
                default: return 4;
            }
        }

        /// <summary>
        /// Put the replacement onto every circuit the original sat on. Every add is verified by reading the
        /// circuit's own member list back: a call that does not throw has still not necessarily done anything,
        /// and a circuit silently dropped is the one failure of this tool that costs real work to find later.
        /// </summary>
        public static int TransferCircuits(Document doc, List<ElectricalSystem> systems, Element newElement, List<string> problems)
        {
            int joined = 0;
            foreach (ElectricalSystem system in systems)
            {
                string label = CircuitLabel(system);
                if (OnCircuit(system, newElement.Id))
                {
                    joined++;
                    continue;
                }
                var errors = new List<string>();
                bool done = false;
                foreach (KeyValuePair<string, Action> route in AddRoutes(system, newElement))
                {
                    try
                    {
                        route.Value();
                    }
                    catch (Exception err)
                    {
                        Exception inner = err is TargetInvocationException && err.InnerException != null ? err.InnerException : err;
                        errors.Add(route.Key + ": " + inner.Message);
                        continue;
                    }
                    // verify rather than trust; regenerate first or the member list can read as it did before
                    try
                    {
                        doc.Regenerate();
                    }
                    catch (Exception)
                    {
                    }
                    if (OnCircuit(system, newElement.Id))
                    {
                        done = true;
                        break;
                    }
                    errors.Add(route.Key + ": accepted but the circuit did not take it");
                }
                if (done)
                {
                    joined++;
                    continue;
                }
                // "accepted but did not take" says something about the model; a signature complaint only about the API
                string detail = errors.FirstOrDefault(t => t.Contains("did not take")) ?? (errors.Count > 0 ? errors[errors.Count - 1] : "no route was accepted");
                problems.Add(label + " would not take the replacement (" + detail + ")");
            }
            return joined;
        }

        /// <summary>Panel and circuit number, which is how the circuit reads on a schedule.</summary>
        public static string CircuitLabel(ElectricalSystem system)
        {
            string panel = "", number = "";
            try
            {
                panel = system.PanelName ?? "";
            }
            catch (Exception)
            {
            }
            try
            {
                number = system.CircuitNumber ?? "";
            }
            catch (Exception)
            {
            }
            if (panel.Length > 0 && number.Length > 0) return "circuit " + panel + "-" + number;
            if (panel.Length > 0) return "circuit on " + panel;
            if (number.Length > 0) return "circuit " + number;
            return "circuit " + Eid(system.Id);
        }

        // ---- tags -------------------------------------------------------------------------------------

        private static readonly Dictionary<long, Dictionary<long, List<IndependentTag>>> TagIndexCache =
            new Dictionary<long, Dictionary<long, List<IndependentTag>>>();

        /// <summary>Tagged element id -> the tags pointing at it, built once per run (one collector, not one per element).</summary>
        private static Dictionary<long, List<IndependentTag>> TagIndex(Document doc)
        {
            long key = DocKey(doc);
            Dictionary<long, List<IndependentTag>> cached;
            if (TagIndexCache.TryGetValue(key, out cached)) return cached;
            var index = new Dictionary<long, List<IndependentTag>>();
            try
            {
                foreach (Element element in new FilteredElementCollector(doc).OfClass(typeof(IndependentTag)))
                {
                    var tag = element as IndependentTag;
                    if (tag == null) continue;
                    foreach (long tagged in TaggedIds(tag))
                    {
                        List<IndependentTag> list;
                        if (!index.TryGetValue(tagged, out list))
                        {
                            list = new List<IndependentTag>();
                            index[tagged] = list;
                        }
                        list.Add(tag);
                    }
                }
            }
            catch (Exception)
            {
            }
            TagIndexCache[key] = index;
            return index;
        }

        private static List<long> TaggedIds(IndependentTag tag)
        {
            var ids = new List<long>();
            try
            {
                foreach (ElementId id in tag.GetTaggedLocalElementIds()) ids.Add(Eid(id));
            }
            catch (Exception)
            {
            }
            return ids;
        }

        public static List<IndependentTag> TagsOn(Document doc, Element instance)
        {
            List<IndependentTag> list;
            return TagIndex(doc).TryGetValue(Eid(instance.Id), out list) ? new List<IndependentTag>(list) : new List<IndependentTag>();
        }

        /// <summary>
        /// Point the originals' tags at the replacement. Re-pointing is preferred over recreating because it
        /// keeps the tag's head, leader and any dragged elbow. Done before the original is deleted: Revit removes
        /// a tag whose only referenced element has gone.
        /// </summary>
        public static int TransferTags(Document doc, List<IndependentTag> tags, Element oldElement, Element newElement, List<string> problems)
        {
            int moved = 0;
            if (tags == null || tags.Count == 0) return moved;
            Reference newRef;
            try
            {
                newRef = new Reference(newElement);
            }
            catch (Exception err)
            {
                problems.Add("the replacement gave no reference to tag (" + err.Message + ")");
                return moved;
            }
            long oldId = Eid(oldElement.Id);
            foreach (IndependentTag tag in tags)
            {
                if (RepointTag(doc, tag, newRef, oldId) || RecreateTag(doc, tag, newRef))
                {
                    moved++;
                    continue;
                }
                problems.Add("tag " + Eid(tag.Id) + " could not be moved to the replacement");
            }
            return moved;
        }

        /// <summary>Add the replacement to the tag, then drop the original.</summary>
        private static bool RepointTag(Document doc, IndependentTag tag, Reference newRef, long oldId)
        {
            try
            {
                tag.AddReferences(new List<Reference> { newRef });
            }
            catch (Exception)
            {
                return false;
            }
            try
            {
                doc.Regenerate();
            }
            catch (Exception)
            {
            }
            // drop the reference to the original so the tag does not read as tagging two things
            try
            {
                var stale = new List<Reference>();
                foreach (Reference reference in tag.GetTaggedReferences())
                    if (Eid(reference.ElementId) == oldId) stale.Add(reference);
                if (stale.Count > 0) tag.RemoveReferences(stale);
            }
            catch (Exception)
            {
            }
            return TaggedIds(tag).Contains(Eid(newRef.ElementId));
        }

        /// <summary>Make an equivalent tag on the replacement and delete the old one.</summary>
        private static bool RecreateTag(Document doc, IndependentTag tag, Reference newRef)
        {
            ElementId viewId, typeId;
            XYZ head;
            bool leader = false;
            TagOrientation orientation;
            try
            {
                viewId = tag.OwnerViewId;
                head = tag.TagHeadPosition;
                typeId = tag.GetTypeId();
                orientation = tag.TagOrientation;
                object hasLeader = Prop(tag, "HasLeader");
                if (hasLeader is bool) leader = (bool)hasLeader;
            }
            catch (Exception)
            {
                return false;
            }
            IndependentTag made = null;
            try
            {
                made = IndependentTag.Create(doc, typeId, viewId, newRef, leader, orientation, head);
            }
            catch (Exception)
            {
                made = null;
            }
            if (made == null) return false;
            try
            {
                doc.Delete(tag.Id);
            }
            catch (Exception)
            {
            }
            return true;
        }

        // ---- wires ------------------------------------------------------------------------------------

        /// <summary>One end of one wire, and where it met the original.</summary>
        public sealed class WireLink
        {
            public ElementId WireId;
            public XYZ Origin;
            public string SystemType;
        }

        private static string OriginKey(Connector connector)
        {
            try
            {
                XYZ o = connector.Origin;
                return Math.Round(o.X * 1000) + "," + Math.Round(o.Y * 1000) + "," + Math.Round(o.Z * 1000);
            }
            catch (Exception)
            {
                return "0,0,0";
            }
        }

        /// <summary>
        /// Every wire end physically connected to this element. Circuits and wires are separate things: putting
        /// the replacement on the circuit says nothing about the Wire elements drawn on the plan, which stay
        /// pointing at the original and dangle once it is deleted.
        /// </summary>
        public static List<WireLink> WireLinks(Document doc, Element instance)
        {
            var links = new List<WireLink>();
            var seen = new HashSet<string>();
            foreach (Connector connector in ConnectorList(instance))
            {
                if (!IsElectrical(connector)) continue;
                object type = Prop(connector, "ElectricalSystemType");
                string systemType = type == null ? "" : type.ToString();
                ConnectorSet refs;
                try
                {
                    refs = connector.AllRefs;
                }
                catch (Exception)
                {
                    continue;
                }
                foreach (Connector other in refs)
                {
                    Wire owner;
                    try
                    {
                        owner = other.Owner as Wire;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    if (owner == null) continue;
                    if (!seen.Add(Eid(owner.Id) + "|" + OriginKey(other))) continue;
                    XYZ origin = null;
                    try
                    {
                        origin = other.Origin;
                    }
                    catch (Exception)
                    {
                    }
                    links.Add(new WireLink { WireId = owner.Id, Origin = origin, SystemType = systemType });
                }
            }
            return links;
        }

        /// <summary>
        /// Move each wire end off the original and onto the replacement, before the original is deleted, and drag
        /// the wire's own end vertex onto the replacement's connector so it is drawn to where the new device is.
        /// </summary>
        public static int TransferWires(Document doc, List<WireLink> links, Element oldElement, Element newElement, List<string> problems)
        {
            int moved = 0;
            if (links == null || links.Count == 0) return moved;
            List<Connector> targets = ConnectorList(newElement).Where(IsElectrical).ToList();
            if (targets.Count == 0)
            {
                problems.Add(links.Count + " wire end(s) could not move - the replacement has no electrical connector");
                return moved;
            }
            List<Connector> oldConnectors = ConnectorList(oldElement);
            foreach (WireLink link in links)
            {
                var wire = doc.GetElement(link.WireId) as Wire;
                if (wire == null) continue;
                Connector target = PickWireTarget(targets, link);
                if (target == null)
                {
                    problems.Add("wire " + Eid(link.WireId) + ": no matching connector on the replacement");
                    continue;
                }
                Connector wireConnector = WireConnectorAt(wire, link.Origin);
                if (wireConnector == null)
                {
                    problems.Add("wire " + Eid(link.WireId) + ": its end could not be found again");
                    continue;
                }
                if (RelinkWire(wire, wireConnector, oldConnectors, target)) moved++;
                else problems.Add("wire " + Eid(link.WireId) + " would not reconnect");
            }
            return moved;
        }

        /// <summary>Prefer a connector of the same system type, else the first one.</summary>
        private static Connector PickWireTarget(List<Connector> targets, WireLink link)
        {
            foreach (Connector connector in targets)
            {
                object type = Prop(connector, "ElectricalSystemType");
                if (type != null && type.ToString() == link.SystemType) return connector;
            }
            return targets.Count > 0 ? targets[0] : null;
        }

        /// <summary>The wire's connector nearest where it met the original.</summary>
        private static Connector WireConnectorAt(Wire wire, XYZ origin)
        {
            Connector best = null;
            double bestGap = double.MaxValue;
            List<Connector> connectors;
            try
            {
                connectors = wire.ConnectorManager.Connectors.Cast<Connector>().ToList();
            }
            catch (Exception)
            {
                return null;
            }
            foreach (Connector connector in connectors)
            {
                if (origin == null) return connector;
                try
                {
                    double gap = connector.Origin.DistanceTo(origin);
                    if (best == null || gap < bestGap)
                    {
                        best = connector;
                        bestGap = gap;
                    }
                }
                catch (Exception)
                {
                }
            }
            return best;
        }

        private static bool RelinkWire(Wire wire, Connector wireConnector, List<Connector> oldConnectors, Connector target)
        {
            // free the end first: a connector already joined to something will not take a second connection
            foreach (Connector old in oldConnectors)
            {
                try
                {
                    if (wireConnector.IsConnectedTo(old)) wireConnector.DisconnectFrom(old);
                }
                catch (Exception)
                {
                }
            }
            try
            {
                wireConnector.ConnectTo(target);
            }
            catch (Exception)
            {
                return false;
            }
            DragWireEnd(wire, wireConnector, target);
            return true;
        }

        private static void DragWireEnd(Wire wire, Connector wireConnector, Connector target)
        {
            try
            {
                int count = wire.NumberOfVertices;
                if (count < 2) return;
                XYZ origin = wireConnector.Origin;
                XYZ first = wire.GetVertex(0);
                XYZ last = wire.GetVertex(count - 1);
                int index = first.DistanceTo(origin) <= last.DistanceTo(origin) ? 0 : count - 1;
                wire.SetVertex(index, target.Origin);
            }
            catch (Exception)
            {
            }
        }
    }
}
