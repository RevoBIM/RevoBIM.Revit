using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;

namespace RevoBIM.Tools.PanelTemplateManager
{
    /// <summary>A template move for one panel (the Apply, Merge and rebuild jobs).</summary>
    public sealed class MoveJob
    {
        public ElementId PanelId, ViewId, TemplateId;
        public string Label = "";
        public string Locked;
    }

    /// <summary>One new template to build.</summary>
    public sealed class DuplicateSpec
    {
        public int Slots;
        public string Name;
        public PanelConfiguration? Config;
        public Dictionary<string, bool> Flags;
    }

    public sealed class LabelledId
    {
        public ElementId Id;
        public string Label = "";
    }

    /// <summary>What a job reports back to the window. Fields are filled as the kind of job needs.</summary>
    public sealed class JobResult
    {
        public List<string> Done = new List<string>();
        public List<KeyValuePair<string, string>> Failed = new List<KeyValuePair<string, string>>();
        public List<KeyValuePair<string, string>> Notes = new List<KeyValuePair<string, string>>();
        public List<KeyValuePair<string, string>> Locked = new List<KeyValuePair<string, string>>();
        public List<KeyValuePair<string, string>> Made = new List<KeyValuePair<string, string>>();
        public List<string> Removed = new List<string>();
        public List<long> Ids = new List<long>();
        public List<string> Names = new List<string>();
        public int Total, OnSheet;
        public bool Ok = true;
        public string Note = "";
        public string FinalName = "";
    }

    /// <summary>One thing for the external event to run. Jobs that write to many elements take their own transactions in pieces.</summary>
    public sealed class PstmJob
    {
        public Func<UIApplication, JobResult> Run;
        public bool OwnsTransaction;
    }

    /// <summary>Everything that writes (pstm_ops.py). Nothing here runs on the WPF thread: every write goes through the ExternalEvent.</summary>
    public static class PstmOps
    {
        // ------------------------------------------------------------------ suppressing Revit's own noise
        /// <summary>Deletes warnings so a run does not stop on a dialog.</summary>
        public sealed class WarningSwallower : IFailuresPreprocessor
        {
            public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
            {
                try
                {
                    foreach (FailureMessageAccessor failure in accessor.GetFailureMessages())
                    {
                        try
                        {
                            if (failure.GetSeverity() == FailureSeverity.Warning) accessor.DeleteWarning(failure);
                        }
                        catch (Exception)
                        {
                        }
                    }
                }
                catch (Exception)
                {
                }
                return FailureProcessingResult.Continue;
            }
        }

        /// <summary>Answers Revit's task dialogs for the duration of a run. Hooked once and then switched on and off with a flag.</summary>
        public sealed class DialogSwallower
        {
            private readonly UIApplication uiapp;
            private bool hooked;

            public bool Active;

            public DialogSwallower(UIApplication uiapp)
            {
                this.uiapp = uiapp;
            }

            private void OnDialog(object sender, DialogBoxShowingEventArgs args)
            {
                if (!Active) return;
                try
                {
                    args.OverrideResult(1);   // IDOK
                }
                catch (Exception)
                {
                }
            }

            public void Hook()
            {
                if (hooked) return;
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
        }

        private static Transaction StartTransaction(Document doc, string name)
        {
            var trans = new Transaction(doc, name);
            try
            {
                trans.Start();
            }
            catch (Exception)
            {
                trans.Dispose();
                return null;
            }
            try
            {
                FailureHandlingOptions opts = trans.GetFailureHandlingOptions();
                opts.SetFailuresPreprocessor(new WarningSwallower());
                opts.SetClearAfterRollback(true);
                trans.SetFailureHandlingOptions(opts);
            }
            catch (Exception)
            {
            }
            return trans;
        }

        private static void RollBack(Transaction trans)
        {
            try
            {
                trans.RollBack();
            }
            catch (Exception)
            {
            }
        }

        /// <summary>One transaction, warnings swallowed, rolled back on any failure.</summary>
        public static JobResult RunTransaction(Document doc, string name, Func<JobResult> fn, out string error)
        {
            error = "";
            Transaction trans = StartTransaction(doc, name);
            if (trans == null)
            {
                error = "could not start a transaction";
                return null;
            }
            try
            {
                JobResult result = fn();
                trans.Commit();
                return result;
            }
            catch (Exception ex)
            {
                RollBack(trans);
                error = ex.Message;
                return null;
            }
            finally
            {
                trans.Dispose();
            }
        }

        private static void Tick(Action<int, int, string> progress, int done, int total, string label)
        {
            if (progress == null) return;
            try
            {
                progress(done, total, label);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Writes items in chunks, retrying a failed chunk one item at a time. applyOne does the write and returns (ok, note); it may throw.
        /// Everything happens inside a TransactionGroup, so Revit's undo still sees one step, but a chunk that Revit refuses is rolled back and
        /// replayed item by item - so the one item at fault is named and only that one is lost.
        /// </summary>
        public static List<Tuple<T, bool, string>> RunBatches<T>(Document doc, string name, List<T> items, Func<T, Tuple<bool, string>> applyOne,
                                                                 int chunk, Action<int, int, string> progress, Func<T, string> labelOf)
        {
            var results = new Dictionary<int, Tuple<bool, string>>();   // by position in items
            int total = items.Count == 0 ? 1 : items.Count;
            TransactionGroup group = null;
            try
            {
                group = new TransactionGroup(doc, name);
                group.Start();
            }
            catch (Exception)
            {
                group = null;
            }

            int seen = 0;
            Action<int, int> oneByOne = (from, count) =>
            {
                for (int i = from; i < from + count && i < items.Count; i++)
                {
                    Tick(progress, seen, total, labelOf(items[i]));
                    seen++;
                    Transaction trans = StartTransaction(doc, name);
                    if (trans == null)
                    {
                        results[i] = Tuple.Create(false, "could not start a transaction");
                        continue;
                    }
                    try
                    {
                        Tuple<bool, string> r = applyOne(items[i]);
                        trans.Commit();
                        results[i] = r;
                    }
                    catch (Exception ex)
                    {
                        RollBack(trans);
                        results[i] = Tuple.Create(false, "Revit refused this one: " + ex.Message);
                    }
                    finally
                    {
                        trans.Dispose();
                    }
                }
            };

            try
            {
                int index = 0;
                while (index < items.Count)
                {
                    int count = Math.Min(chunk, items.Count - index);
                    if (chunk <= 1)
                    {
                        oneByOne(index, count);   // already one at a time - a chunk retry would just do it twice
                        index += Math.Max(1, chunk);
                        continue;
                    }
                    Transaction trans = StartTransaction(doc, name);
                    if (trans == null)
                    {
                        oneByOne(index, count);
                        index += chunk;
                        continue;
                    }
                    try
                    {
                        int doneHere = 0;
                        for (int i = index; i < index + count; i++)
                        {
                            Tick(progress, seen + doneHere, total, labelOf(items[i]));
                            doneHere++;
                            results[i] = applyOne(items[i]);
                        }
                        trans.Commit();
                        seen += count;
                    }
                    catch (Exception)
                    {
                        // something in this chunk was more than Revit would take: undo the chunk and find out which one
                        RollBack(trans);
                        for (int i = index; i < index + count; i++) results.Remove(i);
                        oneByOne(index, count);
                    }
                    finally
                    {
                        trans.Dispose();
                    }
                    index += chunk;
                }
                Tick(progress, total, total, "");
            }
            finally
            {
                if (group != null)
                {
                    try
                    {
                        group.Assimilate();
                    }
                    catch (Exception)
                    {
                        try { group.RollBack(); } catch (Exception) { }
                    }
                    group.Dispose();
                }
            }

            var output = new List<Tuple<T, bool, string>>();
            for (int i = 0; i < items.Count; i++)
            {
                Tuple<bool, string> r;
                if (!results.TryGetValue(i, out r)) r = Tuple.Create(false, "never reached");
                output.Add(Tuple.Create(items[i], r.Item1, r.Item2));
            }
            return output;
        }

        // ------------------------------------------------------------------ template writes
        public static PanelScheduleType? ScheduleTypeOf(Element element)
        {
            try
            {
                var template = element as PanelScheduleTemplate;
                if (template != null) return template.GetPanelScheduleType();
            }
            catch (Exception)
            {
            }
            try
            {
                PanelScheduleData data = PstmModel.TableData(element);
                if (data != null) return data.ScheduleType;
            }
            catch (Exception)
            {
            }
            return null;
        }

        public static bool IsTemplate(Element element)
        {
            try
            {
                var view = element as PanelScheduleView;
                if (view != null) return view.IsPanelScheduleTemplate();
            }
            catch (Exception)
            {
            }
            return element is PanelScheduleTemplate;
        }

        /// <summary>
        /// Pushes a new slot count onto a template: UpdateCircuitTableForTemplate(PanelSchedulePhaseLoadType, int, bool). The configuration is
        /// not an argument - it is fixed when the template is created. The phase load type and currents flag are read off the template's own
        /// data, which already carries the source's settings by the time this runs.
        /// </summary>
        public static bool SetSlotCount(PanelScheduleTemplate template, int slots, Dictionary<string, bool> flags, out string error)
        {
            error = "";
            PanelScheduleData data = PstmModel.TableData(template);
            if (data == null)
            {
                error = "the template has no table data";
                return false;
            }
            PanelSchedulePhaseLoadType phaseType;
            try
            {
                phaseType = data.PhaseLoadType;
            }
            catch (Exception)
            {
                error = "could not work out the phase load type";
                return false;
            }
            bool asCurrents;
            try
            {
                asCurrents = data.PhasesAsCurrents;
            }
            catch (Exception)
            {
                bool f;
                asCurrents = flags != null && flags.TryGetValue("PhasesAsCurrents", out f) && f;
            }
            try
            {
                data.UpdateCircuitTableForTemplate(phaseType, slots, asCurrents);
                return true;
            }
            catch (Exception ex)
            {
                error = "could not set the slot count: " + ex.Message + " [Revit wants: UpdateCircuitTableForTemplate(PanelSchedulePhaseLoadType, Int32, Boolean)]";
                return false;
            }
        }

        private static PanelScheduleTemplate CreateTemplate(Document doc, string name, Element source, PanelConfiguration? config, out string error)
        {
            error = "";
            PanelScheduleType? type = ScheduleTypeOf(source);
            if (type == null)
            {
                error = "could not work out the panel schedule type";
                return null;
            }
            PanelConfiguration cfg;
            if (config != null) cfg = config.Value;
            else
            {
                try
                {
                    cfg = PstmModel.TableData(source).PanelConfiguration;
                }
                catch (Exception)
                {
                    cfg = PanelConfiguration.OneColumn;   // never leave it unset
                }
            }
            try
            {
                // Create(Document, PanelScheduleType, PanelConfiguration, string): four arguments, in this order
                return PanelScheduleTemplate.Create(doc, type.Value, cfg, name);
            }
            catch (Exception ex)
            {
                error = ex.Message + " [Revit wants: Create(Document, PanelScheduleType, PanelConfiguration, String)]";
                return null;
            }
        }

        public static bool StillThere(Document doc, ElementId id)
        {
            try
            {
                Element found = doc.GetElement(id);
                if (found == null) return false;
                try { return found.IsValidObject; } catch (Exception) { return true; }
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Makes one template, checking after every step that it still exists: Revit can accept a call, leave the element looking fine, and then drop it
        /// at commit. Returns the element (null if it did not make it) and says in steps how far it got.
        /// </summary>
        private static PanelScheduleTemplate BuildOnce(Document doc, Element source, string name, int slots, PanelConfiguration? config,
                                                       Dictionary<string, bool> flags, bool copyLayout, List<string> steps)
        {
            string why;
            PanelScheduleTemplate element = CreateTemplate(doc, name, source, config, out why);
            if (element == null)
            {
                steps.Add("Create refused it: " + why);
                return null;
            }
            ElementId id = element.Id;
            steps.Add("created");
            if (!StillThere(doc, id))
            {
                steps.Add("then it vanished straight after Create");
                return null;
            }
            if (copyLayout)
            {
                try
                {
                    element.SetTableData(PstmModel.TableData(source));
                    steps.Add("layout copied from the source");
                }
                catch (Exception ex)
                {
                    steps.Add("SetTableData refused: " + ex.Message);
                }
                if (!StillThere(doc, id))
                {
                    steps.Add("then it vanished when the layout went in");
                    return null;
                }
            }
            if (slots > 0)
            {
                string err;
                bool ok = SetSlotCount(element, slots, flags, out err);
                steps.Add(ok ? "slot count set" : "slot count failed: " + err);
                if (!StillThere(doc, id))
                {
                    steps.Add("then it vanished when the slot count went in");
                    return null;
                }
            }
            try
            {
                doc.Regenerate();
                steps.Add("regenerated");
            }
            catch (Exception ex)
            {
                steps.Add("Regenerate refused: " + ex.Message);
            }
            if (!StillThere(doc, id))
            {
                steps.Add("then it vanished at regeneration");
                return null;
            }
            return element;
        }

        /// <summary>
        /// Copies a template, renames it and gives it a fixed slot count. A PanelScheduleTemplate cannot be copied by Revit, so the only route is
        /// Create plus the source's table data. If the layout copy is what destroys it, it is tried again without the layout.
        /// </summary>
        public static Element DuplicateTemplate(Document doc, Element source, string newName, int slots, PanelConfiguration? config, ISet<string> taken,
                                                Dictionary<string, bool> flags, bool copyLayout, out string note)
        {
            string name = PstmCore.UniqueName(newName, taken);
            var steps = new List<string>();
            PanelScheduleTemplate element = BuildOnce(doc, source, name, slots, config, flags, copyLayout, steps);
            string fallbackNote = "";
            if (element == null && copyLayout)
            {
                string second = PstmCore.UniqueName(name, taken);
                var more = new List<string>();
                element = BuildOnce(doc, source, second, slots, config, flags, false, more);
                if (element != null)
                {
                    fallbackNote = "the source layout could not be carried over, so this is a plain template of the right type, configuration and size - with the layout it " +
                                   string.Join("; ", steps);
                    name = second;
                }
                else
                {
                    note = "could not duplicate \"" + PstmModel.ElementName(source) + "\" - with the layout it " + string.Join("; ", steps) +
                           "; without it " + string.Join("; ", more);
                    return null;
                }
            }
            if (element == null)
            {
                note = "could not duplicate \"" + PstmModel.ElementName(source) + "\" - it " + string.Join("; ", steps);
                return null;
            }
            var notes = new List<string>();
            if (fallbackNote.Length > 0) notes.Add(fallbackNote);
            if (PstmModel.ElementName(element) != name)
            {
                if (!PstmModel.SetElementName(element, name))
                {
                    string spare = PstmCore.UniqueName(name + " Copy", taken);
                    if (PstmModel.SetElementName(element, spare)) notes.Add("Revit would not take the name \"" + name + "\", so it is called \"" + spare + "\"");
                    else notes.Add("Revit would not rename it - it is called \"" + PstmModel.ElementName(element) + "\"");
                }
            }
            taken.Add(PstmModel.ElementName(element).ToLowerInvariant());
            if (!IsTemplate(element)) notes.Add("it came back as a panel schedule view rather than a template, so it will not appear in the template list");
            note = string.Join("; ", notes);
            return element;
        }

        public static long TemplateOn(PanelScheduleView view)
        {
            return PstmModel.ViewTemplateId(view);
        }

        private static void RegenerateQuietly(Document doc)
        {
            try
            {
                doc.Regenerate();
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Calls the one-argument GenerateInstanceFromTemplate. Returns (ok, error).</summary>
        private static Tuple<bool, string> GenerateFrom(PanelScheduleView view, ElementId tid)
        {
            try
            {
                view.GenerateInstanceFromTemplate(tid);
                return Tuple.Create(true, "");
            }
            catch (Exception ex)
            {
                return Tuple.Create(false, ex.Message);
            }
        }

        /// <summary>Ids of schedule views sitting on a sheet. Rebuilding one of those would take it off its sheet.</summary>
        public static HashSet<long> PlacedViewIds(Document doc)
        {
            var output = new HashSet<long>();
            try
            {
                foreach (Element inst in new FilteredElementCollector(doc).OfClass(typeof(ScheduleSheetInstance)))
                {
                    try { output.Add(((ScheduleSheetInstance)inst).ScheduleId.Value); } catch (Exception) { }
                }
            }
            catch (Exception)
            {
            }
            return output;
        }

        /// <summary>Why this template cannot go on this panel, or "" if it can (Revit answers a mismatch with an unreadable managed exception).</summary>
        private static string TypeMismatch(Document doc, PanelScheduleView view, ElementId tid)
        {
            Element template;
            try { template = doc.GetElement(tid); } catch (Exception) { return ""; }
            if (template == null) return "that template is not in the model any more";
            PanelScheduleType? theirs = ScheduleTypeOf(template);
            PanelScheduleType? mine = ScheduleTypeOf(view);
            if (theirs == null || mine == null) return "";
            if (theirs.Value != mine.Value)
                return "that template is a " + theirs.Value + " template and this panel has a " + mine.Value + " schedule";
            return "";
        }

        /// <summary>A panel with no schedule at all gets one, on the template asked for.</summary>
        private static Tuple<bool, string> CreateForPanel(Document doc, ElementId panelId, ElementId tid)
        {
            PanelScheduleView made;
            try
            {
                made = PanelScheduleView.CreateInstanceView(doc, panelId, tid);
            }
            catch (Exception first)
            {
                try
                {
                    made = PanelScheduleView.CreateInstanceView(doc, panelId);
                }
                catch (Exception second)
                {
                    return Tuple.Create(false, "could not make a panel schedule for it: " + first.Message + "; and without a template: " + second.Message);
                }
            }
            if (made == null) return Tuple.Create(false, "Revit made no panel schedule for this panel");
            if (TemplateOn(made) != tid.Value)
            {
                Tuple<bool, string> r = GenerateFrom(made, tid);
                if (!r.Item1) return r;
            }
            return Tuple.Create(true, "a panel schedule was created for this panel");
        }

        /// <summary>
        /// Last resort: throw the schedule away and make a new one on the template (the template is chosen at creation). If the rebuild does not take either,
        /// this THROWS, so the caller's transaction rolls back and the panel keeps the schedule it had.
        /// </summary>
        private static Tuple<bool, string> RebuildOnTemplate(Document doc, ElementId panelId, PanelScheduleView view, ElementId tid)
        {
            if (view != null)
            {
                try
                {
                    doc.Delete(view.Id);
                }
                catch (Exception ex)
                {
                    return Tuple.Create(false, "could not clear the old schedule: " + ex.Message);
                }
            }
            PanelScheduleView made;
            try
            {
                made = PanelScheduleView.CreateInstanceView(doc, panelId, tid);
            }
            catch (Exception ex)
            {
                return Tuple.Create(false, "rebuild refused: " + ex.Message);
            }
            if (made == null) return Tuple.Create(false, "rebuild made no panel schedule");
            RegenerateQuietly(doc);
            if (TemplateOn(made) != tid.Value)
                throw new InvalidOperationException("rebuilt the schedule and it still did not take the template, so it was put back");
            return Tuple.Create(true, "schedule rebuilt - Revit would not swap the template in place");
        }

        private static PanelScheduleView ResolveView(Document doc, MoveJob job)
        {
            if (job.ViewId == null) return null;
            try
            {
                return doc.GetElement(job.ViewId) as PanelScheduleView;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>
        /// Puts templates onto panels in three passes (not one transaction, not one regenerate per panel): swap in chunks; read every panel back and see which ones
        /// moved; rebuild the ones that did not, one transaction each. Takes its own transactions - do not call it inside one.
        /// </summary>
        public static JobResult ApplyMoves(Document doc, List<MoveJob> jobs, Action<int, int, string> progress, bool allowRebuild = true, int chunk = 20)
        {
            var result = new JobResult();
            HashSet<long> placed = PlacedViewIds(doc);
            const string name = "RevoBIM apply panel schedule templates";
            // asked again here rather than trusted from the window's read: ownership is cached from central
            var owner = new Ownership(doc);

            Func<MoveJob, PanelScheduleView, string> lockedReason = (job, view) =>
            {
                Element panel = null;
                try { panel = doc.GetElement(job.PanelId); } catch (Exception) { }
                var holders = new List<Element>();
                if (view != null) holders.Add(view);
                if (panel != null) holders.Add(panel);
                return owner.LockedAny(holders);
            };

            // pass 1: the polite swap
            Func<MoveJob, Tuple<bool, string>> swap = job =>
            {
                PanelScheduleView view = ResolveView(doc, job);
                ElementId tid = job.TemplateId;
                if (tid == null) return Tuple.Create(false, "no template to assign");
                if (view != null && TemplateOn(view) == tid.Value) return Tuple.Create(true, "");
                string stop = lockedReason(job, view);
                if (stop.Length > 0)
                {
                    job.Locked = stop;
                    return Tuple.Create(false, stop);
                }
                if (view == null) return CreateForPanel(doc, job.PanelId, tid);
                string mismatch = TypeMismatch(doc, view, tid);
                if (mismatch.Length > 0) return Tuple.Create(false, mismatch);
                return GenerateFrom(view, tid);
            };
            List<Tuple<MoveJob, bool, string>> first = RunBatches(doc, name, jobs.ToList(), swap, chunk, progress, j => j.Label);

            // pass 2: what actually landed
            var stuck = new List<MoveJob>();
            foreach (var item in first)
            {
                MoveJob job = item.Item1;
                if (!item.Item2)
                {
                    // a panel somebody else has is reported separately, and the run carries on
                    if (!string.IsNullOrEmpty(job.Locked)) result.Locked.Add(new KeyValuePair<string, string>(job.Label, job.Locked));
                    else result.Failed.Add(new KeyValuePair<string, string>(job.Label, item.Item3));
                    continue;
                }
                PanelScheduleView view = ResolveView(doc, job);
                if (view != null && TemplateOn(view) != job.TemplateId.Value) stuck.Add(job);
                else
                {
                    result.Done.Add(job.Label);
                    if (!string.IsNullOrEmpty(item.Item3)) result.Notes.Add(new KeyValuePair<string, string>(job.Label, item.Item3));
                }
            }
            if (stuck.Count == 0) return result;

            // pass 3: rebuild the ones Revit would not swap
            if (!allowRebuild)
            {
                foreach (MoveJob job in stuck)
                    result.Failed.Add(new KeyValuePair<string, string>(job.Label,
                        "Revit took the call and left the panel on its old template, and rebuilding is switched off in Settings"));
                return result;
            }
            var rebuildable = new List<MoveJob>();
            foreach (MoveJob job in stuck)
            {
                PanelScheduleView view = ResolveView(doc, job);
                if (view != null && placed.Contains(view.Id.Value))
                    result.Failed.Add(new KeyValuePair<string, string>(job.Label,
                        "Revit would not swap the template and its schedule is placed on a sheet, so it was left alone rather than rebuilt"));
                else rebuildable.Add(job);
            }
            // one at a time: a delete and a create is not something to batch
            List<Tuple<MoveJob, bool, string>> second = RunBatches(doc, name, rebuildable,
                job => RebuildOnTemplate(doc, job.PanelId, ResolveView(doc, job), job.TemplateId), 1, progress, j => j.Label);
            foreach (var item in second)
            {
                if (item.Item2)
                {
                    result.Done.Add(item.Item1.Label);
                    if (!string.IsNullOrEmpty(item.Item3)) result.Notes.Add(new KeyValuePair<string, string>(item.Item1.Label, item.Item3));
                }
                else result.Failed.Add(new KeyValuePair<string, string>(item.Item1.Label, item.Item3));
            }
            return result;
        }

        // ------------------------------------------------------------------ jobs
        public static PstmJob JobApplyAssignments(Document doc, List<MoveJob> jobs, Action<int, int, string> progress, bool allowRebuild = true, int chunk = 20)
        {
            return new PstmJob { OwnsTransaction = true, Run = app => ApplyMoves(doc, jobs, progress, allowRebuild, chunk) };
        }

        /// <summary>A view Revit can open for this template, if there is one (PanelScheduleTemplate derives from Element, not from View).</summary>
        private static View TemplateAsView(Document doc, ElementId templateId, string templateName)
        {
            long wanted = templateId.Value;
            Element element = null;
            try { element = doc.GetElement(templateId); } catch (Exception) { }
            var view = element as View;
            if (view != null) return view;
            string name = (templateName ?? "").Trim().ToLowerInvariant();
            try
            {
                foreach (Element e in new FilteredElementCollector(doc).OfClass(typeof(PanelScheduleView)))
                {
                    var candidate = (PanelScheduleView)e;
                    try { if (!candidate.IsPanelScheduleTemplate()) continue; } catch (Exception) { continue; }
                    if (candidate.Id.Value == wanted) return candidate;
                    if (name.Length > 0 && PstmModel.ElementName(candidate).Trim().ToLowerInvariant() == name) return candidate;
                }
            }
            catch (Exception)
            {
            }
            return null;
        }

        /// <summary>Opens a panel schedule template in Revit's own editor where the release exposes it as a view; otherwise says what to do by hand.</summary>
        public static PstmJob JobEditTemplate(Document doc, ElementId templateId, string templateName)
        {
            return new PstmJob
            {
                OwnsTransaction = true,
                Run = app =>
                {
                    View view = TemplateAsView(doc, templateId, templateName);
                    if (view == null)
                        return new JobResult { Ok = false, Note = "Revit does not expose this template as a view, so it cannot be opened from the API." };
                    try
                    {
                        // a request, not an assignment: carried out after this API context ends, which is right for a modeless window
                        app.ActiveUIDocument.RequestViewChange(view);
                        return new JobResult { Ok = true };
                    }
                    catch (Exception ex)
                    {
                        return new JobResult { Ok = false, Note = "Revit would not open it: " + ex.Message };
                    }
                },
            };
        }

        /// <summary>
        /// Re-pours every panel schedule from the template it is already on (GenerateInstanceFromTemplate with the view's OWN template): editing a template does not
        /// push the change into the schedules already made from it. Panels somebody else owns are skipped and named, the same as Apply.
        /// </summary>
        public static PstmJob JobRegenerate(Document doc, Action<int, int, string> progress, int chunk = 20)
        {
            return new PstmJob
            {
                OwnsTransaction = true,
                Run = app =>
                {
                    List<PanelScheduleView> views = PstmModel.InstanceViews(doc);
                    var owner = new Ownership(doc);
                    HashSet<long> placed = PlacedViewIds(doc);
                    var items = views.Select(v => new MoveJob { ViewId = v.Id, Label = PstmModel.ElementName(v).Length > 0 ? PstmModel.ElementName(v) : "panel schedule" }).ToList();
                    var result = new JobResult();
                    Func<MoveJob, Tuple<bool, string>> one = item =>
                    {
                        var view = doc.GetElement(item.ViewId) as PanelScheduleView;
                        if (view == null) return Tuple.Create(false, "that schedule is not in the model any more");
                        string stop = owner.Locked(view);
                        if (stop.Length > 0)
                        {
                            item.Locked = stop;
                            return Tuple.Create(false, stop);
                        }
                        ElementId tid = view.GetTemplate();
                        if (tid == null || tid.Value <= 0) return Tuple.Create(false, "no template on this schedule to regenerate from");
                        return GenerateFrom(view, tid);
                    };
                    var output = RunBatches(doc, "RevoBIM regenerate panel schedules", items, one, chunk, progress, i => i.Label);
                    foreach (var item in output)
                    {
                        if (item.Item2) result.Done.Add(item.Item1.Label);
                        else if (!string.IsNullOrEmpty(item.Item1.Locked)) result.Locked.Add(new KeyValuePair<string, string>(item.Item1.Label, item.Item1.Locked));
                        else result.Failed.Add(new KeyValuePair<string, string>(item.Item1.Label, item.Item3));
                    }
                    result.Total = items.Count;
                    result.OnSheet = items.Count(i => placed.Contains(i.ViewId.Value));
                    return result;
                },
            };
        }

        /// <summary>Builds each spec as a copy of the source; one transaction for the batch.</summary>
        public static PstmJob JobDuplicate(Document doc, Element source, List<DuplicateSpec> specs, ISet<string> taken, bool copyLayout, Action<int, int, string> progress)
        {
            return new PstmJob
            {
                Run = app =>
                {
                    var result = new JobResult();
                    int total = specs.Count;
                    for (int index = 0; index < total; index++)
                    {
                        DuplicateSpec spec = specs[index];
                        Tick(progress, index, total, spec.Name);
                        string note;
                        Element el = DuplicateTemplate(doc, source, spec.Name, spec.Slots, spec.Config, taken, spec.Flags, copyLayout, out note);
                        if (el == null) result.Failed.Add(new KeyValuePair<string, string>(spec.Name, note));
                        else
                        {
                            string final = PstmModel.ElementName(el);
                            result.Made.Add(new KeyValuePair<string, string>(final, note));
                            try { result.Ids.Add(el.Id.Value); } catch (Exception) { }
                            result.Names.Add(final);
                        }
                    }
                    Tick(progress, total, total, "");
                    return result;
                },
            };
        }

        public static PstmJob JobDelete(Document doc, List<LabelledId> ids, Action<int, int, string> progress)
        {
            return new PstmJob
            {
                Run = app =>
                {
                    var result = new JobResult();
                    int total = ids.Count;
                    for (int index = 0; index < total; index++)
                    {
                        LabelledId item = ids[index];
                        Tick(progress, index, total, item.Label);
                        try
                        {
                            doc.Delete(item.Id);
                            result.Removed.Add(item.Label);
                        }
                        catch (Exception ex)
                        {
                            result.Failed.Add(new KeyValuePair<string, string>(item.Label, ex.Message));
                        }
                    }
                    Tick(progress, total, total, "");
                    return result;
                },
            };
        }

        /// <summary>
        /// Moves onto the target template through the same batched route as Apply, then deletes the emptied templates - only if every panel really did move.
        /// </summary>
        public static PstmJob JobMerge(Document doc, List<MoveJob> moves, List<LabelledId> deleteIds, Action<int, int, string> progress, bool allowRebuild = true)
        {
            return new PstmJob
            {
                OwnsTransaction = true,
                Run = app =>
                {
                    JobResult result = ApplyMoves(doc, moves, progress, allowRebuild);
                    if (result.Failed.Count == 0 && deleteIds.Count > 0)
                    {
                        var output = RunBatches(doc, "RevoBIM merge templates", deleteIds.ToList(), item =>
                        {
                            doc.Delete(item.Id);
                            return Tuple.Create(true, "");
                        }, 1, progress, i => i.Label);
                        foreach (var item in output)
                        {
                            if (item.Item2) result.Removed.Add(item.Item1.Label);
                            else result.Failed.Add(new KeyValuePair<string, string>(item.Item1.Label, item.Item3));
                        }
                    }
                    return result;
                },
            };
        }

        /// <summary>
        /// Renames in two passes. Swapping "A" and "B", or shuffling a set of names along by one, means a name is briefly taken by the element about to give it
        /// up - so everything goes to a parked name first and lands on its real one second.
        /// </summary>
        public static PstmJob JobRenameMany(Document doc, List<KeyValuePair<Element, string>> pairs, IEnumerable<string> taken, Action<int, int, string> progress)
        {
            return new PstmJob
            {
                Run = app =>
                {
                    var result = new JobResult();
                    var held = new HashSet<string>((taken ?? new string[0]).Select(n => (n ?? "").ToLowerInvariant()));
                    foreach (var pair in pairs) held.Remove((pair.Value ?? "").ToLowerInvariant());
                    var parked = new List<Tuple<Element, string, string>>();
                    int total = pairs.Count * 2;
                    if (total == 0) total = 1;
                    int step = 0;
                    foreach (var pair in pairs)
                    {
                        step++;
                        Tick(progress, step, total, PstmModel.ElementName(pair.Key));
                        string before = PstmModel.ElementName(pair.Key);
                        string park = PstmCore.UniqueName(before + " ~renaming", held);
                        if (PstmModel.SetElementName(pair.Key, park))
                        {
                            held.Add(park.ToLowerInvariant());
                            parked.Add(Tuple.Create(pair.Key, before, pair.Value));
                        }
                        else result.Failed.Add(new KeyValuePair<string, string>(before, "Revit would not let go of the old name"));
                    }
                    foreach (var item in parked)
                    {
                        step++;
                        Tick(progress, step, total, item.Item3);
                        string final = PstmCore.UniqueName(item.Item3, held);
                        if (PstmModel.SetElementName(item.Item1, final))
                        {
                            held.Add(final.ToLowerInvariant());
                            result.Done.Add(final);
                            if (final != item.Item3)
                                result.Notes.Add(new KeyValuePair<string, string>(item.Item2, "that name was taken, so it is now \"" + final + "\""));
                        }
                        else
                        {
                            // put it back rather than leaving a parked name in the model
                            PstmModel.SetElementName(item.Item1, item.Item2);
                            result.Failed.Add(new KeyValuePair<string, string>(item.Item2, "Revit refused the new name"));
                        }
                    }
                    Tick(progress, total, total, "");
                    return result;
                },
            };
        }

        public static string JobTitle = "RevoBIM Panel Template Mngr";
    }

    /// <summary>Carries one job at a time from the window into Revit's API context.</summary>
    public sealed class PstmEventHandler : IExternalEventHandler
    {
        public PstmJob Job;
        public Document Doc;
        public Action<JobResult, string> OnComplete;
        private PstmOps.DialogSwallower swallower;

        public void Execute(UIApplication app)
        {
            PstmJob job = Job;
            Job = null;
            Action<JobResult, string> callback = OnComplete;
            JobResult result = null;
            string error = "";
            if (job == null)
            {
                // the window has already gone busy waiting for this, so it has to hear back either way
                if (callback != null)
                {
                    try { callback(null, "the job went missing before it could run"); } catch (Exception) { }
                }
                return;
            }
            try
            {
                Document doc = Doc ?? app.ActiveUIDocument.Document;
                if (swallower == null) swallower = new PstmOps.DialogSwallower(app);
                swallower.Hook();
                swallower.Active = true;
                try
                {
                    if (job.OwnsTransaction)
                    {
                        // a job that writes to many elements takes its own transactions in pieces, so one bad element cannot roll back the rest
                        result = job.Run(app);
                    }
                    else result = PstmOps.RunTransaction(doc, PstmOps.JobTitle, () => job.Run(app), out error);
                }
                finally
                {
                    swallower.Active = false;
                }
            }
            catch (Exception ex)
            {
                error = ex.Message;
            }
            if (callback != null)
            {
                try { callback(result, error); } catch (Exception) { }
            }
        }

        public string GetName()
        {
            return "RevoBIM Panel Template Mngr";
        }
    }
}
