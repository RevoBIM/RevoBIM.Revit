using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.ProSheets
{
    /// <summary>ps_export.py, continued: DWG, NWC and IFC.</summary>
    public static partial class PsExport
    {
        // ======================================================================
        // DWG
        // ======================================================================

        /// <summary>DWG options from a saved export setup, or sensible defaults.</summary>
        public static DWGExportOptions BuildDwgOptions(Document doc, IDictionary<string, string> profile, List<string> log = null)
        {
            DWGExportOptions options = null;
            string setupName = Text(profile, "dwg.setup");
            if (setupName.Length > 0)
            {
                try
                {
                    ExportDWGSettings settings = ExportDWGSettings.FindByName(doc, setupName);
                    if (settings != null)
                        options = settings.GetDWGExportOptions();
                    else
                        log?.Add(string.Format(Inv,
                            "DWG export setup \"{0}\" is not in this model; the default settings were used instead", setupName));
                }
                catch (Exception err)
                {
                    log?.Add(string.Format(Inv, "could not read DWG setup \"{0}\": {1}", setupName, Msg(err)));
                }
            }
            if (options == null)
            {
                try
                {
                    options = new DWGExportOptions();
                }
                catch (Exception err)
                {
                    log?.Add("no DWG exporter on this Revit: " + Msg(err));
                    return null;
                }
            }

            // Revit's own "Export views on sheets and links as external references" is
            // MergedViews inverted: merged means everything bound into one DWG, unmerged
            // means views and links become XREFs. The profile stores the checkbox as the
            // user sees it, so it is flipped here once rather than everywhere it is read.
            bool asXrefs = Flag(profile, "dwg.external_refs", false);
            SetDirect(null, "MergedViews", () => options.MergedViews = !asXrefs);
            Debug("DWG: links and views " + (asXrefs ? "as external references" : "bound into the DWG"));
            SetDirect(null, "SharedCoords", () => options.SharedCoords = Flag(profile, "dwg.shared_coords", true));

            string version = Text(profile, "dwg.version", "default");
            if (version.Length > 0 && version != "default")
            {
                foreach (string member in new[] { version.ToUpperInvariant(), version })
                {
                    if (Enum.IsDefined(typeof(ACADVersion), member))
                    {
                        var chosen = (ACADVersion)Enum.Parse(typeof(ACADVersion), member);
                        SetDirect(log, "FileVersion", () => options.FileVersion = chosen);
                        break;
                    }
                }
            }
            return options;
        }

        /// <summary>
        /// One DWG per job. Exported one view at a time rather than in a batch, for the same
        /// reason the PDFs are: a batch hands the naming back to Revit, which appends the view
        /// name to a prefix and ignores the custom naming entirely.
        /// </summary>
        public static Report ExportDwg(Document doc, IList<Job> jobs, IDictionary<string, string> profile,
                                       Action<int, int, string, string> progress = null,
                                       Func<bool> shouldStop = null, Report report = null)
        {
            report = report ?? new Report();
            var log = new List<string>();
            int total = jobs.Count;

            DWGExportOptions options = BuildDwgOptions(doc, profile, log);
            if (options == null)
            {
                foreach (Job job in jobs)
                    report.Add(new Outcome(job.Key, job.Label, "DWG", "", false, "no DWG exporter available"));
                foreach (string line in log)
                    report.Note(line);
                return report;
            }

            for (int index = 1; index <= total; index++)
            {
                Job job = jobs[index - 1];
                if (shouldStop != null && shouldStop())
                {
                    report.Cancelled = true;
                    break;
                }
                progress?.Invoke(index, total, job.Label, "DWG");

                string folder = job.FolderFor("dwg");
                var (made, error) = PsPaths.Ensure(folder);
                if (!made)
                {
                    report.Add(new Outcome(job.Key, job.Label, "DWG", "", false, "folder could not be made: " + error));
                    continue;
                }

                string baseName = job.BaseName;
                string target = PathJoin(folder, baseName + ".dwg");
                if (Flag(profile, "out.overwrite", true))
                {
                    RemoveIfPresent(target);
                }
                else
                {
                    target = PsPaths.UniqueOnDisk(folder, baseName, ".dwg");
                    baseName = SplitextStem(Basename(target));
                }

                try
                {
                    doc.Export(folder, baseName, IdList(new[] { job.ElementId }), options);
                }
                catch (Exception err)
                {
                    report.Add(new Outcome(job.Key, job.Label, "DWG", target, false, Msg(err)));
                    continue;
                }

                bool landed = WaitFor(target);
                if (!landed)
                {
                    // Revit sometimes decorates the name with the view type when it is
                    // exporting a view rather than a sheet. Take whichever file it actually
                    // made and rename it, rather than reporting a failure for a file that is
                    // sitting right there under another name.
                    landed = ClaimStrayDwg(folder, baseName, target);
                }
                report.Add(new Outcome(job.Key, job.Label, "DWG", target, landed,
                                       landed ? "" : "Revit reported no error but no file appeared"));
            }

            foreach (string line in log)
                report.Note(line);
            return report;
        }

        internal static bool ClaimStrayDwg(string folder, string baseName, string target)
        {
            try
            {
                string targetName = Basename(target);
                foreach (string entry in ListDir(folder))
                {
                    if (!entry.ToLowerInvariant().EndsWith(".dwg", StringComparison.Ordinal))
                        continue;
                    if (entry.ToLowerInvariant().StartsWith(baseName.ToLowerInvariant(), StringComparison.Ordinal) &&
                        entry != targetName)
                    {
                        File.Move(PathJoin(folder, entry), target);
                        return File.Exists(target);
                    }
                }
            }
            catch (Exception)
            {
            }
            return false;
        }

        // ======================================================================
        // NWC
        //
        // One NWC per ticked 3D view. Navisworks export is scoped to a view and there
        // is no such thing as exporting a sheet, which is why the tile is only live
        // when a 3D view is ticked.
        //
        // NavisworksExportOptions lives in RevitAPI.dll whether or not the exporter
        // add-in is installed, so the type being there proves nothing; the export
        // itself is what fails, and it fails per view. The first failure stops the run
        // rather than repeating the same message once per view.
        // ======================================================================

        public static readonly Dictionary<string, string[]> NwcParameterModes =
            new Dictionary<string, string[]>(StringComparer.Ordinal)
            {
                { "all", new[] { "All" } },
                { "elements", new[] { "Elements" } },
                { "none", new[] { "None" } },
            };

        public static readonly Dictionary<string, string[]> NwcCoordinateModes =
            new Dictionary<string, string[]>(StringComparer.Ordinal)
            {
                { "shared", new[] { "Shared" } },
                { "internal", new[] { "Internal" } },
            };

        internal static T? FirstDefined<T>(IEnumerable<string> names) where T : struct
        {
            foreach (string name in names)
            {
                if (name != null && Enum.IsDefined(typeof(T), name))
                    return (T)Enum.Parse(typeof(T), name);
            }
            return null;
        }

        /// <summary>Navisworks export options from the profile, or null if unavailable.</summary>
        public static NavisworksExportOptions BuildNwcOptions(IDictionary<string, string> profile,
                                                              ElementId viewId = null, List<string> log = null)
        {
            NavisworksExportOptions options;
            try
            {
                options = new NavisworksExportOptions();
            }
            catch (Exception err)
            {
                log?.Add("no Navisworks exporter on this Revit: " + Msg(err));
                return null;
            }

            SetDirect(log, "ExportParts", () => options.ExportParts = Flag(profile, "nwc.parts", false));
            SetDirect(log, "ExportElementIds", () => options.ExportElementIds = Flag(profile, "nwc.element_ids", true));
            SetDirect(log, "ConvertElementProperties", () => options.ConvertElementProperties = Flag(profile, "nwc.properties", false));
            SetDirect(log, "ExportLinks", () => options.ExportLinks = Flag(profile, "nwc.linked_files", false));
            SetDirect(log, "ExportRoomAsAttribute", () => options.ExportRoomAsAttribute = Flag(profile, "nwc.room_as_attribute", true));
            SetDirect(log, "ExportUrls", () => options.ExportUrls = Flag(profile, "nwc.urls", true));
            SetDirect(log, "DivideFileIntoLevels", () => options.DivideFileIntoLevels = Flag(profile, "nwc.divide_levels", true));
            SetDirect(log, "ExportRoomGeometry", () => options.ExportRoomGeometry = Flag(profile, "nwc.room_geometry", true));
            SetDirect(log, "FindMissingMaterials", () => options.FindMissingMaterials = Flag(profile, "nwc.find_materials", true));
            SetDirect(null, "ConvertLinkedCADFormats", () => options.ConvertLinkedCADFormats = Flag(profile, "nwc.linked_cad", true));
            SetDirect(null, "ConvertLights", () => options.ConvertLights = Flag(profile, "nwc.lights", false));

            double faceting = Number(profile, "nwc.faceting", 1.0);
            if (faceting > 0)
                SetDirect(null, "FacetingFactor", () => options.FacetingFactor = faceting);

            string mode = Text(profile, "nwc.parameters", "all").ToLowerInvariant();
            NavisworksParameters? parametersMember = FirstDefined<NavisworksParameters>(
                NwcParameterModes.TryGetValue(mode, out string[] parameterNames) ? parameterNames : new[] { "All" });
            if (parametersMember != null)
                SetDirect(log, "Parameters", () => options.Parameters = parametersMember.Value);

            string coords = Text(profile, "nwc.coordinates", "shared").ToLowerInvariant();
            NavisworksCoordinates? coordsMember = FirstDefined<NavisworksCoordinates>(
                NwcCoordinateModes.TryGetValue(coords, out string[] coordNames) ? coordNames : new[] { "Shared" });
            if (coordsMember != null)
                SetDirect(log, "Coordinates", () => options.Coordinates = coordsMember.Value);

            if (viewId != null)
            {
                SetDirect(log, "ExportScope", () => options.ExportScope = NavisworksExportScope.View);
                SetDirect(log, "ViewId", () => options.ViewId = viewId);
            }
            return options;
        }

        /// <summary>One NWC per job, each scoped to that job's own 3D view.</summary>
        public static Report ExportNwc(Document doc, IList<Job> jobs, IDictionary<string, string> profile,
                                       Action<int, int, string, string> progress = null,
                                       Func<bool> shouldStop = null, Report report = null)
        {
            report = report ?? new Report();
            var log = new List<string>();
            int total = jobs.Count;
            bool refused = false;

            for (int index = 1; index <= total; index++)
            {
                Job job = jobs[index - 1];
                if (shouldStop != null && shouldStop())
                {
                    report.Cancelled = true;
                    break;
                }
                progress?.Invoke(index, total, job.Label, "NWC");

                if (refused)
                {
                    report.Add(new Outcome(job.Key, job.Label, "NWC", "", false,
                                           "skipped: the Navisworks exporter refused the first view"));
                    continue;
                }

                NavisworksExportOptions options = BuildNwcOptions(profile, job.ElementId, log);
                if (options == null)
                {
                    report.Add(new Outcome(job.Key, job.Label, "NWC", "", false,
                                           "the Navisworks exporter is not installed on this machine"));
                    refused = true;
                    continue;
                }

                string folder = job.FolderFor("nwc");
                var (made, error) = PsPaths.Ensure(folder);
                if (!made)
                {
                    report.Add(new Outcome(job.Key, job.Label, "NWC", "", false, "folder could not be made: " + error));
                    continue;
                }

                string baseName = job.BaseName;
                string target = PathJoin(folder, baseName + ".nwc");
                if (Flag(profile, "out.overwrite", true))
                {
                    RemoveIfPresent(target);
                }
                else
                {
                    target = PsPaths.UniqueOnDisk(folder, baseName, ".nwc");
                    baseName = SplitextStem(Basename(target));
                }

                Debug(string.Format(Inv, "NWC: exporting \"{0}\" to {1}", job.Label, target));
                try
                {
                    doc.Export(folder, baseName, options);
                }
                catch (Exception err)
                {
                    string message = Msg(err);
                    report.Add(new Outcome(job.Key, job.Label, "NWC", target, false, message));
                    Debug("NWC: export threw - " + message);
                    // A missing exporter throws identically on every view, so one failure
                    // is enough to know the rest will fail the same way.
                    string lowered = message.ToLowerInvariant();
                    if (lowered.Contains("exporter") || lowered.Contains("not supported"))
                    {
                        refused = true;
                        report.Note("The Navisworks exporter add-in does not appear to be installed for this Revit. " +
                                    "It ships with Navisworks Manage and Simulate, not with Revit itself.");
                    }
                    continue;
                }

                bool landed = WaitFor(target);
                report.Add(new Outcome(job.Key, job.Label, "NWC", target, landed,
                                       landed ? "" : "Revit reported no error but no file appeared"));
            }

            foreach (string line in log)
                report.Note(line);
            return report;
        }

        // ======================================================================
        // IFC
        //
        // IFCExportOptions carries only five typed properties; everything else the
        // Revit IFC dialog offers is a named option read by the open source exporter.
        // AddOption with a name the installed exporter does not know is ignored rather
        // than throwing, so a newer option name on an older exporter costs nothing.
        //
        // The export itself has to sit inside a transaction. Without one Revit 2024 and
        // later raise "Starting a transaction is required", and the message names
        // neither IFC nor the view.
        // ======================================================================

        public static readonly List<(string Key, string Label, string[] Names)> IfcVersions =
            new List<(string Key, string Label, string[] Names)>
            {
                ("IFC2x3CV2", "IFC 2x3 Coordination View 2.0", new[] { "IFC2x3CV2", "IFC2x3CoordinationView2" }),
                ("IFC2x3", "IFC 2x3 Coordination View", new[] { "IFC2x3" }),
                ("IFCBCA", "IFC 2x3 GSA Concept Design BIM 2010", new[] { "IFCBCA" }),
                ("IFC2x3FM", "IFC 2x3 Basic FM Handover View", new[] { "IFC2x3FM" }),
                ("IFC2x2", "IFC 2x2 Coordination View", new[] { "IFC2x2" }),
                ("IFC2x3COBIE", "IFC 2x3 COBie 2.4 Design Deliverable", new[] { "IFC2x3COBIE", "IFCCOBIE" }),
                ("IFC4RV", "IFC 4 Reference View", new[] { "IFC4RV" }),
                ("IFC4DTV", "IFC 4 Design Transfer View", new[] { "IFC4DTV" }),
                ("IFC4", "IFC 4", new[] { "IFC4" }),
            };

        public static readonly List<(string Key, string Label, string Suffix)> IfcFileTypes =
            new List<(string Key, string Label, string Suffix)>
            {
                ("ifc", "IFC", ".ifc"),
                ("ifcxml", "IFC XML", ".ifcXML"),
                ("ifczip", "Zipped IFC", ".ifcZIP"),
                ("ifcxmlzip", "Zipped IFC XML", ".ifcZIP"),
            };

        public static readonly List<(string Key, string Label, string Value)> IfcDetailLevels =
            new List<(string Key, string Label, string Value)>
            {
                ("extralow", "Extra Low", "0.0"),
                ("low", "Low", "0.2"),
                ("medium", "Medium", "0.5"),
                ("high", "High", "1.0"),
            };

        public static readonly List<(string Key, string Label, string Value)> IfcOrigins =
            new List<(string Key, string Label, string Value)>
            {
                ("shared", "Current Shared Coordinates", "0"),
                ("survey", "Site Survey Point", "1"),
                ("project", "Project Base Point", "2"),
                ("internal", "Internal Coordinates", "3"),
            };

        public static string IfcExtension(IDictionary<string, string> profile)
        {
            string wanted = Text(profile, "ifc.file_type", "ifc").ToLowerInvariant();
            foreach (var (key, _, suffix) in IfcFileTypes)
            {
                if (key == wanted)
                    return suffix;
            }
            return ".ifc";
        }

        /// <summary>Column 1 = label, 2 = value, of the row whose key is <paramref name="wanted"/>.</summary>
        internal static string IfcLookup(IList<(string Key, string Label, string Value)> table, string wanted,
                                         int column, string fallback)
        {
            foreach (var row in table)
            {
                if (row.Key == wanted)
                    return column == 0 ? row.Key : column == 1 ? row.Label : row.Value;
            }
            return fallback;
        }

        /// <summary>IfcLookup over IfcVersions, column 2 (the enum spellings).</summary>
        internal static string[] IfcLookup(IList<(string Key, string Label, string[] Names)> table, string wanted,
                                           string[] fallback)
        {
            foreach (var row in table)
            {
                if (row.Key == wanted)
                    return row.Names;
            }
            return fallback;
        }

        /// <summary>IFC export options: five typed properties plus the named options.</summary>
        public static IFCExportOptions BuildIfcOptions(Document doc, IDictionary<string, string> profile,
                                                       ElementId viewId = null, List<string> log = null)
        {
            IFCExportOptions options;
            try
            {
                options = new IFCExportOptions();
            }
            catch (Exception err)
            {
                log?.Add("no IFC exporter on this Revit: " + Msg(err));
                return null;
            }

            string wanted = Text(profile, "ifc.version", "IFC2x3CV2");
            string[] names = IfcLookup(IfcVersions, wanted, new[] { "IFC2x3CV2" });
            IFCVersion? member = FirstDefined<IFCVersion>(names);
            if (member != null)
                SetDirect(log, "FileVersion", () => options.FileVersion = member.Value);
            else
                log?.Add(string.Format(Inv, "this Revit does not offer IFC version \"{0}\"; the exporter default was used", wanted));

            try
            {
                string level = Text(profile, "ifc.space_boundaries", "0");
                options.SpaceBoundaryLevel = int.Parse(level.Length > 0 ? level : "0", NumberStyles.Integer, Inv);
            }
            catch (Exception)
            {
            }
            SetDirect(null, "ExportBaseQuantities", () => options.ExportBaseQuantities = Flag(profile, "ifc.base_quantities", false));
            SetDirect(null, "WallAndColumnSplitting", () => options.WallAndColumnSplitting = Flag(profile, "ifc.split_by_level", false));

            bool visibleOnly = Flag(profile, "ifc.visible_only", true);
            if (visibleOnly && viewId != null)
                SetDirect(log, "FilterViewId", () => options.FilterViewId = viewId);

            void Option(string name, string value)
            {
                try
                {
                    options.AddOption(name, value ?? "None");
                }
                catch (Exception err)
                {
                    log?.Add(string.Format(Inv, "IFC option \"{0}\" was refused: {1}", name, Msg(err)));
                }
            }

            void Switch(string name, string key, bool defaultValue = false)
            {
                Option(name, Flag(profile, key, defaultValue) ? "true" : "false");
            }

            Switch("VisibleElementsOfCurrentView", "ifc.visible_only", true);
            Switch("ExportAnnotations", "ifc.export_2d", false);
            Switch("ExportRoomsInView", "ifc.rooms_in_3d", false);
            Switch("IncludeSteelElements", "ifc.steel", true);
            Switch("ExportInternalRevitPropertySets", "ifc.revit_psets", false);
            Switch("ExportIFCCommonPropertySets", "ifc.common_psets", true);
            Switch("ExportMaterialPsets", "ifc.material_psets", false);
            Switch("ExportSchedulesAsPsets", "ifc.schedule_psets", false);
            Switch("ExportSpecificSchedules", "ifc.specific_schedules", false);
            Switch("ExportUserDefinedPsets", "ifc.user_psets", false);
            Switch("UseTypePropertiesInInstacePSets", "ifc.type_properties", false);
            Switch("ExportUserDefinedParameterMapping", "ifc.parameter_map", false);
            Switch("ExportPartsAsBuildingElements", "ifc.parts_as_elements", false);
            Switch("ExportSolidModelRep", "ifc.solid_model", false);
            Switch("UseActiveViewGeometry", "ifc.active_view_geometry", false);
            Switch("UseFamilyAndTypeNameForReference", "ifc.family_type_reference", false);
            Switch("Use2DRoomBoundaryForVolume", "ifc.room_boundary_2d", false);
            Switch("IncludeSiteElevation", "ifc.site_elevation", false);
            Switch("StoreIFCGUID", "ifc.store_guid", false);
            Switch("ExportBoundingBox", "ifc.bounding_box", false);
            Switch("UseOnlyTriangulation", "ifc.triangulation", false);
            Switch("UseTypeNameOnlyForIfcType", "ifc.type_name_only", false);
            Switch("UseVisibleRevitNameAsEntityName", "ifc.visible_name", false);

            // "Linked Files" is a dropdown in Revit's dialog and a boolean in the exporter,
            // so it is mapped here rather than stored as a flag.
            bool separate = Text(profile, "ifc.linked_files", "none").ToLowerInvariant() == "separate";
            Option("ExportLinkedFiles", separate ? "true" : "false");

            Option("TessellationLevelOfDetail",
                   IfcLookup(IfcDetailLevels, Text(profile, "ifc.detail", "low").ToLowerInvariant(), 2, "0.2"));
            Option("SitePlacement",
                   IfcLookup(IfcOrigins, Text(profile, "ifc.origin", "shared").ToLowerInvariant(), 2, "0"));
            Option("SpaceBoundaries", Text(profile, "ifc.space_boundaries", "0"));

            string psetsFile = Text(profile, "ifc.user_psets_file", "");
            if (psetsFile.Length > 0)
                Option("ExportUserDefinedPsetsFileName", psetsFile);
            string mapFile = Text(profile, "ifc.parameter_map_file", "");
            if (mapFile.Length > 0)
                Option("ExportUserDefinedParameterMappingFileName", mapFile);

            // The id, not the name: ActivePhaseId wants an element id, and the name is
            // only what travels in a template between models.
            string phase = Text(profile, "ifc.phase_id", "");
            if (phase.Length > 0)
                Option("ActivePhaseId", phase);
            return options;
        }

        /// <summary>One IFC per job, inside its own transaction.</summary>
        public static Report ExportIfc(Document doc, IList<Job> jobs, IDictionary<string, string> profile,
                                       Action<int, int, string, string> progress = null,
                                       Func<bool> shouldStop = null, Report report = null)
        {
            report = report ?? new Report();
            var log = new List<string>();
            int total = jobs.Count;
            string suffix = IfcExtension(profile);

            for (int index = 1; index <= total; index++)
            {
                Job job = jobs[index - 1];
                if (shouldStop != null && shouldStop())
                {
                    report.Cancelled = true;
                    break;
                }
                progress?.Invoke(index, total, job.Label, "IFC");

                IFCExportOptions options = BuildIfcOptions(doc, profile, job.ElementId, log);
                if (options == null)
                {
                    report.Add(new Outcome(job.Key, job.Label, "IFC", "", false, "no IFC exporter available on this Revit"));
                    break;
                }

                string folder = job.FolderFor("ifc");
                var (made, error) = PsPaths.Ensure(folder);
                if (!made)
                {
                    report.Add(new Outcome(job.Key, job.Label, "IFC", "", false, "folder could not be made: " + error));
                    continue;
                }

                string baseName = job.BaseName;
                string target = PathJoin(folder, baseName + suffix);
                if (Flag(profile, "out.overwrite", true))
                {
                    RemoveIfPresent(target);
                }
                else
                {
                    target = PsPaths.UniqueOnDisk(folder, baseName, suffix);
                    baseName = SplitextStem(Basename(target));
                }

                Debug(string.Format(Inv, "IFC: exporting \"{0}\" to {1}", job.Label, target));
                try
                {
                    using (var transaction = new Transaction(doc, "RevoBIM IFC export"))
                    {
                        QuietTransaction(transaction);
                        transaction.Start();
                        try
                        {
                            doc.Export(folder, baseName, options);
                        }
                        finally
                        {
                            transaction.Commit();
                        }
                    }
                }
                catch (Exception err)
                {
                    string message = Msg(err);
                    report.Add(new Outcome(job.Key, job.Label, "IFC", target, false, message));
                    Debug("IFC: export threw - " + message);
                    continue;
                }

                bool landed = WaitFor(target);
                if (!landed)
                    landed = ClaimStray(folder, baseName, target, suffix);
                report.Add(new Outcome(job.Key, job.Label, "IFC", target, landed,
                                       landed ? "" : "Revit reported no error but no file appeared"));
            }

            foreach (string line in log)
                report.Note(line);
            return report;
        }

        /// <summary>
        /// Take a file the exporter named slightly differently. The IFC exporter appends the
        /// file type's own casing in places, so a request for .ifc can land as .IFC. That is
        /// the same file under another name, not a failure.
        /// </summary>
        internal static bool ClaimStray(string folder, string baseName, string target, string suffix)
        {
            try
            {
                string targetName = Basename(target);
                string wanted = targetName.ToLowerInvariant();
                foreach (string entry in ListDir(folder))
                {
                    string lowered = entry.ToLowerInvariant();
                    if (lowered == wanted && entry != targetName)
                    {
                        File.Move(PathJoin(folder, entry), target);
                        return File.Exists(target);
                    }
                    if (lowered.StartsWith(baseName.ToLowerInvariant(), StringComparison.Ordinal) &&
                        lowered.EndsWith(suffix.ToLowerInvariant(), StringComparison.Ordinal) &&
                        entry != targetName)
                    {
                        File.Move(PathJoin(folder, entry), target);
                        return File.Exists(target);
                    }
                }
            }
            catch (Exception)
            {
            }
            return false;
        }
    }
}
