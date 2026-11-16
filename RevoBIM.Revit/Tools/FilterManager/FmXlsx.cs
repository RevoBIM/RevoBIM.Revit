using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.FilterManager
{
    /// <summary>One worksheet to write.</summary>
    public class FmSheet
    {
        public string Name = "Sheet1";
        public List<List<string>> Rows = new List<List<string>>();
        public double[] Widths;
        public int HeaderRows = 1;
        public bool Freeze = true;
        /// <summary>Optional grid of style ids the same shape as Rows.</summary>
        public List<List<int>> Styles;
        /// <summary>(sqref, formula) pairs for list validations.</summary>
        public List<Tuple<string, string>> Validations;
    }

    /// <summary>
    /// A minimal Excel reader and writer: Office Open XML written straight into a zip, no Excel and no package.
    /// The parser is deliberately tolerant: Excel rewrites a file it has saved, so values arrive as shared
    /// strings, empty cells are dropped entirely, and rows are numbered rather than ordered. Port of fm_xlsx.py.
    /// </summary>
    public static class FmXlsx
    {
        public const string Ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";

        // the style ids styles.xml declares, in order
        public const int StylePlain = 0, StyleHeader = 1, StyleLocked = 2, StyleEditable = 3, StyleNote = 4,
                         StyleCategory = 5, StyleRule = 6, StyleDark = 7, StyleDarkTitle = 8;

        public static string ColumnLetter(int index)
        {
            string letters = "";
            while (true)
            {
                letters = (char)('A' + (index % 26)) + letters;
                index = index / 26 - 1;
                if (index < 0) break;
            }
            return letters;
        }

        public static int ColumnIndex(string letters)
        {
            int total = 0;
            foreach (char ch in (letters ?? "").ToUpperInvariant())
            {
                if (ch < 'A' || ch > 'Z') continue;
                total = total * 26 + (ch - 'A' + 1);
            }
            return total - 1;
        }

        public static string Escape(string text)
        {
            if (text == null) return "";
            string o = text.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;");
            // control characters are not legal in XML at all
            var sb = new StringBuilder(o.Length);
            foreach (char c in o) if (c >= ' ' || c == '\t' || c == '\n') sb.Append(c);
            return sb.ToString();
        }

        public static string Unescape(string text)
        {
            if (text == null) return "";
            return text.Replace("&lt;", "<").Replace("&gt;", ">").Replace("&quot;", "\"").Replace("&apos;", "'").Replace("&amp;", "&");
        }

        // ---------------------------------------------------------------------------
        //  Writing
        // ---------------------------------------------------------------------------
        public static string SheetXml(FmSheet sheet)
        {
            var o = new StringBuilder();
            o.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
            o.Append("<worksheet xmlns=\"" + Ns + "\">");

            if (sheet.Freeze && sheet.HeaderRows > 0)
                o.Append("<sheetViews><sheetView workbookViewId=\"0\"><pane ySplit=\"" + sheet.HeaderRows + "\" topLeftCell=\"A" +
                         (sheet.HeaderRows + 1) + "\" activePane=\"bottomLeft\" state=\"frozen\"/></sheetView></sheetViews>");

            if (sheet.Widths != null && sheet.Widths.Length > 0)
            {
                o.Append("<cols>");
                for (int i = 0; i < sheet.Widths.Length; i++)
                    o.Append("<col min=\"" + (i + 1) + "\" max=\"" + (i + 1) + "\" width=\"" +
                             sheet.Widths[i].ToString(System.Globalization.CultureInfo.InvariantCulture) + "\" customWidth=\"1\"/>");
                o.Append("</cols>");
            }

            o.Append("<sheetData>");
            for (int r = 0; r < sheet.Rows.Count; r++)
            {
                int number = r + 1;
                o.Append("<row r=\"" + number + "\">");
                List<string> row = sheet.Rows[r];
                for (int c = 0; c < row.Count; c++)
                {
                    int style = StylePlain;
                    if (sheet.Styles != null && r < sheet.Styles.Count && c < sheet.Styles[r].Count) style = sheet.Styles[r][c];
                    else if (r < sheet.HeaderRows) style = StyleHeader;

                    string value = row[c];
                    bool blank = string.IsNullOrEmpty(value);
                    if (blank && style == StylePlain) continue;

                    string attrs = style != 0 ? " s=\"" + style + "\"" : "";
                    if (blank) o.Append("<c r=\"" + ColumnLetter(c) + number + "\"" + attrs + "/>");
                    else
                        o.Append("<c r=\"" + ColumnLetter(c) + number + "\" t=\"inlineStr\"" + attrs +
                                 "><is><t xml:space=\"preserve\">" + Escape(value) + "</t></is></c>");
                }
                o.Append("</row>");
            }
            o.Append("</sheetData>");

            if (sheet.Validations != null && sheet.Validations.Count > 0)
            {
                o.Append("<dataValidations count=\"" + sheet.Validations.Count + "\">");
                foreach (var v in sheet.Validations)
                {
                    // showErrorMessage is off on purpose: the lists are a guide, and a name Excel does not
                    // know about should still be typeable
                    o.Append("<dataValidation type=\"list\" allowBlank=\"1\" showInputMessage=\"1\" showErrorMessage=\"0\" sqref=\"" +
                             Escape(v.Item1) + "\"><formula1>" + Escape(v.Item2) + "</formula1></dataValidation>");
                }
                o.Append("</dataValidations>");
            }

            o.Append("</worksheet>");
            return o.ToString();
        }

        /// <summary>Every part of the file, as {path inside the zip: text}.</summary>
        public static SortedDictionary<string, string> WorkbookParts(IList<FmSheet> sheets)
        {
            var parts = new SortedDictionary<string, string>(StringComparer.Ordinal);
            var overrides = new StringBuilder();
            var rels = new StringBuilder();
            var entries = new StringBuilder();
            for (int i = 0; i < sheets.Count; i++)
            {
                int number = i + 1;
                string path = "xl/worksheets/sheet" + number + ".xml";
                parts[path] = SheetXml(sheets[i]);
                overrides.Append("<Override PartName=\"/" + path +
                                 "\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>");
                rels.Append("<Relationship Id=\"rId" + number +
                            "\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet" +
                            number + ".xml\"/>");
                string name = Escape(sheets[i].Name ?? ("Sheet" + number));
                if (name.Length > 31) name = name.Substring(0, 31);
                entries.Append("<sheet name=\"" + name + "\" sheetId=\"" + number + "\" r:id=\"rId" + number + "\"/>");
            }

            int styleRel = sheets.Count + 1;
            rels.Append("<Relationship Id=\"rId" + styleRel +
                        "\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>");

            parts["[Content_Types].xml"] =
                "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">" +
                "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>" +
                "<Default Extension=\"xml\" ContentType=\"application/xml\"/>" +
                "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>" +
                overrides +
                "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>" +
                "</Types>";

            parts["_rels/.rels"] =
                "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" +
                "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/></Relationships>";

            parts["xl/workbook.xml"] =
                "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                "<workbook xmlns=\"" + Ns + "\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets>" +
                entries + "</sheets></workbook>";

            parts["xl/_rels/workbook.xml.rels"] =
                "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" + rels + "</Relationships>";

            parts["xl/styles.xml"] =
                "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                "<styleSheet xmlns=\"" + Ns + "\">" +
                "<fonts count=\"5\">" +
                "<font><sz val=\"11\"/><name val=\"Calibri\"/></font>" +
                "<font><b/><color rgb=\"FFFFFFFF\"/><sz val=\"11\"/><name val=\"Calibri\"/></font>" +
                "<font><color rgb=\"FF808080\"/><sz val=\"11\"/><name val=\"Calibri\"/></font>" +
                "<font><i/><color rgb=\"FF808080\"/><sz val=\"11\"/><name val=\"Calibri\"/></font>" +
                "<font><color rgb=\"FFE4E4E4\"/><sz val=\"11\"/><name val=\"Calibri\"/></font>" +
                "</fonts>" +
                "<fills count=\"8\">" +
                "<fill><patternFill patternType=\"none\"/></fill>" +
                "<fill><patternFill patternType=\"gray125\"/></fill>" +
                "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FF1F4E2C\"/><bgColor indexed=\"64\"/></patternFill></fill>" +
                "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FFD9D9D9\"/><bgColor indexed=\"64\"/></patternFill></fill>" +
                "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FFFFE08A\"/><bgColor indexed=\"64\"/></patternFill></fill>" +
                "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FF6FAEE2\"/><bgColor indexed=\"64\"/></patternFill></fill>" +
                "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FF8FD3A3\"/><bgColor indexed=\"64\"/></patternFill></fill>" +
                "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FF2B2B2E\"/><bgColor indexed=\"64\"/></patternFill></fill>" +
                "</fills>" +
                "<borders count=\"2\"><border/>" +
                "<border><left style=\"thin\"><color rgb=\"FFD0D0D0\"/></left><right style=\"thin\"><color rgb=\"FFD0D0D0\"/></right>" +
                "<top style=\"thin\"><color rgb=\"FFD0D0D0\"/></top><bottom style=\"thin\"><color rgb=\"FFD0D0D0\"/></bottom></border>" +
                "</borders>" +
                "<cellStyleXfs count=\"1\"><xf/></cellStyleXfs>" +
                "<cellXfs count=\"9\">" +
                "<xf xfId=\"0\"/>" +
                "<xf xfId=\"0\" fontId=\"1\" fillId=\"2\" borderId=\"1\" applyFont=\"1\" applyFill=\"1\" applyBorder=\"1\"><alignment vertical=\"center\"/></xf>" +
                "<xf xfId=\"0\" fontId=\"2\" fillId=\"3\" borderId=\"1\" applyFont=\"1\" applyFill=\"1\" applyBorder=\"1\"/>" +
                "<xf xfId=\"0\" fillId=\"4\" borderId=\"1\" applyFill=\"1\" applyBorder=\"1\"/>" +
                "<xf xfId=\"0\" fontId=\"3\" applyFont=\"1\"/>" +
                "<xf xfId=\"0\" fillId=\"5\" borderId=\"1\" applyFill=\"1\" applyBorder=\"1\"/>" +
                "<xf xfId=\"0\" fillId=\"6\" borderId=\"1\" applyFill=\"1\" applyBorder=\"1\"/>" +
                "<xf xfId=\"0\" fontId=\"4\" fillId=\"7\" applyFont=\"1\" applyFill=\"1\"><alignment vertical=\"center\" wrapText=\"1\"/></xf>" +
                "<xf xfId=\"0\" fontId=\"1\" fillId=\"7\" applyFont=\"1\" applyFill=\"1\"><alignment vertical=\"center\"/></xf>" +
                "</cellXfs>" +
                "</styleSheet>";

            return parts;
        }

        // ---------------------------------------------------------------------------
        //  Parsing
        // ---------------------------------------------------------------------------
        private static readonly Regex RowRx = new Regex("<row[^>]*?\\br=\"(\\d+)\"[^>]*?(?<!/)>(.*?)</row>", RegexOptions.Singleline);
        private static readonly Regex RowEmptyRx = new Regex("<row[^>]*?\\br=\"(\\d+)\"[^>]*?/>", RegexOptions.Singleline);
        private static readonly Regex CellRx = new Regex("<c\\b([^>]*?)(?:/>|>(.*?)</c>)", RegexOptions.Singleline);
        private static readonly Regex RefRx = new Regex("\\br=\"([A-Z]+)(\\d+)\"");
        private static readonly Regex TypeRx = new Regex("\\bt=\"([^\"]+)\"");
        private static readonly Regex VRx = new Regex("<v[^>]*>(.*?)</v>", RegexOptions.Singleline);
        private static readonly Regex IsTRx = new Regex("<t[^>]*>(.*?)</t>", RegexOptions.Singleline);
        private static readonly Regex SiRx = new Regex("<si\\b[^>]*>(.*?)</si>", RegexOptions.Singleline);

        /// <summary>The shared string table, in order. Excel writes one after editing.</summary>
        public static List<string> SharedStrings(string text)
        {
            var output = new List<string>();
            if (string.IsNullOrEmpty(text)) return output;
            foreach (Match si in SiRx.Matches(text))
                output.Add(string.Concat(IsTRx.Matches(si.Groups[1].Value).Cast<Match>().Select(m => Unescape(m.Groups[1].Value))));
            return output;
        }

        /// <summary>A worksheet as a list of rows, each a list of cell strings; missing cells and rows are filled in.</summary>
        public static List<List<string>> ParseSheet(string text, IList<string> strings = null)
        {
            strings = strings ?? new List<string>();
            var rows = new List<List<string>>();
            if (string.IsNullOrEmpty(text)) return rows;

            var found = new Dictionary<int, Dictionary<int, string>>();
            int widest = 0;
            foreach (Match rowMatch in RowRx.Matches(text))
            {
                int number = int.Parse(rowMatch.Groups[1].Value);
                string body = rowMatch.Groups[2].Value;
                var cells = new Dictionary<int, string>();
                foreach (Match cell in CellRx.Matches(body))
                {
                    string attrs = cell.Groups[1].Value;
                    string inner = cell.Groups[2].Success ? cell.Groups[2].Value : "";
                    Match reference = RefRx.Match(attrs);
                    if (!reference.Success) continue;
                    int col = ColumnIndex(reference.Groups[1].Value);
                    Match kindMatch = TypeRx.Match(attrs);
                    string kind = kindMatch.Success ? kindMatch.Groups[1].Value : "";

                    string value;
                    if (kind == "inlineStr")
                    {
                        value = string.Concat(IsTRx.Matches(inner).Cast<Match>().Select(m => Unescape(m.Groups[1].Value)));
                    }
                    else
                    {
                        Match v = VRx.Match(inner);
                        string raw = v.Success ? Unescape(v.Groups[1].Value) : "";
                        if (kind == "s")
                        {
                            int idx;
                            value = int.TryParse(raw, out idx) && idx >= 0 && idx < strings.Count ? strings[idx] : "";
                        }
                        else value = raw;
                    }
                    cells[col] = value;
                    widest = Math.Max(widest, col + 1);
                }
                found[number] = cells;
            }

            foreach (Match m in RowEmptyRx.Matches(text))
            {
                int number = int.Parse(m.Groups[1].Value);
                if (!found.ContainsKey(number)) found[number] = new Dictionary<int, string>();
            }

            if (found.Count == 0) return rows;
            int last = found.Keys.Max();
            for (int number = 1; number <= last; number++)
            {
                Dictionary<int, string> cells;
                found.TryGetValue(number, out cells);
                var row = new List<string>();
                for (int i = 0; i < widest; i++)
                {
                    string v;
                    row.Add(cells != null && cells.TryGetValue(i, out v) ? v : "");
                }
                rows.Add(row);
            }
            return rows;
        }

        // ---------------------------------------------------------------------------
        //  The zip
        // ---------------------------------------------------------------------------
        public static string WriteWorkbook(string path, IList<FmSheet> sheets)
        {
            SortedDictionary<string, string> parts = WorkbookParts(sheets);
            using (var stream = new FileStream(path, FileMode.Create, FileAccess.Write))
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Create))
            {
                foreach (var part in parts)
                {
                    ZipArchiveEntry entry = archive.CreateEntry(part.Key);
                    using (var writer = new StreamWriter(entry.Open(), new UTF8Encoding(false)))
                        writer.Write(part.Value);
                }
            }
            return path;
        }

        public static string WriteWorkbook(string path, FmSheet sheet)
        {
            return WriteWorkbook(path, new List<FmSheet> { sheet });
        }

        /// <summary>The first worksheet of an .xlsx, as a list of rows.</summary>
        public static List<List<string>> ReadWorkbook(string path)
        {
            string sheet = "";
            string stringsText = "";
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Read))
            {
                sheet = EntryText(archive, "xl/worksheets/sheet1.xml");
                if (string.IsNullOrEmpty(sheet))
                {
                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        if (entry.FullName.StartsWith("xl/worksheets/", StringComparison.Ordinal) &&
                            entry.FullName.EndsWith(".xml", StringComparison.Ordinal))
                        {
                            sheet = ReadEntry(entry);
                            break;
                        }
                    }
                }
                stringsText = EntryText(archive, "xl/sharedStrings.xml");
            }
            return ParseSheet(sheet, SharedStrings(stringsText));
        }

        private static string EntryText(ZipArchive archive, string name)
        {
            ZipArchiveEntry entry = null;
            try { entry = archive.GetEntry(name); }
            catch (Exception) { }
            return entry != null ? ReadEntry(entry) : "";
        }

        private static string ReadEntry(ZipArchiveEntry entry)
        {
            using (var reader = new StreamReader(entry.Open(), Encoding.UTF8))
                return reader.ReadToEnd();
        }
    }
}
