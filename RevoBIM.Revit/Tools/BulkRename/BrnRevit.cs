using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.BulkRename
{
    /// <summary>One thing that was not done, and why. Row is null when it is about the whole job.</summary>
    public sealed class Failure
    {
        public readonly Row Row;
        public readonly string Reason;
        /// <summary>True when it came from the Parameter Push rather than a rename.</summary>
        public readonly bool Push;

        public Failure(Row row, string reason, bool push = false)
        {
            Row = row;
            Reason = reason;
            Push = push;
        }
    }

    /// <summary>One parameter of one sheet in the Parameter Push results.</summary>
    public sealed class PushLine
    {
        public string Number;
        public string Name;
        public string Param;
        public string Value;
        public string Status;
    }
    /// <summary>What a rename or a sheet-name write did.</summary>
    public sealed class BrnReport
    {
        public int Done;
        public int Written;
        public readonly List<PushLine> Lines = new List<PushLine>();
        public readonly List<Failure> Failed = new List<Failure>();
        public Dictionary<string, HashSet<string>> Taken;
    }

    /// <summary>
    /// Reading the selection, and the write. Every model change is in ApplyJob and WriteSheetNames.
    /// Port of brn_revit.py.
    /// </summary>
    public static class BrnRevit
    {
        private static readonly Dictionary<string, string> ViewLabels = new Dictionary<string, string>
        {
            { "FloorPlan", "Floor plan" }, { "CeilingPlan", "Ceiling plan" },
            { "EngineeringPlan", "Structural plan" }, { "AreaPlan", "Area plan" },
            { "Section", "Section" }, { "Detail", "Detail" }, { "Elevation", "Elevation" },
            { "ThreeD", "3D view" }, { "Walkthrough", "Walkthrough" },
            { "DraftingView", "Drafting view" }, { "Legend", "Legend" },
            { "Schedule", "Schedule" }, { "ColumnSchedule", "Schedule" },
            { "PanelSchedule", "Panel schedule" }, { "Rendering", "Rendering" },
            { "Report", "Report" }, { "CostReport", "Report" },
        };

        public static long IdValue(ElementId id)
        {
            return id == null ? 0 : id.Value;
        }

        public static string ReadName(Element element)
        {
            try
            {
                return element.Name ?? "";
            }
            catch (Exception)
            {
                return "";
            }
        }

        private static string TypeScope(Element element)
        {
            string family = "";
            try
            {
                ElementType type = element as ElementType;
                if (type != null) family = type.FamilyName ?? "";
            }
            catch (Exception)
            {
            }
            return "type:" + family;
        }

        private static string FamilyScope(Family family)
        {
            try
            {
                return "family:" + family.FamilyCategory.Name;
            }
            catch (Exception)
            {
                return "family:";
            }
        }

        /// <summary>A Row for anything the Project Browser lists and this tool can rename, else null.</summary>
        public static Row MakeRow(Element element)
        {
            if (element == null) return null;
            long key = IdValue(element.Id);
            var sheet = element as ViewSheet;
            if (sheet != null)
                return new Row(element.Id, key, "Sheet", ReadName(element), number: sheet.SheetNumber ?? "",
                               numberScope: "sheet:number");
            var view = element as View;
            if (view != null)
            {
                if (view.IsTemplate) return null;
                string viewType = view.ViewType.ToString();
                string label;
                if (!ViewLabels.TryGetValue(viewType, out label)) label = "View";
                return new Row(element.Id, key, label, ReadName(element), nameScope: "view:" + viewType);
            }
            var family = element as Family;
            if (family != null)
                return new Row(element.Id, key, "Family", ReadName(element), nameScope: FamilyScope(family));
            if (element is ElementType)
            {
                if (element is RevitLinkType || element is CADLinkType) return null;
                return new Row(element.Id, key, "Type", ReadName(element), nameScope: TypeScope(element));
            }
            return null;
        }

        /// <summary>The renamable rows in a selection, and how many selected things cannot be renamed here.</summary>
        public static List<Row> ReadSelection(Document doc, IEnumerable<ElementId> ids, out int leftOut)
        {
            var rows = new List<Row>();
            leftOut = 0;
            foreach (ElementId id in ids)
            {
                Row row = MakeRow(doc.GetElement(id));
                if (row == null) leftOut++;
                else rows.Add(row);
            }
            return BrnCore.SortRows(rows);
        }

        private static void Note(Dictionary<string, HashSet<string>> taken, string scope, string value)
        {
            HashSet<string> set;
            if (!taken.TryGetValue(scope, out set))
            {
                set = new HashSet<string>();
                taken[scope] = set;
            }
            set.Add(value);
        }

        /// <summary>{scope: names used by elements outside the batch}.</summary>
        public static Dictionary<string, HashSet<string>> ReadTaken(Document doc, IEnumerable<Row> rows)
        {
            var batch = new HashSet<long>(rows.Select(r => r.Key));
            var taken = new Dictionary<string, HashSet<string>>();
            bool views = false, types = false, families = false;
            foreach (Row row in rows)
            {
                string scope = row.ScopeOf(Field.Name) ?? "";
                views = views || row.Has(Field.Number) || scope.StartsWith("view:", StringComparison.Ordinal);
                types = types || scope.StartsWith("type:", StringComparison.Ordinal);
                families = families || scope.StartsWith("family:", StringComparison.Ordinal);
            }
            if (views)
            {
                using (var collector = new FilteredElementCollector(doc).OfClass(typeof(View)))
                {
                    foreach (Element element in collector)
                    {
                        if (batch.Contains(IdValue(element.Id))) continue;
                        var sheet = element as ViewSheet;
                        var view = element as View;
                        if (sheet != null) Note(taken, "sheet:number", sheet.SheetNumber ?? "");
                        else if (view != null) Note(taken, "view:" + view.ViewType, ReadName(element));
                    }
                }
            }
            if (types)
            {
                using (var collector = new FilteredElementCollector(doc).OfClass(typeof(ElementType)))
                {
                    foreach (Element element in collector)
                    {
                        if (!batch.Contains(IdValue(element.Id))) Note(taken, TypeScope(element), ReadName(element));
                    }
                }
            }
            if (families)
            {
                using (var collector = new FilteredElementCollector(doc).OfClass(typeof(Family)))
                {
                    foreach (Element element in collector)
                    {
                        var family = element as Family;
                        if (family != null && !batch.Contains(IdValue(element.Id)))
                            Note(taken, FamilyScope(family), ReadName(element));
                    }
                }
            }
            return taken;
        }

        public static string ReadValue(Document doc, Row row, Field field)
        {
            Element element = doc.GetElement(row.Id);
            if (element == null) return null;
            if (field == Field.Number)
            {
                var sheet = element as ViewSheet;
                return sheet == null ? null : (sheet.SheetNumber ?? "");
            }
            return ReadName(element);
        }

        /// <summary>Sets it and reads it back. A write that did not land raises.</summary>
        private static void WriteValue(Document doc, Row row, Field field, string value)
        {
            Element element = doc.GetElement(row.Id);
            if (field == Field.Number)
            {
                var sheet = (ViewSheet)element;
                sheet.SheetNumber = value;
                if ((sheet.SheetNumber ?? "") == value) return;
                throw new InvalidOperationException("Revit did not take the new text");
            }
            string why = null;
            try
            {
                element.Name = value;
            }
            catch (Exception err)
            {
                why = err.Message;
            }
            if (ReadName(element) == value) return;
            try
            {
                Parameter sheetName = element.get_Parameter(BuiltInParameter.SHEET_NAME);
                if (sheetName != null) sheetName.Set(value);
            }
            catch (Exception err)
            {
                why = why ?? err.Message;
            }
            if (ReadName(element) == value) return;
            throw new InvalidOperationException(string.IsNullOrEmpty(why) ? "Revit did not take the new text" : why);
        }

        private sealed class WarningSwallower : IFailuresPreprocessor
        {
            public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
            {
                foreach (FailureMessageAccessor message in accessor.GetFailureMessages())
                {
                    if (message.GetSeverity() == FailureSeverity.Warning) accessor.DeleteWarning(message);
                }
                return FailureProcessingResult.Continue;
            }
        }

        private static void QuietFailures(Transaction tx)
        {
            FailureHandlingOptions options = tx.GetFailureHandlingOptions();
            options.SetFailuresPreprocessor(new WarningSwallower());
            options.SetClearAfterRollback(true);
            tx.SetFailureHandlingOptions(options);
        }

        /// <summary>{row key: who holds it} for rows that could not be borrowed in a workshared model.</summary>
        private static Dictionary<long, string> Borrow(Document doc, IEnumerable<Row> rows)
        {
            var owners = new Dictionary<long, string>();
            if (!doc.IsWorkshared) return owners;
            List<Row> list = rows.ToList();
            var ids = new List<ElementId>(list.Select(r => r.Id));
            ICollection<ElementId> held = WorksharingUtils.CheckoutElements(doc, ids);
            var got = new HashSet<long>(held.Select(IdValue));
            foreach (Row row in list)
            {
                if (got.Contains(row.Key)) continue;
                string owner = null;
                try
                {
                    owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, row.Id).Owner;
                }
                catch (Exception)
                {
                }
                owners[row.Key] = string.IsNullOrEmpty(owner) ? "another user" : owner;
            }
            return owners;
        }

        /// <summary>Runs the action in its own sub-transaction. Returns null, or why Revit refused.</summary>
        private static string InSub(Document doc, Action action)
        {
            using (var sub = new SubTransaction(doc))
            {
                sub.Start();
                try
                {
                    action();
                    sub.Commit();
                    return null;
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
                    return string.IsNullOrEmpty(err.Message) ? "Revit refused it" : err.Message;
                }
            }
        }

        /// <summary>
        /// Names are read again here: a modeless window can be left open while the model moves on, so the
        /// preview is not what gets written.
        /// </summary>
        public static BrnReport ApplyJob(Document doc, IList<Row> rows, IDictionary<Field, Rules> rules, BrnLog log)
        {
            var report = new BrnReport();
            var live = new List<Row>();
            foreach (Row row in rows)
            {
                if (doc.GetElement(row.Id) == null)
                {
                    report.Failed.Add(new Failure(row, "No longer in the model"));
                    continue;
                }
                foreach (Field field in BrnCore.Fields)
                {
                    if (row.Has(field)) row.Values[field] = ReadValue(doc, row, field) ?? row.Values[field];
                }
                live.Add(row);
            }
            List<Item> items = BrnCore.Evaluate(live, rules, ReadTaken(doc, live));
            foreach (Item item in items)
            {
                if (item.State == ItemState.Clash || item.State == ItemState.Bad)
                    report.Failed.Add(new Failure(item.Row, item.Reason));
            }
            List<Item> work = BrnCore.Changes(items);
            if (work.Count == 0)
            {
                report.Taken = ReadTaken(doc, live);
                return report;
            }

            var seen = new Dictionary<long, Row>();
            foreach (Item item in work) seen[item.Row.Key] = item.Row;
            Dictionary<long, string> owners = Borrow(doc, seen.Values);
            foreach (Item item in work.Where(i => owners.ContainsKey(i.Row.Key)))
                report.Failed.Add(new Failure(item.Row, "Owned by " + owners[item.Row.Key]));
            work = work.Where(i => !owners.ContainsKey(i.Row.Key)).ToList();

            var pending = new List<Item>();
            using (var tx = new Transaction(doc, "Bulk Rename"))
            {
                QuietFailures(tx);
                tx.Start();
                try
                {
                    var parked = new List<Item>();
                    foreach (Item item in BrnCore.NeedsParking(work))
                    {
                        Item held = item;
                        string name = BrnCore.ParkPrefix + held.Row.Key;
                        string error = InSub(doc, () => WriteValue(doc, held.Row, held.Field, name));
                        if (error != null) log.Write("park refused " + held.Row.Key + ": " + error);
                        else parked.Add(held);
                    }
                    // Parked items land first: one Revit refuses can still go back to its old name,
                    // because nothing has moved onto it yet.
                    foreach (Item item in parked.Concat(work.Where(i => !parked.Contains(i))))
                    {
                        Item current = item;
                        string error = InSub(doc, () => WriteValue(doc, current.Row, current.Field, current.New));
                        if (error != null)
                        {
                            log.Write("refused " + current.Row.Key + ": " + error);
                            report.Failed.Add(new Failure(current.Row, error));
                            if (parked.Contains(current))
                                InSub(doc, () => WriteValue(doc, current.Row, current.Field, current.Old));
                        }
                        else
                        {
                            pending.Add(current);
                        }
                    }
                }
                catch (Exception)
                {
                    tx.RollBack();
                    throw;
                }
                TransactionStatus status = tx.Commit();
                if (status != TransactionStatus.Committed)
                {
                    report.Failed.Add(new Failure(null, "Revit rolled the rename back (" + status + ")"));
                    report.Taken = ReadTaken(doc, live);
                    return report;
                }
            }

            // Commit regenerates, so the count is what is really there afterwards.
            foreach (Item item in pending)
            {
                string actual = ReadValue(doc, item.Row, item.Field);
                if (actual == item.New) report.Done++;
                else report.Failed.Add(new Failure(item.Row, "Did not stay renamed"));
                item.Row.Values[item.Field] = actual ?? item.Old;
            }
            report.Taken = ReadTaken(doc, live);
            return report;
        }

        /// <summary>Names of the editable text parameters on the selected sheets (the first few).</summary>
        public static List<string> TextParameters(Document doc, IEnumerable<Row> rows, int sample = 40)
        {
            var names = new HashSet<string>();
            foreach (Row row in rows.Where(r => r.Has(Field.Number)).Take(sample))
            {
                Element sheet = doc.GetElement(row.Id);
                if (sheet == null) continue;
                foreach (Parameter param in sheet.Parameters)
                {
                    try
                    {
                        if (param.StorageType == StorageType.String && !param.IsReadOnly)
                            names.Add(param.Definition.Name);
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            return names.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        private static Parameter ParamFor(Element sheet, string paramName, out string problem)
        {
            Parameter param = sheet.LookupParameter(paramName);
            problem = null;
            if (param == null)
            {
                problem = "missing parameter";
                return null;
            }
            if (param.IsReadOnly)
            {
                problem = "read-only";
                return null;
            }
            if (param.StorageType != StorageType.String)
            {
                problem = "not a text parameter";
                return null;
            }
            return param;
        }

        private static PushLine MakeLine(Element sheet, string param, string value, string status)
        {
            var viewSheet = sheet as ViewSheet;
            return new PushLine
            {
                Number = viewSheet != null ? viewSheet.SheetNumber ?? "" : "",
                Name = ReadName(sheet),
                Param = param,
                Value = value,
                Status = status,
            };
        }

        /// <summary>
        /// Writes each part to its parameter. A parameter that is missing or read-only is reported on its
        /// own line and the others are still written.
        /// </summary>
        private static List<PushLine> WriteSheetRow(Document doc, Row row, IEnumerable<KeyValuePair<string, string>> pairs)
        {
            Element sheet = doc.GetElement(row.Id);
            var lines = new List<PushLine>();
            foreach (KeyValuePair<string, string> pair in pairs)
            {
                string problem;
                Parameter param = ParamFor(sheet, pair.Key, out problem);
                if (problem != null)
                {
                    lines.Add(MakeLine(sheet, pair.Key, pair.Value, problem));
                    continue;
                }
                string status;
                try
                {
                    param.Set(pair.Value);
                    status = (param.AsString() ?? "") == pair.Value ? "OK" : "did not take the value";
                }
                catch (Exception err)
                {
                    status = "error: " + err.Message;
                }
                lines.Add(MakeLine(sheet, pair.Key, pair.Value, status));
            }
            return lines;
        }

        private static bool NeedsWrite(Element sheet, IEnumerable<KeyValuePair<string, string>> pairs)
        {
            foreach (KeyValuePair<string, string> pair in pairs)
            {
                Parameter param = sheet.LookupParameter(pair.Key);
                if (param == null || (param.AsString() ?? "") != pair.Value) return true;
            }
            return false;
        }

        private sealed class PushWork
        {
            public Row Row;
            public List<KeyValuePair<string, string>> Pairs;
            public List<PushLine> Lines;
        }

        /// <summary>
        /// The Parameter Push: each sheet's name, as it stands in the model, is split and written to the
        /// target parameters. Sheets already right are not borrowed or touched. report.Lines gets one line
        /// per parameter, for the results window.
        /// </summary>
        public static void WriteSheetNames(Document doc, IEnumerable<Row> rows, IDictionary<string, string> settings,
                                           BrnReport report, BrnLog log)
        {
            var work = new List<PushWork>();
            foreach (Row row in rows)
            {
                if (!row.Has(Field.Number)) continue;
                Element sheet = doc.GetElement(row.Id);
                if (sheet == null)
                {
                    report.Failed.Add(new Failure(row, "No longer in the model", true));
                    continue;
                }
                List<KeyValuePair<string, string>> pairs = BrnCore.SheetWrites(ReadName(sheet), settings);
                if (NeedsWrite(sheet, pairs))
                {
                    work.Add(new PushWork { Row = row, Pairs = pairs });
                }
                else
                {
                    foreach (KeyValuePair<string, string> pair in pairs)
                        report.Lines.Add(MakeLine(sheet, pair.Key, pair.Value, "OK"));
                    report.Written++;
                }
            }
            if (work.Count == 0) return;
            Dictionary<long, string> owners = Borrow(doc, work.Select(w => w.Row));
            var done = new List<PushWork>();
            using (var tx = new Transaction(doc, "Write Sheet names"))
            {
                QuietFailures(tx);
                tx.Start();
                try
                {
                    foreach (PushWork entry in work)
                    {
                        Element sheet = doc.GetElement(entry.Row.Id);
                        if (owners.ContainsKey(entry.Row.Key))
                        {
                            string held = "Owned by " + owners[entry.Row.Key];
                            foreach (KeyValuePair<string, string> pair in entry.Pairs)
                                report.Lines.Add(MakeLine(sheet, pair.Key, pair.Value, held));
                            report.Failed.Add(new Failure(entry.Row, held, true));
                            continue;
                        }
                        PushWork current = entry;
                        string error = InSub(doc, () => current.Lines = WriteSheetRow(doc, current.Row, current.Pairs));
                        if (error != null)
                        {
                            log.Write("sheet " + entry.Row.Key + ": " + error);
                            foreach (KeyValuePair<string, string> pair in entry.Pairs)
                                report.Lines.Add(MakeLine(sheet, pair.Key, pair.Value, "error: " + error));
                            report.Failed.Add(new Failure(entry.Row, error, true));
                        }
                        else
                        {
                            done.Add(entry);
                        }
                    }
                }
                catch (Exception)
                {
                    tx.RollBack();
                    throw;
                }
                TransactionStatus status = tx.Commit();
                if (status != TransactionStatus.Committed)
                {
                    report.Failed.Add(new Failure(null, "Revit rolled the write back (" + status + ")", true));
                    return;
                }
            }
            foreach (PushWork entry in done)
            {
                Element sheet = doc.GetElement(entry.Row.Id);
                bool stayed = !NeedsWrite(sheet, entry.Pairs.Where(p => entry.Lines.Any(l => l.Param == p.Key && l.Status == "OK")));
                var problems = new List<string>();
                foreach (PushLine line in entry.Lines)
                {
                    if (line.Status == "OK" && !stayed) line.Status = "did not stay";
                    report.Lines.Add(line);
                    if (line.Status != "OK") problems.Add(line.Param + ": " + line.Status);
                }
                if (problems.Count == 0) report.Written++;
                else report.Failed.Add(new Failure(entry.Row, string.Join("; ", problems), true));
            }
        }
        /// <summary>The rename (when one is waiting) and the sheet-name write, as one undo step.</summary>
        public static BrnReport RenameAndWrite(Document doc, IList<Row> rows, IDictionary<Field, Rules> rules,
                                               IDictionary<string, string> settings, bool rename, BrnLog log)
        {
            using (var group = new TransactionGroup(doc, "Write Sheet names"))
            {
                group.Start();
                try
                {
                    BrnReport report = rename ? ApplyJob(doc, rows, rules, log) : new BrnReport();
                    WriteSheetNames(doc, rows, settings, report, log);
                    group.Assimilate();
                    return report;
                }
                catch (Exception)
                {
                    group.RollBack();
                    throw;
                }
            }
        }
    }

    /// <summary>
    /// Runs queued jobs inside Revit's API context. One queued job at a time: a Pending answer means an
    /// earlier request is still waiting, so only a refused job is ever dropped.
    /// </summary>
    public sealed class BrnRunner : IExternalEventHandler
    {
        private readonly BrnLog log;
        private readonly List<Action> jobs = new List<Action>();
        private ExternalEvent raiser;

        public BrnRunner(BrnLog log)
        {
            this.log = log;
        }

        public string GetName()
        {
            return "RevoBIM Bulk Rename";
        }

        public void Attach(ExternalEvent external)
        {
            raiser = external;
        }

        /// <summary>Queues the job. False when Revit refused to run it, after onRefused has been told why.</summary>
        public bool Submit(Action job, Action<string> onRefused)
        {
            if (jobs.Count > 0) return true;
            jobs.Add(job);
            string answer = raiser.Raise().ToString();
            log.Write("raise: " + answer);
            if (answer == "Accepted" || answer == "Pending") return true;
            jobs.Remove(job);
            onRefused(answer);
            return false;
        }

        public void Execute(UIApplication app)
        {
            while (jobs.Count > 0)
            {
                Action job = jobs[0];
                jobs.RemoveAt(0);
                try
                {
                    job();
                }
                catch (Exception err)
                {
                    log.Write("job failed: " + err.Message);
                }
            }
        }
    }
}
