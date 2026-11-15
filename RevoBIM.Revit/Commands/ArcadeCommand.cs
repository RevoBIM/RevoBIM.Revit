using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;

namespace RevoBIM.Commands
{
    /// <summary>
    /// RevoBIM Arcade, from the Routines dropdown. Opens the arcade, which is its own program
    /// (RevoBIM.Arcade.exe): it keeps running while a tool is busy and after Revit closes. It opens the
    /// game the player starred as the default, or the game picker. Three slow clicks on the logo of any
    /// RevoBIM tool window do the same.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class ArcadeCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            // The arcade reports its own problems. Cancelled, not Failed, when it could not start: it
            // has already told the user, and Failed would put a Revit error dialog on top.
            return ArcadeLauncher.Launch() ? Result.Succeeded : Result.Cancelled;
        }
    }

    /// <summary>The arcade needs no model, so its button stays enabled with no document open.</summary>
    public class AlwaysAvailability : IExternalCommandAvailability
    {
        public bool IsCommandAvailable(UIApplication app, CategorySet selectedCategories) => true;
    }
}
