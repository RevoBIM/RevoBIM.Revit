using System;
using System.Collections.Generic;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.BulkRename;

namespace RevoBIM.UI.BulkRename
{
    /// <summary>
    /// Reads what is selected in the Project Browser and opens the window, or says what to select first.
    /// Port of brn_app.py.
    /// </summary>
    public static class BrnMain
    {
        private const string Nothing = "Select the views, sheets, schedules or families you want to rename " +
                                       "in the Project Browser first, then run Bulk Rename.";

        public static Result Run(UIApplication uiapp)
        {
            string stage = "reading the settings";
            try
            {
                Dictionary<string, string> settings = BrnCore.LoadSettings();
                string debug;
                var log = new BrnLog(!settings.TryGetValue("debug", out debug) || debug == "1");
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc == null)
                {
                    stage = "telling you to open a model";
                    BrnDialogs.Tell(uiapp, settings, log, "Open a model first.");
                    return Result.Cancelled;
                }
                stage = "reading the selection";
                Document doc = uidoc.Document;
                int leftOut;
                List<Row> rows = BrnRevit.ReadSelection(doc, uidoc.Selection.GetElementIds(), out leftOut);
                log.Write("selected " + rows.Count + ", left out " + leftOut);
                if (rows.Count == 0)
                {
                    stage = "telling you to select something";
                    BrnDialogs.Tell(uiapp, settings, log, Nothing, "Nothing selected");
                    return Result.Cancelled;
                }
                stage = "closing the earlier window";
                BrnWindow old = BrnWindow.Current;
                if (old != null)
                {
                    try
                    {
                        old.ForceClose();
                    }
                    catch (Exception)
                    {
                    }
                    BrnWindow.Current = null;
                }
                stage = "preparing the rename";
                var runner = new BrnRunner(log);
                runner.Attach(ExternalEvent.Create(runner));
                Dictionary<string, HashSet<string>> taken = BrnRevit.ReadTaken(doc, rows);
                List<string> parameters = BrnRevit.TextParameters(doc, rows);
                stage = "opening the window";
                new BrnWindow(uiapp, settings, log, doc, rows, taken, leftOut, runner, parameters).Show();
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                BrnLog.WriteError(stage, err.ToString());
                try
                {
                    var dialog = new TaskDialog("Bulk Rename")
                    {
                        MainInstruction = "Bulk Rename stopped while " + stage + ".",
                        MainContent = "The full text is in\n" + System.IO.Path.Combine(BrnCore.DataDir(), BrnCore.ErrorName),
                        ExpandedContent = err.Message,
                    };
                    dialog.Show();
                }
                catch (Exception)
                {
                }
                return Result.Failed;
            }
        }
    }
}
