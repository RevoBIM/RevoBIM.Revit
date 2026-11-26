using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.FamilyThumbnail
{
    /// <summary>
    /// Family Thumbnail, shared constants, paths and the debug log. Port of the pyRevit tool (ft_logic.py, ft_version.py).
    /// The debug file is %AppData%\RevoBIM\family_thumbnail_debug.txt, the name the pyRevit tool used.
    /// </summary>
    public static class FtCore
    {
        public const string Version = "1.5.1";
        public const string ToolName = "Family Thumbnail";

        // ---- choices shown in the UI ------------------------------------------------------------------

        public static readonly string[] DisplayStyles =
            { "Wireframe", "Hidden Line Removal", "Shaded", "Shaded With Edges", "Consistent Colors", "Realistic" };

        /// <summary>DisplayStyle enum member names to try, in order, for each choice (members differ between releases).</summary>
        public static readonly Dictionary<string, string[]> StyleEnum = new Dictionary<string, string[]>
        {
            { "Wireframe", new[] { "Wireframe" } },
            { "Hidden Line Removal", new[] { "HLR" } },
            { "Shaded", new[] { "Shading" } },
            { "Shaded With Edges", new[] { "ShadingWithEdges", "Shading" } },
            { "Consistent Colors", new[] { "FlatColors", "Shading" } },
            { "Realistic", new[] { "Realistic", "RealisticWithEdges", "Shading" } },
        };

        public static readonly string[] DetailLevels = { "Coarse", "Medium", "Fine" };
        public static readonly int[] Scales = { 1, 2, 5, 10, 20, 50, 100, 200, 500 };

        public static readonly string[] ViewTypes3D =
        {
            "3D View: Top, Front, Right", "3D View: Top, Front, Left", "3D View: Top, Back, Right", "3D View: Top, Back, Left",
            "Top", "Front", "Back", "Left", "Right",
        };

        public static readonly string[] ImageFormats = { "PNG", "JPG" };
        public static readonly string[] FitModes = { "resize", "square" };
        public static readonly string[] RevisionSteps = { "Major", "Minor", "Patch" };

        /// <summary>Override category picker list when no document is open.</summary>
        public static readonly string[] FallbackCategories =
        {
            "Casework", "Ceilings", "Columns", "Communication Devices", "Conduit Fittings", "Curtain Wall Panels", "Data Devices",
            "Detail Items", "Doors", "Duct Accessories", "Duct Fittings", "Electrical Equipment", "Electrical Fixtures", "Entourage",
            "Fire Alarm Devices", "Fire Protection", "Flex Ducts", "Floors", "Food Service Equipment", "Furniture", "Furniture Systems",
            "Generic Models", "Lighting Devices", "Lighting Fixtures", "Mechanical Equipment", "Medical Equipment", "Nurse Call Devices",
            "Parking", "Pipe Accessories", "Pipe Fittings", "Planting", "Plumbing Equipment", "Plumbing Fixtures", "Railings", "Roofs",
            "Security Devices", "Site", "Specialty Equipment", "Sprinklers", "Stairs", "Structural Columns", "Structural Connections",
            "Structural Foundations", "Structural Framing", "Structural Stiffeners", "Telephone Devices", "Walls", "Windows",
        };

        /// <summary>The categories hidden per setting: (setting key, BuiltInCategory member names to try), looked up by name at call time.</summary>
        public static readonly KeyValuePair<string, string[]>[] HideRules =
        {
            new KeyValuePair<string, string[]>("hide_dimensions", new[] { "OST_Dimensions" }),
            new KeyValuePair<string, string[]>("hide_ref_points", new[] { "OST_ReferencePoints" }),
            new KeyValuePair<string, string[]>("hide_ref_lines", new[] { "OST_ReferenceLines" }),
            new KeyValuePair<string, string[]>("hide_ref_planes", new[] { "OST_CLines" }),
            new KeyValuePair<string, string[]>("hide_text_notes", new[] { "OST_TextNotes" }),
            new KeyValuePair<string, string[]>("hide_invisible_lines", new[] { "OST_InvisibleLines" }),
            new KeyValuePair<string, string[]>("hide_flip_controls", new[] { "OST_Controls", "OST_FlipControls" }),
            new KeyValuePair<string, string[]>("hide_room_calc_points", new[] { "OST_RoomCalculationPoint", "OST_RoomCalculationPoints" }),
            new KeyValuePair<string, string[]>("hide_connectors", new[] { "OST_ConnectorElem", "OST_ConnectorElements" }),
        };

        /// <summary>Host categories hidden element by element (the family's own host wall, floor, ceiling or roof).</summary>
        public static readonly string[] HostCategoryNames = { "OST_Walls", "OST_Floors", "OST_Ceilings", "OST_Roofs" };
        public static readonly string[] FormClassNames = { "Extrusion", "Blend", "Revolution", "Sweep", "SweptBlend" };
        public static readonly string[] Categories2D = { "OST_DetailComponents", "OST_ProfileFamilies", "OST_TitleBlocks" };

        // ---- palettes (Revit's own dark theme for dark, the house light palette for light) -------------

        public static readonly Dictionary<string, Dictionary<string, string>> Palettes = new Dictionary<string, Dictionary<string, string>>
        {
            {
                "dark", new Dictionary<string, string>
                {
                    { "bWindow", "#3C4454" }, { "bCard", "#374051" }, { "bField", "#2D3441" }, { "bBar", "#222933" },
                    { "bChip", "#323C48" }, { "bHover", "#444E5E" }, { "bSelect", "#3A7392" }, { "bEdge", "#515C6B" },
                    { "bText", "#EEF0F4" }, { "bMuted", "#A4AAB1" }, { "bBlue", "#5AAEEB" }, { "bOrange", "#E8912D" },
                    { "bGreen", "#3FA75A" }, { "bGreenHover", "#4EC06D" }, { "bRed", "#D9534F" },
                }
            },
            {
                "light", new Dictionary<string, string>
                {
                    { "bWindow", "#F2F4F7" }, { "bCard", "#FFFFFF" }, { "bField", "#FFFFFF" }, { "bBar", "#E3E7ED" },
                    { "bChip", "#E8ECF1" }, { "bHover", "#DDE3EA" }, { "bSelect", "#BFDDF5" }, { "bEdge", "#C3CAD4" },
                    { "bText", "#1E2430" }, { "bMuted", "#5A6372" }, { "bBlue", "#1B72BE" }, { "bOrange", "#B96A12" },
                    { "bGreen", "#2E8546" }, { "bGreenHover", "#3A9C58" }, { "bRed", "#C0392B" },
                }
            },
        };

        /// <summary>Gradient presets: name, sky, horizon, ground.</summary>
        public static readonly string[][] GradientPresets =
        {
            new[] { "Studio Grey", "#FFFFFF", "#F4F5F7", "#BFC5CE" },
            new[] { "Soft Blue", "#E9F2FB", "#FFFFFF", "#AFC4DA" },
            new[] { "Warm", "#FFF6EC", "#FFFFFF", "#E6C9A8" },
            new[] { "Blueprint", "#0F3B66", "#1F6AA8", "#0A2745" },
            new[] { "Charcoal", "#5A6270", "#3A404B", "#1E2229" },
            new[] { "Clean White", "#FFFFFF", "#FFFFFF", "#FFFFFF" },
        };

        // ---- paths ------------------------------------------------------------------------------------

        public static string DataDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM");
        }

        public static string SettingsPath() { return Path.Combine(DataDir(), "family_thumbnail.txt"); }
        public static string LogPath() { return Path.Combine(DataDir(), "family_thumbnail_debug.txt"); }
        public static string ErrorPath() { return Path.Combine(DataDir(), "family_thumbnail_last_error.txt"); }

        public static string DefaultExportFolder()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Documents", "RevoBIM", "Family Thumbnails");
        }

        public static string ExportFolder(FtSettings s)
        {
            return string.IsNullOrWhiteSpace(s.ExportFolder) ? DefaultExportFolder() : s.ExportFolder.Trim();
        }

        /// <summary>Export folder, plus a sub-folder named after the family category when category folders are on.</summary>
        public static string OutputFolder(FtSettings s, string categoryName)
        {
            string baseFolder = ExportFolder(s);
            if (s.CategoryFolders && !string.IsNullOrEmpty(categoryName) && SafeFileName(categoryName, "Family") != "Family")
                return Path.Combine(baseFolder, SafeFileName(categoryName, "Family"));
            return baseFolder;
        }

        /// <summary>The shared parameter file shipped with the tool: BIM_Family_Creator, BIM_Family_Revision, BIM_Family_Date.</summary>
        public static string BundledSharedFile()
        {
            return Path.Combine(DataDir(), "BIM_Family_Parameters.txt");
        }

        public const string BundledSharedFileText =
            "# This is a Revit shared parameter file.\r\n" +
            "# Do not edit manually.\r\n" +
            "*META\tVERSION\tMINVERSION\r\n" +
            "META\t2\t1\r\n" +
            "*GROUP\tID\tNAME\r\n" +
            "GROUP\t5\t*Families\r\n" +
            "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\tHIDEWHENNOVALUE\r\n" +
            "PARAM\tf67a6d65-3a03-4b19-9683-a072f9d344bb\tBIM_Family_Creator\tTEXT\t\t5\t1\tFamily Creator Name\t1\t0\r\n" +
            "PARAM\taa11dc76-3fdc-4ab6-9ac3-48877ad1ae18\tBIM_Family_Revision\tTEXT\t\t5\t1\tFamily Revision Number\t1\t0\r\n" +
            "PARAM\tbd717a86-f74f-40cc-b815-920bbab0d3bc\tBIM_Family_Date\tTEXT\t\t5\t1\tFamily Issue Date\t1\t0\r\n";

        /// <summary>
        /// (path, isDefault, note): the shared parameter file the family parameters come from. Blank in Settings means the
        /// built-in file (written to %AppData%\RevoBIM the first time it is needed); a chosen file that has gone missing
        /// falls back to it with a note.
        /// </summary>
        public static string ResolveSharedFile(FtSettings s, out bool isDefault, out string note)
        {
            string custom = (s.SharedFile ?? "").Trim();
            if (custom.Length > 0 && File.Exists(custom))
            {
                isDefault = false;
                note = "";
                return custom;
            }
            isDefault = true;
            note = custom.Length > 0 ? "Shared parameter file not found, using the built-in one: " + custom : "";
            return EnsureBundledSharedFile();
        }

        private static string EnsureBundledSharedFile()
        {
            string path = BundledSharedFile();
            try
            {
                Directory.CreateDirectory(DataDir());
                if (!File.Exists(path) || File.ReadAllText(path) != BundledSharedFileText)
                    File.WriteAllText(path, BundledSharedFileText, new UTF8Encoding(false));
            }
            catch (Exception err)
            {
                Swallowed("EnsureBundledSharedFile", err);
            }
            return path;
        }

        public static string SafeFileName(string name, string fallback)
        {
            string text = name ?? "";
            if (text.EndsWith(".rfa", StringComparison.OrdinalIgnoreCase)) text = text.Substring(0, text.Length - 4);
            foreach (char ch in "<>:\"/\\|?*") text = text.Replace(ch, '_');
            text = text.Trim().Trim('.');
            return text.Length == 0 ? fallback : text;
        }

        public static string SafeFileName(string name) { return SafeFileName(name, "Family"); }

        // ---- debug log --------------------------------------------------------------------------------

        private static readonly List<string> LogLines = new List<string>();
        private static readonly object Gate = new object();

        public static void Log(string message)
        {
            lock (Gate) LogLines.Add(message ?? "");
        }

        /// <summary>Records an absorbed exception.</summary>
        public static void Swallowed(string where, Exception err)
        {
            Log("swallowed in " + where + ": " + (err == null ? "?" : err.GetType().Name + ": " + err.Message));
        }

        public static void ResetLog()
        {
            lock (Gate) LogLines.Clear();
        }

        public static string[] LogSnapshot()
        {
            lock (Gate) return LogLines.ToArray();
        }

        /// <summary>Writes the log to the debug file (it starts again each run). Returns the path, or null when it could not be written.</summary>
        public static string FlushLog()
        {
            try
            {
                Directory.CreateDirectory(DataDir());
                File.WriteAllText(LogPath(), string.Join("\r\n", LogSnapshot()) + "\r\n", new UTF8Encoding(false));
                return LogPath();
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>The first lines of every debug file: tool version, add-in build, Revit version.</summary>
        public static void BeginLog(string command, string revitVersion, string document)
        {
            ResetLog();
            Log("===== Family Thumbnail " + Version + " | " + command + " (" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + ") =====");
            Log("build: " + BuildInfo());
            Log("revit: " + revitVersion + " | document: " + document);
        }

        public static string BuildInfo()
        {
            try
            {
                Assembly assembly = typeof(FtCore).Assembly;
                string path = assembly.Location;
                string written = "";
                try
                {
                    written = File.GetLastWriteTime(path).ToString("yyyy-MM-dd HH:mm:ss");
                }
                catch (Exception)
                {
                }
                string date = "";
                string revit = "";
                foreach (AssemblyMetadataAttribute meta in assembly.GetCustomAttributes(typeof(AssemblyMetadataAttribute), false))
                {
                    if (meta.Key == "BuildDate") date = meta.Value;
                    if (meta.Key == "RevitVersion") revit = meta.Value;
                }
                string info = assembly.GetName().Version == null ? "?" : assembly.GetName().Version.ToString(3);
                return "add-in " + info + " | built " + date + " | Revit " + revit + " build | " + path + " (written " + written + ")";
            }
            catch (Exception err)
            {
                return "build info unavailable: " + err.Message;
            }
        }

        // ---- small Revit helpers ----------------------------------------------------------------------

        public static long Eid(ElementId id)
        {
            return id == null ? 0 : id.Value;
        }

        /// <summary>An enum member by name, the first name that exists in this release; null when none do.</summary>
        public static T? EnumMember<T>(params string[] names) where T : struct
        {
            foreach (string name in names)
            {
                T value;
                if (Enum.TryParse(name, false, out value) && Enum.IsDefined(typeof(T), value)) return value;
            }
            return null;
        }
    }
}
