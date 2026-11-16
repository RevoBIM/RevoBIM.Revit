using System.Collections.Generic;
using System.Windows.Controls;
using Autodesk.Revit.DB;
using RevoBIM.Tools.FilterManager;

using Grid = System.Windows.Controls.Grid;

namespace RevoBIM.UI.FilterManager
{
    /// <summary>
    /// One filter in the Table tab: a block of rows (its name, its categories stacked, one row per rule). Created
    /// without reading the filter's rules (Hydrated = false); the rules are read when it is first shown, exported,
    /// imported into or applied. Owned by the Table region (FmWindow.Table*.cs); extend it freely.
    /// </summary>
    public class FmBlock
    {
        public ParameterFilterElement Pfe;
        public string Name;
        public string Match = "AND";
        public List<ElementId> Cats = new List<ElementId>();
        public List<FmRule> Rules = new List<FmRule>();
        public ParameterProbe Probe;
        public bool Dirty;
        public HashSet<string> Changes = new HashSet<string>();
        /// <summary>Searchable text per column (name, uses, categories, parameter, operator, value); null until worked out.</summary>
        public Dictionary<string, string> Search;
        public Grid Grid;
        public bool Hydrated;
        public Border Host;
    }
}
