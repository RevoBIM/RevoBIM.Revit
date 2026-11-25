using System;
using System.Collections.Generic;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Helpers
{
    /// <summary>
    /// The few Revit 2024 API members the tools use that Revit 2023 does not have, behind one place.
    /// Used by every version, so the tools do not need an #if at each call site.
    /// </summary>
    public static class RevitCompat
    {
        /// <summary>An ElementId from a long. Revit 2023 ids are 32-bit; a value outside that range gives InvalidElementId.</summary>
        public static ElementId Id(long value)
        {
#if REVIT2023
            if (value > int.MaxValue || value < int.MinValue) return ElementId.InvalidElementId;
            return new ElementId((int)value);
#else
            return new ElementId(value);
#endif
        }

        /// <summary>The canvas (drawing area) theme. Revit 2023 has only the UI theme, which is used instead.</summary>
        public static UITheme CanvasTheme()
        {
#if REVIT2023
            return UIThemeManager.CurrentTheme;
#else
            return UIThemeManager.CurrentCanvasTheme;
#endif
        }
    }
}

#if REVIT2023
/// <summary>
/// Revit 2023 stand-ins for 2024 members, as extension members (C# 14) in the global namespace so the
/// existing call sites compile unchanged: ElementId.Value, and Document.GetUnusedElements.
/// </summary>
public static class Revit2023Extensions
{
    extension(Autodesk.Revit.DB.ElementId id)
    {
        /// <summary>ElementId.Value (long) arrived in 2024; in 2023 it is IntegerValue.</summary>
        public long Value => id.IntegerValue;
    }

    /// <summary>
    /// Revit 2023 has no Document.GetUnusedElements, so nothing can be reported as unused there:
    /// the purge scan of Model Cleanup finds nothing on Revit 2023.
    /// </summary>
    public static ICollection<Autodesk.Revit.DB.ElementId> GetUnusedElements(
        this Autodesk.Revit.DB.Document doc, ISet<Autodesk.Revit.DB.ElementId> categories)
    {
        return new List<Autodesk.Revit.DB.ElementId>();
    }
}
#endif
