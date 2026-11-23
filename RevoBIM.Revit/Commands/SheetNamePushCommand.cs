using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.SheetNamePush;
using RevoBIM.UI.SheetNamePush;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Sheet Name Push: sheet browser, editor and parameter push in one window. Tick sheets, double-click a number or name to edit it
    /// (edits are staged until Apply Edits), find/replace and prefix/suffix stage the same way, and Push splits each sheet name on "_"
    /// into the three target parameters set behind the gear. Port of the pyRevit tool (version 2.2.2); code in Tools\SheetNamePush\,
    /// windows in UI\SheetNamePush\. The main window is modal; Apply Edits and the push each run in their own transaction.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class SheetNamePushCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            string stage = "starting up";
            SnpCore.Log log = null;
            try
            {
                UIApplication uiapp = data.Application;
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc == null)
                {
                    TaskDialog.Show("RevoBIM Sheet Name Push", "Open a project first.");
                    return Result.Cancelled;
                }
                Document doc = uidoc.Document;
                log = new SnpCore.Log(uiapp.Application.VersionName + " " + uiapp.Application.VersionBuild, doc.Title);

                stage = "reading the sheets";
                List<SnpRecord> records = SnpCore.CollectSheetRecords(doc);
                if (records.Count == 0)
                {
                    TaskDialog.Show("RevoBIM Sheet Name Push", "No sheets found in this project.");
                    return Result.Cancelled;
                }
                var preselected = new HashSet<long>();
                try
                {
                    foreach (ElementId id in uidoc.Selection.GetElementIds())
                        if (doc.GetElement(id) is ViewSheet) preselected.Add(SnpCore.Key(id));
                }
                catch (Exception)
                {
                }

                stage = "showing the window";
                Dictionary<string, string> cfg = SnpCore.LoadSettings();
                log.Write("settings: " + string.Join("; ", cfg.OrderBy(k => k.Key).Select(k => k.Key + "=" + k.Value)));
                var window = new SnpMainWindow(uiapp, doc, records, preselected, cfg, log);
                window.ShowModal(null, uiapp);
                if (!window.Pushed || window.ResultSheets.Count == 0)
                {
                    log.Write("closed without a push");
                    return Result.Succeeded;
                }

                stage = "pushing the sheet names";
                string[] paramNames = { window.Cfg["param_1"], window.Cfg["param_2"], window.Cfg["param_3"] };
                string mode = window.FormatMode;
                var rows = new List<SnpPushRow>();
                using (var t = new Transaction(doc, "Push Sheet Name to Sheet Parameters"))
                {
                    t.Start();
                    try
                    {
                        foreach (ViewSheet sheet in window.ResultSheets) rows.Add(SnpCore.PushSheetName(sheet, mode, paramNames));
                        t.Commit();
                    }
                    catch (Exception)
                    {
                        try { if (t.HasStarted()) t.RollBack(); } catch (Exception) { }
                        throw;
                    }
                }
                foreach (SnpPushRow row in rows)
                    foreach (SnpPushResult r in row.Results)
                        log.Write("push: " + row.Number + " -> " + r.Parameter + " = " + (r.Value ?? "-") + " [" + r.Status + "]");

                stage = "showing the results";
                string label;
                new SnpResultsWindow(rows, SnpCore.ModeLabels.TryGetValue(mode, out label) ? label : mode, rows.Count, log).ShowModal(null, uiapp);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                if (log != null) log.Write("error at stage '" + stage + "': " + err);
                Report(stage, err.ToString());
                return Result.Failed;
            }
        }

        /// <summary>Says which stage failed, on screen and on disk.</summary>
        private static void Report(string stage, string text)
        {
            string message = "Sheet Name Push stopped while " + stage + ".\n\n" + text;
            try
            {
                Directory.CreateDirectory(SnpCore.DataDir());
                File.WriteAllText(SnpCore.ErrorPath(), message + "\n\n" + SnpCore.BuildInfo(), new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            try
            {
                TaskDialog.Show("RevoBIM Sheet Name Push", message);
            }
            catch (Exception)
            {
            }
        }
    }
}
