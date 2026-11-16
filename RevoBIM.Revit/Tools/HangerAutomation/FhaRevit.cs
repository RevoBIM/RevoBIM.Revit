using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.HangerAutomation
{
    // =====================================================================================================
    // Hanger Automation - everything that touches the Revit API. Port of fha_revit.py.
    //
    // Three jobs, each run from the window through one ExternalEvent:
    //   JobRehost  re-host selected fabrication hangers on their nearest duct
    //   JobExtend  run selected hangers' rods up to the soffit above
    //   JobPlace   place, host, size, extend and dimension hangers on a duct run
    //
    // API used (checked against the 2024-2027 docs):
    //   FabricationPart.CreateHanger(doc, button, [condition,] hostId, Connector, distance, attach)
    //   FabricationHostedInfo.PlaceOnHost(hostId, Connector, distance)
    //   FabricationRodInfo  RodCount, GetRodEndPosition, GetRodLength (incl. structure
    //                       extension), SetRodLength (excl. it; returns bool; hanger must
    //                       not be auto-hosted), GetRodStructureExtension, AttachToStructure
    //   FabricationService  PaletteCount, GetButtonCount(p), GetButton(p, b)
    //   FabricationServiceButton  IsAHanger, ConditionCount, GetConditionLower/UpperValue,
    //                             IsUnrestrictedCondition
    // Hosting is always measured from a Connector object, never an index.
    //
    // Files: FhaRevit.cs (basics, transactions, worksets), FhaRevit.Graph.cs (connectors, run graph),
    // FhaRevit.Hangers.cs (buttons, comments, create / rehost / replace), FhaRevit.Rods.cs (Soffit, extend),
    // FhaRevit.Dims.cs (dimensions into views), FhaRevit.Jobs.cs (the three jobs).
    // =====================================================================================================
    public static partial class FhaRevit
    {
        public const double MM = FhaCore.MM;
        public const double RodTol = 0.02;          // ft, how close a rod top must be to the soffit
        public const double EndMargin = 0.1;        // ft, never host a hanger closer than this to a joint
        public const double TapReach = 2.5;         // ft, plan offset within which a tap counts as on the run

        // ================================================================ basics
        /// <summary>ElementId -> long on every Revit version (0 for null).</summary>
        public static long EidValue(ElementId eid)
        {
            if (eid == null) return 0;
            try { return eid.Value; }
            catch (Exception) { }
            return 0;
        }

        /// <summary>WorksetId -> int (WorksetId keeps IntegerValue on every release).</summary>
        public static int WsInt(WorksetId wsid)
        {
            try { return wsid.IntegerValue; }
            catch (Exception) { return 0; }
        }

        /// <summary>Element.Name, "" when it cannot be read.</summary>
        public static string ElName(Element el)
        {
            try { return el.Name; }
            catch (Exception) { return ""; }
        }

        /// <summary>BuiltInCategory by name (the Python getattr(DB.BuiltInCategory, name)); throws if the name does not exist in this Revit.</summary>
        public static BuiltInCategory Bic(string name)
        {
            return (BuiltInCategory)Enum.Parse(typeof(BuiltInCategory), name);
        }

        /// <summary>BuiltInParameter by name, or null when this Revit version has no such member (getattr(..., None)).</summary>
        public static BuiltInParameter? Bip(string name)
        {
            BuiltInParameter v;
            if (Enum.TryParse<BuiltInParameter>(name, out v) && Enum.IsDefined(typeof(BuiltInParameter), v)) return v;
            return null;
        }

        private static bool CatIs(Element el, string name)
        {
            try { return el.Category != null && EidValue(el.Category.Id) == (long)(int)Bic(name); }
            catch (Exception) { return false; }
        }

        public static bool IsFab(Element el) { return el is FabricationPart; }

        public static bool IsHanger(Element el)
        {
            FabricationPart fp = el as FabricationPart;
            if (fp == null) return false;
            try
            {
                if (fp.IsAHanger()) return true;
            }
            catch (Exception) { }
            return CatIs(el, "OST_FabricationHangers");
        }

        public static bool IsDuct(Element el)
        {
            return IsFab(el) && !IsHanger(el) && CatIs(el, "OST_FabricationDuctwork");
        }

        public static bool IsTap(Element el)
        {
            try { return ((FabricationPart)el).IsATap(); }
            catch (Exception) { return false; }
        }

        public static bool IsStraight(Element el)
        {
            try { return ((FabricationPart)el).IsAStraight(); }
            catch (Exception) { return false; }
        }

        public static V3 Pt(XYZ v) { return new V3(v.X, v.Y, v.Z); }

        public static XYZ ToXyz(V3 v) { return new XYZ(v.X, v.Y, v.Z); }

        /// <summary>The running job's debug log (set by the window around each job), so a
        /// transaction Revit throws away says why in the log. Python: CURRENT_LOG[0].</summary>
        public static FhaDebugLog CurrentLog;
        private static readonly List<string> Errors = new List<string>();

        /// <summary>Python _say: log to CurrentLog only.</summary>
        private static void Say(string text)
        {
            try
            {
                if (CurrentLog != null) CurrentLog.Add(text);
            }
            catch (Exception) { }
        }

        /// <summary>Delete warnings so Revit does not stop the run with a dialog. Errors
        /// are left to Revit (they undo the transaction) but noted for the log.</summary>
        public class WarningSwallower : IFailuresPreprocessor
        {
            public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
            {
                try
                {
                    foreach (FailureMessageAccessor f in accessor.GetFailureMessages().ToList())
                    {
                        if (f.GetSeverity() == FailureSeverity.Warning)
                            accessor.DeleteWarning(f);
                        else
                        {
                            try { Errors.Add(f.GetDescriptionText()); }
                            catch (Exception) { Errors.Add("(an error Revit gave no text for)"); }
                        }
                    }
                }
                catch (Exception) { }
                return FailureProcessingResult.Continue;
            }
        }

        public static Transaction StartTxn(Document doc, string name)
        {
            Errors.Clear();
            Transaction t = new Transaction(doc, name);
            t.Start();
            try
            {
                FailureHandlingOptions opts = t.GetFailureHandlingOptions();
                opts.SetFailuresPreprocessor(new WarningSwallower());
                t.SetFailureHandlingOptions(opts);
            }
            catch (Exception) { }
            return t;
        }

        public static bool Committed(Transaction t)
        {
            string status;
            try
            {
                status = t.Commit().ToString();
            }
            catch (Exception ex)
            {
                Say("   Revit refused to commit: " + ex.Message);
                try { t.RollBack(); }
                catch (Exception) { }
                return false;
            }
            if (status != "Committed")
                Say("   Revit undid \"" + TxnName(t) + "\" (" + status + ")" + (Errors.Count > 0 ? ": " + string.Join(" | ", Errors) : ""));
            Errors.Clear();
            return status == "Committed";
        }

        private static string TxnName(Transaction t)
        {
            try { return t.GetName(); }
            catch (Exception) { return "?"; }
        }

        public static void Rollback(Transaction t)
        {
            try { t.RollBack(); }
            catch (Exception) { }
        }

        private class FabFilter : ISelectionFilter
        {
            private readonly string _want;
            public FabFilter(string want) { _want = want; }
            public bool AllowElement(Element e) { return _want == "duct" ? IsDuct(e) : IsHanger(e); }
            public bool AllowReference(Reference r, XYZ p) { return false; }
        }

        /// <summary>The current selection filtered to ducts / hangers (want = "duct" or "hanger"), else ask for a pick.</summary>
        public static List<FabricationPart> GetSelection(UIDocument uidoc, string want, string prompt)
        {
            Document doc = uidoc.Document;
            Func<Element, bool> keep = want == "duct" ? (Func<Element, bool>)IsDuct : IsHanger;
            var els = new List<FabricationPart>();
            foreach (ElementId i in uidoc.Selection.GetElementIds())
            {
                Element e = doc.GetElement(i);
                if (e != null && keep(e)) els.Add((FabricationPart)e);
            }
            if (els.Count > 0) return els;
            try
            {
                IList<Reference> refs = uidoc.Selection.PickObjects(ObjectType.Element, new FabFilter(want), prompt);
                var o = new List<FabricationPart>();
                foreach (Reference r in refs)
                {
                    FabricationPart fp = doc.GetElement(r.ElementId) as FabricationPart;
                    if (fp != null) o.Add(fp);
                }
                return o;
            }
            catch (Exception)
            {
                return new List<FabricationPart>();   // Esc
            }
        }

        public static void Checkout(Document doc, IEnumerable<Element> elements, FhaDebugLog log)
        {
            try
            {
                List<Element> els = elements == null ? new List<Element>() : elements.ToList();
                if (doc.IsWorkshared && els.Count > 0)
                {
                    List<ElementId> ids = new List<ElementId>();
                    foreach (Element e in els) ids.Add(e.Id);
                    WorksharingUtils.CheckoutElements(doc, ids);
                }
            }
            catch (Exception ex)
            {
                log.Add("checkout: " + ex.Message);
            }
        }

        /// <summary>[(name, id)] of the model's user worksets, by name; empty if not workshared.</summary>
        public static List<KeyValuePair<string, int>> UserWorksets(Document doc)
        {
            var o = new List<KeyValuePair<string, int>>();
            try
            {
                if (!doc.IsWorkshared) return o;
                foreach (Workset ws in new FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
                {
                    try { o.Add(new KeyValuePair<string, int>(ws.Name, WsInt(ws.Id))); }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            return o.Select((x, i) => new { x, i }).OrderBy(z => z.x.Key.ToLowerInvariant(), StringComparer.Ordinal).ThenBy(z => z.i).Select(z => z.x).ToList();
        }

        /// <summary>The service a fabrication hanger hangs from, if Revit knows it.</summary>
        public static Element HangerHost(Document doc, Element h)
        {
            try
            {
                ElementId hid = ((FabricationPart)h).GetHostedInfo().HostId;
                return doc.GetElement(hid);
            }
            catch (Exception) { return null; }
        }

        /// <summary>Puts placed and edited hangers on the workset chosen on the tab
        /// (see FhaCore.WsOptions / WorksetTarget). One per job.</summary>
        public class Worksets
        {
            public Document Doc;
            public FhaDebugLog Log;
            public string Choice;
            public bool On;
            public int? Active, Named;
            public List<string> Problems = new List<string>();
            public int Moved;
            public bool LastMoved;

            public Worksets(Document doc, string choice, FhaDebugLog log)
            {
                Doc = doc; Log = log;
                Choice = string.IsNullOrEmpty(choice) ? FhaCore.WsLeave : choice;
                On = false;
                Active = Named = null;
                try { On = doc.IsWorkshared; }
                catch (Exception) { On = false; }
                if (!On)
                {
                    if (Choice != FhaCore.WsLeave)
                        log.Add("workset: the model is not workshared - nothing to set");
                    return;
                }
                try { Active = WsInt(doc.GetWorksetTable().GetActiveWorksetId()); }
                catch (Exception) { Active = null; }
                List<KeyValuePair<string, int>> names = UserWorksets(doc);
                if (Choice != FhaCore.WsLeave && Choice != FhaCore.WsService && Choice != FhaCore.WsActive)
                {
                    foreach (var nw in names)
                        if (nw.Key == Choice) Named = nw.Value;
                    if (Named == null)
                        Problems.Add("Workset \"" + Choice + "\" is not in this model - new hangers went on their "
                                     + "service's workset, edited ones were left where they were.");
                }
                string label = "\"" + Choice + "\"";
                foreach (var o in FhaCore.WsOptions)
                    if (o.Key == Choice) { label = o.Value; break; }
                log.Add("workset: " + label + (Named != null ? " (id " + Named.Value.ToString(CultureInfo.InvariantCulture) + ")" : ""));
            }

            /// <summary>Move el to its workset. service: what it serves (for 'same as the
            /// service'); like: the hanger it replaced (kept its workset under
            /// 'leave as is'). Caller holds the transaction. False if Revit refused.</summary>
            public bool Apply(Element el, Element service = null, bool isNew = true, Element like = null)
            {
                if (!On || el == null) return true;
                int? svc = null;
                if (like != null && Choice == FhaCore.WsLeave)
                    svc = WsInt(like.WorksetId);
                else if (service != null)
                    svc = WsInt(service.WorksetId);
                int? target = FhaCore.WorksetTarget(Choice, svc, Active, Named, isNew);
                LastMoved = false;
                if (target == null) return true;
                try
                {
                    if (WsInt(el.WorksetId) == target.Value) return true;
                    Parameter p = el.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
                    if (p == null || p.IsReadOnly) throw new Exception("workset is read only");
                    p.Set(target.Value);
                    LastMoved = true;
                    Moved++;
                    return true;
                }
                catch (Exception ex)
                {
                    string msg = "Could not move a hanger to its workset (is it owned by someone else?)";
                    if (!Problems.Contains(msg)) Problems.Add(msg);
                    Log.Add("   workset: element " + EidValue(el.Id).ToString(CultureInfo.InvariantCulture) + " not moved: " + ex.Message);
                    return false;
                }
            }
        }

        /// <summary>Newly created elements go on the workset of the element they serve.</summary>
        public static void MatchWorkset(Element newEl, Element likeEl)
        {
            try
            {
                Parameter p = newEl.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
                if (p != null && !p.IsReadOnly) p.Set(WsInt(likeEl.WorksetId));
            }
            catch (Exception) { }
        }

        /// <summary>fha_revit.new_result.</summary>
        public static JobResult NewResult(string title) { return new JobResult(title); }

        /// <summary>Python "{0:.0f}" / "{0:.2f}" for log lines.</summary>
        private static string Fmt(double v, int decimals)
        {
            return v.ToString("F" + decimals.ToString(CultureInfo.InvariantCulture), CultureInfo.InvariantCulture);
        }

        private static string Inv(long v) { return v.ToString(CultureInfo.InvariantCulture); }

        /// <summary>Python str() of an optional value in a log line.</summary>
        private static string NoneStr(object v)
        {
            return v == null ? "None" : Convert.ToString(v, CultureInfo.InvariantCulture);
        }
    }
}
