using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using DB = Autodesk.Revit.DB;

namespace RevoBIM.Tools.ProSheets
{
    /// <summary>
    /// The export engine: PDF (Revit's own or a printer), DWG, NWC and IFC.
    ///
    /// Two things shape everything in here.
    ///
    /// Nothing about the Revit API was assumed to exist in the Python: between 2024 and
    /// 2027 the export options classes gain properties, lose properties and rename enum
    /// members, so every option went through set_opt and every enum member through
    /// enum_member. This port targets Revit 2024 only, so the options are set directly;
    /// where the Python's set_opt found nothing on 2024 the same "not available on this
    /// release" note is still recorded, so the report reads the same. SetOpt/EnumMember
    /// are kept (reflection) for any caller that wants the by-name route.
    ///
    /// A void call is not evidence. Revit's export and print calls return nothing useful
    /// and do not reliably raise when a file does not appear. Every job is confirmed by
    /// looking for the file on disk afterwards, and the count reported at the end is the
    /// count of files that exist - not the count of calls that did not throw.
    ///
    /// Port of ps_export.py. This part: API access, dialog suppression, results, the debug
    /// log, printers, option mapping and the PDF routes. See PsExport.Formats.cs (DWG, NWC,
    /// IFC) and PsExport.Files.cs (proving a file landed, scanning, folders).
    /// </summary>
    public static partial class PsExport
    {
        internal static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        // ======================================================================
        // defensive access to an API that moves between releases
        // ======================================================================

        /// <summary>
        /// Set the first property of <paramref name="names"/> that exists on <paramref name="target"/>.
        /// <paramref name="names"/> may be several spellings of the same idea - the print API and
        /// the PDF API disagree about capitalisation in a few places (ViewLinksinBlue against
        /// ViewLinksInBlue).
        /// </summary>
        public static bool SetOpt(object target, IList<string> names, object value, List<string> log = null)
        {
            foreach (string name in names)
            {
                if (target == null)
                    continue;
                MemberInfo[] members;
                try
                {
                    members = target.GetType().GetMember(name, BindingFlags.Public | BindingFlags.Instance);
                }
                catch (Exception)
                {
                    members = new MemberInfo[0];
                }
                if (members.Length == 0)
                    continue;
                try
                {
                    PropertyInfo prop = members.OfType<PropertyInfo>().FirstOrDefault(p => p.GetIndexParameters().Length == 0);
                    if (prop != null)
                    {
                        if (!prop.CanWrite)
                            throw new MissingMemberException(string.Format(Inv,
                                "can't assign to read-only property {0} of type '{1}'", name, target.GetType().Name));
                        prop.SetValue(target, Coerce(value, prop.PropertyType), null);
                        return true;
                    }
                    FieldInfo field = members.OfType<FieldInfo>().FirstOrDefault();
                    if (field != null)
                    {
                        field.SetValue(target, Coerce(value, field.FieldType));
                        return true;
                    }
                    throw new MissingMemberException(string.Format(Inv,
                        "attribute '{0}' of '{1}' object is read-only", name, target.GetType().Name));
                }
                catch (Exception err)
                {
                    log?.Add(string.Format(Inv, "could not set {0}: {1}", name, Msg(err)));
                    return false;
                }
            }
            log?.Add(string.Format(Inv, "not available on this release: {0}", names.Count > 0 ? names[0] : ""));
            return false;
        }

        public static bool SetOpt(object target, string names, object value, List<string> log = null)
        {
            return SetOpt(target, new[] { names }, value, log);
        }

        internal static object Coerce(object value, Type type)
        {
            if (value == null || type.IsInstanceOfType(value))
                return value;
            Type core = Nullable.GetUnderlyingType(type) ?? type;
            if (core.IsEnum)
                return Enum.ToObject(core, value);
            return Convert.ChangeType(value, core, Inv);
        }

        /// <summary>A .NET exception's text as IronPython's u'{0}'.format(err) showed it.</summary>
        internal static string Msg(Exception err)
        {
            while (err is TargetInvocationException && err.InnerException != null)
                err = err.InnerException;
            return err?.Message ?? "";
        }

        /// <summary>
        /// The first member of a DB enum that exists, or null. The enum type itself may be
        /// missing on a release, which is why the type is looked up by name.
        /// </summary>
        public static object EnumMember(string typeName, params string[] members)
        {
            Type enumType;
            try
            {
                enumType = typeof(Element).Assembly.GetType("Autodesk.Revit.DB." + typeName, false);
            }
            catch (Exception)
            {
                return null;
            }
            if (enumType == null)
                return null;
            foreach (string member in members)
            {
                try
                {
                    FieldInfo found = enumType.GetField(member, BindingFlags.Public | BindingFlags.Static);
                    if (found != null)
                        return found.GetValue(null);
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return null;
        }

        public static List<ElementId> IdList(IEnumerable<ElementId> elementIds)
        {
            var typed = new List<ElementId>();
            foreach (ElementId elementId in elementIds)
                typed.Add(elementId);
            return typed;
        }

        /// <summary>
        /// Sets one known 2024 property, recording a refusal the way set_opt did
        /// ("could not set X: ..."). Not in the Python: the direct-call stand-in for set_opt.
        /// </summary>
        internal static bool SetDirect(List<string> log, string name, Action set)
        {
            try
            {
                set();
                return true;
            }
            catch (Exception err)
            {
                log?.Add(string.Format(Inv, "could not set {0}: {1}", name, Msg(err)));
                return false;
            }
        }

        /// <summary>What set_opt recorded on 2024 for a property the class does not have.</summary>
        internal static void NotOnThisRelease(List<string> log, string name)
        {
            log?.Add(string.Format(Inv, "not available on this release: {0}", name));
        }

        // ======================================================================
        // suppressing Revit's own dialogs
        //
        // Two things have to be handled and they are different: a TaskDialog that
        // pops up mid-run, and a failure posted against the transaction. The first
        // is answered through DialogBoxShowing, the second deleted by an
        // IFailuresPreprocessor.
        //
        // The handler is hooked ONCE and switched with a flag (in IronPython an
        // unsubscribe silently removed nothing and the handlers piled up).
        // ======================================================================

        public static bool SuppressOn = false;
        internal static bool DialogHooked = false;
        internal static readonly List<string> Suppressed = new List<string>();

        internal static void OnDialogShowing(object sender, DialogBoxShowingEventArgs args)
        {
            if (!SuppressOn)
                return;
            string shown;
            try
            {
                shown = string.Format(Inv, "{0}", args.DialogId);
            }
            catch (Exception)
            {
                shown = "?";
            }
            foreach (string member in new[] { "Close", "Cancel", "Ok", "OK", "Yes", "No" })
            {
                try
                {
                    if (!Enum.IsDefined(typeof(TaskDialogResult), member))
                        continue;
                    var answer = (TaskDialogResult)Enum.Parse(typeof(TaskDialogResult), member);
                    args.OverrideResult((int)answer);
                    Suppressed.Add(shown);
                    Debug(string.Format(Inv, "suppressed Revit dialog \"{0}\" with {1}", shown, member));
                    return;
                }
                catch (Exception)
                {
                    continue;
                }
            }
            try
            {
                args.OverrideResult(1);
                Suppressed.Add(shown);
                Debug(string.Format(Inv, "suppressed Revit dialog \"{0}\"", shown));
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Hook DialogBoxShowing once for the life of the session.</summary>
        public static bool HookDialogs(UIApplication uiapp)
        {
            if (DialogHooked)
                return true;
            try
            {
                uiapp.DialogBoxShowing += OnDialogShowing;
                DialogHooked = true;
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static void BeginSuppression(UIApplication uiapp)
        {
            Suppressed.Clear();
            HookDialogs(uiapp);
            SuppressOn = true;
            Debug("Revit dialog suppression on");
        }

        public static List<string> EndSuppression()
        {
            SuppressOn = false;
            if (Suppressed.Count > 0)
                Debug(string.Format(Inv, "suppressed {0} Revit dialog(s): {1}",
                    Suppressed.Count, string.Join(", ", Suppressed.Take(12))));
            Debug("Revit dialog suppression off");
            return new List<string>(Suppressed);
        }

        /// <summary>The Python's _Swallow: deletes every warning posted against the transaction.</summary>
        internal class Swallow : IFailuresPreprocessor
        {
            public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
            {
                try
                {
                    foreach (FailureMessageAccessor failure in accessor.GetFailureMessages())
                    {
                        try
                        {
                            accessor.DeleteWarning(failure);
                        }
                        catch (Exception)
                        {
                            continue;
                        }
                    }
                }
                catch (Exception)
                {
                }
                return FailureProcessingResult.Continue;
            }
        }

        /// <summary>An IFailuresPreprocessor that deletes warnings, or null.</summary>
        public static IFailuresPreprocessor FailurePreprocessor()
        {
            try
            {
                return new Swallow();
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>Put the warning-swallowing preprocessor on a transaction.</summary>
        public static bool QuietTransaction(Transaction transaction)
        {
            if (!SuppressOn)
                return false;
            IFailuresPreprocessor handler = FailurePreprocessor();
            if (handler == null)
                return false;
            try
            {
                FailureHandlingOptions options = transaction.GetFailureHandlingOptions();
                options.SetFailuresPreprocessor(handler);
                options.SetClearAfterRollback(true);
                transaction.SetFailureHandlingOptions(options);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ======================================================================
        // results
        // ======================================================================

        /// <summary>
        /// What happened to one row in one format. Key is object: a sheet's element id
        /// number (long), 0 for a combined PDF, or "register" for the Document Register.
        /// Compare keys with Equals, not ==.
        /// </summary>
        public class Outcome
        {
            public object Key;
            public string Label;
            public string Fmt;
            public string Path;
            public bool Ok;
            public string Message;

            public Outcome(object key, string label, string fmt, string path = "", bool ok = false, string message = "")
            {
                Key = key;
                Label = label;
                Fmt = fmt;
                Path = path;
                Ok = ok;
                Message = message;
            }
        }

        // ======================================================================
        // the debug log
        //
        // Always on. The log is a few kilobytes, it is overwritten every run, and a
        // diagnostic that only exists when somebody remembered to ask for it is not
        // there on the run that actually went wrong. The tickbox decides how loudly
        // the report talks about it, not whether it is written.
        // ======================================================================

        public static bool DebugOn = true;
        public static readonly List<string> DebugLines = new List<string>();

        public static void DebugReset()
        {
            DebugLines.Clear();
        }

        public static void Debug(string text)
        {
            if (!DebugOn)
                return;
            string stamp;
            try
            {
                stamp = DateTime.Now.ToString("HH:mm:ss.fff", Inv);
            }
            catch (Exception)
            {
                stamp = "";
            }
            try
            {
                DebugLines.Add(stamp + "  " + text);
            }
            catch (Exception)
            {
            }
        }

        public static string DebugText()
        {
            return string.Join("\n", DebugLines);
        }

        /// <summary>Everything worth telling the user after a run.</summary>
        public class Report
        {
            public List<Outcome> Outcomes = new List<Outcome>();
            public List<string> Notes = new List<string>();
            public bool Cancelled = false;
            public double Seconds = 0.0;
            public string DebugPath = "";
            // Called with each outcome as it happens, so the window can colour the row.
            public Action<Outcome> OnAdd = null;

            public void Add(Outcome outcome)
            {
                Outcomes.Add(outcome);
                if (OnAdd == null)
                    return;
                try
                {
                    OnAdd(outcome);
                }
                catch (Exception)
                {
                    // A window that cannot repaint must never stop an export.
                }
            }

            public void Note(object text)
            {
                string line = text == null ? "None" : string.Format(Inv, "{0}", text);
                if (!string.IsNullOrEmpty(line) && !Notes.Contains(line))
                    Notes.Add(line);
            }

            public List<Outcome> Written()
            {
                return Outcomes.Where(o => o.Ok).ToList();
            }

            public List<Outcome> Failed()
            {
                return Outcomes.Where(o => !o.Ok).ToList();
            }

            public List<string> Folders()
            {
                var seen = new List<string>();
                foreach (Outcome outcome in Written())
                {
                    string folder = Dirname(outcome.Path);
                    if (!string.IsNullOrEmpty(folder) && !seen.Contains(folder))
                        seen.Add(folder);
                }
                return seen;
            }

            public string Summary()
            {
                int okCount = Written().Count;
                int badCount = Failed().Count;
                string head;
                if (Cancelled)
                    head = string.Format(Inv, "Cancelled after {0} file{1}", okCount, okCount == 1 ? "" : "s");
                else if (badCount > 0)
                    head = string.Format(Inv, "{0} written, {1} failed", okCount, badCount);
                else
                    head = string.Format(Inv, "{0} file{1} written", okCount, okCount == 1 ? "" : "s");
                return string.Format(Inv, "{0} in {1}s", head, Seconds.ToString("0.0", Inv));
            }
        }

        /// <summary>
        /// One sheet or view, with the name and folder already decided.
        /// Folders: {"pdf": path, "dwg": path, ...}.
        /// </summary>
        public class Job
        {
            public long Key;
            public string Label;
            public ElementId ElementId;
            public string BaseName;
            public Dictionary<string, string> Folders;
            public PsModel.SheetSize SizeInfo;
            public View View;

            public Job(long key, string label, ElementId elementId, string baseName,
                       Dictionary<string, string> folders, PsModel.SheetSize sizeInfo = null, View view = null)
            {
                Key = key;
                Label = label;
                ElementId = elementId;
                BaseName = baseName;
                Folders = folders ?? new Dictionary<string, string>();
                SizeInfo = sizeInfo;
                View = view;
            }

            /// <summary>job.folders.get(fmt, u'').</summary>
            internal string FolderFor(string fmt)
            {
                return Folders != null && Folders.TryGetValue(fmt, out string folder) && folder != null ? folder : "";
            }
        }

        // ======================================================================
        // what this machine can do
        // ======================================================================

        /// <summary>Every printer installed on this machine, PDF writers included.</summary>
        public static List<string> ListPrinters()
        {
            var names = new List<string>();
            try
            {
                foreach (object name in System.Drawing.Printing.PrinterSettings.InstalledPrinters)
                {
                    string text = string.Format(Inv, "{0}", name);
                    if (!string.IsNullOrEmpty(text) && !names.Contains(text))
                        names.Add(text);
                }
            }
            catch (Exception)
            {
            }
            return names.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        public static string DefaultPrinter()
        {
            try
            {
                return string.Format(Inv, "{0}", new System.Drawing.Printing.PrinterSettings().PrinterName);
            }
            catch (Exception)
            {
                return "";
            }
        }

        // ======================================================================
        // drivers we already know something about
        //
        // "diroots.prosheets" is the one that matters. ProSheets installs its own
        // private instance of PDF24 under that name, set up not to ask where to save -
        // which is the entire reason their batch export works unattended while a
        // hand-rolled one against the main PDF24 printer sits waiting on a Save As
        // dialog. If it is on the machine it is the best driver default available.
        //
        // Matched on letters and digits alone, so "DiRoots.ProSheets", "diroots
        // prosheets" and a redirected copy carrying a session suffix all count.
        // ======================================================================

        // token, what to tell the user, needs a staging folder
        public static readonly List<(string Token, string Description, bool Staging)> KnownPrinters =
            new List<(string Token, string Description, bool Staging)>
            {
                ("dirootsprosheets",
                 "a private PDF24 instance that ProSheets installs, already set not to ask where to save",
                 true),
            };

        internal static string Token(string text)
        {
            return Regex.Replace((text ?? "").ToLowerInvariant(), "[^a-z0-9]", "");
        }

        /// <summary>(description, needs staging) for a driver we know, or null.</summary>
        public static (string Description, bool Staging)? KnownPrinter(string name)
        {
            string token = Token(name);
            if (token.Length == 0)
                return null;
            foreach (var (wanted, description, staging) in KnownPrinters)
            {
                if (token.Contains(wanted))
                    return (description, staging);
            }
            return null;
        }

        /// <summary>
        /// The best known driver out of a list of installed printers, or "". Order in
        /// KnownPrinters is preference order, not the order the printers are installed in.
        /// </summary>
        public static string PreferredPrinter(IEnumerable<string> printers)
        {
            foreach (var (wanted, _, _) in KnownPrinters)
            {
                foreach (string name in printers ?? Enumerable.Empty<string>())
                {
                    if (Token(name).Contains(wanted))
                        return name ?? "";
                }
            }
            return "";
        }

        /// <summary>Whether this Revit has its own PDF exporter (2022 and later): always on 2024.</summary>
        public static bool NativePdfAvailable(Document doc)
        {
            return true;
        }

        /// <summary>Every DWG export setup saved in this model.</summary>
        public static List<string> ListDwgSetups(Document doc)
        {
            var names = new List<string>();
            try
            {
                foreach (string name in ExportDWGSettings.ListNames(doc))
                {
                    string text = name ?? "";
                    if (text.Length > 0 && !names.Contains(text))
                        names.Add(text);
                }
            }
            catch (Exception)
            {
            }
            return names.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        // ======================================================================
        // paper sizes
        // ======================================================================

        /// <summary>The paper sizes the currently selected print driver offers.</summary>
        public static List<(string Name, PaperSize Paper)> PrinterPaperSizes(Document doc)
        {
            var sizes = new List<(string Name, PaperSize Paper)>();
            try
            {
                foreach (PaperSize paper in doc.PrintManager.PaperSizes)
                {
                    try
                    {
                        sizes.Add((paper.Name ?? "", paper));
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }
            catch (Exception)
            {
            }
            return sizes;
        }

        internal static string Normalise(string text)
        {
            return new string((text ?? "None").ToUpperInvariant().Where(char.IsLetterOrDigit).ToArray());
        }

        /// <summary>
        /// Find the driver's paper for a sheet size like "A1". Drivers name the same paper
        /// half a dozen ways - "A1", "ISO A1", "A1 (594 x 841mm)" - so an exact string match
        /// finds nothing on most machines. Exact first, then a whole-token match, then the
        /// millimetres.
        /// </summary>
        public static PaperSize MatchPaper(List<(string Name, PaperSize Paper)> sizes, string wanted,
                                           double widthMm = 0.0, double heightMm = 0.0)
        {
            if (sizes == null || sizes.Count == 0)
                return null;
            string target = Normalise(wanted);

            if (target.Length > 0)
            {
                foreach (var (name, paper) in sizes)
                {
                    if (Normalise(name) == target)
                        return paper;
                }
                foreach (var (name, paper) in sizes)
                {
                    string normalised = Normalise(name);
                    if (normalised.StartsWith(target, StringComparison.Ordinal) ||
                        normalised.EndsWith(target, StringComparison.Ordinal))
                        return paper;
                }
                foreach (var (name, paper) in sizes)
                {
                    if (Normalise(name).Contains(target))
                        return paper;
                }
            }

            if (widthMm != 0 && heightMm != 0)
            {
                int shortEdge = (int)Math.Round(Math.Min(widthMm, heightMm), MidpointRounding.AwayFromZero);
                int longEdge = (int)Math.Round(Math.Max(widthMm, heightMm), MidpointRounding.AwayFromZero);
                for (int tolerance = 0; tolerance <= 5; tolerance++)
                {
                    foreach (var (name, paper) in sizes)
                    {
                        string normalised = Normalise(name);
                        for (int candidateShort = shortEdge - tolerance; candidateShort <= shortEdge + tolerance; candidateShort++)
                        {
                            for (int candidateLong = longEdge - tolerance; candidateLong <= longEdge + tolerance; candidateLong++)
                            {
                                string pair = string.Format(Inv, "{0}X{1}", candidateShort, candidateLong);
                                if (normalised.Contains(pair))
                                    return paper;
                            }
                        }
                    }
                }
            }
            return null;
        }

        // ======================================================================
        // shared option mapping (the Python's enum_member lookups, typed for 2024)
        // ======================================================================

        internal static DB.RasterQualityType RasterQuality(string name)
        {
            switch (name)
            {
                case "low": return DB.RasterQualityType.Low;
                case "medium": return DB.RasterQualityType.Medium;
                case "presentation": return DB.RasterQualityType.Presentation;
                default: return DB.RasterQualityType.High;
            }
        }

        internal static DB.ColorDepthType ColourDepth(string name)
        {
            switch (name)
            {
                case "grayscale": return DB.ColorDepthType.GrayScale;
                case "blackline": return DB.ColorDepthType.BlackLine;
                default: return DB.ColorDepthType.Color;
            }
        }

        internal static DB.ZoomType ZoomType(string name)
        {
            return name == "fit" ? DB.ZoomType.FitToPage : DB.ZoomType.Zoom;
        }

        internal static DB.PaperPlacementType Placement(string name)
        {
            return name == "offset" ? DB.PaperPlacementType.Margins : DB.PaperPlacementType.Center;
        }

        internal static DB.MarginType Margin(string name)
        {
            switch (name)
            {
                case "printerlimit": return DB.MarginType.PrinterLimit;
                case "usermargin": return DB.MarginType.UserDefined;
                default: return DB.MarginType.NoMargin;
            }
        }

        internal static DB.HiddenLineViewsType HiddenLine(string name)
        {
            return name == "raster" ? DB.HiddenLineViewsType.RasterProcessing : DB.HiddenLineViewsType.VectorProcessing;
        }

        internal static DB.PageOrientationType Orientation(bool landscape)
        {
            return landscape ? DB.PageOrientationType.Landscape : DB.PageOrientationType.Portrait;
        }

        internal static bool Flag(IDictionary<string, string> profile, string key, bool defaultValue = false)
        {
            if (profile == null || !profile.TryGetValue(key, out string value) || value == null)
                return defaultValue;
            string text = value.Trim().ToLowerInvariant();
            return text == "1" || text == "true" || text == "yes" || text == "on";
        }

        internal static double Number(IDictionary<string, string> profile, string key, double defaultValue = 0.0)
        {
            string value = null;
            if (profile != null && profile.TryGetValue(key, out string stored))
                value = stored;
            if (value == null)
                return defaultValue;
            return double.TryParse(value.Trim(), NumberStyles.Float, Inv, out double parsed) ? parsed : defaultValue;
        }

        internal static string Text(IDictionary<string, string> profile, string key, string defaultValue = "")
        {
            if (profile == null || !profile.TryGetValue(key, out string value) || value == null)
                return defaultValue;
            return value.Trim();
        }

        // ======================================================================
        // PDF through Revit's own exporter
        // ======================================================================

        /// <summary>A configured PDFExportOptions (never null on 2024).</summary>
        public static PDFExportOptions BuildPdfOptions(IDictionary<string, string> profile,
                                                       PsModel.SheetSize sizeInfo = null, List<string> log = null)
        {
            var options = new PDFExportOptions();

            string zoomMode = Text(profile, "pdf.zoom_mode", "zoom");
            SetDirect(log, "ZoomType", () => options.ZoomType = ZoomType(zoomMode));
            if (zoomMode == "zoom")
            {
                try
                {
                    SetDirect(log, "ZoomPercentage", () => options.ZoomPercentage = (int)Number(profile, "pdf.zoom", 100.0));
                }
                catch (Exception)
                {
                }
            }

            string placement = Text(profile, "pdf.placement", "center");
            SetDirect(log, "PaperPlacement", () => options.PaperPlacement = Placement(placement));
            if (placement == "offset")
            {
                // PDFExportOptions has no MarginType on 2024; the Python's set_opt noted that.
                NotOnThisRelease(log, "MarginType");
                SetDirect(log, "OriginOffsetX", () => options.OriginOffsetX = Number(profile, "pdf.offset_x"));
                SetDirect(log, "OriginOffsetY", () => options.OriginOffsetY = Number(profile, "pdf.offset_y"));
            }

            // No HiddenLineViews on PDFExportOptions in 2024 (the Python's set_opt noted it);
            // the same idea is the bare AlwaysUseRaster flag.
            NotOnThisRelease(log, "HiddenLineViews");
            SetDirect(null, "AlwaysUseRaster", () => options.AlwaysUseRaster = Text(profile, "pdf.hidden_line", "vector") == "raster");

            SetDirect(log, "RasterQuality", () => options.RasterQuality = RasterQuality(Text(profile, "pdf.raster_quality", "high")));
            SetDirect(log, "ColorDepth", () => options.ColorDepth = ColourDepth(Text(profile, "pdf.colors", "color")));

            SetDirect(log, "ViewLinksInBlue", () => options.ViewLinksInBlue = Flag(profile, "pdf.view_links_blue", true));
            SetDirect(log, "HideReferencePlane", () => options.HideReferencePlane = Flag(profile, "pdf.hide_ref_planes", true));
            SetDirect(log, "HideUnreferencedViewTags", () => options.HideUnreferencedViewTags = Flag(profile, "pdf.hide_unreferenced_tags", true));
            SetDirect(log, "HideScopeBoxes", () => options.HideScopeBoxes = Flag(profile, "pdf.hide_scope_boxes", true));
            SetDirect(log, "HideCropBoundaries", () => options.HideCropBoundaries = Flag(profile, "pdf.hide_crop_boundaries", true));
            SetDirect(log, "ReplaceHalftoneWithThinLines", () => options.ReplaceHalftoneWithThinLines = Flag(profile, "pdf.replace_halftone", false));
            SetDirect(log, "MaskCoincidentLines", () => options.MaskCoincidentLines = Flag(profile, "pdf.mask_coincident", false));
            SetDirect(null, "StopOnError", () => options.StopOnError = false);

            if (sizeInfo != null && Flag(profile, "pdf.keep_paper_size", true))
            {
                SetDirect(null, "PaperOrientation", () => options.PaperOrientation = Orientation(sizeInfo.Landscape));
                ExportPaperFormat? paperFormat = PaperFormatFor(sizeInfo.Name);
                if (paperFormat != null)
                    SetDirect(null, "PaperFormat", () => options.PaperFormat = paperFormat.Value);
            }

            return options;
        }

        /// <summary>Map an A-size onto ExportPaperFormat where the member exists (A0-A4 on 2024).</summary>
        internal static ExportPaperFormat? PaperFormatFor(string sizeName)
        {
            string name = (sizeName ?? "None").Trim().ToUpperInvariant();
            if (name == "A0" || name == "A1" || name == "A2" || name == "A3" || name == "A4" || name == "A5" || name == "A6")
            {
                foreach (string member in new[] { "ISO_" + name, name })
                {
                    if (Enum.IsDefined(typeof(ExportPaperFormat), member))
                        return (ExportPaperFormat)Enum.Parse(typeof(ExportPaperFormat), member);
                }
                return null;
            }
            return ExportPaperFormat.Default;
        }

        /// <summary>
        /// One PDF per job through Revit's own exporter. Each job is exported on its own
        /// with Combine on and FileName set, which is the only way to get the exact file
        /// name the naming rules asked for. Exporting them all in one call is faster but
        /// hands the naming back to Revit.
        /// </summary>
        public static Report ExportPdfNative(Document doc, IList<Job> jobs, IDictionary<string, string> profile,
                                             Action<int, int, string, string> progress = null,
                                             Func<bool> shouldStop = null, Report report = null)
        {
            report = report ?? new Report();
            var log = new List<string>();
            int total = jobs.Count;

            for (int index = 1; index <= total; index++)
            {
                Job job = jobs[index - 1];
                if (shouldStop != null && shouldStop())
                {
                    report.Cancelled = true;
                    break;
                }
                progress?.Invoke(index, total, job.Label, "PDF");

                string folder = job.FolderFor("pdf");
                var (made, error) = PsPaths.Ensure(folder);
                if (!made)
                {
                    report.Add(new Outcome(job.Key, job.Label, "PDF", "", false,
                                           "folder could not be made: " + error));
                    continue;
                }

                string target = PathJoin(folder, job.BaseName + ".pdf");
                if (PsPaths.LongPathRisk(target))
                    report.Note("Some paths are close to the 260 character limit; a shorter root folder would be safer.");

                PDFExportOptions options = BuildPdfOptions(profile, job.SizeInfo, log);
                if (options == null)
                {
                    report.Add(new Outcome(job.Key, job.Label, "PDF", target, false,
                                           "no built-in PDF exporter on this Revit"));
                    continue;
                }

                SetDirect(null, "Combine", () => options.Combine = true);
                SetDirect(null, "FileName", () => options.FileName = job.BaseName);

                if (Flag(profile, "out.overwrite", true))
                {
                    RemoveIfPresent(target);
                }
                else
                {
                    target = PsPaths.UniqueOnDisk(folder, job.BaseName, ".pdf");
                    string stem = SplitextStem(Basename(target));
                    SetDirect(null, "FileName", () => options.FileName = stem);
                }

                Debug("--- " + job.Label);
                Debug("native PDF export to " + target);
                try
                {
                    doc.Export(folder, IdList(new[] { job.ElementId }), options);
                    Debug("Document.Export returned with no error");
                }
                catch (Exception err)
                {
                    Debug("Document.Export threw: " + Msg(err));
                    report.Add(new Outcome(job.Key, job.Label, "PDF", target, false, Msg(err)));
                    continue;
                }

                bool landed = WaitFor(target);
                Debug("file on disk afterwards: " + (landed ? "True" : "False"));
                report.Add(new Outcome(job.Key, job.Label, "PDF", target, landed,
                                       landed ? "" : "Revit reported no error but no file appeared"));
            }

            foreach (string line in log)
                report.Note(line);
            return report;
        }

        /// <summary>Every job into one PDF, in the order given.</summary>
        public static Report ExportPdfCombined(Document doc, IList<Job> jobs, IDictionary<string, string> profile,
                                               string outName, Action<int, int, string, string> progress = null,
                                               Report report = null)
        {
            report = report ?? new Report();
            if (jobs == null || jobs.Count == 0)
                return report;
            var log = new List<string>();
            string folder = jobs[0].FolderFor("pdf");
            var (made, error) = PsPaths.Ensure(folder);
            if (!made)
            {
                report.Add(new Outcome(0, outName, "PDF", "", false, "folder could not be made: " + error));
                return report;
            }

            PDFExportOptions options = BuildPdfOptions(profile, jobs[0].SizeInfo, log);
            if (options == null)
            {
                report.Add(new Outcome(0, outName, "PDF", "", false, "no built-in PDF exporter on this Revit"));
                return report;
            }

            SetDirect(null, "Combine", () => options.Combine = true);
            SetDirect(null, "FileName", () => options.FileName = outName);

            string target = PathJoin(folder, outName + ".pdf");
            if (Flag(profile, "out.overwrite", true))
                RemoveIfPresent(target);

            progress?.Invoke(1, 1, outName, "PDF");

            try
            {
                doc.Export(folder, IdList(jobs.Select(job => job.ElementId)), options);
            }
            catch (Exception err)
            {
                report.Add(new Outcome(0, outName, "PDF", target, false, Msg(err)));
                return report;
            }

            bool landed = WaitFor(target);
            report.Add(new Outcome(0, outName, "PDF", target, landed,
                                   landed ? "" : "Revit reported no error but no file appeared"));
            foreach (string line in log)
                report.Note(line);
            return report;
        }

        // ======================================================================
        // PDF through a printer driver
        // ======================================================================

        /// <summary>
        /// One PDF per job through an installed print driver such as PDF24.
        ///
        /// The driver route exists because a house PDF setup (compression, fonts, stamps)
        /// lives in the driver, not in Revit. What it costs is paper size matching: Revit
        /// prints onto whatever paper the driver offers, and a sheet whose size the driver
        /// does not have comes out scaled with no warning. So the size is matched per sheet
        /// and a sheet that cannot be matched is refused rather than printed wrong.
        /// </summary>
        public static Report ExportPdfPrinter(Document doc, IList<Job> jobs, IDictionary<string, string> profile,
                                              string printerName, Action<int, int, string, string> progress = null,
                                              Func<bool> shouldStop = null, Report report = null)
        {
            report = report ?? new Report();
            var log = new List<string>();
            int total = jobs.Count;

            PrintManager manager;
            try
            {
                manager = doc.PrintManager;
            }
            catch (Exception err)
            {
                report.Note("no print manager: " + Msg(err));
                foreach (Job job in jobs)
                    report.Add(new Outcome(job.Key, job.Label, "PDF", "", false, "the print manager is not available"));
                return report;
            }

            // No transaction around any of this.
            //
            // The paper size lives on PrintParameters, which is a document element, so
            // changing it DOES need one - but SubmitPrint must be called with none open.
            // Revit 2024 and later do not throw when it is: the call returns, immediately
            // and successfully, having printed nothing at all.
            //
            // So the transaction is opened per sheet, around the setup only, and committed
            // before the job is submitted. See PrintSetupOk.
            try
            {
                Debug(string.Format(Inv, "printer route: selecting driver \"{0}\"", printerName));
                try
                {
                    manager.SelectNewPrintDriver(printerName);
                }
                catch (Exception err)
                {
                    report.Note(string.Format(Inv, "could not select \"{0}\": {1}", printerName, Msg(err)));
                    foreach (Job job in jobs)
                        report.Add(new Outcome(job.Key, job.Label, "PDF", "", false,
                                               string.Format(Inv, "printer \"{0}\" could not be selected", printerName)));
                    return report;
                }

                string staging = Text(profile, "pdf.staging");
                if (staging.Length > 0)
                {
                    Debug("staging route: collecting from " + staging);
                    // The driver is going to save where its own settings say, so asking
                    // Revit to redirect the output would only confuse it.
                    SetDirect(log, "PrintToFile", () => manager.PrintToFile = false);
                }
                else
                {
                    SetDirect(log, "PrintToFile", () => manager.PrintToFile = true);
                }
                SetDirect(null, "CombinedFile", () => manager.CombinedFile = false);
                SetDirect(log, "PrintRange", () => manager.PrintRange = PrintRange.Current);

                Dictionary<string, long> runBefore = staging.Length > 0 ? FolderSnapshot(staging) : new Dictionary<string, long>();
                var sizes = PrinterPaperSizes(doc);
                string offered = string.Join(", ", sizes.Take(40).Select(s => s.Name));
                Debug(string.Format(Inv, "driver offers {0} paper size(s): {1}", sizes.Count, offered.Length > 0 ? offered : "none"));
                if (sizes.Count == 0)
                    report.Note("the driver reported no paper sizes; sheets will print on whatever it defaults to");

                int writtenSoFar = 0;
                for (int index = 1; index <= total; index++)
                {
                    Job job = jobs[index - 1];
                    if (shouldStop != null && shouldStop())
                    {
                        report.Cancelled = true;
                        break;
                    }

                    // A driver that produced nothing for the first sheet will produce nothing
                    // for the next hundred, each costing ten seconds of waiting. Stop and say so.
                    if (index > 1 && writtenSoFar == 0 && report.Failed().Count > 0)
                    {
                        int skipped = jobs.Count - index + 1;
                        report.Note(string.Format(Inv,
                            "Stopped after the first sheet produced no file. The remaining {0} sheet(s) were not " +
                            "attempted, because the same thing would happen to each of them. Fix the driver or the " +
                            "\"Driver saves to\" folder and run again.", skipped));
                        Debug(string.Format(Inv, "stopping early: first sheet produced nothing, {0} skipped", skipped));
                        report.Cancelled = true;
                        break;
                    }

                    progress?.Invoke(index, total, job.Label, "PDF");

                    string folder = job.FolderFor("pdf");
                    var (made, error) = PsPaths.Ensure(folder);
                    if (!made)
                    {
                        report.Add(new Outcome(job.Key, job.Label, "PDF", "", false, "folder could not be made: " + error));
                        continue;
                    }

                    string target = PathJoin(folder, job.BaseName + ".pdf");
                    if (!Flag(profile, "out.overwrite", true))
                        target = PsPaths.UniqueOnDisk(folder, job.BaseName, ".pdf");
                    else
                        RemoveIfPresent(target);

                    Debug("--- " + job.Label);
                    Debug("target path: " + target);
                    var (ok, message) = PrintSetupOk(doc, manager, profile, job.SizeInfo, sizes, log);
                    Debug("print setup: " + (ok ? "applied" : "REFUSED - " + message));
                    if (!ok)
                    {
                        report.Add(new Outcome(job.Key, job.Label, "PDF", target, false, message));
                        continue;
                    }

                    var before = new Dictionary<string, long>();
                    if (staging.Length > 0)
                    {
                        var (stagingMade, stagingError) = PsPaths.Ensure(staging);
                        if (!stagingMade)
                        {
                            report.Add(new Outcome(job.Key, job.Label, "PDF", target, false,
                                                   "the staging folder could not be made: " + stagingError));
                            continue;
                        }
                        before = FolderSnapshot(staging);
                        Debug(string.Format(Inv, "{0} PDF(s) already in the staging folder", before.Count));
                    }
                    else
                    {
                        string printTo = target;
                        bool tookPath = SetDirect(log, "PrintToFileName", () => manager.PrintToFileName = printTo);
                        Debug("PrintToFileName accepted by the API: " + (tookPath ? "True" : "False"));
                    }
                    try
                    {
                        manager.Apply();
                        Debug("PrintManager.Apply() returned");
                    }
                    catch (Exception err)
                    {
                        log.Add("print settings would not apply: " + Msg(err));
                        Debug("PrintManager.Apply() threw: " + Msg(err));
                    }

                    double spent = 0.0;
                    try
                    {
                        var started = System.Diagnostics.Stopwatch.StartNew();
                        manager.SubmitPrint(job.View);
                        spent = started.Elapsed.TotalSeconds;
                        Debug(string.Format(Inv, "SubmitPrint returned with no error after {0}s", spent.ToString("0.00", Inv)));
                        if (spent < 0.5)
                            Debug("   that is too quick to have rendered a sheet. A submit that returns instantly has " +
                                  "printed nothing - the usual cause is a transaction still open, which Revit does not " +
                                  "complain about.");
                    }
                    catch (Exception err)
                    {
                        Debug("SubmitPrint threw: " + Msg(err));
                        report.Add(new Outcome(job.Key, job.Label, "PDF", target, false, Msg(err)));
                        continue;
                    }

                    if (staging.Length > 0)
                    {
                        double budget = DriverWaitBudget(spent);
                        Debug(string.Format(Inv, "waiting up to {0}s for \"{1}\" to write it", budget.ToString("0", Inv), printerName));
                        string arrived = WaitForNewPdf(staging, before, seconds: budget, shouldStop: shouldStop);
                        if (string.IsNullOrEmpty(arrived))
                        {
                            Debug("nothing new arrived in the staging folder");
                            var (waiting, status) = QueueState(printerName);
                            string stuck;
                            if (waiting > 0)
                            {
                                Debug(string.Format(Inv, "{0} job(s) still sitting in the Windows print queue for \"{1}\" (status: {2})",
                                    waiting, printerName, string.IsNullOrEmpty(status) ? "unknown" : status));
                                stuck = string.Format(Inv,
                                    "{0} job(s) are still sitting in the Windows print queue for \"{1}\", so it took the " +
                                    "sheet and has not finished with it. That is the driver waiting on something - usually " +
                                    "its own Save As or assistant window, open behind Revit.", waiting, printerName);
                            }
                            else if (waiting == 0)
                            {
                                Debug(string.Format(Inv,
                                    "the Windows print queue for \"{0}\" is empty, so the driver finished with the job and " +
                                    "wrote it somewhere else - or discarded it", printerName));
                                stuck = string.Format(Inv,
                                    "The Windows print queue for \"{0}\" is empty, so it finished with the sheet and either " +
                                    "wrote it somewhere other than {1} or threw it away. Automatic saving is most likely off.",
                                    printerName, staging);
                            }
                            else
                            {
                                Debug("could not read the print queue: " + status);
                                stuck = string.Format(Inv,
                                    "\"{0}\" is most likely still asking where to save rather than saving on its own.", printerName);
                            }
                            report.Add(new Outcome(job.Key, job.Label, "PDF", target, false,
                                string.Format(Inv, "nothing appeared in {0} within {1}s. {2}", staging, budget.ToString("0", Inv), stuck)));
                            continue;
                        }
                        Debug("driver wrote " + arrived);
                        var (moved, detail) = MoveIntoPlace(arrived, target, Flag(profile, "out.overwrite", true));
                        Debug(string.Format(Inv, "moved into place: {0} ({1})", moved ? "True" : "False", detail));
                        if (moved)
                            writtenSoFar += 1;
                        report.Add(new Outcome(job.Key, job.Label, "PDF", moved ? detail : target, moved,
                            moved ? "" : string.Format(Inv, "the driver wrote {0} but it could not be moved: {1}", arrived, detail)));
                        continue;
                    }

                    bool landed = WaitFor(target, attempts: 40);
                    Debug("waited 10s for the file: " + (landed ? "it arrived" : "NOTHING ARRIVED"));
                    if (landed)
                        writtenSoFar += 1;
                    report.Add(new Outcome(job.Key, job.Label, "PDF", target, landed,
                                           landed ? "" : "no file appeared at " + target));
                }
                // One last look before calling it a failure.
                //
                // A driver slower than the wait means the file lands after the tool has
                // moved on. Anything that turned up late is claimed here and named.
                if (staging.Length > 0 && writtenSoFar == 0 && !report.Cancelled)
                {
                    List<string> late = LateArrivals(staging, runBefore);
                    if (late.Count > 0)
                    {
                        Debug(string.Format(Inv, "{0} PDF(s) turned up in the staging folder after the run gave up", late.Count));
                        report.Note(string.Format(Inv,
                            "{0} PDF(s) appeared in {1} after the tool had stopped waiting, so \"{2}\" is simply slower " +
                            "than the wait allowed. They are still there, under the driver's own names, and the next run " +
                            "will wait longer.", late.Count, staging, printerName));
                    }
                }
            }
            finally
            {
                foreach (string line in log)
                    report.Note(line);
            }
            return report;
        }

        /// <summary>
        /// Apply the print setup inside a transaction, and close it again. Committed before
        /// returning, always. The caller submits the print job straight afterwards and
        /// SubmitPrint with a transaction still open prints nothing while reporting success.
        /// </summary>
        internal static (bool Ok, string Message) PrintSetupOk(Document doc, PrintManager manager,
            IDictionary<string, string> profile, PsModel.SheetSize sizeInfo,
            List<(string Name, PaperSize Paper)> sizes, List<string> log)
        {
            Transaction transaction = null;
            try
            {
                transaction = new Transaction(doc, "RevoBIM Pro Sheets print setup");
                QuietTransaction(transaction);
                transaction.Start();
            }
            catch (Exception err)
            {
                log.Add("could not start the print setup transaction: " + Msg(err));
                try { transaction?.Dispose(); } catch (Exception) { }
                transaction = null;
            }

            try
            {
                return ApplyPrintSetup(doc, manager, profile, sizeInfo, sizes, log);
            }
            finally
            {
                if (transaction != null)
                {
                    try
                    {
                        transaction.Commit();
                    }
                    catch (Exception)
                    {
                        try { transaction.RollBack(); } catch (Exception) { }
                    }
                    try { transaction.Dispose(); } catch (Exception) { }
                }
            }
        }

        /// <summary>Point the in-session print setting at the right paper and options.</summary>
        internal static (bool Ok, string Message) ApplyPrintSetup(Document doc, PrintManager manager,
            IDictionary<string, string> profile, PsModel.SheetSize sizeInfo,
            List<(string Name, PaperSize Paper)> sizes, List<string> log)
        {
            PrintSetup setup;
            try
            {
                setup = manager.PrintSetup;
            }
            catch (Exception err)
            {
                return (false, "no print setup: " + Msg(err));
            }

            try
            {
                setup.CurrentPrintSetting = setup.InSession;
            }
            catch (Exception)
            {
            }

            PrintParameters parameters;
            try
            {
                parameters = setup.CurrentPrintSetting.PrintParameters;
            }
            catch (Exception err)
            {
                return (false, "no print parameters: " + Msg(err));
            }

            if (sizes != null && sizes.Count > 0 && Flag(profile, "pdf.keep_paper_size", true))
            {
                string wanted = sizeInfo != null ? (sizeInfo.Name ?? "") : "";
                double width = sizeInfo != null ? sizeInfo.WidthMm : 0.0;
                double height = sizeInfo != null ? sizeInfo.HeightMm : 0.0;
                PaperSize paper = MatchPaper(sizes, wanted, width, height);
                string described;
                try
                {
                    described = sizeInfo.Describe();
                }
                catch (Exception)
                {
                    described = wanted.Length > 0 ? wanted : "?";
                }
                string paperName;
                try { paperName = paper != null ? paper.Name : "NONE"; }
                catch (Exception) { paperName = "NONE"; }
                Debug(string.Format(Inv, "sheet wants {0}; driver paper matched: {1}", described, paperName));
                if (sizeInfo != null && !sizeInfo.Exact)
                    Debug("   that sheet is not a standard size and was fitted up");
                if (paper == null)
                    return (false, string.Format(Inv,
                        "\"{0}\" is not a paper size this driver offers - add it in the driver, or untick Keep Paper Size",
                        wanted.Length > 0 ? wanted : "this sheet"));
                SetDirect(log, "PaperSize", () => parameters.PaperSize = paper);
                bool landscape = sizeInfo == null || sizeInfo.Landscape;
                SetDirect(null, "PageOrientation", () => parameters.PageOrientation = Orientation(landscape));
            }

            string placement = Text(profile, "pdf.placement", "center");
            SetDirect(log, "PaperPlacement", () => parameters.PaperPlacement = Placement(placement));
            if (placement == "offset")
            {
                SetDirect(log, "MarginType", () => parameters.MarginType = Margin(Text(profile, "pdf.margin", "nomargin")));
                SetDirect(null, "OriginOffsetX", () => parameters.OriginOffsetX = Number(profile, "pdf.offset_x"));
                SetDirect(null, "OriginOffsetY", () => parameters.OriginOffsetY = Number(profile, "pdf.offset_y"));
            }

            string zoomMode = Text(profile, "pdf.zoom_mode", "zoom");
            SetDirect(log, "ZoomType", () => parameters.ZoomType = ZoomType(zoomMode));
            if (zoomMode == "zoom")
            {
                try
                {
                    SetDirect(log, "Zoom", () => parameters.Zoom = (int)Number(profile, "pdf.zoom", 100.0));
                }
                catch (Exception)
                {
                }
            }

            SetDirect(log, "HiddenLineViews", () => parameters.HiddenLineViews = HiddenLine(Text(profile, "pdf.hidden_line", "vector")));
            SetDirect(log, "RasterQuality", () => parameters.RasterQuality = RasterQuality(Text(profile, "pdf.raster_quality", "high")));
            SetDirect(log, "ColorDepth", () => parameters.ColorDepth = ColourDepth(Text(profile, "pdf.colors", "color")));

            SetDirect(log, "ViewLinksinBlue", () => parameters.ViewLinksinBlue = Flag(profile, "pdf.view_links_blue", true));
            SetDirect(log, "HideReforWorkPlanes", () => parameters.HideReforWorkPlanes = Flag(profile, "pdf.hide_ref_planes", true));
            SetDirect(log, "HideUnreferencedViewTags", () => parameters.HideUnreferencedViewTags = Flag(profile, "pdf.hide_unreferenced_tags", true));
            SetDirect(log, "HideScopeBoxes", () => parameters.HideScopeBoxes = Flag(profile, "pdf.hide_scope_boxes", true));
            SetDirect(log, "HideCropBoundaries", () => parameters.HideCropBoundaries = Flag(profile, "pdf.hide_crop_boundaries", true));
            SetDirect(log, "ReplaceHalftoneWithThinLines", () => parameters.ReplaceHalftoneWithThinLines = Flag(profile, "pdf.replace_halftone", false));
            SetDirect(log, "MaskCoincidentLines", () => parameters.MaskCoincidentLines = Flag(profile, "pdf.mask_coincident", false));
            return (true, "");
        }

        /// <summary>
        /// Point the print manager at a temporary saved set, for a combined file. A combined
        /// print needs PrintRange.Select and a real ViewSheetSet element in the model - there
        /// is no in-memory route. The set is reused by name rather than made fresh each run.
        /// </summary>
        public static (bool Ok, string Message) CombinedPrintSet(Document doc, PrintManager manager,
                                                                 IEnumerable<View> views, string setName = "RevoBIM Pro Sheets")
        {
            try
            {
                ViewSheetSetting setting = manager.ViewSheetSetting;
                var viewSet = new ViewSet();
                foreach (View view in views)
                    viewSet.Insert(view);
                setting.CurrentViewSheetSet.Views = viewSet;
                try
                {
                    setting.SaveAs(setName);
                }
                catch (Exception)
                {
                    setting.Save();
                }
                return (true, "");
            }
            catch (Exception err)
            {
                return (false, Msg(err));
            }
        }
    }
}
