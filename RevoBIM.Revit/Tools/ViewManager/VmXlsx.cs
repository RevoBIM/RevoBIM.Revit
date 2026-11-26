using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ViewManager
{
    /// <summary>
    /// View Manager - Excel push and pull, written and read as Office Open XML directly (no Excel needed), and the import
    /// plan that matches a sheet back to the list on the Revit ID. Port of the Excel block of script.py.
    /// </summary>
    public static class VmXlsx
    {
        public const string SheetName = "View references";
        public const string IdHeader = "Revit ID";

        private const string NsMain = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
        private const string NsRel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
        private const string NsPkgRel = "http://schemas.openxmlformats.org/package/2006/relationships";

        private static readonly Regex IllegalXml = new Regex("[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]");

        /// <summary>0 -> A, 25 -> Z, 26 -> AA.</summary>
        public static string ColLetters(int index)
        {
            string letters = "";
            index += 1;
            while (index > 0)
            {
                int rem = (index - 1) % 26;
                index = (index - 1) / 26;
                letters = (char)(65 + rem) + letters;
            }
            return letters;
        }

        /// <summary>A -> 0, AA -> 26.</summary>
        public static int ColIndex(string letters)
        {
            int total = 0;
            foreach (char ch in letters.ToUpperInvariant()) total = total * 26 + (ch - 64);
            return total - 1;
        }

        public static string XmlText(string text)
        {
            text = IllegalXml.Replace(text ?? "", "");
            return text.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;");
        }

        public static string XmlAttr(string text)
        {
            return XmlText(text).Replace("\"", "&quot;");
        }

        // cellXfs: 0 plain, 1 header, 2 read-only text, 3 editable text, 4 read-only number
        private static string Styles()
        {
            return "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                + "<styleSheet xmlns=\"" + NsMain + "\">"
                + "<fonts count=\"3\">"
                + "<font><sz val=\"11\"/><name val=\"Calibri\"/></font>"
                + "<font><b/><sz val=\"11\"/><color rgb=\"FFFFFFFF\"/><name val=\"Calibri\"/></font>"
                + "<font><sz val=\"11\"/><color rgb=\"FF595959\"/><name val=\"Calibri\"/></font>"
                + "</fonts>"
                + "<fills count=\"4\">"
                + "<fill><patternFill patternType=\"none\"/></fill>"
                + "<fill><patternFill patternType=\"gray125\"/></fill>"
                + "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FF2B5473\"/><bgColor indexed=\"64\"/></patternFill></fill>"
                + "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FFEDEFF2\"/><bgColor indexed=\"64\"/></patternFill></fill>"
                + "</fills>"
                + "<borders count=\"2\">"
                + "<border><left/><right/><top/><bottom/><diagonal/></border>"
                + "<border><left style=\"thin\"><color rgb=\"FFD0D4DA\"/></left>"
                + "<right style=\"thin\"><color rgb=\"FFD0D4DA\"/></right>"
                + "<top style=\"thin\"><color rgb=\"FFD0D4DA\"/></top>"
                + "<bottom style=\"thin\"><color rgb=\"FFD0D4DA\"/></bottom><diagonal/></border>"
                + "</borders>"
                + "<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>"
                + "<cellXfs count=\"5\">"
                + "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/>"
                + "<xf numFmtId=\"49\" fontId=\"1\" fillId=\"2\" borderId=\"1\" xfId=\"0\" applyNumberFormat=\"1\" applyFont=\"1\" applyFill=\"1\" applyBorder=\"1\" applyAlignment=\"1\"><alignment vertical=\"center\"/></xf>"
                + "<xf numFmtId=\"49\" fontId=\"2\" fillId=\"3\" borderId=\"1\" xfId=\"0\" applyNumberFormat=\"1\" applyFont=\"1\" applyFill=\"1\" applyBorder=\"1\"/>"
                + "<xf numFmtId=\"49\" fontId=\"0\" fillId=\"0\" borderId=\"1\" xfId=\"0\" applyNumberFormat=\"1\" applyBorder=\"1\"/>"
                + "<xf numFmtId=\"0\" fontId=\"2\" fillId=\"3\" borderId=\"1\" xfId=\"0\" applyFont=\"1\" applyFill=\"1\" applyBorder=\"1\"/>"
                + "</cellXfs>"
                + "<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>"
                + "</styleSheet>";
        }

        private static bool IsNumberText(string text)
        {
            return Regex.IsMatch(text ?? "", "^\\d{1,15}$");
        }

        /// <summary>
        /// The parts of a workbook: (path, text) in the order they are zipped. headers - column headings, the first is the
        /// Revit ID, the key a pull matches on. writable - one flag per column. body - rows of text, the same width as headers.
        /// </summary>
        public static List<KeyValuePair<string, string>> Build(IList<string> headers, IList<bool> writable, IList<string[]> body, string sheetName = SheetName)
        {
            int width = headers.Count;
            int lastRow = body.Count + 1;
            string lastCol = ColLetters(width - 1);
            var sheet = new StringBuilder();
            sheet.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<worksheet xmlns=\"" + NsMain + "\" xmlns:r=\"" + NsRel + "\">");
            sheet.Append("<dimension ref=\"A1:" + lastCol + lastRow + "\"/>");
            sheet.Append("<sheetViews><sheetView tabSelected=\"1\" workbookViewId=\"0\">"
                + "<pane xSplit=\"2\" ySplit=\"1\" topLeftCell=\"C2\" activePane=\"bottomRight\" state=\"frozen\"/>"
                + "<selection pane=\"topRight\" activeCell=\"C1\" sqref=\"C1\"/>"
                + "<selection pane=\"bottomLeft\" activeCell=\"A2\" sqref=\"A2\"/>"
                + "<selection pane=\"bottomRight\" activeCell=\"C2\" sqref=\"C2\"/>"
                + "</sheetView></sheetViews>");
            sheet.Append("<sheetFormatPr defaultRowHeight=\"15\"/>");
            sheet.Append("<cols>");
            for (int c = 0; c < width; c++)
            {
                int longest = headers[c].Length;
                for (int r = 0; r < Math.Min(400, body.Count); r++)
                    if (body[r][c].Length > longest) longest = body[r][c].Length;
                int chars = c == 0 ? 11 : Math.Min(Math.Max(longest + 3, 10), 60);
                sheet.Append("<col min=\"" + (c + 1) + "\" max=\"" + (c + 1) + "\" width=\"" + chars + "\" customWidth=\"1\"/>");
            }
            sheet.Append("</cols>");
            sheet.Append("<sheetData>");
            sheet.Append("<row r=\"1\" ht=\"21\" customHeight=\"1\">");
            for (int c = 0; c < width; c++)
                sheet.Append("<c r=\"" + ColLetters(c) + "1\" s=\"1\" t=\"inlineStr\"><is><t xml:space=\"preserve\">" + XmlText(headers[c]) + "</t></is></c>");
            sheet.Append("</row>");
            for (int r = 0; r < body.Count; r++)
            {
                int number = r + 2;
                sheet.Append("<row r=\"" + number + "\">");
                string[] row = body[r];
                for (int c = 0; c < width; c++)
                {
                    string reference = ColLetters(c) + number;
                    string text = row[c];
                    if (c == 0 && IsNumberText(text)) sheet.Append("<c r=\"" + reference + "\" s=\"4\"><v>" + text + "</v></c>");
                    else if (string.IsNullOrEmpty(text)) sheet.Append("<c r=\"" + reference + "\" s=\"" + (writable[c] ? 3 : 2) + "\"/>");
                    else sheet.Append("<c r=\"" + reference + "\" s=\"" + (writable[c] ? 3 : 2) + "\" t=\"inlineStr\"><is><t xml:space=\"preserve\">" + XmlText(text) + "</t></is></c>");
                }
                sheet.Append("</row>");
            }
            sheet.Append("</sheetData>");
            sheet.Append("<autoFilter ref=\"A1:" + lastCol + lastRow + "\"/>");
            sheet.Append("</worksheet>");

            string ct = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                + "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
                + "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
                + "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
                + "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>"
                + "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
                + "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>"
                + "</Types>";
            string rootRels = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                + "<Relationships xmlns=\"" + NsPkgRel + "\"><Relationship Id=\"rId1\" Type=\"" + NsRel + "/officeDocument\" Target=\"xl/workbook.xml\"/></Relationships>";
            string name31 = sheetName.Length > 31 ? sheetName.Substring(0, 31) : sheetName;
            string workbook = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                + "<workbook xmlns=\"" + NsMain + "\" xmlns:r=\"" + NsRel + "\"><sheets><sheet name=\"" + XmlAttr(name31) + "\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>";
            string wbRels = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                + "<Relationships xmlns=\"" + NsPkgRel + "\">"
                + "<Relationship Id=\"rId1\" Type=\"" + NsRel + "/worksheet\" Target=\"worksheets/sheet1.xml\"/>"
                + "<Relationship Id=\"rId2\" Type=\"" + NsRel + "/styles\" Target=\"styles.xml\"/>"
                + "</Relationships>";
            return new List<KeyValuePair<string, string>>
            {
                new KeyValuePair<string, string>("[Content_Types].xml", ct),
                new KeyValuePair<string, string>("_rels/.rels", rootRels),
                new KeyValuePair<string, string>("xl/workbook.xml", workbook),
                new KeyValuePair<string, string>("xl/_rels/workbook.xml.rels", wbRels),
                new KeyValuePair<string, string>("xl/styles.xml", Styles()),
                new KeyValuePair<string, string>("xl/worksheets/sheet1.xml", sheet.ToString()),
            };
        }

        // ---------------------------------------------------------------- reading --

        private static readonly Regex EntityRx = new Regex("&(#x[0-9A-Fa-f]+|#[0-9]+|amp|lt|gt|quot|apos);");
        private static readonly Regex AttrRx = new Regex("([A-Za-z_][\\w:.\\-]*)\\s*=\\s*(?:\"([^\"]*)\"|'([^']*)')");
        private static readonly Regex TRunRx = new Regex("<(?:\\w+:)?t\\b[^>]*?(?:/>|>(.*?)</(?:\\w+:)?t>)", RegexOptions.Singleline);
        private static readonly Regex PhoneticRx = new Regex("<(?:\\w+:)?rPh\\b.*?</(?:\\w+:)?rPh>", RegexOptions.Singleline);

        public static string XmlUnescape(string text)
        {
            return EntityRx.Replace(text ?? "", m =>
            {
                string body = m.Groups[1].Value;
                if (body[0] == '#')
                {
                    try
                    {
                        int code = (body[1] == 'x' || body[1] == 'X') ? Convert.ToInt32(body.Substring(2), 16) : int.Parse(body.Substring(1));
                        return char.ConvertFromUtf32(code);
                    }
                    catch (Exception)
                    {
                        return "";
                    }
                }
                switch (body)
                {
                    case "amp": return "&";
                    case "lt": return "<";
                    case "gt": return ">";
                    case "quot": return "\"";
                    default: return "'";
                }
            });
        }

        private static Dictionary<string, string> Attrs(string text)
        {
            var output = new Dictionary<string, string>();
            foreach (Match m in AttrRx.Matches(text ?? ""))
            {
                string name = m.Groups[1].Value;
                int colon = name.IndexOf(':');
                if (colon >= 0) name = name.Substring(colon + 1);
                output[name] = XmlUnescape(m.Groups[2].Success ? m.Groups[2].Value : m.Groups[3].Value);
            }
            return output;
        }

        private static string RunsText(string xml)
        {
            xml = PhoneticRx.Replace(xml, "");
            var sb = new StringBuilder();
            foreach (Match m in TRunRx.Matches(xml)) sb.Append(XmlUnescape(m.Groups[1].Success ? m.Groups[1].Value : ""));
            return sb.ToString();
        }

        public static List<string> ParseSharedStrings(string xml)
        {
            var items = new List<string>();
            foreach (Match m in Regex.Matches(xml ?? "", "<(?:\\w+:)?si\\b[^>]*?(?:/>|>(.*?)</(?:\\w+:)?si>)", RegexOptions.Singleline))
                items.Add(RunsText(m.Groups[1].Success ? m.Groups[1].Value : ""));
            return items;
        }

        /// <summary>A numeric cell as the text a person would have typed: 3.0 -> 3.</summary>
        private static string PlainNumber(string text)
        {
            text = text.Trim();
            if (Regex.IsMatch(text, "^-?\\d+\\.0+$")) return text.Split('.')[0];
            if (Regex.IsMatch(text, "^-?\\d+\\.\\d+([eE][-+]?\\d+)?$") || Regex.IsMatch(text, "^-?\\d+[eE][-+]?\\d+$"))
            {
                double d;
                if (double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out d))
                    return d.ToString("G12", CultureInfo.InvariantCulture);
            }
            return text;
        }

        /// <summary>{row number: {column index: text}} for every cell that holds something.</summary>
        public static Dictionary<int, Dictionary<int, string>> ParseSheetCells(string xml, IList<string> shared)
        {
            var grid = new Dictionary<int, Dictionary<int, string>>();
            var cell = new Regex("<(?:\\w+:)?c\\b([^>]*?)(?:/>|>(.*?)</(?:\\w+:)?c>)", RegexOptions.Singleline);
            foreach (Match m in cell.Matches(xml ?? ""))
            {
                Dictionary<string, string> attrs = Attrs(m.Groups[1].Value);
                string reference;
                attrs.TryGetValue("r", out reference);
                Match rm = Regex.Match(reference ?? "", "^([A-Za-z]+)(\\d+)$");
                if (!rm.Success || !m.Groups[2].Success) continue;
                string inner = m.Groups[2].Value;
                string kind;
                if (!attrs.TryGetValue("t", out kind)) kind = "n";
                string text;
                if (kind == "inlineStr") text = RunsText(inner);
                else
                {
                    Match vm = Regex.Match(inner, "<(?:\\w+:)?v\\b[^>]*?>(.*?)</(?:\\w+:)?v>", RegexOptions.Singleline);
                    string raw = vm.Success ? XmlUnescape(vm.Groups[1].Value) : "";
                    if (kind == "s")
                    {
                        int index;
                        text = int.TryParse(raw.Trim(), out index) && index >= 0 && index < shared.Count ? shared[index] : "";
                    }
                    else if (kind == "str") text = raw;
                    else if (kind == "b") text = raw.Trim() == "1" ? "1" : "0";
                    else if (kind == "e") text = "";
                    else text = PlainNumber(raw);
                }
                if (text.Length > 0)
                {
                    int rowNumber = int.Parse(rm.Groups[2].Value);
                    Dictionary<int, string> row;
                    if (!grid.TryGetValue(rowNumber, out row)) grid[rowNumber] = row = new Dictionary<int, string>();
                    row[ColIndex(rm.Groups[1].Value)] = text;
                }
            }
            return grid;
        }

        /// <summary>(sheet name, grid) from the parts of a workbook. Takes the sheet called preferred, else the first. Throws with a sentence a person can act on.</summary>
        public static Dictionary<int, Dictionary<int, string>> Parse(IDictionary<string, string> parts, out string sheetName, string preferred = SheetName)
        {
            string workbook;
            if (!parts.TryGetValue("xl/workbook.xml", out workbook)) throw new InvalidOperationException("This is not an Excel workbook (.xlsx).");
            var rels = new Dictionary<string, string>();
            string relsText;
            parts.TryGetValue("xl/_rels/workbook.xml.rels", out relsText);
            foreach (Match m in Regex.Matches(relsText ?? "", "<(?:\\w+:)?Relationship\\b([^>]*?)/?>", RegexOptions.Singleline))
            {
                Dictionary<string, string> a = Attrs(m.Groups[1].Value);
                if (a.ContainsKey("Id") && a.ContainsKey("Target") && a["Id"].Length > 0 && a["Target"].Length > 0)
                {
                    string target = a["Target"].TrimStart('/');
                    rels[a["Id"]] = target.StartsWith("xl/") ? target : "xl/" + target;
                }
            }
            var sheets = new List<KeyValuePair<string, string>>();
            foreach (Match m in Regex.Matches(workbook, "<(?:\\w+:)?sheet\\b([^>]*?)/?>", RegexOptions.Singleline))
            {
                Dictionary<string, string> a = Attrs(m.Groups[1].Value);
                string name, id, path = null;
                a.TryGetValue("name", out name);
                if (a.TryGetValue("id", out id)) rels.TryGetValue(id, out path);
                sheets.Add(new KeyValuePair<string, string>(name ?? "", path));
            }
            KeyValuePair<string, string>? chosen = null;
            foreach (var s in sheets) if (s.Key == preferred && s.Value != null) { chosen = s; break; }
            if (chosen == null) foreach (var s in sheets) if (s.Value != null) { chosen = s; break; }
            if (chosen == null || !parts.ContainsKey(chosen.Value.Value)) throw new InvalidOperationException("The workbook has no readable sheet.");
            string sharedText;
            parts.TryGetValue("xl/sharedStrings.xml", out sharedText);
            sheetName = chosen.Value.Key;
            return ParseSheetCells(parts[chosen.Value.Value], ParseSharedStrings(sharedText));
        }

        // ---------------------------------------------------------------- the zip --

        /// <summary>Zip the parts. Throws on a locked or unwritable file.</summary>
        public static void WriteFile(string path, IEnumerable<KeyValuePair<string, string>> parts)
        {
            var utf8 = new UTF8Encoding(false);
            using (var stream = new FileStream(path, FileMode.Create, FileAccess.ReadWrite, FileShare.None))
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, false))
            {
                foreach (KeyValuePair<string, string> part in parts)
                {
                    ZipArchiveEntry entry = archive.CreateEntry(part.Key, CompressionLevel.Optimal);
                    using (Stream outStream = entry.Open())
                    {
                        byte[] bytes = utf8.GetBytes(part.Value);
                        outStream.Write(bytes, 0, bytes.Length);
                    }
                }
            }
        }

        /// <summary>{part name: text} for the XML parts of a workbook. Opened shared, so a file still open in Excel can be read.</summary>
        public static Dictionary<string, string> ReadParts(string path)
        {
            var parts = new Dictionary<string, string>();
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Read, false))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    string name = entry.FullName;
                    if (name.StartsWith("xl/") && (name.EndsWith(".xml") || name.EndsWith(".rels")))
                    {
                        using (Stream src = entry.Open())
                        using (var reader = new StreamReader(src, new UTF8Encoding(false)))
                            parts[name] = reader.ReadToEnd();
                    }
                }
            }
            return parts;
        }

        // ---------------------------------------------------------------- the import plan --

        public sealed class Change
        {
            public long ViewId;
            public string Key, Old, New;
        }

        public sealed class Refusal
        {
            public long ViewId;
            public string Label, Why;
        }

        /// <summary>What an Excel pull would do, worked out before anything is staged.</summary>
        public sealed class ImportPlan
        {
            public List<Change> Changes = new List<Change>();
            public List<Refusal> Refused = new List<Refusal>();
            public List<long> UnknownIds = new List<long>();
            public int IgnoredCells;
            public List<string> UnknownHeaders = new List<string>();
            public List<string> MissingColumns = new List<string>();
            public int RowsRead;
            public int HeaderRow;
            public List<string> MatchedColumns = new List<string>();
        }

        /// <summary>Match the sheet to the list on the Revit ID - never on position.</summary>
        public static ImportPlan PlanImport(VmCore.EditStore store, IList<VmCore.Field> fields, Dictionary<int, Dictionary<int, string>> grid)
        {
            var plan = new ImportPlan();
            int headerRow = 0;
            int idCol = -1;
            foreach (int rowNumber in grid.Keys.OrderBy(k => k).Take(12))
            {
                foreach (KeyValuePair<int, string> kv in grid[rowNumber].OrderBy(k => k.Key))
                {
                    if (kv.Value.Trim().ToLowerInvariant().StartsWith(IdHeader.ToLowerInvariant()))
                    {
                        headerRow = rowNumber;
                        idCol = kv.Key;
                        break;
                    }
                }
                if (idCol >= 0) break;
            }
            if (idCol < 0)
                throw new InvalidOperationException("No '" + IdHeader + "' column was found - this is not a sheet the Push to Excel button wrote.");
            plan.HeaderRow = headerRow;
            var byLabel = new Dictionary<string, VmCore.Field>();
            foreach (VmCore.Field f in fields) byLabel[f.Label.Trim().ToLowerInvariant()] = f;
            var columns = new Dictionary<int, VmCore.Field>();
            foreach (KeyValuePair<int, string> kv in grid[headerRow].OrderBy(k => k.Key))
            {
                if (kv.Key == idCol) continue;
                string label = kv.Value.Trim().ToLowerInvariant();
                VmCore.Field f;
                if (byLabel.TryGetValue(label, out f)) columns[kv.Key] = f;
                else plan.UnknownHeaders.Add(kv.Value.Trim());
            }
            plan.MatchedColumns = columns.OrderBy(k => k.Key).Select(k => k.Value.Label).ToList();
            var present = new HashSet<string>(columns.Values.Select(f => f.Key));
            plan.MissingColumns = fields.Where(f => !present.Contains(f.Key) && f.Key != "vid").Select(f => f.Label).ToList();
            var seen = new HashSet<long>();
            foreach (int rowNumber in grid.Keys.OrderBy(k => k))
            {
                if (rowNumber <= headerRow) continue;
                Dictionary<int, string> cells = grid[rowNumber];
                string raw;
                if (!cells.TryGetValue(idCol, out raw)) continue;
                raw = raw.Trim();
                if (raw.Length == 0) continue;
                double parsed;
                if (!double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out parsed)) continue;
                long viewId = (long)parsed;
                plan.RowsRead++;
                if (!seen.Add(viewId)) continue;
                if (!store.Rows.ContainsKey(viewId))
                {
                    plan.UnknownIds.Add(viewId);
                    continue;
                }
                foreach (KeyValuePair<int, VmCore.Field> kv in columns)
                {
                    string cell;
                    string @new = VmCore.CleanValue(cells.TryGetValue(kv.Key, out cell) ? cell : "");
                    string old = store.Effective(viewId, kv.Value.Key);
                    if (@new == old) continue;
                    if (!kv.Value.Writable)
                    {
                        plan.IgnoredCells++;
                        continue;
                    }
                    string why = store.BasicCheck(viewId, kv.Value.Key, @new);
                    if (why.Length > 0)
                    {
                        plan.Refused.Add(new Refusal { ViewId = viewId, Label = kv.Value.Label, Why = why });
                        continue;
                    }
                    plan.Changes.Add(new Change { ViewId = viewId, Key = kv.Value.Key, Old = old, New = @new });
                }
            }
            return plan;
        }

        /// <summary>The text of the report shown before an import stages anything.</summary>
        public static string ImportReport(ImportPlan plan, VmCore.EditStore store, int limit = 14)
        {
            int views = plan.Changes.Select(c => c.ViewId).Distinct().Count();
            var lines = new List<string>();
            if (plan.Changes.Count > 0)
            {
                lines.Add(plan.Changes.Count + " change(s) in " + views + " view(s) will be staged. Nothing is written to the model until you press Apply.");
                lines.Add("");
                foreach (Change c in plan.Changes.Take(limit))
                {
                    VmCore.RefRow row;
                    string label = store.Rows.TryGetValue(c.ViewId, out row) ? row.Get("name") : "";
                    VmCore.Field field = VmCore.FieldFromKey(c.Key);
                    lines.Add("  " + label + " / " + (field != null ? field.Label : c.Key) + ":  '" + c.Old + "'  ->  '" + c.New + "'");
                }
                if (plan.Changes.Count > limit) lines.Add("  ... and " + (plan.Changes.Count - limit) + " more");
            }
            else lines.Add("Nothing in the sheet differs from the list, so there is nothing to stage.");
            var notes = new List<string>();
            if (plan.Refused.Count > 0) notes.Add(plan.Refused.Count + " cell(s) were refused - e.g. " + plan.Refused[0].Label + ": " + plan.Refused[0].Why);
            if (plan.IgnoredCells > 0) notes.Add(plan.IgnoredCells + " edited cell(s) are in read-only columns and were ignored.");
            if (plan.UnknownIds.Count > 0) notes.Add(plan.UnknownIds.Count + " row(s) have a Revit ID that is not in this list (deleted, or filtered out of the list).");
            if (plan.UnknownHeaders.Count > 0) notes.Add("Columns not in the grid were ignored: " + string.Join(", ", plan.UnknownHeaders.Take(6)) + ".");
            if (notes.Count > 0)
            {
                lines.Add("");
                lines.AddRange(notes);
            }
            return string.Join("\n", lines);
        }
    }
}
