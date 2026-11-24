using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using AW = Autodesk.Windows;

namespace RevoBIM.UI.Ribbon
{
    /// <summary>
    /// Three RevoBIM panels on Revit's Modify tab, each shown only for the selection it is for:
    ///
    /// - "RevoBIM" (Pro Sheets Exporter, Revision Manager): while a sheet or a view is selected -
    ///   in the Project Browser, a view placed on a sheet (a viewport counts as its view), or the
    ///   sheet's title block picked in the sheet view (that is how a sheet is selected on screen).
    /// - "Revisions" (Revision Manager alone): while a revision cloud is selected. Not shown beside
    ///   the "RevoBIM" panel, which already has the button.
    /// - "Nudge" (Nudge Up, Nudge Down): while model elements are selected.
    ///
    /// With nothing selected, or anything else, all are hidden.
    ///
    /// Revit's API can only add panels to an add-in's own tab, so the panels are built on the
    /// RevoBIM tab with the normal API (App.cs builds "RevoBIM" and "Nudge"; Install builds
    /// "Revisions") and then moved across with AdWindows, the ribbon library Revit itself is
    /// built on. The buttons keep their command bindings through the move.
    ///
    /// Why this is more than flipping IsVisible on each selection: Revit rebuilds parts of the
    /// Modify tab as the selection changes (it becomes "Modify | Walls" and so on) and can put a
    /// panel back on show behind our back. So the wanted state is remembered and put back
    /// whenever a panel, the tab or the active tab changes, and again a moment after each
    /// selection change. The selection itself is read from SelectionChanged and, as a backup for
    /// a change that raises no event, from Idling.
    ///
    /// Nothing here may throw into Revit's startup. What it saw and did goes to
    /// %APPDATA%\RevoBIM\logs\modify_tab_panel.txt (rewritten each session) so one pasted log
    /// settles any "it showed when it should not have".
    /// </summary>
    public static class ModifyTabPanel
    {
        public const string PanelName = "RevoBIM";
        /// <summary>The "Nudge" panel (Nudge Up, Nudge Down) moved to the Modify tab alongside it.</summary>
        public const string NudgePanelName = "Nudge";
        /// <summary>The "Revisions" panel (Revision Manager alone) shown for a selected revision cloud.</summary>
        public const string CloudPanelName = "Revisions";
        private const string ModifyTabId = "Modify";

        private static string ownTab;
        private static Dispatcher ui;
        private static AW.RibbonTab modify;
        private static AW.RibbonPanel sheetPanel;
        private static AW.RibbonPanel nudgePanel;
        private static AW.RibbonPanel cloudPanel;

        // What the current selection says each panel should do.
        private static bool wantSheet;
        private static bool wantNudge;
        private static bool wantCloud;
        private static string seenToken = "";
        private static bool applying;
        private static int settleLeft;
        private static DispatcherTimer settle;
        private static readonly Stopwatch idleClock = Stopwatch.StartNew();
        private static long idleLast;

        // The log is for diagnosis, not a trace of every click: the tab dumps are capped, "fix" lines
        // are limited per selection, and the file stops growing past 256 KB.
        private static int dumps;
        private const int MaxDumps = 10;
        private static int fixLogged;
        private static string lastKind = "";
        private const long MaxLogBytes = 262144;

        /// <summary>Move the panels now if the ribbon is ready, else once Revit has started. Never throws.</summary>
        public static void Install(UIControlledApplication app, string tabName)
        {
            ownTab = tabName;
            try
            {
                ui = Dispatcher.CurrentDispatcher;
                LogReset("RevoBIM Modify tab panels - " + BuildInfo());
                CreateCloudPanel(app, tabName);
                if (!Move())
                {
                    app.ControlledApplication.ApplicationInitialized += (sender, args) =>
                    {
                        if (sheetPanel == null)
                            Move();
                    };
                }
                app.SelectionChanged += OnSelectionChanged;
                app.Idling += OnIdling;
            }
            catch (Exception err)
            {
                Log("install failed: " + err);
            }
        }

        // ======================================================================
        // the Revisions panel
        // ======================================================================

        /// <summary>
        /// Build the "Revisions" panel (Revision Manager alone) on the RevoBIM tab, to be moved to the
        /// Modify tab with the others. A failure here only loses this panel.
        /// </summary>
        private static void CreateCloudPanel(UIControlledApplication app, string tabName)
        {
            try
            {
                RibbonPanel panel = app.CreateRibbonPanel(tabName, CloudPanelName);
                panel.AddItem(new PushButtonData(
                    "RevoBIM_RevisionManager_Cloud", "Revision\nManager", Assembly.GetExecutingAssembly().Location,
                    typeof(Commands.RevisionManagerCommand).FullName)
                {
                    ToolTip = "RevoBIM Revision Manager. Add, edit, reorder, merge and delete the project's revisions, " +
                              "with how many sheets use each one.\n\nOpens modeless, and picking a revision cloud in a " +
                              "view takes the list to its revision. Nothing is written until Apply.",
                    AvailabilityClassName = typeof(Commands.ProjectDocumentAvailability).FullName,
                    LargeImage = Icon("RevisionManager", 32),
                    Image = Icon("RevisionManager", 16),
                });
            }
            catch (Exception err)
            {
                Log("could not build the Revisions panel: " + err.Message);
            }
        }

        /// <summary>A tool's embedded ribbon icon (Resources\&lt;tool&gt;\icon.png), or null if it cannot be read.</summary>
        private static System.Windows.Media.Imaging.BitmapImage Icon(string tool, int size)
        {
            try
            {
                using (Stream stream = Assembly.GetExecutingAssembly()
                                               .GetManifestResourceStream("RevoBIM.Resources." + tool + ".icon.png"))
                {
                    if (stream == null) return null;
                    var image = new System.Windows.Media.Imaging.BitmapImage();
                    image.BeginInit();
                    image.StreamSource = stream;
                    image.DecodePixelWidth = size;
                    image.DecodePixelHeight = size;
                    image.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad;
                    image.EndInit();
                    image.Freeze();
                    return image;
                }
            }
            catch (Exception)
            {
                return null;
            }
        }

        // ======================================================================
        // moving the panels across
        // ======================================================================

        private static bool Move()
        {
            try
            {
                AW.RibbonControl ribbon = AW.ComponentManager.Ribbon;
                if (ribbon == null)
                    return false;
                AW.RibbonTab own = ribbon.Tabs.FirstOrDefault(tab => tab.Id == ownTab);
                AW.RibbonTab found = ribbon.Tabs.FirstOrDefault(tab => tab.Id == ModifyTabId);
                if (own == null || found == null)
                    return false;
                AW.RibbonPanel sheet = own.Panels.FirstOrDefault(p => p.Source != null && p.Source.Title == PanelName);
                if (sheet == null)
                    return false;
                AW.RibbonPanel nudge = own.Panels.FirstOrDefault(p => p.Source != null && p.Source.Title == NudgePanelName);

                own.Panels.Remove(sheet);
                found.Panels.Add(sheet);
                sheet.IsVisible = false;
                sheetPanel = sheet;
                modify = found;

                // A failure with the Nudge panel must not stop the sheet/view panel working.
                try
                {
                    if (nudge != null)
                    {
                        own.Panels.Remove(nudge);
                        found.Panels.Add(nudge);
                        nudge.IsVisible = false;
                        nudgePanel = nudge;
                    }
                }
                catch (Exception err)
                {
                    Log("could not move the Nudge panel to the Modify tab: " + err);
                }

                // Likewise the Revisions panel.
                try
                {
                    AW.RibbonPanel cloud = own.Panels.FirstOrDefault(p => p.Source != null && p.Source.Title == CloudPanelName);
                    if (cloud != null)
                    {
                        own.Panels.Remove(cloud);
                        found.Panels.Add(cloud);
                        cloud.IsVisible = false;
                        cloudPanel = cloud;
                    }
                }
                catch (Exception err)
                {
                    Log("could not move the Revisions panel to the Modify tab: " + err);
                }

                Watch(ribbon);
                Log("moved to the Modify tab, all hidden until a selection asks for them: RevoBIM panel" +
                    (nudgePanel != null ? ", Nudge panel" : " (Nudge panel not found)") +
                    (cloudPanel != null ? ", Revisions panel" : " (Revisions panel not found)"));
                DumpTabs("after the move");
                return true;
            }
            catch (Exception err)
            {
                Log("could not move the panels to the Modify tab: " + err);
                return false;
            }
        }

        /// <summary>Put the wanted state back whenever Revit touches the panels, the Modify tab or the active tab.</summary>
        private static void Watch(AW.RibbonControl ribbon)
        {
            try
            {
                foreach (AW.RibbonPanel panel in Panels())
                {
                    AW.RibbonPanel p = panel;
                    p.PropertyChanged += (sender, args) =>
                    {
                        if (!applying && args.PropertyName == "IsVisible" && p.IsVisible != Wanted(p))
                        {
                            // Revit does this several times per selection: the first few are enough for the log.
                            if (fixLogged++ < 2)
                                Log("fix: Revit set the " + NameOf(p) + " panel to " + (p.IsVisible ? "shown" : "hidden") +
                                    ", the selection wants it " + (Wanted(p) ? "shown" : "hidden") + " - put back");
                            Settle();
                        }
                    };
                }
                modify.PropertyChanged += (sender, args) => { if (!applying) Settle(); };
                ribbon.PropertyChanged += (sender, args) =>
                {
                    if (!applying && args.PropertyName == "ActiveTab")
                        Settle();
                };
            }
            catch (Exception err)
            {
                Log("could not watch the ribbon: " + err.Message);
            }
        }

        // ======================================================================
        // reading the selection
        // ======================================================================

        private static void OnSelectionChanged(object sender, SelectionChangedEventArgs args)
        {
            if (sheetPanel == null)
                return;
            try
            {
                Decide(args.GetDocument(), args.GetSelectedElements(), "selection");
            }
            catch (Exception err)
            {
                Log("selection: could not read it: " + err.Message);
                wantSheet = false;
                wantNudge = false;
                wantCloud = false;
                Settle();
            }
        }

        /// <summary>
        /// Backup for a selection change that raises no SelectionChanged. Runs on Revit's idle,
        /// at most four times a second, and only does work when the selection is not what was
        /// last seen.
        /// </summary>
        private static void OnIdling(object sender, Autodesk.Revit.UI.Events.IdlingEventArgs args)
        {
            if (sheetPanel == null)
                return;
            long now = idleClock.ElapsedMilliseconds;
            if (now - idleLast < 250)
                return;
            idleLast = now;
            try
            {
                UIDocument uidoc = (sender as UIApplication)?.ActiveUIDocument;
                if (uidoc == null)
                {
                    if (seenToken != "none")
                        Decide(null, new List<ElementId>(), "idle: no document");
                    return;
                }
                ICollection<ElementId> ids = uidoc.Selection.GetElementIds();
                if (Token(uidoc.Document, ids) != seenToken)
                    Decide(uidoc.Document, ids, "idle");
            }
            catch (Exception)
            {
                // Idling must never throw into Revit; the next selection event sets things right.
            }
        }

        private static string Token(Document doc, ICollection<ElementId> ids)
        {
            long sum = 0;
            foreach (ElementId id in ids.Take(2000))
                sum = unchecked(sum * 31 + id.Value);
            return (doc == null ? "none" : doc.Title) + "|" + ids.Count + "|" + sum;
        }

        /// <summary>
        /// Sort the selection: a sheet or view (Project Browser, or a viewport on a sheet) wants the
        /// RevoBIM panel; a revision cloud wants the Revisions panel (unless the RevoBIM panel, which has
        /// the same button, is already showing); a model element wants the Nudge panel; anything else
        /// wants none.
        /// </summary>
        private static void Decide(Document doc, ICollection<ElementId> ids, string source)
        {
            int sheets = 0, views = 0, viewports = 0, clouds = 0, models = 0, other = 0;
            var otherKinds = new List<string>();
            if (doc != null && ids != null)
            {
                foreach (ElementId id in ids.Take(500))
                {
                    Element element = doc.GetElement(id);
                    if (element == null) continue;
                    // A sheet, or its title block picked in the sheet view, counts as a sheet.
                    if (element is ViewSheet || IsSheetItem(element)) sheets++;
                    else if (element is Viewport) viewports++;
                    else if (element is RevisionCloud) clouds++;
                    else if (element is View view) { if (!view.IsTemplate) views++; else other++; }
                    else if (element.Category != null && element.Category.CategoryType == CategoryType.Model) models++;
                    else
                    {
                        other++;
                        // What it was, so a selection that should have counted can be seen in the log.
                        if (otherKinds.Count < 3)
                            otherKinds.Add(element.GetType().Name + " / " + (element.Category?.Name ?? "no category"));
                    }
                }
            }
            seenToken = Token(doc, ids ?? new List<ElementId>());

            // The sheet and view tools are for projects: not offered in the family editor.
            bool project = doc != null && !doc.IsFamilyDocument;
            bool wantedSheet = project && (sheets + views + viewports) > 0;
            bool wantedCloud = project && clouds > 0 && !wantedSheet;
            bool wantedNudge = models > 0;
            bool changed = wantedSheet != wantSheet || wantedNudge != wantNudge || wantedCloud != wantCloud;
            wantSheet = wantedSheet;
            wantNudge = wantedNudge;
            wantCloud = wantedCloud;

            // One line per different kind of selection, not per click.
            string kind = sheets + "/" + views + "/" + viewports + "/" + clouds + "/" + models + "/" + other + "/" +
                          string.Join(",", otherKinds);
            if (changed || kind != lastKind)
            {
                lastKind = kind;
                fixLogged = 0;
                Log(string.Format("{0}: sheets={1} views={2} viewports={3} revision clouds={4} model={5} other={6}{7} -> RevoBIM panel {8}, Revisions panel {9}, Nudge panel {10}{11}",
                    source, sheets, views, viewports, clouds, models, other,
                    otherKinds.Count > 0 ? " [" + string.Join("; ", otherKinds) + "]" : "",
                    wantSheet ? "SHOWN" : "hidden", wantCloud ? "SHOWN" : "hidden", wantNudge ? "SHOWN" : "hidden",
                    doc == null ? "" : "  doc=" + doc.Title));
                if (changed && (wantSheet || wantNudge || wantCloud))
                    DumpTabs("when a panel is wanted");
            }
            Settle();
        }

        // ======================================================================
        // putting the wanted state on the ribbon
        // ======================================================================

        /// <summary>
        /// True for what stands for "the sheet" when it is picked in the drawing area: anything in the
        /// Sheets category, and the sheet's title block - the frame family you click to select the sheet
        /// itself in a sheet view.
        /// </summary>
        private static bool IsSheetItem(Element element)
        {
            try
            {
                if (element.Category == null)
                    return false;
                BuiltInCategory category = element.Category.BuiltInCategory;
                return category == BuiltInCategory.OST_Sheets || category == BuiltInCategory.OST_TitleBlocks;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>The panels that were found and moved to the Modify tab.</summary>
        private static IEnumerable<AW.RibbonPanel> Panels()
        {
            return new[] { sheetPanel, nudgePanel, cloudPanel }.Where(panel => panel != null);
        }

        private static bool Wanted(AW.RibbonPanel panel)
        {
            if (ReferenceEquals(panel, sheetPanel)) return wantSheet;
            if (ReferenceEquals(panel, cloudPanel)) return wantCloud;
            return wantNudge;
        }

        private static string NameOf(AW.RibbonPanel panel)
        {
            if (ReferenceEquals(panel, sheetPanel)) return PanelName;
            if (ReferenceEquals(panel, cloudPanel)) return CloudPanelName;
            return NudgePanelName;
        }

        /// <summary>Apply now, and again a moment later: Revit finishes changing the tab after the event.</summary>
        private static void Settle()
        {
            Apply();
            try
            {
                settleLeft = 3;
                if (settle == null)
                {
                    settle = new DispatcherTimer(DispatcherPriority.ApplicationIdle, ui ?? Dispatcher.CurrentDispatcher)
                    {
                        Interval = TimeSpan.FromMilliseconds(150),
                    };
                    settle.Tick += (sender, args) =>
                    {
                        Apply();
                        if (--settleLeft <= 0)
                            settle.Stop();
                    };
                }
                if (!settle.IsEnabled)
                    settle.Start();
            }
            catch (Exception)
            {
            }
        }

        private static void Apply()
        {
            if (applying)
                return;
            applying = true;
            try
            {
                foreach (AW.RibbonPanel panel in Panels())
                {
                    if (panel.IsVisible != Wanted(panel))
                        panel.IsVisible = Wanted(panel);
                }
            }
            catch (Exception err)
            {
                Log("could not set a panel: " + err.Message);
            }
            finally
            {
                applying = false;
            }
        }

        // ======================================================================
        // the log
        // ======================================================================

        /// <summary>Which build this is: add-in version, build date, and the DLL it was loaded from.</summary>
        private static string BuildInfo()
        {
            try
            {
                string path = Assembly.GetExecutingAssembly().Location;
                return "add-in " + Commands.AboutCommand.Version + ", built " + Commands.AboutCommand.ReleaseDate +
                       ", " + path + " (" + File.GetLastWriteTime(path).ToString("yyyy-MM-dd HH:mm:ss") + ")";
            }
            catch (Exception)
            {
                return "add-in " + Commands.AboutCommand.Version;
            }
        }

        /// <summary>Every ribbon tab with the flags that decide where a panel can show, and which hold our panels.</summary>
        private static void DumpTabs(string why)
        {
            if (dumps >= MaxDumps)
                return;
            dumps++;
            try
            {
                AW.RibbonControl ribbon = AW.ComponentManager.Ribbon;
                if (ribbon == null) return;
                var text = new StringBuilder("tabs (" + why + "), active=" + (ribbon.ActiveTab?.Id ?? "?") + ":");
                foreach (AW.RibbonTab tab in ribbon.Tabs)
                {
                    bool ours = Panels().Any(panel => tab.Panels.Contains(panel));
                    if (!tab.IsVisible && !tab.IsContextualTab && !ours) continue; // the hidden ordinary tabs are noise
                    text.Append("\n    ").Append(tab.Id).Append(" \"").Append(tab.Title).Append("\" contextual=").Append(tab.IsContextualTab)
                        .Append(" merged=").Append(tab.IsMergedContextualTab).Append(" visible=").Append(tab.IsVisible)
                        .Append(" active=").Append(tab.IsActive).Append(" panels=").Append(tab.Panels.Count)
                        .Append(ours ? "  <- holds RevoBIM panels (" +
                                       string.Join(", ", Panels().Select(panel => NameOf(panel) + " visible=" + panel.IsVisible)) + ")" : "");
                }
                Log(text.ToString());
            }
            catch (Exception err)
            {
                Log("tabs: could not list them: " + err.Message);
            }
        }

        private static string LogPath()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                                "RevoBIM", "logs", "modify_tab_panel.txt");
        }

        private static void LogReset(string first)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(LogPath()));
                File.WriteAllText(LogPath(), first + "\n", new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }

        private static void Log(string text)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(LogPath()));
                var info = new FileInfo(LogPath());
                if (info.Exists && info.Length > MaxLogBytes)
                    return;
                File.AppendAllText(LogPath(), DateTime.Now.ToString("HH:mm:ss") + "  " + text + "\n",
                                   new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }
}
