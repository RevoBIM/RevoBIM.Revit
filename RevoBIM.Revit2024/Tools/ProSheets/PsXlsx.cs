using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ProSheets
{
    /// <summary>
    /// A small Excel writer with no dependencies: Office Open XML straight to a zip.
    ///
    /// No Excel, no interop: a workbook is a zip of XML files, and writing those
    /// directly gives full control over rotated text, merges, borders, frozen panes,
    /// print titles and embedded logos.
    ///
    /// A styles registry: fonts, fills, borders and cell formats are deduplicated and
    /// handed back as indices. Excel insists the first two fills are none and gray125.
    /// Inline strings: text is written t="inlineStr", which skips the shared strings part.
    /// Schema order: OOXML fixes the order of the elements inside worksheet and Excel
    /// enforces it - sheetPr, dimension, sheetViews, sheetFormatPr, cols, sheetData,
    /// mergeCells, pageMargins, pageSetup, drawing. Lenient readers do not care, which is
    /// exactly how this ships broken, so each sheet is built in that order.
    /// A row that carries only a height is still written: heights live on row, so a row
    /// with no cells - the lower half of a merged band - would silently lose its height.
    ///
    /// Nothing here touches Revit. Port of ps_xlsx.py; the zip is written with
    /// System.IO.Compression (the Python's .NET route; its zipfile fallback is not needed).
    /// </summary>
    public static partial class PsXlsx
    {
        internal static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        public const string MainNs = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
        public const string RelNs = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
        public const string PkgRelNs = "http://schemas.openxmlformats.org/package/2006/relationships";
        public const string CtNs = "http://schemas.openxmlformats.org/package/2006/content-types";
        public const string XdrNs = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing";
        public const string ANs = "http://schemas.openxmlformats.org/drawingml/2006/main";

        public const string RelDoc = RelNs + "/officeDocument";
        public const string RelSheet = RelNs + "/worksheet";
        public const string RelStyles = RelNs + "/styles";
        public const string RelDrawing = RelNs + "/drawing";
        public const string RelImage = RelNs + "/image";

        public const string CtWorkbook = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml";
        public const string CtSheet = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml";
        public const string CtStyles = "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml";
        public const string CtDrawing = "application/vnd.openxmlformats-officedocument.drawing+xml";

        public static readonly Dictionary<string, (string Extension, string ContentType)> ImageTypes =
            new Dictionary<string, (string Extension, string ContentType)>(StringComparer.Ordinal)
            {
                { ".png", ("png", "image/png") },
                { ".jpg", ("jpeg", "image/jpeg") },
                { ".jpeg", ("jpeg", "image/jpeg") },
            };

        // Excel's paper codes for the sizes a register gets printed on.
        public static readonly Dictionary<string, int> Paper =
            new Dictionary<string, int>(StringComparer.Ordinal) { { "A4", 9 }, { "A3", 8 } };

        public const int EmuPerPixel = 9525;

        // ======================================================================
        // small helpers
        // ======================================================================

        internal static readonly Regex BadXml = new Regex("[\x00-\x08\x0b\x0c\x0e-\x1f]");

        /// <summary>Python's u'{0}'.format(value): floats as Python prints them.</summary>
        internal static string PyStr(object value)
        {
            switch (value)
            {
                case null: return "None";
                case string s: return s;
                case bool b: return b ? "True" : "False";
                case double d: return PyFloat(d);
                case float f: return PyFloat(f);
                case IFormattable formattable: return formattable.ToString(null, Inv);
                default: return value.ToString();
            }
        }

        /// <summary>repr() of a Python float: shortest round trip, always with a point.</summary>
        internal static string PyFloat(double value)
        {
            if (double.IsNaN(value)) return "nan";
            if (double.IsPositiveInfinity(value)) return "inf";
            if (double.IsNegativeInfinity(value)) return "-inf";
            string text = value.ToString("R", Inv);
            if (text.IndexOf('E') >= 0)
            {
                // 1E+16 -> 1e+16, as Python writes it.
                string[] parts = text.Split('E');
                string exp = parts[1];
                string sign = exp.StartsWith("-") ? "-" : "+";
                exp = exp.TrimStart('+', '-').PadLeft(2, '0');
                return parts[0] + "e" + sign + exp;
            }
            if (text.IndexOf('.') < 0)
                text += ".0";
            return text;
        }

        /// <summary>Text made safe for an XML element or attribute.</summary>
        public static string Escape(object text)
        {
            string body = BadXml.Replace(text != null ? PyStr(text) : "", "");
            return body.Replace("&", "&amp;").Replace("<", "&lt;")
                       .Replace(">", "&gt;").Replace("\"", "&quot;");
        }

        /// <summary>1 -> A, 26 -> Z, 27 -> AA.</summary>
        public static string ColumnLetter(int index)
        {
            string letters = "";
            while (index > 0)
            {
                int remainder = (index - 1) % 26;
                index = (index - 1) / 26;
                letters = ((char)(65 + remainder)).ToString() + letters;
            }
            return letters;
        }

        public static string CellRef(int row, int col)
        {
            return ColumnLetter(col) + row.ToString(Inv);
        }

        public static string RangeRef(int row1, int col1, int row2, int col2)
        {
            return CellRef(row1, col1) + ":" + CellRef(row2, col2);
        }

        internal static readonly Regex SheetBad = new Regex(@"[\[\]:*?/\\]");

        /// <summary>
        /// A worksheet name Excel accepts, unique among <paramref name="taken"/> (lower case).
        /// No [ ] : * ? / \, not blank, at most 31 characters, and unique *after* the cut -
        /// two long discipline names that only differ past the 31st character would
        /// otherwise collide and Excel refuses the file.
        /// </summary>
        public static string SafeSheetName(string name, HashSet<string> taken)
        {
            string baseName = SheetBad.Replace(name ?? "", "-").Trim().Trim('\'');
            if (baseName.Length == 0)
                baseName = "Sheet";
            if (baseName.Length > 31)
                baseName = baseName.Substring(0, 31);
            string candidate = baseName;
            int number = 2;
            while (taken.Contains(candidate.ToLowerInvariant()))
            {
                string suffix = string.Format(Inv, " ({0})", number);
                int keep = Math.Max(0, Math.Min(baseName.Length, 31 - suffix.Length));
                candidate = baseName.Substring(0, keep) + suffix;
                number += 1;
            }
            taken.Add(candidate.ToLowerInvariant());
            return candidate;
        }

        /// <summary>Excel's column width in characters as screen pixels.</summary>
        public static int WidthPixels(double chars)
        {
            return (int)Math.Round(chars * 7.0 + 5, MidpointRounding.AwayFromZero);
        }

        public static int HeightPixels(double points)
        {
            return (int)Math.Round(points * 96.0 / 72.0, MidpointRounding.AwayFromZero);
        }

        /// <summary>
        /// (width, height) in pixels of a PNG or JPEG, read from its header, or null.
        /// Read by hand because the only thing needed is two numbers.
        /// </summary>
        public static (int Width, int Height)? ImageSize(string path)
        {
            byte[] data;
            try
            {
                using (var handle = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    var buffer = new byte[65536];
                    int total = 0;
                    while (total < buffer.Length)
                    {
                        int read = handle.Read(buffer, total, buffer.Length - total);
                        if (read <= 0) break;
                        total += read;
                    }
                    data = new byte[total];
                    Array.Copy(buffer, data, total);
                }
            }
            catch (Exception)
            {
                return null;
            }
            byte[] png = { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A };
            if (data.Length >= 24 && data.Take(8).SequenceEqual(png))
            {
                uint width = ((uint)data[16] << 24) | ((uint)data[17] << 16) | ((uint)data[18] << 8) | data[19];
                uint height = ((uint)data[20] << 24) | ((uint)data[21] << 16) | ((uint)data[22] << 8) | data[23];
                return ((int)width, (int)height);
            }
            if (data.Length >= 2 && data[0] == 0xFF && data[1] == 0xD8)
            {
                int index = 2;
                var sof = new HashSet<int> { 0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF };
                while (index + 9 < data.Length)
                {
                    if (data[index] != 0xFF)
                    {
                        index += 1;
                        continue;
                    }
                    int marker = data[index + 1];
                    if (sof.Contains(marker))
                    {
                        int height = (data[index + 5] << 8) | data[index + 6];
                        int width = (data[index + 7] << 8) | data[index + 8];
                        return (width, height);
                    }
                    int length = (data[index + 2] << 8) + data[index + 3];
                    index += 2 + length;
                }
            }
            return null;
        }

        // ======================================================================
        // styles
        // ======================================================================

        /// <summary>Fonts, fills, borders and cell formats, deduplicated into indices.</summary>
        public class Styles
        {
            public string FontName;
            public double FontSize;
            // One colour for every border line in the book. The RD9 form draws
            // them black; the grey is kept for anything else built on this.
            public string BorderColor;
            public List<(double Size, bool Bold, bool Italic, string Color, string Name)> Fonts;
            // The first two are required by Excel, in this order.
            public List<string> Fills;
            public List<(string Left, string Right, string Top, string Bottom)> Borders;
            public List<(int Font, int Fill, int Border, (string H, string V, bool Wrap, int Rotate, int Indent)? Align)> Formats;

            public Styles(string fontName = "Calibri", double fontSize = 10, string borderColor = "FF7F7F7F")
            {
                FontName = fontName;
                FontSize = fontSize;
                BorderColor = borderColor;
                Fonts = new List<(double, bool, bool, string, string)> { (fontSize, false, false, "FF000000", fontName) };
                Fills = new List<string> { "none", "gray125" };
                Borders = new List<(string, string, string, string)> { (null, null, null, null) };
                Formats = new List<(int, int, int, (string, string, bool, int, int)?)> { (0, 0, 0, null) };
            }

            internal static int Index<T>(List<T> table, T item)
            {
                int found = table.IndexOf(item);
                if (found >= 0)
                    return found;
                table.Add(item);
                return table.Count - 1;
            }

            /// <summary>
            /// The index of a cell format. <paramref name="border"/> is a list of four
            /// (left, right, top, bottom), each null, "thin" or "medium"; or one of those
            /// strings for all four sides. <paramref name="font"/> is a typeface name when the
            /// cell is not in the book's own.
            /// </summary>
            public int Style(double? size = null, bool bold = false, bool italic = false, string color = "FF000000",
                             string fill = null, object border = null, string h = null, string v = "center",
                             bool wrap = false, int rotate = 0, int indent = 0, string font = null)
            {
                int fontId = Index(Fonts, ((size.HasValue && size.Value != 0) ? size.Value : FontSize, bold, italic, color,
                                           !string.IsNullOrEmpty(font) ? font : FontName));
                int fillId = !string.IsNullOrEmpty(fill) ? Index(Fills, fill) : 0;
                (string, string, string, string) sides;
                if (border is string one && one.Length > 0)
                    sides = (one, one, one, one);
                else if (border is IList list && !(border is string))
                {
                    string Side(int i) => i < list.Count ? list[i] as string : null;
                    sides = (Side(0), Side(1), Side(2), Side(3));
                }
                else
                    sides = (null, null, null, null);
                int borderId = Index(Borders, sides);
                (string, string, bool, int, int)? align = (h, v, wrap, rotate, indent);
                return Index(Formats, (fontId, fillId, borderId, align));
            }

            public string Xml()
            {
                var o = new StringBuilder();
                o.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
                o.AppendFormat(Inv, "<styleSheet xmlns=\"{0}\">", MainNs);
                o.AppendFormat(Inv, "<fonts count=\"{0}\">", Fonts.Count);
                foreach (var (size, bold, italic, color, name) in Fonts)
                {
                    o.AppendFormat(Inv, "<font>{0}{1}<sz val=\"{2}\"/><color rgb=\"{3}\"/><name val=\"{4}\"/><family val=\"2\"/></font>",
                        bold ? "<b/>" : "", italic ? "<i/>" : "", size.ToString("R", Inv), color, Escape(name));
                }
                o.Append("</fonts>");
                o.AppendFormat(Inv, "<fills count=\"{0}\">", Fills.Count);
                foreach (string fill in Fills)
                {
                    if (fill == "none" || fill == "gray125")
                        o.AppendFormat(Inv, "<fill><patternFill patternType=\"{0}\"/></fill>", fill);
                    else
                        o.AppendFormat(Inv, "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"{0}\"/><bgColor indexed=\"64\"/></patternFill></fill>", fill);
                }
                o.Append("</fills>");
                o.AppendFormat(Inv, "<borders count=\"{0}\">", Borders.Count);
                foreach (var sides in Borders)
                {
                    var parts = new StringBuilder();
                    string[] tags = { "left", "right", "top", "bottom" };
                    string[] kinds = { sides.Left, sides.Right, sides.Top, sides.Bottom };
                    for (int i = 0; i < 4; i++)
                    {
                        if (!string.IsNullOrEmpty(kinds[i]))
                            parts.AppendFormat(Inv, "<{0} style=\"{1}\"><color rgb=\"{2}\"/></{0}>", tags[i], kinds[i], BorderColor);
                        else
                            parts.AppendFormat(Inv, "<{0}/>", tags[i]);
                    }
                    o.AppendFormat(Inv, "<border>{0}<diagonal/></border>", parts);
                }
                o.Append("</borders>");
                o.Append("<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>");
                o.AppendFormat(Inv, "<cellXfs count=\"{0}\">", Formats.Count);
                foreach (var (font, fillId, borderId, align) in Formats)
                {
                    if (align == null)
                    {
                        o.Append("<xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/>");
                        continue;
                    }
                    var (h, v, wrap, rotate, indent) = align.Value;
                    var attrs = new List<string>();
                    if (!string.IsNullOrEmpty(h))
                        attrs.Add(string.Format(Inv, "horizontal=\"{0}\"", h));
                    if (!string.IsNullOrEmpty(v))
                        attrs.Add(string.Format(Inv, "vertical=\"{0}\"", v));
                    if (wrap)
                        attrs.Add("wrapText=\"1\"");
                    if (rotate != 0)
                        attrs.Add(string.Format(Inv, "textRotation=\"{0}\"", rotate));
                    if (indent != 0)
                        attrs.Add(string.Format(Inv, "indent=\"{0}\"", indent));
                    o.AppendFormat(Inv, "<xf numFmtId=\"0\" fontId=\"{0}\" fillId=\"{1}\" borderId=\"{2}\" xfId=\"0\" applyFont=\"1\" applyFill=\"1\" applyBorder=\"1\" applyAlignment=\"1\"><alignment {3}/></xf>",
                        font, fillId, borderId, string.Join(" ", attrs));
                }
                o.Append("</cellXfs>");
                o.Append("<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>");
                o.Append("</styleSheet>");
                return o.ToString();
            }
        }

        // ======================================================================
        // a worksheet
        // ======================================================================

        public class Sheet
        {
            public string Name;
            public Dictionary<(int Row, int Col), (object Value, int Style, bool Number)> Cells =
                new Dictionary<(int Row, int Col), (object Value, int Style, bool Number)>();
            public List<(int Row1, int Col1, int Row2, int Col2)> Merges = new List<(int, int, int, int)>();
            public Dictionary<int, double> Widths = new Dictionary<int, double>();      // col: characters
            public Dictionary<int, double> Heights = new Dictionary<int, double>();     // row: points
            public (int Rows, int Cols)? Freeze;          // (rows above, columns left)
            public (int First, int Last)? PrintRows;      // repeated on every page
            // Pictures placed by position in pixels from the sheet's top left,
            // so a caller lays them out against the form rather than counting columns.
            public List<(string Path, int X, int Y, int Width, int Height)> Images =
                new List<(string, int, int, int, int)>();
            public bool PrintArea;                        // print the used block and nothing else
            public bool Landscape = true;
            public int Paper = PsXlsx.Paper["A3"];
            public bool FitWidth = true;
            // (left, right, top, bottom, header, footer) in inches.
            public (double Left, double Right, double Top, double Bottom, double Header, double Footer) Margins =
                (0.4, 0.4, 0.5, 0.5, 0.3, 0.3);
            public bool Selected;

            public Sheet(string name)
            {
                Name = name;
            }

            public void Set(int row, int col, object value, int style = 0, bool number = false)
            {
                Cells[(row, col)] = (value, style, number);
            }

            /// <summary>
            /// Give every cell in a block a format, keeping any value already set. Excel
            /// draws a border per cell, so a merged range only has a border all the way
            /// round if every cell inside it carries one.
            /// </summary>
            public void StyleRange(int row1, int col1, int row2, int col2, int style)
            {
                for (int row = row1; row <= row2; row++)
                {
                    for (int col = col1; col <= col2; col++)
                    {
                        Cells.TryGetValue((row, col), out var cell);   // default (null, 0, false)
                        Cells[(row, col)] = (cell.Value, style, cell.Number);
                    }
                }
            }

            /// <summary>Merge a block, put a value in its top left, style all of it.</summary>
            public void Merge(int row1, int col1, int row2, int col2, object value = null, int style = 0)
            {
                StyleRange(row1, col1, row2, col2, style);
                if (value != null)
                    Set(row1, col1, value, style);
                if (row1 != row2 || col1 != col2)
                    Merges.Add((row1, col1, row2, col2));
            }

            // Stored as double (the Python stored float so a precision format never met an int).
            public void Width(int col, double chars)
            {
                Widths[col] = chars;
            }

            public void Height(int row, double points)
            {
                Heights[row] = points;
            }

            /// <summary>Place a picture width x height pixels at x, y.</summary>
            public void Image(string path, double x, double y, double width, double height)
            {
                Images.Add((path, (int)x, (int)y, Math.Max(1, (int)width), Math.Max(1, (int)height)));
            }

            /// <summary>
            /// (col, col offset, row, row offset), zero based, of a pixel point. A
            /// oneCellAnchor's offset has to fall inside its cell: Excel moves a picture whose
            /// offset runs past the column edge, differently in different versions. So the
            /// column and row are found from the widths and heights.
            /// </summary>
            public (int Col, int ColOffset, int Row, int RowOffset) Anchor(int x, int y)
            {
                int col = 1, left = 0;
                while (true)
                {
                    int span = WidthPixels(Widths.TryGetValue(col, out double w) ? w : 8.43);
                    if (x < left + span || col >= 16384)
                        break;
                    left += span;
                    col += 1;
                }
                int row = 1, top = 0;
                while (true)
                {
                    int span = HeightPixels(Heights.TryGetValue(row, out double hgt) ? hgt : 15);
                    if (y < top + span || row >= 1048576)
                        break;
                    top += span;
                    row += 1;
                }
                return (col - 1, x - left, row - 1, y - top);
            }

            public (int LastRow, int LastCol) Extent()
            {
                var rows = Cells.Keys.Select(k => k.Row).Concat(Heights.Keys).ToList();
                var cols = Cells.Keys.Select(k => k.Col).Concat(Widths.Keys).ToList();
                return (rows.Count > 0 ? rows.Max() : 1, cols.Count > 0 ? cols.Max() : 1);
            }

            public string Xml(string drawingRid = null)
            {
                var (lastRow, lastCol) = Extent();
                var o = new StringBuilder();
                o.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
                o.AppendFormat(Inv, "<worksheet xmlns=\"{0}\" xmlns:r=\"{1}\">", MainNs, RelNs);

                // -- sheetPr: fit to page has to be switched on here as well as in
                // pageSetup, or Excel ignores fitToWidth.
                if (FitWidth)
                    o.Append("<sheetPr><pageSetUpPr fitToPage=\"1\"/></sheetPr>");

                o.AppendFormat(Inv, "<dimension ref=\"{0}\"/>", RangeRef(1, 1, lastRow, lastCol));

                // -- sheetViews
                string view = string.Format(Inv, "<sheetView workbookViewId=\"0\"{0}>", Selected ? " tabSelected=\"1\"" : "");
                if (Freeze.HasValue && (Freeze.Value.Rows != 0 || Freeze.Value.Cols != 0))
                {
                    int rows = Freeze.Value.Rows, cols = Freeze.Value.Cols;
                    string topLeft = CellRef(rows + 1, cols + 1);
                    string pane;
                    if (rows != 0 && cols != 0)
                        pane = "bottomRight";
                    else if (rows != 0)
                        pane = "bottomLeft";
                    else
                        pane = "topRight";
                    string split = "";
                    if (cols != 0)
                        split += string.Format(Inv, " xSplit=\"{0}\"", cols);
                    if (rows != 0)
                        split += string.Format(Inv, " ySplit=\"{0}\"", rows);
                    view += string.Format(Inv,
                        "<pane{0} topLeftCell=\"{1}\" activePane=\"{2}\" state=\"frozen\"/><selection pane=\"{2}\" activeCell=\"{1}\" sqref=\"{1}\"/>",
                        split, topLeft, pane);
                }
                view += "</sheetView>";
                o.AppendFormat(Inv, "<sheetViews>{0}</sheetViews>", view);

                o.Append("<sheetFormatPr defaultRowHeight=\"15\"/>");

                // -- cols
                if (Widths.Count > 0)
                {
                    o.Append("<cols>");
                    foreach (int col in Widths.Keys.OrderBy(k => k))
                        o.AppendFormat(Inv, "<col min=\"{0}\" max=\"{0}\" width=\"{1}\" customWidth=\"1\"/>",
                            col, Widths[col].ToString("0.00", Inv));
                    o.Append("</cols>");
                }

                // -- sheetData. Every row with cells or with a height of its own.
                o.Append("<sheetData>");
                var allRows = new HashSet<int>(Cells.Keys.Select(k => k.Row));
                allRows.UnionWith(Heights.Keys);
                var byRow = Cells.Keys.GroupBy(k => k.Row).ToDictionary(g => g.Key, g => g.OrderBy(k => k.Col).ToList());
                foreach (int row in allRows.OrderBy(r => r))
                {
                    string attrs = string.Format(Inv, " r=\"{0}\"", row);
                    if (Heights.TryGetValue(row, out double height))
                        attrs += string.Format(Inv, " ht=\"{0}\" customHeight=\"1\"", height.ToString("0.00", Inv));
                    if (!byRow.TryGetValue(row, out var cells) || cells.Count == 0)
                    {
                        o.AppendFormat(Inv, "<row{0}/>", attrs);
                        continue;
                    }
                    o.AppendFormat(Inv, "<row{0}>", attrs);
                    foreach (var key in cells)
                    {
                        var (value, style, number) = Cells[key];
                        string reference = CellRef(key.Row, key.Col);
                        string styleAttr = style != 0 ? string.Format(Inv, " s=\"{0}\"", style) : "";
                        if (value == null || (value is string text && text.Length == 0))
                            o.AppendFormat(Inv, "<c r=\"{0}\"{1}/>", reference, styleAttr);
                        else if (number)
                            o.AppendFormat(Inv, "<c r=\"{0}\"{1}><v>{2}</v></c>", reference, styleAttr, PyStr(value));
                        else
                            o.AppendFormat(Inv, "<c r=\"{0}\"{1} t=\"inlineStr\"><is><t xml:space=\"preserve\">{2}</t></is></c>",
                                reference, styleAttr, Escape(value));
                    }
                    o.Append("</row>");
                }
                o.Append("</sheetData>");

                // -- mergeCells. Never a single cell: Excel calls that corrupt.
                var merges = Merges.Where(m => m.Row1 != m.Row2 || m.Col1 != m.Col2).ToList();
                if (merges.Count > 0)
                {
                    o.AppendFormat(Inv, "<mergeCells count=\"{0}\">", merges.Count);
                    foreach (var (row1, col1, row2, col2) in merges)
                        o.AppendFormat(Inv, "<mergeCell ref=\"{0}\"/>", RangeRef(row1, col1, row2, col2));
                    o.Append("</mergeCells>");
                }

                o.AppendFormat(Inv, "<pageMargins left=\"{0}\" right=\"{1}\" top=\"{2}\" bottom=\"{3}\" header=\"{4}\" footer=\"{5}\"/>",
                    PyFloat(Margins.Left), PyFloat(Margins.Right), PyFloat(Margins.Top),
                    PyFloat(Margins.Bottom), PyFloat(Margins.Header), PyFloat(Margins.Footer));
                o.AppendFormat(Inv, "<pageSetup paperSize=\"{0}\" orientation=\"{1}\"{2}/>",
                    Paper, Landscape ? "landscape" : "portrait",
                    FitWidth ? " fitToWidth=\"1\" fitToHeight=\"0\"" : "");
                if (!string.IsNullOrEmpty(drawingRid))
                    o.AppendFormat(Inv, "<drawing r:id=\"{0}\"/>", drawingRid);
                o.Append("</worksheet>");
                return o.ToString();
            }
        }

        // ======================================================================
        // the workbook
        // ======================================================================

        public class Workbook
        {
            public Styles Styles;
            public List<Sheet> Sheets = new List<Sheet>();
            internal HashSet<string> Taken = new HashSet<string>(StringComparer.Ordinal);

            public Workbook(string fontName = "Calibri", double fontSize = 10, string borderColor = "FF7F7F7F")
            {
                Styles = new Styles(fontName, fontSize, borderColor);
            }

            public Sheet AddSheet(string name)
            {
                var sheet = new Sheet(SafeSheetName(name, Taken));
                if (Sheets.Count == 0)
                    sheet.Selected = true;
                Sheets.Add(sheet);
                return sheet;
            }

            /// <summary>(extension, content type) of a picture Excel can show, or null.</summary>
            public static (string Extension, string ContentType)? UsableImage(string path)
            {
                if (string.IsNullOrEmpty(path) || !File.Exists(path))
                    return null;
                string ext;
                try { ext = Path.GetExtension(path).ToLowerInvariant(); }
                catch (Exception) { return null; }
                if (!ImageTypes.TryGetValue(ext, out var kind) || ImageSize(path) == null)
                    return null;
                return kind;
            }

            /// <summary>
            /// {path: (zip name, extension, content type)} - each file once. The same logo on
            /// every worksheet is one file in the zip, and a PNG and a JPEG side by side are
            /// two, each with its own extension - Excel refuses a picture whose extension has
            /// no Default type.
            /// </summary>
            internal Dictionary<string, (string Name, string Extension, string Content)> Media()
            {
                var media = new Dictionary<string, (string Name, string Extension, string Content)>(StringComparer.Ordinal);
                foreach (var sheet in Sheets)
                {
                    foreach (var picture in sheet.Images)
                    {
                        string path = picture.Path;
                        if (path == null || media.ContainsKey(path))
                            continue;
                        var kind = UsableImage(path);
                        if (kind == null)
                            continue;
                        media[path] = (string.Format(Inv, "image{0}.{1}", media.Count + 1, kind.Value.Extension),
                                       kind.Value.Extension, kind.Value.ContentType);
                    }
                }
                return media;
            }

            /// <summary>
            /// [(zip path, text, file)] in a stable order. Each part is either XML text
            /// (File null) or a file on disk copied as is (Text null) - the Python's
            /// text-or-('file', path) payload.
            /// </summary>
            public List<(string Name, string Text, string File)> Parts()
            {
                var media = Media();
                var placed = Sheets.Select(sheet => sheet.Images.Where(one => one.Path != null && media.ContainsKey(one.Path)).ToList()).ToList();
                var drawn = Enumerable.Range(0, placed.Count).Where(i => placed[i].Count > 0).ToList();
                var mediaByName = media.Keys.OrderBy(one => media[one].Name, StringComparer.Ordinal).ToList();

                var types = new StringBuilder();
                types.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
                types.AppendFormat(Inv, "<Types xmlns=\"{0}\">", CtNs);
                types.Append("<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>");
                types.Append("<Default Extension=\"xml\" ContentType=\"application/xml\"/>");
                var declared = new HashSet<string>(StringComparer.Ordinal);
                foreach (string path in mediaByName)
                {
                    var (_, extension, content) = media[path];
                    if (declared.Contains(extension))
                        continue;
                    declared.Add(extension);
                    types.AppendFormat(Inv, "<Default Extension=\"{0}\" ContentType=\"{1}\"/>", extension, content);
                }
                types.AppendFormat(Inv, "<Override PartName=\"/xl/workbook.xml\" ContentType=\"{0}\"/>", CtWorkbook);
                for (int number = 1; number <= Sheets.Count; number++)
                    types.AppendFormat(Inv, "<Override PartName=\"/xl/worksheets/sheet{0}.xml\" ContentType=\"{1}\"/>", number, CtSheet);
                foreach (int index in drawn)
                    types.AppendFormat(Inv, "<Override PartName=\"/xl/drawings/drawing{0}.xml\" ContentType=\"{1}\"/>", index + 1, CtDrawing);
                types.AppendFormat(Inv, "<Override PartName=\"/xl/styles.xml\" ContentType=\"{0}\"/>", CtStyles);
                types.Append("</Types>");

                var parts = new List<(string Name, string Text, string File)>
                {
                    ("[Content_Types].xml", types.ToString(), null),
                    ("_rels/.rels", string.Format(Inv,
                        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><Relationships xmlns=\"{0}\"><Relationship Id=\"rId1\" Type=\"{1}\" Target=\"xl/workbook.xml\"/></Relationships>",
                        PkgRelNs, RelDoc), null),
                };
                parts.Add(("xl/workbook.xml", WorkbookXml(), null));

                var rels = new StringBuilder();
                rels.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
                rels.AppendFormat(Inv, "<Relationships xmlns=\"{0}\">", PkgRelNs);
                for (int number = 1; number <= Sheets.Count; number++)
                    rels.AppendFormat(Inv, "<Relationship Id=\"rId{0}\" Type=\"{1}\" Target=\"worksheets/sheet{0}.xml\"/>", number, RelSheet);
                rels.AppendFormat(Inv, "<Relationship Id=\"rId{0}\" Type=\"{1}\" Target=\"styles.xml\"/>", Sheets.Count + 1, RelStyles);
                rels.Append("</Relationships>");
                parts.Add(("xl/_rels/workbook.xml.rels", rels.ToString(), null));
                parts.Add(("xl/styles.xml", Styles.Xml(), null));

                for (int index = 0; index < Sheets.Count; index++)
                {
                    int number = index + 1;
                    var sheet = Sheets[index];
                    var pictures = placed[index];
                    parts.Add((string.Format(Inv, "xl/worksheets/sheet{0}.xml", number),
                               sheet.Xml(pictures.Count > 0 ? "rId1" : null), null));
                    if (pictures.Count == 0)
                        continue;
                    parts.Add((string.Format(Inv, "xl/worksheets/_rels/sheet{0}.xml.rels", number),
                               string.Format(Inv,
                                   "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><Relationships xmlns=\"{0}\"><Relationship Id=\"rId1\" Type=\"{1}\" Target=\"../drawings/drawing{2}.xml\"/></Relationships>",
                                   PkgRelNs, RelDrawing, number), null));
                    parts.Add((string.Format(Inv, "xl/drawings/drawing{0}.xml", number), DrawingXml(sheet, pictures), null));
                    var links = new StringBuilder();
                    links.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
                    links.AppendFormat(Inv, "<Relationships xmlns=\"{0}\">", PkgRelNs);
                    for (int slot = 1; slot <= pictures.Count; slot++)
                        links.AppendFormat(Inv, "<Relationship Id=\"rId{0}\" Type=\"{1}\" Target=\"../media/{2}\"/>",
                            slot, RelImage, media[pictures[slot - 1].Path].Name);
                    links.Append("</Relationships>");
                    parts.Add((string.Format(Inv, "xl/drawings/_rels/drawing{0}.xml.rels", number), links.ToString(), null));
                }
                if (drawn.Count > 0)
                {
                    foreach (string path in mediaByName)
                        parts.Add(("xl/media/" + media[path].Name, null, path));
                }
                return parts;
            }

            internal string WorkbookXml()
            {
                var book = new StringBuilder();
                book.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
                book.AppendFormat(Inv, "<workbook xmlns=\"{0}\" xmlns:r=\"{1}\">", MainNs, RelNs);
                book.Append("<bookViews><workbookView activeTab=\"0\"/></bookViews>");
                book.Append("<sheets>");
                for (int number = 1; number <= Sheets.Count; number++)
                    book.AppendFormat(Inv, "<sheet name=\"{0}\" sheetId=\"{1}\" r:id=\"rId{1}\"/>", Escape(Sheets[number - 1].Name), number);
                book.Append("</sheets>");
                // Excel sorts defined names itself and repairs a book whose names are
                // out of its order, so they are written sorted: Print_Area before
                // Print_Titles, and by sheet within each.
                var names = new List<(string Name, int Index, string Value)>();
                for (int index = 0; index < Sheets.Count; index++)
                {
                    var sheet = Sheets[index];
                    string quoted = "'" + (sheet.Name ?? "").Replace("'", "''") + "'";
                    if (sheet.PrintArea)
                    {
                        var (lastRow, lastCol) = sheet.Extent();
                        names.Add(("_xlnm.Print_Area", index,
                                   string.Format(Inv, "{0}!$A$1:${1}${2}", quoted, ColumnLetter(lastCol), lastRow)));
                    }
                    if (sheet.PrintRows.HasValue)
                    {
                        var (first, last) = sheet.PrintRows.Value;
                        names.Add(("_xlnm.Print_Titles", index, string.Format(Inv, "{0}!${1}:${2}", quoted, first, last)));
                    }
                }
                if (names.Count > 0)
                {
                    book.Append("<definedNames>");
                    foreach (var (name, index, value) in names.OrderBy(n => n.Name, StringComparer.Ordinal)
                                                              .ThenBy(n => n.Index)
                                                              .ThenBy(n => n.Value, StringComparer.Ordinal))
                        book.AppendFormat(Inv, "<definedName name=\"{0}\" localSheetId=\"{1}\">{2}</definedName>", name, index, Escape(value));
                    book.Append("</definedNames>");
                }
                book.Append("</workbook>");
                return book.ToString();
            }

            internal string DrawingXml(Sheet sheet, List<(string Path, int X, int Y, int Width, int Height)> pictures)
            {
                var o = new StringBuilder();
                o.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
                o.AppendFormat(Inv, "<xdr:wsDr xmlns:xdr=\"{0}\" xmlns:a=\"{1}\">", XdrNs, ANs);
                for (int slot = 1; slot <= pictures.Count; slot++)
                {
                    var (_, x, y, width, height) = pictures[slot - 1];
                    var (col, colOff, row, rowOff) = sheet.Anchor(x, y);
                    long cx = (long)width * EmuPerPixel;
                    long cy = (long)height * EmuPerPixel;
                    o.AppendFormat(Inv,
                        "<xdr:oneCellAnchor><xdr:from><xdr:col>{0}</xdr:col>" +
                        "<xdr:colOff>{1}</xdr:colOff><xdr:row>{2}</xdr:row>" +
                        "<xdr:rowOff>{3}</xdr:rowOff></xdr:from>" +
                        "<xdr:ext cx=\"{4}\" cy=\"{5}\"/>" +
                        "<xdr:pic><xdr:nvPicPr><xdr:cNvPr id=\"{6}\" name=\"Logo {7}\"/>" +
                        "<xdr:cNvPicPr><a:picLocks noChangeAspect=\"1\"/></xdr:cNvPicPr>" +
                        "</xdr:nvPicPr><xdr:blipFill><a:blip xmlns:r=\"{8}\" " +
                        "r:embed=\"rId{7}\"/><a:stretch><a:fillRect/></a:stretch>" +
                        "</xdr:blipFill><xdr:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/>" +
                        "<a:ext cx=\"{4}\" cy=\"{5}\"/></a:xfrm><a:prstGeom prst=\"rect\">" +
                        "<a:avLst/></a:prstGeom></xdr:spPr></xdr:pic>" +
                        "<xdr:clientData/></xdr:oneCellAnchor>",
                        col, (long)colOff * EmuPerPixel, row, (long)rowOff * EmuPerPixel, cx, cy, slot + 1, slot, RelNs);
                }
                o.Append("</xdr:wsDr>");
                return o.ToString();
            }

            /// <summary>Write the workbook. (ok, message).</summary>
            public (bool Ok, string Message) Save(string path)
            {
                var parts = Parts();
                try
                {
                    string folder = Path.GetDirectoryName(path);
                    if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder))
                        Directory.CreateDirectory(folder);
                }
                catch (Exception err)
                {
                    return (false, "The folder could not be made: " + err.Message);
                }
                // The Python tried .NET first and its own zipfile second, keeping both
                // errors. Only the .NET route exists here; its error is reported the same way.
                var errors = new List<string>();
                try
                {
                    SaveDotnet(path, parts);
                    return (true, "");
                }
                catch (Exception err)
                {
                    errors.Add(".NET: " + err.Message);
                }
                return (false, errors.Count > 0 ? string.Join("; ", errors) : "no zip writer available");
            }
        }

        /// <summary>Through System.IO.Compression.</summary>
        internal static void SaveDotnet(string path, List<(string Name, string Text, string File)> parts)
        {
            var encoding = new UTF8Encoding(false);          // no byte order mark
            if (File.Exists(path))
                File.Delete(path);
            using (var stream = new FileStream(path, FileMode.Create))
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Create))
            {
                foreach (var (name, text, file) in parts)
                {
                    byte[] data = file != null ? File.ReadAllBytes(file) : encoding.GetBytes(text ?? "");
                    var entry = archive.CreateEntry(name);
                    using (var output = entry.Open())
                        output.Write(data, 0, data.Length);
                }
            }
        }
    }
}
