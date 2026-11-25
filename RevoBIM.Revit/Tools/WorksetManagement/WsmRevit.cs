using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.WorksetManagement;

namespace RevoBIM.Tools.WorksetManagement
{
    /// <summary>A refusal to report to the user as it stands, not as a fault.</summary>
    public class WsmToolStop : Exception
    {
        public WsmToolStop(string message) : base(message) { }
    }

    /// <summary>Deletes warnings so a bulk write never stops on a dialog; errors are left for Revit.</summary>
    public class WsmWarningSwallower : IFailuresPreprocessor
    {
        public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
        {
            try { accessor.DeleteAllWarnings(); } catch (Exception) { }
            return FailureProcessingResult.Continue;
        }
    }

    public class WorksetRecord
    {
        public WorksetId WsId;
        public int Iid;
        public string Name = "", Owner = "";
        public bool Editable, IsOpen = true, Visible = true, Active, Mine;
        public int Count;
        public List<KeyValuePair<string, int>> Categories = new List<KeyValuePair<string, int>>();
    }

    public class ManageResult
    {
        public List<string> Created = new List<string>();
        public List<Tuple<string, string>> Renamed = new List<Tuple<string, string>>();
        public List<Tuple<string, string, int>> Deleted = new List<Tuple<string, string, int>>(), Merged = new List<Tuple<string, string, int>>();
        public List<Tuple<string, string>> Refused = new List<Tuple<string, string>>();
        public int CheckedOut;
        public string Error = "";
    }

    public class AssignMove
    {
        public int WsIid; public string WsName; public List<ElementId> Ids = new List<ElementId>();
    }

    public class AssignResult
    {
        public int Moved, Already, Owned, NotBorrowed, Refused;
        public List<string> Lines = new List<string>();
        public Dictionary<string, int> Owners = new Dictionary<string, int>();
        public string Error = "";
    }

    public class ViewShowResult
    {
        public ElementId ViewId; public bool Made; public Dictionary<string, int> Counts; public string Name;
    }

    public class IsolateResult
    {
        public ElementId ViewId; public int Count; public Dictionary<string, int> Per; public bool Isolated;
    }

    public class ScopeRecord
    {
        public ElementId ElementId;
        public long Eid;
        public string Name = "", Workset = "";
        public List<string> Views = new List<string>(), Datums = new List<string>();
        public List<ElementId> Users = new List<ElementId>();
    }

    public class ScopeResult
    {
        public List<string> Deleted = new List<string>();
        public List<Tuple<string, string>> Renamed = new List<Tuple<string, string>>(), Refused = new List<Tuple<string, string>>();
        public string Error = "";
    }

    public class ParamInfo
    {
        public string Key, Label, Kind;
    }

    public class AssignPreview
    {
        public List<WsmRules.PlanEntry> Plan = new List<WsmRules.PlanEntry>();
        public List<AssignMove> Moves = new List<AssignMove>();
        public int Total;
        public List<string> Problems = new List<string>();
        public List<string> Lines = new List<string>();
    }

    /// <summary>Everything that reads or writes Revit. Port of wsm_revit.py.</summary>
    public static class WsmRevit
    {
        private static string Txt(object v) { return WsmCore.Txt(v); }

        // ================================================================ ids

        public static long EidValue(ElementId id)
        {
            if (id == null) return 0;
            try { return id.Value; } catch (Exception) { return 0; }
        }

        public static int WsidValue(WorksetId id)
        {
            if (id == null) return -1;
            try { return id.IntegerValue; } catch (Exception) { return -1; }
        }

        // ================================================================ theme

        /// <summary>'dark' / 'light' from Revit's canvas, or null.</summary>
        public static string CanvasTheme(Document document)
        {
            try { return RevoBIM.Helpers.RevitCompat.CanvasTheme() == UITheme.Dark ? "dark" : "light"; } catch (Exception) { }
            try { return UIThemeManager.CurrentTheme == UITheme.Dark ? "dark" : "light"; } catch (Exception) { }
            try
            {
                Autodesk.Revit.DB.Color c = document.Application.BackgroundColor;
                double luminance = 0.299 * c.Red + 0.587 * c.Green + 0.114 * c.Blue;
                return luminance < 128 ? "dark" : "light";
            }
            catch (Exception) { return null; }
        }

        // ================================================================ reading

        public static string UserName(Document document)
        {
            try { return Txt(document.Application.Username); } catch (Exception) { return ""; }
        }

        public static bool IsWorkshared(Document document)
        {
            try { return document.IsWorkshared; } catch (Exception) { return false; }
        }

        public static int ActiveWorksetIid(Document document)
        {
            try { return WsidValue(document.GetWorksetTable().GetActiveWorksetId()); } catch (Exception) { return -1; }
        }

        private static WorksetRecord MakeRecord(Workset workset, int active, string user)
        {
            var r = new WorksetRecord { WsId = workset.Id, Iid = WsidValue(workset.Id), Name = Txt(workset.Name) };
            try { r.Editable = workset.IsEditable; } catch (Exception) { }
            try { r.Owner = Txt(workset.Owner); } catch (Exception) { }
            try { r.IsOpen = workset.IsOpen; } catch (Exception) { }
            try { r.Visible = workset.IsVisibleByDefault; } catch (Exception) { }
            r.Active = r.Iid == active;
            r.Mine = r.Owner.Length > 0 && string.Equals(r.Owner, user, StringComparison.OrdinalIgnoreCase);
            return r;
        }

        /// <summary>Every user workset, sorted naturally by name.</summary>
        public static List<WorksetRecord> ReadWorksets(Document document)
        {
            var records = new List<WorksetRecord>();
            if (document == null || !IsWorkshared(document)) return records;
            int active = ActiveWorksetIid(document);
            string user = UserName(document);
            try
            {
                foreach (Workset workset in new FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset))
                    records.Add(MakeRecord(workset, active, user));
            }
            catch (Exception) { return records; }
            return WsmCore.StableSort(records, (a, b) => WsmCore.NaturalCompare(a.Name, b.Name), false);
        }

        private static long? BuiltinCategoryInt(string name)
        {
            BuiltInCategory bic;
            if (!Enum.TryParse(name, out bic)) return null;
            return EidValue(new ElementId(bic));
        }

        private static string ParamText(Parameter param)
        {
            if (param == null) return "";
            try { if (param.StorageType == StorageType.String) return Txt(param.AsString()).Trim(); } catch (Exception) { }
            try { return Txt(param.AsValueString()).Trim(); } catch (Exception) { return ""; }
        }

        /// <summary>Service Type as the model spells it, instance first, then type (cached per type).</summary>
        public static string ServiceTypeOf(Element element, Document document, Dictionary<long, string> cache)
        {
            foreach (string name in WsmCore.ServiceParamNames)
            {
                string text;
                try { text = ParamText(element.LookupParameter(name)); } catch (Exception) { text = ""; }
                if (text.Length > 0) return text;
            }
            ElementId typeId = null; long typeInt = 0;
            try { typeId = element.GetTypeId(); typeInt = EidValue(typeId); } catch (Exception) { }
            string cached;
            if (cache.TryGetValue(typeInt, out cached)) return cached;
            Element typeElement = null;
            try { typeElement = document.GetElement(typeId); } catch (Exception) { }
            string found = "";
            if (typeElement != null)
            {
                foreach (string name in WsmCore.ServiceParamNames)
                {
                    try { found = ParamText(typeElement.LookupParameter(name)); } catch (Exception) { found = ""; }
                    if (found.Length > 0) break;
                }
            }
            if (found.Length == 0)
            {
                foreach (Element holder in new[] { element, typeElement })
                {
                    if (holder == null) continue;
                    try { found = ParamText(holder.get_Parameter(BuiltInParameter.RBS_CTC_SERVICE_TYPE)); } catch (Exception) { found = ""; }
                    if (found.Length > 0) break;
                }
            }
            cache[typeInt] = found.Length > 0 ? found : WsmCore.NoService;
            return cache[typeInt];
        }

        /// <summary>One pass over the model: element count per workset, the model categories in use, the elements behind each, and Service Type sub groups.</summary>
        public static WsmCore.ModelScan ScanModel(Document document, bool hideEmpty = true, bool subgroupServices = true)
        {
            var scan = new WsmCore.ModelScan();
            if (document == null) { scan.Error = "No document is open."; return scan; }
            var datumInts = new HashSet<long>();
            foreach (string name in WsmCore.DatumBics) { long? v = BuiltinCategoryInt(name); if (v.HasValue) datumInts.Add(v.Value); }
            var subgroupInts = new List<long>();
            if (subgroupServices)
                foreach (string name in WsmCore.SubgroupBics) { long? v = BuiltinCategoryInt(name); if (v.HasValue) subgroupInts.Add(v.Value); }

            List<Element> elements;
            try { elements = new FilteredElementCollector(document).WhereElementIsNotElementType().ToList(); }
            catch (Exception err) { scan.Error = "Could not read the model: " + err.Message; return scan; }

            var names = new Dictionary<long, string>();
            var byCat = new Dictionary<long, List<ElementId>>();
            var bySvc = new Dictionary<Tuple<long, string>, List<ElementId>>();
            var cache = new Dictionary<long, string>();
            foreach (Element element in elements)
            {
                int wsInt;
                try { wsInt = WsidValue(element.WorksetId); } catch (Exception) { wsInt = -1; }
                Category category = null;
                try { category = element.Category; } catch (Exception) { }
                if (wsInt >= 0)
                {
                    int n; scan.WorksetCounts.TryGetValue(wsInt, out n); scan.WorksetCounts[wsInt] = n + 1;
                    string label = WsmCore.NoCategory;
                    if (category != null)
                    {
                        try { label = Txt(category.Name).Length > 0 ? Txt(category.Name) : WsmCore.NoCategory; } catch (Exception) { label = WsmCore.NoCategory; }
                        if (label != WsmCore.NoCategory && !scan.CategoryIds.ContainsKey(label)) scan.CategoryIds[label] = category.Id;
                    }
                    Dictionary<string, int> per;
                    if (!scan.WorksetCategories.TryGetValue(wsInt, out per)) scan.WorksetCategories[wsInt] = per = new Dictionary<string, int>();
                    int c; per.TryGetValue(label, out c); per[label] = c + 1;
                }
                try { if (element.ViewSpecific) continue; } catch (Exception) { }
                if (category == null) continue;
                long catInt = EidValue(category.Id);
                if (catInt == 0) continue;
                if (!datumInts.Contains(catInt))
                {
                    try { if (category.CategoryType != CategoryType.Model) continue; } catch (Exception) { continue; }
                }
                if (!names.ContainsKey(catInt)) { names[catInt] = Txt(category.Name); byCat[catInt] = new List<ElementId>(); }
                byCat[catInt].Add(element.Id);
                scan.Total++;
                if (subgroupInts.Contains(catInt))
                {
                    var key = Tuple.Create(catInt, ServiceTypeOf(element, document, cache));
                    List<ElementId> list;
                    if (!bySvc.TryGetValue(key, out list)) bySvc[key] = list = new List<ElementId>();
                    list.Add(element.Id);
                }
            }
            foreach (var pair in names)
            {
                long catInt = pair.Key;
                var ids = byCat[catInt];
                if (hideEmpty && ids.Count == 0) continue;
                string key = "cat:" + catInt;
                var entry = new WsmCore.CategoryEntry(key, pair.Value, ids.Count);
                entry.ElementIds = ids.Cast<object>().ToList();
                scan.Add(entry);
                if (subgroupInts.Contains(catInt))
                {
                    foreach (var svc in bySvc)
                    {
                        if (svc.Key.Item1 != catInt) continue;
                        var child = new WsmCore.CategoryEntry("svc:" + catInt + ":" + svc.Key.Item2, svc.Key.Item2, svc.Value.Count, key);
                        child.ElementIds = svc.Value.Cast<object>().ToList();
                        scan.Add(child);
                    }
                }
            }
            scan.Finish();
            return scan;
        }

        public static List<WorksetRecord> ReadModel(Document document, Dictionary<string, string> settings, out WsmCore.ModelScan scan)
        {
            List<WorksetRecord> records = ReadWorksets(document);
            string hide, sub;
            settings.TryGetValue("hide_empty_categories", out hide);
            settings.TryGetValue("subgroup_service_type", out sub);
            scan = ScanModel(document, WsmCore.AsBool(hide, true), WsmCore.AsBool(sub, true));
            foreach (WorksetRecord record in records)
            {
                int n; scan.WorksetCounts.TryGetValue(record.Iid, out n);
                record.Count = n;
                Dictionary<string, int> per;
                record.Categories = WsmCore.CategoryBreakdown(scan.WorksetCategories.TryGetValue(record.Iid, out per) ? per : new Dictionary<string, int>());
            }
            return records;
        }

        // ================================================================ transactions

        private static Transaction MakeTransaction(Document document, string name)
        {
            var transaction = new Transaction(document, name);
            try
            {
                FailureHandlingOptions options = transaction.GetFailureHandlingOptions();
                options.SetFailuresPreprocessor(new WsmWarningSwallower());
                options.SetClearAfterRollback(true);
                transaction.SetFailureHandlingOptions(options);
            }
            catch (Exception) { }
            return transaction;
        }

        private static bool Committed(TransactionStatus status) { return status == TransactionStatus.Committed; }

        // ================================================================ checking out

        /// <summary>Make worksets editable, outside any transaction. Returns the workset ints editable afterwards - read back, never assumed.</summary>
        public static HashSet<int> CheckoutWorksets(Document document, IEnumerable<WorksetId> wsIds, WsmCore.Log log)
        {
            var wanted = wsIds.Where(w => w != null).ToList();
            var editable = new HashSet<int>();
            if (wanted.Count == 0 || !IsWorkshared(document)) return editable;
            try { WorksharingUtils.CheckoutWorksets(document, wanted); }
            catch (Exception err) { log.Add("CheckoutWorksets refused: {0}", err.Message); }
            WorksetTable table = document.GetWorksetTable();
            foreach (WorksetId id in wanted)
            {
                try { if (table.GetWorkset(id).IsEditable) editable.Add(WsidValue(id)); } catch (Exception) { }
            }
            log.Add("Checked out {0} of {1} worksets", editable.Count, wanted.Count);
            return editable;
        }

        /// <summary>Borrow elements, outside any transaction. Returns the element ints the user now holds.</summary>
        public static HashSet<long> CheckoutElements(Document document, IList<ElementId> elementIds, WsmCore.Log log)
        {
            var held = new HashSet<long>();
            if (elementIds.Count == 0 || !IsWorkshared(document))
            {
                foreach (ElementId id in elementIds) held.Add(EidValue(id));
                return held;
            }
            try
            {
                foreach (ElementId id in WorksharingUtils.CheckoutElements(document, elementIds.ToList())) held.Add(EidValue(id));
            }
            catch (Exception err) { log.Add("CheckoutElements refused: {0}", err.Message); }
            log.Add("Borrowed {0} of {1} elements", held.Count, elementIds.Count);
            return held;
        }

        public static string OwnerOf(Document document, ElementId id, out string status)
        {
            status = "unknown";
            try { status = WorksharingUtils.GetCheckoutStatus(document, id).ToString(); } catch (Exception) { return ""; }
            if (status != "OwnedByOtherUser") return "";
            try { return Txt(WorksharingUtils.GetWorksharingTooltipInfo(document, id).Owner); } catch (Exception) { return ""; }
        }

        // ================================================================ manage worksets

        private static Dictionary<int, WorksetRecord> RecordsByIid(Document document)
        {
            var map = new Dictionary<int, WorksetRecord>();
            foreach (WorksetRecord r in ReadWorksets(document)) map[r.Iid] = r;
            return map;
        }

        /// <summary>
        /// Creates and renames in one transaction, each delete in its own, all inside one group: one undo step, and one
        /// refused delete does not lose the rest. Worksets are checked out first, outside any transaction.
        /// </summary>
        public static ManageResult ApplyManage(Document document, WsmCore.Plan plan, bool autoEditable, WsmCore.Log log)
        {
            var result = new ManageResult();
            Dictionary<int, WorksetRecord> before = RecordsByIid(document);
            log.Add("Plan: {0} create, {1} rename, {2} delete", plan.Creates.Count, plan.Renames.Count, plan.Deletes.Count);

            var touch = plan.Renames.Select(r => r.Iid).Concat(plan.Deletes.Select(d => d.Iid)).ToList();
            var needs = touch.Where(iid => before.ContainsKey(iid) && !before[iid].Editable).Select(iid => before[iid].WsId).ToList();
            if (needs.Count > 0 && autoEditable)
            {
                HashSet<int> editable = CheckoutWorksets(document, needs, log);
                result.CheckedOut = editable.Count;
                before = RecordsByIid(document);
            }

            Func<int, string, string, bool> blocked = (iid, verb, name) =>
            {
                WorksetRecord record;
                if (!before.TryGetValue(iid, out record)) { result.Refused.Add(Tuple.Create(name, "it is no longer in the model")); return true; }
                if (record.Editable) return false;
                string owner = record.Owner, reason;
                if (owner.Length > 0 && !string.Equals(owner, UserName(document), StringComparison.OrdinalIgnoreCase))
                    reason = owner + " has it - it could not be made editable";
                else if (!autoEditable) reason = "it is not editable - tick 'Make worksets editable automatically' or press Make editable";
                else reason = "Revit would not make it editable - synchronise and try again";
                result.Refused.Add(Tuple.Create(verb + " " + name, reason));
                return true;
            };

            var renames = plan.Renames.Where(i => !blocked(i.Iid, "Rename", i.Old)).ToList();
            var deletes = plan.Deletes.Where(i => !blocked(i.Iid, i.Merge ? "Merge" : "Delete", i.Name)).ToList();

            var group = new TransactionGroup(document, "RevoBIM - Workset changes");
            try { group.Start(); }
            catch (Exception err) { result.Error = "Could not start: " + err.Message; return result; }

            bool anyCommitted = false;
            try
            {
                if (plan.Creates.Count > 0 || renames.Count > 0)
                {
                    Transaction transaction = MakeTransaction(document, "RevoBIM - Create and rename worksets");
                    transaction.Start();
                    foreach (string name in plan.Creates)
                    {
                        try
                        {
                            if (WorksetTable.IsWorksetNameUnique(document, name)) Workset.Create(document, name);
                            else result.Refused.Add(Tuple.Create("Create " + name, "a workset of that name exists"));
                        }
                        catch (Exception err) { result.Refused.Add(Tuple.Create("Create " + name, err.Message)); }
                    }
                    foreach (WsmCore.RenameItem item in renames)
                    {
                        try { WorksetTable.RenameWorkset(document, before[item.Iid].WsId, item.New); }
                        catch (Exception err) { result.Refused.Add(Tuple.Create("Rename " + item.Old, err.Message)); }
                    }
                    TransactionStatus status = transaction.Commit();
                    log.Add("Create/rename transaction: {0}", status);
                    if (Committed(status)) anyCommitted = true;
                    else result.Refused.Add(Tuple.Create("Create and rename", "Revit rolled the transaction back"));
                }

                if (deletes.Count > 0)
                {
                    List<WorksetRecord> now = ReadWorksets(document);
                    var byName = new Dictionary<string, WorksetRecord>();
                    foreach (WorksetRecord r in now) byName[r.Name.Trim().ToLowerInvariant()] = r;
                    var byIid = now.ToDictionary(r => r.Iid);
                    int active = ActiveWorksetIid(document);
                    foreach (WsmCore.DeleteItem item in deletes)
                    {
                        WorksetRecord target = null, victim;
                        if (!item.TargetNew) byIid.TryGetValue(item.TargetIid, out target);
                        if (target == null) byName.TryGetValue(item.TargetName.Trim().ToLowerInvariant(), out target);
                        byIid.TryGetValue(item.Iid, out victim);
                        string label = (item.Merge ? "Merge " : "Delete ") + item.Name;
                        if (victim == null) { result.Refused.Add(Tuple.Create(label, "it is no longer in the model")); continue; }
                        if (target == null)
                        {
                            result.Refused.Add(Tuple.Create(label, item.TargetName + ", which was to take its elements, does not exist"));
                            continue;
                        }
                        Transaction transaction = MakeTransaction(document, "RevoBIM - Delete workset");
                        transaction.Start();
                        try
                        {
                            if (active == victim.Iid)
                            {
                                try { document.GetWorksetTable().SetActiveWorksetId(target.WsId); active = target.Iid; }
                                catch (Exception err) { log.Add("Could not move the active workset: {0}", err.Message); }
                            }
                            var settings = new DeleteWorksetSettings(DeleteWorksetOption.MoveElementsToWorkset, target.WsId);
                            if (!WorksetTable.CanDeleteWorkset(document, victim.WsId, settings))
                            {
                                transaction.RollBack();
                                result.Refused.Add(Tuple.Create(label, "Revit will not delete it - an element on it is borrowed by another user, or it holds the last open view"));
                                continue;
                            }
                            WorksetTable.DeleteWorkset(document, victim.WsId, settings);
                            TransactionStatus status = transaction.Commit();
                            log.Add("{0}: {1}", label, status);
                            if (Committed(status)) anyCommitted = true;
                            else result.Refused.Add(Tuple.Create(label, "Revit rolled it back"));
                        }
                        catch (Exception err)
                        {
                            try { transaction.RollBack(); } catch (Exception) { }
                            result.Refused.Add(Tuple.Create(label, err.Message));
                        }
                    }
                }

                if (anyCommitted) group.Assimilate(); else group.RollBack();
            }
            catch (Exception err)
            {
                try { group.RollBack(); } catch (Exception) { }
                result.Error = err.Message;
                log.Add("Rolled back: {0}", err.Message);
                return result;
            }

            List<WorksetRecord> after = ReadWorksets(document);
            var afterIid = after.ToDictionary(r => r.Iid);
            var afterNames = new HashSet<string>(after.Select(r => r.Name.Trim().ToLowerInvariant()));
            foreach (string name in plan.Creates)
                if (afterNames.Contains(name.Trim().ToLowerInvariant())) result.Created.Add(name);
            foreach (WsmCore.RenameItem item in renames)
            {
                WorksetRecord record;
                if (afterIid.TryGetValue(item.Iid, out record) && record.Name == item.New) result.Renamed.Add(Tuple.Create(item.Old, item.New));
                else if (!result.Refused.Any(r => r.Item1.EndsWith(item.Old)))
                    result.Refused.Add(Tuple.Create("Rename " + item.Old, "Revit accepted it but the name did not change"));
            }
            foreach (WsmCore.DeleteItem item in deletes)
            {
                if (!afterIid.ContainsKey(item.Iid))
                    (item.Merge ? result.Merged : result.Deleted).Add(Tuple.Create(item.Name, item.TargetName, item.Count));
            }
            log.Add("Read back: {0} created, {1} renamed, {2} deleted, {3} merged", result.Created.Count, result.Renamed.Count, result.Deleted.Count, result.Merged.Count);
            return result;
        }

        /// <summary>The Make editable button: returns (made, refused [(name, reason)]).</summary>
        public static HashSet<int> MakeEditable(Document document, IEnumerable<int> iids, WsmCore.Log log, List<Tuple<string, string>> refused)
        {
            Dictionary<int, WorksetRecord> records = RecordsByIid(document);
            var wanted = iids.Where(records.ContainsKey).Select(i => records[i]).ToList();
            var needs = wanted.Where(r => !r.Editable).Select(r => r.WsId).ToList();
            HashSet<int> made = needs.Count > 0 ? CheckoutWorksets(document, needs, log) : new HashSet<int>();
            Dictionary<int, WorksetRecord> after = RecordsByIid(document);
            foreach (WorksetRecord record in wanted)
            {
                WorksetRecord now;
                if (after.TryGetValue(record.Iid, out now) && !now.Editable)
                    refused.Add(Tuple.Create(record.Name, now.Owner.Length > 0 ? now.Owner + " has it" : "Revit would not check it out - synchronise and try again"));
            }
            return made;
        }

        // ================================================================ assigner

        public const int MoveBatch = 200;

        /// <summary>Borrows what has to move, writes the workset parameter in one transaction, then reads every element back.</summary>
        public static AssignResult ApplyAssignments(Document document, List<AssignMove> plan, bool autoEditable, WsmCore.Log log)
        {
            var result = new AssignResult();
            Dictionary<int, WorksetRecord> records = RecordsByIid(document);
            var targets = new Dictionary<long, Tuple<ElementId, int, string>>();
            foreach (AssignMove move in plan)
            {
                if (!records.ContainsKey(move.WsIid)) { result.Lines.Add(move.WsName + ": no longer in the model"); continue; }
                foreach (ElementId id in move.Ids) targets[EidValue(id)] = Tuple.Create(id, move.WsIid, move.WsName);
            }
            var toMove = new List<Tuple<ElementId, int, string>>();
            foreach (var item in targets.Values)
            {
                Element element = document.GetElement(item.Item1);
                if (element == null) continue;
                if (WsidValue(element.WorksetId) == item.Item2) { result.Already++; continue; }
                toMove.Add(item);
            }
            log.Add("{0} elements to move, {1} already in place", toMove.Count, result.Already);
            if (toMove.Count == 0) return result;

            if (autoEditable && IsWorkshared(document))
            {
                HashSet<long> held = CheckoutElements(document, toMove.Select(m => m.Item1).ToList(), log);
                var keep = new List<Tuple<ElementId, int, string>>();
                foreach (var item in toMove)
                {
                    if (held.Contains(EidValue(item.Item1))) { keep.Add(item); continue; }
                    string status;
                    string owner = OwnerOf(document, item.Item1, out status);
                    if (owner.Length > 0)
                    {
                        result.Owned++;
                        int n; result.Owners.TryGetValue(owner, out n); result.Owners[owner] = n + 1;
                    }
                    else result.NotBorrowed++;
                }
                toMove = keep;
            }

            Func<List<Tuple<ElementId, int, string>>, bool> write = batch =>
            {
                Transaction transaction = MakeTransaction(document, "RevoBIM - Assign worksets");
                try
                {
                    transaction.Start();
                    foreach (var item in batch)
                    {
                        try
                        {
                            Parameter param = document.GetElement(item.Item1).get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
                            if (param == null || param.IsReadOnly) continue;
                            param.Set(item.Item2);
                        }
                        catch (Exception) { }
                    }
                    return Committed(transaction.Commit());
                }
                catch (Exception err)
                {
                    try { transaction.RollBack(); } catch (Exception) { }
                    log.Add("Batch of {0} refused: {1}", batch.Count, err.Message);
                    return false;
                }
            };

            var group = new TransactionGroup(document, "RevoBIM - Assign worksets");
            try
            {
                group.Start();
                if (write(toMove)) log.Add("Assigned in one transaction");
                else
                {
                    log.Add("Whole run refused - retrying in batches of {0}", MoveBatch);
                    for (int start = 0; start < toMove.Count; start += MoveBatch)
                    {
                        var batch = toMove.Skip(start).Take(MoveBatch).ToList();
                        if (write(batch)) continue;
                        foreach (var single in batch) write(new List<Tuple<ElementId, int, string>> { single });
                    }
                }
                group.Assimilate();
            }
            catch (Exception err)
            {
                try { group.RollBack(); } catch (Exception) { }
                result.Error = err.Message;
                return result;
            }

            var perWorkset = new Dictionary<string, int>();
            foreach (var item in toMove)
            {
                Element element = document.GetElement(item.Item1);
                if (element != null && WsidValue(element.WorksetId) == item.Item2)
                {
                    result.Moved++;
                    int n; perWorkset.TryGetValue(item.Item3, out n); perWorkset[item.Item3] = n + 1;
                }
            }
            result.Refused = toMove.Count - result.Moved;
            foreach (string name in WsmCore.SortedNatural(perWorkset.Keys)) result.Lines.Add(name + ": " + perWorkset[name] + " moved");
            return result;
        }

        // ================================================================ the 3D view

        public const string ViewName = "Workset Management";
        private static readonly BuiltInCategory[] LinkCategories = { BuiltInCategory.OST_RvtLinks, BuiltInCategory.OST_PointClouds };

        public static View3D FindView(Document document)
        {
            try
            {
                foreach (View3D view in new FilteredElementCollector(document).OfClass(typeof(View3D)))
                {
                    try { if (!view.IsTemplate && Txt(view.Name) == ViewName) return view; } catch (Exception) { }
                }
            }
            catch (Exception) { }
            return null;
        }

        public static View3D MakeView(Document document, WsmCore.Log log)
        {
            ViewFamilyType familyType = null;
            foreach (ViewFamilyType candidate in new FilteredElementCollector(document).OfClass(typeof(ViewFamilyType)))
            {
                try { if (candidate.ViewFamily == ViewFamily.ThreeDimensional) { familyType = candidate; break; } } catch (Exception) { }
            }
            if (familyType == null) throw new Exception("This model has no 3D view type to make the view from.");
            View3D view = View3D.CreateIsometric(document, familyType.Id);
            var taken = new HashSet<string>();
            foreach (View other in new FilteredElementCollector(document).OfClass(typeof(View)))
            {
                try { taken.Add(Txt(other.Name)); } catch (Exception) { }
            }
            string name = ViewName;
            int number = 2;
            while (taken.Contains(name)) { name = ViewName + " (" + number + ")"; number++; }
            view.Name = name;
            log.Add("Made 3D view {0}", name);
            return view;
        }

        public static ElementId SolidFillId(Document document)
        {
            foreach (FillPatternElement pattern in new FilteredElementCollector(document).OfClass(typeof(FillPatternElement)))
            {
                try { if (pattern.GetFillPattern().IsSolidFill) return pattern.Id; } catch (Exception) { }
            }
            return null;
        }

        /// <summary>Everything showing, links hidden. Inside a transaction. Each setting is tried on its own.</summary>
        public static void PrepareView(Document document, View3D view, List<WorksetRecord> records, WsmCore.Log log)
        {
            Action<string, Action> attempt = (label, func) =>
            {
                try { func(); } catch (Exception err) { log.Add("View setting {0} skipped: {1}", label, err.Message); }
            };
            attempt("template", () => view.ViewTemplateId = ElementId.InvalidElementId);
            attempt("section box", () => view.IsSectionBoxActive = false);
            attempt("discipline", () => view.Discipline = ViewDiscipline.Coordination);
            attempt("detail level", () => view.DetailLevel = ViewDetailLevel.Fine);
            attempt("display style", () => view.DisplayStyle = DisplayStyle.ShadingWithEdges);
            var linkIds = new HashSet<long>(LinkCategories.Select(c => EidValue(new ElementId(c))));
            int shown = 0;
            foreach (Category category in document.Settings.Categories)
            {
                try
                {
                    if (category.CategoryType != CategoryType.Model && !linkIds.Contains(EidValue(category.Id))) continue;
                    if (!view.CanCategoryBeHidden(category.Id)) continue;
                    bool hide = linkIds.Contains(EidValue(category.Id));
                    view.SetCategoryHidden(category.Id, hide);
                    if (!hide) shown++;
                }
                catch (Exception) { }
            }
            foreach (WorksetRecord record in records)
            {
                WorksetRecord r = record;
                attempt("workset " + r.Name, () => view.SetWorksetVisibility(r.WsId, WorksetVisibility.Visible));
            }
            var cad = new List<ElementId>();
            try
            {
                foreach (ImportInstance instance in new FilteredElementCollector(document).OfClass(typeof(ImportInstance)))
                {
                    try { if (instance.IsLinked && instance.CanBeHidden(view)) cad.Add(instance.Id); } catch (Exception) { }
                }
                if (cad.Count > 0) view.HideElements(cad);
            }
            catch (Exception err) { log.Add("CAD links not hidden: {0}", err.Message); }
            log.Add("View prepared: {0} categories on, {1} CAD links hidden", shown, cad.Count);
        }

        public static List<Element> WorksetElements(Document document, View view, WorksetId wsId)
        {
            return new FilteredElementCollector(document, view.Id).WherePasses(new ElementWorksetFilter(wsId))
                .WhereElementIsNotElementType().Where(e => e.Category != null).ToList();
        }

        public static OverrideGraphicSettings ColourSettings(int[] rgb, ElementId solidId)
        {
            var colour = new Autodesk.Revit.DB.Color((byte)rgb[0], (byte)rgb[1], (byte)rgb[2]);
            var settings = new OverrideGraphicSettings();
            try { settings.SetProjectionLineColor(colour); } catch (Exception) { }
            try { settings.SetCutLineColor(colour); } catch (Exception) { }
            try { settings.SetSurfaceForegroundPatternColor(colour); } catch (Exception) { }
            try { settings.SetCutForegroundPatternColor(colour); } catch (Exception) { }
            if (solidId != null)
            {
                try { settings.SetSurfaceForegroundPatternId(solidId); } catch (Exception) { }
                try { settings.SetCutForegroundPatternId(solidId); } catch (Exception) { }
                try { settings.SetSurfaceForegroundPatternVisible(true); } catch (Exception) { }
                try { settings.SetCutForegroundPatternVisible(true); } catch (Exception) { }
            }
            return settings;
        }

        /// <summary>Every element the view shows takes its workset's colour. Inside a transaction, after the prepare transaction committed.</summary>
        public static Dictionary<string, int> ColourView(Document document, View3D view, List<WorksetRecord> records, Dictionary<int, string> colours, WsmCore.Log log)
        {
            ElementId solid = SolidFillId(document);
            var counts = new Dictionary<string, int>();
            foreach (WorksetRecord record in records)
            {
                string hex;
                int[] rgb = colours.TryGetValue(record.Iid, out hex) ? WsmCore.HexRgb(hex) : null;
                if (rgb == null) continue;
                OverrideGraphicSettings settings = ColourSettings(rgb, solid);
                int done = 0;
                foreach (Element element in WorksetElements(document, view, record.WsId))
                {
                    try { view.SetElementOverrides(element.Id, settings); done++; } catch (Exception) { }
                }
                counts[record.Name] = done;
            }
            log.Add("Coloured {0} elements over {1} worksets", counts.Values.Sum(), counts.Count);
            return counts;
        }

        /// <summary>Clear a temporary isolate - and Reveal Hidden Elements, which otherwise leaves hidden elements showing through the next isolate.</summary>
        public static void ResetIsolate(View view)
        {
            view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate);
            try { view.DisableTemporaryViewMode(TemporaryViewMode.RevealHiddenElements); } catch (Exception) { }
        }

        public static bool IsIsolated(View view)
        {
            try { return view.IsTemporaryHideIsolateActive(); } catch (Exception) { return false; }
        }

        public static UIDocument ActiveUidoc(UIApplication uiapp, Document document)
        {
            try
            {
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc != null && uidoc.Document.Equals(document)) return uidoc;
            }
            catch (Exception) { }
            return null;
        }

        public static void ShowView(UIDocument uidoc, View view, bool direct)
        {
            try { if (uidoc.ActiveView != null && uidoc.ActiveView.Id.Equals(view.Id)) return; } catch (Exception) { }
            if (direct)
            {
                try { uidoc.ActiveView = view; return; } catch (Exception) { }
            }
            uidoc.RequestViewChange(view);
        }

        public static ViewShowResult ShowIn3d(UIApplication uiapp, Document document, Dictionary<int, string> colours, bool direct, WsmCore.Log log)
        {
            UIDocument uidoc = ActiveUidoc(uiapp, document);
            if (uidoc == null) throw new WsmToolStop("Switch to " + Txt(document.Title) + " first - the 3D view opens in the active model.");
            List<WorksetRecord> records = ReadWorksets(document);
            var group = new TransactionGroup(document, "RevoBIM - Workset Management 3D view");
            group.Start();
            View3D view;
            bool made;
            Dictionary<string, int> counts;
            try
            {
                Transaction transaction = MakeTransaction(document, "RevoBIM - Prepare the 3D view");
                transaction.Start();
                view = FindView(document);
                made = view == null;
                if (made) view = MakeView(document, log);
                if (IsIsolated(view)) ResetIsolate(view);
                PrepareView(document, view, records, log);
                if (!Committed(transaction.Commit())) throw new Exception("Revit would not set the view up.");
                transaction = MakeTransaction(document, "RevoBIM - Colour by workset");
                transaction.Start();
                counts = ColourView(document, view, records, colours, log);
                if (!Committed(transaction.Commit())) throw new Exception("Revit would not colour the view.");
                group.Assimilate();
            }
            catch (Exception)
            {
                try { group.RollBack(); } catch (Exception) { }
                throw;
            }
            ShowView(uidoc, view, direct);
            try { uidoc.RefreshActiveView(); } catch (Exception) { }
            return new ViewShowResult { ViewId = view.Id, Made = made, Counts = counts, Name = Txt(view.Name) };
        }

        public static IsolateResult IsolateWorksets(UIApplication uiapp, Document document, IEnumerable<int> iids, bool direct, WsmCore.Log log)
        {
            UIDocument uidoc = ActiveUidoc(uiapp, document);
            if (uidoc == null) throw new WsmToolStop("Switch to " + Txt(document.Title) + " first.");
            View3D view = FindView(document);
            if (view == null) throw new WsmToolStop("Press Show in 3D first - it makes the Workset Management view.");
            var wanted = new HashSet<int>(iids);
            var records = ReadWorksets(document).Where(r => wanted.Contains(r.Iid)).ToList();
            var group = new TransactionGroup(document, "RevoBIM - Isolate worksets");
            group.Start();
            var ids = new List<ElementId>();
            var per = new Dictionary<string, int>();
            try
            {
                Transaction transaction = MakeTransaction(document, "RevoBIM - Reset isolate");
                transaction.Start();
                ResetIsolate(view);
                if (!Committed(transaction.Commit())) throw new Exception("Revit would not reset the view.");
                foreach (WorksetRecord record in records)
                {
                    List<Element> found = WorksetElements(document, view, record.WsId);
                    per[record.Name] = found.Count;
                    foreach (Element element in found) ids.Add(element.Id);
                }
                if (ids.Count == 0)
                {
                    group.RollBack();
                    throw new WsmToolStop("Nothing on those worksets shows in the Workset Management view.");
                }
                transaction = MakeTransaction(document, "RevoBIM - Isolate worksets");
                transaction.Start();
                view.IsolateElementsTemporary(ids);
                if (!Committed(transaction.Commit())) throw new Exception("Revit would not isolate the elements.");
                group.Assimilate();
            }
            catch (WsmToolStop) { throw; }
            catch (Exception)
            {
                try { group.RollBack(); } catch (Exception) { }
                throw;
            }
            ShowView(uidoc, view, direct);
            try { uidoc.RefreshActiveView(); } catch (Exception) { }
            log.Add("Isolated {0} elements on {1} worksets", ids.Count, records.Count);
            return new IsolateResult { ViewId = view.Id, Count = ids.Count, Per = per, Isolated = IsIsolated(view) };
        }

        public static bool Unisolate(UIApplication uiapp, Document document, WsmCore.Log log)
        {
            View3D view = FindView(document);
            if (view == null || !IsIsolated(view)) return false;
            Transaction transaction = MakeTransaction(document, "RevoBIM - Un-isolate");
            transaction.Start();
            ResetIsolate(view);
            TransactionStatus status = transaction.Commit();
            try
            {
                UIDocument uidoc = ActiveUidoc(uiapp, document);
                if (uidoc != null) uidoc.RefreshActiveView();
            }
            catch (Exception) { }
            log.Add("Un-isolate: {0}", status);
            return Committed(status) && !IsIsolated(view);
        }

        // ================================================================ scope boxes

        public static string ElementName(Element element)
        {
            try { return Txt(element.Name); } catch (Exception) { }
            try { return Txt(element.get_Parameter(BuiltInParameter.VOLUME_OF_INTEREST_NAME).AsString()); } catch (Exception) { return ""; }
        }

        /// <summary>Every route to a name, then read back. Returns "" when the name took.</summary>
        public static string SetElementName(Element element, string name)
        {
            Exception last = null;
            var routes = new List<Action>();
            try
            {
                Parameter param = element.get_Parameter(BuiltInParameter.VOLUME_OF_INTEREST_NAME);
                if (param != null && !param.IsReadOnly) routes.Add(() => param.Set(name));
            }
            catch (Exception) { }
            routes.Add(() => element.Name = name);
            foreach (Action route in routes)
            {
                try { route(); } catch (Exception err) { last = err; continue; }
                if (ElementName(element) == name) return "";
            }
            return last != null ? last.Message : "Revit did not take the name";
        }

        private static long ScopeOf(Element element, BuiltInParameter bip)
        {
            try
            {
                Parameter param = element.get_Parameter(bip);
                return param == null ? 0 : EidValue(param.AsElementId());
            }
            catch (Exception) { return 0; }
        }

        /// <summary>Every scope box, with the views, levels, grids and reference planes using it.</summary>
        public static List<ScopeRecord> ReadScopeBoxes(Document document)
        {
            var records = new Dictionary<long, ScopeRecord>();
            foreach (Element element in new FilteredElementCollector(document).OfCategory(BuiltInCategory.OST_VolumeOfInterest).WhereElementIsNotElementType())
            {
                var record = new ScopeRecord { ElementId = element.Id, Eid = EidValue(element.Id), Name = ElementName(element) };
                try { record.Workset = Txt(document.GetWorksetTable().GetWorkset(element.WorksetId).Name); } catch (Exception) { }
                records[record.Eid] = record;
            }
            if (records.Count == 0) return new List<ScopeRecord>();
            foreach (View view in new FilteredElementCollector(document).OfClass(typeof(View)))
            {
                try { if (view.IsTemplate) continue; } catch (Exception) { continue; }
                ScopeRecord owner;
                if (records.TryGetValue(ScopeOf(view, BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP), out owner))
                {
                    owner.Views.Add(ElementName(view));
                    owner.Users.Add(view.Id);
                }
            }
            var labels = new[]
            {
                Tuple.Create(BuiltInCategory.OST_Levels, "Level"), Tuple.Create(BuiltInCategory.OST_Grids, "Grid"), Tuple.Create(BuiltInCategory.OST_CLines, "Ref plane"),
            };
            foreach (var item in labels)
            {
                IEnumerable<Element> datums;
                try { datums = new FilteredElementCollector(document).OfCategory(item.Item1).WhereElementIsNotElementType().ToList(); }
                catch (Exception) { continue; }
                foreach (Element datum in datums)
                {
                    ScopeRecord owner;
                    if (records.TryGetValue(ScopeOf(datum, BuiltInParameter.DATUM_VOLUME_OF_INTEREST), out owner))
                    {
                        owner.Datums.Add(item.Item2 + " " + ElementName(datum));
                        owner.Users.Add(datum.Id);
                    }
                }
            }
            return WsmCore.StableSort(records.Values, (a, b) => WsmCore.NaturalCompare(a.Name, b.Name), false);
        }

        /// <summary>Deletes then renames, so a name a delete frees can be taken in the same Apply. Borrowed first, outside any transaction.</summary>
        public static ScopeResult ApplyScope(Document document, WsmCore.ScopePlan plan, bool autoEditable, WsmCore.Log log)
        {
            var result = new ScopeResult();
            var byEid = ReadScopeBoxes(document).ToDictionary(r => r.Eid);
            var wanted = new List<ElementId>();
            foreach (var item in plan.Deletes)
            {
                ScopeRecord record;
                if (byEid.TryGetValue(item.Eid, out record)) { wanted.Add(record.ElementId); wanted.AddRange(record.Users); }
            }
            foreach (var item in plan.Renames)
            {
                ScopeRecord record;
                if (byEid.TryGetValue(item.Eid, out record)) wanted.Add(record.ElementId);
            }
            var blocked = new Dictionary<long, string>();
            if (autoEditable && IsWorkshared(document) && wanted.Count > 0)
            {
                HashSet<long> held = CheckoutElements(document, wanted, log);
                foreach (ElementId id in wanted)
                {
                    if (held.Contains(EidValue(id))) continue;
                    string status;
                    string owner = OwnerOf(document, id, out status);
                    blocked[EidValue(id)] = owner.Length > 0 ? owner : "Revit would not lend it";
                }
            }

            Func<long, bool, string> refusal = (eid, isDelete) =>
            {
                ScopeRecord record;
                if (!byEid.TryGetValue(eid, out record)) return "it is no longer in the model";
                var ids = new List<ElementId> { record.ElementId };
                if (isDelete) ids.AddRange(record.Users);
                foreach (ElementId id in ids)
                {
                    string who;
                    if (blocked.TryGetValue(EidValue(id), out who))
                        return EidValue(id) == record.Eid ? who + " has it" : who + " has a view or datum that uses it";
                }
                return "";
            };

            var group = new TransactionGroup(document, "RevoBIM - Scope box changes");
            group.Start();
            bool anyCommitted = false;
            try
            {
                foreach (var item in plan.Deletes)
                {
                    string label = "Delete " + item.Name;
                    string why = refusal(item.Eid, true);
                    if (why.Length > 0) { result.Refused.Add(Tuple.Create(label, why)); continue; }
                    Transaction transaction = MakeTransaction(document, "RevoBIM - Delete scope box");
                    transaction.Start();
                    try
                    {
                        document.Delete(byEid[item.Eid].ElementId);
                        if (Committed(transaction.Commit())) anyCommitted = true;
                        else result.Refused.Add(Tuple.Create(label, "Revit rolled it back"));
                    }
                    catch (Exception err)
                    {
                        try { transaction.RollBack(); } catch (Exception) { }
                        result.Refused.Add(Tuple.Create(label, err.Message));
                    }
                }
                var renames = new List<WsmCore.ScopeRenameItem>();
                foreach (var item in plan.Renames)
                {
                    string why = refusal(item.Eid, false);
                    if (why.Length > 0) result.Refused.Add(Tuple.Create("Rename " + item.Old, why)); else renames.Add(item);
                }
                if (renames.Count > 0)
                {
                    Transaction transaction = MakeTransaction(document, "RevoBIM - Rename scope boxes");
                    transaction.Start();
                    foreach (var item in renames)
                    {
                        Element element = document.GetElement(byEid[item.Eid].ElementId);
                        string problem = element != null ? SetElementName(element, item.New) : "it is no longer in the model";
                        if (problem.Length > 0) result.Refused.Add(Tuple.Create("Rename " + item.Old, problem));
                    }
                    if (Committed(transaction.Commit())) anyCommitted = true;
                    else result.Refused.Add(Tuple.Create("Rename", "Revit rolled the renames back"));
                }
                if (anyCommitted) group.Assimilate(); else group.RollBack();
            }
            catch (Exception err)
            {
                try { group.RollBack(); } catch (Exception) { }
                result.Error = err.Message;
                return result;
            }
            var after = ReadScopeBoxes(document).ToDictionary(r => r.Eid);
            foreach (var item in plan.Deletes)
                if (!after.ContainsKey(item.Eid) && byEid.ContainsKey(item.Eid)) result.Deleted.Add(item.Name);
            foreach (var item in plan.Renames)
            {
                ScopeRecord record;
                if (after.TryGetValue(item.Eid, out record) && record.Name == item.New) result.Renamed.Add(Tuple.Create(item.Old, item.New));
            }
            log.Add("Scope boxes read back: {0} deleted, {1} renamed", result.Deleted.Count, result.Renamed.Count);
            return result;
        }

        // ================================================================ routines

        /// <summary>'cat:-2008044' -> the category's ElementId, built from the BuiltInCategory member.</summary>
        public static ElementId CategoryElementId(string key)
        {
            string text = Txt(key);
            if (!text.StartsWith("cat:")) return null;
            long value;
            if (!long.TryParse(text.Substring(4), NumberStyles.Integer, CultureInfo.InvariantCulture, out value)) return null;
            try { return new ElementId((BuiltInCategory)(int)value); } catch (Exception) { return null; }
        }

        public static string CategoryKeyOf(Element element)
        {
            try { return "cat:" + EidValue(element.Category.Id); } catch (Exception) { return ""; }
        }

        private static List<ElementId> IdList(IEnumerable<ElementId> ids) { return ids.Where(i => i != null).ToList(); }

        /// <summary>Model elements (not types, not view specific) in these categories.</summary>
        public static List<Element> Candidates(Document document, IEnumerable<string> categoryKeys, int limit = 0)
        {
            var ids = categoryKeys.Select(CategoryElementId).Where(i => i != null).ToList();
            var output = new List<Element>();
            if (ids.Count == 0) return output;
            var collector = new FilteredElementCollector(document).WherePasses(new ElementMulticategoryFilter(ids)).WhereElementIsNotElementType();
            foreach (Element element in collector)
            {
                try { if (element.ViewSpecific) continue; } catch (Exception) { }
                output.Add(element);
                if (limit > 0 && output.Count >= limit) break;
            }
            return output;
        }

        /// <summary>A filterable parameter's ElementId -> (key, label). Built-in ones by BuiltInParameter name, shared by GUID, project by name.</summary>
        public static bool ParamKeyOf(Document document, ElementId paramId, out string key, out string label)
        {
            key = null; label = null;
            long value = EidValue(paramId);
            if (value < 0)
            {
                BuiltInParameter bip;
                try { bip = (BuiltInParameter)(int)value; } catch (Exception) { return false; }
                string name = bip.ToString();
                label = name;
                try { string l = Txt(LabelUtils.GetLabelFor(bip)); if (l.Length > 0) label = l; } catch (Exception) { }
                key = "bip:" + name;
                return true;
            }
            Element element = document.GetElement(paramId);
            if (element == null) return false;
            label = ElementName(element);
            var shared = element as SharedParameterElement;
            if (shared != null)
            {
                try { key = "guid:" + shared.GuidValue; return true; } catch (Exception) { }
            }
            key = "name:" + label;
            return true;
        }

        private static BuiltInParameter? Bip(string name)
        {
            BuiltInParameter bip;
            return Enum.TryParse(name, out bip) && Enum.IsDefined(typeof(BuiltInParameter), bip) ? (BuiltInParameter?)bip : null;
        }

        public static Parameter FindParam(Element element, string key, Dictionary<string, object> cache)
        {
            if (element == null || string.IsNullOrEmpty(key)) return null;
            try
            {
                if (key.StartsWith("bip:"))
                {
                    object cached;
                    if (!cache.TryGetValue(key, out cached)) { cached = Bip(key.Substring(4)); cache[key] = cached; }
                    var bip = (BuiltInParameter?)cached;
                    return bip.HasValue ? element.get_Parameter(bip.Value) : null;
                }
                if (key.StartsWith("guid:"))
                {
                    object cached;
                    if (!cache.TryGetValue(key, out cached)) { cached = new Guid(key.Substring(5)); cache[key] = cached; }
                    return element.get_Parameter((Guid)cached);
                }
                if (key.StartsWith("name:")) return element.LookupParameter(key.Substring(5));
            }
            catch (Exception) { }
            return null;
        }

        public static string KindOfStorage(StorageType storage)
        {
            switch (storage)
            {
                case StorageType.Double: return WsmRules.KindNumber;
                case StorageType.Integer: return WsmRules.KindInteger;
                case StorageType.ElementId: return WsmRules.KindId;
                default: return WsmRules.KindText;
            }
        }

        /// <summary>Reads ValueRecords, caching the lookups that repeat over thousands of elements.</summary>
        public class Reader
        {
            private readonly Document _doc;
            private readonly Dictionary<long, Element> _types = new Dictionary<long, Element>();
            private readonly Dictionary<string, object> _cache = new Dictionary<string, object>();
            private readonly Dictionary<string, ForgeTypeId> _units = new Dictionary<string, ForgeTypeId>();

            public Reader(Document document) { _doc = document; }

            public Element TypeOf(Element element)
            {
                ElementId typeId;
                try { typeId = element.GetTypeId(); } catch (Exception) { return null; }
                long key = EidValue(typeId);
                Element type;
                if (!_types.TryGetValue(key, out type))
                {
                    try { type = _doc.GetElement(typeId); } catch (Exception) { type = null; }
                    _types[key] = type;
                }
                return type;
            }

            public Parameter Param(Element element, string key)
            {
                Parameter param = FindParam(element, key, _cache);
                return param ?? FindParam(TypeOf(element), key, _cache);
            }

            /// <summary>A Double in the project's display units - mm for a length.</summary>
            private double DisplayNumber(Parameter param)
            {
                double value = param.AsDouble();
                ForgeTypeId spec = null; string specId = "";
                try { spec = param.Definition.GetDataType(); specId = Txt(spec.TypeId); } catch (Exception) { }
                ForgeTypeId unit = null;
                if (spec != null && !_units.TryGetValue(specId, out unit))
                {
                    try { unit = _doc.GetUnits().GetFormatOptions(spec).GetUnitTypeId(); } catch (Exception) { unit = null; }
                    _units[specId] = unit;
                }
                if (unit != null)
                {
                    try { return UnitUtils.ConvertFromInternalUnits(value, unit); } catch (Exception) { }
                }
                if (specId.ToLowerInvariant().Contains("length")) return value * 304.8;
                return value;
            }

            public WsmRules.ValueRecord Record(Element element, string key)
            {
                Parameter param = Param(element, key);
                if (param == null) return WsmRules.Missing;
                bool has;
                try { has = param.HasValue; } catch (Exception) { has = true; }
                StorageType storage = param.StorageType;
                string text = "";
                double? number = null;
                try { text = storage == StorageType.String ? Txt(param.AsString()) : Txt(param.AsValueString()); } catch (Exception) { text = ""; }
                try
                {
                    if (storage == StorageType.Double) number = DisplayNumber(param);
                    else if (storage == StorageType.Integer) number = param.AsInteger();
                    else if (storage == StorageType.ElementId)
                    {
                        ElementId target = param.AsElementId();
                        long v = EidValue(target);
                        if (v == 0 || v == -1) has = false;
                        else if (text.Length == 0)
                        {
                            Element targetElement = _doc.GetElement(target);
                            text = targetElement != null ? ElementName(targetElement) : "";
                        }
                    }
                }
                catch (Exception) { number = null; }
                if (storage == StorageType.String && text.Trim().Length == 0) has = false;
                return new WsmRules.ValueRecord(true, has, text, number);
            }
        }

        /// <summary>The parameters Revit's own Filters dialog offers for these categories: the filterable parameters they have in common.</summary>
        public static List<ParamInfo> FilterParameters(Document document, IList<string> categoryKeys, int sample = 60)
        {
            var ids = categoryKeys.Select(CategoryElementId).Where(i => i != null).ToList();
            var output = new List<ParamInfo>();
            if (ids.Count == 0) return output;
            ICollection<ElementId> common;
            try { common = ParameterFilterUtilities.GetFilterableParametersInCommon(document, ids); }
            catch (Exception) { return output; }
            var found = new Dictionary<string, ParamInfo>();
            foreach (ElementId paramId in common)
            {
                string key, label;
                if (!ParamKeyOf(document, paramId, out key, out label) || found.ContainsKey(key)) continue;
                var info = new ParamInfo { Key = key, Label = label, Kind = null };
                found[key] = info;
                if (key.StartsWith("bip:"))
                {
                    BuiltInParameter? bip = Bip(key.Substring(4));
                    if (bip.HasValue)
                    {
                        try { info.Kind = KindOfStorage(document.get_TypeOfStorage(bip.Value)); } catch (Exception) { }
                    }
                }
            }
            var reader = new Reader(document);
            var pending = new HashSet<string>(found.Where(p => p.Value.Kind == null).Select(p => p.Key));
            if (pending.Count > 0)
            {
                foreach (Element element in Candidates(document, categoryKeys, sample))
                {
                    if (pending.Count == 0) break;
                    foreach (string key in pending.ToList())
                    {
                        Parameter param = reader.Param(element, key);
                        if (param == null) continue;
                        try { found[key].Kind = KindOfStorage(param.StorageType); } catch (Exception) { found[key].Kind = WsmRules.KindText; }
                        pending.Remove(key);
                    }
                }
            }
            foreach (ParamInfo info in found.Values) if (info.Kind == null) info.Kind = WsmRules.KindText;
            return WsmCore.StableSort(found.Values, (a, b) => WsmCore.NaturalCompare(a.Label, b.Label), false);
        }

        /// <summary>The values a parameter takes on these categories, as Revit shows them, for the value suggestions under a rule.</summary>
        public static List<string> SampleValues(Document document, IList<string> categoryKeys, string paramKey, int scanLimit = 4000, int keep = 300)
        {
            var reader = new Reader(document);
            var values = new HashSet<string>();
            foreach (Element element in Candidates(document, categoryKeys, scanLimit))
            {
                WsmRules.ValueRecord record = reader.Record(element, paramKey);
                if (record.Has && record.Text.Trim().Length > 0)
                {
                    values.Add(record.Text.Trim());
                    if (values.Count >= keep) break;
                }
            }
            return WsmCore.SortedNatural(values);
        }

        /// <summary>Every model element the template catches -> {element int: ElementId}.</summary>
        public static Dictionary<long, ElementId> EvaluateTemplate(Document document, WsmRules.Template template, Reader reader = null)
        {
            reader = reader ?? new Reader(document);
            var keys = WsmRules.ParamsUsed(template);
            var caught = new Dictionary<long, ElementId>();
            foreach (Element element in Candidates(document, template.Categories))
            {
                string category = CategoryKeyOf(element);
                var values = new Dictionary<string, WsmRules.ValueRecord>();
                foreach (string key in keys) values[key] = reader.Record(element, key);
                if (WsmRules.Matches(template, values, category)) caught[EidValue(element.Id)] = element.Id;
            }
            return caught;
        }

        /// <summary>What Apply would do, worked out top to bottom: each workset's elements, minus anything a workset above already took, minus anything already on it.</summary>
        public static AssignPreview AssignPreviewFor(Document document, WsmCore.ModelScan scan, WsmRules.AssignState state, Dictionary<string, WsmRules.Template> library, WsmCore.Log log)
        {
            var records = new Dictionary<string, WorksetRecord>();
            foreach (WorksetRecord r in ReadWorksets(document)) records[r.Name] = r;
            var reader = new Reader(document);
            var rows = new List<KeyValuePair<string, List<long>>>();
            var ids = new Dictionary<long, ElementId>();
            var preview = new AssignPreview();
            foreach (string workset in state.Order)
            {
                string mode = state.Mode(workset);
                if (mode == WsmRules.ModeNone) continue;
                if (!records.ContainsKey(workset)) { preview.Problems.Add(workset + ": no longer in the model"); continue; }
                var caught = new Dictionary<long, ElementId>();
                if (mode == WsmRules.ModeCategories)
                {
                    foreach (object o in WsmCore.ElementIdsFor(state.Categories[workset], scan))
                    {
                        var id = (ElementId)o;
                        caught[EidValue(id)] = id;
                    }
                }
                else
                {
                    WsmRules.Template template;
                    if (!library.TryGetValue(state.Routines[workset], out template))
                    {
                        preview.Problems.Add(workset + ": routine '" + state.Routines[workset] + "' is missing");
                        continue;
                    }
                    var issues = WsmRules.TemplateProblems(template);
                    if (issues.Count > 0)
                    {
                        preview.Problems.Add(workset + ": routine '" + template.Name + "' - " + string.Join("; ", issues));
                        continue;
                    }
                    caught = EvaluateTemplate(document, template, reader);
                }
                foreach (var pair in caught) ids[pair.Key] = pair.Value;
                rows.Add(new KeyValuePair<string, List<long>>(workset, caught.Keys.OrderBy(k => k).ToList()));
            }
            var resolved = WsmRules.ResolveClaims(rows);
            var current = new Dictionary<long, int>();
            foreach (var item in resolved)
            {
                foreach (long element in item.Kept)
                {
                    Element e = document.GetElement(ids[element]);
                    if (e != null) current[element] = WsidValue(e.WorksetId);
                }
            }
            var targets = records.ToDictionary(p => p.Key, p => p.Value.Iid);
            int total;
            preview.Plan = WsmRules.PlanMoves(resolved, current, targets, out total);
            preview.Total = total;
            foreach (var entry in preview.Plan)
            {
                if (entry.ToMove.Count == 0) continue;
                var move = new AssignMove { WsIid = targets[entry.Workset], WsName = entry.Workset };
                foreach (long e in entry.ToMove) move.Ids.Add(ids[e]);
                preview.Moves.Add(move);
            }
            log.Add("Preview: {0} worksets, {1} elements to move", preview.Plan.Count, total);
            preview.Lines = WsmRules.PlanLines(preview.Plan);
            return preview;
        }

        /// <summary>Model elements of these categories on one workset - for 'Apply selected to workset' in a workset's drawer.</summary>
        public static List<ElementId> ElementsOnWorkset(Document document, int wsIid, IEnumerable<ElementId> categoryIds)
        {
            WorksetRecord record;
            var ids = IdList(categoryIds);
            if (!RecordsByIid(document).TryGetValue(wsIid, out record) || ids.Count == 0) return new List<ElementId>();
            return new FilteredElementCollector(document).WherePasses(new ElementWorksetFilter(record.WsId))
                .WherePasses(new ElementMulticategoryFilter(ids)).WhereElementIsNotElementType().Select(e => e.Id).ToList();
        }
    }
}
