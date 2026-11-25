using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Xml;

namespace RevoBIM.Tools.WorksetManagement
{
    /// <summary>
    /// The spreadsheet: Office Open XML written straight into a zip and read back the same way, no Excel interop.
    /// Reading handles shared strings, inline strings and numbers, because Excel rewrites the file its own way once
    /// it has been saved. Port of wsm_xlsx.py.
    /// </summary>
    public static class WsmXlsx
    {
        public const int StylePlain = 0, StyleHeader = 1, StyleExisting = 2, StyleNew = 3, StyleLocked = 4, StyleNote = 5;

        public class Cell
        {
            public string Text; public int Style;
            public Cell(string text, int style) { Text = text; Style = style; }
        }

        private static string Esc(string text)
        {
            if (text == null) return "";
            string o = text.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;");
            var sb = new StringBuilder();
            foreach (char c in o) if (c == 9 || c == 10 || c == 13 || c >= 32) sb.Append(c);
            return sb.ToString();
        }

        public static string ColLetter(int index)
        {
            string letters = "";
            while (index > 0)
            {
                int rem = (index - 1) % 26;
                index = (index - 1) / 26;
                letters = (char)(65 + rem) + letters;
            }
            return letters;
        }

        private const string ContentTypes = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">\n" +
            "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>\n<Default Extension=\"xml\" ContentType=\"application/xml\"/>\n" +
            "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>\n" +
            "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>\n" +
            "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>\n</Types>";

        private const string RootRels = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">\n" +
            "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/>\n</Relationships>";

        private const string WorkbookRels = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">\n" +
            "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/>\n" +
            "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>\n</Relationships>";

        private static string WorkbookXml(string sheet)
        {
            return "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" " +
                   "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">\n<sheets><sheet name=\"" + sheet + "\" sheetId=\"1\" r:id=\"rId1\"/></sheets>\n</workbook>";
        }

        private const string Styles = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">\n" +
            "<fonts count=\"5\">\n<font><sz val=\"11\"/><name val=\"Calibri\"/></font>\n<font><b/><sz val=\"11\"/><color rgb=\"FFFFFFFF\"/><name val=\"Calibri\"/></font>\n" +
            "<font><b/><sz val=\"11\"/><color rgb=\"FF7A3E00\"/><name val=\"Calibri\"/></font>\n<font><b/><sz val=\"11\"/><color rgb=\"FF14532D\"/><name val=\"Calibri\"/></font>\n" +
            "<font><i/><sz val=\"10\"/><color rgb=\"FF6B6B70\"/><name val=\"Calibri\"/></font>\n</fonts>\n<fills count=\"6\">\n<fill><patternFill patternType=\"none\"/></fill>\n" +
            "<fill><patternFill patternType=\"gray125\"/></fill>\n<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FF232326\"/><bgColor indexed=\"64\"/></patternFill></fill>\n" +
            "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FFF6C68B\"/><bgColor indexed=\"64\"/></patternFill></fill>\n" +
            "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FFA9E0BC\"/><bgColor indexed=\"64\"/></patternFill></fill>\n" +
            "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FFEDEDEF\"/><bgColor indexed=\"64\"/></patternFill></fill>\n</fills>\n<borders count=\"2\">\n" +
            "<border><left/><right/><top/><bottom/><diagonal/></border>\n<border><left style=\"thin\"><color rgb=\"FFB0B0B4\"/></left><right style=\"thin\"><color rgb=\"FFB0B0B4\"/></right>" +
            "<top style=\"thin\"><color rgb=\"FFB0B0B4\"/></top><bottom style=\"thin\"><color rgb=\"FFB0B0B4\"/></bottom><diagonal/></border>\n</borders>\n" +
            "<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>\n<cellXfs count=\"6\">\n" +
            "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyAlignment=\"1\"><alignment vertical=\"center\"/></xf>\n" +
            "<xf numFmtId=\"0\" fontId=\"1\" fillId=\"2\" borderId=\"1\" xfId=\"0\" applyFont=\"1\" applyFill=\"1\" applyBorder=\"1\" applyAlignment=\"1\"><alignment vertical=\"center\"/></xf>\n" +
            "<xf numFmtId=\"0\" fontId=\"2\" fillId=\"3\" borderId=\"1\" xfId=\"0\" applyFont=\"1\" applyFill=\"1\" applyBorder=\"1\" applyAlignment=\"1\"><alignment vertical=\"center\"/></xf>\n" +
            "<xf numFmtId=\"0\" fontId=\"3\" fillId=\"4\" borderId=\"1\" xfId=\"0\" applyFont=\"1\" applyFill=\"1\" applyBorder=\"1\" applyAlignment=\"1\"><alignment vertical=\"center\"/></xf>\n" +
            "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"5\" borderId=\"1\" xfId=\"0\" applyFill=\"1\" applyBorder=\"1\" applyAlignment=\"1\"><alignment vertical=\"center\"/></xf>\n" +
            "<xf numFmtId=\"0\" fontId=\"4\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyFont=\"1\" applyAlignment=\"1\"><alignment vertical=\"center\"/></xf>\n</cellXfs>\n" +
            "<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>\n</styleSheet>";

        private static string SheetXml(List<Cell[]> rows, double[] widths, int freezeRows)
        {
            var parts = new StringBuilder();
            parts.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">");
            if (freezeRows > 0)
                parts.Append("<sheetViews><sheetView workbookViewId=\"0\" tabSelected=\"1\"><pane ySplit=\"" + freezeRows + "\" topLeftCell=\"A" + (freezeRows + 1) +
                             "\" activePane=\"bottomLeft\" state=\"frozen\"/></sheetView></sheetViews>");
            parts.Append("<sheetFormatPr defaultRowHeight=\"18\"/>");
            if (widths != null && widths.Length > 0)
            {
                parts.Append("<cols>");
                for (int i = 0; i < widths.Length; i++)
                    parts.Append("<col min=\"" + (i + 1) + "\" max=\"" + (i + 1) + "\" width=\"" + widths[i].ToString(System.Globalization.CultureInfo.InvariantCulture) + "\" customWidth=\"1\"/>");
                parts.Append("</cols>");
            }
            parts.Append("<sheetData>");
            for (int r = 0; r < rows.Count; r++)
            {
                int number = r + 1;
                parts.Append("<row r=\"" + number + "\">");
                Cell[] row = rows[r];
                for (int c = 0; c < row.Length; c++)
                {
                    if (row[c] == null) continue;
                    parts.Append("<c r=\"" + ColLetter(c + 1) + number + "\" s=\"" + row[c].Style + "\" t=\"inlineStr\"><is><t xml:space=\"preserve\">" + Esc(row[c].Text) + "</t></is></c>");
                }
                parts.Append("</row>");
            }
            parts.Append("</sheetData></worksheet>");
            return parts.ToString();
        }

        private static void AddEntry(ZipArchive archive, string name, string text)
        {
            ZipArchiveEntry entry = archive.CreateEntry(name, CompressionLevel.Optimal);
            using (Stream stream = entry.Open())
            {
                byte[] data = new UTF8Encoding(false).GetBytes(text);
                stream.Write(data, 0, data.Length);
            }
        }

        /// <summary>Write the whole workbook. Returns (ok, message).</summary>
        public static bool WriteWorkbook(string path, List<Cell[]> rows, double[] widths, string sheetName, out string message)
        {
            message = "";
            try
            {
                using (var stream = new MemoryStream())
                {
                    using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, true))
                    {
                        AddEntry(archive, "[Content_Types].xml", ContentTypes);
                        AddEntry(archive, "_rels/.rels", RootRels);
                        AddEntry(archive, "xl/workbook.xml", WorkbookXml(sheetName));
                        AddEntry(archive, "xl/_rels/workbook.xml.rels", WorkbookRels);
                        AddEntry(archive, "xl/styles.xml", Styles);
                        AddEntry(archive, "xl/worksheets/sheet1.xml", SheetXml(rows, widths, 1));
                    }
                    File.WriteAllBytes(path, stream.ToArray());
                }
                return true;
            }
            catch (Exception err)
            {
                message = err.Message.Contains("being used by another process") ? "The file is open in Excel - close it and try again." : err.Message;
                return false;
            }
        }

        // ---------------------------------------------------------------- reading

        private static string EntryText(ZipArchive archive, string name)
        {
            ZipArchiveEntry entry = archive.GetEntry(name);
            if (entry == null) return null;
            using (var reader = new StreamReader(entry.Open(), Encoding.UTF8)) return reader.ReadToEnd();
        }

        private static string FirstSheetName(ZipArchive archive)
        {
            if (archive.GetEntry("xl/worksheets/sheet1.xml") != null) return "xl/worksheets/sheet1.xml";
            foreach (ZipArchiveEntry entry in archive.Entries)
                if (entry.FullName.StartsWith("xl/worksheets/sheet") && entry.FullName.EndsWith(".xml")) return entry.FullName;
            return null;
        }

        private static void SplitReference(string reference, out int row, out int column)
        {
            string letters = "", digits = "";
            foreach (char c in reference ?? "")
            {
                if (char.IsDigit(c)) digits += c; else letters += c;
            }
            column = 0;
            foreach (char c in letters.ToUpperInvariant()) column = column * 26 + (c - 64);
            if (!int.TryParse(digits, out row)) row = 0;
        }

        /// <summary>rows: {row number: {column number: text}}, 1-based.</summary>
        public static Dictionary<int, Dictionary<int, string>> ReadSheet(string path, out string message)
        {
            message = "";
            var rows = new Dictionary<int, Dictionary<int, string>>();
            ZipArchive archive;
            try { archive = ZipFile.OpenRead(path); }
            catch (Exception err)
            {
                message = err.Message.Contains("being used by another process") ? "The file is open in Excel - save it, close it and import again." : "Could not open the file: " + err.Message;
                return rows;
            }
            using (archive)
            {
                try
                {
                    var shared = new List<string>();
                    string sharedText = null;
                    try { sharedText = EntryText(archive, "xl/sharedStrings.xml"); } catch (Exception) { }
                    if (!string.IsNullOrEmpty(sharedText))
                    {
                        var doc = new XmlDocument();
                        doc.LoadXml(sharedText);
                        foreach (XmlNode node in doc.GetElementsByTagName("si"))
                            shared.Add(string.Concat(((XmlElement)node).GetElementsByTagName("t").Cast<XmlNode>().Select(t => t.InnerText)));
                    }
                    string sheetName = FirstSheetName(archive);
                    if (sheetName == null) { message = "No worksheet found in the workbook."; return rows; }
                    string sheetText = EntryText(archive, sheetName);
                    if (string.IsNullOrEmpty(sheetText)) { message = "The worksheet is empty."; return rows; }
                    var sheet = new XmlDocument();
                    sheet.LoadXml(sheetText);
                    foreach (XmlNode node in sheet.GetElementsByTagName("c"))
                    {
                        var cell = (XmlElement)node;
                        int rowNumber, columnNumber;
                        SplitReference(cell.GetAttribute("r"), out rowNumber, out columnNumber);
                        if (rowNumber <= 0 || columnNumber <= 0) continue;
                        string type = cell.GetAttribute("t") ?? "";
                        string value = "";
                        if (type == "inlineStr") value = string.Concat(cell.GetElementsByTagName("t").Cast<XmlNode>().Select(t => t.InnerText));
                        else if (type == "s")
                        {
                            string raw = "";
                            foreach (XmlNode v in cell.GetElementsByTagName("v")) { raw = v.InnerText; break; }
                            double d;
                            if (double.TryParse(raw, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out d))
                            {
                                int index = (int)d;
                                if (index >= 0 && index < shared.Count) value = shared[index];
                            }
                        }
                        else foreach (XmlNode v in cell.GetElementsByTagName("v")) { value = v.InnerText; break; }
                        value = value.Trim();
                        Dictionary<int, string> line;
                        if (!rows.TryGetValue(rowNumber, out line)) rows[rowNumber] = line = new Dictionary<int, string>();
                        line[columnNumber] = value;
                    }
                }
                catch (Exception err) { message = "Could not read the spreadsheet: " + err.Message; }
            }
            return rows;
        }

        // ---------------------------------------------------------------- the workset sheet

        public static readonly double[] Widths = { 14, 46, 12, 58 };

        public static List<Cell[]> WorksetSheetRows(IEnumerable<WsmCore.WsRow> rows, int blankRows)
        {
            var output = new List<Cell[]>
            {
                new[] { new Cell("Workset ID", StyleHeader), new Cell("Workset Name", StyleHeader), new Cell("Elements", StyleHeader), new Cell("Action", StyleHeader) },
            };
            foreach (WsmCore.WsRow row in rows)
            {
                if (row.IsNew) continue;
                output.Add(new[]
                {
                    new Cell(row.Iid.ToString(), StyleLocked), new Cell(row.Orig, StyleExisting), new Cell(row.Count.ToString(), StyleLocked),
                    new Cell("Existing - edit the name to rename this workset", StyleLocked),
                });
            }
            for (int i = 0; i < Math.Max(1, blankRows); i++)
                output.Add(new[]
                {
                    new Cell(WsmCore.NewRowKey, StyleLocked), new Cell(WsmCore.NewRowPlaceholder, StyleNew), new Cell("", StyleLocked),
                    new Cell("New - type a workset name here to create it", StyleLocked),
                });
            output.Add(new Cell[] { null, null, null, null });
            output.Add(new[]
            {
                new Cell("Leave column A alone - it is how a renamed workset is matched back to the one in the model. Save the file, then press Import Excel. " +
                         "Worksets are deleted from the table in the tool, not from here.", StyleNote),
            });
            return output;
        }

        public static List<WsmCore.SheetRow> SheetTriples(Dictionary<int, Dictionary<int, string>> sheet)
        {
            var output = new List<WsmCore.SheetRow>();
            foreach (int number in sheet.Keys.OrderBy(k => k))
            {
                if (number <= 1) continue;
                string id, name;
                sheet[number].TryGetValue(1, out id);
                sheet[number].TryGetValue(2, out name);
                output.Add(new WsmCore.SheetRow { Number = number, IdCell = id ?? "", NameCell = name ?? "" });
            }
            return output;
        }
    }
}
