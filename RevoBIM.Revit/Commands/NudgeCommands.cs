using System;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Tools.Nudge;
using RevoBIM.UI.Nudge;

namespace RevoBIM.Commands
{
    /// <summary>
    /// Nudge Up / Nudge Down: raise or lower elements by the Nudge increment. With a selection they all move
    /// once per press (the selection is kept); with nothing selected every element clicked moves until Escape.
    /// Finishes silently. Port of the pyRevit tools; the logic is in Tools\Nudge\NudgeEngine.cs.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class NudgeUpCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return NudgeRunner.Run(data, up: true, ref message);
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class NudgeDownCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            return NudgeRunner.Run(data, up: false, ref message);
        }
    }

    internal static class NudgeRunner
    {
        public static Result Run(ExternalCommandData data, bool up, ref string message)
        {
            try
            {
                UIDocument uidoc = data.Application.ActiveUIDocument;
                if (uidoc == null) return Result.Cancelled;
                NudgeEngine.Run(uidoc, up);
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                message = err.Message;
                return Result.Failed;
            }
        }
    }

    /// <summary>Nudge Settings: the increment, rounding, behaviour and keyboard shortcuts for both buttons.</summary>
    [Transaction(TransactionMode.Manual)]
    public class NudgeSettingsCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            try
            {
                var window = new NudgeSettingsWindow(data.Application.Application.VersionName);
                try
                {
                    new System.Windows.Interop.WindowInteropHelper(window).Owner = data.Application.MainWindowHandle;
                }
                catch (Exception)
                {
                }
                window.ShowDialog();
                return Result.Succeeded;
            }
            catch (Exception err)
            {
                message = err.Message;
                return Result.Failed;
            }
        }
    }
}
