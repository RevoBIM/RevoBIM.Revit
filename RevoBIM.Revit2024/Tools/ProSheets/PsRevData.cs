using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.ExtensibleStorage;

namespace RevoBIM.Tools.ProSheets
{
    /// <summary>
    /// Extra columns on revisions, kept in the model, and pushed to parameters (port of ps_revdata).
    ///
    /// Revit will not take parameters on the Revisions category, so a revision cannot carry
    /// "Revision notes" of its own the way a sheet can. The Revision Manager's own columns are
    /// stored in the model instead, through Extensible Storage, on ONE DataStorage element:
    /// - "columns" - the column definitions: name, type, choices, and where the column is pushed to
    /// - "values"  - every revision's value in every column, keyed by the revision's UniqueId so it
    ///               survives worksharing and copy-monitoring
    /// One element, not an entity on each revision: Revit locks an issued revision, and notes are
    /// exactly what gets written after an issue.
    ///
    /// Pushing: Sheets take the value of the sheet's current revision; revision clouds take their
    /// own revision's value. The parameter is a project or shared parameter the office has already
    /// added to that category. It is pushed on every Apply, and on demand.
    ///
    /// The schema GUID, name, field names and access levels are identical to the pyRevit version,
    /// so data written by either reads back in the other.
    /// </summary>
    public static partial class PsRevData
    {
        public const string SchemaGuid = "6f2c1d84-3a57-4b9e-9c41-52e0a7d3b1f6";
        public const string SchemaName = "RevoBIMRevisionData";
        // Values are stored as v1; columns from 1.44.0 as v2, which adds the group a column belongs
        // to. A v1 column list is read and the Issue Status, Issued To and Method columns added to it, once.
        public const string Format = "v1";
        public const string ColumnsFormat = "v2";

        // kind, as the type list words it
        public static readonly List<(string Key, string Label)> Kinds = new List<(string, string)>
        {
            ("text", "Text"), ("yesno", "Yes/No"), ("number", "Number"),
            ("date", "Date"), ("choice", "Choice list"),
        };
        public static readonly Dictionary<string, string> KindLabels = Kinds.ToDictionary(k => k.Key, k => k.Label, StringComparer.Ordinal);

        // where a column can be pushed, as the mapping list words it
        public static readonly List<(string Key, string Label)> Targets = new List<(string, string)>
        {
            ("", "Nowhere - kept in the model only"),
            ("sheets", "Sheets - their current revision's value"),
            ("clouds", "Revision clouds - their own revision's value"),
        };
        public static readonly Dictionary<string, string> TargetLabels = Targets.ToDictionary(k => k.Key, k => k.Label, StringComparer.Ordinal);

        // The parameter data each kind can be written into. 'YesNo' is a Yes/No parameter - an
        // Integer underneath, but a number written into one is nonsense, so it is told apart from
        // a whole-number parameter.
        public static readonly Dictionary<string, string[]> Accepts = new Dictionary<string, string[]>(StringComparer.Ordinal)
        {
            { "text", new[] { "String" } },
            { "date", new[] { "String" } },
            { "choice", new[] { "String" } },
            { "yesno", new[] { "YesNo", "Integer", "String" } },
            { "number", new[] { "Double", "Integer", "String" } },
        };

        public static readonly Dictionary<string, string> DataWords = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "String", "Text" }, { "YesNo", "Yes/No" }, { "Integer", "Integer" }, { "Double", "Number" },
        };

        // What a mapping does, for the tooltips that explain it.
        public const string MappingHelp =
            "Revit takes no parameters on revisions, so these columns are kept in " +
            "the model by this tool. Map one to a parameter to put its values " +
            "where Revit can show them:\n\n" +
            "SHEETS - each sheet takes the value of its current revision. Use it " +
            "for a label in the title block (the parameter must be a shared " +
            "parameter for a label to see it), or in a sheet list schedule.\n\n" +
            "REVISION CLOUDS - each cloud takes the value of its own revision. Use " +
            "it in a revision cloud tag, or to filter and schedule clouds.\n\n" +
            "Only instance parameters bound to that category are offered - a type " +
            "parameter would give every sheet the same value. Text, date and " +
            "choice columns need a Text parameter; Yes/No columns a Yes/No " +
            "parameter; Number columns a Number or Integer parameter.\n\n" +
            "Values are written on every Apply, so a sheet whose current revision " +
            "changes picks up the new value. To add a parameter: Open Project " +
            "Parameters, add it as an instance parameter to Sheets or Revision " +
            "Clouds, then come back here and pick it.";

        public const string DefaultNotes = "Revision notes";

        // Columns that belong to a group, treated apart from the rest: the Document Register's
        // Excel plots the Issued To and Method groups as its "Issued to:" rows - an x where a
        // revision is ticked - and the Issue Status column as each issue's status. Both groups
        // are Yes/No, always.
        public const string IssuedTo = "issued_to";
        public const string Method = "method";
        public const string Status = "status";
        public static readonly List<(string Key, string Label)> Groups = new List<(string, string)>
        {
            (IssuedTo, "Issued To"), (Method, "Issued Method"),
        };
        public static readonly Dictionary<string, string> GroupLabels = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { IssuedTo, "Issued To" }, { Method, "Issued Method" }, { Status, "Issue Status" }, { "", "" },
        };
        public const string StatusId = "status";
        public const string StatusName = "Issue Status";

        // ------------------------------------------------------------------ python-ish helpers

        /// <summary>u'{0}'.format(value) - None as "None" is never wanted here, so null gives "".</summary>
        private static string S(object value)
        {
            if (value == null) return "";
            if (value is string s) return s;
            if (value is bool b) return b ? "True" : "False";
            if (value is double d) return d.ToString("R", CultureInfo.InvariantCulture);
            if (value is float f) return ((double)f).ToString("R", CultureInfo.InvariantCulture);
            if (value is IFormattable fm) return fm.ToString(null, CultureInfo.InvariantCulture);
            return value.ToString();
        }

        /// <summary>Python truthiness, for "value or u''".</summary>
        private static bool Truthy(object value)
        {
            switch (value)
            {
                case null: return false;
                case string s: return s.Length > 0;
                case bool b: return b;
                case int i: return i != 0;
                case long l: return l != 0;
                case double d: return d != 0.0;
                default: return true;
            }
        }

        private static string Or(object value) => Truthy(value) ? S(value) : "";

        /// <summary>One extra column.</summary>
        public class Column
        {
            public string Id;
            public string Name;
            public string Kind;
            public List<string> Choices;
            public string Target;
            public string Parameter;
            public string Group;

            public Column(object columnId, string name, string kind = "text", IEnumerable<string> choices = null,
                          string target = "", string parameter = "", string group = "")
            {
                Id = S(columnId);
                Name = (name ?? "").Trim();
                Kind = kind != null && KindLabels.ContainsKey(kind) ? kind : "text";
                Choices = (choices ?? Enumerable.Empty<string>())
                    .Select(one => S(one).Trim()).Where(one => one.Length > 0).ToList();
                Target = target != null && TargetLabels.ContainsKey(target) ? target : "";
                Parameter = (parameter ?? "").Trim();
                Group = group != null && GroupLabels.ContainsKey(group) ? group : "";
                if (Group == IssuedTo || Group == Method)
                    // Ticked or not, per revision: where the issue went, and how.
                    Kind = "yesno";
                else if (Group == Status)
                    Kind = "text";
            }

            public bool Pushed => !string.IsNullOrEmpty(Target) && !string.IsNullOrEmpty(Parameter);

            public Column Copy()
            {
                return new Column(Id, Name, Kind, new List<string>(Choices), Target, Parameter, Group);
            }

            public bool Same(Column other)
            {
                return Id == other.Id && Name == other.Name && Kind == other.Kind
                       && Choices.SequenceEqual(other.Choices) && Target == other.Target
                       && Parameter == other.Parameter && Group == other.Group;
            }
        }

        /// <summary>One project or shared parameter bound to Sheets or Revision Clouds
        /// (ps_revdata's {'name', 'categories', 'instance', 'data'} dict).</summary>
        public class BoundParameter
        {
            public string Name = "";
            /// <summary>'sheets' and/or 'clouds'.</summary>
            public HashSet<string> Categories = new HashSet<string>(StringComparer.Ordinal);
            public bool Instance;
            /// <summary>'String', 'YesNo', 'Integer', 'Double' or "".</summary>
            public string Data = "";
        }

        /// <summary>The Issue Status column and the Issued To / Method groups a model starts with -
        /// rename, add to or remove them in the manager.</summary>
        public static List<Column> GroupedDefaults()
        {
            var list = new List<Column> { new Column(StatusId, StatusName, "text", group: Status) };
            foreach (var number in new[] { 1, 2, 3 })
                list.Add(new Column("it" + number, "Issued To " + number, "yesno", group: IssuedTo));
            foreach (var number in new[] { 1, 2 })
                list.Add(new Column("m" + number, "Issued Method " + number, "yesno", group: Method));
            return list;
        }

        /// <summary>What a model with nothing stored starts with.</summary>
        public static List<Column> DefaultColumns()
        {
            var list = new List<Column> { new Column("notes", DefaultNotes, "text") };
            list.AddRange(GroupedDefaults());
            return list;
        }

        /// <summary>A column list from before 1.44.0, with the grouped defaults added where nothing
        /// of theirs is there - a name already taken is skipped.</summary>
        public static List<Column> WithGroups(IEnumerable<Column> columns)
        {
            var output = new List<Column>(columns);
            var ids = new HashSet<string>(output.Select(c => c.Id), StringComparer.Ordinal);
            var names = new HashSet<string>(output.Select(c => c.Name.ToLowerInvariant()), StringComparer.Ordinal);
            foreach (var column in GroupedDefaults())
            {
                if (ids.Contains(column.Id) || names.Contains(column.Name.ToLowerInvariant()))
                    continue;
                output.Add(column);
            }
            return output;
        }

        /// <summary>The columns as the manager lays them out: the plain ones, then Issue Status,
        /// then each group with its members side by side.</summary>
        public static List<Column> GroupOrder(IEnumerable<Column> columns)
        {
            var ranks = new Dictionary<string, int>(StringComparer.Ordinal)
            {
                { "", 0 }, { Status, 1 }, { IssuedTo, 2 }, { Method, 3 },
            };
            return columns.Select((column, index) => (column, index))
                .OrderBy(p => ranks.TryGetValue(p.column.Group ?? "", out var r) ? r : 0)
                .ThenBy(p => p.index)
                .Select(p => p.column).ToList();
        }

        public static Column StatusColumn(IEnumerable<Column> columns)
        {
            foreach (var column in columns)
                if (column.Group == Status)
                    return column;
            return null;
        }

        /// <summary>
        /// The Excel register's "Issued to:" block. <paramref name="values"/> is
        /// {revision key: {column id: stored value}} and <paramref name="revisions"/> the revision keys
        /// of the worksheet's issue columns, in order. Returns [(name, group, [ticked per revision])] -
        /// the Issued To group first, then Method - leaving out any column no revision on the worksheet
        /// has ticked.
        /// </summary>
        public static List<(string Name, string Group, List<bool> Ticks)> IssueRows(
            IEnumerable<Column> columns, Dictionary<string, Dictionary<string, string>> values, IEnumerable<string> revisions)
        {
            var cols = columns.ToList();
            var revs = revisions.ToList();
            var rows = new List<(string, string, List<bool>)>();
            foreach (var (group, _) in Groups)
            {
                foreach (var column in cols.Where(one => one.Group == group))
                {
                    var ticks = revs.Select(key =>
                    {
                        Dictionary<string, string> row = null;
                        if (key != null && values != null) values.TryGetValue(key, out row);
                        return row != null && row.TryGetValue(column.Id, out var v) && v == "1";
                    }).ToList();
                    if (ticks.Contains(true))
                        rows.Add((column.Name, group, ticks));
                }
            }
            return rows;
        }

        /// <summary>The columns the Document Register shows as rows under its revision headings
        /// (1.51.0): Issue Status first, then the Issued To group, then Issued Method - every column
        /// whether ticked anywhere or not, so it can be ticked from the register.</summary>
        public static List<Column> IssueBlock(IEnumerable<Column> columns)
        {
            var cols = columns.ToList();
            var block = new List<Column>();
            var status = StatusColumn(cols);
            if (status != null)
                block.Add(status);
            foreach (var (group, _) in Groups)
                block.AddRange(cols.Where(column => column.Group == group));
            return block;
        }

        /// <summary>What divides each row of the block from the next, in order: "frame" under Issue
        /// Status and between the groups (the Excel's medium lines), "line" between rows of one group,
        /// null under the last.</summary>
        public static List<string> BlockEdges(IList<Column> block)
        {
            var edges = new List<string>();
            for (int index = 0; index < block.Count; index++)
            {
                var column = block[index];
                var following = index + 1 < block.Count ? block[index + 1] : null;
                if (following == null)
                    edges.Add(null);
                else if (column.Group == Status || following.Group != column.Group)
                    edges.Add("frame");
                else
                    edges.Add("line");
            }
            return edges;
        }

        /// <summary>A stored value as the register compares it: a Yes/No left empty is a No.</summary>
        public static string StoredValue(Column column, object value)
        {
            string text = S(value).Trim();
            if (column.Kind == "yesno")
                return text == "1" ? "1" : "0";
            return text;
        }

        /// <summary>
        /// <paramref name="values"/> ({revision uid: {column id: value}}) with <paramref name="changes"/>
        /// played over it: [(uid, column id, value)] in order. Returns (values, done, problems) - a
        /// column no longer in the model, or a value it refuses, is a problem and changes nothing.
        /// </summary>
        public static (Dictionary<string, Dictionary<string, string>> Values, int Done, List<string> Problems) ApplyChanges(
            IEnumerable<Column> columns, Dictionary<string, Dictionary<string, string>> values,
            IEnumerable<(string Uid, string ColumnId, object Value)> changes)
        {
            var byId = new Dictionary<string, Column>(StringComparer.Ordinal);
            foreach (var column in columns) byId[column.Id] = column;
            var output = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
            foreach (var pair in values ?? new Dictionary<string, Dictionary<string, string>>())
                output[pair.Key] = new Dictionary<string, string>(pair.Value, StringComparer.Ordinal);
            int done = 0;
            var problems = new List<string>();
            foreach (var (uid, columnId, value) in changes)
            {
                if (columnId == null || !byId.TryGetValue(columnId, out var column))
                {
                    problems.Add(string.Format("The column {0} is no longer in the model.", columnId));
                    continue;
                }
                if (string.IsNullOrEmpty(uid))
                {
                    problems.Add(string.Format("{0}: the revision is no longer in the model.", column.Name));
                    continue;
                }
                var (ok, stored) = Normalise(column, value);
                if (!ok)
                {
                    problems.Add(stored);
                    continue;
                }
                if (!output.TryGetValue(uid, out var row))
                    output[uid] = row = new Dictionary<string, string>(StringComparer.Ordinal);
                row[column.Id] = stored;
                done += 1;
            }
            return (output, done, problems);
        }

        // ==========================================================================
        // pure decisions
        // ==========================================================================

        public static string Escape(object text)
        {
            return S(text).Replace("\\", "\\\\").Replace("\t", "\\t").Replace("\n", "\\n").Replace("\r", "");
        }

        public static string Unescape(string text)
        {
            var output = new StringBuilder();
            int index = 0;
            text = text ?? "";
            while (index < text.Length)
            {
                char ch = text[index];
                if (ch == '\\' && index + 1 < text.Length)
                {
                    char following = text[index + 1];
                    output.Append(following == 't' ? '\t' : following == 'n' ? '\n' : following);
                    index += 2;
                    continue;
                }
                output.Append(ch);
                index += 1;
            }
            return output.ToString();
        }

        /// <summary>A line split on tabs that are not escaped.</summary>
        internal static List<string> Split(string line)
        {
            var parts = new List<string>();
            var current = new StringBuilder();
            int index = 0;
            while (index < line.Length)
            {
                char ch = line[index];
                if (ch == '\\' && index + 1 < line.Length)
                {
                    current.Append(line, index, 2);
                    index += 2;
                    continue;
                }
                if (ch == '\t')
                {
                    parts.Add(current.ToString());
                    current.Clear();
                }
                else
                {
                    current.Append(ch);
                }
                index += 1;
            }
            parts.Add(current.ToString());
            return parts.Select(Unescape).ToList();
        }

        public static string EncodeColumns(IEnumerable<Column> columns)
        {
            var lines = new List<string> { ColumnsFormat };
            foreach (var column in columns)
            {
                lines.Add(string.Join("\t", new[]
                {
                    Escape(column.Id), Escape(column.Name), Escape(column.Kind),
                    Escape(string.Join("|", column.Choices)), Escape(column.Target),
                    Escape(column.Parameter), Escape(column.Group),
                }));
            }
            return string.Join("\n", lines);
        }

        /// <summary>The stored columns, or null when nothing usable is stored. A list stored before
        /// 1.44.0 (v1) gains the grouped defaults.</summary>
        public static List<Column> DecodeColumns(string text)
        {
            var lines = (text ?? "").Split('\n');
            string version = lines.Length > 0 ? lines[0].Trim() : "";
            if (version != Format && version != ColumnsFormat)
                return null;
            var columns = new List<Column>();
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var line in lines.Skip(1))
            {
                if (line.Trim().Length == 0)
                    continue;
                var parts = Split(line);
                for (int pad = 0; pad < 7; pad++) parts.Add("");
                var column = new Column(parts[0], parts[1], parts[2],
                                        parts[3].Length > 0 ? parts[3].Split('|').ToList() : new List<string>(),
                                        parts[4], parts[5], parts[6]);
                if (column.Id.Length > 0 && column.Name.Length > 0 && !seen.Contains(column.Id))
                {
                    seen.Add(column.Id);
                    columns.Add(column);
                }
            }
            if (version == Format)
                columns = WithGroups(columns);
            return columns;
        }

        /// <summary>{revision uid: {column id: value}} as text; empty values left out.</summary>
        public static string EncodeValues(Dictionary<string, Dictionary<string, string>> values)
        {
            var lines = new List<string> { Format };
            foreach (var uid in values.Keys.OrderBy(k => k, StringComparer.Ordinal))
            {
                var row = values[uid] ?? new Dictionary<string, string>();
                foreach (var columnId in row.Keys.OrderBy(k => k, StringComparer.Ordinal))
                {
                    var value = row[columnId];
                    if (string.IsNullOrEmpty(value))
                        continue;
                    lines.Add(string.Join("\t", new[] { Escape(uid), Escape(columnId), Escape(value) }));
                }
            }
            return string.Join("\n", lines);
        }

        public static Dictionary<string, Dictionary<string, string>> DecodeValues(string text)
        {
            var lines = (text ?? "").Split('\n');
            var values = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
            if (lines.Length == 0 || lines[0].Trim() != Format)
                return values;
            foreach (var line in lines.Skip(1))
            {
                if (line.Trim().Length == 0)
                    continue;
                var parts = Split(line);
                if (parts.Count < 3 || parts[0].Length == 0 || parts[1].Length == 0)
                    continue;
                if (!values.TryGetValue(parts[0], out var row))
                    values[parts[0]] = row = new Dictionary<string, string>(StringComparer.Ordinal);
                row[parts[1]] = parts[2];
            }
            return values;
        }

        // Python 2's \d and \s without re.UNICODE are ASCII; kept so.
        internal static readonly Regex Number = new Regex(@"^[ \t\n\r\f\v]*[-+]?([0-9]+(\.[0-9]*)?|\.[0-9]+)[ \t\n\r\f\v]*$", RegexOptions.CultureInvariant);

        /// <summary>(ok, value as stored, or why not) for a value typed into a column.</summary>
        public static (bool Ok, string Value) Normalise(Column column, object value)
        {
            if (column.Kind == "yesno")
            {
                if (value is bool b)
                    return (true, b ? "1" : "0");
                string lowered = Or(value).Trim().ToLowerInvariant();
                return (true, lowered == "1" || lowered == "true" || lowered == "yes" || lowered == "y" ? "1" : "0");
            }
            string text = S(value).Trim();
            if (column.Kind == "number")
            {
                if (text.Length > 0 && !Number.IsMatch(text))
                    return (false, string.Format("{0} takes a number.", column.Name));
                return (true, text);
            }
            if (column.Kind == "choice" && text.Length > 0 && column.Choices.Count > 0 && !column.Choices.Contains(text))
                return (false, string.Format("{0} takes one of: {1}.", column.Name, string.Join(", ", column.Choices)));
            return (true, text);
        }

        /// <summary>A stored value as the grid and the searches read it.</summary>
        public static string Shown(Column column, string value)
        {
            if (column.Kind == "yesno")
                return value == "1" ? "Yes" : "No";
            return value ?? "";
        }

        /// <summary>Why a column cannot be added or renamed like that, or "".</summary>
        public static string ColumnProblem(string name, string kind, IEnumerable<string> choices, IEnumerable<Column> columns,
                                           string columnId = null)
        {
            name = (name ?? "").Trim();
            if (name.Length == 0)
                return "A column needs a name.";
            foreach (var column in columns)
            {
                if (column.Id != columnId && column.Name.ToLowerInvariant() == name.ToLowerInvariant())
                    return string.Format("There is already a column called \"{0}\".", column.Name);
            }
            if (kind == null || !KindLabels.ContainsKey(kind))
                return "Choose a type for the column.";
            if (kind == "choice" && !(choices ?? Enumerable.Empty<string>()).Any(one => S(one).Trim().Length > 0))
                return "A choice list needs at least one choice.";
            return "";
        }

        public static string NewColumnId(IEnumerable<Column> columns)
        {
            var taken = new HashSet<string>(columns.Select(c => c.Id), StringComparer.Ordinal);
            int number = 1;
            while (taken.Contains("c" + number))
                number += 1;
            return "c" + number;
        }

        /// <summary>Python float(text): what it parses, including inf / nan.</summary>
        private static bool TryPyFloat(string text, out double number)
        {
            var t = (text ?? "").Trim();
            if (double.TryParse(t, NumberStyles.Float, CultureInfo.InvariantCulture, out number))
                return true;
            var bare = t.TrimStart('+', '-').ToLowerInvariant();
            bool negative = t.StartsWith("-", StringComparison.Ordinal);
            if (t.Length - bare.Length <= 1)
            {
                if (bare == "inf" || bare == "infinity")
                {
                    number = negative ? double.NegativeInfinity : double.PositiveInfinity;
                    return true;
                }
                if (bare == "nan")
                {
                    number = double.NaN;
                    return true;
                }
            }
            number = 0;
            return false;
        }

        /// <summary>
        /// (ok, value) to write a column's value into a parameter of <paramref name="storage"/>
        /// ('String', 'Integer' or 'Double'), or (false, why). The value is a string, an int or a double.
        /// </summary>
        public static (bool Ok, object Value) ParameterValue(Column column, string storage, object value)
        {
            string text = S(value);
            if (!Accepts.TryGetValue(column.Kind ?? "", out var accepted) || !accepted.Contains(storage))
                return (false, string.Format("a {0} parameter cannot hold a {1} column", storage,
                    KindLabels.TryGetValue(column.Kind ?? "", out var label) ? label : column.Kind));
            if (storage == "YesNo")
                storage = "Integer";
            if (storage == "String")
                return (true, Shown(column, text));
            if (column.Kind == "yesno")
                return (true, text == "1" ? 1 : 0);
            if (text.Trim().Length == 0)
                return (false, "empty");
            if (!TryPyFloat(text, out var number))
                return (false, string.Format("\"{0}\" is not a number", text));
            if (storage == "Integer")
                // Python 2 round(): half away from zero.
                return (true, Convert.ToInt32(Math.Round(number, MidpointRounding.AwayFromZero)));
            return (true, number);
        }

        /// <summary>
        /// [(name, data)] a column of <paramref name="kind"/> can be pushed into on <paramref name="target"/>.
        /// Only instance parameters bound to the target's category, holding data the column's kind can
        /// be written as.
        /// </summary>
        public static List<(string Name, string Data)> Usable(IEnumerable<BoundParameter> parameters, string target, string kind = null)
        {
            string[] accepted = !string.IsNullOrEmpty(kind)
                ? (Accepts.TryGetValue(kind, out var a) ? a : null)
                : new[] { "String", "YesNo", "Integer", "Double" };
            var found = new Dictionary<string, string>(StringComparer.Ordinal);
            var order = new List<string>();
            foreach (var parameter in parameters ?? Enumerable.Empty<BoundParameter>())
            {
                if (!parameter.Instance)
                    continue;
                if (parameter.Categories == null || !parameter.Categories.Contains(target ?? ""))
                    continue;
                if (accepted == null || !accepted.Contains(parameter.Data))
                    continue;
                if (!found.ContainsKey(parameter.Name)) order.Add(parameter.Name);
                found[parameter.Name] = parameter.Data;
            }
            return order.Select(name => (name, found[name]))
                .OrderBy(item => item.name.ToLowerInvariant(), StringComparer.Ordinal).ToList();
        }

        /// <summary>The names holding every word of <paramref name="keyword"/>, anywhere, any case.
        /// An empty keyword keeps them all.</summary>
        public static List<string> Matching(IEnumerable<string> names, string keyword)
        {
            var words = (keyword ?? "").ToLowerInvariant()
                .Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            if (words.Length == 0)
                return names.ToList();
            return names.Where(name => words.All(word => (name ?? "").ToLowerInvariant().Contains(word))).ToList();
        }

        /// <summary>Why <paramref name="name"/> is not offered for this column and target, or "".</summary>
        public static string WhyNot(IEnumerable<BoundParameter> parameters, string target, string kind, string name)
        {
            if (string.IsNullOrEmpty(name))
                return "";
            string where = target == "sheets" ? "Sheets" : "Revision Clouds";
            var matching = (parameters ?? Enumerable.Empty<BoundParameter>()).Where(one => one.Name == name).ToList();
            if (matching.Count == 0)
                return string.Format("\"{0}\" is not in the project. Add it in Project Parameters " +
                                     "as an instance parameter on {1}.", name, where);
            if (!matching.Any(one => one.Categories != null && one.Categories.Contains(target ?? "")))
                return string.Format("\"{0}\" is not bound to {1}.", name, where);
            if (!matching.Any(one => one.Instance))
                return string.Format("\"{0}\" is a type parameter - every {1} would show the same " +
                                     "value. Make it an instance parameter.", name, target == "sheets" ? "sheet" : "cloud");
            var datas = matching.Select(one => one.Data).ToList();
            Accepts.TryGetValue(kind ?? "", out var accepted);
            accepted = accepted ?? new string[0];
            if (!datas.Any(data => accepted.Contains(data)))
                return string.Format("\"{0}\" holds {1}; a {2} column needs {3}.", name,
                    datas[0] != null && DataWords.TryGetValue(datas[0], out var word) ? word : "another type of data",
                    KindLabels.TryGetValue(kind ?? "", out var label) ? label : kind,
                    string.Join(" or ", accepted.Select(one => DataWords[one])));
            return "";
        }

        /// <summary>
        /// {sheet key: value} - each sheet takes its current revision's value. <paramref name="sheets"/>
        /// is [(sheet key, current revision key or null)]. A sheet with no current revision, or whose
        /// revision has no value, gets the empty value: a stale note from a superseded revision is
        /// worse than none.
        /// </summary>
        public static Dictionary<long, string> SheetValues(IEnumerable<(long SheetKey, long? RevisionKey)> sheets,
                                                           Dictionary<long, Dictionary<string, string>> values, Column column)
        {
            var output = new Dictionary<long, string>();
            foreach (var (sheetKey, revisionKey) in sheets)
            {
                string value = "";
                if (revisionKey.HasValue && values.TryGetValue(revisionKey.Value, out var row) && row != null
                    && row.TryGetValue(column.Id, out var v))
                    value = v;
                output[sheetKey] = value;
            }
            return output;
        }

        // ==========================================================================
        // Revit
        // ==========================================================================

        /// <summary>The schema, made if this session has not got it yet (ps_revdata._schema;
        /// named SchemaCore because "Schema" is the Revit type).</summary>
        internal static Schema SchemaCore()
        {
            var found = Schema.Lookup(new Guid(SchemaGuid));
            if (found != null)
                return found;
            var builder = new SchemaBuilder(new Guid(SchemaGuid));
            builder.SetReadAccessLevel(AccessLevel.Public);
            builder.SetWriteAccessLevel(AccessLevel.Public);
            builder.SetSchemaName(SchemaName);
            builder.SetDocumentation("RevoBIM Revision Manager: extra columns on revisions, and their values");
            builder.AddSimpleField("columns", typeof(string));
            builder.AddSimpleField("values", typeof(string));
            return builder.Finish();
        }

        /// <summary>The DataStorage element holding the data, or null.</summary>
        internal static DataStorage Store(Document doc, Schema schema)
        {
            try
            {
                foreach (var element in new FilteredElementCollector(doc).OfClass(typeof(DataStorage)))
                {
                    try
                    {
                        if (element.GetEntity(schema).IsValid())
                            return (DataStorage)element;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }
            catch (Exception)
            {
            }
            return null;
        }

        /// <summary>(columns, {revision uid: {column id: value}}). Never throws.</summary>
        public static (List<Column> Columns, Dictionary<string, Dictionary<string, string>> Values) Read(Document doc)
        {
            Schema schema;
            try
            {
                schema = Schema.Lookup(new Guid(SchemaGuid));
            }
            catch (Exception)
            {
                schema = null;
            }
            if (schema == null)
                return (DefaultColumns(), new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal));
            var element = Store(doc, schema);
            if (element == null)
                return (DefaultColumns(), new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal));
            List<Column> columns;
            Dictionary<string, Dictionary<string, string>> values;
            try
            {
                var entity = element.GetEntity(schema);
                columns = DecodeColumns(entity.Get<string>("columns"));
                values = DecodeValues(entity.Get<string>("values"));
            }
            catch (Exception)
            {
                return (DefaultColumns(), new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal));
            }
            return (columns ?? DefaultColumns(), values);
        }

        /// <summary>Store it. Inside a transaction the caller has open.</summary>
        public static void Write(Document doc, IEnumerable<Column> columns, Dictionary<string, Dictionary<string, string>> values)
        {
            var schema = SchemaCore();
            Element element = Store(doc, schema) ?? DataStorage.Create(doc);
            var entity = new Entity(schema);
            entity.Set<string>("columns", EncodeColumns(columns));
            entity.Set<string>("values", EncodeValues(values));
            element.SetEntity(entity);
        }

        internal static string StorageName(Parameter parameter)
        {
            try
            {
                return parameter.StorageType.ToString();
            }
            catch (Exception)
            {
                return "";
            }
        }

        /// <summary>'String', 'YesNo', 'Integer', 'Double' or "" for a definition.</summary>
        internal static string DataOf(Definition definition)
        {
            ForgeTypeId spec;
            try
            {
                spec = definition.GetDataType();
            }
            catch (Exception)
            {
                return "";
            }
            var wanted = new List<(Func<ForgeTypeId> Spec, string Kind)>
            {
                (() => SpecTypeId.String.Text, "String"),
                (() => SpecTypeId.Boolean.YesNo, "YesNo"),
                (() => SpecTypeId.Int.Integer, "Integer"),
                (() => SpecTypeId.Number, "Double"),
            };
            foreach (var (get, kind) in wanted)
            {
                try
                {
                    var one = get();
                    if ((spec != null && spec.Equals(one)) || (spec?.TypeId ?? "") == (one?.TypeId ?? ""))
                        return kind;
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return "";
        }

        /// <summary>Every project and shared parameter bound to Sheets or Revision Clouds. Never throws.</summary>
        public static List<BoundParameter> BoundParameters(Document doc)
        {
            var targets = new Dictionary<long, string>
            {
                { (long)BuiltInCategory.OST_Sheets, "sheets" },
                { (long)BuiltInCategory.OST_RevisionClouds, "clouds" },
            };
            var found = new List<BoundParameter>();
            DefinitionBindingMapIterator iterator;
            try
            {
                iterator = doc.ParameterBindings.ForwardIterator();
                iterator.Reset();
            }
            catch (Exception)
            {
                return found;
            }
            while (true)
            {
                Definition definition;
                Binding binding;
                try
                {
                    if (!iterator.MoveNext())
                        break;
                    definition = iterator.Key;
                    binding = iterator.Current as Binding;
                }
                catch (Exception)
                {
                    break;
                }
                var categories = new HashSet<string>(StringComparer.Ordinal);
                try
                {
                    foreach (Category category in ((ElementBinding)binding).Categories)
                    {
                        if (targets.TryGetValue(PsModel.EidValue(category.Id), out var key))
                            categories.Add(key);
                    }
                }
                catch (Exception)
                {
                }
                if (categories.Count == 0)
                    continue;
                bool instance;
                try
                {
                    instance = binding.GetType().Name == "InstanceBinding";
                }
                catch (Exception)
                {
                    instance = false;
                }
                found.Add(new BoundParameter
                {
                    Name = definition?.Name ?? "",
                    Categories = categories,
                    Instance = instance,
                    Data = DataOf(definition),
                });
            }
            return found;
        }

        /// <summary>[(name, data)] the column dialog offers for a target.</summary>
        public static List<(string Name, string Data)> ParameterNames(Document doc, string target, string kind = null)
        {
            return Usable(BoundParameters(doc), target, kind);
        }

        /// <summary>(written, problem) for one element.</summary>
        internal static (bool Written, string Problem) Set(Element element, Column column, string value)
        {
            var parameter = element.LookupParameter(column.Parameter);
            if (parameter == null)
                return (false, "missing");
            if (parameter.IsReadOnly)
                return (false, "read-only");
            var (ok, converted) = ParameterValue(column, StorageName(parameter), value);
            if (!ok)
                return (false, (string)converted);
            switch (converted)
            {
                case string s: parameter.Set(s); break;
                case int i: parameter.Set(i); break;
                case double d: parameter.Set(d); break;
            }
            return (true, "");
        }

        /// <summary>
        /// The Document Register's staged issue data, written (1.51.0). <paramref name="changes"/> is
        /// [(revision uid, column id, value)] in the order staged; <paramref name="keysByUid"/> every
        /// revision's element key by uid, for the push. Reads what is stored now, plays the changes
        /// over it, stores it and pushes the mapped columns - one transaction. (done, problems).
        /// </summary>
        public static (int Done, List<string> Problems) WriteChanges(Document doc,
            IEnumerable<(string Uid, string ColumnId, object Value)> changes, Dictionary<string, long> keysByUid)
        {
            using (var transaction = new Transaction(doc, "RevoBIM - Document Register issue data"))
            {
                try
                {
                    transaction.Start();
                }
                catch (Exception err)
                {
                    return (0, new List<string> { string.Format("The transaction would not start: {0}", err.Message) });
                }
                int done;
                List<string> problems;
                try
                {
                    var (columns, stored) = Read(doc);
                    var applied = ApplyChanges(columns, stored, changes);
                    done = applied.Done;
                    problems = applied.Problems;
                    Write(doc, columns, applied.Values);
                    var byKey = new Dictionary<long, Dictionary<string, string>>();
                    foreach (var pair in keysByUid)
                        byKey[pair.Value] = applied.Values.TryGetValue(pair.Key, out var row) && row != null
                            ? row : new Dictionary<string, string>(StringComparer.Ordinal);
                    var (_, pushed) = Push(doc, columns, byKey);
                    problems.AddRange(pushed);
                }
                catch (Exception err)
                {
                    try
                    {
                        transaction.RollBack();
                    }
                    catch (Exception)
                    {
                    }
                    return (0, new List<string> { string.Format("Nothing was changed: {0}", err.Message) });
                }
                try
                {
                    transaction.Commit();
                }
                catch (Exception err)
                {
                    return (0, new List<string> { string.Format("Revit would not keep the changes: {0}", err.Message) });
                }
                return (done, problems);
            }
        }

        /// <summary>
        /// Write every pushed column into its parameters. (count, problems). <paramref name="valuesByKey"/>
        /// is keyed by revision element key. Inside a transaction the caller has open.
        /// </summary>
        public static (int Count, List<string> Problems) Push(Document doc, IEnumerable<Column> columns,
                                                              Dictionary<long, Dictionary<string, string>> valuesByKey)
        {
            int count = 0;
            var problems = new List<string>();
            var pushed = columns.Where(column => column.Pushed).ToList();
            if (pushed.Count == 0)
                return (count, problems);
            var sheets = new List<(Element Element, long? Key)>();
            var clouds = new List<(Element Element, long? Key)>();
            if (pushed.Any(column => column.Target == "sheets"))
            {
                foreach (ViewSheet sheet in new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)))
                {
                    long? key;
                    try
                    {
                        var current = sheet.GetCurrentRevision();
                        key = current != null && PsModel.EidValue(current) > 0 ? PsModel.EidValue(current) : (long?)null;
                    }
                    catch (Exception)
                    {
                        key = null;
                    }
                    sheets.Add((sheet, key));
                }
            }
            if (pushed.Any(column => column.Target == "clouds"))
            {
                foreach (RevisionCloud cloud in new FilteredElementCollector(doc).OfClass(typeof(RevisionCloud)))
                {
                    try
                    {
                        clouds.Add((cloud, PsModel.EidValue(cloud.RevisionId)));
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }
            foreach (var column in pushed)
            {
                var targets = column.Target == "sheets" ? sheets : clouds;
                var tally = new Dictionary<string, int>(StringComparer.Ordinal);
                foreach (var (element, revisionKey) in targets)
                {
                    string value = "";
                    if (revisionKey.HasValue && valuesByKey.TryGetValue(revisionKey.Value, out var row) && row != null
                        && row.TryGetValue(column.Id, out var v))
                        value = v ?? "";
                    bool written;
                    string problem;
                    try
                    {
                        (written, problem) = Set(element, column, value);
                    }
                    catch (Exception err)
                    {
                        written = false;
                        problem = err.Message;
                    }
                    if (written)
                        count += 1;
                    else if (problem != "empty")
                        tally[problem] = (tally.TryGetValue(problem, out var t) ? t : 0) + 1;
                }
                string noun = column.Target == "sheets" ? "sheet" : "cloud";
                foreach (var pair in tally.OrderBy(p => p.Key, StringComparer.Ordinal))
                {
                    problems.Add(string.Format("{0} -> \"{1}\": {2} {3}{4} not written - {5}",
                        column.Name, column.Parameter, pair.Value, noun, pair.Value == 1 ? "" : "s", pair.Key));
                }
            }
            return (count, problems);
        }
    }
}
