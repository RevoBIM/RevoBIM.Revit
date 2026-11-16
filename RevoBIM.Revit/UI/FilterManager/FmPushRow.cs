using System.Collections.Generic;
using System.Windows.Controls;
using Autodesk.Revit.DB;
using Grid = System.Windows.Controls.Grid;

namespace RevoBIM.UI.FilterManager
{
    /// <summary>
    /// One row of the pusher's "Filters to push" table (the python dict {"name", "id", "item", "grid", "pick", "cells"}).
    /// </summary>
    public class FmPushRow
    {
        public string Name;
        public ElementId Id;
        public ListBoxItem Item;
        public Grid Grid;
        public CheckBox Pick;
        /// <summary>One tick per push group (FmOverrides.PushGroups key).</summary>
        public Dictionary<string, CheckBox> Cells = new Dictionary<string, CheckBox>();
    }
}
