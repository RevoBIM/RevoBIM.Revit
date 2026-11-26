using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.ViewManager;

namespace RevoBIM.UI.ViewManager
{
    /// <summary>One item refused. Carries the log line already formatted.</summary>
    internal sealed class VmJobFailed : Exception
    {
        public VmJobFailed(string message) : base(message) { }
    }

    /// <summary>The creating half of the main window: Create Views, Dependent Views, the batch runner and the room tags.</summary>
    internal sealed partial class VmWindow
    {
        private readonly Dictionary<string, double> timings = new Dictionary<string, double>();
        private List<ElementId> createdViewIds = new List<ElementId>();
        private List<ElementId> chunkViews = new List<ElementId>();
        private VmRevit.TagStats tagStats = new VmRevit.TagStats();
        private string tagNote;

        private void AddTiming(string key, Stopwatch clock)
        {
            double v;
            timings.TryGetValue(key, out v);
            timings[key] = v + clock.ElapsedMilliseconds;
        }

        // ---------------------------------------------------------------- Create Views --

        private void OnCreateViews()
        {
            if (Busy) return;
            List<long> tplKeys = Selected(tplState), lvlKeys = Selected(lvlState);
            long? boxKey = cvBoxKey;
            if (tplKeys.Count == 0 || lvlKeys.Count == 0 || boxKey == null)
            {
                SetStatus("Select templates, levels and one scope box.", true);
                return;
            }

            LogEnvironment("Create Views");
            var tplOrder = new Dictionary<long, int>();
            for (int i = 0; i < templates.Count; i++) tplOrder[VmRevit.Key(templates[i])] = i;
            tplKeys = tplKeys.OrderBy(k => tplOrder.ContainsKey(k) ? tplOrder[k] : 0).ToList();
            var lvlOrder = new Dictionary<long, int>();
            for (int i = 0; i < levels.Count; i++) lvlOrder[VmRevit.Key(levels[i])] = i;
            lvlKeys = lvlKeys.OrderBy(k => lvlOrder.ContainsKey(k) ? lvlOrder[k] : 0).ToList();

            bool withTags = false;
            try { withTags = chkRoomTags.IsChecked == true; } catch (Exception) { }
            bool withLinks = VmCore.SettingOn("room_tags_links");

            long box = boxKey.Value;
            AskThen(app => DoCreateViews(tplKeys, lvlKeys, box, withTags, withLinks));
        }

        private void DoCreateViews(List<long> tplKeys, List<long> lvlKeys, long boxKey, bool withTags, bool withLinks)
        {
            Element box = Live(boxKey);
            if (box == null)
            {
                BackOnUi(() => Finish("That scope box is no longer in the model - press Refresh.", true, true));
                return;
            }

            List<View> tpls = tplKeys.Select(Live).Where(e => e != null).Cast<View>().ToList();
            List<Level> lvls = lvlKeys.Select(Live).Where(e => e != null).Cast<Level>().ToList();
            if (tpls.Count == 0 || lvls.Count == 0)
            {
                BackOnUi(() => Finish("The picked templates or levels are no longer in the model - press Refresh.", true, true));
                return;
            }

            Log.Add("Scope box: [" + VmRevit.Key(box) + "] " + box.Name);
            Log.Add("Selected templates:");
            foreach (View t in tpls)
            {
                string typeName = t.ViewType.ToString();
                ViewFamily? family = VmRevit.PlanFamilyFor(typeName);
                bool matched;
                string abbr = VmCore.AbbreviateTemplate(t.Name, out matched);
                Log.Add("  [" + VmRevit.Key(t) + "] " + t.Name + "  ViewType=" + typeName + "  ViewFamily=" + (family == null ? "None" : family.ToString()) + "  abbr=" + abbr + (matched ? "" : " (no keyword match)"));
            }
            Log.Add("Selected levels:");
            foreach (Level lv in lvls)
                Log.Add("  [" + VmRevit.Key(lv) + "] " + lv.Name + "  elev=" + lv.Elevation + "  abbr=" + VmCore.AbbreviateLevel(lv.Name));
            Log.Add("");

            HashSet<string> taken = VmRevit.ExistingViewNames(Doc);
            var cache = new Dictionary<string, ViewFamilyType>();
            var noPlan = new List<string>();
            var jobs = new List<Func<List<string>, string>>();

            foreach (View tpl in tpls)
            {
                ViewFamilyType vft = VmRevit.ViewFamilyTypeFor(Doc, tpl.ViewType.ToString(), cache, Log);
                if (vft == null)
                {
                    if (!noPlan.Contains(tpl.Name)) noPlan.Add(tpl.Name);
                    Log.Add("SKIP  template '" + tpl.Name + "' - no plan ViewFamilyType for ViewType " + tpl.ViewType);
                    continue;
                }
                string abbr = VmCore.AbbreviateTemplate(tpl.Name);
                string vftName = VmRevit.TypeNameOf(vft);
                Log.Add("Template '" + tpl.Name + "' -> ViewFamilyType '" + vftName + "' [" + VmRevit.Key(vft) + "]");
                foreach (Level lvl in lvls) jobs.Add(MakeViewJob(tpl, vft, vftName, lvl, box, abbr, taken));
            }

            if (jobs.Count == 0)
            {
                BackOnUi(() => Finish("Nothing to create - none of the picked templates are plan templates.", true, true));
                return;
            }

            Action after = null;
            if (withTags) after = () => TagNewViews(withLinks);

            int created, failed;
            double elapsed;
            RunBatched(jobs, taken, "views", after, out created, out failed, out elapsed);

            string msg = "Created " + created + " view(s) on " + box.Name + " in " + VmCore.PrettyTime(elapsed);
            if (withTags && !string.IsNullOrEmpty(tagNote)) msg += "  -  " + tagNote;
            else if (withTags)
            {
                msg += "  -  " + tagStats.Tagged + " room tag(s)";
                if (tagStats.Refused > 0) msg += ", " + tagStats.Refused + " refused";
            }
            if (noPlan.Count > 0)
            {
                msg += "  -  not a plan template: " + string.Join(", ", noPlan.Take(3));
                if (noPlan.Count > 3) msg += " +" + (noPlan.Count - 3) + " more";
            }
            if (failed > 0) msg += "  -  " + failed + " failed";

            LogTimings(created, failed, elapsed);
            Log.Add("Result: created=" + created + ", failed=" + failed + ", skipped templates=" + noPlan.Count);

            BackOnUi(() =>
            {
                ReadModel();
                RebuildAll();
                Finish(msg + ".", failed > 0 || noPlan.Count > 0, failed > 0);
            });
        }

        /// <summary>One view, as a callable the batch runner can replay on its own.</summary>
        private Func<List<string>, string> MakeViewJob(View tpl, ViewFamilyType vft, string vftName, Level lvl, Element box, string abbr, HashSet<string> taken)
        {
            string target = VmCore.Sanitise(abbr + VmCore.CreateSeparator + VmCore.AbbreviateLevel(lvl.Name));
            return added =>
            {
                string stage = "start";
                try
                {
                    string final = VmCore.UniqueName(target, taken);

                    stage = "ViewPlan.Create";
                    var clock = Stopwatch.StartNew();
                    ViewPlan newView = ViewPlan.Create(Doc, vft.Id, lvl.Id);
                    if (newView == null) throw new Exception("ViewPlan.Create returned nothing usable");
                    AddTiming("create", clock);

                    // name first: a template never locks the name, but it can lock the crop and scope box parameters.
                    stage = "rename";
                    clock = Stopwatch.StartNew();
                    string nameNote;
                    bool okName = VmRevit.SetName(newView, final, out nameNote);
                    if (!okName)
                    {
                        final = VmCore.UniqueName(target + " 1", taken);
                        okName = VmRevit.SetName(newView, final, out nameNote);
                    }
                    AddTiming("name", clock);

                    VmRevit.Quiet hidden = null;
                    string quietNote = "";
                    if (fastMode)
                    {
                        stage = "hide links and worksets";
                        clock = Stopwatch.StartNew();
                        hidden = VmRevit.QuietenView(Doc, newView, out quietNote);
                        AddTiming("quieten", clock);
                    }

                    stage = "scope box";
                    clock = Stopwatch.StartNew();
                    string boxNote;
                    bool okBox = VmRevit.ApplyScopeBox(newView, box.Id, false, out boxNote);
                    AddTiming("scopebox", clock);

                    stage = "view template";
                    clock = Stopwatch.StartNew();
                    string tplNote;
                    bool okTpl = VmRevit.ApplyTemplate(newView, tpl, out tplNote);
                    AddTiming("template", clock);

                    if (hidden != null && (hidden.Worksets.Count > 0 || hidden.Categories.Count > 0))
                    {
                        stage = "restore worksets";
                        clock = Stopwatch.StartNew();
                        VmRevit.RestoreQuiet(newView, hidden);
                        AddTiming("restore", clock);
                    }

                    // Only re-assert the scope box where the template actually took it away.
                    if (okTpl && okBox)
                    {
                        stage = "scope box (recheck)";
                        if (!VmRevit.ScopeBoxHolds(newView, box.Id)) okBox = VmRevit.ApplyScopeBox(newView, box.Id, false, out boxNote);
                    }

                    taken.Add(final);
                    added.Add(final);
                    chunkViews.Add(newView.Id);

                    var note = new List<string>();
                    if (!okName) note.Add("name: " + nameNote);
                    if (!okBox) note.Add("scope box: " + boxNote);
                    if (!okTpl) note.Add("template: " + tplNote);
                    if (quietNote.Length > 0) note.Add("quieten: " + quietNote);
                    return "OK    " + final + "  [" + VmRevit.Key(newView) + "]" + (note.Count > 0 ? "   WARN " + string.Join("; ", note) : "");
                }
                catch (Exception ex)
                {
                    throw new VmJobFailed("FAIL  " + target + "  at stage '" + stage + "'\n"
                        + "      template [" + VmRevit.Key(tpl) + "] " + tpl.Name + ", level [" + VmRevit.Key(lvl) + "] " + lvl.Name + ", VFT [" + VmRevit.Key(vft) + "] " + vftName + "\n"
                        + "      " + VmCore.Describe(ex) + "\n      " + ex.ToString().Replace("\n", "\n      ").TrimEnd());
                }
            };
        }

        // ---------------------------------------------------------------- Dependent Views --

        private void OnApplyDependents()
        {
            if (Busy) return;
            List<long> viewKeys = Selected(viewState), boxKeys = Selected(boxState);
            if (viewKeys.Count == 0)
            {
                SetStatus("Select at least one host view.", true);
                return;
            }
            if (boxKeys.Count == 0)
            {
                SetStatus("Select at least one scope box.", true);
                return;
            }
            LogEnvironment("Apply Dependents");
            var viewOrder = new Dictionary<long, int>();
            for (int i = 0; i < hostViews.Count; i++) viewOrder[VmRevit.Key(hostViews[i])] = i;
            var boxOrder = new Dictionary<long, int>();
            for (int i = 0; i < scopeBoxes.Count; i++) boxOrder[VmRevit.Key(scopeBoxes[i])] = i;
            viewKeys = viewKeys.OrderBy(k => viewOrder.ContainsKey(k) ? viewOrder[k] : 0).ToList();
            boxKeys = boxKeys.OrderBy(k => boxOrder.ContainsKey(k) ? boxOrder[k] : 0).ToList();
            AskThen(app => DoApplyDependents(viewKeys, boxKeys));
        }

        private void DoApplyDependents(List<long> viewKeys, List<long> boxKeys)
        {
            List<View> views = viewKeys.Select(Live).Where(e => e != null).Cast<View>().ToList();
            List<Element> boxes = boxKeys.Select(Live).Where(e => e != null).ToList();
            if (views.Count == 0 || boxes.Count == 0)
            {
                BackOnUi(() => Finish("The picked views or scope boxes are no longer in the model - press Refresh.", true, true));
                return;
            }

            Log.Add("Selected host views:");
            foreach (View v in views) Log.Add("  [" + VmRevit.Key(v) + "] " + v.Name + "  (" + v.ViewType + ")");
            Log.Add("Selected scope boxes:");
            foreach (Element b in boxes) Log.Add("  [" + VmRevit.Key(b) + "] " + b.Name);
            Log.Add("");

            HashSet<string> taken = VmRevit.ExistingViewNames(Doc);
            var jobs = new List<Func<List<string>, string>>();
            int skipped = 0;
            foreach (View host in views)
            {
                foreach (Element box in boxes)
                {
                    string target = VmCore.Sanitise(VmCore.NamePrefix + host.Name + VmCore.NameSeparator + VmCore.BoxAbbr(box.Name));
                    if (taken.Contains(target))
                    {
                        skipped++;
                        Log.Add("SKIP  " + target + " - a view of that name exists");
                        continue;
                    }
                    jobs.Add(MakeDependentJob(host, box, target, taken));
                }
            }

            if (jobs.Count == 0)
            {
                BackOnUi(() => Finish("Nothing to create - every dependent already exists.", false));
                return;
            }

            int created, failed;
            double elapsed;
            RunBatched(jobs, taken, "dependents", null, out created, out failed, out elapsed);

            string msg = "Created " + created + " dependent view(s) in " + VmCore.PrettyTime(elapsed);
            if (skipped > 0) msg += "  -  " + skipped + " already existed";
            if (failed > 0) msg += "  -  " + failed + " failed";

            LogTimings(created, failed, elapsed);
            Log.Add("Result: created=" + created + ", skipped=" + skipped + ", failed=" + failed);

            BackOnUi(() =>
            {
                ReadModel();
                RebuildAll();
                Finish(msg + ".", failed > 0, failed > 0);
            });
        }

        private Func<List<string>, string> MakeDependentJob(View host, Element box, string target, HashSet<string> taken)
        {
            return added =>
            {
                string stage = "start";
                try
                {
                    stage = "Duplicate";
                    var clock = Stopwatch.StartNew();
                    ElementId madeId = host.Duplicate(ViewDuplicateOption.AsDependent);
                    var newView = Doc.GetElement(madeId) as View;
                    if (newView == null) throw new Exception("Duplicate returned nothing usable");
                    AddTiming("create", clock);

                    VmRevit.Quiet hidden = null;
                    if (fastMode)
                    {
                        stage = "hide links and worksets";
                        clock = Stopwatch.StartNew();
                        string ignore;
                        hidden = VmRevit.QuietenView(Doc, newView, out ignore);
                        AddTiming("quieten", clock);
                    }

                    stage = "scope box";
                    clock = Stopwatch.StartNew();
                    string boxNote;
                    bool okBox = VmRevit.ApplyScopeBox(newView, box.Id, false, out boxNote);
                    AddTiming("scopebox", clock);

                    if (hidden != null && (hidden.Worksets.Count > 0 || hidden.Categories.Count > 0))
                    {
                        stage = "restore worksets";
                        clock = Stopwatch.StartNew();
                        VmRevit.RestoreQuiet(newView, hidden);
                        AddTiming("restore", clock);
                    }

                    stage = "rename";
                    clock = Stopwatch.StartNew();
                    string final = VmCore.UniqueName(target, taken);
                    string nameNote;
                    bool okName = VmRevit.SetName(newView, final, out nameNote);
                    if (!okName)
                    {
                        final = VmCore.UniqueName(target + " 1", taken);
                        okName = VmRevit.SetName(newView, final, out nameNote);
                    }
                    AddTiming("name", clock);

                    taken.Add(final);
                    added.Add(final);

                    var note = new List<string>();
                    if (!okBox) note.Add("scope box: " + boxNote);
                    if (!okName) note.Add("name: " + nameNote);
                    return "OK    " + final + "  [" + VmRevit.Key(newView) + "]" + (note.Count > 0 ? "   WARN " + string.Join("; ", note) : "");
                }
                catch (Exception ex)
                {
                    throw new VmJobFailed("FAIL  " + target + "  at stage '" + stage + "'\n"
                        + "      host [" + VmRevit.Key(host) + "] " + host.Name + ", box [" + VmRevit.Key(box) + "] " + box.Name + "\n"
                        + "      " + VmCore.Describe(ex) + "\n      " + ex.ToString().Replace("\n", "\n      ").TrimEnd());
                }
            };
        }

        // ---------------------------------------------------------------- the batch runner --

        /// <summary>
        /// Many views per transaction, because a commit is a regeneration. A chunk Revit refuses is rolled back and replayed one
        /// at a time, so a single bad view is named and only that one is lost - the batch is not.
        /// </summary>
        private void RunBatched(List<Func<List<string>, string>> jobs, HashSet<string> taken, string label, Action after,
                                out int created, out int failed, out double elapsed)
        {
            timings.Clear();
            foreach (string k in new[] { "create", "name", "quieten", "scopebox", "template", "restore", "commit", "tags" }) timings[k] = 0;
            createdViewIds = new List<ElementId>();
            chunkViews = new List<ElementId>();
            tagStats = new VmRevit.TagStats();
            tagNote = null;
            created = 0;
            failed = 0;
            int total = jobs.Count;
            int index = 0;
            var runClock = Stopwatch.StartNew();

            VmRevit.SuppressDialogs(true);
            try
            {
                var tgroup = new TransactionGroup(Doc, "View Manager");
                tgroup.Start();
                try
                {
                    while (index < total)
                    {
                        List<Func<List<string>, string>> chunk = jobs.Skip(index).Take(VmCore.ChunkSize).ToList();
                        List<string> lines;
                        if (TryChunk(chunk, taken, out lines))
                        {
                            created += chunk.Count;
                            Log.AddRange(lines);
                        }
                        else
                        {
                            Log.Add("      chunk of " + chunk.Count + " refused - replaying one at a time");
                            foreach (var job in chunk)
                            {
                                List<string> linesOne;
                                if (TryChunk(new List<Func<List<string>, string>> { job }, taken, out linesOne)) created++;
                                else failed++;
                                Log.AddRange(linesOne);
                            }
                        }
                        index += chunk.Count;
                        // between chunks only - never with a transaction open
                        ReportProgress(index, total, label);
                    }
                    if (after != null)
                    {
                        // a tagging failure must not take the views down with it
                        try { after(); }
                        catch (Exception ex)
                        {
                            Log.Add("FAIL  after the views - " + VmCore.Describe(ex));
                            Log.Add(ex.ToString());
                        }
                    }
                    tgroup.Assimilate();
                }
                catch (Exception ex)
                {
                    if (tgroup.HasStarted()) tgroup.RollBack();
                    Log.Add("ABORTED: " + VmCore.Describe(ex));
                    Log.Add(ex.ToString());
                    throw;
                }
            }
            finally
            {
                VmRevit.SuppressDialogs(false);
            }
            elapsed = runClock.ElapsedMilliseconds;
        }

        /// <summary>Run a chunk in one transaction. Returns whether it committed, and the log lines.</summary>
        private bool TryChunk(List<Func<List<string>, string>> jobs, HashSet<string> taken, out List<string> lines)
        {
            lines = new List<string>();
            var added = new List<string>();
            chunkViews = new List<ElementId>();
            var t = new Transaction(Doc, "View Manager");
            t.Start();
            VmRevit.QuietOptions(t);
            try
            {
                foreach (var job in jobs) lines.Add(job(added));
                var clock = Stopwatch.StartNew();
                TransactionStatus status = t.Commit();
                AddTiming("commit", clock);
                if (status != TransactionStatus.Committed) throw new Exception("transaction status was " + status);
                // only views whose chunk committed are real enough to tag
                createdViewIds.AddRange(chunkViews);
                return true;
            }
            catch (Exception ex)
            {
                if (t.HasStarted())
                {
                    try { t.RollBack(); } catch (Exception) { }
                }
                // the rollback undid the views, so release the names they claimed
                foreach (string name in added) taken.Remove(name);
                string text = ex is VmJobFailed ? ex.Message : "FAIL  chunk\n      " + VmCore.Describe(ex);
                lines = jobs.Count == 1 ? new List<string> { text } : new List<string>();
                return false;
            }
            finally
            {
                t.Dispose();
            }
        }

        /// <summary>Tag the rooms each committed view cuts, a few views per transaction.</summary>
        private void TagNewViews(bool withLinks)
        {
            var clock = Stopwatch.StartNew();
            tagStats = new VmRevit.TagStats();
            tagNote = null;
            List<ElementId> ids = createdViewIds.ToList();
            Log.Add("");
            Log.Add("Room tags (" + ids.Count + " view(s), links " + (withLinks ? "included" : "left out") + "):");
            if (ids.Count == 0) return;

            string label, note;
            ElementId typeId = VmRevit.ResolveRoomTagType(Doc, out label, out note);
            if (typeId == null)
            {
                tagNote = string.IsNullOrEmpty(note) ? "no room tag loaded - nothing tagged" : note;
                Log.Add("  " + tagNote);
                return;
            }
            Log.Add("  tag: " + label);
            if (!string.IsNullOrEmpty(note)) Log.Add("  " + note);

            List<VmCore.RoomRecord> rooms = VmRevit.CollectRoomRecords(Doc, withLinks, Log);
            if (rooms.Count == 0)
            {
                tagNote = "no placed rooms found - nothing tagged";
                Log.Add("  " + tagNote);
                return;
            }

            int total = ids.Count;
            for (int start = 0; start < total; start += VmCore.TagViewsPerTransaction)
            {
                List<ElementId> chunk = ids.Skip(start).Take(VmCore.TagViewsPerTransaction).ToList();
                var lines = new List<string>();
                var t = new Transaction(Doc, "View Manager - room tags");
                t.Start();
                VmRevit.QuietOptions(t);
                try
                {
                    foreach (ElementId viewId in chunk)
                    {
                        var view = Doc.GetElement(viewId) as View;
                        if (view == null) continue;
                        int wanted;
                        int placed = VmRevit.TagRoomsInView(Doc, view, rooms, typeId, tagStats, out wanted);
                        lines.Add("  " + view.Name + ": " + placed + " of " + wanted + " room(s) tagged");
                    }
                    TransactionStatus status = t.Commit();
                    if (status != TransactionStatus.Committed) throw new Exception("transaction status was " + status);
                    Log.AddRange(lines);
                }
                catch (Exception ex)
                {
                    if (t.HasStarted())
                    {
                        try { t.RollBack(); } catch (Exception) { }
                    }
                    Log.Add("  FAIL  tagging " + chunk.Count + " view(s) - " + VmCore.Describe(ex));
                }
                finally
                {
                    t.Dispose();
                }
                ReportProgress(Math.Min(start + chunk.Count, total), total, "room tags");
            }

            if (!string.IsNullOrEmpty(tagStats.FirstRefusal))
                Log.Add("  first refusal: " + tagStats.FirstRefusal + "  (usually a template hiding Rooms)");
            timings["tags"] += clock.ElapsedMilliseconds;
        }

        private void LogTimings(int created, int failed, double elapsed)
        {
            Log.Add("");
            Log.Add("Timing: " + VmCore.PrettyTime(elapsed) + " total for " + created + " created, " + failed + " failed");
            foreach (string key in new[] { "create", "name", "quieten", "scopebox", "template", "restore", "commit", "tags" })
            {
                double value;
                if (timings.TryGetValue(key, out value) && value > 0) Log.Add("  " + key.PadRight(10) + " " + VmCore.PrettyTime(value));
            }
            if (created > 0) Log.Add("  " + "average".PadRight(10) + " " + VmCore.PrettyTime(elapsed / created) + " per view");
            Log.Add("  fast mode " + (fastMode ? "ON - links and worksets hidden while cropping" : "off"));
            Log.Add("  chunk size " + VmCore.ChunkSize + ", " + ((created + failed + VmCore.ChunkSize - 1) / Math.Max(VmCore.ChunkSize, 1)) + " transaction(s)");
            Log.Add("");
        }

        private void ReportProgress(int done, int total, string label)
        {
            Action paint = () =>
            {
                try
                {
                    double fraction = total > 0 ? (double)done / total : 0.0;
                    double width = progTrack.ActualWidth * fraction;
                    progFill.Width = width > 0 ? width : 0;
                    SetStatus("Creating " + label + "...  " + done + " of " + total);
                }
                catch (Exception) { }
            };
            try { Window.Dispatcher.Invoke(DispatcherPriority.Background, paint); }
            catch (Exception) { paint(); }
        }
    }
}
