using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.DB.Mechanical;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.Wires
{
    /// <summary>What happened, in the order it happened.</summary>
    public sealed class Report
    {
        public const string Ok = "ok";
        public const string Info = "info";   // said for the record; never opens the window
        public const string Note = "note";   // worth a look
        public const string Skip = "skip";   // something was left alone

        public string Title;
        public readonly List<KeyValuePair<string, string>> Lines = new List<KeyValuePair<string, string>>();
        public int Fixed, Drawn, Retyped, Aligned, Skipped;
        /// <summary>Detailed diagnostics: never shown in the window, always written to the debug report.</summary>
        public readonly List<string> Trace = new List<string>();
        /// <summary>Set where a floating prompt is still open: the command returns long before the run is settled.</summary>
        public bool Deferred;

        public Report(string title)
        {
            Title = title;
        }

        private void Add(string kind, string text)
        {
            Lines.Add(new KeyValuePair<string, string>(kind, text));
        }

        public void OkLine(string text) { Add(Ok, text); }
        public void Log(string text) { Trace.Add(text); }
        public void InfoLine(string text) { Add(Info, text); }
        public void NoteLine(string text) { Add(Note, text); }

        public void SkipLine(string text)
        {
            Skipped++;
            Add(Skip, text);
        }

        /// <summary>Only a note or a skip opens the window: everything the run resolved along the way is INFO, so a run that goes to plan finishes without a dialog.</summary>
        public bool NeedsALook()
        {
            return Lines.Any(l => l.Key == Skip || l.Key == Note);
        }

        public string Summary()
        {
            var parts = new List<string>();
            if (Fixed > 0) parts.Add(Fixed + " reconnected");
            if (Drawn > 0) parts.Add(Drawn + " wire(s) and tag(s) drawn");
            // kept separate from drawn: Apply Wire Types draws nothing, and a summary telling the person it drew three wires contradicts its one promise
            if (Retyped > 0) parts.Add(Retyped + " wire(s) retyped");
            if (Aligned > 0) parts.Add(Aligned + " wire end(s) aligned");
            if (Skipped > 0) parts.Add(Skipped + " left alone");
            if (parts.Count == 0) return "Nothing to do.";
            return string.Join(", ", parts) + ".";
        }
    }

    /// <summary>A wireable element and where it sits.</summary>
    public sealed class Candidate
    {
        public Element Element;
        public XYZ Point;
        public string Name;
    }

    /// <summary>Auto-dismisses anything Revit raises for the duration of a run.</summary>
    public sealed class DialogSuppressor : IDisposable
    {
        private readonly UIApplication uiapp;
        private bool hooked;

        public DialogSuppressor(UIApplication uiapp)
        {
            this.uiapp = uiapp;
            try
            {
                uiapp.DialogBoxShowing += OnDialog;
                hooked = true;
            }
            catch (Exception)
            {
                hooked = false;
            }
        }

        private void OnDialog(object sender, DialogBoxShowingEventArgs args)
        {
            try
            {
                args.OverrideResult(1);
            }
            catch (Exception)
            {
            }
        }

        public void Dispose()
        {
            if (!hooked) return;
            try
            {
                uiapp.DialogBoxShowing -= OnDialog;
            }
            catch (Exception)
            {
            }
            hooked = false;
        }
    }

    /// <summary>Deletes warnings so a run is not stopped by Revit's own chatter.</summary>
    public sealed class WarningSwallower : IFailuresPreprocessor
    {
        public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
        {
            try
            {
                foreach (FailureMessageAccessor failure in accessor.GetFailureMessages())
                    if (failure.GetSeverity() == FailureSeverity.Warning) accessor.DeleteWarning(failure);
            }
            catch (Exception)
            {
            }
            return FailureProcessingResult.Continue;
        }
    }

    public sealed class WireSelectionFilter : ISelectionFilter
    {
        public bool AllowElement(Element element)
        {
            return element is Wire;
        }

        public bool AllowReference(Reference reference, XYZ point)
        {
            return false;
        }
    }

    /// <summary>
    /// Wire, connector, circuit and lookup helpers shared by every button (the middle of wires_core.py), plus Reconnect Wires itself.
    /// </summary>
    public static class WiresModel
    {
        public static long Eid(ElementId id)
        {
            return id == null ? 0 : id.Value;
        }

        public static bool SameId(ElementId a, ElementId b)
        {
            return a != null && b != null && a.Value == b.Value;
        }

        public static bool IsWire(Element element)
        {
            return element is Wire;
        }

        public static void ApplyFailureHandler(Transaction transaction)
        {
            try
            {
                FailureHandlingOptions options = transaction.GetFailureHandlingOptions();
                options.SetFailuresPreprocessor(new WarningSwallower());
                options.SetClearAfterRollback(true);
                transaction.SetFailureHandlingOptions(options);
            }
            catch (Exception)
            {
            }
        }

        // ------------------------------------------------------------------ elements and points
        /// <summary>A representative plan point for the coarse distance filter.</summary>
        public static XYZ ElementPoint(Element element)
        {
            Location loc = null;
            try { loc = element.Location; } catch (Exception) { }
            if (loc != null)
            {
                try
                {
                    var lp = loc as LocationPoint;
                    if (lp != null) return lp.Point;
                }
                catch (Exception)
                {
                }
                try
                {
                    var lc = loc as LocationCurve;
                    if (lc != null) return lc.Curve.Evaluate(0.5, true);
                }
                catch (Exception)
                {
                }
            }
            try
            {
                BoundingBoxXYZ box = element.get_BoundingBox(null);
                if (box != null) return new XYZ((box.Min.X + box.Max.X) / 2.0, (box.Min.Y + box.Max.Y) / 2.0, (box.Min.Z + box.Max.Z) / 2.0);
            }
            catch (Exception)
            {
            }
            return null;
        }

        public static string ElementName(Element element)
        {
            try
            {
                var fi = element as FamilyInstance;
                if (fi != null && fi.Symbol != null) return fi.Symbol.Family.Name + " : " + fi.Symbol.Name;
            }
            catch (Exception)
            {
            }
            try
            {
                return element.Name;
            }
            catch (Exception)
            {
                return "element";
            }
        }

        public static string TypeName(Element element)
        {
            if (element == null) return "";
            try
            {
                string name = element.Name;
                if (!string.IsNullOrEmpty(name)) return name;
            }
            catch (Exception)
            {
            }
            foreach (BuiltInParameter bip in new[] { BuiltInParameter.SYMBOL_NAME_PARAM, BuiltInParameter.ALL_MODEL_TYPE_NAME })
            {
                try
                {
                    Parameter p = element.get_Parameter(bip);
                    if (p != null) return p.AsString() ?? "";
                }
                catch (Exception)
                {
                }
            }
            return "";
        }

        // ------------------------------------------------------------------ wires
        public static List<XYZ> WireVertices(Wire wire)
        {
            var points = new List<XYZ>();
            int count;
            try { count = wire.NumberOfVertices; } catch (Exception) { count = 0; }
            for (int i = 0; i < count; i++)
            {
                try
                {
                    points.Add(wire.GetVertex(i));
                }
                catch (Exception)
                {
                    return points;
                }
            }
            return points;
        }

        /// <summary>Chamfer or Arc, however this release exposes it.</summary>
        public static WiringType WiringTypeOf(Wire wire)
        {
            try
            {
                return wire.WiringType;
            }
            catch (Exception)
            {
            }
            try
            {
                BuiltInParameter wiringParam;
                if (!Enum.TryParse("RBS_ELEC_WIRE_TYPE_PARAM", out wiringParam)) return WiringType.Chamfer;   // not on every release, so looked up by name
                Parameter param = wire.get_Parameter(wiringParam);
                if (param != null && param.StorageType == StorageType.Integer) return param.AsInteger() == 1 ? WiringType.Arc : WiringType.Chamfer;
            }
            catch (Exception)
            {
            }
            return WiringType.Chamfer;
        }

        public static WiringType WiringKind(string name)
        {
            return (name ?? "").Trim().ToLowerInvariant() == "chamfer" ? WiringType.Chamfer : WiringType.Arc;
        }

        public static List<Connector> WireConnectors(Wire wire)
        {
            var connectors = new List<Connector>();
            try
            {
                ConnectorManager manager = wire.ConnectorManager;
                if (manager != null)
                    foreach (Connector c in manager.Connectors) connectors.Add(c);
            }
            catch (Exception)
            {
            }
            return connectors;
        }

        /// <summary>The wire's two ends: each connector matched to whichever end vertex it sits nearest in plan.</summary>
        public static List<KeyValuePair<Connector, int>> WireEnds(Wire wire)
        {
            List<XYZ> points = WireVertices(wire);
            List<Connector> connectors = WireConnectors(wire);
            var ends = new List<KeyValuePair<Connector, int>>();
            if (points.Count == 0)
            {
                foreach (Connector c in connectors) ends.Add(new KeyValuePair<Connector, int>(c, -1));
                return ends;
            }
            int last = points.Count - 1;
            var taken = new List<int>();
            foreach (Connector connector in connectors)
            {
                int index;
                try
                {
                    double nearFirst = WiresGeom.PlanDistance(connector.Origin, points[0]);
                    double nearLast = WiresGeom.PlanDistance(connector.Origin, points[last]);
                    index = nearFirst <= nearLast ? 0 : last;
                }
                catch (Exception)
                {
                    index = 0;
                }
                if (taken.Contains(index)) index = index == 0 ? last : 0;
                taken.Add(index);
                ends.Add(new KeyValuePair<Connector, int>(connector, index));
            }
            return ends;
        }

        /// <summary>True where nothing but the owner itself references the connector.</summary>
        public static bool ConnectorIsFree(Connector connector, ElementId ignoreElementId = null)
        {
            try
            {
                if (!connector.IsConnected) return true;
            }
            catch (Exception)
            {
            }
            try
            {
                foreach (Connector reference in connector.AllRefs)
                {
                    Element owner = reference.Owner;
                    if (owner == null) continue;
                    if (SameId(owner.Id, connector.Owner.Id)) continue;
                    if (ignoreElementId != null && SameId(owner.Id, ignoreElementId)) continue;
                    return false;
                }
            }
            catch (Exception)
            {
                return false;
            }
            return true;
        }

        /// <summary>Elements referenced by a connector, excluding its own owner.</summary>
        public static List<Element> ConnectedOwners(Connector connector)
        {
            var owners = new List<Element>();
            ElementId ownId = null;
            try { ownId = connector.Owner.Id; } catch (Exception) { }
            try
            {
                foreach (Connector reference in connector.AllRefs)
                {
                    Element owner = reference.Owner;
                    if (owner == null) continue;
                    if (ownId != null && SameId(owner.Id, ownId)) continue;
                    owners.Add(owner);
                }
            }
            catch (Exception)
            {
            }
            return owners;
        }

        /// <summary>The connector this one is joined to, or null.</summary>
        public static Connector OppositeConnector(Connector connector)
        {
            ElementId ownId = null;
            try { ownId = connector.Owner.Id; } catch (Exception) { }
            try
            {
                foreach (Connector reference in connector.AllRefs)
                {
                    Element owner = reference.Owner;
                    if (owner == null) continue;
                    if (ownId != null && SameId(owner.Id, ownId)) continue;
                    return reference;
                }
            }
            catch (Exception)
            {
            }
            return null;
        }

        // ------------------------------------------------------------------ circuits
        /// <summary>Every ElectricalSystem the element is a member of.</summary>
        public static List<ElectricalSystem> ElementCircuits(Element element)
        {
            var circuits = new List<ElectricalSystem>();
            var fi = element as FamilyInstance;
            if (fi == null) return circuits;
            try
            {
                MEPModel model = fi.MEPModel;
                if (model == null) return circuits;
                ISet<ElectricalSystem> systems = model.GetElectricalSystems();
                if (systems != null) circuits.AddRange(systems);
            }
            catch (Exception)
            {
            }
            return circuits;
        }

        public static List<Connector> ElectricalConnectors(Element element)
        {
            var connectors = new List<Connector>();
            var fi = element as FamilyInstance;
            if (fi == null) return connectors;
            try
            {
                MEPModel model = fi.MEPModel;
                if (model == null) return connectors;
                ConnectorManager manager = model.ConnectorManager;
                if (manager == null) return connectors;
                foreach (Connector connector in manager.Connectors)
                {
                    try
                    {
                        if (connector.Domain == Domain.DomainElectrical) connectors.Add(connector);
                    }
                    catch (Exception)
                    {
                        connectors.Add(connector);
                    }
                }
            }
            catch (Exception)
            {
            }
            return connectors;
        }

        /// <summary>True where any of the element's electrical connectors carries a wire.</summary>
        public static bool ElementHasWire(Element element)
        {
            foreach (Connector connector in ElectricalConnectors(element))
                foreach (Element owner in ConnectedOwners(connector))
                    if (IsWire(owner)) return true;
            return false;
        }

        public static string ConnectorSystemType(Connector connector)
        {
            try
            {
                return connector.ElectricalSystemType.ToString();
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static Dictionary<string, ElectricalSystem> CircuitIndex(Document doc)
        {
            var index = new Dictionary<string, ElectricalSystem>();
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(ElectricalSystem)))
                {
                    var circuit = (ElectricalSystem)e;
                    try
                    {
                        index[(circuit.PanelName ?? "") + "|" + (circuit.CircuitNumber ?? "")] = circuit;
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
            }
            return index;
        }

        /// <summary>The circuit a wire belongs to, by whichever route answers first.</summary>
        public static ElectricalSystem WireCircuit(Document doc, Wire wire, Dictionary<string, object> cache = null)
        {
            try
            {
                var system = wire.MEPSystem as ElectricalSystem;
                if (system != null) return system;
            }
            catch (Exception)
            {
            }
            foreach (Connector connector in WireConnectors(wire))
            {
                try
                {
                    var system = connector.MEPSystem as ElectricalSystem;
                    if (system != null) return system;
                }
                catch (Exception)
                {
                }
                foreach (Element owner in ConnectedOwners(connector))
                    foreach (ElectricalSystem circuit in ElementCircuits(owner)) return circuit;
            }
            // parameter route - the wire reports its circuit number and panel even where the connector walk comes back empty
            try
            {
                Parameter number = wire.get_Parameter(BuiltInParameter.RBS_ELEC_CIRCUIT_NUMBER);
                Parameter panel = wire.get_Parameter(BuiltInParameter.RBS_ELEC_CIRCUIT_PANEL_PARAM);
                if (number != null && panel != null)
                {
                    string key = (panel.AsString() ?? "") + "|" + (number.AsString() ?? "");
                    if (key.Trim('|').Length > 0)
                    {
                        Dictionary<string, ElectricalSystem> built;
                        object stored;
                        if (cache == null || !cache.TryGetValue("circuits", out stored))
                        {
                            built = CircuitIndex(doc);
                            if (cache != null) cache["circuits"] = built;
                        }
                        else built = (Dictionary<string, ElectricalSystem>)stored;
                        ElectricalSystem found;
                        if (built.TryGetValue(key, out found)) return found;
                    }
                }
            }
            catch (Exception)
            {
            }
            return null;
        }

        public static string CircuitLabel(ElectricalSystem circuit)
        {
            if (circuit == null) return "no circuit";
            try
            {
                return (circuit.PanelName ?? "?") + " " + (circuit.CircuitNumber ?? "?");
            }
            catch (Exception)
            {
                return "circuit";
            }
        }

        // ------------------------------------------------------------------ rebuilding a wire
        private static readonly BuiltInParameter[] CopyParams =
        {
            BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS, BuiltInParameter.ALL_MODEL_MARK, BuiltInParameter.ELEM_PARTITION_PARAM,
        };

        /// <summary>Carries the instance parameters worth keeping onto a rebuilt wire.</summary>
        private static void CopyParameters(Element source, Element target)
        {
            foreach (BuiltInParameter bip in CopyParams)
            {
                try
                {
                    Parameter src = source.get_Parameter(bip), dst = target.get_Parameter(bip);
                    if (src == null || dst == null || dst.IsReadOnly) continue;
                    switch (src.StorageType)
                    {
                        case StorageType.String: dst.Set(src.AsString() ?? ""); break;
                        case StorageType.Integer: dst.Set(src.AsInteger()); break;
                        case StorageType.Double: dst.Set(src.AsDouble()); break;
                        case StorageType.ElementId: dst.Set(src.AsElementId()); break;
                    }
                }
                catch (Exception)
                {
                }
            }
            // shared and project parameters, by name
            try
            {
                foreach (Parameter src in source.Parameters)
                {
                    try
                    {
                        if (src.IsReadOnly || src.Definition == null) continue;
                        Parameter dst = target.LookupParameter(src.Definition.Name);
                        if (dst == null || dst.IsReadOnly || src.StorageType != dst.StorageType) continue;
                        if (src.StorageType == StorageType.String)
                        {
                            string value = src.AsString();
                            if (!string.IsNullOrEmpty(value)) dst.Set(value);
                        }
                        else if (src.StorageType == StorageType.Double) dst.Set(src.AsDouble());
                        else if (src.StorageType == StorageType.Integer) dst.Set(src.AsInteger());
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Replaces a wire with a new one on the same type, view and vertices. Wire.Create is the only sanctioned way to make a wire that is genuinely joined to
        /// its elements, so it is the fallback whenever ConnectTo is refused and the only route where the vertex count has to change. Returns the new wire, or null.
        /// </summary>
        public static Wire RebuildWire(Document doc, Wire wire, List<XYZ> points, Connector startConnector, Connector endConnector)
        {
            try
            {
                var vertexList = new List<XYZ>(points);
                Wire newWire = Wire.Create(doc, wire.GetTypeId(), wire.OwnerViewId, WiringTypeOf(wire), vertexList, startConnector, endConnector);
                if (newWire == null) return null;
                CopyParameters(wire, newWire);
                doc.Delete(wire.Id);
                return newWire;
            }
            catch (Exception)
            {
                return null;
            }
        }

        // ------------------------------------------------------------------ selection
        /// <summary>Wires from the current selection, or picked. Returns (wires, others, cancelled).</summary>
        public static List<Wire> SelectedWires(UIDocument uidoc, out List<Element> others, out bool cancelled, bool askIfEmpty = true)
        {
            Document doc = uidoc.Document;
            var wires = new List<Wire>();
            others = new List<Element>();
            cancelled = false;
            try
            {
                foreach (ElementId id in uidoc.Selection.GetElementIds())
                {
                    Element element = doc.GetElement(id);
                    if (element == null) continue;
                    var w = element as Wire;
                    if (w != null) wires.Add(w);
                    else others.Add(element);
                }
            }
            catch (Exception)
            {
            }
            if (wires.Count > 0 || !askIfEmpty) return wires;
            try
            {
                foreach (Reference reference in uidoc.Selection.PickObjects(ObjectType.Element, new WireSelectionFilter(), "Select the wires to fix, then Finish"))
                {
                    var w = doc.GetElement(reference.ElementId) as Wire;
                    if (w != null) wires.Add(w);
                }
            }
            catch (Exception)
            {
                cancelled = true;
                return new List<Wire>();
            }
            return wires;
        }

        // ------------------------------------------------------------------ candidates and reconnect
        public static List<Candidate> CollectCandidates(Document doc, View view, Dictionary<string, string> settings, List<Element> restrictTo = null)
        {
            var candidates = new List<Candidate>();
            if (restrictTo != null && restrictTo.Count > 0)
            {
                foreach (Element element in restrictTo)
                {
                    XYZ point = ElementPoint(element);
                    if (point != null) candidates.Add(new Candidate { Element = element, Point = point, Name = ElementName(element) });
                }
                return candidates;
            }
            List<BuiltInCategory> categories = WiresSettings.ActiveCategories(settings);
            if (categories.Count == 0) return candidates;
            try
            {
                var collector = new FilteredElementCollector(doc, view.Id).WherePasses(new ElementMulticategoryFilter(categories)).WhereElementIsNotElementType();
                foreach (Element element in collector)
                {
                    if (!(element is FamilyInstance)) continue;
                    XYZ point = ElementPoint(element);
                    if (point == null) continue;
                    candidates.Add(new Candidate { Element = element, Point = point, Name = ElementName(element) });
                }
            }
            catch (Exception)
            {
            }
            return candidates;
        }

        private static bool SystemTypesAgree(string wireType, string connectorType)
        {
            if (wireType == null || connectorType == null) return true;
            return wireType == connectorType;
        }

        /// <summary>
        /// The nearest element that this loose wire end ought to be joined to. Where nothing qualifies, refusal says what was in range and why it was passed over,
        /// so a miss reads as a decision rather than a shrug.
        /// </summary>
        public static Element BestTarget(Document doc, Wire wire, XYZ endPoint, List<Candidate> candidates, Dictionary<string, string> settings, ElectricalSystem wireCirc,
                                         out Connector bestConnector, out double distance, out string refusal)
        {
            double radius = WiresSettings.Mm(WiresSettings.Float(settings, "search_radius_mm"));
            double coarse = radius + WiresSettings.Mm(1000);
            bool requireCircuit = WiresSettings.Bool(settings, "require_circuit");
            bool requireUnwired = WiresSettings.Bool(settings, "require_unwired");
            bool crossCircuit = WiresSettings.Bool(settings, "cross_circuit");
            bool matchType = WiresSettings.Bool(settings, "match_system_type");

            string wireType = null;
            if (matchType)
            {
                foreach (Connector connector in WireConnectors(wire))
                {
                    wireType = ConnectorSystemType(connector);
                    if (wireType != null) break;
                }
            }

            Element best = null;
            bestConnector = null;
            distance = 0.0;
            string bestName = null;
            double bestDistance = double.MaxValue;
            var passedOver = new List<string>();
            foreach (Candidate candidate in candidates)
            {
                if (WiresGeom.PlanDistance(candidate.Point, endPoint) > coarse) continue;
                if (SameId(candidate.Element.Id, wire.Id)) continue;
                List<Connector> connectors = ElectricalConnectors(candidate.Element);
                if (connectors.Count == 0) continue;
                List<ElectricalSystem> circuits = ElementCircuits(candidate.Element);
                if (requireCircuit && circuits.Count == 0)
                {
                    passedOver.Add(candidate.Name + " has no circuit");
                    continue;
                }
                if (requireUnwired && ElementHasWire(candidate.Element))
                {
                    passedOver.Add(candidate.Name + " is already wired");
                    continue;
                }
                if (wireCirc != null && circuits.Count > 0 && !crossCircuit)
                {
                    bool agree = circuits.Any(c => SameId(c.Id, wireCirc.Id));
                    if (!agree)
                    {
                        passedOver.Add(candidate.Name + " is on " + CircuitLabel(circuits[0]) + ", the wire is on " + CircuitLabel(wireCirc));
                        continue;
                    }
                }
                foreach (Connector connector in connectors)
                {
                    if (!ConnectorIsFree(connector, wire.Id))
                    {
                        // an electrical connector takes several wires, so being in use is not a refusal - only being in use by this same wire is
                        bool already = ConnectedOwners(connector).Any(o => SameId(o.Id, wire.Id));
                        if (already) continue;
                    }
                    if (matchType && !SystemTypesAgree(wireType, ConnectorSystemType(connector))) continue;
                    double d;
                    try { d = WiresGeom.PlanDistance(connector.Origin, endPoint); } catch (Exception) { continue; }
                    if (d > radius) continue;
                    if (best == null || d < bestDistance)
                    {
                        best = candidate.Element;
                        bestConnector = connector;
                        bestDistance = d;
                        bestName = candidate.Name;
                    }
                }
            }
            if (best == null)
            {
                refusal = passedOver.Count > 0 ? passedOver[0] : null;
                return null;
            }
            distance = bestDistance;
            refusal = null;
            return best;
        }

        /// <summary>Joins a loose wire end to an element connector. True where it took (verified by read-back, not assumed).</summary>
        private static bool Connect(Wire wire, Connector wireConnector, int vertexIndex, Connector targetConnector, Dictionary<string, string> settings)
        {
            if (WiresSettings.Bool(settings, "snap_on_connect") && vertexIndex >= 0)
            {
                try
                {
                    XYZ origin = targetConnector.Origin;
                    XYZ current = wire.GetVertex(vertexIndex);
                    wire.SetVertex(vertexIndex, WiresGeom.PlanAt(origin, current.Z));
                }
                catch (Exception)
                {
                }
            }
            try
            {
                wireConnector.ConnectTo(targetConnector);
            }
            catch (Exception)
            {
                return false;
            }
            try
            {
                foreach (Element owner in ConnectedOwners(wireConnector))
                    if (SameId(owner.Id, targetConnector.Owner.Id)) return true;
            }
            catch (Exception)
            {
            }
            try
            {
                return wireConnector.IsConnected;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Fallback: rebuild the wire with Wire.Create so the join is made at birth.</summary>
        private static Wire RebuildOnto(Document doc, Wire wire, int vertexIndex, Connector targetConnector)
        {
            List<XYZ> points = WireVertices(wire);
            if (points.Count == 0) return null;
            int last = points.Count - 1;
            if (vertexIndex < 0) vertexIndex = 0;
            try
            {
                points[vertexIndex] = WiresGeom.PlanAt(targetConnector.Origin, points[vertexIndex].Z);
            }
            catch (Exception)
            {
            }
            // whatever the other end is already joined to has to be carried over
            int otherIndex = vertexIndex == 0 ? last : 0;
            Connector otherConnector = null;
            foreach (var end in WireEnds(wire))
            {
                if (end.Value == otherIndex)
                {
                    otherConnector = OppositeConnector(end.Key);
                    break;
                }
            }
            Connector start = vertexIndex == 0 ? targetConnector : otherConnector;
            Connector finish = vertexIndex == 0 ? otherConnector : targetConnector;
            return RebuildWire(doc, wire, points, start, finish);
        }

        /// <summary>Joins every loose end of the selected wires to the element beside it. Returns null on Escape.</summary>
        public static Report RunReconnect(UIApplication uiapp, Dictionary<string, string> settings, List<Wire> wires = null)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            View view = doc.ActiveView;
            var report = new Report("Reconnect Wires");
            var cache = new Dictionary<string, object>();
            List<Element> restrictTo = null;
            if (wires == null)
            {
                List<Element> others;
                bool cancelled;
                wires = SelectedWires(uidoc, out others, out cancelled);
                if (cancelled) return null;
                if (others.Count > 0)
                {
                    List<Element> usable = others.Where(e => ElectricalConnectors(e).Count > 0).ToList();
                    if (usable.Count > 0)
                    {
                        restrictTo = usable;
                        report.NoteLine("Search restricted to the " + usable.Count + " element(s) selected alongside the wires.");
                    }
                }
            }
            if (wires.Count == 0)
            {
                report.NoteLine("No wires selected. Select the wires to fix and run again.");
                return report;
            }
            List<Candidate> candidates = CollectCandidates(doc, view, settings, restrictTo);
            if (candidates.Count == 0)
            {
                report.NoteLine("No wireable elements found in this view. Check the categories in Settings.");
                return report;
            }

            using (var transaction = new Transaction(doc, "RevoBIM Reconnect Wires"))
            {
                ApplyFailureHandler(transaction);
                transaction.Start();
                try
                {
                    foreach (Wire wire in wires)
                    {
                        using (var sub = new SubTransaction(doc))
                        {
                            sub.Start();
                            try
                            {
                                ReconnectOne(doc, wire, candidates, settings, report, cache);
                                sub.Commit();
                            }
                            catch (Exception error)
                            {
                                sub.RollBack();
                                report.SkipLine("Wire " + Eid(wire.Id) + " left untouched: " + error.Message);
                            }
                        }
                    }
                    transaction.Commit();
                }
                catch (Exception error)
                {
                    try { transaction.RollBack(); } catch (Exception) { }
                    report.SkipLine("The run was rolled back: " + error.Message);
                }
            }
            return report;
        }

        private static void ReconnectOne(Document doc, Wire wire, List<Candidate> candidates, Dictionary<string, string> settings, Report report, Dictionary<string, object> cache)
        {
            long wireId = Eid(wire.Id);
            ElectricalSystem circuit = WireCircuit(doc, wire, cache);
            if (WireEnds(wire).Count == 0)
            {
                report.SkipLine("Wire " + wireId + " reports no connectors.");
                return;
            }
            var attempted = new List<int>();
            // At most the two ends, re-read each pass: a rebuild deletes the wire the connectors belong to, so anything held from before is stale.
            for (int pass = 0; pass < 2; pass++)
            {
                Connector looseConnector = null;
                int looseIndex = -1;
                List<XYZ> points = WireVertices(wire);
                foreach (var end in WireEnds(wire))
                {
                    if (attempted.Contains(end.Value)) continue;
                    if (ConnectorIsFree(end.Key))
                    {
                        looseConnector = end.Key;
                        looseIndex = end.Value;
                        break;
                    }
                }
                if (looseConnector == null) break;
                attempted.Add(looseIndex);
                XYZ endPoint;
                try
                {
                    endPoint = looseIndex >= 0 && looseIndex < points.Count ? points[looseIndex] : looseConnector.Origin;
                }
                catch (Exception)
                {
                    continue;
                }
                Connector targetConnector;
                double distance;
                string refusal;
                Element target = BestTarget(doc, wire, endPoint, candidates, settings, circuit, out targetConnector, out distance, out refusal);
                if (target == null)
                {
                    if (!string.IsNullOrEmpty(refusal)) report.SkipLine("Wire " + wireId + ": nothing joined - " + refusal + ".");
                    else report.SkipLine("Wire " + wireId + ": no wireable element within " + WiresSettings.Float(settings, "search_radius_mm").ToString("0", CultureInfo.InvariantCulture) + "mm of that end.");
                    continue;
                }
                bool joined = Connect(wire, looseConnector, looseIndex, targetConnector, settings);
                if (!joined && WiresSettings.Bool(settings, "recreate_if_refused"))
                {
                    Wire rebuilt = RebuildOnto(doc, wire, looseIndex, targetConnector);
                    if (rebuilt != null)
                    {
                        wire = rebuilt;
                        joined = true;
                        report.NoteLine("Wire " + wireId + " was refused in place and was rebuilt as " + Eid(wire.Id) + ".");
                    }
                }
                if (!joined)
                {
                    report.SkipLine("Wire " + wireId + ": Revit refused the connection to " + ElementName(target) + " at " + WiresSettings.ToMm(distance).ToString("0", CultureInfo.InvariantCulture) + "mm.");
                    continue;
                }
                report.Fixed++;
                ElectricalSystem newCircuit = WireCircuit(doc, wire, cache);
                if (newCircuit == null)
                {
                    report.NoteLine("Wire " + wireId + " joined " + ElementName(target) + " but still reports no circuit - check the element is circuited.");
                }
                else
                {
                    report.OkLine("Wire " + wireId + " joined " + ElementName(target) + " on " + CircuitLabel(newCircuit) + ", " + WiresSettings.ToMm(distance).ToString("0", CultureInfo.InvariantCulture) + "mm away.");
                    circuit = newCircuit;
                }
            }
        }

        // ------------------------------------------------------------------ views
        /// <summary>Wires are only ever drawn on a floor plan or a ceiling plan.</summary>
        public static bool IsPlanView(View view)
        {
            try
            {
                if (view == null || view.IsTemplate) return false;
                return view.ViewType == ViewType.FloorPlan || view.ViewType == ViewType.CeilingPlan;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// The elevation wires are drawn at in this view, learned from a wire already in the view rather than assumed (the plane Revit puts them on is not the
        /// level elevation and not the fitting's height). Falls back to the view's level.
        /// </summary>
        public static double DrawingPlaneZ(Document doc, View view)
        {
            try
            {
                foreach (Element e in new FilteredElementCollector(doc, view.Id).OfClass(typeof(Wire)))
                {
                    List<XYZ> points = WireVertices((Wire)e);
                    if (points.Count > 0) return points[0].Z;
                }
            }
            catch (Exception)
            {
            }
            try
            {
                Level level = view.GenLevel;
                if (level != null) return level.Elevation;
            }
            catch (Exception)
            {
            }
            return 0.0;
        }

        // ------------------------------------------------------------------ wire types, tag types, line styles
        // Every lookup tries several routes and says which one answered. Never swallow a lookup - report it.
        public static List<KeyValuePair<string, Element>> WireTypes(Document doc, out string note)
        {
            var pairs = new List<KeyValuePair<string, Element>>();
            var seen = new HashSet<long>();
            var tried = new List<string>();
            Action<Element> take = element =>
            {
                if (element == null) return;
                long key;
                try { key = element.Id.Value; } catch (Exception) { return; }
                if (seen.Contains(key)) return;
                string name = TypeName(element);
                if (name.Length == 0) return;
                seen.Add(key);
                pairs.Add(new KeyValuePair<string, Element>(name, element));
            };
            // 1. by class
            try
            {
                int before = pairs.Count;
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(WireType))) take(e);
                tried.Add("OfClass(WireType) found " + (pairs.Count - before));
            }
            catch (Exception error)
            {
                tried.Add("OfClass(WireType) failed (" + error.Message + ")");
            }
            // 2. by category - works where the class filter is refused
            if (pairs.Count == 0)
            {
                BuiltInCategory? bic = WiresSettings.BuiltinCategory("OST_Wire");
                if (bic == null) tried.Add("OST_Wire is not on this release");
                else
                {
                    try
                    {
                        foreach (Element e in new FilteredElementCollector(doc).OfCategory(bic.Value).WhereElementIsElementType()) take(e);
                        tried.Add("OST_Wire element types found " + pairs.Count);
                    }
                    catch (Exception error)
                    {
                        tried.Add("OST_Wire failed (" + error.Message + ")");
                    }
                }
            }
            // 3. the types actually in use on wires already drawn
            if (pairs.Count == 0)
            {
                try
                {
                    foreach (Element w in new FilteredElementCollector(doc).OfClass(typeof(Wire))) take(doc.GetElement(w.GetTypeId()));
                    tried.Add("types in use on existing wires found " + pairs.Count);
                }
                catch (Exception error)
                {
                    tried.Add("walking existing wires failed (" + error.Message + ")");
                }
            }
            // 4. the document's own default
            if (pairs.Count == 0)
            {
                try
                {
                    ElementId typeId = doc.GetDefaultElementTypeId(ElementTypeGroup.WireType);
                    Element element = doc.GetElement(typeId);
                    if (element != null)
                    {
                        take(element);
                        tried.Add("the document default wire type");
                    }
                }
                catch (Exception error)
                {
                    tried.Add("the document default failed (" + error.Message + ")");
                }
            }
            pairs.Sort((a, b) => string.CompareOrdinal(a.Key.ToLowerInvariant(), b.Key.ToLowerInvariant()));
            note = string.Join("; ", tried);
            return pairs;
        }

        /// <summary>The named wire type, or the first available one.</summary>
        public static ElementType FindWireType(Document doc, string name, Dictionary<string, object> cache = null)
        {
            List<KeyValuePair<string, Element>> pairs;
            object stored;
            if (cache != null && cache.TryGetValue("wire_types", out stored)) pairs = (List<KeyValuePair<string, Element>>)stored;
            else
            {
                string note;
                pairs = WireTypes(doc, out note);
                if (cache != null) cache["wire_types"] = pairs;
            }
            if (!string.IsNullOrEmpty(name))
            {
                foreach (var pair in pairs)
                    if (pair.Key == name) return pair.Value as ElementType;
                foreach (var pair in pairs)
                    if (pair.Key.ToLowerInvariant() == name.Trim().ToLowerInvariant()) return pair.Value as ElementType;
            }
            return pairs.Count > 0 ? pairs[0].Value as ElementType : null;
        }

        /// <summary>Wire tag types as (family, type, symbol).</summary>
        public static List<Tuple<string, string, FamilySymbol>> WireTagTypes(Document doc, out string note)
        {
            var found = new List<Tuple<string, string, FamilySymbol>>();
            var seen = new HashSet<long>();
            var tried = new List<string>();
            Action<Element> take = element =>
            {
                var symbol = element as FamilySymbol;
                if (symbol == null) return;
                long key;
                try { key = symbol.Id.Value; } catch (Exception) { return; }
                if (seen.Contains(key)) return;
                string family;
                try { family = symbol.Family.Name; } catch (Exception) { family = "Wire Tag"; }
                string name = TypeName(symbol);
                if (name.Length == 0) return;
                seen.Add(key);
                found.Add(Tuple.Create(family, name, symbol));
            };
            // 1. the wire tag category, by whichever name this release uses
            foreach (string categoryName in new[] { "OST_WireTags", "OST_WireTag" })
            {
                BuiltInCategory? bic = WiresSettings.BuiltinCategory(categoryName);
                if (bic == null) continue;
                try
                {
                    foreach (Element e in new FilteredElementCollector(doc).OfCategory(bic.Value).WhereElementIsElementType()) take(e);
                    tried.Add(categoryName + " found " + found.Count);
                }
                catch (Exception error)
                {
                    tried.Add(categoryName + " failed (" + error.Message + ")");
                }
                if (found.Count > 0) break;
            }
            // 2. every family symbol whose category reads as a wire tag
            if (found.Count == 0)
            {
                try
                {
                    foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)))
                    {
                        string label;
                        try { label = e.Category.Name.ToLowerInvariant(); } catch (Exception) { continue; }
                        if (label.Contains("wire") && label.Contains("tag")) take(e);
                    }
                    tried.Add("family symbols by category name found " + found.Count);
                }
                catch (Exception error)
                {
                    tried.Add("family symbol walk failed (" + error.Message + ")");
                }
            }
            if (found.Count == 0) tried.Add("no wire tag family is loaded in this model");
            found.Sort((a, b) =>
            {
                int c = string.CompareOrdinal(a.Item1.ToLowerInvariant(), b.Item1.ToLowerInvariant());
                return c != 0 ? c : string.CompareOrdinal(a.Item2.ToLowerInvariant(), b.Item2.ToLowerInvariant());
            });
            note = string.Join("; ", tried);
            return found;
        }

        public static List<Tuple<string, string, FamilySymbol>> TagRows(Document doc, Dictionary<string, object> cache = null)
        {
            object stored;
            if (cache != null && cache.TryGetValue("tag_rows", out stored)) return (List<Tuple<string, string, FamilySymbol>>)stored;
            string note;
            List<Tuple<string, string, FamilySymbol>> rows = WireTagTypes(doc, out note);
            if (cache != null) cache["tag_rows"] = rows;
            return rows;
        }

        /// <summary>The named wire tag type. Falls back within the family, then anywhere.</summary>
        public static FamilySymbol FindTagType(Document doc, string familyName, string typeName, Dictionary<string, object> cache = null)
        {
            List<Tuple<string, string, FamilySymbol>> rows = TagRows(doc, cache);
            if (rows.Count == 0) return null;
            if (!string.IsNullOrEmpty(familyName))
            {
                var inFamily = rows.Where(r => r.Item1 == familyName).ToList();
                if (inFamily.Count == 0) inFamily = rows.Where(r => r.Item1.ToLowerInvariant() == familyName.Trim().ToLowerInvariant()).ToList();
                if (inFamily.Count > 0)
                {
                    if (!string.IsNullOrEmpty(typeName))
                    {
                        foreach (var r in inFamily) if (r.Item2 == typeName) return r.Item3;
                        foreach (var r in inFamily) if (r.Item2.ToLowerInvariant() == typeName.Trim().ToLowerInvariant()) return r.Item3;
                    }
                    return inFamily[0].Item3;
                }
            }
            if (!string.IsNullOrEmpty(typeName))
                foreach (var r in rows) if (r.Item2 == typeName) return r.Item3;
            return rows[0].Item3;
        }

        /// <summary>Detail line styles as (name, GraphicsStyle).</summary>
        public static List<KeyValuePair<string, GraphicsStyle>> LineStyles(Document doc, out string note)
        {
            var found = new List<KeyValuePair<string, GraphicsStyle>>();
            var tried = new List<string>();
            BuiltInCategory? bic = WiresSettings.BuiltinCategory("OST_Lines");
            if (bic == null)
            {
                note = "OST_Lines is not on this release";
                return found;
            }
            try
            {
                Category lines = doc.Settings.Categories.get_Item(bic.Value);
                foreach (Category sub in lines.SubCategories)
                {
                    try
                    {
                        GraphicsStyle style = sub.GetGraphicsStyle(GraphicsStyleType.Projection);
                        if (style != null) found.Add(new KeyValuePair<string, GraphicsStyle>(sub.Name, style));
                    }
                    catch (Exception)
                    {
                    }
                }
                tried.Add("line subcategories found " + found.Count);
            }
            catch (Exception error)
            {
                tried.Add("line subcategories failed (" + error.Message + ")");
            }
            if (found.Count == 0)
            {
                try
                {
                    long linesId = new ElementId(bic.Value).Value;
                    foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(GraphicsStyle)))
                    {
                        var style = (GraphicsStyle)e;
                        try
                        {
                            Category category = style.GraphicsStyleCategory;
                            if (category == null || category.Parent == null) continue;
                            if (category.Parent.Id.Value == linesId) found.Add(new KeyValuePair<string, GraphicsStyle>(category.Name, style));
                        }
                        catch (Exception)
                        {
                        }
                    }
                    tried.Add("GraphicsStyle walk found " + found.Count);
                }
                catch (Exception error)
                {
                    tried.Add("GraphicsStyle walk failed (" + error.Message + ")");
                }
            }
            found.Sort((a, b) => string.CompareOrdinal(a.Key.ToLowerInvariant(), b.Key.ToLowerInvariant()));
            note = string.Join("; ", tried);
            return found;
        }

        public static GraphicsStyle FindLineStyle(Document doc, string name, Dictionary<string, object> cache = null)
        {
            List<KeyValuePair<string, GraphicsStyle>> pairs;
            object stored;
            if (cache != null && cache.TryGetValue("line_styles", out stored)) pairs = (List<KeyValuePair<string, GraphicsStyle>>)stored;
            else
            {
                string note;
                pairs = LineStyles(doc, out note);
                if (cache != null) cache["line_styles"] = pairs;
            }
            if (!string.IsNullOrEmpty(name))
            {
                foreach (var pair in pairs) if (pair.Key == name) return pair.Value;
                foreach (var pair in pairs) if (pair.Key.ToLowerInvariant() == name.Trim().ToLowerInvariant()) return pair.Value;
            }
            return null;
        }

        // ------------------------------------------------------------------ parameters on the fittings
        /// <summary>Parameter names carried by the fittings in these categories, read off the elements themselves, instance and type.</summary>
        public static List<string> FittingParameterNames(Document doc, List<BuiltInCategory> categories, int limit = 40)
        {
            var names = new HashSet<string>();
            if (categories == null || categories.Count == 0) return new List<string>();
            try
            {
                var collector = new FilteredElementCollector(doc).WherePasses(new ElementMulticategoryFilter(categories)).WhereElementIsNotElementType();
                int seen = 0;
                foreach (Element element in collector)
                {
                    foreach (Element source in new[] { element, doc.GetElement(element.GetTypeId()) })
                    {
                        if (source == null) continue;
                        try
                        {
                            foreach (Parameter param in source.Parameters)
                            {
                                try
                                {
                                    if (param.Definition != null) names.Add(param.Definition.Name);
                                }
                                catch (Exception)
                                {
                                }
                            }
                        }
                        catch (Exception)
                        {
                        }
                    }
                    seen++;
                    if (seen >= limit) break;
                }
            }
            catch (Exception)
            {
            }
            return names.OrderBy(t => t.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        /// <summary>Is this fitting's named parameter set? Instance first, then type. Yes / true / 1 all count.</summary>
        public static bool ParameterSaysYes(Element element, Document doc, string name)
        {
            if (string.IsNullOrEmpty(name) || element == null) return false;
            var sources = new List<Element> { element };
            try
            {
                Element typeElement = doc.GetElement(element.GetTypeId());
                if (typeElement != null) sources.Add(typeElement);
            }
            catch (Exception)
            {
            }
            foreach (Element source in sources)
            {
                Parameter param = null;
                try { param = source.LookupParameter(name); } catch (Exception) { }
                if (param == null) continue;
                try
                {
                    if (param.StorageType == StorageType.Integer) return param.AsInteger() == 1;
                }
                catch (Exception)
                {
                }
                foreach (Func<Parameter, string> reader in new Func<Parameter, string>[] { p => p.AsString(), p => p.AsValueString() })
                {
                    string value;
                    try { value = reader(param); } catch (Exception) { continue; }
                    if (value == null) continue;
                    string v = value.Trim().ToLowerInvariant();
                    if (v == "yes" || v == "true" || v == "1" || v == "y") return true;
                }
            }
            return false;
        }

        public static bool IsEmergency(Element element, Document doc, Dictionary<string, string> settings)
        {
            return ParameterSaysYes(element, doc, WiresSettings.Get(settings, "emergency_parameter"));
        }

        // ------------------------------------------------------------------ which space a fitting is in
        private static string SpatialName(Element spatial)
        {
            string number = "", name = "";
            try
            {
                var sp = spatial as SpatialElement;
                if (sp != null)
                {
                    number = sp.Number ?? "";
                    name = sp.Name ?? "";
                }
            }
            catch (Exception)
            {
            }
            string label = (number + " " + name).Trim();
            return label.Length > 0 ? label : "space";
        }

        /// <summary>
        /// A key for the space a fitting sits in, and its name. Spaces first because this is an MEP model, then rooms, then the point the fitting sits at.
        /// An empty key means no space could be found, which is a legitimate answer - an unspaced fitting is its own group.
        /// </summary>
        public static string SpaceKey(Element element, Document doc, out string name)
        {
            var fi = element as FamilyInstance;
            if (fi != null)
            {
                try
                {
                    Space space = fi.Space;
                    if (space != null)
                    {
                        name = SpatialName(space);
                        return "sp:" + space.Id.Value;
                    }
                }
                catch (Exception)
                {
                }
                try
                {
                    Room room = fi.Room;
                    if (room != null)
                    {
                        name = SpatialName(room);
                        return "sp:" + room.Id.Value;
                    }
                }
                catch (Exception)
                {
                }
            }
            try
            {
                XYZ point = ElementPoint(element);
                if (point != null)
                {
                    Space space = doc.GetSpaceAtPoint(point);
                    if (space != null)
                    {
                        name = SpatialName(space);
                        return "sp:" + space.Id.Value;
                    }
                }
            }
            catch (Exception)
            {
            }
            name = "";
            return "";
        }

        // ------------------------------------------------------------------ the debug report
        /// <summary>Everything worth knowing about a run, as plain text, so it can be sent on and read by somebody who cannot see the model.</summary>
        public static string DebugReport(UIApplication uiapp, Dictionary<string, string> settings, Report report, IEnumerable<string> extraLines = null)
        {
            var lines = new List<string>();
            lines.Add("RevoBIM PY - Wires debug report");
            lines.Add("tool version: " + WiresSettings.Version);
            lines.Add("build: " + WiresSettings.BuildInfo());
            try
            {
                lines.Add("Revit: " + uiapp.Application.VersionNumber + "  build " + uiapp.Application.VersionBuild);
            }
            catch (Exception)
            {
                lines.Add("Revit: could not be read");
            }
            Document doc = null;
            try
            {
                doc = uiapp.ActiveUIDocument.Document;
                View view = doc.ActiveView;
                lines.Add("document: " + doc.Title);
                lines.Add("view: " + view.Name + "  type " + view.ViewType + "  scale 1:" + WiresGeom.ViewScale(view));
            }
            catch (Exception)
            {
                lines.Add("document/view: could not be read");
            }
            lines.Add("");
            lines.Add("-- what the lookups resolved --");
            if (doc != null)
            {
                try
                {
                    string note;
                    List<KeyValuePair<string, Element>> pairs = WireTypes(doc, out note);
                    lines.Add("wire types in model: " + pairs.Count + "  (" + note + ")");
                    foreach (string key in new[] { "lighting_wire_type", "lighting_emergency_wire_type", "lighting_live_wire_type", "power_wire_type" })
                    {
                        ElementType found = FindWireType(doc, WiresSettings.Get(settings, key));
                        lines.Add("  " + key + " = '" + WiresSettings.Get(settings, key) + "' -> " + (found != null ? TypeName(found) : "NOTHING"));
                    }
                    string tagNote;
                    List<Tuple<string, string, FamilySymbol>> rows = WireTagTypes(doc, out tagNote);
                    lines.Add("wire tag types in model: " + rows.Count + "  (" + tagNote + ")");
                    FamilySymbol symbol = FindTagType(doc, WiresSettings.Get(settings, "wire_tag_family"), WiresSettings.Get(settings, "wire_tag_type"));
                    lines.Add("  tag -> " + (symbol != null ? TypeName(symbol) : "NOTHING"));
                    string styleNote;
                    List<KeyValuePair<string, GraphicsStyle>> styles = LineStyles(doc, out styleNote);
                    lines.Add("line styles in model: " + styles.Count + "  (" + styleNote + ")");
                    string wanted = WiresSettings.Get(settings, "switch_line_style");
                    lines.Add("  switch line style = '" + wanted + "' -> " + (FindLineStyle(doc, wanted) != null ? "found" : (wanted.Length == 0 ? "view default" : "NOTHING")));
                }
                catch (Exception error)
                {
                    lines.Add("lookups failed: " + error.Message);
                }
            }
            lines.Add("");
            lines.Add("-- settings --");
            Dictionary<string, string> defaults = WiresSettings.Defaults();
            foreach (string key in defaults.Keys.OrderBy(k => k, StringComparer.Ordinal))
            {
                string value = WiresSettings.Get(settings, key, defaults[key]);
                lines.Add("  " + key + " = " + value + (value == defaults[key] ? "" : "   <- changed"));
            }
            lines.Add("");
            lines.Add("-- the run --");
            if (report != null)
            {
                lines.Add("summary: " + report.Summary());
                foreach (var line in report.Lines) lines.Add("  [" + line.Key + "] " + line.Value);
            }
            else lines.Add("  no report");
            if (report != null && report.Trace.Count > 0)
            {
                lines.Add("");
                lines.Add("-- trace --");
                foreach (string line in report.Trace) lines.Add("  " + line);
            }
            if (extraLines != null) lines.AddRange(extraLines);
            lines.Add("");
            lines.Add("-- end --");
            return string.Join("\n", lines);
        }

        /// <summary>Drops the report beside the settings file. Returns the path, or null.</summary>
        public static string WriteDebugReport(string text)
        {
            try
            {
                Directory.CreateDirectory(WiresSettings.SettingsDir());
                File.WriteAllText(WiresSettings.DebugPath(), text, new UTF8Encoding(false));
                return WiresSettings.DebugPath();
            }
            catch (Exception)
            {
                return null;
            }
        }
    }
}
