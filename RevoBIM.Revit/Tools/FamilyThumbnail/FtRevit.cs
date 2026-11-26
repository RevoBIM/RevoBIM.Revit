using System;
using System.Collections.Generic;
using System.IO;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.FamilyThumbnail
{
    /// <summary>What one thumbnail update did.</summary>
    public sealed class FtResult
    {
        public bool Ok;
        public string Path;
        public string Rfa;
        public List<string> Notes = new List<string>();
        public string Family = "";
        public string Category = "";
        public string Override;
        public string ViewName = "";
        public string Message = "";
        public Dictionary<string, string> Applied = new Dictionary<string, string>();
    }

    /// <summary>
    /// The Revit side of Family Thumbnail: the thumbnail view, the temporary appearance and the export. The view itself (name,
    /// orientation, lock) is created or updated in one committed transaction. The appearance (display style, detail level,
    /// scale, hidden categories, gradient background) is applied in a second transaction that is ROLLED BACK once the image
    /// has been exported, so the family is left exactly as it was apart from the thumbnail view. Port of ft_revit.py.
    /// </summary>
    public static class FtRevit
    {
        private static readonly string[] ImageExtensions = { ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff" };

        /// <summary>Runs one cosmetic step; a failure is recorded and reported in the notes, never raised.</summary>
        public static bool TryStep(string label, Action action, List<string> notes)
        {
            try
            {
                action();
                return true;
            }
            catch (Exception err)
            {
                FtCore.Swallowed(label, err);
                notes.Add(label);
                return false;
            }
        }

        private static ElementId BuiltInCategoryId(string[] names)
        {
            BuiltInCategory? member = FtCore.EnumMember<BuiltInCategory>(names);
            return member.HasValue ? new ElementId(member.Value) : null;
        }

        // ---- family information ------------------------------------------------------------------------

        public sealed class FamilyInfo
        {
            public string Name = "";
            public string Category = "";
            public bool Is2D;
        }

        /// <summary>Name, category name and whether the family is 2D (annotation, detail, profile or title block).</summary>
        public static FamilyInfo InfoOf(Document doc)
        {
            var info = new FamilyInfo { Name = FtCore.SafeFileName(doc.Title) };
            try
            {
                Category category = doc.OwnerFamily.FamilyCategory;
                if (category != null)
                {
                    info.Category = category.Name;
                    try
                    {
                        if (category.CategoryType == CategoryType.Annotation) info.Is2D = true;
                    }
                    catch (Exception err)
                    {
                        FtCore.Swallowed("family_info.CategoryType", err);
                    }
                    long cid = FtCore.Eid(category.Id);
                    foreach (string memberName in FtCore.Categories2D)
                    {
                        BuiltInCategory member;
                        if (Enum.TryParse(memberName, false, out member) && cid == (long)(int)member) info.Is2D = true;
                    }
                }
            }
            catch (Exception err)
            {
                FtCore.Swallowed("family_info", err);
            }
            return info;
        }

        /// <summary>Top-level model and annotation category names of a document, for the override picker.</summary>
        public static List<string> CategoryNames(Document doc)
        {
            var names = new List<string>();
            try
            {
                foreach (Category category in doc.Settings.Categories)
                {
                    try
                    {
                        if (category.Parent == null
                            && (category.CategoryType == CategoryType.Model || category.CategoryType == CategoryType.Annotation))
                            names.Add(category.Name);
                    }
                    catch (Exception err)
                    {
                        FtCore.Swallowed("category_names.item", err);
                    }
                }
            }
            catch (Exception err)
            {
                FtCore.Swallowed("category_names", err);
            }
            return names;
        }

        // ---- the thumbnail view ------------------------------------------------------------------------

        private static View3D FindView3D(Document doc, string name)
        {
            foreach (View3D view in new FilteredElementCollector(doc).OfClass(typeof(View3D)))
            {
                try
                {
                    if (!view.IsTemplate && view.Name == name) return view;
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("find_view3d.item", err);
                }
            }
            return null;
        }

        private static ElementId View3DTypeId(Document doc)
        {
            foreach (ViewFamilyType vft in new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)))
            {
                try
                {
                    if (vft.ViewFamily == ViewFamily.ThreeDimensional) return vft.Id;
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("view3d_type_id.item", err);
                }
            }
            return null;
        }

        /// <summary>Creates or updates the named 3D view: orientation from the View Type, optional lock.</summary>
        public static View3D EnsureThumbnailView(Document doc, FtSettings s, string viewType, List<string> notes)
        {
            string name = s.ViewName.Trim();
            double[] forward, up;
            FtLogic.ViewVectors(viewType, out forward, out up);
            double[] eye = FtLogic.EyePosition(forward, 100.0);
            using (var t = new Transaction(doc, "Family Thumbnail - 3D view"))
            {
                t.Start();
                try
                {
                    View3D view = FindView3D(doc, name);
                    bool created = false;
                    if (view == null)
                    {
                        ElementId typeId = View3DTypeId(doc);
                        if (typeId == null) throw new Exception("This family has no 3D view type to create the thumbnail view from.");
                        view = View3D.CreateIsometric(doc, typeId);
                        try
                        {
                            view.Name = name;
                        }
                        catch (Exception err)
                        {
                            FtCore.Swallowed("ensure_thumbnail_view.rename", err);
                            view.Name = name + " (3D)";
                            notes.Add("view name already used by another kind of view");
                        }
                        created = true;
                    }
                    try
                    {
                        if (view.IsLocked) view.Unlock();
                    }
                    catch (Exception err)
                    {
                        FtCore.Swallowed("ensure_thumbnail_view.unlock", err);
                    }
                    view.SetOrientation(new ViewOrientation3D(new XYZ(eye[0], eye[1], eye[2]), new XYZ(up[0], up[1], up[2]),
                        new XYZ(forward[0], forward[1], forward[2])));
                    if (s.LockOrientation)
                    {
                        View3D locked = view;
                        TryStep("orientation could not be locked", () => locked.SaveOrientationAndLock(), notes);
                    }
                    t.Commit();
                    FtCore.Log("thumbnail view '" + view.Name + "' " + (created ? "created" : "updated"));
                    return view;
                }
                catch
                {
                    if (t.GetStatus() == TransactionStatus.Started)
                    {
                        try
                        {
                            t.RollBack();
                        }
                        catch (Exception err)
                        {
                            FtCore.Swallowed("ensure_thumbnail_view.rollback", err);
                        }
                    }
                    throw;
                }
            }
        }

        /// <summary>2D families (detail, annotation, profile): the family's own plan view.</summary>
        public static ViewPlan PickPlanView(Document doc, UIDocument uidoc)
        {
            try
            {
                var active = uidoc == null ? null : uidoc.ActiveView as ViewPlan;
                if (active != null && !active.IsTemplate) return active;
            }
            catch (Exception err)
            {
                FtCore.Swallowed("pick_plan_view.active", err);
            }
            ViewPlan first = null;
            foreach (ViewPlan view in new FilteredElementCollector(doc).OfClass(typeof(ViewPlan)))
            {
                try
                {
                    if (view.IsTemplate) continue;
                    if (first == null) first = view;
                    if (view.Name == "Ref. Level") return view;
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("pick_plan_view.item", err);
                }
            }
            return first;
        }

        /// <summary>
        /// Makes the view current and zooms to fit, so Revit's own thumbnail (taken from the active view) matches. A batch run
        /// works on family documents that are not open on screen: nothing to activate.
        /// </summary>
        public static void Activate(UIDocument uidoc, View view, List<string> notes)
        {
            if (uidoc == null) return;
            try
            {
                if (FtCore.Eid(uidoc.ActiveView.Id) != FtCore.Eid(view.Id))
                {
                    try
                    {
                        uidoc.ActiveView = view;
                    }
                    catch (Exception err)
                    {
                        FtCore.Swallowed("activate.ActiveView", err);
                        uidoc.RequestViewChange(view);
                    }
                }
            }
            catch (Exception err)
            {
                FtCore.Swallowed("activate", err);
                notes.Add("could not switch to the thumbnail view");
                return;
            }
            try
            {
                foreach (UIView uiView in uidoc.GetOpenUIViews())
                    if (FtCore.Eid(uiView.ViewId) == FtCore.Eid(view.Id)) uiView.ZoomToFit();
            }
            catch (Exception err)
            {
                FtCore.Swallowed("activate.ZoomToFit", err);
            }
        }

        // ---- temporary appearance ----------------------------------------------------------------------

        private static void HideElements(Document doc, View view, IEnumerable<ElementId> ids, string label, List<string> notes)
        {
            var hideable = new List<ElementId>();
            foreach (ElementId id in ids)
            {
                try
                {
                    Element element = doc.GetElement(id);
                    if (element != null && element.CanBeHidden(view)) hideable.Add(id);
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("hide_elements.item", err);
                }
            }
            if (hideable.Count > 0) TryStep("could not hide " + label, () => view.HideElements(hideable), notes);
            FtCore.Log("hid " + hideable.Count + " " + label);
        }

        private static List<ElementId> VoidIds(Document doc)
        {
            var ids = new List<ElementId>();
            var forms = new List<Type> { typeof(Extrusion), typeof(Blend), typeof(Revolution), typeof(Sweep), typeof(SweptBlend) };
            foreach (Type formClass in forms)
            {
                foreach (Element element in new FilteredElementCollector(doc).OfClass(formClass))
                {
                    try
                    {
                        var form = element as GenericForm;
                        if (form != null && !form.IsSolid) ids.Add(form.Id);
                    }
                    catch (Exception err)
                    {
                        FtCore.Swallowed("void_ids.item", err);
                    }
                }
            }
            return ids;
        }

        private static List<ElementId> HostIds(Document doc)
        {
            var categories = new List<BuiltInCategory>();
            foreach (string name in FtCore.HostCategoryNames)
            {
                BuiltInCategory member;
                if (Enum.TryParse(name, false, out member)) categories.Add(member);
            }
            var ids = new List<ElementId>();
            if (categories.Count == 0) return ids;
            foreach (Element element in new FilteredElementCollector(doc)
                         .WherePasses(new ElementMulticategoryFilter(categories)).WhereElementIsNotElementType())
                ids.Add(element.Id);
            return ids;
        }

        private static List<ElementId> ImportIds(Document doc)
        {
            var ids = new List<ElementId>();
            foreach (Element element in new FilteredElementCollector(doc).OfClass(typeof(ImportInstance))) ids.Add(element.Id);
            return ids;
        }

        /// <summary>Everything here happens inside the transaction that is rolled back after the export.</summary>
        public static void ApplyAppearance(Document doc, View view, FtSettings s, FtAppearance appearance, bool is3d, List<string> notes)
        {
            try
            {
                if (FtCore.Eid(view.ViewTemplateId) != FtCore.Eid(ElementId.InvalidElementId)) view.ViewTemplateId = ElementId.InvalidElementId;
            }
            catch (Exception err)
            {
                FtCore.Swallowed("apply_appearance.template", err);
            }

            string[] styleNames;
            if (!FtCore.StyleEnum.TryGetValue(appearance.Style ?? "", out styleNames)) styleNames = new string[0];
            DisplayStyle? style = FtCore.EnumMember<DisplayStyle>(styleNames);
            if (style.HasValue) TryStep("display style not applied", () => view.DisplayStyle = style.Value, notes);
            ViewDetailLevel? detail = FtCore.EnumMember<ViewDetailLevel>(appearance.Detail ?? "");
            if (detail.HasValue) TryStep("detail level not applied", () => view.DetailLevel = detail.Value, notes);
            TryStep("view scale not applied", () => view.Scale = appearance.Scale, notes);
            TryStep("crop region not hidden", () => view.CropBoxVisible = false, notes);

            foreach (KeyValuePair<string, string[]> rule in FtCore.HideRules)
            {
                if (!s.HideFlag(rule.Key)) continue;
                ElementId categoryId = BuiltInCategoryId(rule.Value);
                if (categoryId == null)
                {
                    FtCore.Log("category not in this release: " + rule.Value[0]);
                    continue;
                }
                try
                {
                    if (view.CanCategoryBeHidden(categoryId) && !view.GetCategoryHidden(categoryId)) view.SetCategoryHidden(categoryId, true);
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("hide category " + rule.Value[0], err);
                    notes.Add("could not hide " + rule.Value[0]);
                }
            }

            if (s.HideVoids) HideElements(doc, view, VoidIds(doc), "void elements", notes);
            if (s.HideHost) HideElements(doc, view, HostIds(doc), "host elements", notes);
            if (s.HideImported) HideElements(doc, view, ImportIds(doc), "imported elements", notes);

            var view3d = view as View3D;
            if (s.Gradient && is3d && view3d != null)
            {
                int sr, sg, sb, hr, hg, hb, gr, gg, gb;
                if (!FtLogic.ParseHex(s.GradSky, out sr, out sg, out sb)) { sr = sg = sb = 255; }
                if (!FtLogic.ParseHex(s.GradHorizon, out hr, out hg, out hb)) { hr = hg = hb = 255; }
                if (!FtLogic.ParseHex(s.GradGround, out gr, out gg, out gb)) { gr = gg = gb = 255; }
                TryStep("gradient background not applied", () =>
                {
                    ViewDisplayBackground background = ViewDisplayBackground.CreateGradient(
                        new Color((byte)sr, (byte)sg, (byte)sb), new Color((byte)hr, (byte)hg, (byte)hb), new Color((byte)gr, (byte)gg, (byte)gb));
                    view3d.SetBackground(background);
                }, notes);
            }
            doc.Regenerate();
        }

        // ---- export ------------------------------------------------------------------------------------

        public static void ExportView(Document doc, View view, string folder, int pixelSize)
        {
            var options = new ImageExportOptions
            {
                ExportRange = ExportRange.SetOfViews,
                FilePath = System.IO.Path.Combine(folder, "thumb"),
                ZoomType = ZoomFitType.FitToPage,
                PixelSize = pixelSize,
                FitDirection = FitDirectionType.Horizontal,
                ImageResolution = ImageResolution.DPI_150,
                HLRandWFViewsFileType = ImageFileType.PNG,
                ShadowViewsFileType = ImageFileType.PNG,
            };
            options.SetViewsAndSheets(new List<ElementId> { view.Id });
            doc.ExportImage(options);
        }

        /// <summary>A void API call is not evidence: find the file that actually landed.</summary>
        private static string ExportedFile(string folder)
        {
            string best = null;
            long bestSize = -1;
            foreach (string path in Directory.GetFiles(folder))
            {
                if (Array.IndexOf(ImageExtensions, System.IO.Path.GetExtension(path).ToLowerInvariant()) < 0) continue;
                long size = new FileInfo(path).Length;
                if (size > bestSize)
                {
                    best = path;
                    bestSize = size;
                }
            }
            return bestSize > 0 ? best : null;
        }

        private static void DeleteFolder(string folder)
        {
            try
            {
                Directory.Delete(folder, true);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Applies the appearance, exports, rolls the appearance back. Returns the raw exported file and its temp folder.</summary>
        public static string ExportWithTemporaryAppearance(Document doc, View view, FtSettings s, FtAppearance appearance, bool is3d,
            List<string> notes, out string tempDir)
        {
            tempDir = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "revobim_ft_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(tempDir);
            int pixelSize = Math.Min(4096, s.ImageSize * 2); // exported large, scaled down for a crisp result
            using (var t = new Transaction(doc, "Family Thumbnail - temporary appearance"))
            {
                t.Start();
                try
                {
                    ApplyAppearance(doc, view, s, appearance, is3d, notes);
                    ExportView(doc, view, tempDir, pixelSize);
                }
                finally
                {
                    if (t.GetStatus() == TransactionStatus.Started)
                    {
                        try
                        {
                            t.RollBack();
                        }
                        catch (Exception err)
                        {
                            FtCore.Swallowed("export_with_temporary_appearance.rollback", err);
                        }
                    }
                }
            }
            string raw = ExportedFile(tempDir);
            if (raw == null)
            {
                DeleteFolder(tempDir);
                throw new Exception("Revit did not write an image file.");
            }
            return raw;
        }

        /// <summary>Crops and resizes the raw export and saves it as family name + extension in the export folder.</summary>
        public static string FinishImage(string rawPath, FtSettings s, string familyName, List<string> notes, string categoryName)
        {
            string folder = FtCore.OutputFolder(s, categoryName);
            Directory.CreateDirectory(folder);
            string extension = string.Equals(s.ImageFormat, "JPG", StringComparison.OrdinalIgnoreCase) ? ".jpg" : ".png";
            string destination = System.IO.Path.Combine(folder, familyName + extension);
            if (File.Exists(destination)) File.Delete(destination);
            try
            {
                FtImage.Process(rawPath, destination, s.ImageSize, s.FitMode, s.ImageFormat);
            }
            catch (Exception err)
            {
                FtCore.Swallowed("finish_image.process", err);
                notes.Add("image could not be cropped, saved as exported");
                destination = System.IO.Path.Combine(folder, familyName + ".png");
                File.Copy(rawPath, destination, true);
            }
            if (!File.Exists(destination) || new FileInfo(destination).Length == 0)
                throw new Exception("The thumbnail was not written to " + folder);
            return destination;
        }

        // ---- the whole run -----------------------------------------------------------------------------

        /// <summary>Update Current: the family open on screen.</summary>
        public static FtResult RunUpdate(UIApplication uiapp, FtSettings s)
        {
            UIDocument uidoc = uiapp.ActiveUIDocument;
            return UpdateDocument(uidoc.Document, uidoc, s);
        }

        /// <summary>
        /// Fills the parameters (if enabled), creates or updates the view, applies the appearance temporarily and exports.
        /// uidoc is null for a family opened in the background by the batch run.
        /// </summary>
        public static FtResult UpdateDocument(Document doc, UIDocument uidoc, FtSettings s)
        {
            FamilyInfo info = InfoOf(doc);
            bool is3d = !info.Is2D;
            FtAppearance appearance = s.ResolveAppearance(info.Category, is3d);
            var result = new FtResult { Family = info.Name, Category = info.Category, Override = appearance.Override };
            List<string> notes = result.Notes;
            View previousView = uidoc == null ? null : uidoc.ActiveView;
            if (s.FillParams)
            {
                try
                {
                    result.Applied = FillParameters(doc, s, notes);
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("update_document.fill_parameters", err);
                    notes.Add("family parameters were not filled in");
                }
            }
            FtCore.Log("family '" + info.Name + "' category '" + info.Category + "' 3D=" + is3d + " appearance=" + appearance.ViewType + " / "
                       + appearance.Style + " / " + appearance.Detail + " / 1:" + appearance.Scale
                       + (appearance.Override == null ? "" : " (override " + appearance.Override + ")"));

            View view;
            if (is3d) view = EnsureThumbnailView(doc, s, appearance.ViewType, notes);
            else
            {
                view = PickPlanView(doc, uidoc);
                if (view == null)
                {
                    result.Message = "This 2D family has no plan view to take a thumbnail from.";
                    return result;
                }
            }
            result.ViewName = view.Name;
            Activate(uidoc, view, notes);

            if (!s.ExportImages)
            {
                result.Ok = true;
                result.Message = "Thumbnail view updated.";
                return result;
            }

            string tempDir;
            string raw = ExportWithTemporaryAppearance(doc, view, s, appearance, is3d, notes, out tempDir);
            try
            {
                result.Path = FinishImage(raw, s, info.Name, notes, info.Category);
                result.Ok = true;
            }
            finally
            {
                DeleteFolder(tempDir);
            }

            if (uidoc != null && !s.LeaveOpen && previousView != null)
            {
                try
                {
                    uidoc.ActiveView = previousView;
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("run_update.restore_view", err);
                }
            }
            return result;
        }

        // ---- family parameters: creator, revision, date (text shared parameters chosen in Settings) ----

        /// <summary>Plain text parameter. Multiline text is a different type and is not offered.</summary>
        private static bool IsTextDefinition(Definition defn)
        {
            try
            {
                return defn.GetDataType() == SpecTypeId.String.Text;
            }
            catch (Exception err)
            {
                FtCore.Swallowed("is_text_definition", err);
                return false;
            }
        }

        /// <summary>
        /// Points Revit at the shared parameter file and reads its text definitions. restore() puts Revit's own shared
        /// parameter file back and must be called once the definitions have been used (a family needs them while it is being
        /// given a parameter).
        /// </summary>
        private static Dictionary<string, ExternalDefinition> OpenShared(Application app, string path, out string note, out Action restore)
        {
            string original = "";
            try
            {
                original = app.SharedParametersFilename ?? "";
            }
            catch (Exception err)
            {
                FtCore.Swallowed("open_shared.original", err);
            }
            string originalCopy = original;
            restore = () =>
            {
                try
                {
                    app.SharedParametersFilename = originalCopy;
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("open_shared.restore", err);
                }
            };
            var found = new Dictionary<string, ExternalDefinition>();
            note = "";
            try
            {
                app.SharedParametersFilename = path;
                DefinitionFile file = app.OpenSharedParameterFile();
                if (file == null) note = "The shared parameter file could not be opened: " + path;
                else
                {
                    foreach (DefinitionGroup group in file.Groups)
                        foreach (Definition defn in group.Definitions)
                        {
                            var external = defn as ExternalDefinition;
                            if (external != null && IsTextDefinition(defn)) found[defn.Name] = external;
                        }
                    if (found.Count == 0) note = "The shared parameter file has no text parameters: " + path;
                }
            }
            catch (Exception err)
            {
                FtCore.Swallowed("open_shared.read", err);
                note = "The shared parameter file could not be read: " + path;
            }
            return found;
        }

        /// <summary>The text parameter names of a shared parameter file, and a one-line note, for the Settings window. Revit's own file setting is left as it was.</summary>
        public static List<string> SharedDefinitions(Application app, string path, out string note)
        {
            string openNote;
            Action restore;
            Dictionary<string, ExternalDefinition> found = OpenShared(app, path, out openNote, out restore);
            restore();
            bool isDefault = string.Equals(System.IO.Path.GetFullPath(path), System.IO.Path.GetFullPath(FtCore.BundledSharedFile()),
                StringComparison.OrdinalIgnoreCase);
            string where = isDefault ? "built-in file" : path;
            note = openNote.Length > 0 ? openNote : found.Count + " text parameters from the " + where;
            return new List<string>(found.Keys);
        }

        private static FamilyParameter FindFamilyParameter(FamilyManager fm, string name)
        {
            foreach (FamilyParameter parameter in fm.Parameters)
            {
                try
                {
                    if (parameter.Definition.Name == name) return parameter;
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("find_family_parameter.item", err);
                }
            }
            return null;
        }

        private static string CurrentText(FamilyManager fm, FamilyParameter parameter)
        {
            try
            {
                FamilyType current = fm.CurrentType;
                if (current != null) return current.AsString(parameter);
            }
            catch (Exception err)
            {
                FtCore.Swallowed("current_text", err);
            }
            return null;
        }

        /// <summary>Sets the value on every family type (a family with no types has just the one current set).</summary>
        private static void SetTextEverywhere(FamilyManager fm, FamilyParameter parameter, string value)
        {
            var types = new List<FamilyType>();
            foreach (FamilyType type in fm.Types) types.Add(type);
            if (types.Count == 0)
            {
                fm.Set(parameter, value);
                return;
            }
            FamilyType original = fm.CurrentType;
            foreach (FamilyType type in types)
            {
                fm.CurrentType = type;
                fm.Set(parameter, value);
            }
            if (original != null) fm.CurrentType = original;
        }

        /// <summary>
        /// Creator, revision (next MAJOR.MINOR.PATCH) and date (YYYY-MM-DD) into the three parameters chosen in Settings. A
        /// parameter the family lacks is added (Identity Data) from the chosen shared parameter file, the built-in
        /// BIM_Family_Parameters.txt unless Settings names another. Returns the values written, by parameter name, so the batch
        /// run can repeat them on the project's loaded types.
        /// </summary>
        public static Dictionary<string, string> FillParameters(Document doc, FtSettings s, List<string> notes)
        {
            var applied = new Dictionary<string, string>();
            if (!doc.IsFamilyDocument) return applied;
            FamilyManager fm = doc.FamilyManager;
            DateTime today = DateTime.Today;
            string creator = s.CreatorValue.Trim().Length > 0 ? s.CreatorValue.Trim() : doc.Application.Username;
            bool isDefault;
            string fileNote;
            string filePath = FtCore.ResolveSharedFile(s, out isDefault, out fileNote);
            if (fileNote.Length > 0) notes.Add(fileNote);
            Dictionary<string, ExternalDefinition> opened = null; // read lazily, only if a parameter is missing from the family
            Action restore = null;
            using (var t = new Transaction(doc, "Family Thumbnail - parameters"))
            {
                t.Start();
                try
                {
                    var plan = new[]
                    {
                        new KeyValuePair<string, string>(s.ParamCreator, ""),
                        new KeyValuePair<string, string>(s.ParamRevision, "revision"),
                        new KeyValuePair<string, string>(s.ParamDate, "date"),
                    };
                    foreach (KeyValuePair<string, string> item in plan)
                    {
                        string name = (item.Key ?? "").Trim();
                        if (name.Length == 0) continue;
                        FamilyParameter parameter = FindFamilyParameter(fm, name);
                        string existing = null;
                        if (parameter == null)
                        {
                            if (opened == null)
                            {
                                string openNote;
                                opened = OpenShared(doc.Application, filePath, out openNote, out restore);
                                if (openNote.Length > 0) notes.Add(openNote);
                            }
                            ExternalDefinition defn;
                            if (!opened.TryGetValue(name, out defn))
                            {
                                notes.Add(name + " is not in the family or the shared parameter file");
                                continue;
                            }
                            parameter = fm.AddParameter(defn, GroupTypeId.IdentityData, false);
                        }
                        else existing = CurrentText(fm, parameter);
                        try
                        {
                            if (parameter.StorageType != StorageType.String || parameter.IsReadOnly)
                            {
                                notes.Add(name + " is not an editable text parameter");
                                continue;
                            }
                            if (!string.IsNullOrEmpty(parameter.Formula))
                            {
                                notes.Add(name + " is driven by a formula");
                                continue;
                            }
                        }
                        catch (Exception err)
                        {
                            FtCore.Swallowed("fill_parameters.check", err);
                        }
                        string value;
                        if (item.Value == "revision") value = FtLogic.NextRevision(existing, s.RevisionStep);
                        else if (item.Value == "date") value = FtLogic.DateText(today.Year, today.Month, today.Day);
                        else value = creator;
                        SetTextEverywhere(fm, parameter, value);
                        applied[name] = value;
                    }
                    t.Commit();
                }
                catch
                {
                    if (t.GetStatus() == TransactionStatus.Started)
                    {
                        try
                        {
                            t.RollBack();
                        }
                        catch (Exception err)
                        {
                            FtCore.Swallowed("fill_parameters.rollback", err);
                        }
                    }
                    throw;
                }
                finally
                {
                    if (restore != null) restore();
                }
            }
            var written = new List<string>();
            foreach (KeyValuePair<string, string> pair in applied) written.Add(pair.Key + "=" + pair.Value);
            FtCore.Log("parameters written: " + string.Join(", ", written.ToArray()));
            return applied;
        }

        /// <summary>Repeats the written values on the project's family types, whatever the load options did to them.</summary>
        public static void ApplyToLoadedFamily(Document doc, Family family, Dictionary<string, string> applied, List<string> notes)
        {
            if (applied == null || applied.Count == 0 || family == null) return;
            using (var t = new Transaction(doc, "Family Thumbnail - parameters on types"))
            {
                t.Start();
                try
                {
                    foreach (ElementId symbolId in family.GetFamilySymbolIds())
                    {
                        Element symbol = doc.GetElement(symbolId);
                        if (symbol == null) continue;
                        foreach (KeyValuePair<string, string> pair in applied)
                        {
                            Parameter parameter = symbol.LookupParameter(pair.Key);
                            if (parameter == null || parameter.IsReadOnly || parameter.StorageType != StorageType.String) continue;
                            if (parameter.AsString() != pair.Value) parameter.Set(pair.Value);
                        }
                    }
                    t.Commit();
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("apply_to_loaded_family", err);
                    notes.Add("parameter values could not be set on the project types");
                    try
                    {
                        if (t.GetStatus() == TransactionStatus.Started) t.RollBack();
                    }
                    catch (Exception err2)
                    {
                        FtCore.Swallowed("apply_to_loaded_family.rollback", err2);
                    }
                }
            }
        }
    }
}
