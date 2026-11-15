using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ExcelForRevit
{
    // Office Open XML read and write with no external dependency. Port of xlsx_io.py.
    //
    // A .xlsx is a zip of XML parts. Writing one by hand is a few hundred lines and costs
    // nothing at runtime: Excel interop needs Excel installed and leaves orphaned processes,
    // and CSV loses the colour, the widths and the header rows that make the export worth
    // having. Everything here is deliberately ignorant of Revit: it moves rows of strings
    // and a style id per cell, and nothing else.
    //
    // (Self-contained on purpose: Excel for Revit does not depend on the Pro Sheets writer.)

    /// <summary>One cell of a row: the text, the style id and whether it is written as a number.</summary>
    public class SheetCell
    {
        public string Text;
        public int Style;
        public bool Numeric;

        public SheetCell(string text, int style, bool numeric = false)
        {
            Text = text;
            Style = style;
            Numeric = numeric;
        }
    }

    /// <summary>xlsx_io module functions.</summary>
    public static class XlsxIo
    {
        internal static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        // =========================================================== zip access ==

        /// <summary>Collects named parts and writes them as one zip.</summary>
        public class ZipOut
        {
            public List<KeyValuePair<string, string>> Parts = new List<KeyValuePair<string, string>>();

            public void Add(string name, string text)
            {
                Parts.Add(new KeyValuePair<string, string>(name, text));
            }

            public void Save(string path)
            {
                string folder = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder))
                    Directory.CreateDirectory(folder);

                var encoding = new UTF8Encoding(false);          // no byte order mark
                byte[] bytes;
                using (var stream = new MemoryStream())
                {
                    using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, true))
                    {
                        foreach (var part in Parts)
                        {
                            var entry = archive.CreateEntry(part.Key, CompressionLevel.Optimal);
                            byte[] data = encoding.GetBytes(part.Value ?? "");
                            using (var writer = entry.Open())
                                writer.Write(data, 0, data.Length);
                        }
                    }
                    bytes = stream.ToArray();
                }
                // written in one go, so a failure part way never leaves half a workbook behind
                File.WriteAllBytes(path, bytes);
            }
        }

        // The file may be open in Excel: that holds it for reading by others but not for writing,
        // so share ReadWrite or the read fails with a sharing violation.
        internal static byte[] ReadAllBytesShared(string path)
        {
            using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var ms = new MemoryStream())
            {
                fs.CopyTo(ms);
                return ms.ToArray();
            }
        }

        /// <summary>{name: text} for the parts asked for that exist.</summary>
        public static Dictionary<string, string> ZipRead(string path, ICollection<string> wanted)
        {
            var result = new Dictionary<string, string>(StringComparer.Ordinal);
            byte[] data = ReadAllBytesShared(path);
            using (var stream = new MemoryStream(data))
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Read))
            {
                foreach (var entry in archive.Entries)
                {
                    string name = entry.FullName.Replace('\\', '/').TrimStart('/');
                    if (!wanted.Contains(name))
                        continue;
                    using (var reader = new StreamReader(entry.Open(), Encoding.UTF8))
                        result[name] = reader.ReadToEnd();
                }
            }
            return result;
        }

        // ================================================================= utils ==

        static readonly Regex UnderscoreEscape = new Regex("_(?=x[0-9A-Fa-f]{4}_)", RegexOptions.Compiled);

        /// <summary>XML-escape, and drop the control characters Excel refuses to open.</summary>
        public static string Esc(string text)
        {
            if (text == null)
                return "";
            var sb = new StringBuilder(text.Length + 16);
            foreach (char ch in text)
            {
                // the control characters Excel refuses to open are dropped
                if (!(ch == 9 || ch == 10 || ch == 13 || ch >= 32))
                    continue;
                switch (ch)
                {
                    case '&': sb.Append("&amp;"); break;
                    case '<': sb.Append("&lt;"); break;
                    case '>': sb.Append("&gt;"); break;
                    case '"': sb.Append("&quot;"); break;
                    default: sb.Append(ch); break;
                }
            }
            return sb.ToString();
        }

        /// <summary>
        /// Esc for the text of a cell. A literal "_x000D_" in the data would be read by Excel (and by
        /// ReadSheet) as an escaped character, so its underscore is escaped the way Excel does it.
        /// </summary>
        internal static string EscCell(string text)
        {
            return Esc(UnderscoreEscape.Replace(text ?? "", "_x005F_"));
        }

        /// <summary>0 -> A, 25 -> Z, 26 -> AA (zero based).</summary>
        public static string ColLetter(int index)
        {
            int n = index;
            string outText = "";
            while (true)
            {
                outText = (char)('A' + (((n % 26) + 26) % 26)) + outText;
                n = (int)Math.Floor(n / 26.0) - 1;
                if (n < 0)
                    break;
            }
            return outText;
        }

        /// <summary>A -> 0, AA -> 26 (zero based).</summary>
        public static int ColIndex(string letters)
        {
            int n = 0;
            foreach (char raw in (letters ?? "").ToUpperInvariant())
            {
                if (raw >= 'A' && raw <= 'Z')
                    n = n * 26 + (raw - 'A' + 1);
            }
            return n - 1;
        }

        static readonly Regex NumericRe = new Regex(@"^-?[0-9]+(\.[0-9]+)?$", RegexOptions.Compiled);

        public static bool LooksNumeric(string text)
        {
            return !string.IsNullOrEmpty(text) && NumericRe.IsMatch(text.Trim());
        }

        static readonly Regex SheetBad = new Regex(@"[:\\/?*\[\]]", RegexOptions.Compiled);

        /// <summary>Excel refuses : \ / ? * [ ] and anything over 31 characters.</summary>
        public static string SheetNameSafe(string name)
        {
            string text = SheetBad.Replace(string.IsNullOrEmpty(name) ? "Sheet1" : name, "-");
            if (text.Length > 31)
                text = text.Substring(0, 31);
            return text.Length > 0 ? text : "Sheet1";
        }

        /// <summary>Python's '{0}'.format(float): always a decimal point.</summary>
        internal static string PyFloat(double value)
        {
            string text = value.ToString("R", Inv);
            if (text.IndexOf('E') < 0 && text.IndexOf('.') < 0 && text.IndexOf("Infinity", StringComparison.Ordinal) < 0 && text != "NaN")
                text += ".0";
            return text;
        }

        // ================================================================ reading ==

        static readonly Regex CellRe = new Regex(@"<c\s+([^>]*?)(/>|>(.*?)</c>)", RegexOptions.Singleline | RegexOptions.Compiled);
        static readonly Regex RowRe = new Regex(@"<row\s+[^>]*?\br=""(\d+)""[^>]*?(/>|>(.*?)</row>)", RegexOptions.Singleline | RegexOptions.Compiled);
        static readonly Regex AttrRe = new Regex(@"([\w:]+)=""([^""]*)""", RegexOptions.Compiled);
        // <t/> and <v/> (empty, self-closing) must not swallow the text of the next element
        static readonly Regex TRe = new Regex(@"<t(?:\s[^>]*)?>(.*?)</t>", RegexOptions.Singleline | RegexOptions.Compiled);
        static readonly Regex VRe = new Regex(@"<v(?:\s[^>]*)?>(.*?)</v>", RegexOptions.Singleline | RegexOptions.Compiled);
        static readonly Regex SiRe = new Regex(@"<si\b[^>]*?(?:/>|>(.*?)</si>)", RegexOptions.Singleline | RegexOptions.Compiled);
        // phonetic (furigana) runs carry their own <t>; they are not part of the cell's text
        static readonly Regex PhoneticRe = new Regex(@"<rPh\b[^>]*?>.*?</rPh>", RegexOptions.Singleline | RegexOptions.Compiled);
        static readonly Regex EntityRe = new Regex(@"&(#[xX][0-9A-Fa-f]+|#[0-9]+|lt|gt|quot|apos|amp);", RegexOptions.Compiled);
        static readonly Regex XEscapeRe = new Regex(@"_x([0-9A-Fa-f]{4})_", RegexOptions.Compiled);

        /// <summary>
        /// The XML entities, numeric character references, and Excel's _xHHHH_ escapes
        /// (Excel writes a carriage return in a cell as _x000D_).
        /// </summary>
        public static string Unesc(string text)
        {
            if (string.IsNullOrEmpty(text))
                return text ?? "";
            if (text.IndexOf('&') >= 0)
            {
                text = EntityRe.Replace(text, m =>
                {
                    string body = m.Groups[1].Value;
                    switch (body)
                    {
                        case "lt": return "<";
                        case "gt": return ">";
                        case "quot": return "\"";
                        case "apos": return "'";
                        case "amp": return "&";
                    }
                    try
                    {
                        int code = (body[1] == 'x' || body[1] == 'X')
                            ? int.Parse(body.Substring(2), NumberStyles.HexNumber, Inv)
                            : int.Parse(body.Substring(1), NumberStyles.Integer, Inv);
                        return (code >= 0 && code <= 0xFFFF) ? ((char)code).ToString() : char.ConvertFromUtf32(code);
                    }
                    catch (Exception)
                    {
                        return m.Value;
                    }
                });
            }
            return text;
        }

        static string UnescString(string text)
        {
            text = Unesc(text);
            if (text.IndexOf("_x", StringComparison.Ordinal) >= 0)
                text = XEscapeRe.Replace(text, m => ((char)int.Parse(m.Groups[1].Value, NumberStyles.HexNumber, Inv)).ToString());
            return text;
        }

        static string JoinT(string payload)
        {
            var sb = new StringBuilder();
            foreach (Match m in TRe.Matches(PhoneticRe.Replace(payload, "")))
                sb.Append(m.Groups[1].Value);
            return sb.ToString();
        }

        static Dictionary<string, string> Attrs(string text)
        {
            var d = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (Match m in AttrRe.Matches(text))
                d[m.Groups[1].Value] = m.Groups[2].Value;
            return d;
        }

        /// <summary>(sheet name, part name) of every worksheet, in the workbook's own order.</summary>
        public static List<KeyValuePair<string, string>> SheetParts(string path)
        {
            var found = new List<KeyValuePair<string, string>>();
            var parts = ZipRead(path, new[] { "xl/workbook.xml", "xl/_rels/workbook.xml.rels" });
            string book, rels;
            if (!parts.TryGetValue("xl/workbook.xml", out book) || !parts.TryGetValue("xl/_rels/workbook.xml.rels", out rels))
                return found;
            var targets = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (Match m in Regex.Matches(rels, @"<Relationship\b([^>]*?)/?>", RegexOptions.Singleline))
            {
                var a = Attrs(m.Groups[1].Value);
                string id, target;
                if (a.TryGetValue("Id", out id) && a.TryGetValue("Target", out target))
                    targets[id] = target;
            }
            foreach (Match m in Regex.Matches(book, @"<sheet\b([^>]*?)/?>", RegexOptions.Singleline))
            {
                var a = Attrs(m.Groups[1].Value);
                string name = "", rid = null, target;
                a.TryGetValue("name", out name);
                foreach (var kv in a)
                {
                    if (kv.Key == "id" || kv.Key.EndsWith(":id", StringComparison.Ordinal))
                        rid = kv.Value;
                }
                if (rid == null || !targets.TryGetValue(rid, out target))
                    continue;
                string part = target.StartsWith("/", StringComparison.Ordinal) ? target.TrimStart('/') : "xl/" + target;
                found.Add(new KeyValuePair<string, string>(Unesc(name ?? ""), part));
            }
            return found;
        }

        /// <summary>
        /// Rows of strings from the worksheet at <paramref name="sheetIndex"/> (0 is the first sheet).
        /// Sparse cells are filled with "". The part read is xl/worksheets/sheet{N}.xml, which is what
        /// the export writes and what Excel keeps when a tab is dragged; if that part is absent the
        /// workbook's own sheet list is used instead.
        /// </summary>
        public static List<List<string>> ReadSheet(string path, int sheetIndex = 0)
        {
            string partName = "xl/worksheets/sheet" + (sheetIndex + 1).ToString(Inv) + ".xml";
            var parts = ZipRead(path, new[] { partName, "xl/sharedStrings.xml" });
            string body;
            if (!parts.TryGetValue(partName, out body))
            {
                var listed = SheetParts(path);
                if (sheetIndex >= 0 && sheetIndex < listed.Count)
                    return ReadPart(path, listed[sheetIndex].Value);
                throw new InvalidDataException("That file does not contain a readable worksheet.");
            }
            string sharedXml;
            parts.TryGetValue("xl/sharedStrings.xml", out sharedXml);
            return ParseSheet(body, sharedXml);
        }

        /// <summary>Rows of strings from the worksheet with this tab name (case-insensitive).</summary>
        public static List<List<string>> ReadSheet(string path, string sheetName)
        {
            foreach (var one in SheetParts(path))
            {
                if (string.Equals(one.Key, sheetName, StringComparison.OrdinalIgnoreCase))
                    return ReadPart(path, one.Value);
            }
            throw new InvalidDataException("That file does not contain a worksheet named \"" + sheetName + "\".");
        }

        static List<List<string>> ReadPart(string path, string partName)
        {
            var parts = ZipRead(path, new[] { partName, "xl/sharedStrings.xml" });
            string body;
            if (!parts.TryGetValue(partName, out body))
                throw new InvalidDataException("That file does not contain a readable worksheet.");
            string sharedXml;
            parts.TryGetValue("xl/sharedStrings.xml", out sharedXml);
            return ParseSheet(body, sharedXml);
        }

        internal static List<List<string>> ParseSheet(string body, string sharedXml)
        {
            var shared = new List<string>();
            if (!string.IsNullOrEmpty(sharedXml))
            {
                foreach (Match m in SiRe.Matches(sharedXml))
                    shared.Add(UnescString(JoinT(m.Groups[1].Value)));
            }

            var rows = new Dictionary<int, Dictionary<int, string>>();
            int widest = 0;
            int maxRow = -1;
            foreach (Match match in RowRe.Matches(body))
            {
                int r = int.Parse(match.Groups[1].Value, Inv) - 1;
                string inner = match.Groups[3].Success ? match.Groups[3].Value : "";
                var cells = new Dictionary<int, string>();
                int next = 0;
                foreach (Match cm in CellRe.Matches(inner))
                {
                    var attrs = Attrs(cm.Groups[1].Value);
                    string reference;
                    attrs.TryGetValue("r", out reference);
                    int c;
                    var letters = Regex.Match(reference ?? "", "^([A-Za-z]+)");
                    if (letters.Success)
                        c = ColIndex(letters.Groups[1].Value);
                    else
                        c = next;              // no reference: the cell follows the one before
                    next = c + 1;
                    string payload = cm.Groups[3].Success ? cm.Groups[3].Value : "";
                    string kind;
                    attrs.TryGetValue("t", out kind);
                    string value;
                    if (kind == "inlineStr")
                    {
                        value = UnescString(JoinT(payload));
                    }
                    else if (kind == "s")
                    {
                        var hit = VRe.Match(payload);
                        int idx = -1;
                        if (hit.Success)
                        {
                            int parsed;
                            if (int.TryParse(hit.Groups[1].Value.Trim(), NumberStyles.Integer, Inv, out parsed))
                                idx = parsed;
                        }
                        value = (idx >= 0 && idx < shared.Count) ? shared[idx] : "";
                    }
                    else if (kind == "str")
                    {
                        var sb = new StringBuilder();
                        foreach (Match vm in VRe.Matches(payload))
                            sb.Append(vm.Groups[1].Value);
                        value = UnescString(sb.ToString());
                    }
                    else
                    {
                        var hit = VRe.Match(payload);
                        value = hit.Success ? Unesc(hit.Groups[1].Value) : "";
                    }
                    cells[c] = value;
                    widest = Math.Max(widest, c + 1);
                }
                rows[r] = cells;
                maxRow = Math.Max(maxRow, r);
            }

            var table = new List<List<string>>();
            if (rows.Count == 0)
                return table;
            for (int r = 0; r <= maxRow; r++)
            {
                Dictionary<int, string> cells;
                if (!rows.TryGetValue(r, out cells))
                    cells = null;
                var line = new List<string>(widest);
                for (int c = 0; c < widest; c++)
                {
                    string v;
                    line.Add(cells != null && cells.TryGetValue(c, out v) ? v : "");
                }
                table.Add(line);
            }
            return table;
        }
    }

    // ================================================================= styling ==

    /// <summary>Builds styles.xml. Each Add-style call returns the index cells refer to.</summary>
    public class Styles
    {
        public List<(string Colour, double Size, bool Bold, bool Italic, string Name)> Fonts =
            new List<(string, double, bool, bool, string)>();
        public List<(string Colour, string Pattern)> Fills = new List<(string, string)>();
        public List<(bool On, string Colour)> Borders = new List<(bool, string)>();
        public List<(int Font, int Fill, int Border, bool Wrap, string Align, string VAlign, int Indent)> Xfs =
            new List<(int, int, int, bool, string, string, int)>();

        public Styles()
        {
            // index 0 of each is the default Excel expects to be present
            Font("000000", 11, false);
            Fill(null);
            Fill(null, "gray125");
            Border(false);
            Xf(0, 0, 0);
        }

        static int Intern<T>(List<T> table, T key)
        {
            int found = table.IndexOf(key);
            if (found >= 0)
                return found;
            table.Add(key);
            return table.Count - 1;
        }

        public int Font(string colour, double size = 11, bool bold = false, bool italic = false, string name = "Calibri")
        {
            return Intern(Fonts, (colour, size, bold, italic, name));
        }

        public int Fill(string colour, string pattern = "solid")
        {
            return Intern(Fills, (colour, pattern));
        }

        public int Border(bool on, string colour = "D0D0D0")
        {
            return Intern(Borders, (on, colour));
        }

        public int Xf(int font, int fill, int border, bool wrap = false, string align = null,
                      string valign = "center", int indent = 0)
        {
            return Intern(Xfs, (font, fill, border, wrap, align, valign, indent));
        }

        /// <summary>One call for the common case: returns a style id for a cell.</summary>
        public int Cell(string colour = null, string bg = null, double size = 11, bool bold = false,
                        bool italic = false, bool border = true, bool wrap = false, string align = null,
                        string valign = "center")
        {
            return Xf(Font(!string.IsNullOrEmpty(colour) ? colour : "000000", size, bold, italic),
                      !string.IsNullOrEmpty(bg) ? Fill(bg) : 0,
                      Border(border),
                      wrap, align, valign);
        }

        public string Xml()
        {
            var inv = XlsxIo.Inv;
            var parts = new StringBuilder();
            parts.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
            parts.Append("<styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">");

            parts.AppendFormat(inv, "<fonts count=\"{0}\">", Fonts.Count);
            foreach (var f in Fonts)
            {
                // <b/> precedes <i/> precedes <sz/>
                parts.Append("<font>");
                if (f.Bold) parts.Append("<b/>");
                if (f.Italic) parts.Append("<i/>");
                parts.AppendFormat(inv, "<sz val=\"{0}\"/><color rgb=\"FF{1}\"/><name val=\"{2}\"/>",
                    f.Size.ToString("R", inv), f.Colour, XlsxIo.Esc(f.Name));
                parts.Append("</font>");
            }
            parts.Append("</fonts>");

            parts.AppendFormat(inv, "<fills count=\"{0}\">", Fills.Count);
            foreach (var f in Fills)
            {
                if (f.Colour == null)
                    parts.AppendFormat(inv, "<fill><patternFill patternType=\"{0}\"/></fill>",
                        f.Pattern == "gray125" ? "gray125" : "none");
                else
                    parts.AppendFormat(inv, "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FF{0}\"/>" +
                                            "<bgColor indexed=\"64\"/></patternFill></fill>", f.Colour);
            }
            parts.Append("</fills>");

            parts.AppendFormat(inv, "<borders count=\"{0}\">", Borders.Count);
            foreach (var b in Borders)
            {
                if (!b.On)
                {
                    parts.Append("<border><left/><right/><top/><bottom/><diagonal/></border>");
                }
                else
                {
                    parts.Append("<border>");
                    foreach (string edge in new[] { "left", "right", "top", "bottom" })
                        parts.AppendFormat(inv, "<{0} style=\"thin\"><color rgb=\"FF{1}\"/></{0}>", edge, b.Colour);
                    parts.Append("<diagonal/></border>");
                }
            }
            parts.Append("</borders>");

            parts.Append("<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>");
            parts.AppendFormat(inv, "<cellXfs count=\"{0}\">", Xfs.Count);
            foreach (var x in Xfs)
            {
                string attrs = string.Format(inv,
                    "numFmtId=\"0\" fontId=\"{0}\" fillId=\"{1}\" borderId=\"{2}\" applyFont=\"1\" applyFill=\"1\" applyBorder=\"1\"",
                    x.Font, x.Fill, x.Border);
                var bits = new List<string>();
                if (x.Wrap) bits.Add("wrapText=\"1\"");
                if (!string.IsNullOrEmpty(x.Align)) bits.Add("horizontal=\"" + x.Align + "\"");
                if (!string.IsNullOrEmpty(x.VAlign)) bits.Add("vertical=\"" + x.VAlign + "\"");
                if (x.Indent != 0) bits.Add("indent=\"" + x.Indent.ToString(inv) + "\"");
                if (bits.Count > 0)
                    parts.AppendFormat(inv, "<xf {0} applyAlignment=\"1\"><alignment {1}/></xf>", attrs, string.Join(" ", bits));
                else
                    parts.AppendFormat(inv, "<xf {0}/>", attrs);
            }
            parts.Append("</cellXfs>");
            parts.Append("<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>");
            parts.Append("</styleSheet>");
            return parts.ToString();
        }
    }

    // ================================================================= writing ==

    /// <summary>Rows of cells, plus layout.</summary>
    public class Sheet
    {
        public string Name;
        public List<List<SheetCell>> Rows = new List<List<SheetCell>>();
        public Dictionary<int, double> Widths = new Dictionary<int, double>();
        public (int Rows, int Cols)? Freeze;                              // rows above, columns left
        public bool Selected;
        public (int FirstRow, int FirstCol, int LastRow, int LastCol)? Autofilter;
        public List<(int Row0, int Col0, int Row1, int Col1)> Merges = new List<(int, int, int, int)>();
        public Dictionary<int, double> RowHeights = new Dictionary<int, double>();

        public Sheet(string name)
        {
            Name = name;
        }

        /// <summary>Append a row (a null entry is an absent cell). Returns the row count (1 based row number).</summary>
        public int AddRow(List<SheetCell> cells, double height = 0)
        {
            Rows.Add(cells ?? new List<SheetCell>());
            if (height != 0)
                RowHeights[Rows.Count] = height;
            return Rows.Count;
        }

        public void Width(int colIndex, double value)
        {
            Widths[colIndex] = value;
        }

        public string Xml()
        {
            var inv = XlsxIo.Inv;
            // OOXML fixes the order of these elements and Excel enforces it, even though lenient
            // readers do not: sheetPr, dimension, sheetViews, sheetFormatPr, cols, sheetData, ...,
            // autoFilter, ..., mergeCells. Building the string in that order is the whole trick:
            // inserting sheetViews later put it after <cols> and every file needed repairing.
            var parts = new StringBuilder();
            parts.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
            parts.Append("<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">");

            int lastRow = Rows.Count;
            int lastCol = 0;
            foreach (var cells in Rows)
                lastCol = Math.Max(lastCol, cells.Count);
            if (lastRow > 0 && lastCol > 0)
                parts.AppendFormat(inv, "<dimension ref=\"A1:{0}{1}\"/>", XlsxIo.ColLetter(lastCol - 1), lastRow);

            if (Freeze.HasValue)
            {
                int rows = Freeze.Value.Rows, cols = Freeze.Value.Cols;
                string topLeft = XlsxIo.ColLetter(cols) + (rows + 1).ToString(inv);
                // the pane that stays live is the one the split leaves: bottom right when both
                // rows and columns are frozen, bottom left for rows only, top right for columns only
                string active = (rows != 0 && cols != 0) ? "bottomRight" : (rows != 0 ? "bottomLeft" : "topRight");
                var pane = new StringBuilder("<pane");
                if (cols != 0)
                    pane.AppendFormat(inv, " xSplit=\"{0}\"", cols);
                if (rows != 0)
                    pane.AppendFormat(inv, " ySplit=\"{0}\"", rows);
                pane.AppendFormat(inv, " topLeftCell=\"{0}\" activePane=\"{1}\" state=\"frozen\"/>", topLeft, active);
                parts.AppendFormat(inv, "<sheetViews><sheetView tabSelected=\"{0}\" workbookViewId=\"0\">{1}</sheetView></sheetViews>",
                    Selected ? 1 : 0, pane);
            }
            else
            {
                parts.AppendFormat(inv, "<sheetViews><sheetView tabSelected=\"{0}\" workbookViewId=\"0\"/></sheetViews>",
                    Selected ? 1 : 0);
            }

            parts.Append("<sheetFormatPr defaultRowHeight=\"15\"/>");

            if (Widths.Count > 0)
            {
                parts.Append("<cols>");
                var keys = new List<int>(Widths.Keys);
                keys.Sort();
                foreach (int idx in keys)
                    parts.AppendFormat(inv, "<col min=\"{0}\" max=\"{0}\" width=\"{1}\" customWidth=\"1\"/>",
                        idx + 1, XlsxIo.PyFloat(Math.Round(Widths[idx], 2, MidpointRounding.AwayFromZero)));
                parts.Append("</cols>");
            }

            parts.Append("<sheetData>");
            for (int r = 0; r < Rows.Count; r++)
            {
                double height;
                if (RowHeights.TryGetValue(r + 1, out height) && height != 0)
                    parts.AppendFormat(inv, "<row r=\"{0}\" ht=\"{1}\" customHeight=\"1\">", r + 1, height.ToString("R", inv));
                else
                    parts.AppendFormat(inv, "<row r=\"{0}\">", r + 1);
                var cells = Rows[r];
                for (int c = 0; c < cells.Count; c++)
                {
                    var cell = cells[c];
                    if (cell == null)
                        continue;
                    string text = cell.Text;
                    string reference = XlsxIo.ColLetter(c) + (r + 1).ToString(inv);
                    string attrs = cell.Style != 0 ? " s=\"" + cell.Style.ToString(inv) + "\"" : "";
                    if (string.IsNullOrEmpty(text))
                    {
                        parts.AppendFormat(inv, "<c r=\"{0}\"{1}/>", reference, attrs);
                    }
                    else if (cell.Numeric && XlsxIo.LooksNumeric(text))
                    {
                        parts.AppendFormat(inv, "<c r=\"{0}\"{1}><v>{2}</v></c>", reference, attrs, XlsxIo.Esc(text.Trim()));
                    }
                    else
                    {
                        // inline strings: no shared-string table to keep in step, which
                        // matters more than the file size here
                        parts.AppendFormat(inv, "<c r=\"{0}\"{1} t=\"inlineStr\"><is><t xml:space=\"preserve\">{2}</t></is></c>",
                            reference, attrs, XlsxIo.EscCell(text));
                    }
                }
                parts.Append("</row>");
            }
            parts.Append("</sheetData>");

            if (Autofilter.HasValue && Autofilter.Value.LastRow > Autofilter.Value.FirstRow)
            {
                var a = Autofilter.Value;
                parts.AppendFormat(inv, "<autoFilter ref=\"{0}{1}:{2}{3}\"/>",
                    XlsxIo.ColLetter(a.FirstCol), a.FirstRow + 1, XlsxIo.ColLetter(a.LastCol), a.LastRow + 1);
            }

            // a single-cell merge is corrupt to Excel
            var merges = new List<(int Row0, int Col0, int Row1, int Col1)>();
            foreach (var m in Merges)
            {
                if (!(m.Row0 == m.Row1 && m.Col0 == m.Col1))
                    merges.Add(m);
            }
            if (merges.Count > 0)
            {
                parts.AppendFormat(inv, "<mergeCells count=\"{0}\">", merges.Count);
                foreach (var m in merges)
                    parts.AppendFormat(inv, "<mergeCell ref=\"{0}{1}:{2}{3}\"/>",
                        XlsxIo.ColLetter(m.Col0), m.Row0 + 1, XlsxIo.ColLetter(m.Col1), m.Row1 + 1);
                parts.Append("</mergeCells>");
            }

            parts.Append("</worksheet>");
            return parts.ToString();
        }
    }

    public class Workbook
    {
        public Styles Styles = new Styles();
        public List<Sheet> Sheets = new List<Sheet>();

        /// <summary>Add a sheet; the name is made safe and unique.</summary>
        public Sheet Sheet(string name)
        {
            // duplicate tab names make a workbook Excel refuses to open, and two
            // long names can collide after the 31-character truncation
            string wanted = XlsxIo.SheetNameSafe(name);
            var taken = new HashSet<string>(StringComparer.Ordinal);
            foreach (var x in Sheets)
                taken.Add(x.Name.ToLowerInvariant());
            if (taken.Contains(wanted.ToLowerInvariant()))
            {
                int n = 2;
                while (true)
                {
                    string suffix = " (" + n.ToString(XlsxIo.Inv) + ")";
                    string head = wanted.Length > 31 - suffix.Length ? wanted.Substring(0, 31 - suffix.Length) : wanted;
                    string candidate = head + suffix;
                    if (!taken.Contains(candidate.ToLowerInvariant()))
                    {
                        wanted = candidate;
                        break;
                    }
                    n++;
                }
            }
            var s = new Sheet(wanted);
            s.Selected = Sheets.Count == 0;      // only the first tab opens selected
            Sheets.Add(s);
            return s;
        }

        public void Save(string path)
        {
            var z = new XlsxIo.ZipOut();
            z.Add("[Content_Types].xml", ContentTypes());
            z.Add("_rels/.rels",
                  "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                  "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" +
                  "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" " +
                  "Target=\"xl/workbook.xml\"/></Relationships>");
            z.Add("xl/workbook.xml", WorkbookXml());
            z.Add("xl/_rels/workbook.xml.rels", WorkbookRels());
            z.Add("xl/styles.xml", Styles.Xml());
            for (int i = 0; i < Sheets.Count; i++)
                z.Add("xl/worksheets/sheet" + (i + 1).ToString(XlsxIo.Inv) + ".xml", Sheets[i].Xml());
            z.Save(path);
        }

        string ContentTypes()
        {
            var inv = XlsxIo.Inv;
            var parts = new StringBuilder();
            parts.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
            parts.Append("<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">");
            parts.Append("<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>");
            parts.Append("<Default Extension=\"xml\" ContentType=\"application/xml\"/>");
            parts.Append("<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>");
            parts.Append("<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>");
            for (int i = 0; i < Sheets.Count; i++)
                parts.AppendFormat(inv, "<Override PartName=\"/xl/worksheets/sheet{0}.xml\" " +
                                        "ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>", i + 1);
            parts.Append("</Types>");
            return parts.ToString();
        }

        string WorkbookXml()
        {
            var inv = XlsxIo.Inv;
            var parts = new StringBuilder();
            parts.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
            parts.Append("<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" " +
                         "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets>");
            for (int i = 0; i < Sheets.Count; i++)
                parts.AppendFormat(inv, "<sheet name=\"{0}\" sheetId=\"{1}\" r:id=\"rId{1}\"/>",
                    XlsxIo.Esc(XlsxIo.SheetNameSafe(Sheets[i].Name)), i + 1);
            parts.Append("</sheets></workbook>");
            return parts.ToString();
        }

        string WorkbookRels()
        {
            var inv = XlsxIo.Inv;
            var parts = new StringBuilder();
            parts.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
            parts.Append("<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">");
            for (int i = 0; i < Sheets.Count; i++)
                parts.AppendFormat(inv, "<Relationship Id=\"rId{0}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" " +
                                        "Target=\"worksheets/sheet{0}.xml\"/>", i + 1);
            parts.AppendFormat(inv, "<Relationship Id=\"rId{0}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" " +
                                    "Target=\"styles.xml\"/>", Sheets.Count + 1);
            parts.Append("</Relationships>");
            return parts.ToString();
        }
    }
}
