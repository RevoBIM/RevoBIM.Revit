using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;

namespace RevoBIM.Tools.ViewManager
{
    /// <summary>Warnings are deleted rather than stopping the run to show each one.</summary>
    public sealed class VmWarningSwallower : IFailuresPreprocessor
    {
        public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
        {
            try
            {
                foreach (FailureMessageAccessor failure in accessor.GetFailureMessages())
                    if (failure.GetSeverity() == FailureSeverity.Warning) accessor.DeleteWarning(failure);
            }
            catch (Exception)
            {
            }
            return FailureProcessingResult.Continue;
        }
    }

    /// <summary>
    /// View Manager - the Revit side: collecting views, templates, levels and scope boxes, making views quiet while they are
    /// cropped, the template and scope box writes, room tags, and the View Reference Manager's read and write. Port of the
    /// Revit-facing functions of script.py.
    /// </summary>
    public static class VmRevit
    {
        // ---------------------------------------------------------------- small helpers --

        public static long Key(Element element)
        {
            try { return element.Id.Value; } catch (Exception) { return 0; }
        }

        public static bool IsInvalid(ElementId id)
        {
            try { return id == null || id.Value <= 0; } catch (Exception) { return true; }
        }

        public static string TypeNameOf(Element element)
        {
            try { return element.Name; } catch (Exception) { return "<unnamed>"; }
        }

        /// <summary>Renaming, confirmed by reading back. Returns true or a reason.</summary>
        public static bool SetName(Element element, string name, out string why)
        {
            var errors = new List<string>();
            try
            {
                element.Name = name;
                if (element.Name == name)
                {
                    why = "";
                    return true;
                }
            }
            catch (Exception ex)
            {
                errors.Add("direct: " + VmCore.Describe(ex));
            }
            try
            {
                Parameter p = element.get_Parameter(BuiltInParameter.VIEW_NAME);
                if (p != null && !p.IsReadOnly)
                {
                    p.Set(name);
                    if (element.Name == name)
                    {
                        why = "";
                        return true;
                    }
                    errors.Add("VIEW_NAME: name did not take");
                }
            }
            catch (Exception ex)
            {
                errors.Add("VIEW_NAME: " + VmCore.Describe(ex));
            }
            why = string.Join("; ", errors);
            return false;
        }

        public static string RevitVersion(Autodesk.Revit.ApplicationServices.Application app)
        {
            var bits = new List<string>();
            try { bits.Add("VersionNumber=" + app.VersionNumber); } catch (Exception) { }
            try { bits.Add("VersionBuild=" + app.VersionBuild); } catch (Exception) { }
            try { bits.Add("VersionName=" + app.VersionName); } catch (Exception) { }
            try { bits.Add("SubVersionNumber=" + app.SubVersionNumber); } catch (Exception) { }
            return bits.Count == 0 ? "unknown" : string.Join(", ", bits);
        }

        /// <summary>The central file name when workshared, else the file, else the title - what keys the per-project abbreviation files.</summary>
        public static string ProjectName(Document doc)
        {
            string name = "";
            try
            {
                if (doc.IsWorkshared)
                {
                    ModelPath central = doc.GetWorksharingCentralModelPath();
                    name = ModelPathUtils.ConvertModelPathToUserVisiblePath(central);
                }
            }
            catch (Exception) { name = ""; }
            if (string.IsNullOrEmpty(name))
            {
                try { name = doc.PathName ?? ""; } catch (Exception) { name = ""; }
            }
            if (string.IsNullOrEmpty(name))
            {
                try { name = doc.Title ?? ""; } catch (Exception) { name = ""; }
            }
            return name;
        }

        // ---------------------------------------------------------------- dialogs and warnings --

        private static bool suppressing;
        private static bool hooked;

        /// <summary>DialogBoxShowing is hooked once and switched with a flag.</summary>
        public static void HookDialogs(UIApplication uiapp)
        {
            if (hooked) return;
            try
            {
                uiapp.DialogBoxShowing += OnDialogShowing;
                hooked = true;
            }
            catch (Exception)
            {
            }
        }

        private static void OnDialogShowing(object sender, Autodesk.Revit.UI.Events.DialogBoxShowingEventArgs args)
        {
            if (!suppressing) return;
            try { args.OverrideResult(1); } catch (Exception) { }     // IDOK
        }

        public static void SuppressDialogs(bool state) { suppressing = state; }

        /// <summary>Warnings deleted rather than stopping the run to show each one.</summary>
        public static void QuietOptions(Transaction transaction)
        {
            try
            {
                FailureHandlingOptions options = transaction.GetFailureHandlingOptions();
                options.SetFailuresPreprocessor(new VmWarningSwallower());
                options.SetForcedModalHandling(false);
                options.SetClearAfterRollback(true);
                try { options.SetDelayedMiniWarnings(true); } catch (Exception) { }
                transaction.SetFailureHandlingOptions(options);
            }
            catch (Exception)
            {
            }
        }

        public static bool ScopeBoxHolds(View view, ElementId boxId)
        {
            try
            {
                Parameter p = view.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP);
                if (p == null) return false;
                return p.AsElementId().Value == boxId.Value;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ---------------------------------------------------------------- model collection --

        public static List<View> CollectHostViews(Document document)
        {
            var result = new List<View>();
            foreach (View v in new FilteredElementCollector(document).OfClass(typeof(View)).Cast<View>())
            {
                try
                {
                    if (v.IsTemplate) continue;
                    if (!IsInvalid(v.GetPrimaryViewId())) continue;
                    if (!v.CanViewBeDuplicated(ViewDuplicateOption.AsDependent)) continue;
                }
                catch (Exception)
                {
                    continue;
                }
                result.Add(v);
            }
            result.Sort((a, b) =>
            {
                int c = string.CompareOrdinal(a.ViewType.ToString(), b.ViewType.ToString());
                return c != 0 ? c : string.CompareOrdinal(a.Name.ToLowerInvariant(), b.Name.ToLowerInvariant());
            });
            return result;
        }

        public static List<View> CollectViewTemplates(Document document)
        {
            var result = new List<View>();
            foreach (View v in new FilteredElementCollector(document).OfClass(typeof(View)).Cast<View>())
            {
                try { if (v.IsTemplate) result.Add(v); } catch (Exception) { }
            }
            result.Sort((a, b) => string.CompareOrdinal(a.Name.ToLowerInvariant(), b.Name.ToLowerInvariant()));
            return result;
        }

        public static List<Level> CollectLevels(Document document)
        {
            List<Level> levels = new FilteredElementCollector(document).OfClass(typeof(Level)).WhereElementIsNotElementType().Cast<Level>().ToList();
            levels.Sort((a, b) => a.Elevation.CompareTo(b.Elevation));
            return levels;
        }

        public static List<Element> CollectScopeBoxes(Document document)
        {
            List<Element> boxes = new FilteredElementCollector(document).OfCategory(BuiltInCategory.OST_VolumeOfInterest).WhereElementIsNotElementType().ToList();
            boxes.Sort((a, b) => string.CompareOrdinal(a.Name.ToLowerInvariant(), b.Name.ToLowerInvariant()));
            return boxes;
        }

        public static HashSet<string> ExistingViewNames(Document document)
        {
            var names = new HashSet<string>();
            foreach (View v in new FilteredElementCollector(document).OfClass(typeof(View)).Cast<View>())
            {
                try { names.Add(v.Name); } catch (Exception) { }
            }
            return names;
        }

        /// <summary>The ViewFamily a new view of a template's ViewType needs, or null (an area plan needs an area scheme and is not offered).</summary>
        public static ViewFamily? PlanFamilyFor(string viewType)
        {
            switch (viewType)
            {
                case "FloorPlan": return ViewFamily.FloorPlan;
                case "CeilingPlan": return ViewFamily.CeilingPlan;
                case "EngineeringPlan": return ViewFamily.StructuralPlan;
                case "StructuralPlan": return ViewFamily.StructuralPlan;
                default: return null;
            }
        }

        public static string FamilyLabel(View view)
        {
            try { return view.ViewType.ToString(); } catch (Exception) { return "Other"; }
        }

        public static string TypeLabel(Document document, View view)
        {
            try
            {
                ElementId typeId = view.GetTypeId();
                if (IsInvalid(typeId)) return "(no type)";
                Element element = document.GetElement(typeId);
                if (element == null) return "(no type)";
                string name = TypeNameOf(element);
                return string.IsNullOrEmpty(name) ? "(no type)" : name;
            }
            catch (Exception)
            {
                return "(no type)";
            }
        }

        /// <summary>family and type for every view, read once rather than per rebuild.</summary>
        public static Dictionary<long, string[]> BuildMeta(Document document, IEnumerable<View> views)
        {
            var meta = new Dictionary<long, string[]>();
            foreach (View v in views) meta[Key(v)] = new[] { FamilyLabel(v), TypeLabel(document, v) };
            return meta;
        }

        public sealed class FilterOption
        {
            public string Family, Type, Label;
        }

        /// <summary>All, then each family, then each family-and-type pair beneath it.</summary>
        public static List<FilterOption> BuildFilterOptions(Dictionary<long, string[]> meta)
        {
            var pairs = new SortedDictionary<string, SortedSet<string>>(StringComparer.Ordinal);
            foreach (string[] ft in meta.Values)
            {
                SortedSet<string> set;
                if (!pairs.TryGetValue(ft[0], out set)) pairs[ft[0]] = set = new SortedSet<string>(StringComparer.Ordinal);
                set.Add(ft[1]);
            }
            var options = new List<FilterOption> { new FilterOption { Family = null, Type = null, Label = "All families and types" } };
            foreach (KeyValuePair<string, SortedSet<string>> kv in pairs)
            {
                options.Add(new FilterOption { Family = kv.Key, Type = null, Label = kv.Key + "  -  all" });
                foreach (string type in kv.Value) options.Add(new FilterOption { Family = kv.Key, Type = type, Label = "    " + type });
            }
            return options;
        }

        /// <summary>A ViewFamilyType matching the plan family of a template. Sorted by name, first taken, so the same one is picked every run.</summary>
        public static ViewFamilyType ViewFamilyTypeFor(Document document, string viewType, Dictionary<string, ViewFamilyType> cache, List<string> log)
        {
            ViewFamilyType cached;
            if (cache.TryGetValue(viewType, out cached)) return cached;
            ViewFamily? family = PlanFamilyFor(viewType);
            var candidates = new List<ViewFamilyType>();
            if (family != null)
            {
                foreach (ViewFamilyType vft in new FilteredElementCollector(document).OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>())
                {
                    try { if (vft.ViewFamily == family.Value) candidates.Add(vft); } catch (Exception) { }
                }
            }
            candidates.Sort((a, b) => string.CompareOrdinal(TypeNameOf(a).ToLowerInvariant(), TypeNameOf(b).ToLowerInvariant()));
            ViewFamilyType found = candidates.Count > 0 ? candidates[0] : null;
            if (log != null)
            {
                if (found == null) log.Add("    no ViewFamilyType for ViewType '" + viewType + "' (ViewFamily " + family + ")");
                else if (candidates.Count > 1)
                    log.Add("    " + candidates.Count + " ViewFamilyTypes available for " + viewType + ": " + string.Join(", ", candidates.Take(8).Select(TypeNameOf)));
            }
            cache[viewType] = found;
            return found;
        }

        // ---------------------------------------------------------------- quiet views --

        private static readonly string[] QuietCategories = { "OST_RvtLinks", "OST_Coordination_Model", "OST_PointClouds", "OST_RasterImages" };

        public static ElementId CategoryId(Document document, string builtinName)
        {
            BuiltInCategory builtin;
            if (!Enum.TryParse(builtinName, out builtin)) return null;
            try
            {
                Category cat = Category.GetCategory(document, builtin);
                if (cat != null) return cat.Id;
            }
            catch (Exception) { }
            try { return RevitCompat.Id((long)(int)builtin); } catch (Exception) { return null; }
        }

        public sealed class Quiet
        {
            public List<WorksetId> Worksets = new List<WorksetId>();
            public List<ElementId> Categories = new List<ElementId>();
        }

        /// <summary>Hides links and worksets before the view is cropped, so the crop is worked out against nothing.</summary>
        public static Quiet QuietenView(Document document, View view, out string notes)
        {
            var quiet = new Quiet();
            var list = new List<string>();
            foreach (string name in QuietCategories)
            {
                ElementId cid = CategoryId(document, name);
                if (cid == null) continue;
                try
                {
                    if (view.CanCategoryBeHidden(cid) && !view.GetCategoryHidden(cid))
                    {
                        view.SetCategoryHidden(cid, true);
                        quiet.Categories.Add(cid);
                    }
                }
                catch (Exception ex)
                {
                    list.Add(name + ": " + VmCore.Describe(ex));
                }
            }
            if (document.IsWorkshared)
            {
                try
                {
                    foreach (Workset workset in new FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset))
                    {
                        try
                        {
                            if (view.GetWorksetVisibility(workset.Id) != WorksetVisibility.Hidden)
                            {
                                view.SetWorksetVisibility(workset.Id, WorksetVisibility.Hidden);
                                quiet.Worksets.Add(workset.Id);
                            }
                        }
                        catch (Exception) { }
                    }
                }
                catch (Exception ex)
                {
                    list.Add("worksets: " + VmCore.Describe(ex));
                }
            }
            notes = string.Join("; ", list);
            return quiet;
        }

        /// <summary>Undo QuietenView once the template is on: categories and worksets. The template's answer wins.</summary>
        public static int RestoreQuiet(View view, Quiet hidden)
        {
            if (hidden == null) return 0;
            foreach (ElementId cid in hidden.Categories)
            {
                try { view.SetCategoryHidden(cid, false); } catch (Exception) { }
            }
            return RestoreWorksets(view, hidden.Worksets);
        }

        public static int RestoreWorksets(View view, IEnumerable<WorksetId> worksetIds)
        {
            int restored = 0;
            if (worksetIds == null) return 0;
            foreach (WorksetId id in worksetIds)
            {
                try
                {
                    view.SetWorksetVisibility(id, WorksetVisibility.UseGlobalSetting);
                    restored++;
                }
                catch (Exception) { }
            }
            return restored;
        }

        /// <summary>(applied, note). verify reads the value back, which forces a regeneration - fine once after the commit, ruinous inside the loop.</summary>
        public static bool ApplyScopeBox(View view, ElementId boxId, bool verify, out string note)
        {
            note = "";
            Parameter p;
            try
            {
                p = view.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP);
            }
            catch (Exception ex)
            {
                note = "scope box parameter lookup failed - " + VmCore.Describe(ex);
                return false;
            }
            if (p == null)
            {
                note = "view has no scope box parameter";
                return false;
            }
            if (p.IsReadOnly)
            {
                note = "scope box parameter is read-only (locked by the view template?)";
                return false;
            }
            try
            {
                p.Set(boxId);
            }
            catch (Exception ex)
            {
                note = "scope box Set failed - " + VmCore.Describe(ex);
                return false;
            }
            try
            {
                if (!view.CropBoxActive) view.CropBoxActive = true;
                if (!view.CropBoxVisible) view.CropBoxVisible = true;
            }
            catch (Exception) { }
            if (verify)
            {
                try
                {
                    if (IsInvalid(p.AsElementId()))
                    {
                        note = "scope box did not take (read back as none)";
                        return false;
                    }
                }
                catch (Exception) { }
            }
            return true;
        }

        public static bool ApplyTemplate(View view, View template, out string note)
        {
            note = "";
            try
            {
                if (!view.IsValidViewTemplate(template.Id))
                {
                    note = "template is not valid for this view type";
                    return false;
                }
            }
            catch (Exception) { }
            try
            {
                view.ViewTemplateId = template.Id;
            }
            catch (Exception ex)
            {
                note = "ViewTemplateId Set failed - " + VmCore.Describe(ex);
                return false;
            }
            try
            {
                if (view.ViewTemplateId.Value != template.Id.Value)
                {
                    note = "template did not take (read back as a different id)";
                    return false;
                }
            }
            catch (Exception) { }
            return true;
        }

        // ---------------------------------------------------------------- room tags --

        /// <summary>(link instance or null, document, transform) for this model and each loaded link.</summary>
        private static List<Tuple<RevitLinkInstance, Document, Transform>> RoomSources(Document document, bool includeLinks)
        {
            var sources = new List<Tuple<RevitLinkInstance, Document, Transform>> { Tuple.Create<RevitLinkInstance, Document, Transform>(null, document, Transform.Identity) };
            if (!includeLinks) return sources;
            try
            {
                foreach (RevitLinkInstance instance in new FilteredElementCollector(document).OfClass(typeof(RevitLinkInstance)).Cast<RevitLinkInstance>())
                {
                    try
                    {
                        Document linkDoc = instance.GetLinkDocument();
                        if (linkDoc == null) continue;           // unloaded
                        sources.Add(Tuple.Create(instance, linkDoc, instance.GetTotalTransform()));
                    }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            return sources;
        }

        /// <summary>Every placed, bounded room, with its point and height in host coordinates.</summary>
        public static List<VmCore.RoomRecord> CollectRoomRecords(Document document, bool includeLinks, List<string> log)
        {
            var records = new List<VmCore.RoomRecord>();
            int skipped = 0;
            foreach (var source in RoomSources(document, includeLinks))
            {
                string sourceName = source.Item1 == null ? "this model" : TypeNameOf(source.Item1);
                int count = 0;
                FilteredElementCollector rooms;
                try
                {
                    rooms = new FilteredElementCollector(source.Item2).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType();
                }
                catch (Exception) { continue; }
                foreach (Element element in rooms)
                {
                    try
                    {
                        var room = element as Room;
                        if (room == null || room.Area <= 0) { skipped++; continue; }       // unplaced, unbounded or redundant
                        var location = room.Location as LocationPoint;
                        if (location == null) { skipped++; continue; }
                        XYZ point = source.Item3.OfPoint(location.Point);
                        BoundingBoxXYZ box = room.get_BoundingBox(null);
                        if (box == null) { skipped++; continue; }
                        var zs = new List<double>();
                        foreach (double x in new[] { box.Min.X, box.Max.X })
                            foreach (double y in new[] { box.Min.Y, box.Max.Y })
                                foreach (double z in new[] { box.Min.Z, box.Max.Z })
                                    zs.Add(source.Item3.OfPoint(new XYZ(x, y, z)).Z);
                        records.Add(new VmCore.RoomRecord { Link = source.Item1, Id = room.Id, X = point.X, Y = point.Y, ZMin = zs.Min(), ZMax = zs.Max() });
                        count++;
                    }
                    catch (Exception) { skipped++; }
                }
                if (log != null) log.Add("  rooms from " + sourceName + ": " + count);
            }
            if (log != null && skipped > 0) log.Add("  rooms skipped (unplaced, unbounded or redundant): " + skipped);
            return records;
        }

        /// <summary>The cut plane's height in model coordinates. ProjectElevation, never Elevation.</summary>
        public static double? ViewCutZ(View view)
        {
            try
            {
                var plan = view as ViewPlan;
                if (plan != null)
                {
                    PlanViewRange range = plan.GetViewRange();
                    ElementId levelId = range.GetLevelId(PlanViewPlane.CutPlane);
                    double offset = range.GetOffset(PlanViewPlane.CutPlane);
                    var level = view.Document.GetElement(levelId) as Level;
                    if (level != null) return level.ProjectElevation + offset;
                }
            }
            catch (Exception) { }
            try { return view.GenLevel.ProjectElevation + VmCore.DefaultCutOffset; } catch (Exception) { return null; }
        }

        /// <summary>The crop's XY extent in model coordinates, or null if it is not cropped.</summary>
        public static double[] ViewCropRect(View view)
        {
            try
            {
                if (!view.CropBoxActive) return null;
                BoundingBoxXYZ crop = view.CropBox;
                Transform transform = crop.Transform;
                var points = new List<double[]>();
                foreach (double x in new[] { crop.Min.X, crop.Max.X })
                    foreach (double y in new[] { crop.Min.Y, crop.Max.Y })
                    {
                        XYZ p = transform.OfPoint(new XYZ(x, y, crop.Min.Z));
                        points.Add(new[] { p.X, p.Y });
                    }
                return VmCore.RectOfPoints(points);
            }
            catch (Exception)
            {
                return null;
            }
        }

        public sealed class TagStats
        {
            public int Tagged, Views, Refused;
            public string FirstRefusal;
        }

        /// <summary>Tag every room this plan cuts. Inside an open transaction. (placed, candidates)</summary>
        public static int TagRoomsInView(Document document, View view, IEnumerable<VmCore.RoomRecord> rooms, ElementId tagTypeId, TagStats stats, out int candidates)
        {
            List<VmCore.RoomRecord> picked = VmCore.RoomsInPlan(rooms, ViewCutZ(view), ViewCropRect(view));
            int placed = 0;
            foreach (VmCore.RoomRecord room in picked)
            {
                try
                {
                    LinkElementId linkId = room.Link == null
                        ? new LinkElementId((ElementId)room.Id)
                        : new LinkElementId(((RevitLinkInstance)room.Link).Id, (ElementId)room.Id);
                    RoomTag tag = document.Create.NewRoomTag(linkId, new UV(room.X, room.Y), view.Id);
                    if (tag == null)
                    {
                        stats.Refused++;
                        continue;
                    }
                    if (tagTypeId != null)
                    {
                        try
                        {
                            if (tag.GetTypeId().Value != tagTypeId.Value) tag.ChangeTypeId(tagTypeId);
                        }
                        catch (Exception) { }
                    }
                    placed++;
                }
                catch (Exception ex)
                {
                    stats.Refused++;
                    if (string.IsNullOrEmpty(stats.FirstRefusal)) stats.FirstRefusal = VmCore.Describe(ex);
                }
            }
            stats.Tagged += placed;
            stats.Views++;
            candidates = picked.Count;
            return placed;
        }

        /// <summary>Family : Type of a room tag symbol, as the Type Selector shows it.</summary>
        public static string RoomTagLabel(Element symbol)
        {
            string name = TypeNameOf(symbol);
            string family = null;
            try { family = (symbol as FamilySymbol) != null ? ((FamilySymbol)symbol).FamilyName : null; } catch (Exception) { }
            return string.IsNullOrEmpty(family) ? name : family + " : " + name;
        }

        public static List<Element> CollectRoomTagTypes(Document document)
        {
            var found = new List<Element>();
            try
            {
                foreach (Element e in new FilteredElementCollector(document).OfCategory(BuiltInCategory.OST_RoomTags).WhereElementIsElementType())
                    found.Add(e);
            }
            catch (Exception) { }
            found.Sort((a, b) => string.CompareOrdinal(RoomTagLabel(a).ToLowerInvariant(), RoomTagLabel(b).ToLowerInvariant()));
            return found;
        }

        /// <summary>The room tag type the project uses by default, or null.</summary>
        public static ElementId DefaultRoomTagId(Document document)
        {
            try
            {
                ElementId cid = CategoryId(document, "OST_RoomTags");
                if (cid != null)
                {
                    ElementId id = document.GetDefaultFamilyTypeId(cid);
                    if (!IsInvalid(id)) return id;
                }
            }
            catch (Exception) { }
            return null;
        }

        /// <summary>The chosen tag, else the project default, else the first loaded. Returns null (with a note) when none is loaded.</summary>
        public static ElementId ResolveRoomTagType(Document document, out string label, out string note)
        {
            List<Element> types = CollectRoomTagTypes(document);
            if (types.Count == 0)
            {
                label = "";
                note = "No room tag family is loaded in this project.";
                return null;
            }
            string wanted = (VmCore.Get("room_tag_type") ?? "").Trim();
            if (wanted.Length > 0)
            {
                foreach (Element symbol in types)
                    if (RoomTagLabel(symbol) == wanted)
                    {
                        label = wanted;
                        note = "";
                        return symbol.Id;
                    }
            }
            ElementId defaultId = DefaultRoomTagId(document);
            if (defaultId != null)
            {
                Element element = document.GetElement(defaultId);
                label = element != null ? RoomTagLabel(element) : "project default";
                note = wanted.Length > 0 ? "'" + wanted + "' is not loaded here - using the project default." : "";
                return defaultId;
            }
            label = RoomTagLabel(types[0]);
            note = "No project default is set - using the first loaded room tag.";
            return types[0].Id;
        }

        // ---------------------------------------------------------------- view references --

        /// <summary>Family : Type, as the Type Selector shows it.</summary>
        public static string TypeLabelOf(Document document, ElementId typeId)
        {
            Element element = document.GetElement(typeId);
            string name = VmCore.CleanValue(TypeNameOf(element));
            string family = null;
            try
            {
                var symbol = element as ElementType;
                if (symbol != null) family = symbol.FamilyName;
            }
            catch (Exception) { }
            return string.IsNullOrEmpty(family) ? name : VmCore.CleanValue(family + " : " + name);
        }

        /// <summary>What a parameter shows, as text. A string is its string; a number is the value as Revit would display it.</summary>
        public static string ParamText(Parameter p)
        {
            if (p == null) return "";
            try
            {
                if (p.StorageType == StorageType.String) return VmCore.CleanValue(p.AsString());
                return VmCore.CleanValue(p.AsValueString());
            }
            catch (Exception)
            {
                return "";
            }
        }

        public static Parameter NamedParam(Element element, string name)
        {
            try { return element.LookupParameter(name); } catch (Exception) { return null; }
        }

        /// <summary>'Title on Sheet': by name first, then by its built-in id, which survives a Revit running in another language.</summary>
        public static Parameter TitleParam(Element view)
        {
            Parameter p = NamedParam(view, "Title on Sheet");
            if (p == null)
            {
                try { p = view.get_Parameter(BuiltInParameter.VIEW_DESCRIPTION); } catch (Exception) { p = null; }
            }
            return p;
        }

        public static Parameter DetailParam(Element viewport)
        {
            Parameter p = null;
            try { p = viewport.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER); } catch (Exception) { p = null; }
            return p ?? NamedParam(viewport, "Detail Number");
        }

        public static string LevelText(View view)
        {
            string text = ParamText(NamedParam(view, "Associated Level"));
            if (text.Length > 0) return text;
            try
            {
                text = ParamText(view.get_Parameter(BuiltInParameter.PLAN_VIEW_LEVEL));
                if (text.Length > 0) return text;
            }
            catch (Exception) { }
            try
            {
                Level level = view.GenLevel;
                if (level != null) return VmCore.CleanValue(level.Name);
            }
            catch (Exception) { }
            return "";
        }

        /// <summary>{view id: (viewport, sheet)} - the first sheet a view sits on.</summary>
        public static Dictionary<long, Tuple<Viewport, Element>> SheetPlacements(Document document)
        {
            var found = new Dictionary<long, Tuple<Viewport, Element>>();
            foreach (Viewport vp in new FilteredElementCollector(document).OfClass(typeof(Viewport)).Cast<Viewport>())
            {
                try
                {
                    long viewId = vp.ViewId.Value;
                    if (found.ContainsKey(viewId)) continue;
                    Element sheet = document.GetElement(vp.SheetId);
                    if (sheet != null) found[viewId] = Tuple.Create(vp, sheet);
                }
                catch (Exception) { }
            }
            return found;
        }

        /// <summary>Every view worth listing, as RefRows with their values and the reason any cell cannot be edited.</summary>
        public static List<VmCore.RefRow> ReadViewRefs(Document document, IEnumerable<string> extraNames, List<string> log)
        {
            List<string> extras = extraNames == null ? new List<string>() : extraNames.ToList();
            Dictionary<long, Tuple<Viewport, Element>> placements = SheetPlacements(document);
            var rows = new List<VmCore.RefRow>();
            foreach (View v in new FilteredElementCollector(document).OfClass(typeof(View)).Cast<View>())
            {
                string typeName, name;
                try
                {
                    if (v.IsTemplate) continue;
                    typeName = v.ViewType.ToString();
                    if (Array.IndexOf(VmCore.ExcludedViewTypes, typeName) >= 0) continue;
                    name = VmCore.CleanValue(v.Name);
                }
                catch (Exception)
                {
                    continue;
                }
                var row = new VmCore.RefRow(Key(v), typeName);
                Dictionary<string, string> values = row.Values;
                values["name"] = name;
                values["level"] = LevelText(v);
                values["vtype"] = row.TypeLabel;
                values["vid"] = row.ViewId.ToString();
                Parameter tp = TitleParam(v);
                values["title"] = ParamText(tp);
                if (tp == null) row.Locked["title"] = "This view has no Title on Sheet parameter.";
                else if (tp.IsReadOnly) row.Locked["title"] = "Title on Sheet is read-only for this view.";
                values["sheetno"] = "";
                values["sheetname"] = "";
                values["detail"] = "";
                values["vptype"] = "";
                values["template"] = "";
                try
                {
                    ElementId tid = v.ViewTemplateId;
                    if (!IsInvalid(tid))
                    {
                        Element tpl = document.GetElement(tid);
                        values["template"] = tpl != null ? VmCore.CleanValue(TypeNameOf(tpl)) : "";
                    }
                }
                catch (Exception)
                {
                    row.Locked["template"] = "This kind of view has no view template.";
                }
                Tuple<Viewport, Element> placed;
                if (placements.TryGetValue(row.ViewId, out placed))
                {
                    Viewport vp = placed.Item1;
                    Element sheet = placed.Item2;
                    row.SheetId = Key(sheet);
                    row.ViewportId = Key(vp);
                    try
                    {
                        var vs = sheet as ViewSheet;
                        if (vs != null) values["sheetno"] = VmCore.CleanValue(vs.SheetNumber);
                        values["sheetname"] = VmCore.CleanValue(sheet.Name);
                    }
                    catch (Exception) { }
                    try { values["vptype"] = TypeLabelOf(document, vp.GetTypeId()); }
                    catch (Exception) { row.Locked["vptype"] = "The viewport type could not be read."; }
                    Parameter dp = DetailParam(vp);
                    values["detail"] = ParamText(dp);
                    if (dp == null) row.Locked["detail"] = "This viewport has no Detail Number.";
                    else if (dp.IsReadOnly) row.Locked["detail"] = "Detail Number is read-only here.";
                }
                else
                {
                    row.Locked["detail"] = "Not placed on a sheet, so it has no detail number.";
                    row.Locked["vptype"] = "Not placed on a sheet, so it has no viewport type.";
                }
                foreach (string pname in extras)
                {
                    string key = VmCore.ParamPrefix + pname;
                    Parameter p = NamedParam(v, pname);
                    values[key] = ParamText(p);
                    if (p == null) row.Locked[key] = "This view has no '" + pname + "' parameter.";
                    else if (p.IsReadOnly) row.Locked[key] = "'" + pname + "' is read-only.";
                    else if (p.StorageType != StorageType.String && p.StorageType != StorageType.Integer && p.StorageType != StorageType.Double)
                        row.Locked[key] = "'" + pname + "' holds a reference, not text.";
                }
                rows.Add(row);
            }
            // stable: view type rank, then natural name order
            rows = rows.Select((r, i) => new { r, i })
                       .OrderBy(t => VmCore.ViewTypeRank(t.r.TypeName))
                       .ThenBy(t => VmCore.NaturalKey(t.r.Values["name"]), StringComparer.Ordinal)
                       .ThenBy(t => t.i)
                       .Select(t => t.r).ToList();
            if (log != null) log.Add("Read " + rows.Count + " view(s) for the reference list.");
            return rows;
        }

        /// <summary>{lower-case name: id} of every view template.</summary>
        public static Dictionary<string, ElementId> TemplateIds(Document document)
        {
            var found = new Dictionary<string, ElementId>();
            foreach (View v in new FilteredElementCollector(document).OfClass(typeof(View)).Cast<View>())
            {
                try { if (v.IsTemplate) found[VmCore.CleanValue(v.Name).ToLowerInvariant()] = v.Id; } catch (Exception) { }
            }
            return found;
        }

        /// <summary>What the template and viewport-type columns may be set to.</summary>
        public static Dictionary<string, List<string>> CollectChoices(Document document)
        {
            var names = new HashSet<string>();
            foreach (View v in new FilteredElementCollector(document).OfClass(typeof(View)).Cast<View>())
            {
                try { if (v.IsTemplate) names.Add(VmCore.CleanValue(v.Name)); } catch (Exception) { }
            }
            var templates = names.ToList();
            templates.Sort((a, b) => string.CompareOrdinal(VmCore.NaturalKey(a), VmCore.NaturalKey(b)));
            templates.Insert(0, "");
            var vpNames = new HashSet<string>();
            var done = new HashSet<long>();
            foreach (Viewport vp in new FilteredElementCollector(document).OfClass(typeof(Viewport)).Cast<Viewport>())
            {
                try
                {
                    long current = vp.GetTypeId().Value;
                    if (!done.Add(current)) continue;
                    foreach (ElementId tid in vp.GetValidTypes()) vpNames.Add(TypeLabelOf(document, tid));
                }
                catch (Exception) { }
            }
            var vpList = vpNames.ToList();
            vpList.Sort((a, b) => string.CompareOrdinal(VmCore.NaturalKey(a), VmCore.NaturalKey(b)));
            return new Dictionary<string, List<string>> { { "template", templates }, { "vptype", vpList } };
        }

        public sealed class ParamName
        {
            public string Name;
            public bool Editable;
        }

        /// <summary>The parameter names a column could show: those on the views of the chosen type (or all), minus the columns that are always there.</summary>
        public static List<ParamName> ParameterNames(Document document, IEnumerable<VmCore.RefRow> rows, string typeName, int limit = 250)
        {
            HashSet<string> skip = VmCore.FixedLabels();
            var seen = new Dictionary<string, bool>();
            int count = 0;
            foreach (VmCore.RefRow row in rows)
            {
                if (!string.IsNullOrEmpty(typeName) && row.TypeName != typeName) continue;
                Element view = document.GetElement(RevitCompat.Id(row.ViewId));
                if (view == null) continue;
                count++;
                if (count > limit) break;
                try
                {
                    foreach (Parameter p in view.Parameters)
                    {
                        string name;
                        try { name = VmCore.CleanValue(p.Definition.Name); } catch (Exception) { continue; }
                        if (name.Length == 0 || skip.Contains(name.ToLowerInvariant())) continue;
                        bool editable = !p.IsReadOnly && (p.StorageType == StorageType.String || p.StorageType == StorageType.Integer || p.StorageType == StorageType.Double);
                        bool before;
                        seen.TryGetValue(name, out before);
                        seen[name] = before || editable;
                    }
                }
                catch (Exception) { }
            }
            return seen.OrderBy(kv => kv.Key.ToLowerInvariant(), StringComparer.Ordinal).Select(kv => new ParamName { Name = kv.Key, Editable = kv.Value }).ToList();
        }

        /// <summary>(ok, message). Reads back what Revit kept, because a parameter can take a value and quietly change it.</summary>
        public static bool WriteParamText(Parameter p, string text, out string message)
        {
            message = "";
            if (p == null)
            {
                message = "The parameter is not on this element.";
                return false;
            }
            try
            {
                if (p.IsReadOnly)
                {
                    message = "The parameter is read-only.";
                    return false;
                }
                StorageType storage = p.StorageType;
                if (storage == StorageType.String)
                {
                    p.Set(text);
                    string kept = VmCore.CleanValue(p.AsString());
                    if (kept != text)
                    {
                        message = "Revit kept '" + kept + "' instead.";
                        return false;
                    }
                    return true;
                }
                if (storage == StorageType.Integer || storage == StorageType.Double)
                {
                    if (p.SetValueString(text)) return true;
                    try
                    {
                        if (storage == StorageType.Integer) p.Set(int.Parse(text));
                        else p.Set(double.Parse(text, System.Globalization.CultureInfo.InvariantCulture));
                        return true;
                    }
                    catch (Exception)
                    {
                        message = "Revit would not accept '" + text + "'.";
                        return false;
                    }
                }
                message = "This parameter cannot be written as text.";
                return false;
            }
            catch (Exception ex)
            {
                message = VmCore.Describe(ex);
                return false;
            }
        }

        public static string TempText(long viewId) { return "~RB" + viewId; }

        /// <summary>
        /// Write staged edits in one transaction. applied: the cells written; failed: cell -> why. Names and detail numbers must
        /// be unique, so a swap or a shift would collide halfway through: an edit whose target is held by another edited item is
        /// parked on a temporary value first, and every edit then lands on its real value.
        /// </summary>
        public static void ApplyRefEdits(Document document, IList<VmCore.EditItem> items, List<string> log,
                                         out List<VmCore.CellKey> applied, out Dictionary<VmCore.CellKey, string> failed)
        {
            applied = new List<VmCore.CellKey>();
            failed = new Dictionary<VmCore.CellKey, string>();
            Dictionary<string, ElementId> tplIds = null;

            Func<VmCore.EditItem, Element> targetOf = item =>
                document.GetElement(RevitCompat.Id((item.Kind == "detail" || item.Kind == "vptype") ? item.Viewport : item.ViewId));

            Func<VmCore.EditItem, string, string> setter = (item, text) =>
            {
                // returns "" for success, else why
                string kind = item.Kind;
                Element element = targetOf(item);
                if (element == null) return "The view is no longer in the model.";
                string why;
                if (kind == "name") return SetName(element, text, out why) ? "" : why;
                if (kind == "title") return WriteParamText(TitleParam(element), text, out why) ? "" : why;
                if (kind == "detail") return WriteParamText(DetailParam(element), text, out why) ? "" : why;
                if (kind == "param") return WriteParamText(NamedParam(element, item.Param), text, out why) ? "" : why;
                if (kind == "template")
                {
                    try
                    {
                        var view = (View)element;
                        if (text.Length == 0)
                        {
                            view.ViewTemplateId = ElementId.InvalidElementId;
                            return "";
                        }
                        if (tplIds == null) tplIds = TemplateIds(document);
                        ElementId tid;
                        if (!tplIds.TryGetValue(text.ToLowerInvariant(), out tid)) return "No view template called '" + text + "'.";
                        if (!view.IsValidViewTemplate(tid)) return "'" + text + "' is not valid for this kind of view.";
                        view.ViewTemplateId = tid;
                        return "";
                    }
                    catch (Exception ex) { return VmCore.Describe(ex); }
                }
                if (kind == "vptype")
                {
                    try
                    {
                        var viewport = (Viewport)element;
                        foreach (ElementId tid in viewport.GetValidTypes())
                        {
                            string label = TypeLabelOf(document, tid).ToLowerInvariant();
                            string bare = VmCore.CleanValue(TypeNameOf(document.GetElement(tid))).ToLowerInvariant();
                            if (text.ToLowerInvariant() == label || text.ToLowerInvariant() == bare)
                            {
                                viewport.ChangeTypeId(tid);
                                return "";
                            }
                        }
                        return "'" + text + "' is not a valid viewport type here.";
                    }
                    catch (Exception ex) { return VmCore.Describe(ex); }
                }
                return "Unknown field.";
            };

            var namesOld = new HashSet<string>(items.Where(i => i.Kind == "name").Select(i => i.Old.ToLowerInvariant()));
            var detailsOld = new Dictionary<long, HashSet<string>>();
            foreach (VmCore.EditItem i in items)
            {
                if (i.Kind != "detail") continue;
                HashSet<string> set;
                if (!detailsOld.TryGetValue(i.Sheet, out set)) detailsOld[i.Sheet] = set = new HashSet<string>();
                set.Add(i.Old.ToLowerInvariant());
            }

            Func<VmCore.EditItem, bool> collides = item =>
            {
                if (item.Kind == "name")
                    return namesOld.Contains(item.Text.ToLowerInvariant()) && item.Text.ToLowerInvariant() != item.Old.ToLowerInvariant();
                if (item.Kind == "detail")
                {
                    HashSet<string> set;
                    return detailsOld.TryGetValue(item.Sheet, out set) && set.Contains(item.Text.ToLowerInvariant())
                           && item.Text.ToLowerInvariant() != item.Old.ToLowerInvariant();
                }
                return false;
            };

            var t = new Transaction(document, "View Manager - view references");
            t.Start();
            QuietOptions(t);
            var parked = new List<VmCore.EditItem>();
            try
            {
                foreach (VmCore.EditItem item in items)
                {
                    if (!collides(item)) continue;
                    string why = setter(item, TempText(item.ViewId));
                    if (why.Length == 0) parked.Add(item);
                    else log.Add("  could not park " + item.Kind + " " + item.ViewId + ": " + why);
                }
                // Land the real values. One that has to wait for another to move out of the way is retried after the others;
                // what still will not go after a pass that moved nothing is refused, with the reason Revit gave.
                var waiting = new List<VmCore.EditItem>(items);
                var reasons = new Dictionary<VmCore.CellKey, string>();
                while (waiting.Count > 0)
                {
                    bool moved = false;
                    foreach (VmCore.EditItem item in waiting.ToList())
                    {
                        var key = new VmCore.CellKey(item.ViewId, item.Key);
                        string why = setter(item, item.Text);
                        if (why.Length == 0)
                        {
                            applied.Add(key);
                            waiting.Remove(item);
                            moved = true;
                        }
                        else reasons[key] = why;
                    }
                    if (!moved) break;
                }
                foreach (VmCore.EditItem item in waiting)
                {
                    var key = new VmCore.CellKey(item.ViewId, item.Key);
                    string reason;
                    failed[key] = reasons.TryGetValue(key, out reason) ? reason : "Revit refused it.";
                    if (parked.Contains(item))
                    {
                        bool backOk = setter(item, item.Old).Length == 0;
                        log.Add("  restored " + item.Kind + " on " + item.ViewId + ": " + (backOk ? "yes" : "NO"));
                    }
                    log.Add("  FAIL " + item.Kind + " [" + item.ViewId + "] '" + item.Old + "' -> '" + item.Text + "': " + failed[key]);
                }
                TransactionStatus status = t.Commit();
                if (status != TransactionStatus.Committed) throw new Exception("transaction status was " + status);
            }
            catch (Exception ex)
            {
                if (t.HasStarted())
                {
                    try { t.RollBack(); } catch (Exception) { }
                }
                log.Add("  transaction failed: " + VmCore.Describe(ex));
                applied = new List<VmCore.CellKey>();
                failed = new Dictionary<VmCore.CellKey, string>();
                foreach (VmCore.EditItem i in items) failed[new VmCore.CellKey(i.ViewId, i.Key)] = "Nothing was written: " + VmCore.Describe(ex);
            }
            finally
            {
                t.Dispose();
            }
        }
    }
}

