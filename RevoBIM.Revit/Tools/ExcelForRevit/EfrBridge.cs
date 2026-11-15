using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ExcelForRevit
{
    // The two Excel exports and the import that comes back. Port of excel_bridge.py.
    //
    // Nothing in here touches the Revit API: it is handed plain values by the caller and hands
    // back plain values.
    //
    // Round trip writes a key block (element id; the schedule name and a stamp on a second sheet)
    // and one column per field, coloured the way the grid colours them. Coming back, rows are
    // matched on the element id rather than on position, so sorting or filtering the sheet in
    // Excel (the whole point of exporting a list) cannot scramble the import.
    //
    // Presentation writes what the schedule looks like: a title band, headers, borders, banded
    // rows, sensible widths and wrapped text, and no key block. It is one-directional by design;
    // there is nothing in it to match on.

    /// <summary>One column of the export (Python's dict {'name','letter','is_type','editable','reason'}).</summary>
    public class ExportField
    {
        public string Name = "";
        public string Letter = "";
        public bool IsType;
        public bool Editable;
        public string Reason = "";

        public ExportField() { }

        public ExportField(string name, string letter, bool isType, bool editable, string reason = "")
        {
            Name = name;
            Letter = letter;
            IsType = isType;
            Editable = editable;
            Reason = reason;
        }
    }

    /// <summary>One row of the export (Python's dict {'eid','values','editable','is_type'}).</summary>
    public class ExportRow
    {
        /// <summary>The element id as text.</summary>
        public string Eid = "";
        public List<string> Values = new List<string>();
        public List<bool> Editable = new List<bool>();
        public List<bool> IsType = new List<bool>();
    }

    /// <summary>What an import would do. Nothing has been written when you get this.</summary>
    public class ImportResult
    {
        public List<(string Eid, int FieldIndex, string Old, string New)> Changes =
            new List<(string, int, string, string)>();
        public int Unchanged;
        public List<(string Eid, string FieldName)> SkippedReadonly = new List<(string, string)>();
        public List<string> UnmatchedRows = new List<string>();     // eid or row label
        public List<string> UnmatchedCols = new List<string>();     // header text
        public List<(string Header, int FieldIndex)> MatchedCols = new List<(string, int)>();
        public List<string> Errors = new List<string>();
        public int RowsSeen;

        public bool Ok
        {
            get { return Errors.Count == 0; }
        }
    }

    public static class ExcelBridge
    {
        public const string MARKER = "RevoBIM Excel for Revit";
        public const string KEY_HEADER = "Revit ID";
        public const string ROW_HEADER = "#";

        // how wide a column is allowed to get before the text wraps instead
        public const double MIN_WIDTH = 9.0;
        public const double MAX_WIDTH = 46.0;

        // ------------------------------------------------------------ palettes --
        // Excel is always read on white, so the round-trip colours are the light palette's,
        // not the dark one's. The key is that they match the *meaning* of the grid's colours,
        // not their exact hex.

        public static readonly Dictionary<string, string> XL = new Dictionary<string, string>
        {
            { "inst_bg", "D9E9F8" }, { "inst_fg", "13507F" },
            { "type_bg", "FBE7CC" }, { "type_fg", "8A4E07" },
            { "ro_bg", "F5DDDB" }, { "ro_fg", "8E3733" },
            { "key_bg", "ECECF0" }, { "key_fg", "5A5A62" },
            { "head_bg", "1F3D57" }, { "head_fg", "FFFFFF" },
            { "inst_head", "2E6EA6" }, { "type_head", "B96A12" }, { "ro_head", "A24540" },
            { "title_bg", "17293A" }, { "title_fg", "FFFFFF" },
            { "band", "F7F9FC" }, { "plain", "FFFFFF" },
            { "edge", "C6CBD2" },
            { "note_fg", "5A5A62" },
        };

        public static int TextWidth(string value)
        {
            return value != null ? value.Length : 0;
        }

        /// <summary>Column width from the content, clamped so nothing runs off the page.</summary>
        public static double Measure(string header, IEnumerable<string> values, double cap = MAX_WIDTH)
        {
            int widest = TextWidth(header);
            foreach (string v in values)
                widest = Math.Max(widest, TextWidth(v));
            return Math.Max(MIN_WIDTH, Math.Min(cap, widest * 1.15 + 3.5));
        }

        public static string Sanitize(string name)
        {
            return XlsxIo.SheetNameSafe(name);
        }

        static string ValueAt(ExportRow row, int i)
        {
            return i < row.Values.Count ? row.Values[i] : "";
        }

        static List<string> Column(List<ExportRow> rows, int i)
        {
            return rows.Select(r => ValueAt(r, i)).ToList();
        }

        static List<SheetCell> Repeat(SheetCell cell, int count)
        {
            // the same cell object repeated is fine: cells are only read when written
            var list = new List<SheetCell>();
            for (int i = 0; i < count; i++)
                list.Add(cell);
            return list;
        }

        // ================================================================ export ==

        /// <summary>
        /// Sheet 1 a flat list with a key column; sheet 2 the legend and the stamp.
        /// Returns the number of rows written.
        /// </summary>
        public static int ExportRoundTrip(string path, string scheduleName, List<ExportField> fields,
                                          List<ExportRow> rows, string docTitle = "")
        {
            var wb = new Workbook();
            var st = wb.Styles;

            int headKey = st.Cell(XL["head_fg"], XL["head_bg"], 11, true, align: "center", wrap: true);
            int headInst = st.Cell("FFFFFF", XL["inst_head"], 11, true, align: "center", wrap: true);
            int headType = st.Cell("FFFFFF", XL["type_head"], 11, true, align: "center", wrap: true);
            int headRo = st.Cell("FFFFFF", XL["ro_head"], 11, true, align: "center", wrap: true);

            int keyStyle = st.Cell(XL["key_fg"], XL["key_bg"], 11, false, align: "center");
            int idxStyle = st.Cell(XL["key_fg"], XL["key_bg"], 11, false, align: "center");
            int instStyle = st.Cell(XL["inst_fg"], XL["inst_bg"], 11, wrap: true, align: "left");
            int typeStyle = st.Cell(XL["type_fg"], XL["type_bg"], 11, wrap: true, align: "left");
            int roStyle = st.Cell(XL["ro_fg"], XL["ro_bg"], 11, italic: true, wrap: true, align: "left");

            var sheet = wb.Sheet(Sanitize(!string.IsNullOrEmpty(scheduleName) ? scheduleName : "Schedule"));

            var header = new List<SheetCell>
            {
                new SheetCell(ROW_HEADER, headKey, false),
                new SheetCell(KEY_HEADER, headKey, false),
            };
            foreach (var f in fields)
            {
                int style;
                if (f.IsType)
                    style = headType;
                else if (!f.Editable)
                    style = headRo;
                else
                    style = headInst;
                header.Add(new SheetCell(f.Name, style, false));
            }
            sheet.AddRow(header, 34);

            for (int n = 0; n < rows.Count; n++)
            {
                var row = rows[n];
                var cells = new List<SheetCell>
                {
                    new SheetCell((n + 1).ToString(CultureInfo.InvariantCulture), idxStyle, true),
                    new SheetCell(row.Eid, keyStyle, true),
                };
                for (int i = 0; i < fields.Count; i++)
                {
                    string value = ValueAt(row, i);
                    bool editable = i < row.Editable.Count ? row.Editable[i] : false;
                    bool isType = i < row.IsType.Count ? row.IsType[i] : false;
                    int style;
                    if (!editable)
                        style = roStyle;
                    else if (isType)
                        style = typeStyle;
                    else
                        style = instStyle;
                    cells.Add(new SheetCell(value, style, false));
                }
                sheet.AddRow(cells);
            }

            sheet.Width(0, 5.5);
            sheet.Width(1, 12.0);
            for (int i = 0; i < fields.Count; i++)
                sheet.Width(i + 2, Measure(fields[i].Name, Column(rows, i)));
            sheet.Freeze = (1, 2);
            sheet.Autofilter = (0, 0, Math.Max(0, rows.Count), fields.Count + 1);

            LegendSheet(wb, st, scheduleName, fields, rows, docTitle, true);
            wb.Save(path);
            return rows.Count;
        }

        /// <summary>What the schedule looks like, for issuing. Nothing to import back. Returns the row count.</summary>
        public static int ExportPresentation(string path, string scheduleName, List<ExportField> fields,
                                             List<ExportRow> rows, string docTitle = "")
        {
            var wb = new Workbook();
            var st = wb.Styles;

            int titleStyle = st.Cell(XL["title_fg"], XL["title_bg"], 16, true, border: false, align: "left");
            int subStyle = st.Cell(XL["note_fg"], null, 10, false, border: false, align: "left");
            int headStyle = st.Cell("FFFFFF", XL["head_bg"], 11, true, align: "center", wrap: true);
            int plain = st.Cell("1F1F23", XL["plain"], 11, wrap: true, align: "left");
            int band = st.Cell("1F1F23", XL["band"], 11, wrap: true, align: "left");
            int plainNum = st.Cell("1F1F23", XL["plain"], 11, align: "right");
            int bandNum = st.Cell("1F1F23", XL["band"], 11, align: "right");

            var sheet = wb.Sheet(Sanitize(!string.IsNullOrEmpty(scheduleName) ? scheduleName : "Schedule"));

            int width = Math.Max(1, fields.Count);
            var titleRow = new List<SheetCell> { new SheetCell(!string.IsNullOrEmpty(scheduleName) ? scheduleName : "Schedule", titleStyle, false) };
            titleRow.AddRange(Repeat(new SheetCell(null, titleStyle, false), width - 1));
            sheet.AddRow(titleRow, 30);
            sheet.Merges.Add((0, 0, 0, width - 1));
            string stamp = docTitle ?? "";
            var stampRow = new List<SheetCell> { new SheetCell(stamp, subStyle, false) };
            stampRow.AddRange(Repeat(new SheetCell(null, subStyle, false), width - 1));
            sheet.AddRow(stampRow, 16);
            sheet.Merges.Add((1, 0, 1, width - 1));
            sheet.AddRow(new List<SheetCell>());

            sheet.AddRow(fields.Select(f => new SheetCell(f.Name, headStyle, false)).ToList(), 34);

            var numericCol = new List<bool>();
            for (int i = 0; i < fields.Count; i++)
            {
                var filled = Column(rows, i).Where(v => !string.IsNullOrEmpty(v) && v.Trim().Length > 0).ToList();
                numericCol.Add(filled.Count > 0 && filled.All(v => XlsxIo.LooksNumeric(v)));
            }

            for (int n = 0; n < rows.Count; n++)
            {
                var row = rows[n];
                bool striped = (n % 2) == 1;
                var cells = new List<SheetCell>();
                for (int i = 0; i < fields.Count; i++)
                {
                    string value = ValueAt(row, i);
                    int style;
                    if (numericCol[i])
                        style = striped ? bandNum : plainNum;
                    else
                        style = striped ? band : plain;
                    cells.Add(new SheetCell(value, style, numericCol[i]));
                }
                sheet.AddRow(cells);
            }

            for (int i = 0; i < fields.Count; i++)
                sheet.Width(i, Measure(fields[i].Name, Column(rows, i)));
            sheet.Freeze = (4, 0);
            sheet.Autofilter = (3, 0, 3 + rows.Count, Math.Max(0, fields.Count - 1));

            wb.Save(path);
            return rows.Count;
        }

        /// <summary>Sheet 2: what the colours mean, and the stamp the import checks.</summary>
        public static Sheet LegendSheet(Workbook wb, Styles st, string scheduleName, List<ExportField> fields,
                                        List<ExportRow> rows, string docTitle, bool roundTrip)
        {
            var sheet = wb.Sheet("RevoBIM");
            int title = st.Cell(XL["title_fg"], XL["title_bg"], 14, true, border: false);
            int key = st.Cell("1F1F23", null, 11, true, border: false);
            int val = st.Cell(XL["note_fg"], null, 11, false, border: false, wrap: true);
            int note = st.Cell(XL["note_fg"], null, 10, italic: true, border: false, wrap: true);

            sheet.AddRow(new List<SheetCell> { new SheetCell(MARKER, title, false), new SheetCell(null, title, false) }, 26);
            sheet.Merges.Add((0, 0, 0, 1));
            sheet.AddRow(new List<SheetCell>());
            var inv = CultureInfo.InvariantCulture;
            var labels = new[]
            {
                new KeyValuePair<string, string>("Schedule", scheduleName ?? ""),
                new KeyValuePair<string, string>("Model", docTitle ?? ""),
                new KeyValuePair<string, string>("Columns", fields.Count.ToString(inv)),
                new KeyValuePair<string, string>("Rows", rows.Count.ToString(inv)),
                new KeyValuePair<string, string>("Layout", roundTrip ? "Round trip" : "Presentation"),
            };
            foreach (var pair in labels)
                sheet.AddRow(new List<SheetCell> { new SheetCell(pair.Key, key, false), new SheetCell(pair.Value, val, false) });

            sheet.AddRow(new List<SheetCell>());
            sheet.AddRow(new List<SheetCell> { new SheetCell("Cell colours", key, false) });
            var swatches = new[]
            {
                new[] { "Instance parameter", XL["inst_bg"], XL["inst_fg"],
                        "Editable. Changing it affects this element only." },
                new[] { "Type parameter", XL["type_bg"], XL["type_fg"],
                        "Editable. Changing it affects every element of that type." },
                new[] { "Not editable", XL["ro_bg"], XL["ro_fg"],
                        "Read only in Revit. Edits to these cells are ignored on import." },
                new[] { "Key columns", XL["key_bg"], XL["key_fg"],
                        "Used to match rows on the way back. Do not edit or delete them." },
            };
            foreach (var s in swatches)
            {
                int chip = st.Cell(s[2], s[1], 11, true, border: true, align: "center");
                sheet.AddRow(new List<SheetCell> { new SheetCell(s[0], chip, false), new SheetCell(s[3], val, false) });
            }

            sheet.AddRow(new List<SheetCell>());
            string text;
            if (roundTrip)
                text = "Edit the coloured value columns and save the file, then use " +
                       "Import from Excel in the tool. Rows are matched on Revit ID, " +
                       "so sorting and filtering this sheet is safe. Adding rows, " +
                       "deleting the ID column or renaming the value headers is not.";
            else
                text = "This is a presentation export. It carries no Revit IDs and " +
                       "cannot be imported back — use the round-trip export for that.";
            sheet.AddRow(new List<SheetCell> { new SheetCell(text, note, false), new SheetCell(null, note, false) }, 46);
            sheet.Merges.Add((sheet.Rows.Count - 1, 0, sheet.Rows.Count - 1, 1));
            sheet.Width(0, 22.0);
            sheet.Width(1, 64.0);
            return sheet;
        }

        // ================================================================ import ==

        static readonly Regex NotAlnum = new Regex("[^a-z0-9]", RegexOptions.Compiled);

        /// <summary>Compare headers loosely: case, spacing and punctuation should not matter.</summary>
        public static string NormHeader(string text)
        {
            return NotAlnum.Replace((text ?? "").ToLowerInvariant(), "");
        }

        /// <summary>
        /// Match a sheet back onto the model.
        /// table: rows of strings straight from <see cref="XlsxIo.ReadSheet(string,int)"/>;
        /// fields: the export's field list; rowsByEid: {eid text: the exported row}.
        /// Nothing is written here: it returns what *would* change, and the caller stages it.
        /// </summary>
        public static ImportResult ParseImport(List<List<string>> table, List<ExportField> fields,
                                               Dictionary<string, ExportRow> rowsByEid)
        {
            var res = new ImportResult();
            if (table == null || table.Count == 0)
            {
                res.Errors.Add("That file has no rows in it.");
                return res;
            }

            List<string> header = null;
            int headerAt = -1;
            string keyNorm = NormHeader(KEY_HEADER);
            for (int i = 0; i < table.Count && i < 10; i++)
            {
                var cells = table[i].Select(NormHeader).ToList();
                if (cells.Contains(keyNorm))
                {
                    header = table[i];
                    headerAt = i;
                    break;
                }
            }
            if (header == null)
            {
                res.Errors.Add(
                    "No \"" + KEY_HEADER + "\" column found in the first ten rows. This looks like a " +
                    "presentation export or a file from somewhere else — only the " +
                    "round-trip export can be imported.");
                return res;
            }

            int keyCol = -1;
            for (int i = 0; i < header.Count; i++)
            {
                if (NormHeader(header[i]) == keyNorm)
                {
                    keyCol = i;
                    break;
                }
            }

            var byNorm = new Dictionary<string, int>(StringComparer.Ordinal);
            for (int i = 0; i < fields.Count; i++)
            {
                string norm = NormHeader(fields[i].Name);
                if (!byNorm.ContainsKey(norm))
                    byNorm[norm] = i;
            }

            // column order is kept ascending, as the Python's small-int dict iterates
            var colMap = new SortedDictionary<int, int>();
            string rowNorm = NormHeader(ROW_HEADER);
            for (int i = 0; i < header.Count; i++)
            {
                if (i == keyCol)
                    continue;
                string cell = header[i];
                string norm = NormHeader(cell);
                if (norm.Length == 0 || norm == rowNorm)
                    continue;
                int fidx;
                if (byNorm.TryGetValue(norm, out fidx))
                {
                    colMap[i] = fidx;
                    res.MatchedCols.Add((cell, fidx));
                }
                else
                {
                    res.UnmatchedCols.Add(cell);
                }
            }

            if (colMap.Count == 0)
            {
                res.Errors.Add("None of the column headings match this schedule. " +
                               "Was this exported from a different schedule?");
                return res;
            }

            var seen = new HashSet<string>(StringComparer.Ordinal);
            for (int ri = headerAt + 1; ri < table.Count; ri++)
            {
                var row = table[ri];
                if (keyCol >= row.Count)
                    continue;
                string eid = (row[keyCol] ?? "").Trim();
                if (eid.Length == 0)
                {
                    if (row.Any(c => (c ?? "").Trim().Length > 0))
                        res.UnmatchedRows.Add("(row with no Revit ID)");
                    continue;
                }
                res.RowsSeen += 1;
                if (seen.Contains(eid))
                {
                    res.UnmatchedRows.Add(eid + " (listed twice)");
                    continue;
                }
                seen.Add(eid);
                ExportRow modelRow;
                if (!rowsByEid.TryGetValue(eid, out modelRow) || modelRow == null)
                {
                    res.UnmatchedRows.Add(eid);
                    continue;
                }
                foreach (var pair in colMap)
                {
                    int col = pair.Key, fidx = pair.Value;
                    if (col >= row.Count)
                        continue;
                    string newValue = row[col] ?? "";
                    string oldValue = fidx < modelRow.Values.Count ? (modelRow.Values[fidx] ?? "") : "";
                    if (string.Equals(newValue, oldValue, StringComparison.Ordinal))
                    {
                        res.Unchanged += 1;
                        continue;
                    }
                    bool editable = fidx < modelRow.Editable.Count ? modelRow.Editable[fidx] : false;
                    if (!editable)
                    {
                        res.SkippedReadonly.Add((eid, fields[fidx].Name));
                        continue;
                    }
                    res.Changes.Add((eid, fidx, oldValue, newValue));
                }
            }
            return res;
        }
    }
}
