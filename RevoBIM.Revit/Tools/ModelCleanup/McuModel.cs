using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.ModelCleanup
{
    /// <summary>What the sheet and view stages will delete, worked out before any of it runs.</summary>
    public sealed class McuPlan
    {
        public List<McuSheetItem> Sheets = new List<McuSheetItem>();
        public List<McuViewItem> Views = new List<McuViewItem>();
        public HashSet<long> Placed = new HashSet<long>();
        public Dictionary<string, List<long>> Doomed = new Dictionary<string, List<long>>();
        public Dictionary<long, string> Decisions = new Dictionary<long, string>();
        public HashSet<string> RetainedViews = new HashSet<string>();
        public HashSet<string> RetainedSheets = new HashSet<string>();
    }

    public sealed class McuPurgeScan
    {
        public bool Ok;
        public string Reason = "";
        public List<(long Id, string Name, string Group, string Status)> Rows = new List<(long, string, string, string)>();
        public List<(long Id, string Group)> Unused = new List<(long, string)>();
        public List<(long Id, string Group)> Used = new List<(long, string)>();
    }

    public sealed class McuCounts
    {
        public Dictionary<string, int> Counts = new Dictionary<string, int>();
        public List<string> Kept = new List<string>();
    }

    /// <summary>
    /// Reading the model. Nothing in here writes. Every function takes the document it reads, so the same
    /// code counts the live model (for the preview) and the saved copy (for the real run). Port of mcu_model.py.
    /// </summary>
    public static class McuModel
    {
        public static long Eid(ElementId id)
        {
            return id == null ? 0 : id.Value;
        }

        public static ElementId ToElementId(long value)
        {
            return new ElementId(value);
        }

        public static string ElementName(Element element)
        {
            if (element == null) return "";
            try { return element.Name ?? ""; }
            catch (Exception) { return ""; }
        }

        public static string ClassName(Element element)
        {
            try { return element.GetType().Name; }
            catch (Exception) { return ""; }
        }

        public static string CategoryName(Element element)
        {
            try
            {
                Category category = element is Family ? ((Family)element).FamilyCategory : element.Category;
                if (category != null) return category.Name ?? "";
            }
            catch (Exception) { }
            return "";
        }

        public static string DisplayName(Element element)
        {
            string name = ElementName(element);
            try
            {
                var symbol = element as ElementType;
                string family = symbol == null ? null : symbol.FamilyName;
                if (!string.IsNullOrEmpty(family) && family != name) return family + " : " + name;
            }
            catch (Exception) { }
            return name;
        }

        public static string ModelTitle(Document doc)
        {
            try { return doc.Title ?? ""; }
            catch (Exception) { return ""; }
        }

        // ============================================================
        // model identity
        // ============================================================

        public static bool IsCloud(Document doc)
        {
            try { return doc.IsModelInCloud; }
            catch (Exception) { return false; }
        }

        /// <summary>ModelPath of the central (or cloud) model, else null.</summary>
        public static ModelPath CentralPath(Document doc)
        {
            if (!doc.IsWorkshared) return null;
            if (IsCloud(doc))
            {
                try { return doc.GetCloudModelPath(); }
                catch (Exception) { }
            }
            try { return doc.GetWorksharingCentralModelPath(); }
            catch (Exception) { return null; }
        }

        public static string VisiblePath(ModelPath modelPath)
        {
            if (modelPath == null) return "";
            try { return ModelPathUtils.ConvertModelPathToUserVisiblePath(modelPath) ?? ""; }
            catch (Exception) { return ""; }
        }

        /// <summary>Two handles on the same open model.</summary>
        public static bool SameDocument(Document first, Document second)
        {
            if (first == null || second == null) return false;
            try
            {
                if (first.Equals(second)) return true;
            }
            catch (Exception) { }
            try
            {
                return first.PathName == second.PathName && first.Title == second.Title;
            }
            catch (Exception) { return false; }
        }

        public static McuModelInfo Describe(Document doc)
        {
            return new McuModelInfo
            {
                Title = ModelTitle(doc),
                Path = doc.PathName ?? "",
                Workshared = doc.IsWorkshared,
                Cloud = IsCloud(doc),
                Central = VisiblePath(CentralPath(doc)),
            };
        }

        // ============================================================
        // views, sheets, schedules
        // ============================================================

        /// <summary>Views placed on a sheet. With sheetIds, only placements on those sheets count.</summary>
        public static HashSet<long> OnSheetIds(Document doc, ICollection<long> sheetIds = null)
        {
            var ids = new HashSet<long>();
            foreach (Viewport viewport in new FilteredElementCollector(doc).OfClass(typeof(Viewport)))
            {
                try
                {
                    if (sheetIds != null && !sheetIds.Contains(Eid(viewport.SheetId))) continue;
                    ids.Add(Eid(viewport.ViewId));
                }
                catch (Exception) { }
            }
            foreach (ScheduleSheetInstance instance in new FilteredElementCollector(doc).OfClass(typeof(ScheduleSheetInstance)))
            {
                try
                {
                    if (sheetIds != null && !sheetIds.Contains(Eid(instance.OwnerViewId))) continue;
                    ids.Add(Eid(instance.ScheduleId));
                }
                catch (Exception) { }
            }
            return ids;
        }

        public static List<McuSheetItem> ReadSheets(Document doc)
        {
            var output = new List<McuSheetItem>();
            foreach (ViewSheet sheet in new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)))
            {
                try
                {
                    if (sheet.IsTemplate) continue;
                    bool placeholder = false;
                    try { placeholder = sheet.IsPlaceholder; } catch (Exception) { }
                    output.Add(new McuSheetItem
                    {
                        Id = Eid(sheet.Id), Number = sheet.SheetNumber ?? "", Name = ElementName(sheet), Placeholder = placeholder,
                    });
                }
                catch (Exception) { }
            }
            return output;
        }

        // ============================================================
        // the project browser organisation
        // ============================================================

        /// <summary>The organisation the browser is using now, or null (grouping by type then).</summary>
        public static BrowserOrganization BrowserOrg(Document doc, bool sheets)
        {
            try
            {
                return sheets ? BrowserOrganization.GetCurrentBrowserOrganizationForSheets(doc)
                              : BrowserOrganization.GetCurrentBrowserOrganizationForViews(doc);
            }
            catch (Exception) { return null; }
        }

        public static List<string> BrowserFolders(BrowserOrganization organisation, ElementId id)
        {
            if (organisation == null) return new List<string>();
            try { return organisation.GetFolderItems(id).Select(info => info.Name ?? "").ToList(); }
            catch (Exception) { return new List<string>(); }
        }

        public static string OrganisationName(BrowserOrganization organisation)
        {
            return organisation != null ? ElementName(organisation) : "type only";
        }

        /// <summary>Every view, schedule and legend someone might keep, grouped the way the browser shows them.</summary>
        public static (List<McuRetainItem> Items, string Organisation) ViewRetainItems(Document doc)
        {
            BrowserOrganization organisation = BrowserOrg(doc, false);
            var names = new Dictionary<long, string>();
            var views = new List<(View View, string Kind)>();
            foreach (View view in new FilteredElementCollector(doc).OfClass(typeof(View)))
            {
                try
                {
                    if (view.IsTemplate || view is ViewSheet) continue;
                    string kind = view.ViewType.ToString();
                    if (!McuCore.ViewTypeLabels.ContainsKey(kind)) continue;
                    if (view is ViewSchedule && IsInternalSchedule((ViewSchedule)view)) continue;
                    names[Eid(view.Id)] = ElementName(view);
                    views.Add((view, kind));
                }
                catch (Exception) { }
            }
            var items = new List<McuRetainItem>();
            foreach (var entry in views)
            {
                View view = entry.View;
                string name;
                names.TryGetValue(Eid(view.Id), out name);
                name = name ?? "";
                string label = name;
                try
                {
                    long parent = Eid(view.GetPrimaryViewId());
                    if (parent > 0)
                    {
                        string parentName;
                        label = name + "   (dependent of " + (names.TryGetValue(parent, out parentName) ? parentName : "?") + ")";
                    }
                }
                catch (Exception) { }
                items.Add(new McuRetainItem
                {
                    Key = McuCore.ViewKey(entry.Kind, name), Label = label, Id = Eid(view.Id),
                    Folders = McuCore.ViewFolders(BrowserFolders(organisation, view.Id), entry.Kind),
                });
            }
            return (items, OrganisationName(organisation));
        }

        public static (List<McuRetainItem> Items, string Organisation) SheetRetainItems(Document doc)
        {
            BrowserOrganization organisation = BrowserOrg(doc, true);
            var items = new List<McuRetainItem>();
            foreach (ViewSheet sheet in new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)))
            {
                try
                {
                    if (sheet.IsTemplate) continue;
                    string number = sheet.SheetNumber ?? "";
                    string label = number + " - " + ElementName(sheet);
                    bool placeholder = false;
                    try { placeholder = sheet.IsPlaceholder; } catch (Exception) { }
                    if (placeholder) label += "   (placeholder)";
                    items.Add(new McuRetainItem
                    {
                        Key = number, Label = label, Id = Eid(sheet.Id),
                        Folders = McuCore.SheetFolders(BrowserFolders(organisation, sheet.Id)),
                    });
                }
                catch (Exception) { }
            }
            return (items, OrganisationName(organisation));
        }

        public static long StartingViewId(Document doc)
        {
            try { return Eid(StartingViewSettings.GetStartingViewSettings(doc).ViewId); }
            catch (Exception) { return 0; }
        }

        private static bool IsInternalSchedule(ViewSchedule view)
        {
            try { if (view.IsTitleblockRevisionSchedule) return true; } catch (Exception) { }
            try { if (view.IsInternalKeynoteSchedule) return true; } catch (Exception) { }
            return false;
        }

        public static List<McuViewItem> ReadViews(Document doc)
        {
            var items = new List<McuViewItem>();
            foreach (View view in new FilteredElementCollector(doc).OfClass(typeof(View)))
            {
                try
                {
                    if (view is ViewSheet) continue;
                    long parent = 0;
                    try
                    {
                        parent = Eid(view.GetPrimaryViewId());
                        if (parent < 0) parent = 0;
                    }
                    catch (Exception) { parent = 0; }
                    bool isInternal = view is ViewSchedule && IsInternalSchedule((ViewSchedule)view);
                    items.Add(new McuViewItem
                    {
                        Id = Eid(view.Id), Name = ElementName(view), Kind = view.ViewType.ToString(),
                        Template = view.IsTemplate, Parent = parent, Internal = isInternal,
                    });
                }
                catch (Exception) { }
            }
            return items;
        }

        /// <summary>ignore: view ids that are going anyway, so their templates count as unused.</summary>
        public static (List<long> Templates, HashSet<long> Used, HashSet<long> Defaults) TemplateUsage(Document doc, ICollection<long> ignore = null)
        {
            var templates = new List<long>();
            var used = new HashSet<long>();
            var defaults = new HashSet<long>();
            foreach (View view in new FilteredElementCollector(doc).OfClass(typeof(View)))
            {
                try
                {
                    if (view.IsTemplate) templates.Add(Eid(view.Id));
                    else if (ignore == null || !ignore.Contains(Eid(view.Id)))
                    {
                        long value = Eid(view.ViewTemplateId);
                        if (value > 0) used.Add(value);
                    }
                }
                catch (Exception) { }
            }
            foreach (ViewFamilyType familyType in new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)))
            {
                try
                {
                    long value = Eid(familyType.DefaultTemplateId);
                    if (value > 0) defaults.Add(value);
                }
                catch (Exception) { }
            }
            return (templates, used, defaults);
        }

        public static (List<long> Filters, HashSet<long> Used) FilterUsage(Document doc, ICollection<long> ignore = null)
        {
            var filters = new FilteredElementCollector(doc).OfClass(typeof(ParameterFilterElement)).Select(e => Eid(e.Id)).ToList();
            var used = new HashSet<long>();
            foreach (View view in new FilteredElementCollector(doc).OfClass(typeof(View)))
            {
                if (ignore != null && ignore.Contains(Eid(view.Id))) continue;
                try { if (!view.AreGraphicsOverridesAllowed()) continue; } catch (Exception) { }
                try
                {
                    foreach (ElementId filterId in view.GetFilters()) used.Add(Eid(filterId));
                }
                catch (Exception) { }
            }
            return (filters, used);
        }

        // ============================================================
        // links and imports
        // ============================================================

        public static List<long> IdsOfClass(Document doc, Type cls)
        {
            if (cls == null) return new List<long>();
            try { return new FilteredElementCollector(doc).OfClass(cls).Select(e => Eid(e.Id)).ToList(); }
            catch (Exception) { return new List<long>(); }
        }

        public static List<long> RevitLinkIds(Document doc) { return IdsOfClass(doc, typeof(RevitLinkType)); }

        // instances first, then the link types they came from
        public static List<long> CadIds(Document doc)
        {
            return IdsOfClass(doc, typeof(ImportInstance)).Concat(IdsOfClass(doc, typeof(CADLinkType))).ToList();
        }

        public static List<long> PointCloudIds(Document doc)
        {
            return IdsOfClass(doc, typeof(PointCloudInstance)).Concat(IdsOfClass(doc, typeof(PointCloudType))).ToList();
        }

        // ============================================================
        // NWC export
        // ============================================================

        /// <summary>{name: id} of every 3D view that can be exported (not templates).</summary>
        public static Dictionary<string, long> ThreeDViews(Document doc)
        {
            var output = new Dictionary<string, long>();
            foreach (View3D view in new FilteredElementCollector(doc).OfClass(typeof(View3D)))
            {
                try
                {
                    if (view.IsTemplate) continue;
                    output[ElementName(view)] = Eid(view.Id);
                }
                catch (Exception) { }
            }
            return output;
        }

        public static bool NwcAvailable()
        {
            try { return OptionalFunctionalityUtils.IsNavisworksExporterAvailable(); }
            catch (Exception) { return false; }
        }

        public static List<long> ImageTypeIds(Document doc) { return IdsOfClass(doc, typeof(ImageType)); }

        /// <summary>(image type id, view id) for every placed raster image.</summary>
        public static List<(long TypeId, long ViewId)> ImagePlacements(Document doc)
        {
            var output = new List<(long, long)>();
            foreach (ImageInstance instance in new FilteredElementCollector(doc).OfClass(typeof(ImageInstance)))
            {
                try { output.Add((Eid(instance.GetTypeId()), Eid(instance.OwnerViewId))); }
                catch (Exception) { }
            }
            return output;
        }

        /// <summary>What Revit's purge calls unused in the Raster Images category.</summary>
        public static HashSet<long> UnusedImageIds(Document doc)
        {
            try
            {
                var categories = new HashSet<ElementId> { new ElementId(BuiltInCategory.OST_RasterImages) };
                return new HashSet<long>(doc.GetUnusedElements(categories).Select(Eid));
            }
            catch (Exception)
            {
                try { return new HashSet<long>(UnusedEntries(doc).Select(e => e.Id)); }
                catch (Exception) { return null; }
            }
        }

        // ============================================================
        // purge
        // ============================================================

        /// <summary>[(id, group)] for everything Revit's own purge would offer.</summary>
        public static List<(long Id, string Group)> UnusedEntries(Document doc)
        {
            var output = new List<(long, string)>();
            foreach (ElementId elementId in doc.GetUnusedElements(new HashSet<ElementId>()))
            {
                Element element = doc.GetElement(elementId);
                if (element == null) continue;
                output.Add((Eid(elementId), McuCore.PurgeGroup(CategoryName(element), ClassName(element))));
            }
            return output;
        }

        /// <summary>Everything the settings window lists: unused and (optionally) used purgeable elements, with names.</summary>
        public static McuPurgeScan ScanPurge(Document doc, bool withUsed = true)
        {
            var scan = new McuPurgeScan { Ok = true };
            var unusedSet = new HashSet<long>();
            foreach (ElementId elementId in doc.GetUnusedElements(new HashSet<ElementId>()))
            {
                Element element = doc.GetElement(elementId);
                if (element == null) continue;
                long value = Eid(elementId);
                string group = McuCore.PurgeGroup(CategoryName(element), ClassName(element));
                scan.Unused.Add((value, group));
                unusedSet.Add(value);
                scan.Rows.Add((value, DisplayName(element), group, "Unused"));
            }
            if (withUsed)
            {
                var seen = new HashSet<long>(unusedSet);
                var collectors = new List<FilteredElementCollector>
                {
                    new FilteredElementCollector(doc).WhereElementIsElementType(),
                    new FilteredElementCollector(doc).OfClass(typeof(Material)),
                    new FilteredElementCollector(doc).OfClass(typeof(LinePatternElement)),
                    new FilteredElementCollector(doc).OfClass(typeof(FillPatternElement)),
                    new FilteredElementCollector(doc).OfClass(typeof(Family)),
                };
                foreach (var collector in collectors)
                {
                    foreach (Element element in collector)
                    {
                        try
                        {
                            long value = Eid(element.Id);
                            if (!seen.Add(value)) continue;
                            string group = McuCore.PurgeGroup(CategoryName(element), ClassName(element));
                            scan.Used.Add((value, group));
                            scan.Rows.Add((value, DisplayName(element), group, "Used"));
                        }
                        catch (Exception) { }
                    }
                }
            }
            return scan;
        }

        // ============================================================
        // the preview counts
        // ============================================================

        public static readonly List<(string Key, McuCore.ViewRule Rule)> ViewStages = new List<(string, McuCore.ViewRule)>
        {
            ("delete_views_off_sheet", (i, o, k, p, r, d) => McuCore.ViewsToDelete(i, o, k, p, r, d)),
            ("delete_schedules_off_sheet", (i, o, k, p, r, d) => McuCore.SchedulesToDelete(i, o, k, p, r, d)),
            ("delete_legends_off_sheet", (i, o, k, p, r, d) => McuCore.LegendsToDelete(i, o, k, p, r, d)),
        };

        /// <summary>What the sheet and view stages will delete, worked out before any of it runs.</summary>
        public static McuPlan ViewSheetPlan(Document doc, Dictionary<string, string> template, ICollection<long> protectedIds)
        {
            var keep = McuCore.SplitWords(template.Get("keep_view_words"));
            var plan = new McuPlan
            {
                RetainedViews = new HashSet<string>(McuCore.SplitRetain(template.Get("retain_views"))),
                RetainedSheets = new HashSet<string>(McuCore.SplitRetain(template.Get("retain_sheets"))),
            };
            bool deleteSheets = McuCore.AsBool(template.Get("delete_sheets_not_retained"));
            plan.Sheets = ReadSheets(doc);
            if (deleteSheets)
            {
                plan.Doomed["delete_sheets_not_retained"] =
                    McuCore.SheetsToDelete(plan.Sheets, plan.RetainedSheets, protectedIds, plan.Decisions).Ids;
            }
            else
            {
                foreach (McuSheetItem sheet in plan.Sheets) plan.Decisions[sheet.Id] = "kept: Delete sheets not retained is off";
            }
            plan.Views = ReadViews(doc);
            var surviving = McuCore.SurvivingSheetIds(plan.Sheets, deleteSheets, plan.RetainedSheets, protectedIds);
            plan.Placed = OnSheetIds(doc, surviving);
            foreach (var stage in ViewStages)
            {
                if (McuCore.AsBool(template.Get(stage.Key)))
                    plan.Doomed[stage.Key] = stage.Rule(plan.Views, plan.Placed, keep, protectedIds, plan.RetainedViews, plan.Decisions).Ids;
            }
            foreach (McuViewItem item in plan.Views)
                if (!plan.Decisions.ContainsKey(item.Id)) plan.Decisions[item.Id] = "kept: its delete stage is off";
            return plan;
        }

        public static HashSet<long> AllDoomed(McuPlan plan)
        {
            var output = new HashSet<long>();
            foreach (var ids in plan.Doomed.Values) foreach (long id in ids) output.Add(id);
            return output;
        }

        /// <summary>
        /// Where to move the active view: retained sheets, then retained plans and other views, then retained
        /// schedules and legends, then the starting view, then anything that stays.
        /// </summary>
        public static List<long> SwitchCandidates(McuPlan plan, long startingId)
        {
            var openable = plan.Sheets.Where(s => !s.Placeholder).ToList();
            var sheets = openable.Where(s => plan.RetainedSheets.Contains(s.Number)).ToList();
            sheets.Sort((a, b) => McuCore.NaturalCompare(a.Number, b.Number));
            var ids = sheets.Select(s => s.Id).ToList();
            var retained = plan.Views.Where(v => plan.RetainedViews.Contains(McuCore.ViewKey(v.Kind, v.Name)) && !v.Template).ToList();
            ids.AddRange(retained.Where(v => !McuCore.TopLevelKinds.Contains(v.Kind)).Select(v => v.Id));
            ids.AddRange(retained.Where(v => McuCore.TopLevelKinds.Contains(v.Kind)).Select(v => v.Id));
            ids.Add(startingId);
            ids.AddRange(openable.Select(s => s.Id));
            ids.AddRange(plan.Views.Where(v => !v.Template && !McuCore.NeverDeleteKinds.Contains(v.Kind)).Select(v => v.Id));
            return ids;
        }

        /// <summary>{op_key: count} of what the template would remove from doc, in the same order the run takes them.</summary>
        public static McuCounts PlanCounts(Document doc, Dictionary<string, string> template, long activeViewId = 0,
                                           List<(long Id, string Group)> purgeScan = null)
        {
            var protectedIds = new HashSet<long> { StartingViewId(doc), activeViewId };
            var result = new McuCounts();
            var counts = result.Counts;
            McuPlan plan = ViewSheetPlan(doc, template, protectedIds);
            foreach (var pair in plan.Doomed) counts[pair.Key] = pair.Value.Count;
            if (McuCore.AsBool(template.Get("remove_revit_links"))) counts["remove_revit_links"] = RevitLinkIds(doc).Count;
            var going = AllDoomed(plan);
            if (McuCore.AsBool(template.Get("remove_cad")))
            {
                int surviving = 0;
                foreach (ImportInstance instance in new FilteredElementCollector(doc).OfClass(typeof(ImportInstance)))
                {
                    try { if (!going.Contains(Eid(instance.OwnerViewId))) surviving++; }
                    catch (Exception) { surviving++; }
                }
                counts["remove_cad"] = surviving + IdsOfClass(doc, typeof(CADLinkType)).Count;
            }
            if (McuCore.AsBool(template.Get("remove_point_clouds")))
                counts["remove_point_clouds"] = IdsOfClass(doc, typeof(PointCloudInstance)).Count;
            if (McuCore.AsBool(template.Get("delete_unplaced_images")))
            {
                HashSet<long> unused = UnusedImageIds(doc);
                if (unused != null)
                    counts["delete_unplaced_images"] = McuCore.ImagesFreed(ImageTypeIds(doc), ImagePlacements(doc), going, unused).Count;
            }
            // sheets and views go first, so count templates and filters as the run will find them
            var doomedTemplates = new List<long>();
            if (McuCore.AsBool(template.Get("delete_unused_templates")))
            {
                var (templates, used, defaults) = TemplateUsage(doc, going);
                doomedTemplates = McuCore.UnusedIds(templates, used, defaults);
                counts["delete_unused_templates"] = doomedTemplates.Count;
            }
            if (McuCore.AsBool(template.Get("delete_unused_filters")))
            {
                var ignore = new HashSet<long>(going);
                foreach (long id in doomedTemplates) ignore.Add(id);
                var (filters, usedFilters) = FilterUsage(doc, ignore);
                counts["delete_unused_filters"] = McuCore.UnusedIds(filters, usedFilters).Count;
            }
            result.Kept = McuCore.KeptSummary(plan.Views, plan.Decisions);
            if (McuCore.AsBool(template.Get("export_nwc")))
            {
                var (views, _) = McuNwc.Selection(template);
                var names = ThreeDViews(doc);
                counts["export_nwc"] = views.Count(names.ContainsKey);
            }
            if (McuCore.AsBool(template.Get("purge")) && purgeScan != null)
            {
                var excluded = McuCore.SplitList(template.Get("purge_exclude"));
                counts["purge"] = McuCore.PurgeSelection(purgeScan, excluded).Count;
            }
            return result;
        }

        /// <summary>Versions and model facts for the debug report. Never throws.</summary>
        public static List<(string, object)> Environment(UIApplication uiapp, Document doc)
        {
            var pairs = new List<(string, object)>();
            Action<string, Func<object>> add = (label, getter) =>
            {
                try { pairs.Add((label, getter())); }
                catch (Exception error) { pairs.Add((label, "(unavailable: " + error.Message + ")")); }
            };
            Autodesk.Revit.ApplicationServices.Application app = uiapp.Application;
            add("Revit", () => app.VersionName + " build " + app.VersionBuild);
            add(".NET", () => System.Environment.Version.ToString());
            add("Runtime", () => System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription);
            add("Model title", () => ModelTitle(doc));
            add("Model path", () => doc.PathName);
            add("Workshared", () => doc.IsWorkshared);
            add("Cloud model", () => IsCloud(doc));
            add("Central", () => VisiblePath(CentralPath(doc)));
            add("Views browser organisation", () => OrganisationName(BrowserOrg(doc, false)));
            add("Sheets browser organisation", () => OrganisationName(BrowserOrg(doc, true)));
            add("Starting view id", () => StartingViewId(doc));
            return pairs;
        }
    }
}
