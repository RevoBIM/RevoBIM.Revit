using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.Wires;
using RevoBIM.UI.Wires;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Shared runner of the six Wires buttons (the pyRevit pulldown's script.py files). A failure says so in a dialog and writes the text to
    /// %APPDATA%\RevoBIM\wires_last_error.txt; nothing is left half done because every change is in a transaction.
    /// </summary>
    internal static class WiresRun
    {
        public static Result Go(ExternalCommandData data, string name, Action<UIApplication, Document> body)
        {
            try
            {
                UIApplication uiapp = data.Application;
                UIDocument uidoc = uiapp.ActiveUIDocument;
                if (uidoc == null || uidoc.Document == null)
                {
                    Say(name, "No document is open.");
                    return Result.Cancelled;
                }
                body(uiapp, uidoc.Document);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                string text = "The tool stopped with an error and nothing was left half done.\n\n" + err;
                try
                {
                    Directory.CreateDirectory(WiresSettings.SettingsDir());
                    File.WriteAllText(WiresSettings.ErrorPath(), name + "\n\n" + text + "\n\n" + WiresSettings.BuildInfo(), new UTF8Encoding(false));
                }
                catch (Exception)
                {
                }
                Say(name, text);
                return Result.Failed;
            }
        }

        public static void Say(string title, string message)
        {
            try
            {
                new TaskDialog(title) { MainContent = message.Length > 1800 ? message.Substring(0, 1800) : message }.Show();
            }
            catch (Exception)
            {
            }
        }
    }

    /// <summary>Auto Wire: select fittings and only their circuits are wired; select nothing and every circuit in the view that has no wires yet is wired. Shuffle and Previous step through the route options.</summary>
    [Transaction(TransactionMode.Manual)]
    public class AutoWireCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return WiresRun.Go(data, "RevoBIM Auto Wire", (uiapp, doc) =>
            {
                var settings = WiresSettings.Load();
                Report report;
                using (new DialogSuppressor(uiapp))
                    report = CircuitRuns.RunWireCircuits(uiapp, settings, (session, headline) => WiresShuffleWindow.Show(session, headline, "Auto Wire", uiapp));
                if (report != null && !report.Deferred) WiresResultsWindow.Show(report, settings, uiapp);
            });
        }
    }

    /// <summary>Re-Route Wires: takes one circuit's wires and tags out and redraws them to the same rules.</summary>
    [Transaction(TransactionMode.Manual)]
    public class ReRouteWiresCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return WiresRun.Go(data, "RevoBIM Re-Route Wires", (uiapp, doc) =>
            {
                var settings = WiresSettings.Load();
                Report report;
                using (new DialogSuppressor(uiapp))
                    report = CircuitRuns.RunRejig(uiapp, settings, (session, headline) => WiresShuffleWindow.Show(session, headline, "Re-Route Wires", uiapp));
                if (report != null && !report.Deferred) WiresResultsWindow.Show(report, settings, uiapp);
            });
        }
    }

    /// <summary>Apply Wire Types: sets the wire type on existing wires and changes nothing else.</summary>
    [Transaction(TransactionMode.Manual)]
    public class ApplyWireTypesCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return WiresRun.Go(data, "RevoBIM Apply Wire Types", (uiapp, doc) =>
            {
                var settings = WiresSettings.Load();
                Report report;
                using (new DialogSuppressor(uiapp))
                    report = CircuitRuns.RunApplyTypes(uiapp, settings, (m, d) => WiresConfirmWindow.Ask(m, d, "Apply Wire Types", "Apply to the view", uiapp));
                if (report != null) WiresResultsWindow.Show(report, settings, uiapp);
            });
        }
    }

    /// <summary>Align Wire Ends: moves the point where a wire meets its fitting onto where it belongs and changes nothing else.</summary>
    [Transaction(TransactionMode.Manual)]
    public class AlignWireEndsCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return WiresRun.Go(data, "RevoBIM Align Wire Ends", (uiapp, doc) =>
            {
                var settings = WiresSettings.Load();
                Report report;
                using (new DialogSuppressor(uiapp))
                    report = CircuitRuns.RunAlignEnds(uiapp, settings, (m, d) => WiresConfirmWindow.Ask(m, d, "Align Wire Ends", "Align the view", uiapp));
                if (report != null) WiresResultsWindow.Show(report, settings, uiapp);
            });
        }
    }

    /// <summary>Reconnect Wires: joins loose wire ends back onto the circuited fittings beside them. With "Keep asking" ticked it asks again until Escape.</summary>
    [Transaction(TransactionMode.Manual)]
    public class ReconnectWiresCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return WiresRun.Go(data, "RevoBIM Reconnect Wires", (uiapp, doc) =>
            {
                var settings = WiresSettings.Load();
                bool keepRunning = WiresSettings.Bool(settings, "keep_running");
                using (new DialogSuppressor(uiapp))
                {
                    while (true)
                    {
                        Report report = WiresModel.RunReconnect(uiapp, settings);
                        if (report == null) return;   // Escape
                        WiresResultsWindow.Show(report, settings, uiapp);
                        if (!keepRunning) return;
                    }
                }
            });
        }
    }

    /// <summary>Settings for the Wires tools: tabbed Circuits, Lighting, Power, Reconnect and Running.</summary>
    [Transaction(TransactionMode.Manual)]
    public class WiresSettingsCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            try
            {
                new WiresSettingsWindow(data.Application).Show();
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                WiresRun.Say("RevoBIM Wires Settings", err.ToString());
                return Result.Failed;
            }
        }
    }
}
