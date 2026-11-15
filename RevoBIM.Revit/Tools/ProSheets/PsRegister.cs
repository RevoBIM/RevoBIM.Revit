using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.ProSheets
{
    /// <summary>
    /// The Document Register: every sheet down the page, every revision across.
    /// Port of ps_register.py.
    ///
    /// The read of the model and the decisions about it, with no WPF in here at
    /// all. The tab that draws it is PsRegView; this module hands it plain
    /// objects.
    ///
    /// The cell is what the sheet prints. GetRevisionNumberOnSheet is the only
    /// call that agrees with the sheet's own revision schedule. Revision.RevisionNumber
    /// is the project-wide one - deprecated since 2022 and gone in later releases.
    /// It is not used here, even as a fallback; the sequence number is.
    ///
    /// Read in one pass. Revisions are one call, scales are one collector keyed by
    /// sheet. Nothing here runs a collector per sheet.
    ///
    /// Groups and tabs appear where their first drawing does. Rows are in natural
    /// drawing-number order, and a series or a discipline is placed where its first
    /// member falls. Sorting the names alphabetically shuffles a register into
    /// blocks that read wrong.
    ///
    /// The issue status letter is derived, never stored: the alpha prefix of the
    /// codes actually written in a column, majority winning, derived across every
    /// sheet in the project - the letter describes the issue, not the tab.
    /// </summary>
    public static partial class PsRegister
    {
        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        // What a blank discipline or series is called on screen. Blank values are
        // real - a sheet nobody has filled in yet still has to be printable - so they
        // get a tab and a heading of their own rather than vanishing.
        public const string NoDiscipline = "(no discipline)";
        public const string NoSeries = "(no series)";

        // The first tab. Every drawing, grouped by discipline then series.
        public const string AllTab = "All";
        // Kept among the unticked tabs to mean the opposite for All: ticked, so the
        // Excel export gets an All worksheet. Off unless ticked.
        public const string AllIncluded = "+All";

        /// <summary>u'{0}'.format(value or u'') - the text of a value, blank for None.</summary>
        internal static string Str(object value)
        {
            if (value == null) return "";
            if (value is string s) return s;
            if (value is bool b) return b ? "True" : "";
            if (value is IFormattable f) return f.ToString(null, Inv);
            return value.ToString() ?? "";
        }

        /// <summary>Whether the All tab is ticked into the Excel export.</summary>
        public static bool AllTicked(IEnumerable<string> skip)
        {
            return new HashSet<string>(skip ?? Enumerable.Empty<string>()).Contains(AllIncluded);
        }

        /// <summary>A tab's tick: a discipline is in unless unticked; All is out unless ticked.</summary>
        public static bool TabTicked(string label, IEnumerable<string> skip)
        {
            if (label == AllTab)
                return AllTicked(skip);
            return !new HashSet<string>(skip ?? Enumerable.Empty<string>()).Contains(label);
        }

        /// <summary>The tab ticks after one is clicked: a new set.</summary>
        public static HashSet<string> TickTab(string label, bool wanted, IEnumerable<string> skip)
        {
            var result = new HashSet<string>(skip ?? Enumerable.Empty<string>());
            bool marked;
            if (label == AllTab)
            {
                marked = wanted;
                label = AllIncluded;
            }
            else
            {
                marked = !wanted;
            }
            if (marked)
                result.Add(label);
            else
                result.Remove(label);
            return result;
        }

        // How an empty cell is listed in a column's filter, as Excel lists it.
        public const string Blanks = "(Blanks)";

        // A revision column's key in the table. A letter then the element id, so it
        // can never collide with the fixed columns and is a legal DataTable name.
        public const string ColumnPrefix = "r";

        // ==========================================================================
        // the records
        // ==========================================================================

        /// <summary>One revision in the project, as a column across the register.</summary>
        public class RevisionColumn
        {
            public long ElementKey;
            public string Key;
            public int Sequence;
            public string Date;
            public string Description;
            public string IssuedBy;
            public string IssuedTo;
            public bool Issued;
            public string StatusLetter = "";
            // 1.44.0: Revit's UniqueId - what the Revision Manager keys its own
            // columns by - and the issue's status, as the Excel prints it.
            public string Uid = "";
            public string Status = "";

            public RevisionColumn(long elementKey, int sequence = 0, string date = "",
                                  string description = "", string issuedBy = "",
                                  string issuedTo = "", bool issued = false)
            {
                ElementKey = elementKey;
                Key = ColumnKey(elementKey);
                Sequence = sequence;
                Date = date ?? "";
                Description = description ?? "";
                IssuedBy = issuedBy ?? "";
                IssuedTo = issuedTo ?? "";
                Issued = issued;
            }

            /// <summary>What goes up the rotated header: the date, as typed.</summary>
            public string Heading()
            {
                if (!string.IsNullOrEmpty(Date))
                    return Date;
                return string.Format(Inv, "Seq {0}", Sequence);
            }

            /// <summary>The tooltip: everything Revit holds about this revision.</summary>
            public string Describe()
            {
                var lines = new List<string> { string.Format(Inv, "Sequence {0}", Sequence) };
                if (!string.IsNullOrEmpty(Date))
                    lines.Add("Date: " + Date);
                if (!string.IsNullOrEmpty(Description))
                    lines.Add("Description: " + Description);
                if (!string.IsNullOrEmpty(IssuedBy))
                    lines.Add("Issued by: " + IssuedBy);
                if (!string.IsNullOrEmpty(IssuedTo))
                    lines.Add("Issued to: " + IssuedTo);
                lines.Add(Issued ? "Issued" : "Not yet issued");
                if (!string.IsNullOrEmpty(StatusLetter))
                    lines.Add("Status: " + StatusLetter);
                return string.Join("\n", lines);
            }
        }

        /// <summary>One sheet, as the register sees it.</summary>
        public class RegisterRow
        {
            public long Key;
            public string Number;
            public string Name;
            public string Size = "";
            public string Scale = "";
            public string Discipline = "";
            public string Series = "";
            // {column key: the revision number this sheet prints for it}
            public Dictionary<string, string> Cells = new Dictionary<string, string>(StringComparer.Ordinal);
            public string Current = "";
            public string CurrentKey = "";
            public string CurrentDate = "";
            // The current revision's sequence number in the project - what
            // Revit's Sheet Issues/Revisions dialog numbers it - as text.
            public string CurrentSequence = "";
            // The sheet's status parameter (BGL_Sheet Status), as it is now.
            public string Status = "";

            public RegisterRow(long key, string number = "", string name = "")
            {
                Key = key;
                Number = number ?? "";
                Name = name ?? "";
            }

            /// <summary>row.cells.get(key, u'') - the cell's text, blank where none.</summary>
            internal string Cell(string columnKey)
            {
                if (columnKey != null && Cells.TryGetValue(columnKey, out var text))
                    return text ?? "";
                return "";
            }
        }

        /// <summary>The register's file name, dated so each issue keeps its own:
        /// "Wrexham AFC - Document Register - 2026-10-06.xlsx".</summary>
        public static string RegisterFileName(string project, DateTime? today = null)
        {
            DateTime when = today ?? DateTime.Today;
            return string.Format(Inv, "{0} - Document Register - {1}.xlsx",
                PsConfig.SafeName(string.IsNullOrEmpty(project) ? "Project" : project, "Project"),
                when.ToString("yyyy-MM-dd", Inv));
        }

        /// <summary>A revision's sequence number as the register shows it: the whole
        /// number, or nothing where Revit has none.</summary>
        public static string SequenceText(object sequence)
        {
            long number;
            if (!PyInt(sequence, out number))
                return "";
            return number > 0 ? number.ToString(Inv) : "";
        }

        /// <summary>Python int(value): whole numbers, floats truncated, digit text
        /// (surrounding whitespace allowed). False where int() would raise.</summary>
        internal static bool PyInt(object value, out long number)
        {
            number = 0;
            switch (value)
            {
                case null:
                    return false;
                case int i: number = i; return true;
                case long l: number = l; return true;
                case short sh: number = sh; return true;
                case bool b: number = b ? 1 : 0; return true;
                case double d:
                    if (double.IsNaN(d) || double.IsInfinity(d)) return false;
                    number = (long)Math.Truncate(d); return true;
                case float fl:
                    if (float.IsNaN(fl) || float.IsInfinity(fl)) return false;
                    number = (long)Math.Truncate(fl); return true;
                case decimal m: number = (long)Math.Truncate(m); return true;
                case string s:
                    return long.TryParse(s.Trim(), NumberStyles.AllowLeadingSign, Inv, out number);
                default:
                    return long.TryParse(Str(value).Trim(), NumberStyles.AllowLeadingSign, Inv, out number);
            }
        }

        public static string ColumnKey(long elementKey)
        {
            return ColumnPrefix + elementKey.ToString(Inv);
        }

        public static string ColumnKey(object elementKey)
        {
            return ColumnPrefix + Str(elementKey);
        }

        public static bool IsColumnKey(object text)
        {
            string value = Str(text);
            if (!(value.Length > ColumnPrefix.Length && value.StartsWith(ColumnPrefix, StringComparison.Ordinal)))
                return false;
            string rest = value.Substring(ColumnPrefix.Length).TrimStart('-');
            return rest.Length > 0 && rest.All(char.IsDigit);
        }

        // ==========================================================================
        // pure decisions
        // ==========================================================================

        internal static readonly Regex Prefix = new Regex(@"^\s*([A-Za-z]+)");

        /// <summary>The issue status letter for a column, from the codes written in it.
        ///
        /// P01, P02 and P03 make P; C01 makes C; AB makes AB. Where a column is
        /// mixed the majority wins, and a tie goes to the alphabetically first so
        /// the answer does not change from one read to the next. A column of plain
        /// numbers has no letter.</summary>
        public static string StatusLetter(IEnumerable<string> codes)
        {
            var counts = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (var code in codes ?? Enumerable.Empty<string>())
            {
                var match = Prefix.Match(code ?? "");
                if (!match.Success)
                    continue;
                string letter = match.Groups[1].Value.ToUpperInvariant();
                counts.TryGetValue(letter, out int n);
                counts[letter] = n + 1;
            }
            if (counts.Count == 0)
                return "";
            return counts.OrderBy(item => -item.Value)
                         .ThenBy(item => item.Key, StringComparer.Ordinal)
                         .First().Key;
        }

        /// <summary>Write each revision's status letter, derived across every row.</summary>
        public static void AssignStatusLetters(IEnumerable<RevisionColumn> revisions, IEnumerable<RegisterRow> rows)
        {
            var list = rows.ToList();
            foreach (var column in revisions)
            {
                var codes = list.Select(row => row.Cell(column.Key)).ToList();
                column.StatusLetter = StatusLetter(codes);
            }
        }

        /// <summary>[(label, [rows])] in the order each value first appears.
        ///
        /// Every member of a value is gathered under it, even when the values
        /// interleave, so a sheet numbered out of step with its series still sits
        /// with its series. Blank values go last under blankLabel: an unfilled
        /// parameter is the exception, and leading with it buries the register
        /// under the sheets nobody has finished.</summary>
        public static List<(string Label, List<T> Rows)> FirstAppearance<T>(
            IEnumerable<T> rows, Func<T, string> valueOf, string blankLabel)
        {
            var order = new List<string>();
            var members = new Dictionary<string, List<T>>(StringComparer.Ordinal);
            var blanks = new List<T>();
            foreach (var row in rows)
            {
                string value = (valueOf(row) ?? "").Trim();
                if (value.Length == 0)
                {
                    blanks.Add(row);
                    continue;
                }
                if (!members.ContainsKey(value))
                {
                    members[value] = new List<T>();
                    order.Add(value);
                }
                members[value].Add(row);
            }
            var groups = order.Select(value => (value, members[value])).ToList();
            if (blanks.Count > 0)
                groups.Add((blankLabel, blanks));
            return groups;
        }

        /// <summary>The tabs along the bottom: All first, then one per discipline.
        ///
        /// Disciplines in the order their first drawing appears, blank last. When
        /// nobody has filled the discipline in on any sheet there is only the All
        /// tab - a second tab holding exactly the same drawings is noise.</summary>
        public static List<(string Label, List<RegisterRow> Rows)> DisciplineTabs(IEnumerable<RegisterRow> rows)
        {
            var all = rows.ToList();
            var tabs = new List<(string Label, List<RegisterRow> Rows)> { (AllTab, new List<RegisterRow>(all)) };
            var groups = FirstAppearance(all, row => row.Discipline, NoDiscipline);
            if (groups.Count == 1 && groups[0].Label == NoDiscipline)
                return tabs;
            tabs.AddRange(groups);
            return tabs;
        }

        /// <summary>Whether the parameter holds a value on at least one sheet.</summary>
        public static bool HasValues<T>(IEnumerable<T> rows, Func<T, string> valueOf)
        {
            foreach (var row in rows)
            {
                if ((valueOf(row) ?? "").Trim().Length > 0)
                    return true;
            }
            return false;
        }

        /// <summary>The revisions at least one of these rows carries, in sequence order.
        ///
        /// Each tab only shows the columns its own drawings use, as the paper form
        /// does. A Mechanical tab with forty empty Electrical columns across it is
        /// a register you have to scroll to read.</summary>
        public static List<RevisionColumn> ColumnsUsed(IEnumerable<RevisionColumn> revisions, IEnumerable<RegisterRow> rows)
        {
            var used = new HashSet<string>(StringComparer.Ordinal);
            foreach (var row in rows)
            {
                foreach (var pair in row.Cells)
                {
                    if ((pair.Value ?? "").Trim().Length > 0)
                        used.Add(pair.Key);
                }
            }
            return revisions.OrderBy(column => column.Sequence)
                            .Where(column => used.Contains(column.Key))
                            .ToList();
        }

        /// <summary>The rows that carry a given revision - what a header click ticks.</summary>
        public static List<RegisterRow> Carrying(IEnumerable<RegisterRow> rows, string columnKeyText)
        {
            var found = new List<RegisterRow>();
            foreach (var row in rows)
            {
                if (row.Cell(columnKeyText).Trim().Length > 0)
                    found.Add(row);
            }
            return found;
        }

        /// <summary>The revision's element key behind a column key: "r1234" -> "1234".</summary>
        public static string ElementOf(object columnKeyText)
        {
            string text = Str(columnKeyText);
            return IsColumnKey(text) ? text.Substring(ColumnPrefix.Length) : "";
        }

        /// <summary>The revision columns picked after a click on one's sequence number.
        ///
        /// Excel's rules, along one row of headings:
        ///   - a plain click picks that column alone, and a second plain click on
        ///     the only one picked lets it go;
        ///   - Ctrl toggles one in or out and moves the anchor to it;
        ///   - Shift picks the run from the anchor to it, Ctrl+Shift adds the run.
        /// order is the columns as shown. Returns (picked, anchor), picked in
        /// order's order.</summary>
        public static (List<string> Picked, string Anchor) ColumnPicks(
            IEnumerable<string> picked, string key, string anchor, IList<string> order,
            bool ctrl = false, bool shift = false)
        {
            var current = (picked ?? Enumerable.Empty<string>()).Where(one => order.Contains(one)).ToList();
            if (!order.Contains(key))
                return (current, anchor);
            if (shift && anchor != null && order.Contains(anchor))
            {
                int a = order.IndexOf(anchor), b = order.IndexOf(key);
                int start = Math.Min(a, b), end = Math.Max(a, b);
                var run = new HashSet<string>(order.Skip(start).Take(end - start + 1));
                var wanted = ctrl ? new HashSet<string>(current.Concat(run)) : run;
                return (order.Where(one => wanted.Contains(one)).ToList(), anchor);
            }
            if (ctrl)
            {
                var wanted = new HashSet<string>(current);
                wanted.SymmetricExceptWith(new[] { key });
                return (order.Where(one => wanted.Contains(one)).ToList(), key);
            }
            if (current.Count == 1 && current[0] == key)
                return (new List<string>(), key);
            return (new List<string> { key }, key);
        }

        /// <summary>The revision cells picked after a click on one.
        ///
        /// cell and anchor are (sheet key, column key). rows and columns are the
        /// drawings and revision columns in the order shown; filled(sheet, column)
        /// says whether that sheet carries that revision - only those can be
        /// picked, since an empty cell has no revision to change. Same rules as
        /// ColumnPicks, with Shift picking the rectangle. Returns (picked set, anchor).</summary>
        public static (HashSet<(string Sheet, string Column)> Picked, (string Sheet, string Column)? Anchor) CellPicks(
            IEnumerable<(string Sheet, string Column)> picked, (string Sheet, string Column) cell,
            (string Sheet, string Column)? anchor, IList<string> rows, IList<string> columns,
            Func<string, string, bool> filled, bool ctrl = false, bool shift = false)
        {
            var current = new HashSet<(string Sheet, string Column)>(picked ?? Enumerable.Empty<(string, string)>());
            string sheet = cell.Sheet, column = cell.Column;
            if (!filled(sheet, column))
                return (current, anchor);
            if (shift && anchor.HasValue && rows.Contains(anchor.Value.Sheet) &&
                columns.Contains(anchor.Value.Column) && rows.Contains(sheet) && columns.Contains(column))
            {
                int r1 = rows.IndexOf(anchor.Value.Sheet), r2 = rows.IndexOf(sheet);
                int c1 = columns.IndexOf(anchor.Value.Column), c2 = columns.IndexOf(column);
                int top = Math.Min(r1, r2), bottom = Math.Max(r1, r2);
                int left = Math.Min(c1, c2), right = Math.Max(c1, c2);
                var block = new HashSet<(string Sheet, string Column)>();
                for (int r = top; r <= bottom; r++)
                {
                    for (int c = left; c <= right; c++)
                    {
                        if (filled(rows[r], columns[c]))
                            block.Add((rows[r], columns[c]));
                    }
                }
                if (ctrl)
                {
                    current.UnionWith(block);
                    return (current, anchor);
                }
                return (block, anchor);
            }
            if (ctrl)
            {
                current.SymmetricExceptWith(new[] { cell });
                return (current, cell);
            }
            if (current.Count == 1 && current.Contains(cell))
                return (new HashSet<(string Sheet, string Column)>(), cell);
            return (new HashSet<(string Sheet, string Column)> { cell }, cell);
        }

        /// <summary>The rows carrying ANY of these revisions - Isolate sheets with this
        /// revision. No revisions picked is no isolation: every row.</summary>
        public static List<RegisterRow> IsolatedRows(IEnumerable<RegisterRow> rows, IEnumerable<string> columnKeys)
        {
            var keys = (columnKeys ?? Enumerable.Empty<string>()).Select(one => one ?? "").ToList();
            if (keys.Count == 0)
                return rows.ToList();
            return rows.Where(row => keys.Any(key => row.Cell(key).Trim().Length > 0)).ToList();
        }

        /// <summary>Whether a row survives every column filter, Excel fashion.
        ///
        /// values is {column: text}. filters is {column: set of allowed texts},
        /// where "" stands for a blank cell and null means the column is not
        /// filtered - everything ticked is no filter, which is not the same thing
        /// as a filter that happens to allow everything. Every filtered column has
        /// to allow the row, so filters narrow rather than widen. A filter on a
        /// column the row does not have is ignored rather than hiding everything:
        /// a revision column filtered on one discipline must not empty the next
        /// discipline's tab.</summary>
        public static bool Passes(IDictionary<string, string> values, IDictionary<string, HashSet<string>> filters)
        {
            if (filters == null)
                return true;
            foreach (var pair in filters)
            {
                var allowed = pair.Value;
                if (allowed == null || values == null || !values.ContainsKey(pair.Key))
                    continue;
                values.TryGetValue(pair.Key, out var value);
                if (!allowed.Contains((value ?? "").Trim()))
                    return false;
            }
            return true;
        }

        /// <summary>The values a column's filter list offers, in order, blanks last.
        ///
        /// Natural order, so P-9 comes before P-10. Blank cells are one entry,
        /// "(Blanks)", at the end - where Excel puts it - and only if the column
        /// has any.</summary>
        public static List<string> FilterChoices(IEnumerable<string> texts)
        {
            var seen = new HashSet<string>(StringComparer.Ordinal);
            var values = new List<string>();
            bool blank = false;
            foreach (var raw in texts)
            {
                string text = (raw ?? "").Trim();
                if (text.Length == 0)
                {
                    blank = true;
                    continue;
                }
                if (seen.Add(text))
                    values.Add(text);
            }
            values = values.OrderBy(Natural).ToList();
            if (blank)
                values.Add(Blanks);
            return values;
        }

        private static readonly Regex DigitRun = new Regex("([0-9]+)");

        /// <summary>The natural sort key: re.split(r'(\d+)') with digit runs as
        /// numbers, the rest lower case. Compares as the Python list of tuples does.</summary>
        internal static NaturalSortKey Natural(object text)
        {
            return new NaturalSortKey(Str(text));
        }

        /// <summary>The Python natural key, comparable: a list of (kind, number,
        /// text) parts compared element by element, a shorter prefix first.</summary>
        internal sealed class NaturalSortKey : IComparable<NaturalSortKey>, IComparable
        {
            private readonly List<(int Kind, string Digits, string Text)> parts =
                new List<(int, string, string)>();

            public NaturalSortKey(string text)
            {
                foreach (var part in DigitRun.Split(text ?? ""))
                {
                    if (part.Length > 0 && part.All(ch => ch >= '0' && ch <= '9'))
                    {
                        string digits = part.TrimStart('0');
                        parts.Add((1, digits.Length == 0 ? "0" : digits, ""));
                    }
                    else
                    {
                        parts.Add((0, "0", part.ToLowerInvariant()));
                    }
                }
            }

            public int CompareTo(NaturalSortKey other)
            {
                if (other == null) return 1;
                int count = Math.Min(parts.Count, other.parts.Count);
                for (int i = 0; i < count; i++)
                {
                    var a = parts[i];
                    var b = other.parts[i];
                    int c = a.Kind.CompareTo(b.Kind);
                    if (c != 0) return c;
                    // Integers of any size: fewer digits is smaller, then digit by digit.
                    c = a.Digits.Length.CompareTo(b.Digits.Length);
                    if (c != 0) return c;
                    c = string.CompareOrdinal(a.Digits, b.Digits);
                    if (c != 0) return Math.Sign(c);
                    c = string.CompareOrdinal(a.Text, b.Text);
                    if (c != 0) return Math.Sign(c);
                }
                return parts.Count.CompareTo(other.parts.Count);
            }

            int IComparable.CompareTo(object obj)
            {
                return CompareTo(obj as NaturalSortKey);
            }
        }

        /// <summary>One heading on a tab: (label, rows, [children]). Children are
        /// the series under a discipline, themselves with no children. Deconstructs
        /// as (label, rows, children) like the Python tuple.</summary>
        public class GroupNode
        {
            public string Label;
            public List<RegisterRow> Rows;
            public List<GroupNode> Children;

            public GroupNode(string label, List<RegisterRow> rows, List<GroupNode> children = null)
            {
                Label = label;
                Rows = rows ?? new List<RegisterRow>();
                Children = children ?? new List<GroupNode>();
            }

            public void Deconstruct(out string label, out List<RegisterRow> rows, out List<GroupNode> children)
            {
                label = Label;
                rows = Rows;
                children = Children;
            }
        }

        /// <summary>[(label, rows, [(label, rows, [])])] - the headings on a tab.
        ///
        /// The All tab is grouped by discipline and then, inside each, by series;
        /// a discipline's own tab by series alone. Groups go where their first
        /// drawing is, blanks last. A parameter holding nothing anywhere gives no
        /// headings at all, rather than one heading saying "(no series)" over
        /// everything.</summary>
        public static List<GroupNode> GroupTree(IEnumerable<RegisterRow> rows, bool byDiscipline, bool bySeries)
        {
            var all = rows.ToList();

            List<GroupNode> SeriesOf(List<RegisterRow> members)
            {
                if (!bySeries || !HasValues(members, row => row.Series))
                    return new List<GroupNode>();
                return FirstAppearance(members, row => row.Series, NoSeries)
                    .Select(group => new GroupNode(group.Label, group.Rows, new List<GroupNode>()))
                    .ToList();
            }

            if (byDiscipline)
            {
                return FirstAppearance(all, row => row.Discipline, NoDiscipline)
                    .Select(group => new GroupNode(group.Label, group.Rows, SeriesOf(group.Rows)))
                    .ToList();
            }
            var series = SeriesOf(all);
            if (series.Count > 0)
                return series;
            return new List<GroupNode> { new GroupNode(null, new List<RegisterRow>(all), new List<GroupNode>()) };
        }

        /// <summary>The revision columns to show: only those used, or every one.</summary>
        public static List<RevisionColumn> RevisionsFor(IEnumerable<RevisionColumn> revisions,
                                                        IEnumerable<RegisterRow> rows, bool hideUnused)
        {
            if (hideUnused)
                return ColumnsUsed(revisions, rows);
            return revisions.OrderBy(column => column.Sequence).ToList();
        }

        /// <summary>Pixels for a column: its widest text plus padding, within limits.
        ///
        /// Measured once per tab and frozen, never left on Auto: Auto re-measures
        /// as rows are realised, so columns shift under the reader halfway down a
        /// long list, and it has no ceiling.</summary>
        public static int ColumnWidth(IEnumerable<double> widths, double header, double floor, double ceiling,
                                      double padding = 18)
        {
            double widest = (widths ?? Enumerable.Empty<double>()).Concat(new[] { header }).Max();
            return (int)Math.Max(floor, Math.Min(ceiling, widest + padding));
        }

        /// <summary>The deepest folder every path sits in, or "" where there is none.
        ///
        /// Split on both separators by hand rather than through Path, to answer
        /// for Windows the same way the Python does.</summary>
        public static string CommonFolder(IEnumerable<string> paths)
        {
            var split = new List<string[]>();
            foreach (var path in paths ?? Enumerable.Empty<string>())
            {
                string text = (path ?? "").Replace("/", "\\").TrimEnd('\\');
                if (text.Length > 0)
                    split.Add(text.Split('\\'));
            }
            if (split.Count == 0)
                return "";
            var shared = new List<string>();
            int shortest = split.Min(parts => parts.Length);
            for (int i = 0; i < shortest; i++)
            {
                string first = split[0][i];
                if (split.All(parts => parts[i].ToLowerInvariant() == first.ToLowerInvariant()))
                    shared.Add(first);
                else
                    break;
            }
            if (shared.Count == 0 || (shared.Count == 1 && shared[0].Length == 0))
                return "";
            string folder = string.Join("\\", shared);
            if (folder.EndsWith(":", StringComparison.Ordinal))
                folder += "\\";
            return folder;
        }

        /// <summary>Where the register goes alongside an export run.
        ///
        /// The folder above the PDF and DWG folders, not the deepest folder the
        /// run's files share. 1.21.0 used the shared folder, so a run of one series
        /// in one format put the register inside the PDF folder, among the
        /// drawings, where nobody looks for it. With a folder per format the format
        /// is the last part of every path, so it is taken off before the paths are
        /// compared.</summary>
        public static string RegisterFolder(IEnumerable<string> jobFolders, bool perFormat)
        {
            var bases = new List<string>();
            foreach (var folder in jobFolders ?? Enumerable.Empty<string>())
            {
                string text = (folder ?? "").Replace("/", "\\").TrimEnd('\\');
                if (text.Length == 0)
                    continue;
                if (perFormat && text.Contains("\\"))
                    text = text.Substring(0, text.LastIndexOf('\\'));
                bases.Add(text);
            }
            return CommonFolder(bases);
        }

        // The icon on a discipline tab, in a 16 x 16 box: path data for WPF.
        public static readonly Dictionary<string, string> TabIcons = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            // All: every sheet - a grid of four.
            ["all"] = "M 0,0 H 7 V 7 H 0 Z M 9,0 H 16 V 7 H 9 Z " +
                      "M 0,9 H 7 V 16 H 0 Z M 9,9 H 16 V 16 H 9 Z",
            // Electrical: a lightning bolt.
            ["electrical"] = "M 9.5,0 L 2,9.2 H 7 L 5.2,16 L 14,6.2 H 9 L 11,0 Z",
            // Mechanical: a four-bladed fan round its hub.
            ["mechanical"] = "M 8.0,6.2 C 7.2,2.0 9.6,0.3 12.6,1.6 C 13.4,4.0 " +
                             "9.6,6.8 8.0,6.2 Z M 9.8,8.0 C 14.0,7.2 15.7,9.6 " +
                             "14.4,12.6 C 12.0,13.4 9.2,9.6 9.8,8.0 Z M 8.0,9.8 " +
                             "C 8.8,14.0 6.4,15.7 3.4,14.4 C 2.6,12.0 6.4,9.2 " +
                             "8.0,9.8 Z M 6.2,8.0 C 2.0,8.8 0.3,6.4 1.6,3.4 " +
                             "C 4.0,2.6 6.8,6.4 6.2,8.0 Z " +
                             "M 6.6,8 A 1.4,1.4 0 1 1 9.4,8 A 1.4,1.4 0 1 1 6.6,8 Z",
            // Coordination: two rings linked - the trades brought together.
            ["coordination"] = "M 0.5,8 A 5,5 0 1 1 10.5,8 A 5,5 0 1 1 0.5,8 Z " +
                               "M 2.1,8 A 3.4,3.4 0 1 0 8.9,8 " +
                               "A 3.4,3.4 0 1 0 2.1,8 Z " +
                               "M 5.5,8 A 5,5 0 1 1 15.5,8 A 5,5 0 1 1 5.5,8 Z " +
                               "M 7.1,8 A 3.4,3.4 0 1 0 13.9,8 " +
                               "A 3.4,3.4 0 1 0 7.1,8 Z",
            // Builderswork: a brick wall, courses staggered.
            ["builderswork"] = "M 0,0 H 7.4 V 4.4 H 0 Z M 8.6,0 H 16 V 4.4 H 8.6 Z " +
                               "M 0,5.8 H 3.4 V 10.2 H 0 Z " +
                               "M 4.6,5.8 H 11.4 V 10.2 H 4.6 Z " +
                               "M 12.6,5.8 H 16 V 10.2 H 12.6 Z " +
                               "M 0,11.6 H 7.4 V 16 H 0 Z " +
                               "M 8.6,11.6 H 16 V 16 H 8.6 Z",
        };

        // What in a tab's name says which icon it wears - any case, anywhere in
        // it, so "E - Electrical", "MECHANICAL SERVICES" and "BWIC" all match.
        public static readonly (string Name, string[] Words)[] TabIconWords =
        {
            ("builderswork", new[] { "BUILDERSWORK", "BUILDERS WORK", "BUILDERS", "BWIC" }),
            ("coordination", new[] { "COORDINAT", "CO-ORDINAT", "COORD" }),
            ("electrical", new[] { "ELECTRIC" }),
            ("mechanical", new[] { "MECHANIC" }),
        };

        /// <summary>The path data for a tab's icon, or null when its name says nothing
        /// known. The All tab is matched by name, whatever case.</summary>
        public static string TabIcon(string label)
        {
            string text = (label ?? "").Trim().ToUpperInvariant().Replace("'", "");
            if (text.Length == 0)
                return null;
            if (text == AllTab.ToUpperInvariant())
                return TabIcons["all"];
            foreach (var (name, words) in TabIconWords)
            {
                foreach (var word in words)
                {
                    if (text.Contains(word))
                        return TabIcons[name];
                }
            }
            return null;
        }

        // ----------------------------------------------------------------------
        // Revision changes waiting for Apply revisions
        // ----------------------------------------------------------------------
        // An edit is a record in column keys ("r501"), never element ids:
        //   {Kind = "assign", Target = col, Sheets = [sheet, ...]}
        //   {Kind = "change", Target = col, Picks = {sheet: [col, ...]}}
        //   {Kind = "remove", Picks = {sheet: [col, ...]}}
        // They are kept in order and written in order, so a later one can act on a
        // cell an earlier one put there. Sheet keys are the sheet's key as text.

        public const string PendingAdd = "add";
        public const string PendingDel = "del";

        // A staged change to a revision's issue data - its Issue Status, or a tick
        // under Issued To / Issued Method (1.51.0):
        //   {Kind = "meta", Target = column key, Field = column id, Value = the new value}
        // Shares the undo stack and Apply with the sheet revision edits.
        public const string Meta = "meta";

        /// <summary>One staged edit (the Python dict). Unused fields stay null.</summary>
        public class PendingEdit
        {
            public string Kind;
            public string Target;
            public List<string> Sheets;
            public Dictionary<string, List<string>> Picks;
            public string Field;
            public string Value;

            /// <summary>dict(edit) - a shallow copy, so one field can be replaced.</summary>
            public PendingEdit Copy()
            {
                return new PendingEdit
                {
                    Kind = Kind, Target = Target, Sheets = Sheets, Picks = Picks,
                    Field = Field, Value = Value,
                };
            }
        }

        /// <summary>{(column key, field id): value}: what is stored, with the staged
        /// issue data edits played over it in order.</summary>
        public static Dictionary<(string Column, string Field), string> MetaValues(
            IDictionary<(string Column, string Field), string> stored, IEnumerable<PendingEdit> edits)
        {
            var now = stored != null
                ? new Dictionary<(string Column, string Field), string>(stored)
                : new Dictionary<(string Column, string Field), string>();
            foreach (var edit in edits ?? Enumerable.Empty<PendingEdit>())
            {
                if (edit.Kind == Meta)
                    now[(edit.Target, edit.Field)] = edit.Value ?? "";
            }
            return now;
        }

        /// <summary>The issue data cells the staged edits leave different from what
        /// is stored. A cell edited and edited back is not changed.</summary>
        public static HashSet<(string Column, string Field)> MetaChanged(
            IDictionary<(string Column, string Field), string> stored, IEnumerable<PendingEdit> edits)
        {
            stored = stored ?? new Dictionary<(string Column, string Field), string>();
            var now = MetaValues(stored, edits);
            var changed = new HashSet<(string Column, string Field)>();
            foreach (var pair in now)
            {
                stored.TryGetValue(pair.Key, out var was);
                if (pair.Value != (was ?? ""))
                    changed.Add(pair.Key);
            }
            return changed;
        }

        /// <summary>What the edits do to the grid: {(sheet, column): "add" | "del"}.
        ///
        /// present is {sheet: set of columns carrying something} as read from the
        /// model. The edits are played over it in order; a cell that ends up as it
        /// started is not flagged at all - assign, then remove, is no change.</summary>
        public static Dictionary<(string Sheet, string Column), string> PendingFlags(
            IDictionary<string, HashSet<string>> present, IEnumerable<PendingEdit> edits)
        {
            present = present ?? new Dictionary<string, HashSet<string>>();
            var now = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            foreach (var pair in present)
                now[pair.Key] = new HashSet<string>(pair.Value ?? new HashSet<string>(), StringComparer.Ordinal);

            HashSet<string> Held(string sheet)
            {
                if (!now.TryGetValue(sheet, out var held))
                {
                    held = new HashSet<string>(StringComparer.Ordinal);
                    now[sheet] = held;
                }
                return held;
            }

            foreach (var edit in edits ?? Enumerable.Empty<PendingEdit>())
            {
                string kind = edit.Kind;
                if (kind == "assign")
                {
                    foreach (var sheet in edit.Sheets ?? new List<string>())
                        Held(sheet).Add(edit.Target);
                }
                else if (kind == "change" || kind == "remove")
                {
                    foreach (var pair in edit.Picks ?? new Dictionary<string, List<string>>())
                    {
                        var held = Held(pair.Key);
                        foreach (var column in pair.Value)
                            held.Remove(column);
                        if (kind == "change")
                            held.Add(edit.Target);
                    }
                }
            }
            var flags = new Dictionary<(string Sheet, string Column), string>();
            var sheets = new HashSet<string>(now.Keys, StringComparer.Ordinal);
            sheets.UnionWith(present.Keys);
            foreach (var sheet in sheets)
            {
                var after = now.TryGetValue(sheet, out var a) ? a : new HashSet<string>();
                var before = present.TryGetValue(sheet, out var b) && b != null
                    ? new HashSet<string>(b, StringComparer.Ordinal)
                    : new HashSet<string>(StringComparer.Ordinal);
                foreach (var column in after.Where(one => !before.Contains(one)))
                    flags[(sheet, column)] = PendingAdd;
                foreach (var column in before.Where(one => !after.Contains(one)))
                    flags[(sheet, column)] = PendingDel;
            }
            return flags;
        }

        /// <summary>How many sheet cells one edit touches.</summary>
        public static int PendingCells(PendingEdit edit)
        {
            if (edit.Kind == "assign")
                return (edit.Sheets ?? new List<string>()).Count;
            if (edit.Kind == Meta)
                return 1;
            return (edit.Picks ?? new Dictionary<string, List<string>>()).Values.Sum(columns => columns.Count);
        }

        /// <summary>The sheets carrying any of the columns that are not in the set -
        /// the ones Included only would hide from an isolated revision.</summary>
        public static List<string> OutsideSet(IEnumerable<string> sheets, IEnumerable<string> columns,
                                              IEnumerable<string> included, Func<string, string, bool> filled)
        {
            var set = new HashSet<string>(included ?? Enumerable.Empty<string>());
            var cols = (columns ?? Enumerable.Empty<string>()).ToList();
            return sheets.Where(sheet => !set.Contains(sheet) && cols.Any(column => filled(sheet, column)))
                         .ToList();
        }

        /// <summary>The edits made and not yet written, with Undo and Redo.</summary>
        public class PendingEdits
        {
            public List<PendingEdit> Edits = new List<PendingEdit>();
            public List<PendingEdit> Undone = new List<PendingEdit>();

            /// <summary>len(pending) - the edits waiting.</summary>
            public int Count => Edits.Count;

            /// <summary>A new edit. Whatever was undone cannot be redone after it.</summary>
            public void Push(PendingEdit edit)
            {
                Edits.Add(edit);
                Undone = new List<PendingEdit>();
            }

            public PendingEdit Undo()
            {
                if (Edits.Count == 0)
                    return null;
                var edit = Edits[Edits.Count - 1];
                Edits.RemoveAt(Edits.Count - 1);
                Undone.Add(edit);
                return edit;
            }

            public PendingEdit Redo()
            {
                if (Undone.Count == 0)
                    return null;
                var edit = Undone[Undone.Count - 1];
                Undone.RemoveAt(Undone.Count - 1);
                Edits.Add(edit);
                return edit;
            }

            public void Clear()
            {
                Edits = new List<PendingEdit>();
                Undone = new List<PendingEdit>();
            }

            public Dictionary<(string Sheet, string Column), string> Flags(IDictionary<string, HashSet<string>> present)
            {
                return PendingFlags(present, Edits);
            }

            /// <summary>After a read: keep only what still names revisions and sheets in
            /// the model - and, for issue data, a column the model still has (fields).
            /// Returns how many edits went.</summary>
            public int Prune(IEnumerable<string> columns, IEnumerable<string> sheets, IEnumerable<string> fields = null)
            {
                var columnSet = new HashSet<string>(columns ?? Enumerable.Empty<string>());
                var sheetSet = new HashSet<string>(sheets ?? Enumerable.Empty<string>());
                var fieldSet = fields != null ? new HashSet<string>(fields) : null;

                PendingEdit Kept(PendingEdit edit)
                {
                    if (edit.Kind == Meta)
                    {
                        if (edit.Target == null || !columnSet.Contains(edit.Target))
                            return null;
                        if (fieldSet != null && (edit.Field == null || !fieldSet.Contains(edit.Field)))
                            return null;
                        return edit;
                    }
                    if (edit.Kind != "remove" && (edit.Target == null || !columnSet.Contains(edit.Target)))
                        return null;
                    if (edit.Kind == "assign")
                    {
                        var left = (edit.Sheets ?? new List<string>()).Where(sheet => sheetSet.Contains(sheet)).ToList();
                        if (left.Count == 0)
                            return null;
                        var copy = edit.Copy();
                        copy.Sheets = left;
                        return copy;
                    }
                    var picks = new Dictionary<string, List<string>>(StringComparer.Ordinal);
                    foreach (var pair in edit.Picks ?? new Dictionary<string, List<string>>())
                    {
                        var left = pair.Value.Where(column => columnSet.Contains(column)).ToList();
                        if (sheetSet.Contains(pair.Key) && left.Count > 0)
                            picks[pair.Key] = left;
                    }
                    if (picks.Count == 0)
                        return null;
                    var changed = edit.Copy();
                    changed.Picks = picks;
                    return changed;
                }

                int before = Edits.Count;
                Edits = Edits.Select(Kept).Where(one => one != null).ToList();
                Undone = Undone.Select(Kept).Where(one => one != null).ToList();
                return before - Edits.Count;
            }
        }

        /// <summary>Whether a discipline's tab is on the strip.
        ///
        /// Every tab while everything is showing. Under "Included only" a
        /// discipline with nothing in the register has nothing to show, so its tab
        /// goes - except All, which is always there, and the tab already on screen,
        /// which stays until you leave it rather than vanishing under the cursor
        /// the moment its last drawing is unticked.</summary>
        public static bool TabShows(string label, IEnumerable<RegisterRow> members, ICollection<string> included,
                                    bool includedOnly, bool current)
        {
            if (!includedOnly || label == AllTab || current)
                return true;
            foreach (var row in members)
            {
                if (included != null && included.Contains(row.Key.ToString(Inv)))
                    return true;
            }
            return false;
        }

        /// <summary>Whether the series and discipline headings carry a tick box.
        ///
        /// Only under All sheets: under "Included only" every drawing on screen is
        /// already in, and a heading tick there could only take a whole series out
        /// at a stroke. And not with everything collapsed - a column of heading
        /// ticks with no drawing under any of them reads as a list of things to
        /// tick, when the drawings themselves are folded away.</summary>
        public static bool HeadingTicksShown(bool includedOnly, bool drawingsShowing)
        {
            return !includedOnly && drawingsShowing;
        }

        /// <summary>One distinct scale gives 1:100, several give As Shown, none NTS.</summary>
        public static string ScaleLabel(IEnumerable<int> scales)
        {
            var distinct = new HashSet<int>();
            foreach (var value in scales ?? Enumerable.Empty<int>())
            {
                if (value > 0)
                    distinct.Add(value);
            }
            if (distinct.Count == 0)
                return "NTS";
            if (distinct.Count > 1)
                return "As Shown";
            return "1:" + distinct.First().ToString(Inv);
        }

        // ==========================================================================
        // reading the model
        // ==========================================================================

        /// <summary>Every revision in the project, in sequence order.</summary>
        public static List<RevisionColumn> ReadRevisions(Document doc)
        {
            List<ElementId> ids;
            try
            {
                ids = Revision.GetAllRevisionIds(doc).ToList();
            }
            catch (Exception)
            {
                try
                {
                    ids = new FilteredElementCollector(doc)
                        .OfCategory(BuiltInCategory.OST_Revisions)
                        .WhereElementIsNotElementType()
                        .Select(element => element.Id)
                        .ToList();
                }
                catch (Exception)
                {
                    ids = new List<ElementId>();
                }
            }

            var columns = new List<RevisionColumn>();
            for (int index = 0; index < ids.Count; index++)
            {
                var revisionId = ids[index];
                Revision revision;
                try
                {
                    revision = doc.GetElement(revisionId) as Revision;
                }
                catch (Exception)
                {
                    revision = null;
                }
                if (revision == null)
                    continue;
                int sequence;
                try
                {
                    sequence = revision.SequenceNumber;
                }
                catch (Exception)
                {
                    sequence = index + 1;
                }
                var column = new RevisionColumn(
                    PsModel.EidValue(revisionId),
                    sequence: sequence,
                    date: Text(revision, "RevisionDate"),
                    description: Text(revision, "Description"),
                    issuedBy: Text(revision, "IssuedBy"),
                    issuedTo: Text(revision, "IssuedTo"),
                    issued: Flag(revision, "Issued"));
                column.Uid = Text(revision, "UniqueId");
                columns.Add(column);
            }
            return columns.OrderBy(column => column.Sequence).ToList();
        }

        /// <summary>getattr(element, name) as trimmed text, blank on any failure.
        /// The Revision properties the register reads are called directly; any
        /// other name is looked up as a property, as getattr would.</summary>
        internal static string Text(Element element, string name)
        {
            try
            {
                object value;
                var revision = element as Revision;
                switch (name)
                {
                    case "RevisionDate" when revision != null: value = revision.RevisionDate; break;
                    case "Description" when revision != null: value = revision.Description; break;
                    case "IssuedBy" when revision != null: value = revision.IssuedBy; break;
                    case "IssuedTo" when revision != null: value = revision.IssuedTo; break;
                    case "UniqueId": value = element?.UniqueId; break;
                    default:
                        value = element?.GetType().GetProperty(name)?.GetValue(element);
                        break;
                }
                return Str(value).Trim();
            }
            catch (Exception)
            {
                return "";
            }
        }

        /// <summary>bool(getattr(element, name, False)), False on any failure.</summary>
        internal static bool Flag(Element element, string name)
        {
            try
            {
                if (name == "Issued" && element is Revision revision)
                    return revision.Issued;
                var value = element?.GetType().GetProperty(name)?.GetValue(element);
                return value is bool b && b;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // Views that carry no meaningful scale on a drawing register: a legend is
        // drawn at whatever scale fits the key, a drafting view's scale is a text
        // size. Schedules are not viewports at all, so they never get here.
        internal static readonly HashSet<ViewType> NoScaleTypes = new HashSet<ViewType>
        {
            ViewType.Legend, ViewType.DraftingView, ViewType.Schedule, ViewType.Report,
        };

        /// <summary>{sheet key: scale label} from one collector over every viewport.</summary>
        public static Dictionary<long, string> ReadScales(Document doc)
        {
            var found = new Dictionary<long, List<int>>();
            List<Viewport> viewports;
            try
            {
                viewports = new FilteredElementCollector(doc).OfClass(typeof(Viewport)).Cast<Viewport>().ToList();
            }
            catch (Exception)
            {
                viewports = new List<Viewport>();
            }
            foreach (var viewport in viewports)
            {
                long sheetKey;
                View view;
                try
                {
                    sheetKey = PsModel.EidValue(viewport.SheetId);
                    view = doc.GetElement(viewport.ViewId) as View;
                }
                catch (Exception)
                {
                    continue;
                }
                if (view == null)
                    continue;
                try
                {
                    if (NoScaleTypes.Contains(view.ViewType))
                        continue;
                }
                catch (Exception)
                {
                }
                try
                {
                    int scale = view.Scale;
                    if (!found.TryGetValue(sheetKey, out var list))
                    {
                        list = new List<int>();
                        found[sheetKey] = list;
                    }
                    list.Add(scale);
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return found.ToDictionary(pair => pair.Key, pair => ScaleLabel(pair.Value));
        }

        /// <summary>The Scale column for one sheet: the parameter's text, read from the
        /// sheet and then from its title block, or Revit's own scale where the
        /// parameter is not named or holds nothing.</summary>
        public static string ScaleText(Element sheet, Element block, string parameter, string native)
        {
            if (!string.IsNullOrEmpty(parameter))
            {
                foreach (var element in new[] { sheet, block })
                {
                    if (element == null)
                        continue;
                    string text;
                    try
                    {
                        text = (PsModel.ParamText(element, parameter) ?? "").Trim();
                    }
                    catch (Exception)
                    {
                        text = "";
                    }
                    if (text.Length > 0)
                        return text;
                }
            }
            return native;
        }

        /// <summary>(revisions, rows) for the register, from the Selection tab's sheets.
        ///
        /// sheetRows are PsModel.Row objects already in natural number order, with
        /// their paper sizes read - the register reuses them rather than reading
        /// the title blocks a second time. scaleParam names the text parameter the
        /// Scale column comes from; blank is Revit's own.</summary>
        public static (List<RevisionColumn> Revisions, List<RegisterRow> Rows) ReadRegister(
            Document doc, IEnumerable<PsModel.Row> sheetRows, string disciplineParam, string seriesParam,
            string statusParam = "", string scaleParam = "")
        {
            var revisions = ReadRevisions(doc);
            var byElement = new Dictionary<long, RevisionColumn>();
            foreach (var column in revisions)
                byElement[column.ElementKey] = column;
            var scales = ReadScales(doc);
            var blocks = !string.IsNullOrEmpty(scaleParam) ? PsModel.ReadTitleBlocks(doc) : null;

            var rows = new List<RegisterRow>();
            foreach (var sheetRow in sheetRows ?? Enumerable.Empty<PsModel.Row>())
            {
                if (sheetRow == null || !sheetRow.IsSheet)
                    continue;
                var sheet = sheetRow.Element as ViewSheet;
                var row = new RegisterRow(sheetRow.Key, sheetRow.Number, sheetRow.Name);
                row.Size = sheetRow.Size ?? "";
                Element block = null;
                if (blocks != null && blocks.TryGetValue(sheetRow.Key, out var found))
                    block = found;
                row.Scale = ScaleText(sheetRow.Element, block, scaleParam,
                                      scales.TryGetValue(sheetRow.Key, out var native) ? native : "NTS");
                if (!string.IsNullOrEmpty(statusParam))
                    row.Status = (PsModel.ParamText(sheetRow.Element, statusParam) ?? "").Trim();
                if (!string.IsNullOrEmpty(disciplineParam))
                    row.Discipline = (PsModel.ParamText(sheetRow.Element, disciplineParam) ?? "").Trim();
                if (!string.IsNullOrEmpty(seriesParam))
                    row.Series = (PsModel.ParamText(sheetRow.Element, seriesParam) ?? "").Trim();

                List<ElementId> carried;
                try
                {
                    carried = sheet.GetAllRevisionIds().ToList();
                }
                catch (Exception)
                {
                    carried = new List<ElementId>();
                }
                foreach (var revisionId in carried)
                {
                    if (!byElement.TryGetValue(PsModel.EidValue(revisionId), out var column))
                        continue;
                    row.Cells[column.Key] = NumberOnSheet(sheet, revisionId, column);
                }

                long currentKey;
                try
                {
                    var current = sheet.GetCurrentRevision();
                    currentKey = PsModel.EidValue(current);
                }
                catch (Exception)
                {
                    currentKey = 0;
                }
                if (byElement.TryGetValue(currentKey, out var currentColumn))
                {
                    row.CurrentKey = currentColumn.Key;
                    row.Current = row.Cell(currentColumn.Key);
                    row.CurrentDate = currentColumn.Date;
                    row.CurrentSequence = SequenceText(currentColumn.Sequence);
                }
                rows.Add(row);
            }

            AssignStatusLetters(revisions, rows);
            return (revisions, rows);
        }

        /// <summary>What this sheet prints for this revision, per sheet numbering.</summary>
        internal static string NumberOnSheet(ViewSheet sheet, ElementId revisionId, RevisionColumn column)
        {
            try
            {
                string shown = sheet.GetRevisionNumberOnSheet(revisionId);
                if (!string.IsNullOrEmpty(shown))
                    return PsModel.ToText(shown);
            }
            catch (Exception)
            {
            }
            // Never Revision.RevisionNumber: it is project-wide, deprecated since
            // 2022, and gone in later releases. The sequence number is at least a
            // number Revit still has.
            return column.Sequence.ToString(Inv);
        }
    }
}
