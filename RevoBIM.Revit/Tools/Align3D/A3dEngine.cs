using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Mechanical;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.Align3D
{
    /// <summary>One line of the results window.</summary>
    public sealed class A3dRow
    {
        public string Kind = "";           // ok | already | warn | refused | failed
        public string First = "";
        public string Second = "";
        public string Mode = "";
        public double? MovedMm;
        public string Note = "";
    }

    /// <summary>Reset each run, written once at the end, with the build line first.</summary>
    public sealed class A3dLog
    {
        private readonly bool enabled;
        private readonly List<string> lines = new List<string>();

        public A3dLog(bool enabled)
        {
            this.enabled = enabled;
            Write("3D Align " + A3dSettings.Version + " (" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + ")");
            Write("build: " + A3dSettings.BuildInfo());
        }

        public void Write(string text)
        {
            if (enabled) lines.Add(text);
        }

        public void Flush()
        {
            if (!enabled) return;
            try
            {
                Directory.CreateDirectory(A3dSettings.DataDir());
                File.WriteAllText(A3dSettings.DebugPath(), string.Join("\r\n", lines) + "\r\n", new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }

    /// <summary>
    /// 3D Align - the picks, the move, and the proof that it landed (port of a3d_core.py). Windowless: settings are read from
    /// file and the tool goes straight to the picks. The results window opens only when something needs a look.
    /// </summary>
    public static class A3dEngine
    {
        private const string TransactionName = "RevoBIM 3D Align";

        private static readonly BuiltInCategory[] TargetCategories =
        {
            BuiltInCategory.OST_PipeCurves, BuiltInCategory.OST_DuctCurves, BuiltInCategory.OST_CableTray, BuiltInCategory.OST_Conduit,
        };

        private static readonly HashSet<string> NeedsLook = new HashSet<string> { "warn", "refused", "failed" };

        // ---------------------------------------------------------------- small helpers --

        private static long Key(ElementId id) { return id == null ? 0 : id.Value; }

        private static double FtToMm(double v) { return v * A3dSettings.MmPerFt; }

        private static HashSet<long> TargetCategoryIds()
        {
            return new HashSet<long>(TargetCategories.Select(c => (long)(int)c));
        }

        private static A3dPoint Pt(XYZ p) { return new A3dPoint(p.X, p.Y, p.Z); }

        /// <summary>The two ends of the element's centreline, or null if it is not a straight location line.</summary>
        public static A3dAxis AxisOf(Element element)
        {
            if (element == null) return null;
            try
            {
                var location = element.Location as LocationCurve;
                if (location == null) return null;
                var line = location.Curve as Line;
                if (line == null) return null;
                return new A3dAxis(Pt(line.GetEndPoint(0)), Pt(line.GetEndPoint(1)));
            }
            catch (Exception)
            {
                return null;
            }
        }

        public static bool IsTarget(Element element, HashSet<long> categories = null)
        {
            categories = categories ?? TargetCategoryIds();
            try
            {
                return categories.Contains(Key(element.Category.Id)) && AxisOf(element) != null;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static string Describe(Element element)
        {
            if (element == null) return "(nothing)";
            string name = "Element";
            try { name = element.Category.Name; } catch (Exception) { }
            string size = "";
            try
            {
                Parameter p = element.get_Parameter(BuiltInParameter.RBS_CALCULATED_SIZE);
                if (p != null) size = p.AsString() ?? "";
            }
            catch (Exception)
            {
            }
            return (name + " " + size).Trim() + " [" + Key(element.Id) + "]";
        }

        // ---------------------------------------------------------------- picking --

        /// <summary>
        /// Straight pipes, ducts, cable trays and conduits. The datum cannot be picked twice, and after a horizontal datum only
        /// uprights are offered, because two horizontals is not an alignment this tool makes.
        /// </summary>
        private sealed class AlignFilter : ISelectionFilter
        {
            private readonly HashSet<long> categories = TargetCategoryIds();
            private readonly long? exclude;
            private readonly string needKind;

            public AlignFilter(long? excludeId, string needKind)
            {
                exclude = excludeId;
                this.needKind = needKind;
            }

            public bool AllowElement(Element element)
            {
                try
                {
                    if (exclude != null && Key(element.Id) == exclude.Value) return false;
                    if (!IsTarget(element, categories)) return false;
                    return needKind == null || A3dGeom.Classify(AxisOf(element)) == needKind;
                }
                catch (Exception)
                {
                    return false;
                }
            }

            public bool AllowReference(Reference reference, XYZ position) { return false; }
        }

        /// <summary>The picked element, or null on Escape.</summary>
        private static Element Pick(UIDocument uidoc, string prompt, long? excludeId, string needKind)
        {
            try
            {
                Reference reference = uidoc.Selection.PickObject(ObjectType.Element, new AlignFilter(excludeId, needKind), prompt);
                return reference == null ? null : uidoc.Document.GetElement(reference.ElementId);
            }
            catch (Autodesk.Revit.Exceptions.OperationCanceledException)
            {
                return null;
            }
        }

        /// <summary>The element selected before the button was pressed, if it is exactly one straight pipe, duct, cable tray or conduit.</summary>
        private static Element Preselected(UIDocument uidoc, A3dLog log)
        {
            List<ElementId> ids;
            try { ids = uidoc.Selection.GetElementIds().ToList(); } catch (Exception) { return null; }
            if (ids.Count != 1)
            {
                if (ids.Count > 0) log.Write(ids.Count + " elements were selected - picking the datum instead");
                return null;
            }
            Element element = uidoc.Document.GetElement(ids[0]);
            if (element == null || !IsTarget(element))
            {
                log.Write("The selected element is not a straight pipe, duct, tray or conduit");
                return null;
            }
            return element;
        }

        private static void Highlight(UIDocument uidoc, Element element)
        {
            try
            {
                var ids = new List<ElementId>();
                if (element != null) ids.Add(element.Id);
                uidoc.Selection.SetElementIds(ids);
            }
            catch (Exception)
            {
            }
        }

        // ---------------------------------------------------------------- writing --

        /// <summary>Warnings deleted; an error rolls the transaction back quietly and its text is kept so the report can say what Revit said.</summary>
        private sealed class Failures : IFailuresPreprocessor
        {
            public readonly List<string> Errors = new List<string>();
            public int Warnings;

            public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
            {
                bool rollback = false;
                try
                {
                    foreach (FailureMessageAccessor message in accessor.GetFailureMessages().ToList())
                    {
                        FailureSeverity severity = FailureSeverity.None;
                        try { severity = message.GetSeverity(); } catch (Exception) { }
                        if (severity == FailureSeverity.Warning)
                        {
                            try
                            {
                                accessor.DeleteWarning(message);
                                Warnings++;
                            }
                            catch (Exception)
                            {
                            }
                        }
                        else
                        {
                            rollback = true;
                            try { Errors.Add(message.GetDescriptionText()); } catch (Exception) { Errors.Add("Revit raised an error"); }
                        }
                    }
                }
                catch (Exception)
                {
                }
                return rollback ? FailureProcessingResult.ProceedWithRollBack : FailureProcessingResult.Continue;
            }
        }

        /// <summary>One transaction, failures handled, and the commit status checked rather than assumed.</summary>
        private static bool RunTransaction(Document doc, Action work, out Failures failures)
        {
            failures = new Failures();
            using (var transaction = new Transaction(doc, TransactionName))
            {
                FailureHandlingOptions options = transaction.GetFailureHandlingOptions();
                options.SetFailuresPreprocessor(failures);
                options.SetClearAfterRollback(true);
                transaction.SetFailureHandlingOptions(options);
                transaction.Start();
                try
                {
                    work();
                }
                catch (Exception error)
                {
                    failures.Errors.Add(error.Message);
                    try { if (transaction.HasStarted()) transaction.RollBack(); } catch (Exception) { }
                    return false;
                }
                return transaction.Commit() == TransactionStatus.Committed;
            }
        }

        private static List<Connector> ConnectorsOf(Element element)
        {
            var output = new List<Connector>();
            try
            {
                var curve = element as MEPCurve;
                if (curve != null)
                    foreach (Connector c in curve.ConnectorManager.Connectors) output.Add(c);
            }
            catch (Exception)
            {
            }
            return output;
        }

        private static int ConnectedCount(Element element)
        {
            int count = 0;
            foreach (Connector c in ConnectorsOf(element))
            {
                try { if (c.IsConnected) count++; } catch (Exception) { }
            }
            return count;
        }

        /// <summary>A connector joined to another element, not the logical link to the element's own MEP system.</summary>
        private static bool PhysicalRef(Element element, Connector other)
        {
            try
            {
                if (Key(other.Owner.Id) == Key(element.Id)) return false;
                if (other.Owner.GetType().Name.Contains("System")) return false;
                return ((int)other.ConnectorType & 3) != 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static int DisconnectAll(Element element)
        {
            int released = 0;
            foreach (Connector connector in ConnectorsOf(element))
            {
                try
                {
                    if (!connector.IsConnected) continue;
                    foreach (Connector other in connector.AllRefs.Cast<Connector>().ToList())
                    {
                        if (!PhysicalRef(element, other)) continue;
                        try
                        {
                            connector.DisconnectFrom(other);
                            released++;
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
            return released;
        }

        private static string OwnerOf(Document doc, ElementId id)
        {
            try
            {
                string owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, id).Owner;
                if (!string.IsNullOrEmpty(owner)) return owner + " has it borrowed";
            }
            catch (Exception)
            {
            }
            try
            {
                Element element = doc.GetElement(id);
                Workset workset = doc.GetWorksetTable().GetWorkset(element.WorksetId);
                if (!string.IsNullOrEmpty(workset.Owner)) return "workset \"" + workset.Name + "\" is owned by " + workset.Owner;
            }
            catch (Exception)
            {
            }
            return "another user has it";
        }

        /// <summary>
        /// True when the element can be written, else false and who has it. On a workshared model a write to an element that is
        /// not borrowed writes nothing and says nothing, so it is borrowed before the transaction.
        /// </summary>
        private static bool Borrow(Document doc, ElementId id, out string holder)
        {
            holder = "";
            try { if (!doc.IsWorkshared) return true; } catch (Exception) { return true; }
            try
            {
                foreach (ElementId held in WorksharingUtils.CheckoutElements(doc, new List<ElementId> { id }))
                    if (Key(held) == Key(id)) return true;
            }
            catch (Exception)
            {
            }
            holder = OwnerOf(doc, id);
            return false;
        }

        // ---------------------------------------------------------------- one alignment --

        private static A3dRow NewRow(Element first, Element second, string kind, string note, string mode = "", double? movedMm = null)
        {
            return new A3dRow { Kind = kind, First = Describe(first), Second = Describe(second), Mode = mode, MovedMm = movedMm, Note = note };
        }

        /// <summary>Moves the second element onto the first in plan, then proves it.</summary>
        private static A3dRow Align(Document doc, Element first, Element second, Dictionary<string, string> settings, A3dLog log)
        {
            if (Key(first.Id) == Key(second.Id)) return NewRow(first, second, "refused", "the same element was clicked twice");
            A3dAxis firstAxis = AxisOf(first), secondAxis = AxisOf(second);
            if (firstAxis == null || secondAxis == null) return NewRow(first, second, "refused", "not a straight run - no centreline to align");

            A3dPlan plan = A3dGeom.PlanAlignment(firstAxis, secondAxis);
            string mode = plan.Mode;
            log.Write(Describe(first) + " -> " + Describe(second) + ": " + plan.FirstKind + " / " + plan.SecondKind + ", move " + FtToMm(plan.Distance).ToString("0.00") + "mm");
            if (!plan.Ok) return NewRow(first, second, "refused", plan.Reason, mode);
            double movedMm = FtToMm(plan.Distance);
            if (plan.Already)
                return NewRow(first, second, "already", "already aligned to within " + A3dGeom.AlignedMm + "mm - nothing moved", mode, movedMm);

            double? limit = A3dSettings.MaxMoveFt(settings);
            if (limit != null && plan.Distance > limit.Value)
                return NewRow(first, second, "refused",
                    "would move " + movedMm.ToString("0") + "mm, more than the " + FtToMm(limit.Value).ToString("0") + "mm limit in Settings", mode, movedMm);
            bool inGroup;
            try { inGroup = Key(second.GroupId) > 0; } catch (Exception) { inGroup = false; }
            if (inGroup) return NewRow(first, second, "refused", "it is inside a model group - edit the group to move it", mode, movedMm);
            string holder;
            if (!Borrow(doc, second.Id, out holder)) return NewRow(first, second, "refused", "cannot be moved: " + holder, mode, movedMm);

            int joinedBefore = ConnectedCount(second);
            var move = new XYZ(plan.MoveX, plan.MoveY, plan.MoveZ);
            int detachedNow = 0;
            Func<bool, Action> job = detach => () =>
            {
                bool wasPinned = second.Pinned;
                if (wasPinned) second.Pinned = false;
                if (detach) detachedNow = DisconnectAll(second);
                ElementTransformUtils.MoveElement(doc, second.Id, move);
                if (wasPinned) second.Pinned = true;
            };
            Failures failures;
            bool committed = RunTransaction(doc, job(false), out failures);
            int detached = 0;
            if (!committed)
            {
                string revitSays = failures.Errors.Count > 0 ? string.Join("; ", failures.Errors) : "Revit refused the move";
                log.Write("  refused with its connections: " + revitSays);
                if (A3dSettings.Get(settings, "on_refusal") == "detach" && joinedBefore > 0)
                {
                    committed = RunTransaction(doc, job(true), out failures);
                    detached = detachedNow;
                    if (!committed)
                        return NewRow(first, second, "failed",
                            "Revit refused the move even detached: " + (failures.Errors.Count > 0 ? string.Join("; ", failures.Errors) : revitSays), mode, movedMm);
                }
                else
                {
                    return NewRow(first, second, "failed", revitSays + " - left where it was", mode, movedMm);
                }
            }

            // A void API call is not evidence: read both centrelines back.
            A3dAxis firstAfter = AxisOf(doc.GetElement(first.Id)), secondAfter = AxisOf(doc.GetElement(second.Id));
            A3dPlan check = firstAfter != null && secondAfter != null ? A3dGeom.PlanAlignment(firstAfter, secondAfter) : null;
            bool datumMoved = A3dGeom.MovedBy(firstAxis, firstAfter) > A3dGeom.AlignedFt;
            if (check == null || !check.Ok || !A3dGeom.IsAligned(check.Distance))
            {
                double residual = check != null && check.Ok ? FtToMm(check.Distance) : -1.0;
                log.Write("  read back " + residual.ToString("0.00") + "mm out, datum moved: " + datumMoved);
                if (datumMoved)
                    return NewRow(first, second, "warn",
                        "moved, but the first element was dragged with it through their connection and they now read " + residual.ToString("0.0") +
                        "mm apart - check the joint", mode, movedMm);
                return NewRow(first, second, "failed", "Revit accepted the move but it reads back " + residual.ToString("0.0") + "mm out", mode, movedMm);
            }

            var notes = new List<string>();
            string kind = "ok";
            if (detached > 0)
            {
                kind = "warn";
                notes.Add("Revit would not move it with its connections, so " + detached + " connection(s) were released - reconnect by hand");
            }
            else
            {
                int joinedAfter = ConnectedCount(second);
                if (joinedAfter < joinedBefore)
                {
                    kind = "warn";
                    notes.Add((joinedBefore - joinedAfter) + " connection(s) came apart in the move");
                }
            }
            if (datumMoved)
            {
                kind = "warn";
                notes.Add("the first element moved too - the two are connected, check the joint");
            }
            if (notes.Count == 0) notes.Add("aligned and read back");
            log.Write("  " + kind + ": " + string.Join("; ", notes));
            return NewRow(first, second, kind, string.Join("; ", notes), mode, movedMm);
        }

        public static bool ShouldShow(List<A3dRow> rows, string mode)
        {
            if (rows.Count == 0 || mode == "never") return false;
            if (mode == "always") return true;
            return rows.Any(r => NeedsLook.Contains(r.Kind));
        }

        // ---------------------------------------------------------------- the command --

        private static string SecondPrompt(string kind)
        {
            return kind == A3dGeom.Vertical
                ? "3D Align: click the element to centre on this upright (Esc to choose a different first element)"
                : "3D Align: click the upright to move onto this run's centreline (Esc to choose a different first element)";
        }

        /// <summary>Picks until Escape. Returns the rows of what was done, for the results window.</summary>
        public static List<A3dRow> Run(UIApplication uiapp, Dictionary<string, string> settings, A3dLog log)
        {
            var rows = new List<A3dRow>();
            UIDocument uidoc = uiapp.ActiveUIDocument;
            if (uidoc == null) return rows;
            Document doc = uidoc.Document;
            log.Write("revit: " + uiapp.Application.VersionName + " " + uiapp.Application.VersionBuild + " | document: " + doc.Title);
            log.Write("settings: " + string.Join("; ", settings.OrderBy(k => k.Key).Select(k => k.Key + "=" + k.Value)));
            bool keepRunning = A3dSettings.IsOn(settings, "keep_running");
            Element first = Preselected(uidoc, log);
            if (first != null) log.Write("Using the selection as the first element: " + Describe(first));
            try
            {
                while (true)
                {
                    if (first == null)
                    {
                        Highlight(uidoc, null);
                        first = Pick(uidoc, "3D Align: click the first element - the one to align to (Esc to finish)", null, null);
                        if (first == null) break;
                    }
                    string kind = A3dGeom.Classify(AxisOf(first));
                    Highlight(uidoc, first);
                    string need = kind == A3dGeom.Horizontal ? A3dGeom.Vertical : null;
                    Element second = Pick(uidoc, SecondPrompt(kind), Key(first.Id), need);
                    if (second == null)
                    {
                        first = null;
                        if (keepRunning) continue;
                        break;
                    }
                    rows.Add(Align(doc, first, second, settings, log));
                    first = null;
                    if (!keepRunning) break;
                }
            }
            finally
            {
                Highlight(uidoc, null);
                log.Write("done: " + rows.Count + " alignment(s)");
                log.Flush();
            }
            return rows;
        }
    }
}
