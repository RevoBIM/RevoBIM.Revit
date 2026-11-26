using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

using Wire = Autodesk.Revit.DB.Electrical.Wire;

namespace RevoBIM.Tools.Wires
{
    /// <summary>
    /// Places a set of circuits, and can replace them with another route. Modal path: everything sits inside one TransactionGroup that is only assimilated when
    /// the route is kept, so Cancel puts the view back exactly as it was and Keep leaves one undo step. Modeless path (Revit stays usable while the Shuffle prompt
    /// floats): each redraw commits on its own and Cancel restores from snapshots, because a group left open would swallow whatever else the person did in Revit.
    /// </summary>
    public sealed class Session
    {
        public readonly UIDocument Uidoc;
        public readonly Document Doc;
        public readonly View View;
        public readonly Dictionary<string, string> Settings;
        public readonly List<CircuitJob> Jobs;
        public Dictionary<string, List<Member>> Switches;
        public readonly Report Report;
        private TransactionGroup group;
        public int Variant;
        public readonly List<ElementId> Placed = new List<ElementId>();
        public int Alternatives = 1;
        private bool cleared;
        private readonly Dictionary<string, object> cache = new Dictionary<string, object>();
        public readonly bool Modeless;
        private readonly List<KeyValuePair<string, object>> removed = new List<KeyValuePair<string, object>>();
        private double? vertexOverride, sagOverride;
        private bool? avoidOverride;
        private string wiringOverride;
        public int Clashing;
        private string title = "RevoBIM Wires";

        public Session(UIDocument uidoc, Dictionary<string, string> settings, List<CircuitJob> jobs, Dictionary<string, List<Member>> switches, Report report)
        {
            Uidoc = uidoc;
            Doc = uidoc.Document;
            View = uidoc.Document.ActiveView;
            Settings = settings;
            Jobs = jobs;
            Switches = switches;
            Report = report;
            Modeless = WiresSettings.Bool(settings, "modeless_shuffle");
        }

        // -- the group
        /// <summary>Opens a transaction group, but only for the modal path (a group left open across a modeless session would nest anything else the person did).</summary>
        public void Start(string title)
        {
            this.title = title;
            if (Modeless)
            {
                group = null;
                return;
            }
            group = new TransactionGroup(Doc, title);
            group.Start();
        }

        public void Keep()
        {
            try
            {
                if (group != null) group.Assimilate();
            }
            catch (Exception)
            {
            }
            group = null;
        }

        public void Cancel()
        {
            if (group != null)
            {
                try { group.RollBack(); } catch (Exception) { }
                group = null;
                Refresh();
                return;
            }
            // modeless: undo it by hand, in one transaction so it is one undo step
            using (var transaction = new Transaction(Doc, (title ?? "RevoBIM Wires") + " cancelled"))
            {
                WiresModel.ApplyFailureHandler(transaction);
                transaction.Start();
                try
                {
                    DeletePlaced();
                    foreach (var shot in removed) if (shot.Key == "wire") CircuitCore.RestoreWire(Doc, (CircuitCore.WireShot)shot.Value);
                    foreach (var shot in removed) if (shot.Key == "tag") CircuitCore.RestoreTag(Doc, (CircuitCore.TagShot)shot.Value);
                    removed.Clear();
                    cleared = false;
                    transaction.Commit();
                }
                catch (Exception)
                {
                    try { transaction.RollBack(); } catch (Exception) { }
                }
            }
            Refresh();
        }

        public void Refresh()
        {
            try
            {
                Uidoc.RefreshActiveView();
            }
            catch (Exception)
            {
            }
        }

        // -- placing
        private void DeletePlaced()
        {
            foreach (ElementId id in Placed)
            {
                try { Doc.Delete(id); } catch (Exception) { }
            }
            Placed.Clear();
        }

        public int Place(int variant, bool clearFirst = false)
        {
            Variant = variant;
            using (var transaction = new Transaction(Doc, "RevoBIM Auto Wire"))
            {
                WiresModel.ApplyFailureHandler(transaction);
                transaction.Start();
                try
                {
                    DeletePlaced();
                    if (clearFirst && !cleared)
                    {
                        foreach (CircuitJob job in Jobs)
                        {
                            int wires, tags;
                            CircuitCore.ClearCircuit(Doc, View, job, removed, out wires, out tags);
                            if (wires > 0 || tags > 0) Report.NoteLine(job.Label + ": " + wires + " wire(s) and " + tags + " tag(s) removed before redrawing.");
                        }
                        cleared = true;
                    }
                    int count = 0;
                    Clashing = 0;
                    foreach (CircuitJob job in Jobs)
                    {
                        using (var sub = new SubTransaction(Doc))
                        {
                            sub.Start();
                            try
                            {
                                Placement result = CircuitCore.WireOneCircuit(Doc, View, Settings, job, variant, cache, vertexOverride, sagOverride, avoidOverride, wiringOverride);
                                foreach (Wire wire in result.Wires) Placed.Add(wire.Id);
                                foreach (Element extra in result.Extras) Placed.Add(extra.Id);
                                if (result.Tag != null) Placed.Add(result.Tag.Id);
                                count += result.Wires.Count;
                                Clashing += result.Clashing;
                                Alternatives = Math.Max(Alternatives, result.Options);
                                if (variant == 0)
                                {
                                    foreach (string note in result.Info) Report.InfoLine(note);
                                    foreach (string note in result.Notes) Report.NoteLine(note);
                                }
                                sub.Commit();
                            }
                            catch (Exception error)
                            {
                                sub.RollBack();
                                Report.SkipLine(job.Label + ": left alone - " + error.Message);
                            }
                        }
                    }
                    transaction.Commit();
                    Report.Drawn = count;
                }
                catch (Exception error)
                {
                    try { transaction.RollBack(); } catch (Exception) { }
                    Report.SkipLine("The run was rolled back: " + error.Message);
                }
            }
            Refresh();
            return Placed.Count;
        }

        /// <summary>Keep or cancel, whichever path the session is on.</summary>
        public void Finish(bool keep)
        {
            if (keep) Keep();
            else Cancel();
        }

        public int Shuffle()
        {
            return Place(Variant + 1);
        }

        /// <summary>Redraws at a different vertex count, same route. Never below 1.</summary>
        public int SetVertices(int count)
        {
            vertexOverride = WiresGeom.ClampVertices(count);
            return Place(Variant);
        }

        public int Vertices()
        {
            return vertexOverride == null ? WiresGeom.ClampVertices(WiresSettings.Float(Settings, "mid_vertices")) : WiresGeom.ClampVertices(vertexOverride.Value);
        }

        /// <summary>Redraws as arc or chamfered wires, same route and vertices.</summary>
        public int SetWiring(string kind)
        {
            wiringOverride = (kind ?? "").ToLowerInvariant() == "chamfer" ? "chamfer" : "arc";
            return Place(Variant);
        }

        public string Wiring()
        {
            if (wiringOverride != null) return wiringOverride;
            return WiresSettings.Lower(Settings, "wiring_type", "arc") == "chamfer" ? "chamfer" : "arc";
        }

        /// <summary>Turns clash avoidance on or off and redraws, so the difference it makes can be seen rather than taken on trust.</summary>
        public int SetAvoid(bool flag)
        {
            avoidOverride = flag;
            return Place(Variant);
        }

        public bool Avoiding()
        {
            return avoidOverride ?? WiresSettings.Bool(Settings, "avoid_fittings");
        }

        /// <summary>Redraws with the vertices further off the chord, or closer to it.</summary>
        public int SetSag(double paperMm)
        {
            sagOverride = Math.Max(0.0, paperMm);
            return Place(Variant);
        }

        public double Sag()
        {
            return sagOverride ?? CircuitCore.SagSetting(Settings);
        }

        public string SagMode()
        {
            return WiresSettings.Lower(Settings, "arc_sag_mode", "span");
        }

        /// <summary>Back to the route before this one. Wraps round at the start.</summary>
        public int Previous()
        {
            int step = Variant - 1;
            if (step < 0) step = Math.Max(0, Alternatives - 1);
            return Place(step);
        }

        public bool HasPrevious()
        {
            return Alternatives > 1;
        }
    }

    /// <summary>One end of a wire that is joined to a fitting, and where it should sit.</summary>
    public sealed class EndTarget
    {
        public int Index;
        public Element Owner;
        public XYZ Target;
        public Connector Connector, Partner;
    }

    /// <summary>The Auto Wire, Re-Route, Apply Wire Types and Align Wire Ends runs (circuit_core.py, second half).</summary>
    public static class CircuitRuns
    {
        private static View Guard(UIDocument uidoc, Report report)
        {
            View view = uidoc.Document.ActiveView;
            if (!WiresModel.IsPlanView(view))
            {
                report.SkipLine("Wires are only drawn on a floor plan or a ceiling plan. Open one and run again.");
                return null;
            }
            return view;
        }

        /// <summary>Says what the run resolved before it draws anything.</summary>
        private static void ReportLookups(Document doc, Dictionary<string, string> settings, Report report)
        {
            string note;
            List<KeyValuePair<string, Element>> pairs = WiresModel.WireTypes(doc, out note);
            if (pairs.Count == 0)
            {
                report.SkipLine("No wire type could be found in this model, so nothing can be drawn. Lookup routes tried: " + note + ".");
            }
            else
            {
                ElementType chosen = WiresModel.FindWireType(doc, WiresSettings.Get(settings, "lighting_wire_type"));
                ElementType live = WiresModel.FindWireType(doc, WiresSettings.Get(settings, "lighting_live_wire_type"));
                report.InfoLine("Wire type: " + (chosen != null ? WiresModel.TypeName(chosen) : "none") + ". Permanent live: " + (live != null ? WiresModel.TypeName(live) : "none") +
                                ". (" + pairs.Count + " wire type(s) in this model.)");
            }
            if (WiresSettings.Bool(settings, "tag_circuits"))
            {
                string tagNote;
                List<Tuple<string, string, FamilySymbol>> rows = WiresModel.WireTagTypes(doc, out tagNote);
                if (rows.Count == 0) report.SkipLine("No wire tag family is loaded, so no tags will be placed. Lookup routes tried: " + tagNote + ".");
                else
                {
                    FamilySymbol symbol = WiresModel.FindTagType(doc, WiresSettings.Get(settings, "wire_tag_family"), WiresSettings.Get(settings, "wire_tag_type"));
                    report.InfoLine("Wire tag: " + (symbol != null ? WiresModel.TypeName(symbol) : "none") + ".");
                }
            }
        }

        /// <summary>Everything read from the model before a single transaction opens.</summary>
        public static View Prepare(UIDocument uidoc, Dictionary<string, string> settings, Report report, out List<CircuitJob> jobs, List<Element> restrictTo = null,
                                   ElectricalSystem onlyCircuit = null)
        {
            jobs = null;
            Document doc = uidoc.Document;
            View view = Guard(uidoc, report);
            if (view == null) return null;
            bool wantPower = WiresSettings.Bool(settings, "power_enabled");
            jobs = CircuitCore.CollectJobs(doc, view, settings, restrictTo, wantPower);
            if (onlyCircuit != null)
            {
                long target = onlyCircuit.Id.Value;
                jobs = jobs.Where(j => j.Circuit.Id.Value == target).ToList();
            }
            Dictionary<string, List<Member>> switches = CircuitCore.FindSwitchDevices(doc, view, settings);
            foreach (CircuitJob job in jobs)
            {
                CircuitCore.AttachSwitch(job, switches, settings, doc);
                if (job.SwitchElement != null && job.SwitchRoute.Length > 0) report.InfoLine(job.Label + ": switch found - " + job.SwitchRoute + ".");
                if (job.SwitchKey.Length > 0 && job.SwitchElement == null)
                {
                    int colon = job.SwitchKey.IndexOf(':');
                    report.NoteLine(job.Label + ": switch system " + (colon >= 0 ? job.SwitchKey.Substring(colon + 1) : job.SwitchKey) +
                                    " found on the fittings, but no switch device is drawn in this view.");
                }
                if (WiresSettings.Bool(settings, "report_offscreen") && job.Offscreen > 0)
                    report.NoteLine(job.Label + ": " + job.Offscreen + " member(s) of this circuit are not in this view and have been left out of the run.");
            }
            return view;
        }

        /// <summary>
        /// Auto Wire. With something selected, wires the circuits that selection sits on and nothing else; with nothing selected, wires every circuit in the view that
        /// has no wires yet. shufflePrompt returns true (kept), false (cancelled) or null (the floating prompt is still open and owns the session).
        /// </summary>
        public static Report RunWireCircuits(UIApplication uiapp, Dictionary<string, string> settings, Func<Session, string, bool?> shufflePrompt = null)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            var report = new Report("Auto Wire");
            List<Element> restrictTo = null;
            try
            {
                var chosen = new List<Element>();
                foreach (ElementId id in uidoc.Selection.GetElementIds())
                {
                    Element element = doc.GetElement(id);
                    if (element != null && WiresModel.ElectricalConnectors(element).Count > 0) chosen.Add(element);
                }
                if (chosen.Count > 0)
                {
                    restrictTo = chosen;
                    report.InfoLine(chosen.Count + " fitting(s) selected, so only their circuits are wired.");
                }
            }
            catch (Exception)
            {
            }
            List<CircuitJob> jobs;
            View view = Prepare(uidoc, settings, report, out jobs, restrictTo);
            if (view == null) return report;

            // A deliberate pick means redraw it: the existing wires and tags come out first. The sweep leaves already-wired circuits alone.
            bool sweeping = restrictTo == null;
            if (sweeping && WiresSettings.Bool(settings, "skip_wired_circuits"))
            {
                int skipped = jobs.Count(j => j.ExistingWires.Count > 0);
                jobs = jobs.Where(j => j.ExistingWires.Count == 0).ToList();
                if (skipped > 0) report.InfoLine(skipped + " circuit(s) in this view already have wires and were left alone. Select one to redraw it.");
            }
            else if (!sweeping)
            {
                List<string> wired = jobs.Where(j => j.ExistingWires.Count > 0).Select(j => j.Label).ToList();
                if (wired.Count > 0) report.InfoLine("Redrawing " + string.Join(", ", wired) + ", so the existing wires and tags come out first.");
            }
            if (jobs.Count == 0)
            {
                if (restrictTo != null) report.NoteLine("Nothing selected is on a circuit that needs wiring.");
                else report.NoteLine("No circuited fittings in this view need wiring.");
                return report;
            }
            ReportLookups(doc, settings, report);
            var session = new Session(uidoc, settings, jobs, new Dictionary<string, List<Member>>(), report);
            session.Switches = CircuitCore.FindSwitchDevices(doc, view, settings);
            session.Start("RevoBIM Auto Wire");
            session.Place(0, restrictTo != null);
            FinishRun(session, settings, shufflePrompt, report, jobs.Count + " circuit(s) drawn.", "Auto Wire");
            return report;
        }

        /// <summary>Redraws one existing circuit: out with the old wires and tags, in with the route rules, then Shuffle until it reads right.</summary>
        public static Report RunRejig(UIApplication uiapp, Dictionary<string, string> settings, Func<Session, string, bool?> shufflePrompt = null)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            var report = new Report("Re-Route Wires");
            ElectricalSystem circuit = PickCircuit(uidoc, report);
            if (circuit == null) return report.Lines.Count > 0 ? report : null;
            List<CircuitJob> jobs;
            View view = Prepare(uidoc, settings, report, out jobs, null, circuit);
            if (view == null) return report;
            if (jobs.Count == 0)
            {
                report.NoteLine("That circuit has no fittings drawn in this view.");
                return report;
            }
            ReportLookups(doc, settings, report);
            var session = new Session(uidoc, settings, jobs, new Dictionary<string, List<Member>>(), report);
            session.Switches = CircuitCore.FindSwitchDevices(doc, view, settings);
            session.Start("RevoBIM Re-Route Wires");
            session.Place(0, true);
            FinishRun(session, settings, shufflePrompt, report, jobs[0].Label + " redrawn.", "Re-Route Wires");
            return report;
        }

        /// <summary>
        /// Keeps, shuffles or rolls back - and never hides why nothing was drawn: no prompt when nothing landed, and Cancel keeps the notes.
        /// </summary>
        private static void FinishRun(Session session, Dictionary<string, string> settings, Func<Session, string, bool?> shufflePrompt, Report report, string headline, string title)
        {
            if (session.Placed.Count == 0)
            {
                session.Cancel();
                report.NoteLine("Nothing was drawn. The notes above say why for each circuit.");
                return;
            }
            if (shufflePrompt != null && WiresSettings.Bool(settings, "preview_shuffle"))
            {
                bool? kept = shufflePrompt(session, headline);
                if (kept == null)
                {
                    // the prompt is floating and still open, so it owns the session now - and the command is about to return long before the route is settled
                    report.Deferred = true;
                    report.InfoLine("Shuffle is open - Revit is yours to pan and zoom while you judge the route.");
                    return;
                }
                if (!kept.Value)
                {
                    report.Drawn = 0;
                    report.InfoLine("Cancelled - the view is back as it was.");
                    return;
                }
            }
            session.Keep();
            report.Drawn = session.Placed.Count;
            report.OkLine(headline);
        }

        /// <summary>A circuit from whatever is selected, or picked.</summary>
        private static ElectricalSystem PickCircuit(UIDocument uidoc, Report report)
        {
            Document doc = uidoc.Document;
            var candidates = new List<Element>();
            try
            {
                foreach (ElementId id in uidoc.Selection.GetElementIds())
                {
                    Element element = doc.GetElement(id);
                    if (element != null) candidates.Add(element);
                }
            }
            catch (Exception)
            {
            }
            if (candidates.Count == 0)
            {
                try
                {
                    Reference reference = uidoc.Selection.PickObject(ObjectType.Element, "Select a wire or a fitting on the circuit to re-route");
                    Element element = doc.GetElement(reference.ElementId);
                    if (element != null) candidates.Add(element);
                }
                catch (Exception)
                {
                    return null;
                }
            }
            foreach (Element element in candidates)
            {
                var wire = element as Wire;
                if (wire == null) continue;
                ElectricalSystem circuit = WiresModel.WireCircuit(doc, wire);
                if (circuit != null) return circuit;
            }
            foreach (Element element in candidates)
            {
                List<ElectricalSystem> circuits = WiresModel.ElementCircuits(element);
                if (circuits.Count > 0) return circuits[0];
            }
            report.SkipLine("Nothing selected is on a circuit.");
            return null;
        }

        // ------------------------------------------------------------------ Apply Wire Types - the type, and nothing else
        /// <summary>Every wire drawn in the view, grouped by the circuit it belongs to (one pass: asking each circuit in turn would resolve every wire once per circuit).</summary>
        public static Dictionary<long, KeyValuePair<ElectricalSystem, List<Wire>>> WiresByCircuit(Document doc, View view, out List<Wire> loose)
        {
            var grouped = new Dictionary<long, KeyValuePair<ElectricalSystem, List<Wire>>>();
            loose = new List<Wire>();
            try
            {
                foreach (Element e in new FilteredElementCollector(doc, view.Id).OfClass(typeof(Wire)))
                {
                    var wire = (Wire)e;
                    ElectricalSystem circuit = WiresModel.WireCircuit(doc, wire);
                    if (circuit == null)
                    {
                        loose.Add(wire);
                        continue;
                    }
                    long key = circuit.Id.Value;
                    if (!grouped.ContainsKey(key)) grouped[key] = new KeyValuePair<ElectricalSystem, List<Wire>>(circuit, new List<Wire>());
                    grouped[key].Value.Add(wire);
                }
            }
            catch (Exception)
            {
            }
            return grouped;
        }

        /// <summary>The elements at each end of a wire, as far as it is connected.</summary>
        public static List<Element> WireEndpoints(Document doc, Wire wire)
        {
            var owners = new List<Element>();
            foreach (var end in WiresModel.WireEnds(wire))
            {
                Connector partner = WiresModel.OppositeConnector(end.Key);
                if (partner == null) continue;
                Element owner = null;
                try { owner = partner.Owner; } catch (Exception) { }
                if (owner != null && !WiresModel.IsWire(owner)) owners.Add(owner);
            }
            return owners;
        }

        /// <summary>
        /// Which type this wire should be, by the rules Auto Wire draws with: deliberately the same three questions in the same order, so a circuit drawn by Auto Wire
        /// and one retyped by this tool cannot disagree.
        /// </summary>
        private static ElementType WantedWireType(Document doc, Dictionary<string, string> settings, Wire wire, bool circuitEmergency, bool isLighting, ElementType baseType,
                                                  ElementType emergencyType, ElementType liveType, Dictionary<string, object> cache, out string why)
        {
            why = "";
            if (circuitEmergency && emergencyType != null)
            {
                why = "the circuit is emergency";
                return emergencyType;
            }
            if (isLighting && liveType != null)
            {
                List<Element> owners = WireEndpoints(doc, wire);
                if (owners.Count >= 2)
                {
                    string first = CircuitCore.LegKey(owners[0], doc, settings, cache);
                    string second = CircuitCore.LegKey(owners[1], doc, settings, cache);
                    if (first != second)
                    {
                        why = "it bridges two legs";
                        return liveType;
                    }
                }
            }
            return baseType;
        }

        /// <summary>Any member reading as emergency makes the circuit an emergency one.</summary>
        private static bool CircuitReadsEmergency(Document doc, Dictionary<string, string> settings, ElectricalSystem circuit, Dictionary<long, bool> cache)
        {
            long key = circuit.Id.Value;
            bool stored;
            if (cache != null && cache.TryGetValue(key, out stored)) return stored;
            bool answer = false;
            try
            {
                foreach (Element member in circuit.Elements)
                {
                    if (WiresModel.IsEmergency(member, doc, settings))
                    {
                        answer = true;
                        break;
                    }
                }
            }
            catch (Exception)
            {
                answer = false;
            }
            if (cache != null) cache[key] = answer;
            return answer;
        }

        private static bool CircuitIsLighting(Document doc, Dictionary<string, string> settings, ElectricalSystem circuit)
        {
            HashSet<long> lighting = new HashSet<long>();
            foreach (BuiltInCategory bic in WiresSettings.CategoriesFrom(WiresSettings.Get(settings, "lighting_categories", "lighting_fixtures"), null))
            {
                try { lighting.Add(new ElementId(bic).Value); } catch (Exception) { }
            }
            try
            {
                foreach (Element member in circuit.Elements)
                    if (lighting.Contains(member.Category.Id.Value)) return true;
            }
            catch (Exception)
            {
            }
            return false;
        }

        /// <summary>Sets the wire type on a circuit's wires. Nothing else is touched.</summary>
        private static int ApplyTypesToCircuit(Document doc, Dictionary<string, string> settings, ElectricalSystem circuit, List<Wire> wires, Report report,
                                               Dictionary<string, object> cache, Dictionary<long, bool> emergencyCache)
        {
            string label = WiresModel.CircuitLabel(circuit);
            bool isLighting = CircuitIsLighting(doc, settings, circuit);
            bool emergency = isLighting && CircuitReadsEmergency(doc, settings, circuit, emergencyCache);
            ElementType baseType = isLighting
                ? WiresModel.FindWireType(doc, WiresSettings.Get(settings, "lighting_wire_type"), cache)
                : WiresModel.FindWireType(doc, WiresSettings.Get(settings, "power_wire_type"), cache);
            ElementType emergencyType = WiresModel.FindWireType(doc, WiresSettings.Get(settings, "lighting_emergency_wire_type"), cache);
            ElementType liveType = WiresModel.FindWireType(doc, WiresSettings.Get(settings, "lighting_live_wire_type"), cache);
            if (baseType == null)
            {
                report.SkipLine(label + ": no wire type could be found, so nothing was changed.");
                return 0;
            }
            int changed = 0, already = 0, refused = 0;
            var tally = new Dictionary<string, int>();
            foreach (Wire wire in wires)
            {
                using (var sub = new SubTransaction(doc))
                {
                    sub.Start();
                    try
                    {
                        string why;
                        ElementType wanted = WantedWireType(doc, settings, wire, emergency, isLighting, baseType, emergencyType, liveType, cache, out why);
                        if (wanted == null)
                        {
                            sub.RollBack();
                            continue;
                        }
                        if (WiresModel.SameId(wire.GetTypeId(), wanted.Id))
                        {
                            already++;
                            sub.Commit();
                            continue;
                        }
                        wire.ChangeTypeId(wanted.Id);
                        // read back rather than trust it
                        if (WiresModel.SameId(wire.GetTypeId(), wanted.Id))
                        {
                            changed++;
                            string name = WiresModel.TypeName(wanted);
                            int c;
                            tally.TryGetValue(name, out c);
                            tally[name] = c + 1;
                            sub.Commit();
                        }
                        else
                        {
                            refused++;
                            sub.RollBack();
                        }
                    }
                    catch (Exception)
                    {
                        refused++;
                        try { sub.RollBack(); } catch (Exception) { }
                    }
                }
            }
            if (changed > 0)
            {
                IEnumerable<string> parts = tally.Keys.OrderBy(n => n, StringComparer.Ordinal).Select(n => tally[n] + " to " + n);
                report.OkLine(label + ": " + changed + " wire(s) retyped - " + string.Join(", ", parts) + ".");
            }
            if (already > 0 && changed == 0) report.InfoLine(label + ": all " + already + " wire(s) were already the right type.");
            else if (already > 0) report.InfoLine(label + ": " + already + " wire(s) were already right.");
            if (refused > 0) report.SkipLine(label + ": Revit refused the type on " + refused + " wire(s).");
            if (emergency) report.InfoLine(label + ": reads as an emergency circuit.");
            return changed;
        }

        /// <summary>Every circuit the current selection sits on, in selection order.</summary>
        public static List<ElectricalSystem> SelectedCircuits(UIDocument uidoc)
        {
            Document doc = uidoc.Document;
            var found = new List<ElectricalSystem>();
            var seen = new HashSet<long>();
            Action<ElectricalSystem> take = circuit =>
            {
                if (circuit == null) return;
                if (seen.Add(circuit.Id.Value)) found.Add(circuit);
            };
            try
            {
                foreach (ElementId id in uidoc.Selection.GetElementIds())
                {
                    Element element = doc.GetElement(id);
                    if (element == null) continue;
                    var wire = element as Wire;
                    if (wire != null)
                    {
                        take(WiresModel.WireCircuit(doc, wire));
                        continue;
                    }
                    var system = element as ElectricalSystem;
                    if (system != null)
                    {
                        take(system);
                        continue;
                    }
                    foreach (ElectricalSystem circuit in WiresModel.ElementCircuits(element)) take(circuit);
                }
            }
            catch (Exception)
            {
            }
            return found;
        }

        /// <summary>Sets wire types to match the settings. The drawing is not touched. Nothing selected: asks, then does every circuit with wires in the active view.</summary>
        public static Report RunApplyTypes(UIApplication uiapp, Dictionary<string, string> settings, Func<string, string, bool> confirm = null)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            View view = doc.ActiveView;
            var report = new Report("Apply Wire Types");
            var cache = new Dictionary<string, object>();
            var emergencyCache = new Dictionary<long, bool>();
            List<ElectricalSystem> chosen = SelectedCircuits(uidoc);
            if (chosen.Count == 0)
            {
                if (!WiresModel.IsPlanView(view))
                {
                    report.SkipLine("Nothing is selected, and this view is not a floor or ceiling plan. Select a circuit, or open a plan.");
                    return report;
                }
                if (confirm != null)
                {
                    string name = "this view";
                    try { name = view.Name; } catch (Exception) { }
                    if (!confirm("Apply wire types to every circuit in " + name + "?",
                                 "Only the wire type is set. Nothing is moved, redrawn, retagged or deleted. Select a circuit first to do just that one."))
                    {
                        report.InfoLine("Cancelled.");
                        return report;
                    }
                }
            }
            List<Wire> loose;
            var grouped = WiresByCircuit(doc, view, out loose);
            List<KeyValuePair<ElectricalSystem, List<Wire>>> work;
            if (chosen.Count > 0)
            {
                var wanted = new HashSet<long>(chosen.Select(c => c.Id.Value));
                work = grouped.Where(g => wanted.Contains(g.Key)).Select(g => g.Value).ToList();
                int missing = wanted.Count(w => !grouped.ContainsKey(w));
                if (missing > 0) report.NoteLine(missing + " selected circuit(s) have no wires drawn in this view.");
                report.InfoLine(chosen.Count + " circuit(s) selected.");
            }
            else work = grouped.Values.ToList();
            if (loose.Count > 0 && chosen.Count == 0)
                report.NoteLine(loose.Count + " wire(s) in this view belong to no circuit and were left alone. Reconnect Wires is the button for those.");
            if (work.Count == 0)
            {
                report.NoteLine("No circuits with wires were found to retype.");
                return report;
            }
            work = work.OrderBy(p => WiresModel.CircuitLabel(p.Key), StringComparer.Ordinal).ToList();

            int total = 0;
            using (var transaction = new Transaction(doc, "RevoBIM Apply Wire Types"))
            {
                WiresModel.ApplyFailureHandler(transaction);
                transaction.Start();
                try
                {
                    foreach (var pair in work) total += ApplyTypesToCircuit(doc, settings, pair.Key, pair.Value, report, cache, emergencyCache);
                    transaction.Commit();
                }
                catch (Exception error)
                {
                    try { transaction.RollBack(); } catch (Exception) { }
                    report.SkipLine("The run was rolled back: " + error.Message);
                    return report;
                }
            }
            report.Retyped = total;
            if (total > 0 && work.Count > 1) report.OkLine(total + " wire(s) retyped across " + work.Count + " circuit(s).");   // with one circuit this would only repeat the line above it
            else if (total == 0) report.InfoLine("Every wire was already the right type.");
            try { uidoc.RefreshActiveView(); } catch (Exception) { }
            return report;
        }

        // ------------------------------------------------------------------ Align Wire Ends - the arrival point, and nothing else
        /// <summary>The joined ends of one wire and where each should sit. A loose end has no fitting to be aligned to: guessing one is Reconnect Wires' job.</summary>
        private static List<EndTarget> WireEndTargets(Document doc, View view, Dictionary<string, string> settings, Wire wire)
        {
            List<XYZ> points = WiresModel.WireVertices(wire);
            var found = new List<EndTarget>();
            if (points.Count < 2) return found;
            int last = points.Count - 1;
            foreach (var end in WiresModel.WireEnds(wire))
            {
                Connector connector = end.Key;
                int index = end.Value;
                if (index != 0 && index != last) continue;
                Connector partner = WiresModel.OppositeConnector(connector);
                if (partner == null) continue;
                Element owner = null;
                try { owner = partner.Owner; } catch (Exception) { }
                if (owner == null || WiresModel.IsWire(owner)) continue;
                // the vertex the wire arrives from, which sets the direction
                XYZ neighbour = index == 0 ? points[1] : points[last - 1];
                if (WiresGeom.PlanDistance(neighbour, points[index]) < WiresSettings.Mm(0.1) && points.Count > 2) neighbour = index == 0 ? points[2] : points[last - 2];
                XYZ centre = null;
                try { centre = partner.Origin; } catch (Exception) { }
                if (centre == null) centre = WiresModel.ElementPoint(owner);
                if (centre == null) continue;
                XYZ target = WiresGeom.ArrivalPoint(view, settings, owner, centre, neighbour, points[index].Z);
                if (target == null) continue;
                found.Add(new EndTarget { Index = index, Owner = owner, Target = target, Connector = connector, Partner = partner });
            }
            return found;
        }

        private static string At(XYZ point)
        {
            return "(" + WiresSettings.ToMm(point.X).ToString("0", CultureInfo.InvariantCulture) + "," + WiresSettings.ToMm(point.Y).ToString("0", CultureInfo.InvariantCulture) + ")";
        }

        private static XYZ VertexNow(Wire wire, int index)
        {
            List<XYZ> points = WiresModel.WireVertices(wire);
            return index < points.Count ? points[index] : null;
        }

        private static string FirstLine(Exception error)
        {
            string text = error.Message ?? "";
            int nl = text.IndexOf('\n');
            return nl >= 0 ? text.Substring(0, nl).Trim() : text.Trim();
        }

        /// <summary>
        /// Resolves one end afresh: its connector, its partner, and its target. Resolved immediately before every attempt and never held across one: a sub-transaction that
        /// commits or rolls back invalidates the connector references taken before it.
        /// </summary>
        private static EndTarget EndState(Document doc, View view, Dictionary<string, string> settings, Wire wire, int index)
        {
            foreach (EndTarget t in WireEndTargets(doc, view, settings, wire)) if (t.Index == index) return t;
            return null;
        }

        private static bool TryMove(Document doc, View view, Dictionary<string, string> settings, Wire wire, int index, List<string> trace)
        {
            EndTarget state = EndState(doc, view, settings, wire, index);
            if (state == null)
            {
                trace.Add("    move: the end could not be resolved again");
                return false;
            }
            using (var sub = new SubTransaction(doc))
            {
                sub.Start();
                try
                {
                    wire.SetVertex(index, state.Target);
                    doc.Regenerate();
                }
                catch (Exception error)
                {
                    sub.RollBack();
                    trace.Add("    move: refused (" + FirstLine(error) + ")");
                    return false;
                }
                XYZ landed = VertexNow(wire, index);
                if (landed != null && WiresGeom.PlanDistance(landed, state.Target) <= WiresSettings.Mm(0.5))
                {
                    sub.Commit();
                    trace.Add("    move: took, now " + At(landed));
                    return true;
                }
                sub.RollBack();
                trace.Add("    move: returned without moving it");
                return false;
            }
        }

        // How far back from the node to try, in millimetres, when the node itself is refused. The first that Revit accepts wins.
        private static readonly int[] NudgeSteps = { 0, 2, 5, 10, 15, 25, 40 };
        // How far to shove the end before dropping it back on the node. Small first: the hand barely moves it.
        private static readonly double[] RedockShoves = { 300.0, 1500.0 };

        /// <summary>The vertex indices of the ends that are joined to a fitting. Where they should go is Revit's to answer.</summary>
        private static List<int> WireJoinedEnds(Document doc, Wire wire)
        {
            List<XYZ> points = WiresModel.WireVertices(wire);
            var found = new List<int>();
            if (points.Count < 2) return found;
            int last = points.Count - 1;
            foreach (var end in WiresModel.WireEnds(wire))
            {
                if (end.Value != 0 && end.Value != last) continue;
                Connector partner = WiresModel.OppositeConnector(end.Key);
                if (partner == null) continue;
                Element owner;
                try { owner = partner.Owner; } catch (Exception) { continue; }
                if (owner == null || WiresModel.IsWire(owner)) continue;
                found.Add(end.Value);
            }
            return found;
        }

        /// <summary>
        /// Does what the hand does: drag the end off, drag it back on, let go. Disconnect the end, move the vertex well clear so Revit has to recompute, put it on the
        /// connector, reconnect. The test is not "did it land on my target" but "did it end up nearer the node than it started", because the exact spot is Revit's to choose.
        /// </summary>
        private static bool TryRedock(Document doc, View view, Dictionary<string, string> settings, Wire wire, int index, List<string> trace)
        {
            EndTarget first = EndState(doc, view, settings, wire, index);
            if (first == null || first.Connector == null || first.Partner == null)
            {
                trace.Add("    redock: no connector pair");
                return false;
            }
            XYZ node;
            try
            {
                node = first.Partner.Origin;
            }
            catch (Exception)
            {
                trace.Add("    redock: the node could not be read");
                return false;
            }
            XYZ here = VertexNow(wire, index);
            if (here == null) return false;
            double was = WiresGeom.PlanDistance(here, node);
            foreach (double shove in RedockShoves)
            {
                EndTarget state = EndState(doc, view, settings, wire, index);
                if (state == null || state.Connector == null || state.Partner == null) return false;
                using (var sub = new SubTransaction(doc))
                {
                    sub.Start();
                    try
                    {
                        state.Connector.DisconnectFrom(state.Partner);
                        doc.Regenerate();
                        var away = new XYZ(here.X + WiresSettings.Mm(shove), here.Y + WiresSettings.Mm(shove), here.Z);
                        wire.SetVertex(index, away);
                        doc.Regenerate();
                        wire.SetVertex(index, new XYZ(node.X, node.Y, here.Z));
                        doc.Regenerate();
                        state.Connector.ConnectTo(state.Partner);
                        doc.Regenerate();
                    }
                    catch (Exception error)
                    {
                        sub.RollBack();
                        trace.Add("    redock " + shove.ToString("0", CultureInfo.InvariantCulture) + "mm: refused (" + FirstLine(error) + ")");
                        continue;
                    }
                    XYZ landed = VertexNow(wire, index);
                    if (landed == null)
                    {
                        sub.RollBack();
                        trace.Add("    redock " + shove.ToString("0", CultureInfo.InvariantCulture) + "mm: the vertex went away");
                        continue;
                    }
                    double now = WiresGeom.PlanDistance(landed, node);
                    if (now < was - WiresSettings.Mm(1))
                    {
                        sub.Commit();
                        trace.Add("    redock " + shove.ToString("0", CultureInfo.InvariantCulture) + "mm: took, now " + At(landed) + ", " +
                                  WiresSettings.ToMm(now).ToString("0", CultureInfo.InvariantCulture) + "mm from the node (was " + WiresSettings.ToMm(was).ToString("0", CultureInfo.InvariantCulture) + "mm)");
                        return true;
                    }
                    sub.RollBack();
                    trace.Add("    redock " + shove.ToString("0", CultureInfo.InvariantCulture) + "mm: no closer (" + WiresSettings.ToMm(now).ToString("0", CultureInfo.InvariantCulture) +
                              "mm, was " + WiresSettings.ToMm(was).ToString("0", CultureInfo.InvariantCulture) + "mm)");
                }
            }
            return false;
        }

        /// <summary>
        /// Shoves the end, then walks it in towards the node. Revit refuses a vertex that lands within tolerance of one it already holds - so first the vertex is shoved
        /// somewhere free and put straight back; if that does not do it, the end is set at increasing distances back from the node until one is accepted.
        /// </summary>
        private static bool TryNudge(Document doc, View view, Dictionary<string, string> settings, Wire wire, int index, List<string> trace)
        {
            EndTarget state = EndState(doc, view, settings, wire, index);
            if (state == null)
            {
                trace.Add("    nudge: the end could not be resolved again");
                return false;
            }
            XYZ target = state.Target;
            XYZ here = VertexNow(wire, index);
            if (here == null) return false;
            double closeEnough = WiresSettings.Mm(WiresSettings.Float(settings, "align_max_gap_mm"));
            // shove it and put it back
            foreach (double distance in new[] { 50.0, 200.0 })
            {
                using (var sub = new SubTransaction(doc))
                {
                    sub.Start();
                    try
                    {
                        var away = new XYZ(here.X + WiresSettings.Mm(distance), here.Y + WiresSettings.Mm(distance), here.Z);
                        wire.SetVertex(index, away);
                        doc.Regenerate();
                        wire.SetVertex(index, here);
                        doc.Regenerate();
                    }
                    catch (Exception error)
                    {
                        sub.RollBack();
                        trace.Add("    nudge " + distance.ToString("0", CultureInfo.InvariantCulture) + "mm: refused (" + FirstLine(error) + ")");
                        continue;
                    }
                    XYZ landed = VertexNow(wire, index);
                    if (landed != null && WiresGeom.PlanDistance(landed, target) <= closeEnough)
                    {
                        sub.Commit();
                        trace.Add("    nudge " + distance.ToString("0", CultureInfo.InvariantCulture) + "mm: Revit re-seated it, now " + At(landed));
                        return true;
                    }
                    sub.RollBack();
                    trace.Add("    nudge " + distance.ToString("0", CultureInfo.InvariantCulture) + "mm: no re-seat");
                }
            }
            // walk in from the node until Revit takes it
            double dx = here.X - target.X, dy = here.Y - target.Y;
            double reach = Math.Sqrt(dx * dx + dy * dy);
            if (reach < 1.0e-9) return false;
            double ux = dx / reach, uy = dy / reach;
            foreach (int back in NudgeSteps)
            {
                var point = new XYZ(target.X + ux * WiresSettings.Mm(back), target.Y + uy * WiresSettings.Mm(back), here.Z);
                using (var sub = new SubTransaction(doc))
                {
                    sub.Start();
                    try
                    {
                        wire.SetVertex(index, point);
                        doc.Regenerate();
                    }
                    catch (Exception error)
                    {
                        sub.RollBack();
                        trace.Add("    step " + back + "mm: refused (" + FirstLine(error) + ")");
                        continue;
                    }
                    XYZ landed = VertexNow(wire, index);
                    if (landed == null)
                    {
                        sub.RollBack();
                        continue;
                    }
                    double gap = WiresGeom.PlanDistance(landed, target);
                    if (gap <= closeEnough)
                    {
                        sub.Commit();
                        trace.Add("    step " + back + "mm: took, now " + At(landed) + ", " + WiresSettings.ToMm(gap).ToString("0", CultureInfo.InvariantCulture) + "mm from the node");
                        return true;
                    }
                    sub.RollBack();
                    trace.Add("    step " + back + "mm: landed " + WiresSettings.ToMm(gap).ToString("0", CultureInfo.InvariantCulture) + "mm away, not close enough");
                }
            }
            return false;
        }

        /// <summary>Disconnects the end and reconnects it, so Revit re-seats it.</summary>
        private static bool TryJiggle(Document doc, View view, Dictionary<string, string> settings, Wire wire, int index, List<string> trace)
        {
            EndTarget state = EndState(doc, view, settings, wire, index);
            if (state == null || state.Connector == null || state.Partner == null)
            {
                trace.Add("    jiggle: no connector pair to re-seat");
                return false;
            }
            using (var sub = new SubTransaction(doc))
            {
                sub.Start();
                try
                {
                    state.Connector.DisconnectFrom(state.Partner);
                    state.Connector.ConnectTo(state.Partner);
                    doc.Regenerate();
                }
                catch (Exception error)
                {
                    sub.RollBack();
                    trace.Add("    jiggle: refused (" + FirstLine(error) + ")");
                    return false;
                }
                XYZ landed = VertexNow(wire, index);
                if (landed == null)
                {
                    sub.RollBack();
                    trace.Add("    jiggle: the vertex went away");
                    return false;
                }
                if (WiresGeom.PlanDistance(landed, state.Target) <= WiresSettings.Mm(0.5))
                {
                    sub.Commit();
                    trace.Add("    jiggle: took, now " + At(landed));
                    return true;
                }
                sub.RollBack();
                trace.Add("    jiggle: re-seated at " + At(landed) + ", not the target");
                return false;
            }
        }

        /// <summary>
        /// Builds the wire again with its ends where they belong: the only route that can put a vertex exactly where it is asked for, at the cost of the element id, so any tag
        /// hosted on the wire is snapshotted first and re-pointed at the replacement.
        /// </summary>
        private static Wire TryRebuild(Document doc, View view, Dictionary<string, string> settings, Wire wire, List<string> trace)
        {
            List<EndTarget> targets = WireEndTargets(doc, view, settings, wire);
            if (targets.Count == 0)
            {
                trace.Add("    rebuild: no joined end to aim at");
                return null;
            }
            List<XYZ> points = WiresModel.WireVertices(wire);
            if (points.Count < 2)
            {
                trace.Add("    rebuild: fewer than two vertices");
                return null;
            }
            int last = points.Count - 1;
            Connector start = null, finish = null;
            foreach (EndTarget t in targets)
            {
                if (t.Index < points.Count) points[t.Index] = t.Target;
                if (t.Index == 0) start = t.Partner;
                else if (t.Index == last) finish = t.Partner;
            }
            var shots = new List<CircuitCore.TagShot>();
            foreach (IndependentTag tag in CircuitCore.TagsOn(doc, doc.ActiveView, new Element[] { wire }))
            {
                CircuitCore.TagShot shot = CircuitCore.SnapshotTag(doc, tag);
                if (shot != null) shots.Add(shot);
            }
            using (var sub = new SubTransaction(doc))
            {
                sub.Start();
                Wire rebuilt;
                try
                {
                    rebuilt = WiresModel.RebuildWire(doc, wire, points, start, finish);
                }
                catch (Exception error)
                {
                    sub.RollBack();
                    trace.Add("    rebuild: refused (" + FirstLine(error) + ")");
                    return null;
                }
                if (rebuilt == null)
                {
                    sub.RollBack();
                    trace.Add("    rebuild: Revit returned no wire");
                    return null;
                }
                int putBack = 0;
                foreach (CircuitCore.TagShot shot in shots)
                    if (CircuitCore.RestoreTag(doc, shot, rebuilt) != null) putBack++;
                sub.Commit();
                trace.Add("    rebuild: took, new id " + rebuilt.Id.Value + (shots.Count > 0 ? ", " + putBack + " tag(s) re-placed" : ""));
                return rebuilt;
            }
        }

        /// <summary>Everything Revit will tell us about one wire, written out in full (asking it directly instead of inferring from the way it refuses).</summary>
        private static void LogWireGeometry(Document doc, View view, Dictionary<string, string> settings, Wire wire, List<string> trace)
        {
            trace.Add("  geometry of wire " + wire.Id.Value + ":");
            string kind, typeName;
            try { kind = WiresModel.WiringTypeOf(wire).ToString(); } catch (Exception) { kind = "?"; }
            try { typeName = WiresModel.TypeName(doc.GetElement(wire.GetTypeId())); } catch (Exception) { typeName = "?"; }
            trace.Add("    type " + typeName + ", wiring " + kind);
            List<XYZ> points = WiresModel.WireVertices(wire);
            trace.Add("    " + points.Count + " vertices: " + string.Join(" ", points.Select(At)));
            foreach (var end in WiresModel.WireEnds(wire))
            {
                Connector connector = end.Key;
                string where, joined;
                try
                {
                    XYZ origin = connector.Origin;
                    where = At(origin) + " z=" + WiresSettings.ToMm(origin.Z).ToString("0", CultureInfo.InvariantCulture);
                }
                catch (Exception) { where = "?"; }
                try { joined = connector.IsConnected.ToString(); } catch (Exception) { joined = "?"; }
                trace.Add("    wire connector -> vertex " + end.Value + ", origin " + where + ", connected " + joined);
                Connector partner = WiresModel.OppositeConnector(connector);
                if (partner == null)
                {
                    trace.Add("      joined to nothing");
                    continue;
                }
                try
                {
                    XYZ origin = partner.Origin;
                    trace.Add("      partner origin " + At(origin) + " z=" + WiresSettings.ToMm(origin.Z).ToString("0", CultureInfo.InvariantCulture));
                }
                catch (Exception) { trace.Add("      partner origin unreadable"); }
                try
                {
                    Element owner = partner.Owner;
                    trace.Add("      on " + WiresModel.ElementName(owner) + " (id " + owner.Id.Value + ", " + owner.Category.Name + ")");
                    XYZ spot = WiresModel.ElementPoint(owner);
                    if (spot != null) trace.Add("      its location " + At(spot) + " z=" + WiresSettings.ToMm(spot.Z).ToString("0", CultureInfo.InvariantCulture));
                    BoundingBoxXYZ box = owner.get_BoundingBox(view);
                    if (box != null) trace.Add("      its box " + At(box.Min) + " to " + At(box.Max));
                    List<Connector> others = WiresModel.ElectricalConnectors(owner);
                    trace.Add("      it has " + others.Count + " electrical connector(s)");
                    foreach (Connector other in others)
                    {
                        try
                        {
                            trace.Add("        connector at " + At(other.Origin) + " z=" + WiresSettings.ToMm(other.Origin.Z).ToString("0", CultureInfo.InvariantCulture) + ", connected " + other.IsConnected);
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
                catch (Exception error)
                {
                    trace.Add("      owner unreadable (" + error.Message + ")");
                }
            }
        }

        /// <summary>
        /// Puts a wire's joined ends where they belong. On auto there is no target: every joined end is re-docked and kept only if it finished nearer the node than it started
        /// (Revit works out the arrival correctly the moment a wire is re-docked, so the destination does not belong in this tool). The other methods still aim at align_target.
        /// Returns moved, refused, already and the replacement wire where one was rebuilt.
        /// </summary>
        private static void AlignOneWire(Document doc, View view, Dictionary<string, string> settings, Wire wire, double tolerance, Report report,
                                         out int moved, out int refused, out int already, out Wire replacement)
        {
            replacement = null;
            List<string> trace = report != null ? report.Trace : new List<string>();
            long wireId = wire.Id.Value;
            if (WiresSettings.Bool(settings, "debug_geometry")) LogWireGeometry(doc, view, settings, wire, trace);
            string method = WiresSettings.Lower(settings, "align_method", "auto");
            if (method == "auto" || method == "redock")
            {
                List<int> ends = WireJoinedEnds(doc, wire);
                moved = refused = already = 0;
                if (ends.Count == 0) return;
                trace.Add("wire " + wireId + ": " + ends.Count + " joined end(s), re-docking");
                int settled = 0;
                foreach (int index in ends)
                {
                    XYZ here = VertexNow(wire, index);
                    trace.Add("  end " + index + " at " + (here != null ? At(here) : "?"));
                    if (TryRedock(doc, view, settings, wire, index, trace)) moved++;
                    else settled++;
                }
                already = settled;
                return;
            }
            // the aimed methods, which need a target
            List<EndTarget> targets = WireEndTargets(doc, view, settings, wire);
            moved = refused = already = 0;
            if (targets.Count == 0) return;
            List<XYZ> points = WiresModel.WireVertices(wire);
            var todo = new List<Tuple<int, XYZ>>();
            foreach (EndTarget t in targets)
            {
                if (t.Index >= points.Count) continue;
                if (WiresGeom.PlanDistance(points[t.Index], t.Target) <= tolerance)
                {
                    already++;
                    continue;
                }
                todo.Add(Tuple.Create(t.Index, t.Target));
            }
            if (todo.Count == 0) return;
            trace.Add("wire " + wireId + ": " + todo.Count + " end(s) to move, by " + method);
            foreach (var item in todo)
            {
                XYZ here = VertexNow(wire, item.Item1);
                trace.Add("  end " + item.Item1 + ": " + (here != null ? At(here) : "?") + " -> " + At(item.Item2));
                bool done = false;
                if (method == "move") done = TryMove(doc, view, settings, wire, item.Item1, trace);
                else if (method == "nudge") done = TryNudge(doc, view, settings, wire, item.Item1, trace);
                else if (method == "jiggle") done = TryJiggle(doc, view, settings, wire, item.Item1, trace);
                if (done) moved++;
                else refused++;
            }
            if (refused > 0 && (method == "auto+rebuild" || method == "rebuild"))
            {
                Wire rebuilt = TryRebuild(doc, view, settings, wire, trace);
                if (rebuilt != null)
                {
                    replacement = rebuilt;
                    moved = todo.Count;
                    refused = 0;
                }
            }
        }

        /// <summary>Pulls wire ends onto the fittings they are joined to. Nothing selected: asks, then every wire in the active view. Wires selected: just those. Circuits selected: every wire on them.</summary>
        public static Report RunAlignEnds(UIApplication uiapp, Dictionary<string, string> settings, Func<string, string, bool> confirm = null)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            Document doc = uidoc.Document;
            View view = doc.ActiveView;
            var report = new Report("Align Wire Ends");
            if (!WiresModel.IsPlanView(view))
            {
                report.SkipLine("Wires are only drawn on a floor plan or a ceiling plan. Open one and run again.");
                return report;
            }
            var pickedWires = new List<Wire>();
            var seenWires = new HashSet<long>();
            try
            {
                foreach (ElementId id in uidoc.Selection.GetElementIds())
                {
                    var w = doc.GetElement(id) as Wire;
                    if (w != null && seenWires.Add(w.Id.Value)) pickedWires.Add(w);
                }
            }
            catch (Exception)
            {
            }
            List<ElectricalSystem> pickedCircuits = SelectedCircuits(uidoc);
            List<Wire> loose;
            var grouped = WiresByCircuit(doc, view, out loose);

            var work = new List<Wire>();
            if (pickedWires.Count > 0)
            {
                work = pickedWires.ToList();
                report.InfoLine(work.Count + " wire(s) selected.");
            }
            if (pickedCircuits.Count > 0)
            {
                var wanted = new HashSet<long>(pickedCircuits.Select(c => c.Id.Value));
                int added = 0;
                var have = new HashSet<long>(work.Select(w => w.Id.Value));
                foreach (var entry in grouped)
                {
                    if (!wanted.Contains(entry.Key)) continue;
                    foreach (Wire wire in entry.Value.Value)
                    {
                        if (!have.Contains(wire.Id.Value))
                        {
                            work.Add(wire);
                            added++;
                        }
                    }
                }
                if (added > 0) report.InfoLine(added + " wire(s) on " + pickedCircuits.Count + " selected circuit(s).");
            }
            if (work.Count == 0)
            {
                if (confirm != null)
                {
                    string name = "this view";
                    try { name = view.Name; } catch (Exception) { }
                    if (!confirm("Align every wire end in " + name + "?",
                                 "Only the point where a wire meets its fitting is moved. Nothing is retyped, retagged, reconnected or deleted, and no wire changes its element id. " +
                                 "Select wires or circuits first to do just those."))
                    {
                        report.InfoLine("Cancelled.");
                        return report;
                    }
                }
                foreach (var entry in grouped) work.AddRange(entry.Value.Value);
                work.AddRange(loose);
            }
            if (work.Count == 0)
            {
                report.NoteLine("No wires were found in this view.");
                return report;
            }
            double tolerance = WiresSettings.Mm(WiresSettings.Float(settings, "align_tolerance_mm"));
            string mode = WiresSettings.Lower(settings, "align_target", "trim");
            report.InfoLine("Ends are set " + (mode == "centre" ? "on the connector at the symbol centre" : "short of the symbol, by the trim setting") + ".");

            int movedTotal = 0, refusedTotal = 0, alreadyTotal = 0, untouched = 0, rebuilds = 0;
            using (var transaction = new Transaction(doc, "RevoBIM Align Wire Ends"))
            {
                WiresModel.ApplyFailureHandler(transaction);
                transaction.Start();
                try
                {
                    foreach (Wire wire in work)
                    {
                        using (var sub = new SubTransaction(doc))
                        {
                            sub.Start();
                            try
                            {
                                int m, r, a;
                                Wire rebuilt;
                                AlignOneWire(doc, view, settings, wire, tolerance, report, out m, out r, out a, out rebuilt);
                                if (rebuilt != null) rebuilds++;
                                if (m == 0 && r == 0 && a == 0) untouched++;
                                movedTotal += m;
                                refusedTotal += r;
                                alreadyTotal += a;
                                sub.Commit();
                            }
                            catch (Exception)
                            {
                                sub.RollBack();
                                refusedTotal++;
                            }
                        }
                    }
                    transaction.Commit();
                }
                catch (Exception error)
                {
                    try { transaction.RollBack(); } catch (Exception) { }
                    report.SkipLine("The run was rolled back: " + error.Message);
                    return report;
                }
            }
            report.Aligned = movedTotal;
            if (movedTotal > 0) report.OkLine(movedTotal + " wire end(s) pulled onto their fitting, across " + work.Count + " wire(s).");
            if (alreadyTotal > 0) report.InfoLine(alreadyTotal + " end(s) were left as they were - Revit put them back in the same place, so they were already right.");
            if (untouched > 0) report.InfoLine(untouched + " wire(s) had no end joined to a fitting and were left alone.");
            if (rebuilds > 0) report.NoteLine(rebuilds + " wire(s) could not be moved or re-seated and were rebuilt instead, so those have new element ids.");
            if (refusedTotal > 0) report.NoteLine("Revit refused every route on " + refusedTotal + " end(s). The debug report says what each one did.");
            if (movedTotal == 0 && refusedTotal == 0) report.InfoLine("Every wire end was already where it belongs.");
            try { uidoc.RefreshActiveView(); } catch (Exception) { }
            return report;
        }
    }
}
