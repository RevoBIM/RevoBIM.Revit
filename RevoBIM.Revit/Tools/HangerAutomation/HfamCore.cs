using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace RevoBIM.Tools.HangerAutomation
{
    // =====================================================================================================
    // Hanger Automation - Family Hangers tab, pure logic (no Revit). Port of hfam_core.py.
    // Lengths are decimal feet unless a name ends in Mm.
    // =====================================================================================================

    // HfamCore is split into HfamCore.*.cs (see CODEMAP.md). Every static field initialiser stays in THIS file, in this
    // order: across partial files C# leaves the initialisation order undefined (FamDefaults reads FamKeys).
    public static partial class HfamCore
    {
        public const double MM = FhaCore.MM;

        // category key (BuiltInCategory name) -> label, in list order
        public static readonly List<KeyValuePair<string, string>> Categories = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("all", "All hanger categories"),
            new KeyValuePair<string, string>("OST_GenericModel", "Generic Models"),
            new KeyValuePair<string, string>("OST_MEPAncillaryFraming", "MEP Ancillary Framing"),
            new KeyValuePair<string, string>("OST_DuctAccessory", "Duct Accessories"),
        };

        public const string RodDefault = "BGL_DIM_Drop Rod Length";
        public const string FirstBarDefault = "First Bar Offset";
        public const string SupportHeightDefault = "BIM_Hanger_Support_Height";
        public const string DiameterDefault = "BIM_DIM_Diameter";

        /// <summary>The per-family keys in the order FAM_DEFAULTS lists them.</summary>
        public static readonly string[] FamKeys =
        {
            "left", "right", "rod", "axis", "clearance", "soffit", "swap",
            "first_bar", "height", "height_clear", "style", "dia", "circ_height", "circ_axis",
        };

        /// <summary>FAM_DEFAULTS as a key -> value table (use new FamConfig() for a default config object).</summary>
        public static readonly Dictionary<string, string> FamDefaults = BuildFamDefaults();

        private static Dictionary<string, string> BuildFamDefaults()
        {
            var c = new FamConfig();
            var d = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (string k in FamKeys) d[k] = c[k];
            return d;
        }

        public static readonly string[] Modes = { "hang", "floor" };
        public static readonly List<KeyValuePair<string, string>> Styles = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("rect", "Rectangular Floor Based"),
            new KeyValuePair<string, string>("circ", "Circular System Based"),
        };
        public static readonly List<KeyValuePair<string, string>> RunAxes = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("X", "X - left / right"),
            new KeyValuePair<string, string>("Y", "Y - front / back"),
        };
        public static readonly List<KeyValuePair<string, string>> Axes = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("X", "X - left / right"),
            new KeyValuePair<string, string>("Y", "Y - front / back"),
        };
        public static readonly List<KeyValuePair<string, string>> Soffits = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("level", "Base of the level above"),
            new KeyValuePair<string, string>("structure", "Underside of structure above"),
        };

        private static string F0(double v)
        {
            // Python's '{0:.0f}'.format(v)
            string s = Math.Round(v, MidpointRounding.ToEven).ToString("0", CultureInfo.InvariantCulture);
            if ((s == "0" || s == "-0") && (v < 0 || (v == 0 && 1.0 / v < 0))) s = "-0";
            else if (s == "-0") s = "0";
            return s;
        }

        private static string L(long k) { return k.ToString(CultureInfo.InvariantCulture); }

        // ================================================================ the list
        /// <summary>Every search word must appear in 'family type' (any case, any order).</summary>
        public static List<FamTypeItem> FilterTypes(IEnumerable<FamTypeItem> items, string category, string text)
        {
            var words = (text ?? "").ToLowerInvariant().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            var o = new List<FamTypeItem>();
            foreach (FamTypeItem it in items)
            {
                if (!string.IsNullOrEmpty(category) && category != "all" && it.Cat != category) continue;
                string hay = ((it.Family ?? "") + " " + (it.Type ?? "")).ToLowerInvariant();
                if (words.All(w => hay.Contains(w))) o.Add(it);
            }
            return o;
        }

        public static string ItemKey(string family, string typeName)
        {
            return family + " : " + typeName;
        }

        // ============================================================== DW/144 etc
        // DW/144 maximum support spacing for horizontal ductwork. Based on duct weight only; closer spacings may be
        // needed for rigidity or the structure. The tool uses min(your maximum, this) when the DW/144 tick is on.
        public static readonly double[][] Dw144Rect = { new[] { 1500.0, 3000.0 }, new[] { 1e9, 2500.0 } };    // longer side up to, spacing
        public static readonly double[][] Dw144Round = { new[] { 1120.0, 3000.0 }, new[] { 1e9, 2500.0 } };   // diameter up to, spacing

        // ===================================================== grouped services
        public const double BundleZMm = 50.0;       // bottoms within this of each other
        public const double BundleGapMm = 500.0;    // clear gap in plan between neighbours under this
        public const double BundleAngleDeg = 2.0;   // counts as parallel
        public static readonly List<KeyValuePair<string, string>> Centres = new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("mean", "Mean of the service centres"),
            new KeyValuePair<string, string>("edges", "Middle of the outer edges"),
        };
    }
}
