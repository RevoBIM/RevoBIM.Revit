// Port of ps_model.py (Pro Sheets Exporter).
//
// Reading the model: sheets, views, their parameters and their paper sizes.
//
// No WPF in here. The window asks this module for rows and parameter values and
// gets plain objects back, which keeps the read testable and keeps the grid from
// ever touching the Revit API on a background thread.
//
// Read in one pass, not per sheet. The first honest version of a tool like
// this runs a FilteredElementCollector per sheet for the title block, which
// is fine on a demo model and unusable at four hundred sheets. Title blocks and
// view scales are each one collector here, keyed by sheet id.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.ProSheets
{
    public static partial class PsModel
    {
        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        // ==================================================================
        // small helpers that have caught this extension out before
        // ==================================================================

        /// <summary>
        /// The integer behind an ElementId (ElementId.Value, Int64, Revit 2024+).
        /// null gives 0, as the Python does.
        /// </summary>
        public static long EidValue(ElementId elementId)
        {
            if (elementId == null)
                return 0;
            try
            {
                return elementId.Value;
            }
            catch (Exception)
            {
                return 0;
            }
        }

        /// <summary>
        /// An ElementId from a number. Always the Int64 constructor: from Revit 2026
        /// an int literal is ambiguous between the BuiltInCategory, BuiltInParameter
        /// and Int64 overloads.
        /// </summary>
        public static ElementId MakeId(long value)
        {
            return new ElementId(value);
        }

        /// <summary>
        /// Python u'{0}'.format(value): null gives "", bools give True/False, floats
        /// give Python's str(float) form ("297.0"), enums their member name,
        /// ElementIds their number, everything else invariant-culture text.
        /// </summary>
        public static string ToText(object value)
        {
            if (value == null)
                return "";
            try
            {
                switch (value)
                {
                    case string text:
                        return text;
                    case bool flag:
                        return flag ? "True" : "False";
                    case double number:
                        return PyFloat(number);
                    case float single:
                        return PyFloat(single);
                    case ElementId id:
                        return id.Value.ToString(Inv);
                    case Enum member:
                        return member.ToString();
                    case IFormattable formattable:
                        return formattable.ToString(null, Inv);
                    default:
                        return value.ToString() ?? "";
                }
            }
            catch (Exception)
            {
                return "";
            }
        }

        /// <summary>Python's str(float): shortest round-trip digits, always with a ".0" or exponent.</summary>
        public static string PyFloat(double number)
        {
            if (double.IsNaN(number))
                return "nan";
            if (double.IsPositiveInfinity(number))
                return "inf";
            if (double.IsNegativeInfinity(number))
                return "-inf";
            if (number == Math.Floor(number) && Math.Abs(number) < 1e16)
                return number.ToString("0", Inv) + ".0";
            string text = number.ToString("R", Inv);
            int e = text.IndexOf('E');
            if (e >= 0)
            {
                // .NET "1E+20" / "1.5E-05" -> Python "1e+20" / "1.5e-05"
                string mantissa = text.Substring(0, e);
                string exponent = text.Substring(e + 1);
                string sign = "+";
                if (exponent.StartsWith("-", StringComparison.Ordinal) || exponent.StartsWith("+", StringComparison.Ordinal))
                {
                    sign = exponent.Substring(0, 1);
                    exponent = exponent.Substring(1);
                }
                exponent = exponent.TrimStart('0');
                if (exponent.Length < 2)
                    exponent = exponent.PadLeft(2, '0');
                return mantissa + "e" + sign + exponent;
            }
            return text;
        }

        /// <summary>Python u'{0:.0f}'.format(x): round half to even on exact ties.</summary>
        internal static string F0(double number)
        {
            return Math.Round(number, 0, MidpointRounding.ToEven).ToString("0", Inv);
        }

        /// <summary>
        /// The sort key natural_key returns, as a comparable object. Python builds a
        /// list of tuples - (0, 0, lowered text) for a text run, (1, int, '') for a
        /// digit run - and compares the lists. This class compares the same way:
        /// part by part, a text run before a digit run, text runs ordinally on the
        /// lower-cased text, digit runs by numeric value (any length, leading zeros
        /// ignored), and a key that is a prefix of another sorts first.
        /// Use as an OrderBy key: rows.OrderBy(r => PsModel.NaturalKey(r.Number)).
        /// </summary>
        public sealed class NaturalSortKey : IComparable<NaturalSortKey>, IComparable, IEquatable<NaturalSortKey>
        {
            private readonly List<(bool IsNumber, string Digits, string Text)> parts;

            internal NaturalSortKey(List<(bool IsNumber, string Digits, string Text)> parts)
            {
                this.parts = parts;
            }

            public int CompareTo(NaturalSortKey other)
            {
                if (ReferenceEquals(other, null))
                    return 1;
                int count = Math.Min(parts.Count, other.parts.Count);
                for (int i = 0; i < count; i++)
                {
                    var a = parts[i];
                    var b = other.parts[i];
                    if (a.IsNumber != b.IsNumber)
                        return a.IsNumber ? 1 : -1;
                    if (a.IsNumber)
                    {
                        if (a.Digits.Length != b.Digits.Length)
                            return a.Digits.Length < b.Digits.Length ? -1 : 1;
                        int byDigits = string.CompareOrdinal(a.Digits, b.Digits);
                        if (byDigits != 0)
                            return byDigits < 0 ? -1 : 1;
                    }
                    int byText = string.CompareOrdinal(a.Text, b.Text);
                    if (byText != 0)
                        return byText < 0 ? -1 : 1;
                }
                return parts.Count.CompareTo(other.parts.Count);
            }

            public int CompareTo(object obj)
            {
                return CompareTo(obj as NaturalSortKey);
            }

            public bool Equals(NaturalSortKey other)
            {
                return !ReferenceEquals(other, null) && CompareTo(other) == 0;
            }

            public override bool Equals(object obj)
            {
                return Equals(obj as NaturalSortKey);
            }

            public override int GetHashCode()
            {
                unchecked
                {
                    int hash = 17;
                    foreach (var part in parts)
                    {
                        hash = hash * 31 + (part.IsNumber ? 1 : 0);
                        hash = hash * 31 + part.Digits.GetHashCode();
                        hash = hash * 31 + part.Text.GetHashCode();
                    }
                    return hash;
                }
            }

            public static bool operator <(NaturalSortKey a, NaturalSortKey b) { return Comparer<NaturalSortKey>.Default.Compare(a, b) < 0; }
            public static bool operator >(NaturalSortKey a, NaturalSortKey b) { return Comparer<NaturalSortKey>.Default.Compare(a, b) > 0; }
        }

        // Python re \d without the UNICODE flag: ASCII digits only.
        private static readonly Regex DigitRun = new Regex("([0-9]+)");

        /// <summary>Sort key giving P-9 before P-10, which plain string order does not.</summary>
        public static NaturalSortKey NaturalKey(object text)
        {
            string[] split = DigitRun.Split(ToText(text));
            var key = new List<(bool IsNumber, string Digits, string Text)>();
            foreach (string part in split)
            {
                if (part.Length > 0 && part.All(ch => ch >= '0' && ch <= '9'))
                {
                    string digits = part.TrimStart('0');
                    if (digits.Length == 0)
                        digits = "0";
                    key.Add((true, digits, ""));
                }
                else
                {
                    key.Add((false, "0", part.ToLowerInvariant()));
                }
            }
            return new NaturalSortKey(key);
        }

        // ==================================================================
        // parameter reading
        // ==================================================================

        /// <summary>
        /// A parameter's value as display text, by every route that might work.
        /// GetParameters and LookupParameter do not always hand back the same
        /// object, and a shared parameter that is missing on one element is present
        /// on the next, so both are tried and neither is trusted to throw.
        /// </summary>
        public static string ParamText(Element element, string name)
        {
            if (element == null || string.IsNullOrEmpty(name))
                return "";
            Parameter param = null;
            try
            {
                IList<Parameter> found = element.GetParameters(name);
                if (found != null && found.Count > 0)
                    param = found[0];
            }
            catch (Exception)
            {
                param = null;
            }
            if (param == null)
            {
                try
                {
                    param = element.LookupParameter(name);
                }
                catch (Exception)
                {
                    param = null;
                }
            }
            if (param == null)
                return "";
            return ParamValueText(param);
        }

        /// <summary>One parameter turned into the text a file name should use.</summary>
        public static string ParamValueText(Parameter param)
        {
            if (param == null)
                return "";
            try
            {
                if (!param.HasValue)
                    return "";
            }
            catch (Exception) { }
            StorageType? storage;
            try
            {
                storage = param.StorageType;
            }
            catch (Exception)
            {
                storage = null;
            }
            try
            {
                if (storage == StorageType.String)
                    return ToText(param.AsString() ?? "");
                if (storage == StorageType.Integer)
                {
                    string shown = param.AsValueString();
                    if (!string.IsNullOrEmpty(shown))
                        return ToText(shown);
                    return ToText(param.AsInteger());
                }
                if (storage == StorageType.Double)
                {
                    string shown = param.AsValueString();
                    if (!string.IsNullOrEmpty(shown))
                        return ToText(shown);
                    return ToText(param.AsDouble());
                }
                if (storage == StorageType.ElementId)
                {
                    string shown = param.AsValueString();
                    if (!string.IsNullOrEmpty(shown))
                        return ToText(shown);
                    return ToText(EidValue(param.AsElementId()));
                }
            }
            catch (Exception) { }
            try
            {
                string text = param.AsString();
                if (string.IsNullOrEmpty(text))
                    text = param.AsValueString();
                return ToText(string.IsNullOrEmpty(text) ? "" : text);
            }
            catch (Exception)
            {
                return "";
            }
        }

        /// <summary>Every readable parameter name on an element, deduplicated.</summary>
        public static HashSet<string> ParameterNames(Element element)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            try
            {
                foreach (Parameter param in element.Parameters)
                {
                    try
                    {
                        Definition definition = param.Definition;
                        if (definition != null && !string.IsNullOrEmpty(definition.Name))
                            names.Add(ToText(definition.Name));
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }
            catch (Exception) { }
            return names;
        }

        // ==================================================================
        // paper sizes
        // ==================================================================

        // Nominal ISO sizes in millimetres, short edge first, largest first so that
        // "the smallest one that fits" can walk the list backwards.
        public static readonly List<(string Name, double Short, double Long)> IsoSizes =
            new List<(string Name, double Short, double Long)>
            {
                ("A0", 841.0, 1189.0),
                ("A1", 594.0, 841.0),
                ("A2", 420.0, 594.0),
                ("A3", 297.0, 420.0),
                ("A4", 210.0, 297.0),
                ("A5", 148.0, 210.0),
                ("A6", 105.0, 148.0),
            };

        public const double FeetToMm = 304.8;

        // How far a title block may be off nominal and still count as that size.
        // Title blocks are routinely drawn a millimetre or two under so the border
        // does not sit on the paper edge, and a few are drawn to an old imperial
        // equivalent, so this is deliberately generous.
        public const double SizeToleranceMm = 8.0;

        public const string Landscape = "landscape";
        public const string Portrait = "portrait";

        /// <summary>The ISO name for a sheet of this size, or null where nothing fits.</summary>
        public static string MatchIso(double widthMm, double heightMm, double tolerance = SizeToleranceMm)
        {
            double shortEdge = Math.Min(widthMm, heightMm);
            double longEdge = Math.Max(widthMm, heightMm);
            foreach (var size in IsoSizes)
            {
                if (Math.Abs(shortEdge - size.Short) <= tolerance && Math.Abs(longEdge - size.Long) <= tolerance)
                    return size.Name;
            }
            return null;
        }

        /// <summary>
        /// The smallest standard size this sheet fits inside.
        /// For the title blocks that are not a standard size at all - and there is
        /// usually at least one per office, a cut-down sheet for schematics - the
        /// honest answer is the smallest standard paper the drawing fits on. Sizing
        /// it down would clip the sheet, and defaulting to A0 would waste most of
        /// the page, so neither of those is a kindness.
        /// </summary>
        public static string SmallestContaining(double widthMm, double heightMm, double tolerance = SizeToleranceMm)
        {
            double shortEdge = Math.Min(widthMm, heightMm);
            double longEdge = Math.Max(widthMm, heightMm);
            if (shortEdge <= 0 || longEdge <= 0)
                return null;
            string best = null;
            foreach (var size in IsoSizes)
            {
                // The list runs largest first, so every later hit is smaller.
                if (shortEdge <= size.Short + tolerance && longEdge <= size.Long + tolerance)
                    best = size.Name;
            }
            return best;
        }

        private static readonly Regex ASize = new Regex(@"\bA([0-6])\b");

        /// <summary>An A-size read out of a family or type name, where one is spelled out.</summary>
        public static string SizeFromName(string text)
        {
            Match match = ASize.Match(ToText(text).ToUpperInvariant());
            if (match.Success)
                return "A" + match.Groups[1].Value;
            return null;
        }

        /// <summary>(short, long) in mm for an A-size name, or null.</summary>
        public static (double Short, double LongEdge)? IsoDimensions(string name)
        {
            string wanted = ToText(name).Trim().ToUpperInvariant();
            foreach (var size in IsoSizes)
            {
                if (size.Name == wanted)
                    return (size.Short, size.Long);
            }
            return null;
        }

        /// <summary>What paper a sheet wants, which way round, and how sure we are.</summary>
        public class SheetSize
        {
            public string Name { get; set; }
            public double WidthMm { get; set; }
            public double HeightMm { get; set; }
            public bool Landscape { get; set; }
            public string Source { get; set; }
            // False where the sheet is not a standard size and has been fitted
            // up to the next one. Worth telling the user about rather than
            // quietly rounding their paper.
            public bool Exact { get; set; }

            public SheetSize(string name = "", double widthMm = 0.0, double heightMm = 0.0,
                             bool landscape = true, string source = "", bool exact = true)
            {
                Name = name ?? "";
                WidthMm = widthMm;
                HeightMm = heightMm;
                Landscape = landscape;
                Source = source ?? "";
                Exact = exact;
            }

            public string Orientation()
            {
                return Landscape ? PsModel.Landscape : PsModel.Portrait;
            }

            /// <summary>What the Size column shows: "A1 landscape".</summary>
            public string Label()
            {
                if (!string.IsNullOrEmpty(Name))
                {
                    string text = string.Format("{0} {1}", Name, Orientation());
                    return Exact ? text : text + " (fitted)";
                }
                if (WidthMm != 0 && HeightMm != 0)
                    return string.Format("{0} x {1} mm", F0(WidthMm), F0(HeightMm));
                return "?";
            }

            /// <summary>A fuller line for the debug log and the report.</summary>
            public string Describe()
            {
                if (string.IsNullOrEmpty(Name))
                    return Label();
                return string.Format("{0} {1} from {2} ({3} x {4} mm{5})",
                                     Name, Orientation(), string.IsNullOrEmpty(Source) ? "?" : Source,
                                     F0(WidthMm), F0(HeightMm),
                                     Exact ? "" : ", fitted up from a non-standard sheet");
            }
        }

        /// <summary>
        /// Every parameter name on the title blocks placed on sheets - read from
        /// a few, since a family carries the same parameters wherever it sits.
        /// </summary>
        public static List<string> TitleBlockParameterNames(Document doc, int sample = 10)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            List<Element> blocks;
            try
            {
                blocks = ReadTitleBlocks(doc).Values.Take(sample).ToList();
            }
            catch (Exception)
            {
                blocks = new List<Element>();
            }
            foreach (Element block in blocks)
                names.UnionWith(ParameterNames(block));
            return names.OrderBy(one => one.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        /// <summary>
        /// Every title block instance in the model, keyed by the sheet it is on.
        /// One collector for the whole model. Where a sheet somehow carries more than
        /// one title block the largest wins, since that is the one defining the paper.
        /// </summary>
        public static Dictionary<long, Element> ReadTitleBlocks(Document doc)
        {
            var bySheet = new Dictionary<long, Element>();
            try
            {
                var collector = new FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_TitleBlocks)
                    .WhereElementIsNotElementType();
                foreach (Element block in collector)
                {
                    long owner;
                    try
                    {
                        owner = EidValue(block.OwnerViewId);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    if (owner == 0)
                        continue;
                    if (!bySheet.TryGetValue(owner, out Element existing) || existing == null)
                    {
                        bySheet[owner] = block;
                        continue;
                    }
                    try
                    {
                        if (BlockArea(block) > BlockArea(existing))
                            bySheet[owner] = block;
                    }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            return bySheet;
        }

        internal static double BlockParam(Element block, BuiltInParameter builtIn)
        {
            try
            {
                Parameter param = block.get_Parameter(builtIn);
                if (param != null && param.HasValue)
                    return param.AsDouble();
            }
            catch (Exception) { }
            return 0.0;
        }

        internal static double BlockArea(Element block)
        {
            return BlockParam(block, BuiltInParameter.SHEET_WIDTH) * BlockParam(block, BuiltInParameter.SHEET_HEIGHT);
        }

        /// <summary>
        /// Python sheet_size (renamed: a method cannot share the nested class SheetSize's name).
        /// The paper a sheet wants, worked out from its own extents.
        /// The order is deliberate. The title block's own width and height are the
        /// truth about how big the drawing is, so geometry is tried before any name:
        /// a title block called "A1" that has been stretched is an A0 print, and the
        /// name would have lied about it.
        /// 1. an explicit parameter override, where the office nominates one
        /// 2. the extents, matched against a standard size
        /// 3. the extents, fitted up to the smallest standard size that contains
        ///    them, for the cut-down sheets every office has
        /// 4. an A-size spelled out in the title block type name
        /// 5. the bare millimetres
        /// Orientation always comes from the extents, never from the name.
        /// </summary>
        public static SheetSize SheetSizeCore(Document doc, Element sheet, Element titleBlock, string overrideText = "")
        {
            double widthMm = 0.0, heightMm = 0.0;
            if (titleBlock != null)
            {
                widthMm = BlockParam(titleBlock, BuiltInParameter.SHEET_WIDTH) * FeetToMm;
                heightMm = BlockParam(titleBlock, BuiltInParameter.SHEET_HEIGHT) * FeetToMm;
            }

            bool landscape = (widthMm != 0 && heightMm != 0) ? (widthMm >= heightMm) : true;

            if (!string.IsNullOrEmpty(overrideText))
            {
                string named = SizeFromName(overrideText) ?? ToText(overrideText).Trim();
                // A nominated size still takes its orientation from the sheet, and
                // its nominal millimetres from the standard, so the driver gets a
                // sensible page even where the model has no title block.
                var dims = IsoDimensions(named);
                if (dims != null && !(widthMm != 0 && heightMm != 0))
                {
                    double shortEdge = dims.Value.Short, longEdge = dims.Value.LongEdge;
                    if (landscape)
                    {
                        widthMm = longEdge;
                        heightMm = shortEdge;
                    }
                    else
                    {
                        widthMm = shortEdge;
                        heightMm = longEdge;
                    }
                }
                return new SheetSize(named, widthMm, heightMm, landscape, "the nominated parameter", true);
            }

            if (widthMm != 0 && heightMm != 0)
            {
                string exact = MatchIso(widthMm, heightMm);
                if (!string.IsNullOrEmpty(exact))
                    return new SheetSize(exact, widthMm, heightMm, landscape, "the sheet extents", true);
                string fitted = SmallestContaining(widthMm, heightMm);
                if (!string.IsNullOrEmpty(fitted))
                    return new SheetSize(fitted, widthMm, heightMm, landscape, "the sheet extents", false);
            }

            string typeName = "";
            if (titleBlock != null)
            {
                try
                {
                    Element symbol = doc.GetElement(titleBlock.GetTypeId());
                    if (symbol != null)
                        typeName = ToText(symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString());
                }
                catch (Exception)
                {
                    typeName = "";
                }
            }
            if (string.IsNullOrEmpty(typeName) && titleBlock != null)
            {
                try
                {
                    typeName = ToText(titleBlock.Name);
                }
                catch (Exception)
                {
                    typeName = "";
                }
            }

            string fromName = SizeFromName(typeName);
            if (!string.IsNullOrEmpty(fromName))
                return new SheetSize(fromName, widthMm, heightMm, landscape, "the title block name", true);
            if (widthMm != 0 && heightMm != 0)
                return new SheetSize("", widthMm, heightMm, landscape, "the sheet extents", true);
            return new SheetSize("", 0.0, 0.0, true, "nothing to go on", true);
        }

        // ==================================================================
        // rows
        // ==================================================================

        /// <summary>One sheet or one view, as the grid and the exporter both see it.</summary>
        public class Row
        {
            public Element Element { get; set; }
            public bool IsSheet { get; set; }
            public ElementId ElementId { get; set; }
            public long Key { get; set; }
            public bool Checked { get; set; }
            public string Number { get; set; }
            public string Name { get; set; }
            public string Revision { get; set; }
            public string Size { get; set; }
            public SheetSize SizeInfo { get; set; }
            public string ViewType { get; set; }
            public string CustomName { get; set; }
            public string Folder { get; set; }
            public bool IsPlaceholder { get; set; }
            public bool OnSheetList { get; set; }
            public List<string> Sets { get; set; }

            public Row(Element element, bool isSheet)
            {
                Element = element;
                IsSheet = isSheet;
                ElementId = element.Id;
                Key = EidValue(element.Id);
                Checked = false;
                Number = "";
                Name = "";
                Revision = "";
                Size = "";
                SizeInfo = null;
                ViewType = "";
                CustomName = "";
                Folder = "";
                IsPlaceholder = false;
                OnSheetList = true;
                Sets = new List<string>();
            }

            public NaturalSortKey SortKey()
            {
                return NaturalKey(!string.IsNullOrEmpty(Number) ? Number : Name);
            }
        }

        /// <summary>Every sheet (or every printable view) in the model, as Row objects.</summary>
        public static List<Row> ReadRows(Document doc, string mode = "sheets", string sizeParam = "")
        {
            List<Row> rows;
            if (mode == "views")
                rows = ReadViews(doc);
            else
                rows = ReadSheets(doc, sizeParam);
            return rows.OrderBy(r => r.SortKey()).ToList();
        }

        internal static List<Row> ReadSheets(Document doc, string sizeParam = "")
        {
            Dictionary<long, Element> blocks = ReadTitleBlocks(doc);
            var rows = new List<Row>();
            FilteredElementCollector collector;
            try
            {
                collector = new FilteredElementCollector(doc)
                    .OfClass(typeof(ViewSheet))
                    .WhereElementIsNotElementType();
            }
            catch (Exception)
            {
                return rows;
            }
            foreach (Element element in collector)
            {
                var sheet = element as ViewSheet;
                if (sheet == null)
                    continue;
                try
                {
                    if (sheet.IsTemplate)
                        continue;
                }
                catch (Exception) { }
                var row = new Row(sheet, true);
                try { row.Number = ToText(sheet.SheetNumber); }
                catch (Exception) { row.Number = ""; }
                try { row.Name = ToText(sheet.Name); }
                catch (Exception) { row.Name = ""; }
                try { row.IsPlaceholder = sheet.IsPlaceholder; }
                catch (Exception) { row.IsPlaceholder = false; }
                try
                {
                    Parameter param = sheet.get_Parameter(BuiltInParameter.SHEET_SCHEDULED);
                    row.OnSheetList = param != null ? param.AsInteger() != 0 : true;
                }
                catch (Exception)
                {
                    row.OnSheetList = true;
                }

                row.Revision = CurrentRevisionText(doc, sheet);

                string overrideText = !string.IsNullOrEmpty(sizeParam) ? ParamText(sheet, sizeParam) : "";
                blocks.TryGetValue(row.Key, out Element block);
                SheetSize info = SheetSizeCore(doc, sheet, block, overrideText);
                row.SizeInfo = info;
                row.Size = info.Label();
                rows.Add(row);
            }
            return rows;
        }

        // View types that cannot be printed or exported on their own.
        internal static readonly HashSet<ViewType> SkipViewTypes = new HashSet<ViewType>
        {
            Autodesk.Revit.DB.ViewType.ProjectBrowser,
            Autodesk.Revit.DB.ViewType.SystemBrowser,
            Autodesk.Revit.DB.ViewType.Undefined,
            Autodesk.Revit.DB.ViewType.Internal,
            Autodesk.Revit.DB.ViewType.DrawingSheet,
            Autodesk.Revit.DB.ViewType.Schedule,
            Autodesk.Revit.DB.ViewType.ColumnSchedule,
            Autodesk.Revit.DB.ViewType.PanelSchedule,
            Autodesk.Revit.DB.ViewType.Report,
        };

        internal static List<Row> ReadViews(Document doc)
        {
            var rows = new List<Row>();
            FilteredElementCollector collector;
            try
            {
                collector = new FilteredElementCollector(doc)
                    .OfClass(typeof(View))
                    .WhereElementIsNotElementType();
            }
            catch (Exception)
            {
                return rows;
            }
            foreach (Element element in collector)
            {
                var view = element as View;
                if (view == null)
                    continue;
                try
                {
                    if (view.IsTemplate)
                        continue;
                }
                catch (Exception)
                {
                    continue;
                }
                try
                {
                    if (SkipViewTypes.Contains(view.ViewType))
                        continue;
                }
                catch (Exception) { }
                try
                {
                    if (!view.CanBePrinted)
                        continue;
                }
                catch (Exception) { }
                var row = new Row(view, false);
                try { row.Name = ToText(view.Name); }
                catch (Exception) { row.Name = ""; }
                try { row.ViewType = ToText(view.ViewType); }
                catch (Exception) { row.ViewType = ""; }
                row.Number = row.ViewType;
                row.Size = "";
                row.SizeInfo = new SheetSize();
                rows.Add(row);
            }
            return rows;
        }

        // The column a view's own type is read into - the folders Revit's Project
        // Browser always puts views in under any organisation's own folders
        // (Floor Plans, Sections...).
        public const string ViewTypeColumn = "View Type";

        // How many views are asked for their folders. An organisation groups every
        // view by the same parameters, so a handful tells you all of it.
        public const int BrowserSample = 40;

        /// <summary>
        /// The folder levels of an organisation, top first, from what a few
        /// views reported - [[level 1 name, level 2 name...], ...]. A view with
        /// no value for a level reports fewer, so each depth takes the first name
        /// any view gave it.
        /// </summary>
        public static List<string> BrowserLevels(IEnumerable<IEnumerable<string>> samples)
        {
            var levels = new List<string>();
            foreach (var names in samples ?? Enumerable.Empty<IEnumerable<string>>())
            {
                int depth = 0;
                foreach (string raw in names ?? Enumerable.Empty<string>())
                {
                    while (levels.Count <= depth)
                        levels.Add("");
                    string name = ToText(raw).Trim();
                    if (name.Length > 0 && levels[depth].Length == 0)
                        levels[depth] = name;
                    depth++;
                }
            }
            var found = new List<string>();
            foreach (string name in levels)
            {
                if (name.Length > 0 && !found.Contains(name))
                    found.Add(name);
            }
            return found;
        }

        /// <summary>
        /// The columns the Views list starts with, as Revit's Project Browser
        /// shows them: the organisation's folder parameters top first, then the
        /// view type. Each once.
        /// </summary>
        public static List<string> BrowserColumns(IEnumerable<string> levels)
        {
            var found = new List<string>();
            var all = new List<string>(levels ?? Enumerable.Empty<string>()) { ViewTypeColumn };
            foreach (string raw in all)
            {
                string name = ToText(raw).Trim();
                if (name.Length > 0 && !found.Contains(name))
                    found.Add(name);
            }
            return found;
        }

        /// <summary>
        /// A folder's grouping parameter by name: from the view's own
        /// parameters first (built-in ones have no element), then the project's
        /// parameter element.
        /// </summary>
        internal static string ParameterName(Document doc, View view, ElementId parameterId)
        {
            long wanted = EidValue(parameterId);
            try
            {
                foreach (Parameter parameter in view.Parameters)
                {
                    try
                    {
                        if (EidValue(parameter.Id) == wanted)
                            return ToText(parameter.Definition.Name);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }
            catch (Exception) { }
            try
            {
                Element element = doc.GetElement(parameterId);
                if (element != null)
                    return ToText(element.Name);
            }
            catch (Exception) { }
            return "";
        }

        /// <summary>
        /// The parameter names the project's current browser organisation for
        /// views groups by, top first - [] when it groups by nothing, or the
        /// Revit in use cannot say.
        /// </summary>
        public static List<string> BrowserFolderParameters(Document doc, IEnumerable<Row> rows)
        {
            BrowserOrganization organisation;
            try
            {
                organisation = BrowserOrganization.GetCurrentBrowserOrganizationForViews(doc);
            }
            catch (Exception)
            {
                return new List<string>();
            }
            if (organisation == null)
                return new List<string>();
            var samples = new List<List<string>>();
            foreach (Row row in (rows ?? Enumerable.Empty<Row>()).Take(BrowserSample))
            {
                var view = row?.Element as View;
                if (view == null)
                    continue;
                IList<FolderItemInfo> items;
                try
                {
                    items = organisation.GetFolderItems(view.Id);
                }
                catch (Exception)
                {
                    continue;
                }
                var names = new List<string>();
                try
                {
                    foreach (FolderItemInfo item in items)
                        names.Add(ParameterName(doc, view, item.ElementId));
                }
                catch (Exception)
                {
                    continue;
                }
                if (names.Count > 0)
                    samples.Add(names);
            }
            return BrowserLevels(samples);
        }

        /// <summary>
        /// Whether a row is a 3D view, which is what NWC and IFC need.
        /// ViewType.ThreeD covers both the default {3D} and any named
        /// perspective or isometric. A sheet is never one, whatever it holds.
        /// </summary>
        public static bool IsThreeD(Row row)
        {
            if (row == null || row.IsSheet)
                return false;
            try
            {
                if (row.Element is View view)
                    return view.ViewType == Autodesk.Revit.DB.ViewType.ThreeD;
            }
            catch (Exception) { }
            // A release that renames the member should not silently answer "no".
            return (row.ViewType ?? "").ToLowerInvariant() == "threed";
        }

        /// <summary>
        /// Every phase in the model as {name: element id text}.
        /// The name is what a template stores, because an id from another model
        /// points at whatever happens to share that number. The id is what the
        /// IFC exporter's ActivePhaseId option wants.
        /// </summary>
        public static Dictionary<string, string> ReadPhases(Document doc)
        {
            var found = new Dictionary<string, string>(StringComparer.Ordinal);
            try
            {
                foreach (Phase phase in doc.Phases)
                {
                    try
                    {
                        found[ToText(phase.Name)] = EidValue(phase.Id).ToString(Inv);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }
            catch (Exception) { }
            return found;
        }

        // ==================================================================
        // revisions
        // ==================================================================

        /// <summary>
        /// The revision number the sheet itself shows, not the project-wide one.
        /// Revision.RevisionNumber is the project-wide number, deprecated since
        /// 2022. GetRevisionNumberOnSheet reports exactly what the sheet's own
        /// revision schedule shows, which is the only answer that can agree with
        /// the drawing. Takes an Element; anything but a ViewSheet gives "".
        /// </summary>
        public static string CurrentRevisionText(Document doc, Element sheet)
        {
            var viewSheet = sheet as ViewSheet;
            ElementId current;
            try
            {
                if (viewSheet == null)
                    return "";
                current = viewSheet.GetCurrentRevision();
            }
            catch (Exception)
            {
                return "";
            }
            if (current == null || EidValue(current) <= 0)
                return "";
            try
            {
                string shown = viewSheet.GetRevisionNumberOnSheet(current);
                if (!string.IsNullOrEmpty(shown))
                    return ToText(shown);
            }
            catch (Exception) { }
            try
            {
                var revision = doc.GetElement(current) as Revision;
                if (revision != null)
                    return ToText(revision.SequenceNumber);
            }
            catch (Exception) { }
            return "";
        }

        /// <summary>
        /// Description, date or issued-by for the sheet's current revision.
        /// field is a Revision property name (RevisionDate, Description, IssuedBy,
        /// IssuedTo...), as the Python getattr took it.
        /// </summary>
        public static string CurrentRevisionField(Document doc, Element sheet, string field)
        {
            try
            {
                var viewSheet = sheet as ViewSheet;
                if (viewSheet == null)
                    return "";
                ElementId current = viewSheet.GetCurrentRevision();
                if (current == null || EidValue(current) <= 0)
                    return "";
                Element element = doc.GetElement(current);
                if (element == null)
                    return "";
                var revision = element as Revision;
                if (revision != null)
                {
                    switch (field)
                    {
                        case "RevisionDate": return ToText(revision.RevisionDate);
                        case "Description": return ToText(revision.Description);
                        case "IssuedBy": return ToText(revision.IssuedBy);
                        case "IssuedTo": return ToText(revision.IssuedTo);
                        case "SequenceNumber": return ToText(revision.SequenceNumber);
                        case "Issued": return ToText(revision.Issued);
                    }
                }
                // Python getattr(revision, field, u'') for any other member name.
                var property = string.IsNullOrEmpty(field) ? null : element.GetType().GetProperty(field);
                if (property == null || property.GetIndexParameters().Length > 0)
                    return "";
                return ToText(property.GetValue(element, null));
            }
            catch (Exception)
            {
                return "";
            }
        }

        // ==================================================================
        // view / sheet sets
        // ==================================================================

        /// <summary>Every saved View/Sheet Set, as {name: set of element id numbers}.</summary>
        public static Dictionary<string, HashSet<long>> ReadSheetSets(Document doc)
        {
            var sets = new Dictionary<string, HashSet<long>>(StringComparer.Ordinal);
            FilteredElementCollector collector;
            try
            {
                collector = new FilteredElementCollector(doc)
                    .OfClass(typeof(ViewSheetSet))
                    .WhereElementIsNotElementType();
            }
            catch (Exception)
            {
                return sets;
            }
            foreach (Element element in collector)
            {
                var entry = element as ViewSheetSet;
                if (entry == null)
                    continue;
                string name;
                try
                {
                    name = ToText(entry.Name);
                }
                catch (Exception)
                {
                    continue;
                }
                var members = new HashSet<long>();
                try
                {
                    foreach (View view in entry.Views)
                        members.Add(EidValue(view.Id));
                }
                catch (Exception) { }
                sets[name] = members;
            }
            return sets;
        }

        /// <summary>The saved View/Sheet Set called name, or null.</summary>
        public static ViewSheetSet FindViewSheetSet(Document doc, string name)
        {
            string wanted = ToText(name);
            FilteredElementCollector collector;
            try
            {
                collector = new FilteredElementCollector(doc)
                    .OfClass(typeof(ViewSheetSet))
                    .WhereElementIsNotElementType();
            }
            catch (Exception)
            {
                return null;
            }
            foreach (Element element in collector)
            {
                try
                {
                    if (element is ViewSheetSet entry && ToText(entry.Name) == wanted)
                        return entry;
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return null;
        }

        /// <summary>
        /// Write a View/Sheet Set: update it where it exists, make it where not.
        /// (ok, message). Opens and closes its own transaction, so the caller
        /// must hold none.
        /// Three things the 1.20.0 version got wrong, and all three fail quietly:
        /// - ViewSheetSetting is only usable with the print range on Select. Left on
        ///   Current Window or Visible Portion - Revit's default - it throws.
        /// - Updating an existing set means making it the current set first and
        ///   then calling Save. SaveAs with a name that is already taken throws, and
        ///   falling back to Save without switching sets saved the ticked sheets
        ///   over whichever set happened to be current.
        /// - A set can hold views as well as sheets. The register only manages
        ///   sheets, so the views already in the set are kept unless asked not to.
        /// </summary>
        public static (bool Ok, string Message) SaveViewSheetSet(Document doc, string name, IEnumerable<View> sheets, bool keepOtherViews = true)
        {
            name = ToText(name).Trim();
            if (name.Length == 0)
                return (false, "The set needs a name.");
            var sheetList = (sheets ?? Enumerable.Empty<View>()).Where(sheet => sheet != null).ToList();
            if (sheetList.Count == 0)
                return (false, "A View/Sheet Set cannot be empty - tick at least one sheet.");

            ViewSheetSet existing = FindViewSheetSet(doc, name);
            var views = new List<View>(sheetList);
            if (existing != null && keepOtherViews)
            {
                try
                {
                    foreach (View view in existing.Views)
                    {
                        if (!(view is ViewSheet))
                            views.Add(view);
                    }
                }
                catch (Exception) { }
            }

            using (var transaction = new Transaction(doc, "RevoBIM save View/Sheet Set"))
            {
                try
                {
                    transaction.Start();
                    PrintManager manager = doc.PrintManager;
                    manager.PrintRange = PrintRange.Select;
                    ViewSheetSetting setting = manager.ViewSheetSetting;
                    if (existing != null)
                        setting.CurrentViewSheetSet = existing;
                    var viewSet = new ViewSet();
                    foreach (View view in views)
                        viewSet.Insert(view);
                    setting.CurrentViewSheetSet.Views = viewSet;
                    if (existing != null)
                        setting.Save();
                    else
                        setting.SaveAs(name);
                    transaction.Commit();
                }
                catch (Exception err)
                {
                    try
                    {
                        if (transaction.HasStarted() && !transaction.HasEnded())
                            transaction.RollBack();
                    }
                    catch (Exception) { }
                    return (false, string.Format("The set \"{0}\" could not be saved: {1}", name, err.Message));
                }
            }
            return (true, string.Format("View/Sheet Set \"{0}\" {1} with {2} sheet{3}.",
                                        name, existing != null ? "updated" : "created",
                                        sheetList.Count, sheetList.Count == 1 ? "" : "s"));
        }

        /// <summary>Write onto each row which saved sets it belongs to.</summary>
        public static IList<Row> TagRowsWithSets(IList<Row> rows, IDictionary<string, HashSet<long>> sets)
        {
            foreach (Row row in rows)
            {
                row.Sets = sets.Where(entry => entry.Value.Contains(row.Key))
                               .Select(entry => entry.Key)
                               .OrderBy(name => name, StringComparer.Ordinal)
                               .ToList();
            }
            return rows;
        }

        // ==================================================================
        // the parameter catalogue for the Custom File Name dialog
        // ==================================================================

        // Values the tool works out rather than reading off an element. Keeping them
        // in the same list as real parameters means the naming dialog has one idea of
        // what a "parameter" is, and the user does not have to know the difference.
        public static readonly List<(string Name, string Group)> Derived = new List<(string Name, string Group)>
        {
            ("Sheet Number", "Sheet"),
            ("Sheet Name", "Sheet"),
            ("Sheet Size", "Sheet"),
            ("Sheet Orientation", "Sheet"),
            ("Current Revision", "Revision"),
            ("Current Revision Date", "Revision"),
            ("Current Revision Description", "Revision"),
            ("Current Revision Issued By", "Revision"),
            ("Current Revision Issued To", "Revision"),
            ("View Name", "View"),
            ("View Type", "View"),
            ("Project File Name", "Project"),
            ("Export Date", "Export"),
            ("Export Time", "Export"),
            ("User Name", "Export"),
        };

        public static readonly HashSet<string> DerivedNames =
            new HashSet<string>(Derived.Select(pair => pair.Name), StringComparer.Ordinal);

        public static Autodesk.Revit.DB.ProjectInfo ProjectInfo(Document doc)
        {
            try
            {
                return doc.ProjectInformation;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>
        /// Every parameter the naming dialog can offer, as (name, group) pairs.
        /// Sampled from the first few sheets rather than all of them - shared
        /// parameters are applied by category, so twenty sheets tell you everything
        /// four hundred would, and the dialog opens instantly instead of after a
        /// pause nobody expects from a dropdown.
        /// </summary>
        public static List<(string Name, string Group)> ParameterCatalogue(Document doc, IList<Row> rows)
        {
            var groups = new Dictionary<string, string>(StringComparer.Ordinal);
            var order = new List<string>();
            void Add(string name, string group)
            {
                if (groups.ContainsKey(name))
                {
                    groups[name] = group;
                    return;
                }
                groups[name] = group;
                order.Add(name);
            }

            foreach (var pair in Derived)
                Add(pair.Name, pair.Group);

            var sample = (rows ?? new List<Row>()).Take(20).Where(row => row.Element != null).ToList();
            foreach (Row row in sample)
            {
                foreach (string name in ParameterNames(row.Element))
                {
                    if (!groups.ContainsKey(name))
                        Add(name, row.IsSheet ? "Sheet" : "View");
                }
            }

            var info = ProjectInfo(doc);
            if (info != null)
            {
                foreach (string name in ParameterNames(info))
                {
                    // A project parameter wins the label, since that is where the user
                    // will look for it, but it must not displace a sheet parameter of
                    // the same name.
                    if (!groups.ContainsKey(name))
                        Add(name, "Project");
                }
            }

            return order.Select(name => (Name: name, Group: groups[name]))
                        .OrderBy(pair => NaturalKey(pair.Name))
                        .ToList();
        }

        /// <summary>The dropdown contents: All, then each group that actually has members.</summary>
        public static List<string> CatalogueGroups(IEnumerable<(string Name, string Group)> pairs)
        {
            var seen = new List<string>();
            foreach (var pair in pairs)
            {
                if (!seen.Contains(pair.Group))
                    seen.Add(pair.Group);
            }
            var result = new List<string> { "All" };
            result.AddRange(seen.OrderBy(group => group, StringComparer.Ordinal));
            return result;
        }

        // ==================================================================
        // the lookup a row hands to the naming and path engines
        // ==================================================================

        /// <summary>
        /// Resolve a parameter name against one row, then the project.
        /// Order matters and is deliberate: the element first, because a sheet
        /// parameter and a project parameter can share a name and the sheet's is the
        /// one that varies per file; then project information; then the derived
        /// values the tool computes itself.
        /// Python called the object itself; here call Invoke(name), or pass the
        /// RowLookup where a Func&lt;string, string&gt; is wanted (implicit conversion).
        /// </summary>
        public class RowLookup
        {
            public Document Doc { get; set; }
            public Row Row { get; set; }
            public (string Date, string Time)? Stamp { get; set; }
            public string UserName { get; set; }
            internal Dictionary<string, string> Cache { get; } = new Dictionary<string, string>(StringComparer.Ordinal);

            public RowLookup(Document doc, Row row, (string Date, string Time)? exportStamp = null, string userName = "")
            {
                Doc = doc;
                Row = row;
                Stamp = exportStamp;
                UserName = userName;
            }

            public string Invoke(string name)
            {
                name = ToText(name).Trim();
                if (name.Length == 0)
                    return "";
                if (Cache.TryGetValue(name, out string cached))
                    return cached;
                string value = Resolve(name);
                Cache[name] = value;
                return value;
            }

            public static implicit operator Func<string, string>(RowLookup lookup)
            {
                return lookup == null ? null : new Func<string, string>(lookup.Invoke);
            }

            internal string Resolve(string name)
            {
                Row row = Row;
                Element element = row?.Element;

                if (element != null)
                {
                    string found = ParamText(element, name);
                    if (!string.IsNullOrEmpty(found))
                        return found;
                }

                var info = ProjectInfo(Doc);
                if (info != null)
                {
                    string found = ParamText(info, name);
                    if (!string.IsNullOrEmpty(found))
                        return found;
                }

                return Derived(name);
            }

            internal string Derived(string name)
            {
                Row row = Row;
                Document doc = Doc;
                if (name == "Sheet Number")
                    return row != null ? row.Number : "";
                if (name == "Sheet Name" || name == "View Name")
                    return row != null ? row.Name : "";
                if (name == "Sheet Size")
                {
                    // The bare size, not the Size column's label. The column says
                    // "A1 landscape" to be useful to read; a file name that suddenly
                    // gained " landscape" because the column got chattier would be a
                    // nasty surprise on a re-issue.
                    if (row == null || row.SizeInfo == null)
                        return "";
                    return ToText(row.SizeInfo.Name);
                }
                if (name == "Sheet Orientation")
                {
                    if (row == null || row.SizeInfo == null)
                        return "";
                    return ToText(row.SizeInfo.Orientation());
                }
                if (name == "View Type")
                    return row != null ? row.ViewType : "";
                if (name == "Current Revision")
                    return row != null ? row.Revision : "";
                if (name.StartsWith("Current Revision ", StringComparison.Ordinal) && row != null && row.IsSheet)
                {
                    string field = null;
                    switch (name)
                    {
                        case "Current Revision Date": field = "RevisionDate"; break;
                        case "Current Revision Description": field = "Description"; break;
                        case "Current Revision Issued By": field = "IssuedBy"; break;
                        case "Current Revision Issued To": field = "IssuedTo"; break;
                    }
                    if (field != null)
                        return CurrentRevisionField(doc, row.Element, field);
                }
                if (name == "Project File Name")
                {
                    try
                    {
                        string path = ToText(doc?.PathName);
                        if (path.Length > 0)
                            return PsPaths.OsPathSplitExt(PsPaths.OsPathBaseName(path)).Root;
                        return ToText(doc?.Title);
                    }
                    catch (Exception)
                    {
                        return "";
                    }
                }
                if (name == "Export Date" && Stamp != null)
                    return Stamp.Value.Date;
                if (name == "Export Time" && Stamp != null)
                    return Stamp.Value.Time;
                if (name == "User Name")
                    return UserName;
                return "";
            }
        }

        /// <summary>Today's date and the time now, as (date, time) in file-safe form.</summary>
        public static (string Date, string Time) ExportStamp()
        {
            try
            {
                DateTime now = DateTime.Now;
                return (now.ToString("yyyy-MM-dd", Inv), now.ToString("HHmm", Inv));
            }
            catch (Exception)
            {
                return ("", "");
            }
        }

        public static string CurrentUser(Autodesk.Revit.ApplicationServices.Application app)
        {
            try
            {
                if (app != null)
                    return ToText(app.Username);
            }
            catch (Exception) { }
            try
            {
                return ToText(Environment.UserName);
            }
            catch (Exception)
            {
                return "";
            }
        }

        /// <summary>
        /// Which rows were already selected in Revit when the tool opened.
        /// Returns the subset of rows whose element the user had picked, so the first
        /// page can isolate to exactly those. An empty answer means nothing relevant
        /// was selected and the full list should stand.
        /// </summary>
        public static List<Row> PreselectedRows(UIDocument uidoc, IEnumerable<Row> rows)
        {
            var picked = new HashSet<long>();
            var ids = new List<ElementId>();
            try
            {
                foreach (ElementId elementId in uidoc.Selection.GetElementIds())
                {
                    ids.Add(elementId);
                    picked.Add(EidValue(elementId));
                }
            }
            catch (Exception)
            {
                return new List<Row>();
            }
            if (picked.Count == 0)
                return new List<Row>();

            var rowList = (rows ?? Enumerable.Empty<Row>()).ToList();
            var matched = rowList.Where(row => picked.Contains(row.Key)).ToList();
            if (matched.Count > 0)
                return matched;

            // Nothing in the selection is a sheet, but the selected elements may sit
            // on sheets - taking their owning sheets is what the user meant.
            var owners = new HashSet<long>();
            try
            {
                Document doc = uidoc.Document;
                foreach (ElementId elementId in ids)
                {
                    Element element = doc.GetElement(elementId);
                    if (element == null)
                        continue;
                    long owner = EidValue(element.OwnerViewId);
                    if (owner != 0)
                        owners.Add(owner);
                }
            }
            catch (Exception) { }
            if (owners.Count == 0)
                return new List<Row>();
            return rowList.Where(row => owners.Contains(row.Key)).ToList();
        }
    }
}
