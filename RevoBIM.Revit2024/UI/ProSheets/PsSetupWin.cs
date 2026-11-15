using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// First run setup: make this machine able to write a PDF before it tries.
    /// Port of ps_setupwin.py.
    ///
    /// Every setting this asks about is per machine and none of it is in the
    /// model, so a template that works on one desk can fail on the next with
    /// nothing to show for it but "no file appeared".
    ///
    /// The default is Revit's own exporter wherever it exists. A print driver
    /// needs its "Driver saves to" folder before a single file lands, so a driver
    /// is offered here, with the folder it needs on the same screen, instead of
    /// being chosen quietly on the user's behalf.
    /// </summary>
    public static partial class PsSetupWin
    {
        public const string RevitPdf = "Revit built-in PDF export";
        public const string NoParameter = "(this project has none)";
        public static readonly List<string> Papers = new List<string> { "A4 portrait", "A3 portrait", "A4 landscape", "A3 landscape" };

        /// <summary>
        /// The two logos the register's title band carries:
        /// slot: (setting, file name in %APPDATA%\RevoBIM, controls prefix, what).
        /// </summary>
        public static readonly Dictionary<string, (string Setting, string Stem, string Prefix, string What)> Logos =
            new Dictionary<string, (string Setting, string Stem, string Prefix, string What)>(StringComparer.Ordinal)
            {
                { "company", ("reg_logo", "register_logo", "SetupRegLogo", "company logo") },
                { "client", ("reg_client_logo", "register_client_logo", "SetupRegClientLogo", "client logo") },
            };

        /// <summary>Whether this machine has been through setup.</summary>
        public static bool Needed(PsConfig.Settings settings)
        {
            try
            {
                return !settings.Flag("setup_done", false);
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>os.path.normcase on Windows: lower case, forward slashes made back slashes.</summary>
        internal static string NormCase(string path)
        {
            return (path ?? "").Replace('/', '\\').ToLowerInvariant();
        }

        /// <summary>Modal. Show() returns true when settings were saved.</summary>
        public class SetupWindow
        {
            public Autodesk.Revit.DB.Document Doc;
            public string Focus;
            public Dictionary<string, string> LogoPaths = new Dictionary<string, string>(StringComparer.Ordinal)
            {
                { "company", "" }, { "client", "" },
            };
            public PsConfig.Settings Settings;
            public string ThemeName;
            public bool Saved;
            public List<string> SheetParameters;
            public List<string> ScaleParameters;
            public bool Native;
            public List<string> Printers;
            public string Preferred;

            public Window Window;
            public PsUi.Chrome Chrome;
            public Dictionary<string, object> Ui = new Dictionary<string, object>(StringComparer.Ordinal);

            public SetupWindow(Autodesk.Revit.DB.Document doc, PsConfig.Settings settings, string themeName = "dark", Window owner = null,
                bool firstRun = true, IEnumerable<(string Name, string Group)> catalogue = null, string focus = null)
            {
                Doc = doc;
                Focus = focus;
                Settings = settings;
                ThemeName = themeName;
                Saved = false;
                SheetParameters = ReadParameters(catalogue);
                // The Scale parameter may be the title block's rather than the
                // sheet's, so both are offered for it.
                ScaleParameters = SheetParameters.Concat(PsModel.TitleBlockParameterNames(doc))
                    .Distinct(StringComparer.Ordinal)
                    .OrderBy(one => (one ?? "").ToLowerInvariant(), StringComparer.Ordinal)
                    .ToList();
                Native = PsExport.NativePdfAvailable(doc);
                Printers = PsExport.ListPrinters();
                Preferred = PsExport.PreferredPrinter(Printers);

                Window = PsUi.LoadWindow("ProSheetsSetup.xaml", themeName);
                Chrome = new PsUi.Chrome(Window, onClose: () => Skip());
                if (owner != null)
                {
                    try
                    {
                        Window.Owner = owner;
                    }
                    catch (Exception)
                    {
                    }
                }

                foreach (string name in new[]
                         {
                             "IntroText", "NativeRadio", "NativeNote", "DriverRadio",
                             "DriverNote", "SetupPreferNative",
                             "SetupPrinterCombo", "SetupStagingBox",
                             "SetupStagingBrowse", "SetupStagingFind",
                             "SetupStagingNote",
                             "SetupRootBox", "SetupRootBrowse", "FoundText",
                             "SetupSeriesCombo", "SetupDisciplineCombo",
                             "SetupStatusCombo", "SetupParamNote",
                             "SetupScaleParamRadio", "SetupScaleRevitRadio",
                             "SetupScaleCombo",
                             "RegisterSection", "SetupRegTitle", "SetupRegLogoBox",
                             "SetupRegLogoBrowse", "SetupRegLogoClear",
                             "SetupRegLogoPreview", "SetupRegLogoNote",
                             "SetupRegClientLogoBox", "SetupRegClientLogoBrowse",
                             "SetupRegClientLogoClear", "SetupRegClientLogoPreview",
                             "SetupRegClientLogoNote", "SetupRegSnapshot",
                             "SetupRegLegend", "SetupRegFooter",
                             "SetupRegPaper", "RevisionSection", "SetupRevReopen",
                             "StatusText", "TestButton", "SkipButton", "OkButton",
                         })
                    Ui[name] = PsUi.Find(Window, name);

                if (!firstRun)
                {
                    PsUi.SetText(UiGet("IntroText"),
                        "Settings kept on this computer, not in the model. " +
                        "Changing them here changes what a new template starts " +
                        "with; templates already saved keep their own.");
                }

                Fill();
                FillRegister();
                Wire();
                SayWhatIsHere();
                ModeChanged();
                if (Focus == "register")
                {
                    try
                    {
                        Window.Loaded += (sender, args) => BringRegisterForward(sender, args);
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            /// <summary>self.ui.get(name): the control, or null.</summary>
            internal object UiGet(string name)
            {
                return Ui.TryGetValue(name, out object control) ? control : null;
            }

            internal T UiGet<T>(string name) where T : class
            {
                return UiGet(name) as T;
            }

            /// <summary>Opened from the register tab: start at the register's section.</summary>
            internal void BringRegisterForward(object sender = null, EventArgs args = null)
            {
                try
                {
                    ((FrameworkElement)UiGet("RegisterSection")).BringIntoView();
                }
                catch (Exception)
                {
                }
            }

            // ------------------------------------------------------------------
            /// <summary>
            /// Every parameter a sheet in this model actually carries. Taken from the
            /// window's own catalogue where there is one, so the model is not read
            /// twice for the same answer, and read here only when setup is opened
            /// without one.
            /// </summary>
            internal List<string> ReadParameters(IEnumerable<(string Name, string Group)> catalogue)
            {
                List<(string Name, string Group)> pairs = catalogue != null ? catalogue.ToList() : null;
                if (pairs == null || pairs.Count == 0)
                {
                    try
                    {
                        var rows = PsModel.ReadRows(Doc, "sheets");
                        pairs = PsModel.ParameterCatalogue(Doc, rows);
                    }
                    catch (Exception)
                    {
                        pairs = new List<(string Name, string Group)>();
                    }
                }
                var names = new List<string>();
                foreach (var pair in pairs ?? new List<(string Name, string Group)>())
                {
                    string name = PsUi.PyStr(pair.Name);
                    if (name.Length > 0 && !names.Contains(name))
                        names.Add(name);
                }
                return names.OrderBy(one => one.ToLowerInvariant(), StringComparer.Ordinal).ToList();
            }

            /// <summary>
            /// Offer the model's parameters, with the saved one selected. A saved
            /// name this model does not have is still offered rather than dropped:
            /// the answer to "which parameter is it" should not silently become
            /// something else because one project has not got it.
            /// </summary>
            internal void FillParameterCombos()
            {
                var missing = new List<string>();
                foreach (var (controlName, key, names) in new[]
                         {
                             ("SetupSeriesCombo", "param_series", SheetParameters),
                             ("SetupDisciplineCombo", "param_discipline", SheetParameters),
                             ("SetupStatusCombo", "reg_status_param", SheetParameters),
                             ("SetupScaleCombo", "reg_scale_param", ScaleParameters),
                         })
                {
                    string wanted = Settings.Text(key, "");
                    var offered = new List<string> { NoParameter };
                    offered.AddRange(names);
                    if (!string.IsNullOrEmpty(wanted) && !offered.Contains(wanted))
                    {
                        offered.Insert(1, wanted);
                        missing.Add(wanted);
                    }
                    PsUi.FillCombo(UiGet<ComboBox>(controlName), offered,
                        selected: !string.IsNullOrEmpty(wanted) ? wanted : NoParameter);
                }
                if (missing.Count > 0)
                {
                    PsUi.SetText(UiGet("SetupParamNote"), string.Format(
                        "Not on the sheets in this model: {0}. Left as it is in " +
                        "case this is not the project it was meant for - pick " +
                        "another, or \"{1}\", if it is.",
                        string.Join(", ", missing.Select(one => "\"" + one + "\"")), NoParameter));
                }
                else
                {
                    PsUi.SetText(UiGet("SetupParamNote"), "");
                }
            }

            internal string ChosenParameter(string controlName)
            {
                string name = PsUi.ComboText(UiGet<ComboBox>(controlName), NoParameter);
                return name == NoParameter ? "" : name;
            }

            internal void Fill()
            {
                string chosen = Settings.Text("default_printer") ?? "";
                if (chosen.Length == 0)
                    chosen = Native ? RevitPdf : Preferred;
                string selected = chosen != RevitPdf ? chosen : (string.IsNullOrEmpty(Preferred) ? null : Preferred);
                PsUi.FillCombo(UiGet<ComboBox>("SetupPrinterCombo"), Printers, selected: selected);

                bool useNative = Native && (string.IsNullOrEmpty(chosen) || chosen == RevitPdf);
                try
                {
                    UiGet<RadioButton>("NativeRadio").IsChecked = useNative;
                    UiGet<RadioButton>("DriverRadio").IsChecked = !useNative;
                    UiGet<RadioButton>("NativeRadio").IsEnabled = Native;
                }
                catch (Exception)
                {
                }
                if (!Native)
                {
                    PsUi.SetText(UiGet("NativeNote"),
                        "Not on this Revit. Revit gained its own PDF exporter in " +
                        "2022; before that a print driver is the only route.");
                }

                try
                {
                    string root = Settings.Text("default_root");
                    UiGet<TextBox>("SetupRootBox").Text = !string.IsNullOrEmpty(root) ? root : SuggestRoot();
                }
                catch (Exception)
                {
                }
                try
                {
                    UiGet<CheckBox>("SetupPreferNative").IsChecked = Settings.Flag("prefer_native_pdf", true);
                }
                catch (Exception)
                {
                }
                FillParameterCombos();
                RecallStaging();
            }

            // ------------------------------------------------------------------
            // the Document Register's form
            // ------------------------------------------------------------------

            internal void FillRegister()
            {
                var store = Settings.Store;
                try
                {
                    UiGet<TextBox>("SetupRegTitle").Text = Settings.Text("reg_title");
                    UiGet<TextBox>("SetupRegFooter").Text = Settings.Text("reg_footer");
                    UiGet<TextBox>("SetupRegLegend").Text = string.Join("\n", PsConfig.GetList(store, "reg_legend"));
                    UiGet<TextBox>("SetupRegSnapshot").Text =
                        store.TryGetValue("reg_snapshot", out string snapshot) && snapshot != null ? snapshot : "";
                }
                catch (Exception)
                {
                }
                bool byParameter = Settings.Text("reg_scale_mode", "") != PsConfig.ScaleRevit;
                try
                {
                    UiGet<RadioButton>("SetupScaleParamRadio").IsChecked = byParameter;
                    UiGet<RadioButton>("SetupScaleRevitRadio").IsChecked = !byParameter;
                }
                catch (Exception)
                {
                }
                string paper = Settings.Text("reg_paper", "");
                if (string.IsNullOrEmpty(paper)) paper = Papers[0];
                PsUi.FillCombo(UiGet<ComboBox>("SetupRegPaper"), Papers,
                    selected: Papers.Contains(paper) ? paper : Papers[0]);
                foreach (string slot in Logos.Keys)
                    ShowLogo(Settings.Text(Logos[slot].Setting, ""), slot);
                try
                {
                    UiGet<CheckBox>("SetupRevReopen").IsChecked = Settings.Flag("rev_reopen", true);
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Put a logo in its preview, or say there is none.</summary>
            internal void ShowLogo(string path, string slot = "company")
            {
                string prefix = Logos[slot].Prefix;
                bool usable = !string.IsNullOrEmpty(path) && File.Exists(path) && PsXlsx.ImageSize(path) != null;
                LogoPaths[slot] = usable ? path : "";
                try
                {
                    UiGet<TextBox>(prefix + "Box").Text = LogoPaths[slot];
                }
                catch (Exception)
                {
                }
                var image = usable ? PsUi.LoadBitmap(LogoPaths[slot]) : null;
                try
                {
                    UiGet<Image>(prefix + "Preview").Source = image;
                }
                catch (Exception)
                {
                }
                if (!string.IsNullOrEmpty(path) && !usable)
                    PsUi.SetText(UiGet(prefix + "Note"), "Not found - choose it again");
                else
                    PsUi.SetText(UiGet(prefix + "Note"), usable ? "" : "No logo");
            }

            /// <summary>
            /// Pick a PNG or JPG and keep a copy of it beside the settings. A copy,
            /// because a logo on a network drive or in somebody's Downloads is gone
            /// the day the register is next exported, and the form would quietly
            /// lose its band. Each slot has its own file, so choosing the client's
            /// never replaces the company's.
            /// </summary>
            internal void BrowseLogo(object sender = null, RoutedEventArgs args = null, string slot = "company")
            {
                var (_, stem, _, what) = Logos[slot];
                string chosen = PickImage(string.Format("Choose the {0}", what));
                if (string.IsNullOrEmpty(chosen)) return;
                if (PsXlsx.ImageSize(chosen) == null)
                {
                    Say("That is not a PNG or JPG this can read.");
                    return;
                }
                string target = LogoTarget(PsConfig.AppdataRoot(), stem, chosen);
                try
                {
                    foreach (string old in new[] { ".png", ".jpg", ".jpeg" })
                    {
                        string stale = Path.Combine(PsConfig.AppdataRoot(), stem + old);
                        if (NormCase(stale) != NormCase(target) && File.Exists(stale))
                            File.Delete(stale);
                    }
                    if (NormCase(chosen) != NormCase(target))
                        File.Copy(chosen, target, true);
                }
                catch (Exception err)
                {
                    Say(string.Format("The {0} could not be copied: {1}", what, err.Message));
                    return;
                }
                ShowLogo(target, slot);
                Say(string.Format("{0} set. It goes in the register's title band.",
                    what.Substring(0, Math.Min(1, what.Length)).ToUpperInvariant() + (what.Length > 1 ? what.Substring(1) : "")));
            }

            internal void ClearLogo(object sender = null, RoutedEventArgs args = null, string slot = "company")
            {
                ShowLogo("", slot);
                Say(string.Format("No {0} on the register.", Logos[slot].What));
            }

            internal void BrowseClientLogo(object sender = null, RoutedEventArgs args = null)
            {
                BrowseLogo(sender, args, "client");
            }

            internal void ClearClientLogo(object sender = null, RoutedEventArgs args = null)
            {
                ClearLogo(sender, args, "client");
            }

            /// <summary>A multi-line box as a list, blank lines dropped.</summary>
            public static List<string> LinesOf(string text)
            {
                return (text ?? "").Replace("\r", "").Split('\n')
                    .Where(line => line.Trim().Length > 0)
                    .Select(line => line.Trim())
                    .ToList();
            }

            /// <summary>The folder the model sits in, else Documents.</summary>
            internal string SuggestRoot()
            {
                try
                {
                    string here = Path.GetDirectoryName(Doc.PathName ?? "");
                    if (!string.IsNullOrEmpty(here) && Directory.Exists(here))
                        return here;
                }
                catch (Exception)
                {
                }
                try
                {
                    return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Documents");
                }
                catch (Exception)
                {
                    return "";
                }
            }

            internal void RecallStaging()
            {
                string printer = PsUi.ComboText(UiGet<ComboBox>("SetupPrinterCombo"));
                try
                {
                    UiGet<TextBox>("SetupStagingBox").Text = Settings.Text(PsConfig.StagingKey(printer), "");
                }
                catch (Exception)
                {
                }
            }

            internal void SayWhatIsHere()
            {
                var lines = new List<string>();
                lines.Add(string.Format("Revit's own PDF exporter: {0}",
                    Native ? "yes" : "no, this Revit is older than 2022"));
                lines.Add(string.Format("{0} printer(s) installed.", Printers.Count));
                if (!string.IsNullOrEmpty(Preferred))
                {
                    lines.Add(string.Format(
                        "\"{0}\" is installed. That is ProSheets' own instance of " +
                        "PDF24, already set not to ask where to save - but like " +
                        "any PDF24 it writes to PDF24's output folder rather than " +
                        "the path Revit asks for, so it still needs \"Driver saves " +
                        "to\" filled in below.", Preferred));
                }
                PsUi.SetText(UiGet("FoundText"), string.Join("\n", lines));
            }

            internal void Wire()
            {
                foreach (var (name, handler) in new (string, RoutedEventHandler)[]
                         {
                             ("OkButton", (s, a) => SaveSettings(s, a)),
                             ("SkipButton", (s, a) => Skip(s, a)),
                             ("TestButton", (s, a) => Test(s, a)),
                             ("SetupStagingBrowse", (s, a) => BrowseStaging(s, a)),
                             ("SetupStagingFind", (s, a) => FindStaging(s, a)),
                             ("SetupRootBrowse", (s, a) => BrowseRoot(s, a)),
                             ("SetupRegLogoBrowse", (s, a) => BrowseLogo(s, a)),
                             ("SetupRegLogoClear", (s, a) => ClearLogo(s, a)),
                             ("SetupRegClientLogoBrowse", (s, a) => BrowseClientLogo(s, a)),
                             ("SetupRegClientLogoClear", (s, a) => ClearClientLogo(s, a)),
                         })
                {
                    if (!(UiGet(name) is ButtonBase control)) continue;
                    try
                    {
                        control.Click += handler;
                    }
                    catch (Exception)
                    {
                    }
                }
                foreach (string name in new[] { "NativeRadio", "DriverRadio" })
                {
                    if (!(UiGet(name) is ToggleButton control)) continue;
                    try
                    {
                        control.Checked += (s, a) => OnMode(s, a);
                    }
                    catch (Exception)
                    {
                    }
                }
                if (UiGet("SetupPrinterCombo") is ComboBox combo)
                {
                    try
                    {
                        combo.SelectionChanged += (s, a) => OnPrinter(s, a);
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            // ------------------------------------------------------------------
            internal bool DriverChosen()
            {
                try
                {
                    return UiGet<RadioButton>("DriverRadio").IsChecked == true;
                }
                catch (Exception)
                {
                    return false;
                }
            }

            internal void OnMode(object sender = null, RoutedEventArgs args = null)
            {
                ModeChanged();
            }

            internal void OnPrinter(object sender = null, RoutedEventArgs args = null)
            {
                RecallStaging();
                ModeChanged();
            }

            internal void ModeChanged()
            {
                bool driver = DriverChosen();
                // The override only means anything while the built-in exporter
                // is the choice; picking a driver is the override.
                try
                {
                    UiGet<CheckBox>("SetupPreferNative").IsEnabled = Native && !driver;
                    if (driver)
                        UiGet<CheckBox>("SetupPreferNative").IsChecked = false;
                }
                catch (Exception)
                {
                }
                foreach (string name in new[] { "SetupPrinterCombo", "SetupStagingBox", "SetupStagingBrowse", "SetupStagingFind" })
                {
                    if (!(UiGet(name) is UIElement control)) continue;
                    try
                    {
                        control.IsEnabled = driver;
                    }
                    catch (Exception)
                    {
                    }
                }
                if (!driver)
                {
                    PsUi.SetText(UiGet("SetupStagingNote"), "");
                    Say("Revit writes the files itself. Nothing else needed.");
                    return;
                }

                string printer = PsUi.ComboText(UiGet<ComboBox>("SetupPrinterCombo"));
                string staging = Text("SetupStagingBox");
                var known = PsExport.KnownPrinter(printer);
                if (staging.Length == 0)
                {
                    PsUi.SetText(UiGet("SetupStagingNote"),
                        "Needed, and it has to be the folder the driver itself " +
                        "is set to save into - open the driver's own preferences " +
                        "to find out which that is. Typing where you want the " +
                        "PDFs does not work: the tool collects from this folder " +
                        "and renames, it cannot move the driver's output.");
                    Say(string.Format("\"{0}\" needs a folder above before it can write anything.",
                        !string.IsNullOrEmpty(printer) ? printer : "That driver"));
                }
                else
                {
                    PsUi.SetText(UiGet("SetupStagingNote"),
                        "Give it a folder of its own. Collecting takes whatever " +
                        "new PDF turns up while a run is going, so a folder used " +
                        "for other things will pick up somebody else's file.");
                    if (known == null)
                        Say(string.Format("\"{0}\" must also be set not to ask where to save.", printer));
                    else
                        Say(string.Format("\"{0}\" is already set not to ask where to save.", printer));
                }
            }

            internal string Text(string name)
            {
                try
                {
                    object control = UiGet(name);
                    if (control is TextBox box) return box.Text ?? "";
                    if (control is TextBlock block) return block.Text ?? "";
                    if (control is ComboBox combo) return combo.Text ?? "";
                    return "";
                }
                catch (Exception)
                {
                    return "";
                }
            }

            internal void Say(string text)
            {
                PsUi.SetText(UiGet("StatusText"), text);
            }

            // ------------------------------------------------------------------
            internal void BrowseRoot(object sender = null, RoutedEventArgs args = null)
            {
                string chosen = PsUi.BrowseFolder(Text("SetupRootBox"));
                if (!string.IsNullOrEmpty(chosen))
                {
                    try
                    {
                        UiGet<TextBox>("SetupRootBox").Text = chosen;
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal void BrowseStaging(object sender = null, RoutedEventArgs args = null)
            {
                string chosen = PsUi.BrowseFolder(Text("SetupStagingBox"));
                if (!string.IsNullOrEmpty(chosen))
                {
                    try
                    {
                        UiGet<TextBox>("SetupStagingBox").Text = chosen;
                    }
                    catch (Exception)
                    {
                    }
                    ModeChanged();
                }
            }

            /// <summary>Look for where the driver has been writing, and fill it in.</summary>
            internal void FindStaging(object sender = null, RoutedEventArgs args = null)
            {
                Say("Looking for PDFs written in the last few minutes...");
                List<string> found;
                try
                {
                    found = PsExport.FindRecentPdfs(600);
                }
                catch (Exception err)
                {
                    Say(string.Format("The search failed: {0}", err.Message));
                    return;
                }
                var folders = new List<string>();
                foreach (string path in found)
                {
                    string folder = Path.GetDirectoryName(path) ?? "";
                    if (!folders.Contains(folder)) folders.Add(folder);
                }

                if (folders.Count == 0)
                {
                    new PsUi.Prompt(
                        title: "Find the folder",
                        headline: "Nothing has been written recently.",
                        message: "The search looks for PDFs this machine has " +
                                 "written in the last ten minutes, so there has to " +
                                 "be one to find.",
                        detail: "1.  Open the driver's own settings and turn ON " +
                                "automatic saving, with an output folder of its " +
                                "own.\n\n" +
                                "2.  Print anything to that printer once - a " +
                                "Notepad page will do.\n\n" +
                                "3.  Come back and press Find it again.\n\n" +
                                "If the driver is set to ASK where to save, it will " +
                                "never work with this tool. Either turn automatic " +
                                "saving on, or use Revit's own exporter, which " +
                                "needs none of this.",
                        primary: "Close", themeName: ThemeName,
                        owner: Window).Show();
                    Say("Nothing found. Print one page to the driver first.");
                    return;
                }

                if (folders.Count == 1)
                {
                    try
                    {
                        UiGet<TextBox>("SetupStagingBox").Text = folders[0];
                    }
                    catch (Exception)
                    {
                    }
                    ModeChanged();
                    Say(string.Format("Found it: {0}", folders[0]));
                    return;
                }

                // More than one place had a recent PDF, so guessing would be
                // worse than asking. Say which they are and let them pick.
                new PsUi.Prompt(
                    title: "Find the folder",
                    headline: "More than one folder had a recent PDF.",
                    message: "Pick whichever of these is the driver's own output " +
                             "folder and type or browse to it. A folder used for " +
                             "anything else is the wrong answer even if the PDF is " +
                             "in it.",
                    detail: string.Join("\n", folders.Take(12)), primary: "Close",
                    themeName: ThemeName, owner: Window).Show();
                Say(string.Format("{0} folders had a recent PDF - pick the driver's own.", folders.Count));
            }

            /// <summary>Say what would happen, without writing anything.</summary>
            internal void Test(object sender = null, RoutedEventArgs args = null)
            {
                var problems = Problems();
                if (problems.Count == 0)
                {
                    Say("Looks right. Nothing has been written - this only checks the settings.");
                    return;
                }
                new PsUi.Prompt(
                    title: "Set up this machine",
                    headline: "This would not write a file yet.",
                    message: "Each of these has to be sorted before a run can produce anything.",
                    detail: string.Join("\n\n", problems), primary: "Close",
                    themeName: ThemeName, owner: Window).Show();
            }

            /// <summary>Everything that would stop a run writing a file, in words.</summary>
            public List<string> Problems()
            {
                var found = new List<string>();
                if (DriverChosen())
                {
                    string printer = PsUi.ComboText(UiGet<ComboBox>("SetupPrinterCombo"));
                    if (string.IsNullOrEmpty(printer))
                        found.Add("No printer is chosen.");
                    if (Text("SetupStagingBox").Length == 0)
                    {
                        found.Add(
                            "\"Driver saves to\" is empty. A print driver writes to " +
                            "its own output folder, and the tool collects the file " +
                            "from there - with nothing to collect from, every " +
                            "sheet reports \"no file appeared\". Either fill it in, " +
                            "or use Revit's own exporter, which needs no folder.");
                    }
                }
                else if (!Native)
                {
                    found.Add("Revit's own exporter does not exist before " +
                              "Revit 2022, so a print driver has to be used here.");
                }
                string root = Text("SetupRootBox");
                if (root.Length > 0)
                {
                    var (ok, error) = PsPaths.Writable(root);
                    if (!ok)
                        found.Add(string.Format("The export folder cannot be written to: {0}", error));
                }
                return found;
            }

            // ------------------------------------------------------------------
            /// <summary>The Python's _save. Named SaveSettings so it does not read as Settings.Save.</summary>
            internal void SaveSettings(object sender = null, RoutedEventArgs args = null)
            {
                string printer = "";
                if (DriverChosen())
                {
                    printer = PsUi.ComboText(UiGet<ComboBox>("SetupPrinterCombo"));
                    string staging = Text("SetupStagingBox");
                    if (!string.IsNullOrEmpty(printer) && staging.Length > 0)
                        Settings.Set(PsConfig.StagingKey(printer), staging);
                }
                bool prefer;
                try
                {
                    prefer = UiGet<CheckBox>("SetupPreferNative").IsChecked == true;
                }
                catch (Exception)
                {
                    prefer = true;
                }
                // Choosing a driver at all means not preferring the built-in
                // exporter. Saving both would store a setting that the very next
                // template load quietly undoes.
                if (!string.IsNullOrEmpty(printer))
                    prefer = false;
                Settings.Set("prefer_native_pdf", prefer ? "1" : "0");
                Settings.Set("default_printer", printer);
                Settings.Set("default_root", Text("SetupRootBox"));
                Settings.Set("param_series", ChosenParameter("SetupSeriesCombo"));
                Settings.Set("param_discipline", ChosenParameter("SetupDisciplineCombo"));
                string title = Text("SetupRegTitle").Trim();
                Settings.Set("reg_title", title.Length > 0 ? title : PsConfig.SettingsDefaults["reg_title"]);
                Settings.Set("reg_footer", Text("SetupRegFooter").Trim());
                Settings.Set("reg_legend", PsConfig.PutList(LinesOf(Text("SetupRegLegend"))));
                Settings.Set("reg_status_param", ChosenParameter("SetupStatusCombo"));
                Settings.Set("reg_scale_param", ChosenParameter("SetupScaleCombo"));
                bool byRevit;
                try
                {
                    byRevit = UiGet<RadioButton>("SetupScaleRevitRadio").IsChecked == true;
                }
                catch (Exception)
                {
                    byRevit = false;
                }
                Settings.Set("reg_scale_mode", byRevit ? PsConfig.ScaleRevit : PsConfig.ScaleParameter);
                foreach (string slot in Logos.Keys)
                    Settings.Set(Logos[slot].Setting, LogoPaths[slot]);
                Settings.Set("reg_snapshot", Text("SetupRegSnapshot").Trim());
                try
                {
                    Settings.Set("rev_reopen", UiGet<CheckBox>("SetupRevReopen").IsChecked == true ? "1" : "0");
                }
                catch (Exception)
                {
                }
                string paper = PsUi.ComboText(UiGet<ComboBox>("SetupRegPaper"), Papers[0]);
                Settings.Set("reg_paper", !string.IsNullOrEmpty(paper) ? paper : Papers[0]);
                Settings.Set("setup_done", "1");
                Settings.Save();
                Saved = true;
                Close();
            }

            internal void Skip(object sender = null, RoutedEventArgs args = null)
            {
                // Not marked done. Somebody who closes this without answering gets
                // asked again next time, which is the right way round: the cost of
                // asking twice is a click, the cost of not asking is a failed
                // issue.
                Close();
            }

            internal void Close()
            {
                try
                {
                    Window.Close();
                }
                catch (Exception)
                {
                }
            }

            public bool Show()
            {
                try
                {
                    Window.ShowDialog();
                }
                catch (Exception)
                {
                }
                return Saved;
            }
        }

        /// <summary>Where a chosen logo is copied: its slot's own name, its own type.</summary>
        public static string LogoTarget(string folder, string stem, string chosen)
        {
            string extension = (Path.GetExtension(chosen ?? "") ?? "").ToLowerInvariant();
            return Path.Combine(folder, stem + extension);
        }

        /// <summary>An image file chosen by the user, or an empty string.</summary>
        internal static string PickImage(string title = "Choose the company logo")
        {
            System.Windows.Forms.OpenFileDialog dialog = null;
            try
            {
                dialog = new System.Windows.Forms.OpenFileDialog();
                dialog.Title = title;
                dialog.Filter = "Images (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg|All files (*.*)|*.*";
                dialog.Multiselect = false;
                if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                    return dialog.FileName ?? "";
            }
            catch (Exception)
            {
            }
            finally
            {
                if (dialog != null)
                {
                    try
                    {
                        dialog.Dispose();
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            return "";
        }

        /// <summary>Show the setup window. True when it saved.</summary>
        public static bool Run(Autodesk.Revit.DB.Document doc, PsConfig.Settings settings, string themeName = "dark", Window owner = null,
            bool firstRun = true, IEnumerable<(string Name, string Group)> catalogue = null, string focus = null)
        {
            try
            {
                return new SetupWindow(doc, settings, themeName, owner, firstRun, catalogue, focus).Show();
            }
            catch (Exception)
            {
                return false;
            }
        }
    }
}
