using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ProSheets
{
    /// <summary>
    /// The Document Register as an Excel workbook, laid out as the BGL RD9 sheet.
    /// Port of ps_regexport.py.
    ///
    /// Cell for cell the office's own RD9 - Document Register &amp; Issue Sheet form
    /// (1.44.0 brought the layout, 1.45.0 the RD9 title back):
    ///   1-2   the title band: the title, then the company logo and the client logo
    ///   3-5   Project No: / Project Title: with Day / Month / Year beside them, and
    ///         each issue's date up its column
    ///   6-7   Issue Status: and each issue's status (S3, S4...), the legend under
    ///   8..   Issued to: - a row per Issued To column of the Revision Manager, then
    ///         one per Method column, x where the revision is ticked; a column
    ///         nothing on the worksheet is ticked in is left off
    ///   then  Document No / Document Title / Sheet Size / Scale / Current Rev /
    ///         Document Issued
    ///   below the discipline, then the drawings, a blank row between series
    ///   last  the footer line, boxed
    ///
    /// Current Rev - every drawing's current revision - is the orange column before
    /// the issues. The form keeps at least MinIssueColumns issue columns, blank
    /// ones included, so it has room for the next issues and the same shape from
    /// one issue to the next.
    ///
    /// One worksheet per discipline, each carrying only the revision columns its own
    /// drawings use. Rows 1 to the column headings repeat on every printed page; the
    /// print area is the form and nothing else; A4 portrait, fitted to the width.
    ///
    /// Start from the paper form, not from the grid: a register that looks like the
    /// one the office already sends is adopted.
    ///
    /// Nothing here reads Revit. The register tab hands over what it has already
    /// read, which lets it run from a plain button press as well as from inside an
    /// export run.
    /// </summary>
    public static partial class PsRegExport
    {
        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        // Column positions: four drawing columns, Current Rev (unless its heading
        // is blank), then the issues.
        public const int ColNumber = 1, ColTitle = 2, ColSize = 3, ColScale = 4;
        public const int ColCurrent = 5;
        // Blank issue columns are added up to this many, as on the paper form.
        public const int MinIssueColumns = 24;

        // The TIDP form's colours. LabelFill is Project No / Title's own blue; the
        // headings are the theme's Text 2 at 90% lighter, written as RGB.
        public const string TitleBlue = "FF35607A";
        public const string LabelFill = "FFDDEBF7";
        public const string HeadFill = "FFDCEAF7";
        public const string CurrentFill = "FFFFC000";
        public const string CurrentInk = "FF0E2841";      // the theme's Text 2, on the orange
        public const string Black = "FF000000";
        public const string TitleFont = "Gadugi";
        public const string CurrentFont = "Arial";

        // Widths in characters and heights in points, from the form.
        public static readonly Dictionary<int, double> Widths = new Dictionary<int, double>
        {
            [ColNumber] = 34.0, [ColTitle] = 48.0, [ColSize] = 12.44,
            [ColScale] = 6.11, [ColCurrent] = 3.89,
        };
        public const double IssueWidth = 3.55;
        public static readonly (double Title, double Logo) BandHeights = (96.75, 35.25);
        public static readonly Dictionary<int, double> TopHeights = new Dictionary<int, double>
        {
            [3] = 18, [4] = 18, [5] = 17.4, [6] = 13.8, [7] = 17.4,
        };
        public const double HeadHeight = 63;
        public const double FooterHeight = 34.5;
        public const double RowHeight = 15;

        // The largest a logo is drawn, in pixels, and the gaps around it.
        public static readonly (int Width, int Height) LogoBox = (300, 168);
        public const int LogoGap = 24;

        public const string DefaultTitle = "RD9 - Document Register & Issue Sheet";
        public static readonly string[] DefaultLegend =
        {
            "S0 = WIP", "S1 = Coordination", "S2 = Information",
            "S3 = Review/Comment", "S4 = Stage Approval", "S5 = Authorisation",
        };
        public const string DefaultSnapshot = "Current Rev";
        public const string DefaultPaper = "A4 portrait";

        public static readonly Dictionary<string, int> Months = new Dictionary<string, int>(StringComparer.Ordinal)
        {
            ["jan"] = 1, ["feb"] = 2, ["mar"] = 3, ["apr"] = 4, ["may"] = 5, ["jun"] = 6,
            ["jul"] = 7, ["aug"] = 8, ["sep"] = 9, ["oct"] = 10, ["nov"] = 11, ["dec"] = 12,
        };

        /// <summary>Everything the form needs that is not a sheet or a revision.</summary>
        public class Info
        {
            public string Title = DefaultTitle;
            public string Logo = "";              // the company's, from Setup
            public string ClientLogo = "";        // the client's, from Setup
            public List<string> Legend = new List<string>(DefaultLegend);
            public string Footer = "";
            public string Paper = DefaultPaper;
            // The heading of the Current Rev column, every drawing's current
            // revision. Blank leaves the column off.
            public string Snapshot = DefaultSnapshot;
            public string ProjectNumber = "";
            public string ProjectName = "";
            public string ModelName = "";
            public string SeriesParam = "";
            // As on the register tab: only the revisions the worksheet's own
            // drawings carry, or every revision in the project.
            public bool HideUnused = true;
            // Disciplines unticked on the tab strip: no worksheet for them.
            public HashSet<string> Skip = new HashSet<string>();
            // The Revision Manager's own columns and values, by revision
            // UniqueId: the Issued To / Method rows and each Issue Status.
            // RevisionValues is {revision UniqueId: {column id: stored value}}.
            public List<PsRevData.Column> RevisionColumns = new List<PsRevData.Column>();
            public Dictionary<string, Dictionary<string, string>> RevisionValues =
                new Dictionary<string, Dictionary<string, string>>();
        }

        // ==========================================================================
        // pure decisions
        // ==========================================================================

        internal static readonly Regex Iso = new Regex(@"^\s*([0-9]{4})[-/.]([0-9]{1,2})[-/.]([0-9]{1,2})\s*$");
        internal static readonly Regex Uk = new Regex(@"^\s*([0-9]{1,2})[-/.]([0-9]{1,2})[-/.]([0-9]{2,4})\s*$");
        internal static readonly Regex Words = new Regex(@"^\s*([0-9]{1,2})(?:st|nd|rd|th)?[\s.-]*([A-Za-z]{3,})" +
                                                         @"\.?[\s,.-]*([0-9]{2,4})\s*$");

        /// <summary>(day, month, two-digit year) from a revision date as typed, or null.
        ///
        /// Revit holds the revision date as free text, so it is whatever the office
        /// types: 01/02/26, 01.02.2026, 2026-02-01, 1 Feb 2026. Day first, because
        /// this is a UK register; ISO is recognised by its four digit year at the
        /// front. Anything else is shown as typed rather than guessed.</summary>
        public static (int Day, int Month, int Year)? ParseDate(string text)
        {
            text = text ?? "";
            int? day = null, month = null, year = null;
            var match = Iso.Match(text);
            if (match.Success)
            {
                year = int.Parse(match.Groups[1].Value, Inv);
                month = int.Parse(match.Groups[2].Value, Inv);
                day = int.Parse(match.Groups[3].Value, Inv);
            }
            else
            {
                match = Uk.Match(text);
                if (match.Success)
                {
                    day = int.Parse(match.Groups[1].Value, Inv);
                    month = int.Parse(match.Groups[2].Value, Inv);
                    year = int.Parse(match.Groups[3].Value, Inv);
                }
                else
                {
                    match = Words.Match(text);
                    if (match.Success)
                    {
                        day = int.Parse(match.Groups[1].Value, Inv);
                        if (Months.TryGetValue(match.Groups[2].Value.Substring(0, 3).ToLowerInvariant(), out int found))
                            month = found;
                        year = int.Parse(match.Groups[3].Value, Inv);
                    }
                }
            }
            if (day == null || month == null || year == null)
                return null;
            if (!(1 <= day && day <= 31 && 1 <= month && month <= 12))
                return null;
            return (day.Value, month.Value, year.Value % 100);
        }

        /// <summary>An issue's date as it runs up its column: dd/mm/yy where it can be
        /// read, as typed where it cannot.</summary>
        public static string DateText(string text)
        {
            var found = ParseDate(text);
            if (found == null)
                return (text ?? "").Trim();
            return string.Format(Inv, "{0:00}/{1:00}/{2:00}", found.Value.Day, found.Value.Month, found.Value.Year);
        }

        /// <summary>{revision key: the status printed over its column}.
        ///
        /// The Revision Manager's Issue Status where one is stored - kept with the
        /// revision, so an old issue keeps its status - and otherwise the status
        /// most of the drawings carrying it have now.</summary>
        public static Dictionary<string, string> IssueStatuses(IEnumerable<PsRegister.RevisionColumn> revisions,
                                                               IEnumerable<PsRegister.RegisterRow> rows, Info info)
        {
            var column = PsRevData.StatusColumn(info.RevisionColumns);
            var rowList = rows.ToList();
            var found = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var revision in revisions)
            {
                string stored = "";
                if (column != null)
                    stored = Value(ValuesOf(info, revision.Uid), column.Id).Trim();
                if (stored.Length == 0)
                {
                    stored = CommonStatus(rowList
                        .Where(row => !string.IsNullOrEmpty(row.Cells.TryGetValue(revision.Key, out var cell) ? cell : null))
                        .Select(row => row.Status));
                }
                found[revision.Key] = stored;
            }
            return found;
        }

        /// <summary>info.revision_values.get(uid) or {}.</summary>
        internal static Dictionary<string, string> ValuesOf(Info info, string uid)
        {
            if (uid != null && info.RevisionValues != null &&
                info.RevisionValues.TryGetValue(uid, out var values) && values != null)
                return values;
            return new Dictionary<string, string>();
        }

        private static string Value(Dictionary<string, string> values, string key)
        {
            return key != null && values.TryGetValue(key, out var value) ? value ?? "" : "";
        }

        /// <summary>The most common status; ties to the first seen; blanks ignored.</summary>
        public static string CommonStatus(IEnumerable<string> texts)
        {
            var counts = new Dictionary<string, int>(StringComparer.Ordinal);
            var order = new List<string>();
            foreach (var raw in texts)
            {
                string text = (raw ?? "").Trim();
                if (text.Length == 0)
                    continue;
                if (!counts.ContainsKey(text))
                {
                    order.Add(text);
                    counts[text] = 0;
                }
                counts[text] += 1;
            }
            if (order.Count == 0)
                return "";
            return order.OrderBy(one => -counts[one]).ThenBy(one => order.IndexOf(one)).First();
        }

        /// <summary>The "Issued to:" rows for a worksheet's issue columns:
        /// [(name, group, [ticked per issue])], Issued To then Method, leaving out
        /// any column none of these issues is ticked in.</summary>
        public static List<(string Name, string Group, List<bool> Ticks)> IssuedRows(
            IEnumerable<PsRegister.RevisionColumn> revisions, Info info)
        {
            var list = revisions.ToList();
            var values = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
            foreach (var revision in list)
                values[revision.Key] = ValuesOf(info, revision.Uid);
            var result = new List<(string Name, string Group, List<bool> Ticks)>();
            foreach (var one in PsRevData.IssueRows(info.RevisionColumns, values, list.Select(r => r.Key).ToList()))
            {
                var (name, group, ticks) = one;
                result.Add((name, group, ticks.ToList()));
            }
            return result;
        }

        /// <summary>[(name, rows)] - one per discipline, or one for everything.
        ///
        /// On paper the register is split by discipline. The All tab gets a
        /// worksheet of its own - first, every discipline under its own heading -
        /// only when it is ticked on the tab strip (1.46.0). A discipline unticked
        /// there gets no worksheet, and neither does one with nothing in the
        /// register.</summary>
        public static List<(string Name, List<PsRegister.RegisterRow> Rows)> Worksheets(
            IEnumerable<PsRegister.RegisterRow> rows, IEnumerable<string> skip = null)
        {
            var skipped = new HashSet<string>(skip ?? Enumerable.Empty<string>());
            var all = rows.ToList();
            var tabs = PsRegister.DisciplineTabs(all);
            if (tabs.Count == 1)
            {
                return all.Count > 0
                    ? new List<(string Name, List<PsRegister.RegisterRow> Rows)> { ("Register", new List<PsRegister.RegisterRow>(all)) }
                    : new List<(string Name, List<PsRegister.RegisterRow> Rows)>();
            }
            var output = tabs.Where(tab => tab.Label != PsRegister.AllTab && !skipped.Contains(tab.Label) &&
                                           tab.Rows.Count > 0)
                             .Select(tab => (tab.Label, tab.Rows))
                             .ToList();
            if (PsRegister.AllTicked(skipped) && all.Count > 0)
                output.Insert(0, (PsRegister.AllTab, new List<PsRegister.RegisterRow>(all)));
            return output;
        }

        /// <summary>A column width in characters that fits the longest text.</summary>
        public static double TextWidth(IEnumerable<string> texts, double floor, double ceiling)
        {
            int longest = texts.Select(text => (text ?? "").Length).DefaultIfEmpty(0).Max();
            return Math.Max(floor, Math.Min(ceiling, longest * 1.05 + 2));
        }

        /// <summary>(Excel paper code, landscape) from a setting like 'A4 portrait'.
        ///
        /// The size alone - how the setting was kept before 1.24.0 - is portrait,
        /// the form's own orientation.</summary>
        public static (int Paper, bool Landscape) PaperSetup(string text)
        {
            var words = (text ?? "").ToUpperInvariant()
                .Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            var size = words.Where(word => PsXlsx.Paper.ContainsKey(word)).ToList();
            return (size.Count > 0 ? PsXlsx.Paper[size[0]] : PsXlsx.Paper["A4"],
                    words.Contains("LANDSCAPE"));
        }

        /// <summary>[(x, y, width, height)] for logos laid left to right in the band.
        ///
        /// Each is scaled to fit box keeping its shape, centred top to bottom,
        /// starting at start with gap between. Where the row would run past
        /// rightEdge - a narrow form - they are all shrunk together, so neither
        /// lands outside the print area. box null is LogoBox, gap null is LogoGap.</summary>
        public static List<(int X, int Y, int Width, int Height)?> FitLogos(
            IEnumerable<(int Width, int Height)?> sizes, double start, double rightEdge, double bandHeight,
            (int Width, int Height)? box = null, int? gap = null)
        {
            var boxSize = box ?? LogoBox;
            int gapSize = gap ?? LogoGap;
            var sizeList = sizes.ToList();
            var fitted = new List<(double Width, double Height)?>();
            foreach (var size in sizeList)
            {
                if (size == null || size.Value.Width == 0 || size.Value.Height == 0)
                {
                    fitted.Add(null);
                    continue;
                }
                double width = size.Value.Width, height = size.Value.Height;
                double scale = Math.Min((double)boxSize.Width / width,
                                        Math.Min(boxSize.Height, bandHeight - 8) / height);
                fitted.Add((width * scale, height * scale));
            }
            var shown = fitted.Where(size => size != null).Select(size => size.Value).ToList();
            if (shown.Count == 0)
                return sizeList.Select(_ => ((int, int, int, int)?)null).ToList();
            double need = shown.Sum(size => size.Width) + gapSize * (shown.Count - 1);
            double room = rightEdge - start - 8;
            double shrink = 1.0;
            if (need > room && room > 0)
                shrink = room / need;
            else if (room <= 0)
                shrink = 0.25;
            var placed = new List<(int X, int Y, int Width, int Height)?>();
            double x = start;
            foreach (var size in fitted)
            {
                if (size == null)
                {
                    placed.Add(null);
                    continue;
                }
                double width = size.Value.Width * shrink, height = size.Value.Height * shrink;
                placed.Add(((int)x, (int)((bandHeight - height) / 2.0),
                            Math.Max(1, (int)width), Math.Max(1, (int)height)));
                x += width + gapSize;
            }
            return placed;
        }

        // ==========================================================================
        // the workbook
        // ==========================================================================

        /// <summary>One worksheet of the form, and where its heavy lines go.
        ///
        /// Thin lines throughout inside a medium frame, as on the TIDP sheet, with
        /// medium lines: under the title band and over the project rows; under
        /// Day/Month/Year and under the legend; between the Issued To rows and the
        /// Method rows; either side of the headings; down the left of Current Rev
        /// and of the first issue; under the last drawing; round the footer. Every
        /// cell asks for its look and the frame is worked out from where it sits -
        /// which is what keeps the edges right whatever the number of issues,
        /// Issued to rows and drawings.</summary>
        internal class Form
        {
            public PsXlsx.Styles Styles;
            public PsXlsx.Sheet Sheet;
            public int Last;               // the last column of the form
            public int FirstIssue;
            public int Current;            // the Current Rev column, or 0
            public int Split;              // the last Issued To row before Method
            public (int First, int Last) Issued = (0, -1);   // the first and last Issued to row
            public int Head;               // the column headings row
            public (int First, int Last) Data = (0, -1);     // first and last drawing row
            public int Footer;

            public Form(PsXlsx.Workbook book, PsXlsx.Sheet sheet, int last, int firstIssue, int current)
            {
                Styles = book.Styles;
                Sheet = sheet;
                Last = last;
                FirstIssue = firstIssue;
                Current = current;
            }

            public (string Left, string Right, string Top, string Bottom) Sides(int row, int col)
            {
                string left = "thin", right = "thin", top = "thin", bottom = "thin";
                if (col == 1)
                    left = "medium";
                if (col == Last)
                    right = "medium";
                if (row == 1)
                    top = "medium";
                if (row == 2)
                    bottom = "medium";
                if (row == 3)
                    top = "medium";
                if (row == 5 && ColSize <= col && col < FirstIssue)
                    bottom = "medium";
                if (row == 6 && col < FirstIssue)
                    // Issue Status: and its legend read as one box.
                    bottom = null;
                if (row == 7 && col < FirstIssue)
                {
                    top = null;
                    bottom = "medium";
                }
                if (Split != 0 && row == Split && col > ColNumber)
                    bottom = "medium";
                if (row == Head || row == Footer)
                    top = bottom = "medium";
                if (row == Data.Last)
                    bottom = "medium";
                if (3 <= row && row < Footer)
                {
                    if (col == FirstIssue)
                        left = "medium";
                    if (col == FirstIssue - 1)
                        right = "medium";
                }
                if (Current != 0 && Head <= row && row < Footer)
                {
                    if (col == Current)
                        left = "medium";
                    if (col == Current - 1)
                        right = "medium";
                }
                if (Issued.First <= row && row <= Issued.Last)
                {
                    // The Issued to block, as the office drew it on the form: a
                    // heavy line round it and between "Issued to:" and the names,
                    // and the issue columns carried through it on thin lines.
                    if (row == Issued.First)
                        top = "medium";
                    if (row == Issued.Last)
                        bottom = "medium";
                    if (col == ColNumber)
                        right = "medium";
                    if (col == ColTitle)
                        left = "medium";
                    if (col == FirstIssue)
                        left = "thin";
                    if (col == FirstIssue - 1)
                        right = "thin";
                }
                return (left, right, top, bottom);
            }

            public int Look(int row, int col, int? size = null, bool bold = false, string color = Black,
                            string fill = null, string h = null, bool wrap = false, int rotate = 0,
                            int indent = 0, string font = null,
                            (string Left, string Right, string Top, string Bottom)? border = null)
            {
                var sides = border ?? Sides(row, col);
                // PsXlsx.Styles.Style takes the four sides as a list (or one string).
                var list = new[] { sides.Left, sides.Right, sides.Top, sides.Bottom };
                return Styles.Style(size: size, bold: bold, color: color, fill: fill, border: list,
                                    h: h, wrap: wrap, rotate: rotate, indent: indent, font: font);
            }

            public void Put(int row, int col, object value, bool number = false, int? size = null,
                            bool bold = false, string color = Black, string fill = null, string h = null,
                            bool wrap = false, int rotate = 0, int indent = 0, string font = null)
            {
                Sheet.Set(row, col, value,
                          Look(row, col, size: size, bold: bold, color: color, fill: fill, h: h, wrap: wrap,
                               rotate: rotate, indent: indent, font: font),
                          number);
            }

            /// <summary>Merge a block, each cell framed for where it sits.</summary>
            public void Block(int row1, int col1, int row2, int col2, object value = null, int? size = null,
                              bool bold = false, string color = Black, string fill = null, string h = null,
                              bool wrap = false, int rotate = 0, int indent = 0, string font = null)
            {
                for (int row = row1; row <= row2; row++)
                {
                    for (int col = col1; col <= col2; col++)
                    {
                        Put(row, col, (row == row1 && col == col1) ? value : null, size: size, bold: bold,
                            color: color, fill: fill, h: h, wrap: wrap, rotate: rotate, indent: indent,
                            font: font);
                    }
                }
                if (row1 != row2 || col1 != col2)
                    Sheet.Merges.Add((row1, col1, row2, col2));
            }
        }

        /// <summary>The register as a Workbook. rows are the included drawings.</summary>
        public static PsXlsx.Workbook Build(List<PsRegister.RevisionColumn> revisions,
                                            List<PsRegister.RegisterRow> rows, Info info)
        {
            var book = new PsXlsx.Workbook(fontSize: 11, borderColor: Black);
            var statuses = IssueStatuses(revisions, rows, info);
            foreach (var (name, members) in Worksheets(rows, info.Skip))
                SheetCore(book, name, members, revisions, info, statuses);
            if (book.Sheets.Count == 0)
                SheetCore(book, "Register", new List<PsRegister.RegisterRow>(), revisions, info, statuses);
            return book;
        }

        internal static List<(string Label, List<PsRegister.RegisterRow> Rows)> SeriesGroups(
            List<PsRegister.RegisterRow> rows, Info info)
        {
            if (!string.IsNullOrEmpty(info.SeriesParam) && PsRegister.HasValues(rows, one => one.Series))
                return PsRegister.FirstAppearance(rows, one => one.Series, PsRegister.NoSeries);
            return new List<(string Label, List<PsRegister.RegisterRow> Rows)>
            {
                (null, new List<PsRegister.RegisterRow>(rows)),
            };
        }

        /// <summary>[(heading, series groups)] for a worksheet. The All worksheet has one
        /// per discipline, in tab order, each under its own heading; any other has
        /// one, under its discipline.</summary>
        public static List<(string Heading, List<(string Label, List<PsRegister.RegisterRow> Rows)> Groups)> Sections(
            string name, List<PsRegister.RegisterRow> rows, Info info)
        {
            if (name == PsRegister.AllTab)
            {
                var tabs = PsRegister.DisciplineTabs(rows)
                    .Where(tab => tab.Label != PsRegister.AllTab && tab.Rows.Count > 0)
                    .ToList();
                if (tabs.Count > 1)
                    return tabs.Select(tab => (tab.Label, SeriesGroups(tab.Rows, info))).ToList();
            }
            return new List<(string Heading, List<(string Label, List<PsRegister.RegisterRow> Rows)> Groups)>
            {
                (DisciplineHeading(name, rows), SeriesGroups(rows, info)),
            };
        }

        /// <summary>The line over a worksheet's drawings: its discipline, where the
        /// drawings have one; nothing for a register with no disciplines.</summary>
        public static string DisciplineHeading(string name, IEnumerable<PsRegister.RegisterRow> rows)
        {
            var found = new HashSet<string>(rows.Select(row => (row.Discipline ?? "").Trim()));
            found.Remove("");
            if (found.Count == 1)
                return found.First();
            return name == "Register" ? "" : name;
        }

        /// <summary>One worksheet of the form (Python _sheet; named SheetCore so it does
        /// not clash with the nested type name Sheet used elsewhere).</summary>
        internal static PsXlsx.Sheet SheetCore(PsXlsx.Workbook book, string name, List<PsRegister.RegisterRow> rows,
                                               List<PsRegister.RevisionColumn> revisions, Info info,
                                               Dictionary<string, string> statuses = null)
        {
            statuses = statuses ?? new Dictionary<string, string>();
            var sheet = book.AddSheet(name);
            var paper = PaperSetup(info.Paper);
            sheet.Paper = paper.Paper;
            sheet.Landscape = paper.Landscape;
            sheet.Margins = (0.25, 0.25, 0.75, 0.75, 0.3, 0.3);
            sheet.PrintArea = true;
            var issues = PsRegister.RevisionsFor(revisions, rows, info.HideUnused);
            int columns = Math.Max(issues.Count, MinIssueColumns);
            string snapshot = (info.Snapshot ?? "").Trim();
            int current = snapshot.Length > 0 ? ColCurrent : 0;
            int firstIssue = snapshot.Length > 0 ? ColCurrent + 1 : ColCurrent;
            int last = firstIssue + columns - 1;
            var form = new Form(book, sheet, last, firstIssue, current);
            int labelsEnd = firstIssue - 1;          // Day/Month/Year span C to here
            var issued = IssuedRows(issues, info);
            var parts = Sections(name, rows, info);

            // Rows: the Issued to rows (one blank when there are none), the
            // headings, the discipline, the drawings with a blank row between
            // series, the footer.
            int issuedTo = 8;
            int end = issuedTo + Math.Max(1, issued.Count) - 1;
            var methods = issued.Select((one, index) => (one, index))
                                .Where(pair => pair.one.Group == PsRevData.Method)
                                .Select(pair => pair.index)
                                .ToList();
            if (methods.Count > 0 && methods[0] > 0)
                form.Split = issuedTo + methods[0] - 1;
            form.Issued = (issuedTo, end);
            form.Head = end + 1;
            // Each section: its heading line, its drawings, and a blank row
            // between its series.
            int used = 0;
            foreach (var (heading, groups) in parts)
            {
                used += (!string.IsNullOrEmpty(heading) ? 1 : 0) +
                        groups.Sum(group => group.Rows.Count) +
                        Math.Max(0, groups.Count - 1);
            }
            int lastData = form.Head + used;
            form.Data = (form.Head + 1, Math.Max(form.Head + 1, lastData));
            form.Footer = form.Data.Last + 1;

            // -- widths: the form's, wider only where the text needs it
            sheet.Width(ColNumber, TextWidth(rows.Select(row => row.Number)
                                                 .Concat(new[] { info.ProjectNumber }),
                                             Widths[ColNumber], 48));
            sheet.Width(ColTitle, TextWidth(rows.Select(row => row.Name)
                                                .Concat(new[] { info.ProjectName }),
                                            Widths[ColTitle], 80));
            foreach (var (col, values) in new[]
                     {
                         (ColSize, rows.Select(row => row.Size).ToList()),
                         (ColScale, rows.Select(row => row.Scale).ToList()),
                     })
            {
                int longest = values.Select(v => (v ?? "").Length).DefaultIfEmpty(0).Max();
                sheet.Width(col, Math.Max(Widths[col], longest * 0.8 + 1));
            }
            if (current != 0)
                sheet.Width(current, Widths[ColCurrent]);
            for (int col = firstIssue; col <= last; col++)
                sheet.Width(col, IssueWidth);

            // -- heights
            sheet.Height(1, BandHeights.Title);
            sheet.Height(2, BandHeights.Logo);
            foreach (var pair in TopHeights)
                sheet.Height(pair.Key, pair.Value);
            for (int row = issuedTo; row < form.Footer; row++)
                sheet.Height(row, RowHeight);
            sheet.Height(form.Head, HeadHeight);
            sheet.Height(form.Footer, FooterHeight);

            // -- 1-2 the title band, logos after the title
            form.Block(1, 1, 2, last, string.IsNullOrEmpty(info.Title) ? DefaultTitle : info.Title,
                       size: 18, bold: true, color: TitleBlue, font: TitleFont, h: "left", indent: 2);
            Logos(sheet, info, last);

            // -- 3-5 project, and each issue's date up its column
            form.Put(3, ColNumber, "Project No:", bold: true, fill: LabelFill, h: "left");
            form.Put(3, ColTitle, "Project Title:", bold: true, fill: LabelFill, h: "left", wrap: true);
            form.Block(4, ColNumber, 5, ColNumber, OrNone(info.ProjectNumber), size: 14);
            form.Block(4, ColTitle, 5, ColTitle, OrNone(info.ProjectName), size: 14);
            foreach (var (row, part) in new[] { (3, "Day"), (4, "Month"), (5, "Year") })
            {
                form.Block(row, ColSize, row, labelsEnd, part, bold: true, h: "center", fill: HeadFill);
            }
            for (int offset = 0; offset < columns; offset++)
            {
                int col = firstIssue + offset;
                string text = offset < issues.Count ? DateText(issues[offset].Date) : "";
                form.Block(3, col, 5, col, OrNone(text), size: 8, bold: true, h: "center", rotate: 90,
                           fill: HeadFill);
            }

            // -- 6-7 each issue's status, and the legend
            form.Block(6, ColNumber, 6, labelsEnd, "Issue Status: ", h: "right", wrap: true);
            form.Block(7, ColNumber, 7, labelsEnd,
                       string.Join("  ", (info.Legend ?? new List<string>())
                                         .Select(item => (item ?? "").Trim())
                                         .Where(item => item.Length > 0)),
                       size: 9, h: "right", wrap: true);
            for (int offset = 0; offset < columns; offset++)
            {
                string status = offset < issues.Count && statuses.TryGetValue(issues[offset].Key, out var s)
                    ? s ?? "" : "";
                form.Block(6, firstIssue + offset, 7, firstIssue + offset, OrNone(status), bold: true,
                           h: "center");
            }

            // -- 8.. Issued to: the Revision Manager's Issued To then Method rows
            form.Block(issuedTo, ColNumber, end, ColNumber, "Issued to:", bold: true, h: "center", wrap: true);
            for (int index = 0; index < end - issuedTo + 1; index++)
            {
                int row = issuedTo + index;
                var (label, _group, ticks) = index < issued.Count
                    ? issued[index]
                    : ("", "", new List<bool>());
                form.Block(row, ColTitle, row, labelsEnd, OrNone(label), bold: true, h: "right");
                for (int offset = 0; offset < columns; offset++)
                {
                    bool went = offset < ticks.Count && ticks[offset];
                    form.Put(row, firstIssue + offset, went ? "x" : null, bold: true, h: "center");
                }
            }

            // -- the column headings
            int head = form.Head;
            form.Put(head, ColNumber, "Document No", size: 14, bold: true, h: "center", fill: HeadFill);
            form.Put(head, ColTitle, "Document Title", size: 14, bold: true, h: "center", fill: HeadFill);
            form.Put(head, ColSize, "Sheet Size", bold: true, h: "center", fill: HeadFill);
            form.Put(head, ColScale, "Scale", bold: true, h: "center", rotate: 90, fill: HeadFill);
            if (current != 0)
                form.Put(head, current, snapshot, bold: true, h: "center", rotate: 90, fill: CurrentFill);
            form.Block(head, firstIssue, head, last, "Document Issued", size: 14, bold: true, h: "center",
                       fill: HeadFill);

            // -- the discipline, then the drawings with a blank row between series;
            //    on the All worksheet, one of those per discipline
            int at = head;
            foreach (var (heading, groups) in parts)
            {
                if (!string.IsNullOrEmpty(heading))
                {
                    at += 1;
                    BlankRow(form, at, current, last);
                    form.Block(at, ColNumber, at, ColTitle, heading, bold: true, h: "center", wrap: true);
                }
                at = Drawings(form, at, groups, issues, columns, current, firstIssue, last);
            }

            // -- the footer
            string footer = !string.IsNullOrEmpty(info.Footer)
                ? info.Footer
                : string.Format(Inv, "Generated from {0} on {1} by RevoBIM Pro Sheets Exporter.",
                                string.IsNullOrEmpty(info.ModelName) ? "the model" : info.ModelName,
                                DateTime.Now.ToString("dd/MM/yyyy", Inv));
            form.Block(form.Footer, 1, form.Footer, last, footer, size: 9, h: "center", wrap: true);

            // Rows down to the headings repeat on every printed page.
            sheet.PrintRows = (1, head);
            return sheet;
        }

        /// <summary>text or None: a blank value leaves the cell empty.</summary>
        private static string OrNone(string text)
        {
            return string.IsNullOrEmpty(text) ? null : text;
        }

        /// <summary>One section's drawings from the row after row, a blank row between
        /// series. Returns the last row written.</summary>
        internal static int Drawings(Form form, int row, List<(string Label, List<PsRegister.RegisterRow> Rows)> groups,
                                     List<PsRegister.RevisionColumn> issues, int columns, int current,
                                     int firstIssue, int last)
        {
            bool first = true;
            foreach (var (_label, members) in groups)
            {
                if (!first)
                {
                    row += 1;
                    BlankRow(form, row, current, last);
                }
                first = false;
                foreach (var drawing in members)
                {
                    row += 1;
                    form.Put(row, ColNumber, drawing.Number, size: 10, h: "center");
                    form.Put(row, ColTitle, drawing.Name, size: 10, h: "left", indent: 1);
                    form.Put(row, ColSize, OrNone(drawing.Size), size: 8, h: "center");
                    form.Put(row, ColScale, OrNone(drawing.Scale), size: 8, h: "center");
                    if (current != 0)
                    {
                        form.Put(row, current, OrNone(drawing.Current), size: 8, bold: true, h: "center",
                                 font: CurrentFont, color: CurrentInk, fill: CurrentFill);
                    }
                    for (int offset = 0; offset < columns; offset++)
                    {
                        string code = offset < issues.Count &&
                                      drawing.Cells.TryGetValue(issues[offset].Key, out var c) ? c : "";
                        form.Put(row, firstIssue + offset, OrNone(code), size: 9, h: "center");
                    }
                }
            }
            return row;
        }

        /// <summary>A spacer row, framed like the drawings either side of it; Current
        /// Rev stays orange down its whole length. (Python _blank.)</summary>
        internal static void BlankRow(Form form, int row, int current, int last)
        {
            for (int col = 1; col <= last; col++)
            {
                if (col == current)
                    form.Put(row, col, null, size: 9, bold: true, font: CurrentFont, color: CurrentInk,
                             fill: CurrentFill);
                else
                    form.Put(row, col, null, size: 9);
            }
        }

        /// <summary>The company's logo then the client's to its right, after the title
        /// in the band (1.46.0 - the client's came first before).</summary>
        internal static void Logos(PsXlsx.Sheet sheet, Info info, int last)
        {
            var paths = new List<string>();
            foreach (var path in new[] { info.Logo, info.ClientLogo })
            {
                if (!string.IsNullOrEmpty(path) && PsXlsx.Workbook.UsableImage(path) != null &&
                    !paths.Contains(path))
                    paths.Add(path);
            }
            if (paths.Count == 0)
                return;
            int band = PsXlsx.HeightPixels(BandHeights.Title) + PsXlsx.HeightPixels(BandHeights.Logo);
            int right = 0;
            for (int col = 1; col <= last; col++)
                right += PsXlsx.WidthPixels(sheet.Widths.TryGetValue(col, out var chars) ? chars : 8.43);
            // Where the title ends: 18pt Gadugi bold runs 13 to 15 pixels a
            // character, after the two-step indent - the wider end, so a long
            // title like the RD9 one never runs under the logo.
            string title = string.IsNullOrEmpty(info.Title) ? DefaultTitle : info.Title;
            int start = 24 + title.Length * 15 + LogoGap;
            var sizes = new List<(int Width, int Height)?>();
            foreach (var path in paths)
            {
                var size = PsXlsx.ImageSize(path);
                sizes.Add(size == null ? ((int, int)?)null : (size.Value.Item1, size.Value.Item2));
            }
            var places = FitLogos(sizes, start, right, band);
            for (int i = 0; i < paths.Count && i < places.Count; i++)
            {
                var place = places[i];
                if (place != null)
                    sheet.Image(paths[i], place.Value.X, place.Value.Y, place.Value.Width, place.Value.Height);
            }
        }

        /// <summary>Build and save. (ok, message).</summary>
        public static (bool Ok, string Message) Write(string path, List<PsRegister.RevisionColumn> revisions,
                                                     List<PsRegister.RegisterRow> rows, Info info)
        {
            PsXlsx.Workbook book;
            try
            {
                book = Build(revisions, rows, info);
            }
            catch (Exception err)
            {
                return (false, "The register could not be laid out: " + err.Message);
            }
            var (ok, error) = book.Save(path);
            if (!ok)
                return (false, "The register could not be written: " + error);
            return (true, string.Format(Inv, "Document Register written: {0} drawing{1} on {2} worksheet{3}.",
                                        rows.Count, rows.Count == 1 ? "" : "s",
                                        book.Sheets.Count, book.Sheets.Count == 1 ? "" : "s"));
        }
    }
}
