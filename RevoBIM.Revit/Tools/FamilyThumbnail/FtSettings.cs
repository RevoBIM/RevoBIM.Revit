using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace RevoBIM.Tools.FamilyThumbnail
{
    /// <summary>One appearance override: a family category with its own view, style, detail and scale.</summary>
    public sealed class FtOverride
    {
        public string Category = "";
        public string ViewType = "";
        public string Style = "";
        public string Detail = "";
        public int Scale = 1;

        public string Encode()
        {
            return string.Join("|", new[] { Category, ViewType, Style, Detail, Scale.ToString(CultureInfo.InvariantCulture) });
        }

        public static FtOverride Decode(string text)
        {
            string[] parts = (text ?? "").Split('|');
            if (parts.Length != 5 || parts[0].Trim().Length == 0) return null;
            int scale;
            if (!int.TryParse(parts[4], NumberStyles.Integer, CultureInfo.InvariantCulture, out scale)) scale = 1;
            return new FtOverride { Category = parts[0].Trim(), ViewType = parts[1], Style = parts[2], Detail = parts[3], Scale = scale };
        }
    }

    /// <summary>
    /// Family Thumbnail settings: plain key=value text in %AppData%\RevoBIM\family_thumbnail.txt, the pyRevit tool's file and
    /// format, split on the first '=' only, a missing or bad key falling back to its default on its own.
    /// </summary>
    public sealed class FtSettings
    {
        public string ViewName = "Thumbnail View";
        public bool ExportImages = true;
        public string FitMode = "resize";
        public string ExportFolder = "";
        public int ImageSize = 512;
        public string ImageFormat = "PNG";
        public bool PromptOpen = true;
        public bool LeaveOpen = true;
        public bool CategoryFolders = true;
        public bool FillParams;
        public string ParamCreator = "BIM_Family_Creator";
        public string ParamRevision = "BIM_Family_Revision";
        public string ParamDate = "BIM_Family_Date";
        public string CreatorValue = "";
        public string RevisionStep = "Minor";
        public string SharedFile = "";
        public bool LockOrientation;
        public bool HideDimensions = true;
        public bool HideRefPoints = true;
        public bool HideRefLines = true;
        public bool HideRefPlanes = true;
        public bool HideTextNotes = true;
        public bool HideInvisibleLines = true;
        public bool HideFlipControls = true;
        public bool HideRoomCalcPoints = true;
        public bool HideHost = true;
        public bool HideConnectors = true;
        public bool HideVoids = true;
        public bool HideImported;
        public bool Gradient;
        public string GradSky = "#FFFFFF";
        public string GradHorizon = "#F4F5F7";
        public string GradGround = "#BFC5CE";
        public string D3Style = "Realistic";
        public string D3Detail = "Fine";
        public int D3Scale = 1;
        public string D3View = "3D View: Top, Front, Right";
        public string D2Style = "Hidden Line Removal";
        public string D2Detail = "Fine";
        public int D2Scale = 1;
        public string ThemeMode = "auto";
        public List<FtOverride> Overrides = new List<FtOverride>();

        public const int SettingsVersion = 1;

        // ---- hide rules by the setting key the pyRevit file used ---------------------------------------

        public bool HideFlag(string key)
        {
            switch (key)
            {
                case "hide_dimensions": return HideDimensions;
                case "hide_ref_points": return HideRefPoints;
                case "hide_ref_lines": return HideRefLines;
                case "hide_ref_planes": return HideRefPlanes;
                case "hide_text_notes": return HideTextNotes;
                case "hide_invisible_lines": return HideInvisibleLines;
                case "hide_flip_controls": return HideFlipControls;
                case "hide_room_calc_points": return HideRoomCalcPoints;
                case "hide_connectors": return HideConnectors;
                default: return false;
            }
        }

        // ---- the file ---------------------------------------------------------------------------------

        private sealed class BoolField
        {
            public string Key;
            public Func<FtSettings, bool> Get;
            public Action<FtSettings, bool> Set;
        }

        private static BoolField B(string key, Func<FtSettings, bool> get, Action<FtSettings, bool> set)
        {
            return new BoolField { Key = key, Get = get, Set = set };
        }

        private static readonly BoolField[] Bools =
        {
            B("export_images", s => s.ExportImages, (s, v) => s.ExportImages = v),
            B("lock_orientation", s => s.LockOrientation, (s, v) => s.LockOrientation = v),
            B("hide_dimensions", s => s.HideDimensions, (s, v) => s.HideDimensions = v),
            B("hide_ref_points", s => s.HideRefPoints, (s, v) => s.HideRefPoints = v),
            B("hide_ref_lines", s => s.HideRefLines, (s, v) => s.HideRefLines = v),
            B("hide_ref_planes", s => s.HideRefPlanes, (s, v) => s.HideRefPlanes = v),
            B("hide_text_notes", s => s.HideTextNotes, (s, v) => s.HideTextNotes = v),
            B("hide_invisible_lines", s => s.HideInvisibleLines, (s, v) => s.HideInvisibleLines = v),
            B("hide_flip_controls", s => s.HideFlipControls, (s, v) => s.HideFlipControls = v),
            B("hide_room_calc_points", s => s.HideRoomCalcPoints, (s, v) => s.HideRoomCalcPoints = v),
            B("hide_host", s => s.HideHost, (s, v) => s.HideHost = v),
            B("hide_connectors", s => s.HideConnectors, (s, v) => s.HideConnectors = v),
            B("hide_voids", s => s.HideVoids, (s, v) => s.HideVoids = v),
            B("hide_imported", s => s.HideImported, (s, v) => s.HideImported = v),
            B("gradient", s => s.Gradient, (s, v) => s.Gradient = v),
            B("leave_open", s => s.LeaveOpen, (s, v) => s.LeaveOpen = v),
            B("prompt_open", s => s.PromptOpen, (s, v) => s.PromptOpen = v),
            B("category_folders", s => s.CategoryFolders, (s, v) => s.CategoryFolders = v),
            B("fill_params", s => s.FillParams, (s, v) => s.FillParams = v),
        };

        private static bool ToBool(string text)
        {
            string t = (text ?? "").Trim().ToLowerInvariant();
            return t == "1" || t == "true" || t == "yes" || t == "on";
        }

        private static bool InList(string[] list, string value)
        {
            return Array.IndexOf(list, value) >= 0;
        }

        public static string NormaliseHex(string value, string fallback)
        {
            int r, g, b;
            return FtLogic.ParseHex(value, out r, out g, out b) ? FtLogic.ToHex(r, g, b) : fallback;
        }

        /// <summary>Parses settings text over the defaults. Unknown keys are ignored; bad values fall back.</summary>
        public static FtSettings Parse(string text)
        {
            var s = new FtSettings();
            var indexed = new SortedDictionary<int, string>();
            foreach (string raw in (text ?? "").Replace("\r\n", "\n").Split('\n'))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#") || line.IndexOf('=') < 0) continue;
                int eq = line.IndexOf('=');
                string key = line.Substring(0, eq).Trim();
                string value = line.Substring(eq + 1).Trim();
                try
                {
                    BoolField bf = Array.Find(Bools, f => f.Key == key);
                    if (bf != null) { bf.Set(s, ToBool(value)); continue; }
                    int n;
                    switch (key)
                    {
                        case "image_size":
                            if (int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out n)) s.ImageSize = n;
                            break;
                        case "d3_scale":
                            if (int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out n)) s.D3Scale = n;
                            break;
                        case "d2_scale":
                            if (int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out n)) s.D2Scale = n;
                            break;
                        case "grad_sky": s.GradSky = NormaliseHex(value, s.GradSky); break;
                        case "grad_horizon": s.GradHorizon = NormaliseHex(value, s.GradHorizon); break;
                        case "grad_ground": s.GradGround = NormaliseHex(value, s.GradGround); break;
                        case "d3_style": if (InList(FtCore.DisplayStyles, value)) s.D3Style = value; break;
                        case "d2_style": if (InList(FtCore.DisplayStyles, value)) s.D2Style = value; break;
                        case "d3_detail": if (InList(FtCore.DetailLevels, value)) s.D3Detail = value; break;
                        case "d2_detail": if (InList(FtCore.DetailLevels, value)) s.D2Detail = value; break;
                        case "d3_view": if (InList(FtCore.ViewTypes3D, value)) s.D3View = value; break;
                        case "image_format": if (InList(FtCore.ImageFormats, value)) s.ImageFormat = value; break;
                        case "fit_mode": if (InList(FtCore.FitModes, value)) s.FitMode = value; break;
                        case "theme_mode": if (value == "auto" || value == "dark" || value == "light") s.ThemeMode = value; break;
                        case "view_name": s.ViewName = value; break;
                        case "export_folder": s.ExportFolder = value; break;
                        case "param_creator": s.ParamCreator = value; break;
                        case "param_revision": s.ParamRevision = value; break;
                        case "param_date": s.ParamDate = value; break;
                        case "creator_value": s.CreatorValue = value; break;
                        case "shared_file": s.SharedFile = value; break;
                        case "revision_step": if (InList(FtCore.RevisionSteps, value)) s.RevisionStep = value; break;
                        default:
                            if (key.StartsWith("override.", StringComparison.Ordinal)
                                && int.TryParse(key.Substring(9), NumberStyles.Integer, CultureInfo.InvariantCulture, out n))
                                indexed[n] = value;
                            break;
                    }
                }
                catch (Exception err)
                {
                    FtCore.Swallowed("parse_settings:" + key, err);
                }
            }
            s.Overrides = new List<FtOverride>();
            foreach (KeyValuePair<int, string> pair in indexed)
            {
                FtOverride item = FtOverride.Decode(pair.Value);
                if (item != null) s.Overrides.Add(item);
            }
            s.ImageSize = Math.Max(128, Math.Min(4096, s.ImageSize));
            if (string.IsNullOrWhiteSpace(s.ViewName)) s.ViewName = new FtSettings().ViewName;
            return s;
        }

        public string Serialise()
        {
            var lines = new List<string> { "settings_version=" + SettingsVersion };
            Action<string, object> add = (k, v) => lines.Add(k + "=" + Convert.ToString(v, CultureInfo.InvariantCulture));
            add("view_name", ViewName);
            add("fit_mode", FitMode);
            add("export_folder", ExportFolder);
            add("image_format", ImageFormat);
            add("theme_mode", ThemeMode);
            add("param_creator", ParamCreator);
            add("param_revision", ParamRevision);
            add("param_date", ParamDate);
            add("creator_value", CreatorValue);
            add("revision_step", RevisionStep);
            add("shared_file", SharedFile);
            add("d3_style", D3Style);
            add("d3_detail", D3Detail);
            add("d3_scale", D3Scale);
            add("d3_view", D3View);
            add("d2_style", D2Style);
            add("d2_detail", D2Detail);
            add("d2_scale", D2Scale);
            add("image_size", ImageSize);
            add("grad_sky", GradSky);
            add("grad_horizon", GradHorizon);
            add("grad_ground", GradGround);
            foreach (BoolField f in Bools) lines.Add(f.Key + "=" + (f.Get(this) ? 1 : 0));
            for (int i = 0; i < Overrides.Count; i++) lines.Add("override." + i + "=" + Overrides[i].Encode());
            return string.Join("\n", lines) + "\n";
        }

        public static FtSettings Load()
        {
            string text = "";
            try
            {
                string path = FtCore.SettingsPath();
                if (File.Exists(path)) text = File.ReadAllText(path, Encoding.UTF8);
            }
            catch (Exception err)
            {
                FtCore.Swallowed("load_settings", err);
            }
            return Parse(text);
        }

        public void Save()
        {
            string text = Serialise();
            Directory.CreateDirectory(FtCore.DataDir());
            File.WriteAllText(FtCore.SettingsPath(), text, new UTF8Encoding(false));
        }

        /// <summary>Changes the theme mode on disk without touching anything else the window may not own.</summary>
        public static void SaveThemeMode(string mode)
        {
            FtSettings s = Load();
            s.ThemeMode = mode;
            s.Save();
        }

        /// <summary>Default appearance, replaced by the first override whose category matches the family's.</summary>
        public FtAppearance ResolveAppearance(string categoryName, bool is3d)
        {
            var ap = is3d
                ? new FtAppearance { ViewType = D3View, Style = D3Style, Detail = D3Detail, Scale = D3Scale }
                : new FtAppearance { ViewType = null, Style = D2Style, Detail = D2Detail, Scale = D2Scale };
            string wanted = (categoryName ?? "").Trim().ToLowerInvariant();
            if (wanted.Length > 0)
            {
                foreach (FtOverride item in Overrides)
                {
                    if (item.Category.Trim().ToLowerInvariant() != wanted) continue;
                    if (is3d && InList(FtCore.ViewTypes3D, item.ViewType)) ap.ViewType = item.ViewType;
                    if (InList(FtCore.DisplayStyles, item.Style)) ap.Style = item.Style;
                    if (InList(FtCore.DetailLevels, item.Detail)) ap.Detail = item.Detail;
                    ap.Scale = item.Scale;
                    ap.Override = item.Category;
                    break;
                }
            }
            return ap;
        }
    }

    public sealed class FtAppearance
    {
        public string ViewType;
        public string Style;
        public string Detail;
        public int Scale = 1;
        public string Override;
    }
}
