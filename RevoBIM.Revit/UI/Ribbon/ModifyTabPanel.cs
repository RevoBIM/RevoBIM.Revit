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
    /// Two RevoBIM panels on Revit's Modify tab, each shown only for the selection it is for:
    ///
    /// - "RevoBIM" (Pro Sheets Exporter, Revision Manager): while a sheet or a view is selected -
    ///   in the Project Browser, or a view placed on a sheet (a viewport counts as its view).
    /// - "Nudge" (Nudge Up, Nudge Down): while model elements are selected.
    ///
    /// With nothing selected, or anything else, both are hidden.
    ///
    /// Revit's API can only add panels to an add-in's own tab, so the panels are built on the
    /// RevoBIM tab with the normal API (App.cs) and then moved across with AdWindows, the
    /// ribbon library Revit itself is built on. The buttons keep their command bindings through
    /// the move.
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
        private const string ModifyTabId = "Modify";

        private static string ownTab;
        private static Dispatcher ui;
        private static AW.RibbonTab modify;
        private static AW.RibbonPanel sheetPanel;
        private static AW.RibbonPanel nudgePanel;

        // What the current selection says each panel should do.
        private static bool wantSheet;
        private static bool wantNudge;
        private static string seenToken = "";
        private static bool applying;
        private static int settleLeft;
        private static DispatcherTimer settle;
        private static readonly Stopwatch idleClock = Stopwatch.StartNew();
        private static long idleLast;

        // The log is for diagnosis, not a trace of every click: the tab dumps are capped.
        private static int dumps;
        private const int MaxDumps = 10;

        /// <summary>Move the panels now if the ribbon is ready, else once Revit has started. Never throws.</summary>
        public static void Install(UIControlledApplication app, string tabName)
        {
            ownTab = tabName;
            try
            {
                ui = Dispatcher.CurrentDispatcher;
                LogReset("RevoBIM Modify tab panels - " + BuildInfo());
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

                Watch(ribbon);
                Log("moved: RevoBIM panel" + (nudgePanel != null ? " and Nudge panel" : " (Nudge panel not found)") +
                    " to the Modify tab, both hidden until a selection asks for them");
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
                foreach (AW.RibbonPanel panel in new[] { sheetPanel, nudgePanel })
                {
                    if (panel == null) continue;
                    AW.RibbonPanel p = panel;
                    p.PropertyChanged += (sender, args) =>
                    {
                        if (!applying && args.PropertyName == "IsVisible" && p.IsVisible != Wanted(p))
                        {
                            Log("fix: Revit set the " + NameOf(p) + " panel to " + (p.IsVisible ? "shown" : "hidden") +
                                ", the selection wants it " + (Wanted(p) ? "shown" : "hidden"));
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
        /// RevoBIM panel; a model element wants the Nudge panel; anything else wants neither.
        /// </summary>
        private static void Decide(Document doc, ICollection<ElementId> ids, string source)
        {
            int sheets = 0, views = 0, viewports = 0, models = 0, other = 0;
            if (doc != null && ids != null)
            {
                foreach (ElementId id in ids.Take(500))
                {
                    Element element = doc.GetElement(id);
                    if (element == null) continue;
                    if (element is ViewSheet) sheets++;
                    else if (element is Viewport) viewports++;
                    else if (element is View view) { if (!view.IsTemplate) views++; else other++; }
                    else if (element.Category != null && element.Category.CategoryType == CategoryType.Model) models++;
                    else other++;
                }
            }
            seenToken = Token(doc, ids ?? new List<ElementId>());

            // The sheet and view tools are for projects: not offered in the family editor.
            bool wantedSheet = doc != null && !doc.IsFamilyDocument && (sheets + views + viewports) > 0;
            bool wantedNudge = models > 0;
            bool changed = wantedSheet != wantSheet || wantedNudge != wantNudge;
            wantSheet = wantedSheet;
            wantNudge = wantedNudge;

            if (changed)
            {
                Log(string.Format("{0}: sheets={1} views={2} viewports={3} model={4} other={5} -> RevoBIM panel {6}, Nudge panel {7}{8}",
                    source, sheets, views, viewports, models, other, wantSheet ? "SHOWN" : "hidden",
                    wantNudge ? "SHOWN" : "hidden", doc == null ? "" : "  doc=" + doc.Title));
                if (wantSheet || wantNudge)
                    DumpTabs("when a panel is wanted");
            }
            Settle();
        }

        // ======================================================================
        // putting the wanted state on the ribbon
        // ======================================================================

        private static bool Wanted(AW.RibbonPanel panel)
        {
            return ReferenceEquals(panel, sheetPanel) ? wantSheet : wantNudge;
        }

        private static string NameOf(AW.RibbonPanel panel)
        {
            return ReferenceEquals(panel, sheetPanel) ? PanelName : NudgePanelName;
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
                foreach (AW.RibbonPanel panel in new[] { sheetPanel, nudgePanel })
                {
                    if (panel != null && panel.IsVisible != Wanted(panel))
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
                    bool ours = tab.Panels.Contains(sheetPanel) || (nudgePanel != null && tab.Panels.Contains(nudgePanel));
                    if (!tab.IsVisible && !tab.IsContextualTab && !ours) continue; // the hidden ordinary tabs are noise
                    text.Append("\n    ").Append(tab.Id).Append(" \"").Append(tab.Title).Append("\" contextual=").Append(tab.IsContextualTab)
                        .Append(" merged=").Append(tab.IsMergedContextualTab).Append(" visible=").Append(tab.IsVisible)
                        .Append(" active=").Append(tab.IsActive).Append(" panels=").Append(tab.Panels.Count)
                        .Append(ours ? "  <- holds RevoBIM panels (RevoBIM visible=" + sheetPanel.IsVisible +
                                       (nudgePanel != null ? ", Nudge visible=" + nudgePanel.IsVisible : "") + ")" : "");
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
                File.AppendAllText(LogPath(), DateTime.Now.ToString("HH:mm:ss") + "  " + text + "\n",
                                   new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }
}
