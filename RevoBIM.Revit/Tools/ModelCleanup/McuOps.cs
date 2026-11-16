using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using static RevoBIM.Tools.ModelCleanup.McuCore;

namespace RevoBIM.Tools.ModelCleanup
{
    /// <summary>
    /// Answers any Revit dialog raised during a run and records it. The same handler object is added and
    /// removed, so the unsubscribe always matches.
    /// </summary>
    public sealed class McuDialogSuppressor : IDisposable
    {
        private readonly UIApplication uiapp;
        private readonly EventHandler<DialogBoxShowingEventArgs> handler;
        private bool active;
        private bool hooked;
        public readonly List<string> Seen = new List<string>();

        public McuDialogSuppressor(UIApplication uiapp)
        {
            this.uiapp = uiapp;
            handler = OnDialog;
            active = true;
            try
            {
                uiapp.DialogBoxShowing += handler;
                hooked = true;
            }
            catch (Exception) { hooked = false; }
        }

        private void OnDialog(object sender, DialogBoxShowingEventArgs args)
        {
            if (!active) return;
            try { Seen.Add(args.DialogId ?? ""); }
            catch (Exception) { Seen.Add("(unnamed dialog)"); }
            try { args.OverrideResult(1); }
            catch (Exception) { }
        }

        public void Dispose()
        {
            active = false;
            if (hooked)
            {
                try { uiapp.DialogBoxShowing -= handler; }
                catch (Exception) { }
                hooked = false;
            }
            if (Seen.Count > 0) Log("dialogs answered: " + string.Join(", ", Seen));
        }
    }

    /// <summary>Warnings deleted; any error rolls the transaction back so the caller can replay one element at a time.</summary>
    public sealed class McuRollbackOnError : IFailuresPreprocessor
    {
        public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
        {
            bool hasError = false;
            try
            {
                foreach (FailureMessageAccessor message in accessor.GetFailureMessages())
                {
                    if (message.GetSeverity() == FailureSeverity.Warning) accessor.DeleteWarning(message);
                    else hasError = true;
                }
            }
            catch (Exception) { hasError = true; }
            return hasError ? FailureProcessingResult.ProceedWithRollBack : FailureProcessingResult.Continue;
        }
    }

    public sealed class McuSaveAsFailed : Exception
    {
        public McuSaveAsFailed(string message) : base(message) { }
    }

    public sealed class McuRunReport
    {
        public readonly List<string> Lines = new List<string>();
        public readonly Dictionary<string, int> Deleted = new Dictionary<string, int>();
        public readonly Dictionary<string, Dictionary<long, string>> Failures = new Dictionary<string, Dictionary<long, string>>();
        public readonly Dictionary<string, Dictionary<long, string>> Protected = new Dictionary<string, Dictionary<long, string>>();
        public bool Saved;

        public void Add(string text)
        {
            Lines.Add(text);
            Log(text);
        }

        /// <summary>
        /// Refusals are Revit saying no. Views the cascade guard held back are not failures - they stayed
        /// because something under them stays - and are counted apart so they do not read as a problem.
        /// </summary>
        public void Record(string key, string label, List<long> deleted, Dictionary<long, string> failures)
        {
            var (refused, kept) = SplitRefusals(failures);
            Deleted[key] = deleted.Count;
            if (refused.Count > 0) Failures[key] = refused;
            if (kept.Count > 0) Protected[key] = kept;
            string text = label + ": " + deleted.Count + " removed";
            if (kept.Count > 0) text += ", " + kept.Count + " kept because a view that stays depends on them";
            if (refused.Count > 0) text += ", " + refused.Count + " refused";
            Add(text);
            var listed = kept.Concat(refused).ToList();
            foreach (var pair in listed.Take(15)) Add("    id " + pair.Key + ": " + pair.Value);
            if (listed.Count > 15)
            {
                Add("    ... " + (listed.Count - 15) + " more in the log");
                foreach (var pair in listed.Skip(15)) Log("    id " + pair.Key + ": " + pair.Value);
            }
        }

        public int Total() { return Deleted.Values.Sum(); }
        public int RefusedCount() { return Failures.Values.Sum(f => f.Count); }
        public int KeptCount() { return Protected.Values.Sum(f => f.Count); }
    }

    /// <summary>
    /// Every write the tool makes. Progress is only ever reported between transactions: pumping the
    /// dispatcher inside an open transaction can leave it with nothing committed. Port of mcu_ops.py.
    /// </summary>
    public static class McuOps
    {
        private static ElementId Id(long value) { return McuModel.ToElementId(value); }

        // ============================================================
        // transactions
        // ============================================================

        private static Transaction StartTransaction(Document doc, string name)
        {
            var transaction = new Transaction(doc, name);
            FailureHandlingOptions options = transaction.GetFailureHandlingOptions();
            options.SetFailuresPreprocessor(new McuRollbackOnError());
            options.SetClearAfterRollback(true);
            transaction.SetFailureHandlingOptions(options);
            transaction.Start();
            return transaction;
        }

        private static bool Finish(Transaction transaction)
        {
            TransactionStatus status;
            try
            {
                status = transaction.Commit();
            }
            catch (Exception)
            {
                try
                {
                    if (transaction.HasStarted() && !transaction.HasEnded()) transaction.RollBack();
                }
                catch (Exception) { }
                return false;
            }
            return status == TransactionStatus.Committed;
        }

        private static void RollBack(Transaction transaction)
        {
            try { transaction.RollBack(); }
            catch (Exception) { }
        }

        // ============================================================
        // step 1 - sync or save
        // ============================================================

        public static (bool Ok, string Message) SyncCurrent(UIApplication uiapp, Document doc, string comment, bool relinquish, bool compact)
        {
            if (!doc.IsWorkshared)
            {
                if (string.IsNullOrEmpty(doc.PathName)) return (false, "This model has never been saved. Save it in Revit first.");
                using (new McuDialogSuppressor(uiapp)) doc.Save();
                return (true, "Saved " + McuModel.ModelTitle(doc));
            }
            var transact = new TransactWithCentralOptions();
            var options = new SynchronizeWithCentralOptions();
            options.SetRelinquishOptions(new RelinquishOptions(relinquish));
            options.Comment = comment ?? "";
            options.Compact = compact;
            try
            {
                options.SaveLocalBefore = true;
                options.SaveLocalAfter = true;
            }
            catch (Exception) { }
            int seen;
            using (var dialogs = new McuDialogSuppressor(uiapp))
            {
                doc.SynchronizeWithCentral(transact, options);
                seen = dialogs.Seen.Count;
            }
            string note = seen > 0 ? " (Revit asked " + seen + " question(s), answered automatically)" : "";
            return (true, "Synced with central" + note);
        }

        // ============================================================
        // step 2 - the send copy
        // ============================================================

        private static void SaveAs(Document doc, string target, bool compact)
        {
            var options = new SaveAsOptions { OverwriteExistingFile = true };
            try { options.Compact = compact; }
            catch (Exception) { }
            if (doc.IsWorkshared)
                options.SetWorksharingOptions(new WorksharingSaveAsOptions { SaveAsCentral = true });
            doc.SaveAs(target, options);
        }

        /// <summary>
        /// Open the central detached, save it to target, return the new (background) document. The live
        /// model is never modified. onStage(label, fraction) is called between the open and the save.
        /// </summary>
        public static Document OpenDetachedCopy(UIApplication uiapp, Document doc, string target,
            Dictionary<string, string> template, Action<string, double> onStage = null)
        {
            Action<string, double> stage = (label, fraction) =>
            {
                try { onStage?.Invoke(label, fraction); } catch (Exception) { }
            };
            var app = uiapp.Application;
            bool preserve = template.Get("detach_mode") != DetachDiscard;
            bool compact = AsBool(template.Get("compact"), true);
            Document copy;
            using (new McuDialogSuppressor(uiapp))
            {
                if (doc.IsWorkshared)
                {
                    ModelPath source = McuModel.CentralPath(doc);
                    if (source == null) throw new InvalidOperationException("The central model path could not be read.");
                    var options = new OpenOptions
                    {
                        DetachFromCentralOption = preserve ? DetachFromCentralOption.DetachAndPreserveWorksets
                                                           : DetachFromCentralOption.DetachAndDiscardWorksets,
                        Audit = AsBool(template.Get("audit"), false),
                    };
                    try { options.SetOpenWorksetsConfiguration(new WorksetConfiguration(WorksetConfigurationOption.OpenAllWorksets)); }
                    catch (Exception) { }
                    copy = app.OpenDocumentFile(source, options);
                }
                else
                {
                    stage("Copying the model file", 0.1);
                    File.Copy(doc.PathName, target, true);
                    ModelPath path = ModelPathUtils.ConvertUserVisiblePathToModelPath(target);
                    var options = new OpenOptions { Audit = AsBool(template.Get("audit"), false) };
                    stage("Opening the copied file", 0.4);
                    // the copied file already is the send copy - nothing to save yet
                    return app.OpenDocumentFile(path, options);
                }
                stage("Saving the detached copy to " + target, 0.7);
                try
                {
                    SaveAs(copy, target, compact);
                }
                catch (Exception error)
                {
                    // never leave an invisible detached document open for the rest of the session
                    try { copy.Close(false); } catch (Exception) { }
                    throw new McuSaveAsFailed(error.Message);
                }
            }
            return copy;
        }

        /// <summary>Fallback when the central cannot be opened a second time: the open model is saved as the send copy.</summary>
        public static Document SaveActiveAsCopy(UIApplication uiapp, Document doc, string target, Dictionary<string, string> template)
        {
            bool compact = AsBool(template.Get("compact"), true);
            using (new McuDialogSuppressor(uiapp)) SaveAs(doc, target, compact);
            return doc;
        }

        // ============================================================
        // step 3 - clean up
        // ============================================================

        private static Func<long, bool> StillThere(Document doc)
        {
            return value =>
            {
                try { return doc.GetElement(Id(value)) != null; }
                catch (Exception) { return false; }
            };
        }

        private static List<long> IdsOf(ICollection<ElementId> collection)
        {
            var output = new List<long>();
            try { foreach (ElementId id in collection) output.Add(McuModel.Eid(id)); }
            catch (Exception) { }
            return output;
        }

        private static Func<List<long>, bool> DeleteBatch(Document doc, string label, ICollection<long> guard)
        {
            return values =>
            {
                Transaction transaction = StartTransaction(doc, "Model Cleanup - " + label);
                ICollection<ElementId> removed;
                try
                {
                    removed = doc.Delete(values.Select(Id).ToList());
                }
                catch (Exception)
                {
                    RollBack(transaction);
                    return false;
                }
                if (CascadeHits(IdsOf(removed), guard).Count > 0)
                {
                    // something that stays went with this chunk: undo it, and the chunk is replayed one at a time
                    RollBack(transaction);
                    return false;
                }
                return Finish(transaction);
            };
        }

        private static Func<long, (bool, string)> DeleteOne(Document doc, string label, ICollection<long> guard)
        {
            return value =>
            {
                Transaction transaction = StartTransaction(doc, "Model Cleanup - " + label);
                ICollection<ElementId> removed;
                try
                {
                    removed = doc.Delete(Id(value));
                }
                catch (Exception error)
                {
                    RollBack(transaction);
                    return (false, error.Message);
                }
                var hits = CascadeHits(IdsOf(removed), guard);
                if (hits.Count > 0)
                {
                    RollBack(transaction);
                    // read after the rollback - until then they are deleted
                    var names = hits.Select(h => McuModel.ElementName(doc.GetElement(Id(h)))).ToList();
                    return (false, CascadeReason(names));
                }
                if (Finish(transaction)) return (true, "");
                return (false, "Revit rolled the delete back");
            };
        }

        public static (List<long> Deleted, Dictionary<long, string> Failures) DeleteIds(Document doc, IEnumerable<long> ids,
            string label, Action<double> progress = null, ICollection<long> guard = null)
        {
            return DeleteInChunks(ids, DeleteBatch(doc, label, guard), DeleteOne(doc, label, guard), StillThere(doc), 25, progress);
        }

        private static readonly string[] ViewStageKeys = { "delete_views_off_sheet", "delete_schedules_off_sheet", "delete_legends_off_sheet" };

        /// <summary>For the view stages: every view and sheet the plan keeps, so a delete that would cascade into one is undone.</summary>
        private static HashSet<long> GuardFor(Document doc, string key, Dictionary<string, string> template, long activeViewId)
        {
            if (!ViewStageKeys.Contains(key)) return null;
            var protectedIds = new HashSet<long> { McuModel.StartingViewId(doc), activeViewId };
            McuPlan plan = McuModel.ViewSheetPlan(doc, template, protectedIds);
            var every = plan.Views.Select(v => v.Id).Concat(plan.Sheets.Select(s => s.Id));
            return ViewGuard(every, McuModel.AllDoomed(plan), McuModel.OnSheetIds(doc));
        }

        /// <summary>A workshared copy: take every user workset before deleting, so a delete cannot quietly ask a question.</summary>
        public static string BorrowEverything(Document doc)
        {
            if (!doc.IsWorkshared) return "";
            try
            {
                var worksets = new List<WorksetId>();
                foreach (Workset workset in new FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset)) worksets.Add(workset.Id);
                WorksharingUtils.CheckoutWorksets(doc, worksets);
                return "";
            }
            catch (Exception error)
            {
                return error.Message;
            }
        }

        /// <summary>
        /// Before cleaning the open model: if the active view is not retained, open a retained sheet (or view)
        /// and close the old one. Any other open view that is going is closed too. Returns the id active afterwards.
        /// </summary>
        public static long MoveOffDoomedViews(UIDocument uidoc, Document doc, McuPlan plan, McuRunReport report, DebugReport debug)
        {
            View active = uidoc.ActiveView;
            long activeId = McuModel.Eid(active.Id);
            var doomed = McuModel.AllDoomed(plan);
            var sheets = plan.Sheets.Where(s => plan.RetainedSheets.Contains(s.Number) && !s.Placeholder).ToList();
            sheets.Sort((a, b) => NaturalCompare(a.Number, b.Number));
            var sheetIds = sheets.Select(s => s.Id).ToList();
            var viewIds = plan.Views.Where(v => plan.RetainedViews.Contains(ViewKey(v.Kind, v.Name)) && !v.Template)
                                    .Select(v => v.Id).ToList();
            long targetId = ViewToOpen(activeId, sheetIds, viewIds, doomed,
                                       McuModel.SwitchCandidates(plan, McuModel.StartingViewId(doc)));
            debug.Section("Active view");
            debug.Values(new List<(string, object)>
            {
                ("Active view", McuModel.ElementName(active) + " (" + activeId + ")"),
                ("Retained", sheetIds.Contains(activeId) || viewIds.Contains(activeId)),
                ("Going in this run", doomed.Contains(activeId)),
                ("Move to", targetId),
            });
            long oldId = activeId;
            if (targetId == 0)
            {
                if (doomed.Contains(activeId))
                    report.Add("The active view " + McuModel.ElementName(active) + " is going, but no view that stays " +
                               "could be opened instead, so it is kept.");
            }
            else
            {
                var target = doc.GetElement(Id(targetId)) as View;
                try { uidoc.ActiveView = target; }
                catch (Exception error) { debug.Line("Revit would not open " + McuModel.ElementName(target) + ": " + error.Message); }
                long newId = McuModel.Eid(uidoc.ActiveView.Id);
                if (newId != targetId)
                {
                    report.Add("Revit did not switch views, so " + McuModel.ElementName(active) + " is kept.");
                    debug.Line("Switch refused; active is still " + newId);
                }
                else
                {
                    report.Add("Opened " + McuModel.ElementName(target) + " and closed " + McuModel.ElementName(active) + ".");
                    activeId = newId;
                }
            }
            var closed = new List<string>();
            foreach (UIView uiView in uidoc.GetOpenUIViews().ToList())
            {
                long viewId = McuModel.Eid(uiView.ViewId);
                if (viewId == activeId) continue;
                if (viewId != oldId && !doomed.Contains(viewId)) continue;
                string name = McuModel.ElementName(doc.GetElement(uiView.ViewId));
                try
                {
                    uiView.Close();
                    closed.Add(name);
                }
                catch (Exception error) { debug.Line("Could not close " + name + ": " + error.Message); }
            }
            if (closed.Count > 0) debug.Values(new List<(string, object)> { ("Closed", string.Join(", ", closed)) });
            debug.Flush();
            return activeId;
        }

        // ============================================================
        // NWC export
        // ============================================================

        /// <summary>NavisworksExportOptions from the plain plan. Each property is set on its own, so one a release lacks is reported, not fatal.</summary>
        public static (NavisworksExportOptions Options, List<string> Applied, List<string> Refused) NwcOptions(
            Dictionary<string, object> plan, long viewId)
        {
            var options = new NavisworksExportOptions();
            var applied = new List<string>();
            var refused = new List<string>();
            var order = new List<string> { "ExportScope" };
            order.AddRange(plan.Keys.Where(k => k != "ExportScope").OrderBy(k => k, StringComparer.Ordinal));
            foreach (string prop in order)
            {
                try
                {
                    object value = plan[prop];
                    var info = typeof(NavisworksExportOptions).GetProperty(prop);
                    if (info == null) throw new MissingMemberException(prop);
                    if (info.PropertyType.IsEnum) value = Enum.Parse(info.PropertyType, (string)value);
                    info.SetValue(options, value, null);
                    applied.Add(prop);
                }
                catch (Exception error)
                {
                    refused.Add(prop + " (" + error.Message + ")");
                }
            }
            options.ViewId = Id(viewId);
            return (options, applied, refused);
        }

        /// <summary>
        /// Export every ticked 3D view to folder. Each file is checked on disk afterwards - a quiet export
        /// is not proof. progress(fraction, label).
        /// </summary>
        public static (List<(string View, string Path)> Written, List<(string View, string Reason)> Failures) ExportNwc(
            UIApplication uiapp, Document doc, Dictionary<string, string> template, string folder, string modelStem,
            Action<double, string> progress = null, DebugReport debug = null)
        {
            debug = debug ?? new DebugReport(false);
            var (views, primary) = McuNwc.Selection(template);
            var planned = McuNwc.FileNames(modelStem, views, primary);
            var (found, missing) = McuNwc.Resolve(McuModel.ThreeDViews(doc), planned);
            var plan = McuNwc.OptionsPlan(template);
            var written = new List<(string, string)>();
            var failures = missing.Select(v => (v, "no 3D view with this name in the model")).ToList();
            debug.Section("NWC export");
            var values = new List<(string, object)>
            {
                ("folder", folder), ("primary", primary), ("settings", template.Get("nwc_source")),
                ("exporter installed", McuModel.NwcAvailable()),
            };
            values.AddRange(plan.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => ("option " + p.Key, p.Value)));
            debug.Values(values);
            double total = Math.Max(1, found.Count);
            using (new McuDialogSuppressor(uiapp))
            {
                for (int index = 0; index < found.Count; index++)
                {
                    var (viewId, view, fileName) = found[index];
                    progress?.Invoke(index / total, "Exporting NWC " + (index + 1) + " of " + found.Count + ": " + view);
                    string path = Path.Combine(folder, fileName + ".nwc");
                    DateTime started = DateTime.Now;
                    try
                    {
                        var (options, _, refused) = NwcOptions(plan, viewId);
                        if (refused.Count > 0) debug.Line(view + ": options not set: " + string.Join("; ", refused));
                        doc.Export(folder, fileName, options);
                    }
                    catch (Exception error)
                    {
                        failures.Add((view, error.Message));
                        debug.Line(view + ": export failed: " + FormatException(error));
                        continue;
                    }
                    if (NwcWritten(path, started)) written.Add((view, path));
                    else failures.Add((view, "Revit reported no error, but no new file appeared"));
                }
            }
            progress?.Invoke(1.0, "NWC export done");
            debug.Table(new[] { "view", "file", "result" },
                        written.Select(w => new object[] { w.Item1, w.Item2, "written" })
                               .Concat(failures.Select(f => new object[] { f.Item1, "", f.Item2 })));
            debug.Flush();
            return (written, failures);
        }

        public static bool NwcWritten(string path, DateTime started)
        {
            try
            {
                var info = new FileInfo(path);
                return info.Exists && info.Length > 0 && info.LastWriteTime >= started.AddSeconds(-2);
            }
            catch (Exception) { return false; }
        }

        private static void DebugPlan(DebugReport debug, McuPlan plan, string title)
        {
            if (!debug.Enabled) return;
            debug.Section(title + " - sheets");
            debug.Table(new[] { "id", "number", "name", "retained", "decision" },
                plan.Sheets.Select(s => new object[]
                {
                    s.Id, s.Number, s.Name, plan.RetainedSheets.Contains(s.Number),
                    plan.Decisions.ContainsKey(s.Id) ? plan.Decisions[s.Id] : "",
                }));
            debug.Section(title + " - views");
            debug.Table(new[] { "id", "type", "name", "retain key", "retained", "placed on a kept sheet", "parent", "template", "decision" },
                plan.Views.Select(v => new object[]
                {
                    v.Id, v.Kind, v.Name, ViewKey(v.Kind, v.Name), plan.RetainedViews.Contains(ViewKey(v.Kind, v.Name)),
                    plan.Placed.Contains(v.Id), v.Parent, v.Template, plan.Decisions.ContainsKey(v.Id) ? plan.Decisions[v.Id] : "",
                }));
            debug.Section(title + " - retained entries not found in this model");
            var viewKeys = new HashSet<string>(plan.Views.Select(v => ViewKey(v.Kind, v.Name)));
            var numbers = new HashSet<string>(plan.Sheets.Select(s => s.Number));
            var missing = plan.RetainedViews.Where(k => !viewKeys.Contains(k)).OrderBy(k => k, StringComparer.Ordinal)
                .Concat(plan.RetainedSheets.Where(n => !numbers.Contains(n)).OrderBy(n => n, StringComparer.Ordinal)).ToList();
            debug.Line(missing.Count > 0 ? string.Join("\n", missing) : "(none)");
            debug.Flush();
        }

        /// <summary>
        /// The whole clean up on doc, then save. onStep(label, fraction) is called between transactions only,
        /// with the fraction of the whole run, weighted by how long each stage usually takes. uidoc is given
        /// only when doc is the open model, so the active view can be moved off.
        /// </summary>
        public static McuRunReport RunCleanup(UIApplication uiapp, Document doc, Dictionary<string, string> template,
            long activeViewId = 0, Action<string, double> onStep = null, bool save = true, UIDocument uidoc = null,
            DebugReport debug = null)
        {
            debug = debug ?? new DebugReport(false);
            var report = new McuRunReport();
            var keep = SplitWords(template.Get("keep_view_words"));
            var retainedViews = new HashSet<string>(SplitRetain(template.Get("retain_views")));
            var retainedSheets = new HashSet<string>(SplitRetain(template.Get("retain_sheets")));
            var excluded = SplitList(template.Get("purge_exclude"));
            int passes = AsInt(template.Get("purge_passes"), 4, 1, 10);
            var ops = EnabledOps(template);
            var plan = StagePlan(ops.Select(o => o.Key).Concat(save ? new[] { "save" } : new string[0]));

            debug.Section("Clean up run");
            debug.Values(McuModel.Environment(uiapp, doc));
            debug.Values(new List<(string, object)>
            {
                ("Runs on", uidoc != null ? "the open model" : "the saved copy"),
                ("Saves afterwards", save),
                ("Stages", string.Join(", ", ops.Select(o => o.Key))),
            });
            debug.Section("Template");
            debug.Values(template.Where(p => p.Key != "retain_views" && p.Key != "retain_sheets")
                                 .OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => (p.Key, (object)p.Value)));
            debug.Values(new List<(string, object)> { ("retained views", retainedViews.Count), ("retained sheets", retainedSheets.Count) });
            var warnings = RetentionWarnings(template);
            if (warnings.Count > 0) debug.Line("Retention warnings: " + RetentionMessage(template, warnings));
            debug.Flush();

            Action<string, string, double> step = (label, key, local) =>
            {
                try { onStep?.Invoke(label, PlanFraction(plan, key, local)); } catch (Exception) { }
            };

            using (var dialogs = new McuDialogSuppressor(uiapp))
            {
                if (uidoc != null || debug.Enabled)
                {
                    step("Working out which views and sheets go", plan.Count > 0 ? plan[0].Key : "save", 0.0);
                    McuPlan before = McuModel.ViewSheetPlan(doc, template, new HashSet<long> { McuModel.StartingViewId(doc) });
                    DebugPlan(debug, before, "Before the run");
                    if (uidoc != null) activeViewId = MoveOffDoomedViews(uidoc, doc, before, report, debug);
                }

                // Taking every workset is only right where they will be given back: a run that saves (it syncs
                // and relinquishes), or a model that is its own central.
                if (save || SaveRoute(McuModel.Describe(doc)) == SaveSync)
                {
                    step("Taking every workset in the copy", plan.Count > 0 ? plan[0].Key : "save", 0.0);
                    string problem = BorrowEverything(doc);
                    if (problem.Length > 0)
                    {
                        report.Add("Could not take every workset: " + problem);
                        debug.Line("Borrowing worksets failed: " + problem);
                    }
                }
                else
                {
                    debug.Line("Worksets not borrowed: this run does not save, and the model is a local of a live central.");
                }

                var group = new TransactionGroup(doc, "Model Cleanup");
                group.Start();
                try
                {
                    foreach (var op in ops)
                    {
                        string key = op.Key, label = op.Label;
                        if (key == "export_nwc") continue;
                        step(label + " - finding what to remove", key, 0.0);
                        Action<double> progress = fraction => step(label, key, fraction);
                        if (key == "purge")
                        {
                            RunPurge(doc, report, excluded, passes, label, progress, debug);
                            continue;
                        }
                        List<long> ids = IdsFor(doc, key, keep, activeViewId, retainedViews, retainedSheets, debug);
                        if (ids == null) continue;
                        var names = debug.Enabled ? Names(doc, ids) : new Dictionary<long, string>();
                        HashSet<long> guard = GuardFor(doc, key, template, activeViewId);
                        step(label + " (" + ids.Count + ")", key, 0.0);
                        var (deleted, failures) = DeleteIds(doc, ids, label, progress, guard);
                        report.Record(key, label, deleted, failures);
                        debug.Section("Stage: " + label);
                        var values = new List<(string, object)>
                            { ("asked", ids.Count), ("removed", deleted.Count), ("refused", failures.Count) };
                        values.AddRange(debug.TakePending());
                        debug.Values(values);
                        if (failures.Count > 0)
                        {
                            debug.Table(new[] { "id", "name", "reason" },
                                failures.Select(f => new object[] { f.Key, names.ContainsKey(f.Key) ? names[f.Key] : "", f.Value }));
                        }
                        debug.Flush();
                        step(label, key, 1.0);
                    }
                    debug.Line("");
                    debug.Line("Transaction group: assimilating");
                    group.Assimilate();
                }
                catch (Exception error)
                {
                    debug.Exception("the clean up stages", FormatException(error));
                    try { group.RollBack(); } catch (Exception) { }
                    throw;
                }

                if (debug.Enabled)
                {
                    McuPlan after = McuModel.ViewSheetPlan(doc, template, new HashSet<long> { McuModel.StartingViewId(doc) });
                    debug.Section("After the run");
                    List<long> sheetsLeft;
                    after.Doomed.TryGetValue("delete_sheets_not_retained", out sheetsLeft);
                    debug.Values(new List<(string, object)>
                    {
                        ("sheets left", after.Sheets.Count),
                        ("views left", after.Views.Count),
                        ("sheets that should have gone but remain", sheetsLeft == null ? 0 : sheetsLeft.Count),
                        ("views that should have gone but remain",
                            McuModel.ViewStages.Sum(s => after.Doomed.ContainsKey(s.Key) ? after.Doomed[s.Key].Count : 0)),
                    });
                    if (McuModel.AllDoomed(after).Count > 0) DebugPlan(debug, after, "Left after the run");
                    debug.Flush();
                }

                bool compact = AsBool(template.Get("compact"), true);
                if (!save)
                {
                    report.Add("Not saved and not synced: steps 1 and 2 were skipped. Check the model, then save it yourself.");
                }
                else if (doc.IsWorkshared)
                {
                    step("Syncing the copy to its own central (Revit is busy)", "save", 0.05);
                    var transact = new TransactWithCentralOptions();
                    var options = new SynchronizeWithCentralOptions();
                    options.SetRelinquishOptions(new RelinquishOptions(true));
                    options.Comment = "Model Cleanup - cleaned for issue";
                    options.Compact = compact;
                    try
                    {
                        doc.SynchronizeWithCentral(transact, options);
                        report.Add("Copy synced as its own central and relinquished.");
                    }
                    catch (Exception error)
                    {
                        // the clean up is already committed; a refused sync must not leave it unsaved
                        debug.Exception("final sync (falling back to a save)", FormatException(error));
                        doc.Save(new SaveOptions { Compact = compact });
                        report.Add("Revit would not sync the copy, so it was saved compact instead. Worksets were not relinquished.");
                    }
                    report.Saved = true;
                }
                else
                {
                    step("Saving the copy (Revit is busy)", "save", 0.05);
                    doc.Save(new SaveOptions { Compact = compact });
                    report.Saved = true;
                    report.Add("Copy saved.");
                }
                if (save) step("Saved", "save", 1.0);
                if (dialogs.Seen.Count > 0)
                {
                    report.Add("Revit asked " + dialogs.Seen.Count + " question(s) during the run; each was answered " +
                               "automatically and listed in the log.");
                    debug.Section("Revit dialogs answered");
                    debug.Line(string.Join("\n", dialogs.Seen));
                }
            }
            debug.Section("Run log");
            debug.Line(string.Join("\n", report.Lines));
            debug.Flush();
            return report;
        }

        private static Dictionary<long, string> Names(Document doc, IEnumerable<long> ids)
        {
            var output = new Dictionary<long, string>();
            foreach (long value in ids)
            {
                try { output[value] = McuModel.ElementName(doc.GetElement(Id(value))); }
                catch (Exception) { output[value] = ""; }
            }
            return output;
        }

        private static List<long> IdsFor(Document doc, string key, List<string> keep, long activeViewId,
            HashSet<string> retainedViews, HashSet<string> retainedSheets, DebugReport debug)
        {
            var protectedIds = new HashSet<long> { McuModel.StartingViewId(doc), activeViewId };
            switch (key)
            {
                case "delete_sheets_not_retained":
                {
                    var (ids, skipped) = SheetsToDelete(McuModel.ReadSheets(doc), retainedSheets, protectedIds);
                    if (skipped.Count > 0) Log("sheets kept: " + skipped.Count);
                    return ids;
                }
                case "remove_revit_links": return McuModel.RevitLinkIds(doc);
                case "remove_cad": return McuModel.CadIds(doc);
                case "remove_point_clouds": return McuModel.PointCloudIds(doc);
                case "delete_unplaced_images":
                {
                    // runs after the sheets and views, so images that were only placed on them are unused by now
                    var unused = McuModel.UnusedImageIds(doc);
                    var types = McuModel.ImageTypeIds(doc);
                    if (unused == null)
                    {
                        debug.Pending = new List<(string, object)> { ("skipped", "this release has no purge API") };
                        return new List<long>();
                    }
                    var ids = UnplacedImages(types, unused);
                    debug.Pending = new List<(string, object)>
                        { ("raster images in the model", types.Count), ("still placed or used", types.Count - ids.Count) };
                    return ids;
                }
                case "delete_views_off_sheet":
                case "delete_schedules_off_sheet":
                case "delete_legends_off_sheet":
                {
                    // read after the sheet stage: a deleted sheet took its viewports with it
                    var views = McuModel.ReadViews(doc);
                    var onSheet = McuModel.OnSheetIds(doc);
                    var rule = McuModel.ViewStages.First(s => s.Key == key).Rule;
                    var (ids, skipped) = rule(views, onSheet, keep, protectedIds, retainedViews, null);
                    if (skipped.Count > 0) Log(key + ": kept " + skipped.Count);
                    debug.Pending = new List<(string, object)>
                    {
                        ("protected ids", protectedIds.OrderBy(v => v).ToList()),
                        ("views on a kept sheet", onSheet.Count),
                        ("kept by the rules", skipped.Count),
                    };
                    return ids;
                }
                case "delete_unused_templates":
                {
                    var (templates, used, defaults) = McuModel.TemplateUsage(doc);
                    return UnusedIds(templates, used, defaults);
                }
                case "delete_unused_filters":
                {
                    var (filters, used) = McuModel.FilterUsage(doc);
                    return UnusedIds(filters, used);
                }
            }
            return null;
        }

        private static void RunPurge(Document doc, McuRunReport report, List<string> excluded, int passes, string label,
            Action<double> progress, DebugReport debug)
        {
            var passesSeen = new List<List<(long Id, string Group)>>();
            Func<List<(long, string)>> scan = () =>
            {
                var entries = McuModel.UnusedEntries(doc);
                passesSeen.Add(entries);
                return entries;
            };
            Func<List<long>, Action<double>, (List<long>, Dictionary<long, string>)> delete =
                (ids, sub) => DeleteIds(doc, ids, label + " (" + ids.Count + ")", sub);
            var (deleted, failures, ran) = PurgeLoop(scan, delete, excluded, passes, progress);
            report.Record("purge", label + " (" + ran + " pass" + (ran == 1 ? "" : "es") + ")", deleted, failures);
            if (!debug.Enabled) return;
            debug.Section("Purge");
            debug.Values(new List<(string, object)>
            {
                ("passes asked", passes), ("passes run", ran),
                ("excluded categories", excluded.Count > 0 ? string.Join(", ", excluded) : "(none)"),
                ("removed", deleted.Count), ("refused", failures.Count),
            });
            for (int index = 0; index < passesSeen.Count; index++)
            {
                var counts = GroupCounts(passesSeen[index], new List<(long, string)>());
                debug.Line("Pass " + (index + 1) + " found " + passesSeen[index].Count + " unused: " +
                           (counts.Count > 0 ? string.Join(", ", counts.Select(c => c.Group + " " + c.Unused)) : "nothing"));
            }
            if (failures.Count > 0)
                debug.Table(new[] { "id", "reason" }, failures.OrderBy(f => f.Key).Select(f => new object[] { f.Key, f.Value }));
            debug.Flush();
        }

        /// <summary>Save compact and let go of every workset, the way the route says.</summary>
        public static string SaveModel(UIApplication uiapp, Document doc, string route, string comment, DebugReport debug = null)
        {
            debug = debug ?? new DebugReport(false);
            string message;
            int answered;
            using (var dialogs = new McuDialogSuppressor(uiapp))
            {
                if (route == SaveSync)
                {
                    var transact = new TransactWithCentralOptions();
                    var options = new SynchronizeWithCentralOptions();
                    options.SetRelinquishOptions(new RelinquishOptions(true));
                    options.Comment = comment ?? "";
                    options.Compact = true;
                    try
                    {
                        options.SaveLocalBefore = false;
                        options.SaveLocalAfter = false;
                    }
                    catch (Exception) { }
                    try
                    {
                        doc.SynchronizeWithCentral(transact, options);
                        message = "Synced compact and relinquished every workset.";
                    }
                    catch (Exception error)
                    {
                        // a central opened directly can refuse a sync on some releases
                        debug.Exception("sync before close (falling back to a save)", FormatException(error));
                        doc.Save(new SaveOptions { Compact = true });
                        message = "Revit would not sync this file, so it was saved compact instead. Worksets were not relinquished.";
                    }
                }
                else
                {
                    doc.Save(new SaveOptions { Compact = true });
                    message = route == SavePlain ? "Saved compact." : "Saved the local file compact. Worksets are still yours.";
                }
                answered = dialogs.Seen.Count;
            }
            debug.Values(new List<(string, object)> { ("save route", route), ("result", message), ("dialogs answered", answered) });
            debug.Flush();
            return message;
        }

        /// <summary>A model that has never been saved: Save As, compact, as its own central when workshared.</summary>
        public static void SaveNewFile(UIApplication uiapp, Document doc, string target)
        {
            using (new McuDialogSuppressor(uiapp)) SaveAs(doc, target, true);
        }

        /// <summary>Revit will not let an add-in close the active model directly. Its own Close command, posted now, runs once this returns.</summary>
        public static bool PostCloseActive(UIApplication uiapp)
        {
            RevitCommandId command = null;
            try
            {
                PostableCommand close;
                if (Enum.TryParse("Close", out close)) command = RevitCommandId.LookupPostableCommandId(close);
            }
            catch (Exception) { command = null; }
            if (command == null)
            {
                try { command = RevitCommandId.LookupCommandId("ID_REVIT_FILE_CLOSE"); }
                catch (Exception) { command = null; }
            }
            if (command == null) return false;
            uiapp.PostCommand(command);
            return true;
        }

        public static bool CloseDocument(Document doc, bool save = false)
        {
            try { return doc.Close(save); }
            catch (Exception error)
            {
                Log("could not close the copy: " + FormatException(error));
                return false;
            }
        }

        public static bool TargetExists(string path) { return File.Exists(path ?? ""); }
    }
}
