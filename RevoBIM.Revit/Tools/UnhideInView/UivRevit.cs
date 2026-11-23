using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;

namespace RevoBIM.Tools.UnhideInView
{
    /// <summary>
    /// Unhide in View - everything that reads or writes the Revit model (port of uiv_revit.py). Runs only inside an
    /// ExternalEvent, never straight from a window handler. ElementIds are read as long through .Value and kept as the
    /// objects Revit handed over.
    /// </summary>
    public static class UivRevit
    {
        // ---------------------------------------------------------------- small helpers --

        public static long Key(ElementId id)
        {
            return id == null ? 0 : id.Value;
        }

        public static bool Valid(ElementId id)
        {
            return id != null && id.Value > 0;
        }

        public static string SafeName(Element element)
        {
            if (element == null) return "";
            try { return element.Name ?? ""; } catch (Exception) { return ""; }
        }

        public static bool DocAlive(Document doc)
        {
            try { return doc != null && doc.IsValidObject; } catch (Exception) { return false; }
        }

        public static bool SameDoc(Document a, Document b)
        {
            try { return a != null && b != null && a.Equals(b); } catch (Exception) { return false; }
        }

        // ---------------------------------------------------------------- views --

        public static List<UivView> ReadViews(Document doc, UivCore.DebugLog log)
        {
            var output = new List<UivView>();
            int skipped = 0;
            foreach (View v in new FilteredElementCollector(doc).OfClass(typeof(View)).Cast<View>())
            {
                try
                {
                    string vt = v.ViewType.ToString();
                    if (!UivCore.ViewIsListed(vt, v.IsTemplate))
                    {
                        skipped++;
                        continue;
                    }
                    string sheetNo = null;
                    if (vt == "DrawingSheet")
                    {
                        var sheet = v as ViewSheet;
                        if (sheet != null) sheetNo = sheet.SheetNumber;
                    }
                    ElementId tid = v.ViewTemplateId;
                    long? tkey = null;
                    string tname = "";
                    if (Valid(tid))
                    {
                        Element t = doc.GetElement(tid);
                        if (t != null)
                        {
                            tkey = Key(tid);
                            tname = SafeName(t);
                        }
                    }
                    output.Add(new UivView
                    {
                        Key = Key(v.Id),
                        View = v,
                        Name = UivCore.ViewDisplayName(SafeName(v), sheetNo),
                        Type = UivCore.ViewTypeLabel(vt),
                        TemplateKey = tkey,
                        TemplateId = tkey != null ? tid : null,
                        TemplateName = tname,
                    });
                }
                catch (Exception err)
                {
                    log.Add("read_views: skipped a view - " + err.Message);
                }
            }
            log.Add("Views listed: " + output.Count + " (" + skipped + " schedules, templates and browsers left out)");
            return output;
        }

        public static long? ActiveViewKey(UIDocument uidoc)
        {
            try
            {
                return uidoc.ActiveView == null ? (long?)null : Key(uidoc.ActiveView.Id);
            }
            catch (Exception)
            {
                return null;
            }
        }

        // ---------------------------------------------------------------- candidates for the scan --

        /// <summary>Model and annotation categories. Internal and analytical ones hold nothing a person hides.</summary>
        public static List<ElementId> CandidateCategoryIds(Document doc)
        {
            var ids = new List<ElementId>();
            foreach (Category cat in doc.Settings.Categories)
            {
                try
                {
                    if (cat.CategoryType == CategoryType.Model || cat.CategoryType == CategoryType.Annotation) ids.Add(cat.Id);
                }
                catch (Exception)
                {
                }
            }
            return ids;
        }

        /// <summary>Every element that is not view-specific, not a type and not a view.</summary>
        private static IList<Element> ModelCandidates(Document doc, List<ElementId> catIds)
        {
            return new FilteredElementCollector(doc)
                .WhereElementIsNotElementType()
                .WherePasses(new ElementMulticategoryFilter(catIds))
                .WherePasses(new ElementOwnerViewFilter(ElementId.InvalidElementId))
                .WherePasses(new ElementClassFilter(typeof(View), true))
                .ToElements();
        }

        /// <summary>View-specific elements can only be hidden in the view that owns them.</summary>
        private static IList<Element> OwnedCandidates(Document doc, ElementId viewId, List<ElementId> catIds)
        {
            return new FilteredElementCollector(doc)
                .WherePasses(new ElementOwnerViewFilter(viewId))
                .WhereElementIsNotElementType()
                .WherePasses(new ElementMulticategoryFilter(catIds))
                .ToElements();
        }

        public static UivScanner MakeScanner(Document doc, List<UivView> views, List<ElementId> catIds, UivCore.DebugLog log)
        {
            var timer = Stopwatch.StartNew();
            IList<Element> model = ModelCandidates(doc, catIds);
            log.Add("Scan candidates: " + model.Count + " model elements read in " + timer.Elapsed.TotalSeconds.ToString("0.00") + "s");
            var byKey = views.ToDictionary(v => v.Key, v => v.View);

            Func<long, List<IList<Element>>> segments = vk =>
            {
                View view;
                if (!byKey.TryGetValue(vk, out view)) return new List<IList<Element>>();
                return new List<IList<Element>> { model, OwnedCandidates(doc, view.Id, catIds) };
            };
            Func<Element, long, bool> hidden = (item, vk) => item.IsHidden(byKey[vk]);
            return new UivScanner(views.Select(v => v.Key), segments, hidden);
        }

        // ---------------------------------------------------------------- rows for the hidden elements table --

        private static string FamilyTypeText(Document doc, Element elem)
        {
            string fam = "", typ = "";
            try
            {
                ElementId tid = elem.GetTypeId();
                if (Valid(tid))
                {
                    Element t = doc.GetElement(tid);
                    if (t != null)
                    {
                        typ = SafeName(t);
                        var symbol = t as ElementType;
                        if (symbol != null)
                        {
                            try { fam = symbol.FamilyName ?? ""; } catch (Exception) { fam = ""; }
                        }
                    }
                }
            }
            catch (Exception)
            {
            }
            if (typ.Length == 0) typ = SafeName(elem);
            if (fam.Length > 0 && typ.Length > 0 && fam != typ) return fam + " : " + typ;
            return typ.Length > 0 ? typ : fam;
        }

        private static string LevelText(Document doc, Element elem)
        {
            try
            {
                if (Valid(elem.LevelId)) return SafeName(doc.GetElement(elem.LevelId));
            }
            catch (Exception)
            {
            }
            try
            {
                // pipes, ducts and cable trays keep their level in a parameter
                var curve = elem as Autodesk.Revit.DB.MEPCurve;
                if (curve != null && curve.ReferenceLevel != null) return SafeName(curve.ReferenceLevel);
            }
            catch (Exception)
            {
            }
            try
            {
                if (Valid(elem.OwnerViewId)) return "(view-specific)";
            }
            catch (Exception)
            {
            }
            return "";
        }

        /// <summary>One row of the left table. The note says when the element's category is hidden in the view too.</summary>
        public static UivElementRow ElementRow(Document doc, ElementId eid, View view, Dictionary<long, bool> catHiddenCache)
        {
            long key = Key(eid);
            var row = new UivElementRow { Key = key, IdText = key.ToString() };
            Element elem = doc.GetElement(eid);
            if (elem == null)
            {
                row.Category = "(deleted)";
                row.Note = "No longer in the model";
                row.Bad = true;
                return row;
            }
            Category cat = null;
            try { cat = elem.Category; } catch (Exception) { }
            if (cat != null) row.Category = cat.Name ?? "";
            row.FamilyType = FamilyTypeText(doc, elem);
            row.Level = LevelText(doc, elem);
            if (cat != null)
            {
                long ck = Key(cat.Id);
                bool hidden;
                if (!catHiddenCache.TryGetValue(ck, out hidden))
                {
                    hidden = false;
                    try
                    {
                        if (view.CanCategoryBeHidden(cat.Id)) hidden = view.GetCategoryHidden(cat.Id);
                    }
                    catch (Exception)
                    {
                        hidden = false;
                    }
                    catHiddenCache[ck] = hidden;
                }
                if (hidden)
                {
                    row.Note = "Category hidden here too";
                    row.Warn = true;
                }
            }
            return row;
        }

        // ---------------------------------------------------------------- categories hidden in a view --

        /// <summary>Model and annotation categories, parents before their subcategories.</summary>
        public static List<UivCategory> AllCategories(Document doc)
        {
            var output = new List<UivCategory>();
            foreach (Category cat in doc.Settings.Categories)
            {
                try
                {
                    bool model = cat.CategoryType == CategoryType.Model;
                    if (!model && cat.CategoryType != CategoryType.Annotation) continue;
                    string pname = cat.Name ?? "";
                    output.Add(new UivCategory { Key = Key(cat.Id), Category = cat, Name = pname, IsModel = model });
                    try
                    {
                        foreach (Category sub in cat.SubCategories)
                            output.Add(new UivCategory { Key = Key(sub.Id), Category = sub, Name = pname + " : " + sub.Name, IsModel = model, Parent = Key(cat.Id) });
                    }
                    catch (Exception)
                    {
                    }
                }
                catch (Exception)
                {
                }
            }
            return output;
        }

        private static bool ControlsParameter(HashSet<long> free, string builtIn)
        {
            BuiltInParameter p;
            if (!Enum.TryParse(builtIn, out p)) return true;     // cannot tell: treat as controlled
            try { return !free.Contains(new ElementId(p).Value); } catch (Exception) { return true; }
        }

        /// <summary>The view template and whether it controls Model / Annotation categories V/G.</summary>
        private static View TemplateControl(Document doc, View view, out string name, out bool model, out bool annotation)
        {
            name = "";
            model = annotation = false;
            ElementId tid = view.ViewTemplateId;
            if (!Valid(tid)) return null;
            var t = doc.GetElement(tid) as View;
            if (t == null) return null;
            var free = new HashSet<long>();
            try
            {
                foreach (ElementId id in t.GetNonControlledTemplateParameterIds()) free.Add(Key(id));
            }
            catch (Exception)
            {
            }
            name = SafeName(t);
            model = ControlsParameter(free, "VIS_GRAPHICS_MODEL");
            annotation = ControlsParameter(free, "VIS_GRAPHICS_ANNOTATION");
            return t;
        }

        /// <summary>
        /// The categories hidden in the view (with the template name when a template decides it). A subcategory is
        /// left out when its parent is hidden - unhiding the parent is the action that matters.
        /// </summary>
        public static Dictionary<long, UivCatState> ReadCategoryState(Document doc, View view, List<UivCategory> cats)
        {
            string tname;
            bool cm, ca;
            View t = TemplateControl(doc, view, out tname, out cm, out ca);
            var state = new Dictionary<long, UivCatState>();
            var hiddenParents = new HashSet<long>();
            foreach (UivCategory c in cats)
            {
                bool controlled = c.IsModel ? cm : ca;
                View src = controlled && t != null ? t : view;
                bool hidden;
                try
                {
                    if (!view.CanCategoryBeHidden(c.Category.Id)) continue;
                    hidden = src.GetCategoryHidden(c.Category.Id);
                }
                catch (Exception)
                {
                    continue;
                }
                if (!hidden) continue;
                if (c.Parent == null) hiddenParents.Add(c.Key);
                else if (hiddenParents.Contains(c.Parent.Value)) continue;
                state[c.Key] = new UivCatState { ControlledBy = controlled && t != null ? tname : null };
            }
            return state;
        }

        // ---------------------------------------------------------------- writing --

        /// <summary>Deletes warnings; keeps the text of anything worse so the row can say what Revit said.</summary>
        private sealed class Quiet : IFailuresPreprocessor
        {
            private readonly UivCore.DebugLog log;
            public readonly List<string> Errors = new List<string>();

            public Quiet(UivCore.DebugLog log) { this.log = log; }

            public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
            {
                try
                {
                    foreach (FailureMessageAccessor f in accessor.GetFailureMessages())
                    {
                        string sev = f.GetSeverity().ToString();
                        string text = "";
                        try { text = f.GetDescriptionText(); } catch (Exception) { }
                        if (sev == "Warning")
                        {
                            accessor.DeleteWarning(f);
                            log.Add("  warning removed: " + text);
                        }
                        else
                        {
                            Errors.Add(text);
                            log.Add("  Revit " + sev + ": " + text);
                        }
                    }
                }
                catch (Exception err)
                {
                    log.Add("  failure preprocessor: " + err.Message);
                }
                return FailureProcessingResult.Continue;
            }
        }

        private static Transaction NewTransaction(Document doc, string name, UivCore.DebugLog log, out Quiet quiet)
        {
            var t = new Transaction(doc, name);
            quiet = new Quiet(log);
            try
            {
                FailureHandlingOptions options = t.GetFailureHandlingOptions();
                options.SetFailuresPreprocessor(quiet);
                options.SetClearAfterRollback(true);
                t.SetFailureHandlingOptions(options);
            }
            catch (Exception)
            {
            }
            return t;
        }

        /// <summary>Checks out the views (and templates) the run writes to. Returns the keys refused, with the reason.</summary>
        private static Dictionary<long, string> Borrow(Document doc, List<ElementId> ids, UivCore.DebugLog log)
        {
            var refused = new Dictionary<long, string>();
            if (ids.Count == 0) return refused;
            bool workshared;
            try { workshared = doc.IsWorkshared; } catch (Exception) { workshared = false; }
            if (!workshared) return refused;
            var held = new HashSet<long>();
            try
            {
                foreach (ElementId id in WorksharingUtils.CheckoutElements(doc, ids)) held.Add(Key(id));
            }
            catch (Exception err)
            {
                log.Add("CheckoutElements failed: " + err.Message);
            }
            foreach (ElementId id in ids)
            {
                long k = Key(id);
                if (held.Contains(k)) continue;
                string owner = "";
                try { owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, id).Owner ?? ""; } catch (Exception) { }
                refused[k] = owner.Length > 0 ? "Held by " + owner : "Could not be borrowed";
                log.Add("  not borrowed " + k + ": " + refused[k]);
            }
            return refused;
        }

        /// <summary>All at once; on a refusal, one at a time so one bad element does not lose the rest.</summary>
        private static Dictionary<long, string> UnhideBatch(Document doc, View view, List<ElementId> ids, UivCore.DebugLog log)
        {
            var refused = new Dictionary<long, string>();
            Quiet quiet;
            using (Transaction t = NewTransaction(doc, "RevoBIM Unhide elements", log, out quiet))
            {
                t.Start();
                try
                {
                    view.UnhideElements(ids);
                    TransactionStatus status = t.Commit();
                    if (status == TransactionStatus.Committed) return refused;
                    log.Add("  batch did not commit (" + status + ") - one at a time");
                }
                catch (Exception err)
                {
                    log.Add("  batch refused: " + err.Message + " - one at a time");
                    try { if (t.HasStarted()) t.RollBack(); } catch (Exception) { }
                }
            }
            foreach (ElementId id in ids)
            {
                long k = Key(id);
                Quiet q;
                using (Transaction t1 = NewTransaction(doc, "RevoBIM Unhide element", log, out q))
                {
                    t1.Start();
                    try
                    {
                        view.UnhideElements(new List<ElementId> { id });
                        if (t1.Commit() != TransactionStatus.Committed)
                            refused[k] = "Refused by Revit" + (q.Errors.Count > 0 ? ": " + q.Errors[0] : "");
                    }
                    catch (Exception err)
                    {
                        try { if (t1.HasStarted()) t1.RollBack(); } catch (Exception) { }
                        refused[k] = "Refused: " + err.Message;
                    }
                }
            }
            return refused;
        }

        /// <summary>
        /// Carries out a plan. Everything sits in one TransactionGroup (one undo step), one transaction per view so a
        /// refusal stays local, and nothing is counted until it reads back after the group has closed.
        /// </summary>
        public static UivResult RunUnhide(Document doc, UivPlan plan, Func<long, View> viewOf, Func<long, bool, View> ownerOf,
            Func<long, long, ElementId> eidOf, Func<long, ElementId> catIdOf, UIApplication uiapp, UivCore.DebugLog log)
        {
            var result = new UivResult();
            result.Skipped.AddRange(plan.Skipped);

            var ownerIds = new List<ElementId>();
            var seen = new HashSet<long>();
            foreach (UivPlanElements pe in plan.Elements)
            {
                View v = viewOf(pe.View);
                if (v != null && seen.Add(Key(v.Id))) ownerIds.Add(v.Id);
            }
            foreach (UivPlanCategories pc in plan.Categories)
            {
                View o = ownerOf(pc.Owner, pc.IsTemplate);
                if (o != null && seen.Add(Key(o.Id))) ownerIds.Add(o.Id);
            }
            Dictionary<long, string> notHeld = Borrow(doc, ownerIds, log);

            // Revit may raise a dialog about the edit; answer it so the run is not left waiting on one
            EventHandler<DialogBoxShowingEventArgs> onDialog = (sender, args) =>
            {
                try
                {
                    string id = "";
                    try
                    {
                        object value = args.GetType().GetProperty("DialogId")?.GetValue(args, null);
                        id = value == null ? "" : value.ToString();
                    }
                    catch (Exception) { }
                    args.OverrideResult(1);
                    log.Add("  dialog suppressed: " + id);
                }
                catch (Exception)
                {
                }
            };
            bool hooked = false;
            try
            {
                uiapp.DialogBoxShowing += onDialog;
                hooked = true;
            }
            catch (Exception err)
            {
                log.Add("DialogBoxShowing could not be hooked: " + err.Message);
            }

            using (var tg = new TransactionGroup(doc, "RevoBIM Unhide in View"))
            {
                tg.Start();
                try
                {
                    foreach (UivPlanElements pe in plan.Elements)
                    {
                        View view = viewOf(pe.View);
                        if (view == null)
                        {
                            foreach (long ek in pe.Elements) Refuse(result, "element", pe.View, ek, "View not found");
                            continue;
                        }
                        string why;
                        if (notHeld.TryGetValue(pe.View, out why))
                        {
                            foreach (long ek in pe.Elements) Refuse(result, "element", pe.View, ek, why);
                            continue;
                        }
                        var ids = new List<ElementId>();
                        foreach (long ek in pe.Elements)
                        {
                            ElementId i = eidOf(pe.View, ek);
                            if (i == null || doc.GetElement(i) == null)
                            {
                                Refuse(result, "element", pe.View, ek, "No longer in the model");
                                continue;
                            }
                            ids.Add(i);
                        }
                        if (ids.Count == 0) continue;
                        log.Add("Unhide " + ids.Count + " in view " + pe.View);
                        foreach (KeyValuePair<long, string> r in UnhideBatch(doc, view, ids, log))
                            Refuse(result, "element", pe.View, r.Key, r.Value);
                    }

                    foreach (UivPlanCategories pc in plan.Categories)
                    {
                        View owner = ownerOf(pc.Owner, pc.IsTemplate);
                        string label = pc.IsTemplate ? "template" : "view";
                        if (owner == null)
                        {
                            foreach (long ck in pc.Categories) Refuse(result, "category", pc.Owner, ck, label + " not found");
                            continue;
                        }
                        string why;
                        if (notHeld.TryGetValue(pc.Owner, out why))
                        {
                            foreach (long ck in pc.Categories) Refuse(result, "category", pc.Owner, ck, why);
                            continue;
                        }
                        log.Add("Unhide " + pc.Categories.Count + " categories on " + label + " " + pc.Owner);
                        Quiet quiet;
                        var failed = new Dictionary<long, string>();
                        using (Transaction t = NewTransaction(doc, "RevoBIM Unhide categories", log, out quiet))
                        {
                            t.Start();
                            try
                            {
                                foreach (long ck in pc.Categories)
                                {
                                    try { owner.SetCategoryHidden(catIdOf(ck), false); }
                                    catch (Exception err) { failed[ck] = "Refused: " + err.Message; }
                                }
                                if (t.Commit() != TransactionStatus.Committed)
                                    foreach (long ck in pc.Categories)
                                        if (!failed.ContainsKey(ck)) failed[ck] = "Refused by Revit" + (quiet.Errors.Count > 0 ? ": " + quiet.Errors[0] : "");
                            }
                            catch (Exception err)
                            {
                                try { if (t.HasStarted()) t.RollBack(); } catch (Exception) { }
                                foreach (long ck in pc.Categories)
                                    if (!failed.ContainsKey(ck)) failed[ck] = "Refused: " + err.Message;
                            }
                        }
                        foreach (KeyValuePair<long, string> f in failed) Refuse(result, "category", pc.Owner, f.Key, f.Value);
                    }
                    tg.Assimilate();
                }
                catch (Exception err)
                {
                    log.Add("Unhide run failed, rolled back: " + err);
                    try { if (tg.HasStarted()) tg.RollBack(); } catch (Exception) { }
                    Refuse(result, "run", 0, 0, "The run failed and was rolled back - see the debug log");
                }
                finally
                {
                    if (hooked)
                    {
                        try { uiapp.DialogBoxShowing -= onDialog; } catch (Exception) { }
                    }
                }
            }

            // ---- read back, after the group has closed ------------------------------------------------
            var refusedKeys = new HashSet<string>(result.Refused.Select(r => r.Kind + ":" + r.Owner + ":" + r.Key));
            var viewsOk = new HashSet<long>();
            foreach (UivPlanElements pe in plan.Elements)
            {
                View view = viewOf(pe.View);
                foreach (long ek in pe.Elements)
                {
                    if (refusedKeys.Contains("element:" + pe.View + ":" + ek)) continue;
                    ElementId i = eidOf(pe.View, ek);
                    Element elem = i != null ? doc.GetElement(i) : null;
                    bool still;
                    try { still = elem == null || elem.IsHidden(view); } catch (Exception) { still = true; }
                    if (still)
                    {
                        Refuse(result, "element", pe.View, ek, "Still hidden after the run");
                        continue;
                    }
                    result.OkElements.Add(new KeyValuePair<long, long>(pe.View, ek));
                    viewsOk.Add(pe.View);
                }
            }
            var ownersOk = new HashSet<string>();
            foreach (UivPlanCategories pc in plan.Categories)
            {
                View owner = ownerOf(pc.Owner, pc.IsTemplate);
                var okCats = new UivPlanCategories { Owner = pc.Owner, IsTemplate = pc.IsTemplate };
                foreach (long ck in pc.Categories)
                {
                    if (refusedKeys.Contains("category:" + pc.Owner + ":" + ck)) continue;
                    bool still;
                    try { still = owner.GetCategoryHidden(catIdOf(ck)); } catch (Exception) { still = true; }
                    if (still)
                    {
                        Refuse(result, "category", pc.Owner, ck, "Still hidden after the run");
                        continue;
                    }
                    okCats.Categories.Add(ck);
                    ownersOk.Add((pc.IsTemplate ? "T" : "V") + pc.Owner);
                }
                if (okCats.Categories.Count > 0) result.OkCategories.Add(okCats);
            }
            result.ElementsOk = result.OkElements.Count;
            result.ElementViews = viewsOk.Count;
            result.CategoriesOk = result.OkCategories.Sum(c => c.Categories.Count);
            result.CategoryOwners = ownersOk.Count;
            log.Add("Read back: " + result.ElementsOk + " elements in " + result.ElementViews + " views, " + result.CategoriesOk +
                    " categories on " + result.CategoryOwners + " owners, " + result.Refused.Count + " refused");
            return result;
        }

        private static void Refuse(UivResult result, string kind, long owner, long key, string reason)
        {
            result.Refused.Add(new UivSkip { Kind = kind, Owner = owner, Key = key, Reason = reason });
        }

        // ---------------------------------------------------------------- showing things in Revit --

        public static bool ActivateView(UIDocument uidoc, View view, UivCore.DebugLog log)
        {
            try
            {
                if (uidoc.ActiveView != null && Key(uidoc.ActiveView.Id) == Key(view.Id)) return true;
            }
            catch (Exception)
            {
            }
            try
            {
                uidoc.ActiveView = view;
                return true;
            }
            catch (Exception err)
            {
                log.Add("ActiveView refused, requesting change: " + err.Message);
            }
            try
            {
                uidoc.RequestViewChange(view);
                return true;
            }
            catch (Exception err)
            {
                log.Add("RequestViewChange refused: " + err.Message);
                return false;
            }
        }

        public static bool SelectIds(UIDocument uidoc, List<ElementId> ids, UivCore.DebugLog log)
        {
            try
            {
                uidoc.Selection.SetElementIds(ids);
                return true;
            }
            catch (Exception err)
            {
                log.Add("Selection refused: " + err.Message);
                return false;
            }
        }
    }
}
