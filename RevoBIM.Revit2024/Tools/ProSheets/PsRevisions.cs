using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace RevoBIM.Tools.ProSheets
{
    /// <summary>
    /// The Revision Manager's model: read, stage, and write the project's revisions (port of ps_revisions).
    ///
    /// What Revit's own Sheet Issues/Revisions dialog does - add, delete, edit, move up and down, merge
    /// up and down, Per Project / Per Sheet numbering, arc length - plus what it does not: how many sheets
    /// each revision is on, a search on every column, several rows moved at once, and a question before
    /// a revision that is in use is deleted.
    ///
    /// Nothing is written until Apply. Every change is staged in a Staging and shown green; Apply turns
    /// the staging into a Plan and the plan is written in one transaction on Revit's thread. The staging
    /// and the plan have no WPF and no Revit in them - the window is only a view of a Staging.
    ///
    /// The order the plan is written in matters, because Revit locks an issued revision against edits
    /// and only merges revisions that sit next to each other:
    ///  1. numbering mode and arc length
    ///  2. revisions being un-issued are un-issued first, so they can be edited
    ///  3. new revisions are created
    ///  4. field edits
    ///  5. merges - each one moved next to its target first, then combined
    ///  6. deletes
    ///  7. the final order
    ///  8. revisions being issued are issued last, after their edits
    ///  9. the extra columns are stored, and pushed into their parameters - last, so a sheet's current
    ///     revision is the one it will have from now on
    /// Each step is tried on its own. One that Revit refuses is reported and the rest still go in.
    ///
    /// Keys: Entry.Key is text - the revision's element id as text for a revision in the model, "newN"
    /// for one added here. Entry.ElementKey is the element id (long), null for a new revision.
    /// </summary>
    public static partial class PsRevisions
    {
        // The editable fields, in the order the window shows them.
        public static readonly string[] Fields = { "numbering", "date", "desc", "issued", "issued_to", "issued_by", "show" };
        public static readonly string[] TextFields = { "date", "desc", "issued_to", "issued_by" };

        // The fields that never take one value across several selected revisions.
        public static readonly string[] AllAtOnceRefused = { "date" };

        // Show, as Revit's dialog words it, against RevisionVisibility's names.
        public static readonly List<(string Label, string Name)> ShowChoices = new List<(string, string)>
        {
            ("None", "Hidden"), ("Tag", "TagVisible"), ("Cloud and Tag", "CloudAndTagVisible"),
        };
        public static readonly List<string> ShowLabels = ShowChoices.Select(c => c.Label).ToList();
        public const string DefaultShow = "Cloud and Tag";

        public const string PerProject = "PerProject";
        public const string PerSheet = "PerSheet";

        public const double FeetToMm = 304.8;

        // ------------------------------------------------------------------ python-ish helpers

        /// <summary>u'{0}'.format(value), null as "".</summary>
        internal static string S(object value)
        {
            if (value == null) return "";
            if (value is string s) return s;
            if (value is bool b) return b ? "True" : "False";
            if (value is double d) return d.ToString("R", CultureInfo.InvariantCulture);
            if (value is IFormattable fm) return fm.ToString(null, CultureInfo.InvariantCulture);
            return value.ToString();
        }

        /// <summary>Python truthiness.</summary>
        internal static bool Truthy(object value)
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

        internal static string Or(object value) => Truthy(value) ? S(value) : "";

        /// <summary>ps_model.natural_key as a comparer: P-9 before P-10, which plain string order does not.
        /// Kept here (rather than calling PsModel) so the comparison is exactly the Python tuple order.</summary>
        internal sealed class NaturalComparer : IComparer<string>
        {
            public static readonly NaturalComparer Instance = new NaturalComparer();
            private static readonly Regex Digits = new Regex("([0-9]+)", RegexOptions.CultureInvariant);

            private static List<(int Kind, string Number, string Text)> Key(string text)
            {
                var key = new List<(int, string, string)>();
                foreach (var part in Digits.Split(text ?? ""))
                {
                    if (part.Length > 0 && part.All(ch => ch >= '0' && ch <= '9'))
                        key.Add((1, part.TrimStart('0'), ""));
                    else
                        key.Add((0, "", part.ToLowerInvariant()));
                }
                return key;
            }

            public int Compare(string x, string y)
            {
                var a = Key(x);
                var b = Key(y);
                for (int i = 0; i < Math.Min(a.Count, b.Count); i++)
                {
                    int c = a[i].Kind.CompareTo(b[i].Kind);
                    if (c != 0) return c;
                    // Whole numbers compared by value, any length: fewer digits (leading zeros dropped) is smaller.
                    c = a[i].Number.Length.CompareTo(b[i].Number.Length);
                    if (c != 0) return c;
                    c = string.CompareOrdinal(a[i].Number, b[i].Number);
                    if (c != 0) return c;
                    c = string.CompareOrdinal(a[i].Text, b[i].Text);
                    if (c != 0) return c;
                }
                return a.Count.CompareTo(b.Count);
            }
        }

        /// <summary>'CloudAndTagVisible' -> 'Cloud and Tag'.</summary>
        public static string ShowLabel(string visibilityName)
        {
            string name = (visibilityName ?? "").Trim();
            foreach (var (label, enumName) in ShowChoices)
            {
                if (enumName.ToLowerInvariant() == name.ToLowerInvariant() || label.ToLowerInvariant() == name.ToLowerInvariant())
                    return label;
            }
            return DefaultShow;
        }

        /// <summary>'Cloud and Tag' -> 'CloudAndTagVisible'.</summary>
        public static string ShowName(string label)
        {
            string text = (label ?? "").Trim().ToLowerInvariant();
            foreach (var (choice, enumName) in ShowChoices)
            {
                if (choice.ToLowerInvariant() == text || enumName.ToLowerInvariant() == text)
                    return enumName;
            }
            return "CloudAndTagVisible";
        }

        /// <summary>One revision, as read and as staged.</summary>
        public class Entry
        {
            public string Key;
            public string Uid;
            /// <summary>The extra columns: {column id: value as stored}.</summary>
            public Dictionary<string, string> Custom;
            public Dictionary<string, string> OriginalCustom;
            /// <summary>null for a new revision.</summary>
            public long? ElementKey;
            /// <summary>As read; 0 for a new one.</summary>
            public int Sequence;
            /// <summary>{field: value} - strings, except "issued" which is a bool.</summary>
            public Dictionary<string, object> Fields;
            public Dictionary<string, object> Original;
            /// <summary>Sheet numbers carrying it.</summary>
            public List<string> Sheets;
            /// <summary>The sheet series of those sheets, each once, in natural order.</summary>
            public List<string> Series = new List<string>();
            public int Clouds;
            /// <summary>Its clouds by the view they are drawn in, {view key: [cloud keys]}.</summary>
            public Dictionary<string, List<string>> CloudViews = new Dictionary<string, List<string>>(StringComparer.Ordinal);
            /// <summary>Those views that are on no sheet, [(view key, name, clouds)] - a revision "on 0
            /// sheets" can still have clouds there.</summary>
            public List<(string View, string Name, int Clouds)> OffViews = new List<(string, string, int)>();
            public bool Deleted;
            /// <summary>The key it merges into.</summary>
            public string MergedInto;

            public Entry(object key, long? elementKey = null, int sequence = 0, Dictionary<string, object> fields = null,
                         IEnumerable<string> sheets = null, int clouds = 0, string uid = "",
                         Dictionary<string, string> custom = null)
            {
                Key = S(key);
                Uid = uid ?? "";
                Custom = new Dictionary<string, string>(custom ?? new Dictionary<string, string>(), StringComparer.Ordinal);
                OriginalCustom = elementKey == null ? null : new Dictionary<string, string>(Custom, StringComparer.Ordinal);
                ElementKey = elementKey;
                Sequence = sequence;
                Fields = new Dictionary<string, object>(fields ?? new Dictionary<string, object>(), StringComparer.Ordinal);
                foreach (var field in PsRevisions.Fields)
                {
                    if (!Fields.ContainsKey(field))
                        Fields[field] = field == "issued" ? (object)false : "";
                }
                Original = elementKey == null ? null : new Dictionary<string, object>(Fields, StringComparer.Ordinal);
                Sheets = new List<string>(sheets ?? Enumerable.Empty<string>());
                Clouds = clouds;
            }

            public bool IsNew => ElementKey == null;

            public bool Live => !Deleted && MergedInto == null;

            public int Used => Sheets.Count;

            /// <summary>How many of its clouds are in views placed on no sheet.</summary>
            public int Unplaced => OffViews.Sum(v => v.Clouds);

            public bool OriginallyIssued()
            {
                return Original != null && Original.TryGetValue("issued", out var v) && Truthy(v);
            }

            internal object Field(string field) => Fields.TryGetValue(field, out var v) ? v : null;
        }

        // ==========================================================================
        // pure decisions
        // ==========================================================================

        /// <summary>
        /// <paramref name="keys"/> with every selected one moved <paramref name="step"/> (-1 up, 1 down).
        /// A selected block moves as a block; one already at the end it is moving towards stays put, and
        /// so does the rest of its block behind it - the way a list in Revit or Explorer behaves.
        /// </summary>
        public static List<string> MoveWithin(IEnumerable<string> keys, IEnumerable<string> selected, int step)
        {
            var result = new List<string>(keys);
            var picked = new HashSet<string>(selected ?? Enumerable.Empty<string>(), StringComparer.Ordinal);
            if (step < 0)
            {
                for (int index = 1; index < result.Count; index++)
                {
                    if (picked.Contains(result[index]) && !picked.Contains(result[index - 1]))
                    {
                        var t = result[index - 1];
                        result[index - 1] = result[index];
                        result[index] = t;
                    }
                }
            }
            else if (step > 0)
            {
                for (int index = result.Count - 2; index >= 0; index--)
                {
                    if (picked.Contains(result[index]) && !picked.Contains(result[index + 1]))
                    {
                        var t = result[index + 1];
                        result[index + 1] = result[index];
                        result[index] = t;
                    }
                }
            }
            return result;
        }

        /// <summary>Move among <paramref name="movable"/> keys only; the rest keep their places. Rows
        /// staged for deletion stay where they are, struck through, rather than being shuffled by a move
        /// they have no part in.</summary>
        public static List<string> MoveKeeping(IList<string> order, IEnumerable<string> movable, IEnumerable<string> selected, int step)
        {
            var movableSet = new HashSet<string>(movable, StringComparer.Ordinal);
            var slots = Enumerable.Range(0, order.Count).Where(index => movableSet.Contains(order[index])).ToList();
            var moved = MoveWithin(slots.Select(index => order[index]), selected, step);
            var result = new List<string>(order);
            for (int i = 0; i < Math.Min(slots.Count, moved.Count); i++)
                result[slots[i]] = moved[i];
            return result;
        }

        /// <summary>
        /// <paramref name="order"/> with <paramref name="key"/> put in so that it is
        /// <paramref name="position"/> among the live revisions (1 = first), ahead of whichever live one
        /// held that place. Rows staged to go keep their slot in order but are not counted, which is how
        /// Revit will number them once they are gone. Past the end, or null, is last.
        /// </summary>
        public static List<string> InsertAt(IEnumerable<string> order, IEnumerable<string> live, string key, int? position)
        {
            var orderList = order.Where(one => one != key).ToList();
            var liveList = live.Where(one => one != key).ToList();
            int pos = position ?? liveList.Count + 1;
            if (pos < 1)
                pos = 1;
            if (pos > liveList.Count)
            {
                orderList.Add(key);
                return orderList;
            }
            var aheadOf = liveList[pos - 1];
            int index = orderList.IndexOf(aheadOf);
            if (index < 0)
                throw new InvalidOperationException("list.index(x): x not in list");
            orderList.Insert(index, key);
            return orderList;
        }

        /// <summary>Whether a row's display values pass every column's search. Each search is a
        /// case-insensitive "contains"; an empty one passes everything. All of them have to pass.</summary>
        public static bool Matches(IDictionary<string, string> values, IDictionary<string, string> filters)
        {
            foreach (var pair in filters ?? new Dictionary<string, string>())
            {
                string needle = (pair.Value ?? "").Trim().ToLowerInvariant();
                if (needle.Length == 0)
                    continue;
                string have = values != null && values.TryGetValue(pair.Key, out var v) ? v ?? "" : "";
                if (!have.ToLowerInvariant().Contains(needle))
                    return false;
            }
            return true;
        }

        /// <summary>
        /// Whether a row passes every column's value filter. <paramref name="tokensOf"/>(field) gives the
        /// row's values in that column - one for most columns, one per series for Sheet series.
        /// <paramref name="picks"/> is {field: set of allowed values}, "" standing for a blank cell; a
        /// column with no entry is not filtered. A row passes a column when any of its values is allowed.
        /// <paramref name="skip"/> leaves one column out, for that column's own list (Excel's rule).
        /// </summary>
        public static bool PassesPicks(Func<string, List<string>> tokensOf, IDictionary<string, HashSet<string>> picks, string skip = null)
        {
            foreach (var pair in picks ?? new Dictionary<string, HashSet<string>>())
            {
                if (pair.Key == skip || pair.Value == null)
                    continue;
                var tokens = tokensOf(pair.Key);
                if (tokens == null || tokens.Count == 0)
                    tokens = new List<string> { "" };
                if (!tokens.Any(token => pair.Value.Contains(token)))
                    return false;
            }
            return true;
        }

        /// <summary>The custom-column part of a plan (ps_revisions plan['custom']). Values are keyed
        /// like Plan.Order: an element id as text, or a new revision's "newN" key.</summary>
        public class PlanCustom
        {
            public List<PsRevData.Column> Columns = new List<PsRevData.Column>();
            public Dictionary<string, Dictionary<string, string>> Values =
                new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
        }

        /// <summary>Everything Apply has to do (ps_revisions plan dict). Where the Python mixes element
        /// ids (int) with new keys (u'newN'), the C# uses text: the element id as text, or "newN".</summary>
        public class Plan
        {
            /// <summary>{'numbering': PerProject/PerSheet string, 'arc_mm': double}.</summary>
            public Dictionary<string, object> Settings = new Dictionary<string, object>(StringComparer.Ordinal);
            public List<long> Unissue = new List<long>();
            public List<(string Key, Dictionary<string, object> Fields)> Creates = new List<(string, Dictionary<string, object>)>();
            public List<(long ElementKey, Dictionary<string, object> Edits)> Edits = new List<(long, Dictionary<string, object>)>();
            public List<(long ElementKey, long Into)> Merges = new List<(long, long)>();
            public List<long> Deletes = new List<long>();
            /// <summary>The final order, or null when Revit's natural order is already right.</summary>
            public List<string> Order;
            public List<string> Issue = new List<string>();
            public PlanCustom Custom;
            public bool Push;
        }

        /// <summary>Every change the window has made, none of them written yet.</summary>
        public class Staging
        {
            public Dictionary<string, Entry> Entries;
            public List<PsRevData.Column> Columns;
            public List<PsRevData.Column> OriginalColumns;
            /// <summary>"Push to parameters" pressed: push even with nothing else staged.</summary>
            public bool PushRequested;
            public List<string> Order;
            public List<string> OriginalOrder;
            public List<string> Sequences;
            /// <summary>{'numbering': string, 'arc_mm': double}.</summary>
            public Dictionary<string, object> Settings;
            public Dictionary<string, object> OriginalSettings;
            internal int New;

            public Staging(IEnumerable<Entry> entries, string numbering = PerProject, double arcMm = 0.0,
                           IEnumerable<string> sequences = null, IEnumerable<PsRevData.Column> columns = null)
            {
                var list = entries.ToList();
                Entries = new Dictionary<string, Entry>(StringComparer.Ordinal);
                foreach (var entry in list) Entries[entry.Key] = entry;
                var cols = columns != null ? columns.ToList() : PsRevData.DefaultColumns();
                Columns = cols.Select(c => c.Copy()).ToList();
                OriginalColumns = cols.Select(c => c.Copy()).ToList();
                PushRequested = false;
                Order = list.OrderBy(one => one.Sequence).Select(one => one.Key).ToList();
                OriginalOrder = new List<string>(Order);
                Sequences = new List<string>(sequences ?? Enumerable.Empty<string>());
                Settings = new Dictionary<string, object>(StringComparer.Ordinal) { { "numbering", numbering }, { "arc_mm", arcMm } };
                OriginalSettings = new Dictionary<string, object>(Settings, StringComparer.Ordinal);
                New = 0;
            }

            // -------------------------------------------------------------- reading
            public List<string> LiveOrder()
            {
                return Order.Where(key => Entries[key].Live).ToList();
            }

            public int? StagedSequence(string key)
            {
                var live = LiveOrder();
                int index = live.IndexOf(key);
                return index >= 0 ? index + 1 : (int?)null;
            }

            /// <summary>Issued as staged: Revit will not edit an issued revision.</summary>
            public bool Locked(string key)
            {
                return Truthy(Entries[key].Field("issued"));
            }

            /// <summary>The fields of one row that differ from the model, plus 'seq' and 'x_' + column id.</summary>
            public HashSet<string> Changed(string key)
            {
                var entry = Entries[key];
                if (entry.IsNew)
                {
                    var all = new HashSet<string>(PsRevisions.Fields, StringComparer.Ordinal) { "seq" };
                    foreach (var column in Columns) all.Add("x_" + column.Id);
                    return all;
                }
                var found = new HashSet<string>(PsRevisions.Fields.Where(field =>
                    !Equals(entry.Field(field), entry.Original.TryGetValue(field, out var o) ? o : null)), StringComparer.Ordinal);
                foreach (var column in Columns)
                {
                    if (CustomValue(entry, column) != CustomValue(entry, column, original: true))
                        found.Add("x_" + column.Id);
                }
                var staged = StagedSequence(key);
                if (staged != null && staged != OriginalPosition(key))
                    found.Add("seq");
                return found;
            }

            /// <summary>Where a surviving revision would sit with no move staged.</summary>
            internal int? OriginalPosition(string key)
            {
                var survivors = OriginalOrder.Where(one => Entries[one].Live).ToList();
                int index = survivors.IndexOf(key);
                return index >= 0 ? index + 1 : (int?)null;
            }

            /// <summary>What is staged for a row, in a word: the Sequence cell's tooltip.</summary>
            public string Pending(string key)
            {
                var entry = Entries[key];
                if (entry.MergedInto != null)
                {
                    var target = StagedSequence(entry.MergedInto);
                    return string.Format("Merge into {0}", target.HasValue && target.Value != 0 ? target.Value.ToString(CultureInfo.InvariantCulture) : "?");
                }
                if (entry.Deleted)
                    return "Delete";
                if (entry.IsNew)
                    return "New";
                var changed = Changed(key);
                if (changed.Count == 0)
                    return "";
                if (changed.Count == 1 && changed.Contains("seq"))
                    return "Moved";
                if (!changed.Any(name => !name.StartsWith("x_", StringComparison.Ordinal)))
                    return "Notes";
                return "Edited";
            }

            // ---------------------------------------------------------- extra columns
            public PsRevData.Column Column(string columnId)
            {
                foreach (var column in Columns)
                    if (column.Id == columnId)
                        return column;
                return null;
            }

            /// <summary>A row's value in an extra column, normalised for comparing.</summary>
            public static string CustomValue(Entry entry, PsRevData.Column column, bool original = false)
            {
                var source = original ? entry.OriginalCustom : entry.Custom;
                string value = source != null && source.TryGetValue(column.Id, out var v) ? v : "";
                if (column.Kind == "yesno")
                    return value == "1" ? "1" : "0";
                return value ?? "";
            }

            public bool ColumnsChanged()
            {
                if (Columns.Count != OriginalColumns.Count)
                    return true;
                return !Columns.Zip(OriginalColumns, (one, other) => one.Same(other)).All(same => same);
            }

            /// <summary>(ok, message). Issued revisions take these too: they are the tool's own data, not
            /// Revit's, and notes are written after issue.</summary>
            public (bool Ok, string Message) SetCustom(string key, string columnId, object value)
            {
                Entries.TryGetValue(key ?? "", out var entry);
                var column = Column(columnId);
                if (entry == null || column == null)
                    return (false, "No such column.");
                if (!entry.Live)
                    return (false, "That revision is staged to go - restore it to edit it.");
                var (ok, stored) = PsRevData.Normalise(column, value);
                if (!ok)
                    return (false, stored);
                entry.Custom[column.Id] = stored;
                return (true, "");
            }

            /// <summary>
            /// One value into several revisions: (changed keys, refusals). Each is set on its own, so an
            /// issued one refuses for itself and the rest still take it. Never the Date: a date belongs
            /// to one issue, and the same date on several revisions is a slip, not an edit.
            /// </summary>
            public (List<string> Changed, List<string> Refusals) SetFieldMany(IEnumerable<string> keys, string field, object value)
            {
                if (AllAtOnceRefused.Contains(field))
                    return (new List<string>(), new List<string> { string.Format("The {0} is set one revision at a time.", field) });
                var changed = new List<string>();
                var refusals = new List<string>();
                foreach (var key in keys)
                {
                    var (ok, message) = SetField(key, field, value);
                    if (ok)
                        changed.Add(key);
                    else if (!refusals.Contains(message))
                        refusals.Add(message);
                }
                return (changed, refusals);
            }

            /// <summary>
            /// Everything from the Edit revision window, staged in the order Revit will take it: an Issued
            /// tick coming off goes first, so the rest can change; one going on goes last, after them.
            /// Returns the refusals - empty when all of it went in.
            /// </summary>
            public List<string> Edit(string key, Dictionary<string, object> fields, Dictionary<string, string> custom = null)
            {
                if (key == null || !Entries.TryGetValue(key, out var entry))
                    return new List<string> { "That revision is no longer in the project." };
                var refusals = new List<string>();
                fields = fields ?? new Dictionary<string, object>();
                bool hasWanted = fields.TryGetValue("issued", out var wantedObj) && wantedObj != null;
                bool wanted = hasWanted && Truthy(wantedObj);
                bool was = Truthy(entry.Field("issued"));
                if (hasWanted && was && !wanted)
                    SetField(key, "issued", false);
                foreach (var pair in fields)
                {
                    if (pair.Key == "issued")
                        continue;
                    if (Or(entry.Field(pair.Key)) == Or(pair.Value))
                        continue;
                    var (ok, message) = SetField(key, pair.Key, pair.Value);
                    if (!ok && !refusals.Contains(message))
                        refusals.Add(message);
                }
                foreach (var pair in custom ?? new Dictionary<string, string>())
                {
                    var (ok, message) = SetCustom(key, pair.Key, pair.Value);
                    if (!ok && !refusals.Contains(message))
                        refusals.Add(message);
                }
                if (hasWanted && !was && wanted)
                    SetField(key, "issued", true);
                return refusals;
            }

            /// <summary>SetFieldMany for the manager's own columns.</summary>
            public (List<string> Changed, List<string> Refusals) SetCustomMany(IEnumerable<string> keys, string columnId, object value)
            {
                var changed = new List<string>();
                var refusals = new List<string>();
                foreach (var key in keys)
                {
                    var (ok, message) = SetCustom(key, columnId, value);
                    if (ok)
                        changed.Add(key);
                    else if (!refusals.Contains(message))
                        refusals.Add(message);
                }
                return (changed, refusals);
            }

            /// <summary>(ok, the new column's id, or why not). An Issued To or Method column is Yes/No
            /// whatever <paramref name="kind"/> says.</summary>
            public (bool Ok, string Found) AddColumn(string name, string kind, IEnumerable<string> choices = null, string target = "",
                                                    string parameter = "", string group = "")
            {
                if (group == PsRevData.IssuedTo || group == PsRevData.Method)
                {
                    kind = "yesno";
                    choices = new List<string>();
                }
                var problem = PsRevData.ColumnProblem(name, kind, choices, Columns);
                if (!string.IsNullOrEmpty(problem))
                    return (false, problem);
                if (group == PsRevData.Status && PsRevData.StatusColumn(Columns) != null)
                    return (false, "There is already an Issue Status column.");
                var column = new PsRevData.Column(PsRevData.NewColumnId(Columns), name, kind, choices, target, parameter, group);
                Columns.Add(column);
                return (true, column.Id);
            }

            /// <summary>Rename, re-choose, re-map - and, for a Yes/No column, move it between the Issued
            /// To and Method groups (<paramref name="group"/> null keeps it).</summary>
            public (bool Ok, string Message) UpdateColumn(string columnId, string name, IEnumerable<string> choices = null,
                                                          string target = "", string parameter = "", string group = null)
            {
                var column = Column(columnId);
                if (column == null)
                    return (false, "No such column.");
                if (group != null && group != column.Group)
                {
                    var movable = new[] { PsRevData.IssuedTo, PsRevData.Method, "" };
                    if (column.Kind != "yesno" || !movable.Contains(group) || column.Group == PsRevData.Status)
                        return (false, "Only a Yes/No column can join Issued To or Method.");
                    column.Group = group;
                }
                var choiceList = (choices ?? Enumerable.Empty<string>()).ToList();
                var problem = PsRevData.ColumnProblem(name, column.Kind, choiceList, Columns, columnId);
                if (!string.IsNullOrEmpty(problem))
                    return (false, problem);
                column.Name = (name ?? "").Trim();
                column.Choices = choiceList.Select(one => S(one).Trim()).Where(one => one.Length > 0).ToList();
                column.Target = target != null && PsRevData.TargetLabels.ContainsKey(target) ? target : "";
                column.Parameter = (parameter ?? "").Trim();
                return (true, "");
            }

            /// <summary>
            /// Stage each revision's Issue Status from its sheets, where it has none stored:
            /// <paramref name="statuses"/> is {revision key: status text}. Returns the keys filled. The
            /// value is then kept with the revision, so an old issue keeps its status when the sheets move on.
            /// </summary>
            public List<string> FillStatuses(IDictionary<string, string> statuses)
            {
                var column = PsRevData.StatusColumn(Columns);
                if (column == null)
                    return new List<string>();
                var filled = new List<string>();
                foreach (var key in Order)
                {
                    var entry = Entries[key];
                    string wanted = (statuses.TryGetValue(key, out var s) ? s ?? "" : "").Trim();
                    if (wanted.Length == 0 || !entry.Live || CustomValue(entry, column).Length > 0)
                        continue;
                    entry.Custom[column.Id] = wanted;
                    filled.Add(key);
                }
                return filled;
            }

            public bool RemoveColumn(string columnId)
            {
                int before = Columns.Count;
                Columns = Columns.Where(column => column.Id != columnId).ToList();
                return Columns.Count != before;
            }

            public bool CustomChanged()
            {
                foreach (var key in Order)
                {
                    var entry = Entries[key];
                    if (!entry.Live)
                        continue;
                    if (entry.IsNew && entry.Custom.Values.Any(value => value != "" && value != "0"))
                        return true;
                    if (!entry.IsNew && Changed(key).Any(name => name.StartsWith("x_", StringComparison.Ordinal)))
                        return true;
                }
                return ColumnsChanged();
            }

            public HashSet<string> SettingsChanged()
            {
                return new HashSet<string>(Settings.Keys.Where(name =>
                    !Equals(Settings[name], OriginalSettings.TryGetValue(name, out var o) ? o : null)), StringComparer.Ordinal);
            }

            public int ChangeCount()
            {
                int count = SettingsChanged().Count;
                if (ColumnsChanged())
                    count += 1;
                if (PushRequested)
                    count += 1;
                foreach (var key in Order)
                {
                    var entry = Entries[key];
                    if (entry.IsNew || !entry.Live || Changed(key).Count > 0)
                        count += 1;
                }
                return count;
            }

            public bool Dirty()
            {
                return ChangeCount() > 0;
            }

            /// <summary>What each column shows for a row, as text - what the searches match against.</summary>
            public Dictionary<string, string> Values(string key)
            {
                var entry = Entries[key];
                var staged = StagedSequence(key);
                var values = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var pair in entry.Fields)
                    values[pair.Key] = S(pair.Value);
                values["issued"] = Truthy(entry.Field("issued")) ? "Yes" : "No";
                values["seq"] = staged.HasValue && staged.Value != 0 ? staged.Value.ToString(CultureInfo.InvariantCulture) : "";
                values["used"] = entry.Used.ToString(CultureInfo.InvariantCulture);
                values["series"] = string.Join(", ", entry.Series);
                values["pending"] = Pending(key);
                foreach (var column in Columns)
                    values["x_" + column.Id] = PsRevData.Shown(column, CustomValue(entry, column));
                return values;
            }

            /// <summary>A row's values in one column, as its filter list sees them: every series on its
            /// own for Sheet series, "" for a blank cell.</summary>
            public List<string> Tokens(string key, string field, Dictionary<string, string> values = null)
            {
                if (field == "series")
                {
                    var series = Entries[key].Series.Select(name => (name ?? "").Trim()).Where(name => name.Length > 0).ToList();
                    return series.Count > 0 ? series : new List<string> { "" };
                }
                if (values == null)
                    values = Values(key);
                return new List<string> { (values.TryGetValue(field, out var v) ? v ?? "" : "").Trim() };
            }

            /// <summary>
            /// The rows every search and every value filter lets through - and, given a sheet number,
            /// only the revisions on that sheet. A revision added here and not yet applied is on no sheet,
            /// but stays: hiding the row just made would read as losing it.
            /// </summary>
            public List<string> Visible(IDictionary<string, string> filters, IDictionary<string, HashSet<string>> picks = null,
                                        string onSheet = null)
            {
                var found = new List<string>();
                foreach (var key in Order)
                {
                    if (onSheet != null)
                    {
                        var entry = Entries[key];
                        if (!entry.IsNew && !entry.Sheets.Contains(onSheet))
                            continue;
                    }
                    var values = Values(key);
                    if (!Matches(values, filters))
                        continue;
                    if (picks != null && picks.Count > 0 && !PassesPicks(field => Tokens(key, field, values), picks))
                        continue;
                    found.Add(key);
                }
                return found;
            }

            /// <summary>
            /// What one column's filter list offers: every value in the rows the searches and the OTHER
            /// columns' filters leave, each once, in natural order, "(Blanks)" last. Its own filter is left
            /// out, or the values it hides would not be there to tick back on.
            /// </summary>
            public List<string> Choices(string field, IDictionary<string, string> filters = null,
                                        IDictionary<string, HashSet<string>> picks = null)
            {
                var found = new List<string>();
                foreach (var key in Order)
                {
                    var values = Values(key);
                    if (!Matches(values, filters))
                        continue;
                    if (!PassesPicks(name => Tokens(key, name, values), picks, skip: field))
                        continue;
                    found.AddRange(Tokens(key, field, values));
                }
                return PsRegister.FilterChoices(found).ToList();
            }

            // -------------------------------------------------------------- staging
            /// <summary>(ok, message). Refused where Revit would refuse it.</summary>
            public (bool Ok, string Message) SetField(string key, string field, object value)
            {
                if (key == null || !Entries.TryGetValue(key, out var entry) || !PsRevisions.Fields.Contains(field))
                    return (false, "No such field.");
                if (!entry.Live)
                    return (false, "That revision is staged to go - restore it to edit it.");
                if (field != "issued" && Locked(key))
                    return (false, string.Format("Revision {0} is issued, so Revit keeps it as it is. Untick Issued to edit it.",
                                                 StagedSequence(key)?.ToString(CultureInfo.InvariantCulture) ?? "None"));
                object stored;
                if (field == "issued")
                    stored = Truthy(value);
                else if (field == "show")
                    stored = ShowLabel(S(value));
                else
                    stored = S(value);
                entry.Fields[field] = stored;
                return (true, "");
            }

            public bool SetSetting(string name, object value)
            {
                object stored;
                if (name == "arc_mm")
                {
                    double number;
                    if (value is double d) number = d;
                    else if (value is int i) number = i;
                    else if (value is long l) number = l;
                    else if (value is float f) number = f;
                    else if (!double.TryParse(S(value).Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out number))
                        return false;
                    if (number <= 0)
                        return false;
                    stored = number;
                }
                else if (name == "numbering")
                {
                    stored = S(value) == PerSheet ? PerSheet : PerProject;
                }
                else
                {
                    return false;
                }
                Settings[name] = stored;
                return true;
            }

            /// <summary>
            /// A new revision; returns its key. <paramref name="position"/> is the sequence it is to have,
            /// 1 being the top: it goes in there and the revision that had that sequence, and every one
            /// after it, moves down a slot. null, or past the end, puts it last. <paramref name="fields"/>
            /// and <paramref name="custom"/> fill it in; anything not given is as Revit would start it -
            /// numbered like the last revision, shown with clouds and tags, not issued.
            /// </summary>
            public string Add(int? position = null, Dictionary<string, object> fields = null, Dictionary<string, string> custom = null)
            {
                New += 1;
                string key = "new" + New.ToString(CultureInfo.InvariantCulture);
                var live = LiveOrder();
                object numbering = live.Count > 0
                    ? Entries[live[live.Count - 1]].Field("numbering")
                    : (Sequences.Count > 0 ? Sequences[0] : "");
                var start = new Dictionary<string, object>(StringComparer.Ordinal)
                {
                    { "numbering", Or(numbering) }, { "show", DefaultShow }, { "issued", false },
                };
                foreach (var pair in fields ?? new Dictionary<string, object>())
                {
                    if (pair.Key == "issued")
                        start[pair.Key] = Truthy(pair.Value);
                    else if (pair.Key == "show")
                        start[pair.Key] = ShowLabel(S(pair.Value));
                    else if (PsRevisions.Fields.Contains(pair.Key))
                        start[pair.Key] = S(pair.Value);
                }
                var entry = new Entry(key, null, 0, start, custom: new Dictionary<string, string>(custom ?? new Dictionary<string, string>()));
                Entries[key] = entry;
                Order = InsertAt(Order, live, key, position);
                return key;
            }

            /// <summary>[(sequence, description, sheets, clouds, unplaced)] for the used ones.</summary>
            public List<(int? Sequence, string Description, int Sheets, int Clouds, int Unplaced)> InUse(IEnumerable<string> keys)
            {
                var found = new List<(int?, string, int, int, int)>();
                foreach (var key in keys)
                {
                    if (key == null || !Entries.TryGetValue(key, out var entry) || entry.IsNew || !entry.Live)
                        continue;
                    if (entry.Used > 0 || entry.Clouds > 0)
                        found.Add((StagedSequence(key), Or(entry.Field("desc")), entry.Used, entry.Clouds, entry.Unplaced));
                }
                return found;
            }

            /// <summary>
            /// Stage deletes, or restore rows already staged. (ok, message). Every selected row already
            /// staged is restored; otherwise they are all staged to go. A new row is simply dropped. Revit
            /// needs at least one revision in a project, so the last live one is refused.
            /// </summary>
            public (bool Ok, string Message) Delete(IEnumerable<string> keys)
            {
                var list = keys.Where(key => key != null && Entries.ContainsKey(key)).ToList();
                if (list.Count == 0)
                    return (false, "Select a revision first.");
                if (list.All(key => !Entries[key].Live))
                {
                    foreach (var key in list)
                    {
                        Entries[key].Deleted = false;
                        Entries[key].MergedInto = null;
                    }
                    return (true, string.Format("{0} revision{1} restored.", list.Count, list.Count == 1 ? "" : "s"));
                }
                var going = list.Where(key => Entries[key].Live).ToList();
                if (LiveOrder().Count(key => !going.Contains(key)) < 1)
                    return (false, "A project has to keep at least one revision, so the last one cannot go.");
                foreach (var key in going)
                {
                    if (Entries[key].IsNew)
                    {
                        Order.Remove(key);
                        Entries.Remove(key);
                    }
                    else
                    {
                        Entries[key].Deleted = true;
                    }
                }
                return (true, string.Format("{0} revision{1} staged to delete.", going.Count, going.Count == 1 ? "" : "s"));
            }

            public bool Move(IEnumerable<string> keys, int step)
            {
                var movable = LiveOrder();
                var selected = keys.Where(key => movable.Contains(key)).ToList();
                if (selected.Count == 0)
                    return false;
                var before = new List<string>(Order);
                Order = MoveKeeping(Order, movable, selected, step);
                return !Order.SequenceEqual(before);
            }

            /// <summary>
            /// Stage merging one revision into its neighbour. (ok, message). As in Revit: only two
            /// revisions that are both unissued, and here only ones already in the model - a new one has
            /// nothing to merge yet. The merged one goes; its clouds move to the other.
            /// </summary>
            public (bool Ok, string Message) Merge(string key, int step)
            {
                if (key == null || !Entries.TryGetValue(key, out var entry) || !entry.Live)
                    return (false, "Select one revision that is not already going.");
                var live = LiveOrder();
                int index = live.IndexOf(key) + step;
                if (index < 0 || index >= live.Count)
                    return (false, string.Format("There is no revision {0} it to merge into.", step < 0 ? "above" : "below"));
                var target = Entries[live[index]];
                if (entry.IsNew || target.IsNew)
                    return (false, "A new revision has to be applied before it can be merged.");
                foreach (var one in new[] { entry, target })
                {
                    if (Truthy(one.Field("issued")) || one.OriginallyIssued())
                        return (false, string.Format("Revision {0} is issued, and Revit only merges unissued revisions.",
                                                     StagedSequence(one.Key)?.ToString(CultureInfo.InvariantCulture) ?? "None"));
                }
                entry.MergedInto = target.Key;
                var staged = StagedSequence(key);
                return (true, string.Format("Revision {0} staged to merge into {1}.",
                                            staged.HasValue && staged.Value != 0 ? staged.Value : live.IndexOf(key) + 1, index + 1));
            }

            // ----------------------------------------------------------------- plan
            /// <summary>Everything Apply has to do, in the order it has to be done.</summary>
            public PsRevisions.Plan Plan()
            {
                var plan = new PsRevisions.Plan();
                foreach (var name in SettingsChanged())
                    plan.Settings[name] = Settings[name];

                foreach (var key in Order)
                {
                    var entry = Entries[key];
                    if (entry.IsNew)
                    {
                        if (!entry.Live)
                            continue;
                        var fields = new Dictionary<string, object>(StringComparer.Ordinal);
                        foreach (var field in PsRevisions.Fields)
                            if (field != "issued")
                                fields[field] = entry.Field(field);
                        plan.Creates.Add((key, fields));
                        if (Truthy(entry.Field("issued")))
                            plan.Issue.Add(key);
                        continue;
                    }
                    if (entry.MergedInto != null)
                    {
                        plan.Merges.Add((entry.ElementKey.Value, Entries[entry.MergedInto].ElementKey.Value));
                        continue;
                    }
                    if (entry.Deleted)
                    {
                        plan.Deletes.Add(entry.ElementKey.Value);
                        continue;
                    }
                    bool was = entry.OriginallyIssued();
                    bool now = Truthy(entry.Field("issued"));
                    if (was && !now)
                        plan.Unissue.Add(entry.ElementKey.Value);
                    var edits = new Dictionary<string, object>(StringComparer.Ordinal);
                    foreach (var field in PsRevisions.Fields)
                    {
                        if (field != "issued" && !Equals(entry.Field(field), entry.Original.TryGetValue(field, out var o) ? o : null))
                            edits[field] = entry.Field(field);
                    }
                    if (edits.Count > 0)
                        plan.Edits.Add((entry.ElementKey.Value, edits));
                    if (now && !was)
                        plan.Issue.Add(entry.ElementKey.Value.ToString(CultureInfo.InvariantCulture));
                }

                // The order Revit would end up in with no reorder: the survivors in their old order, then
                // the new ones as they were created.
                var live = LiveOrder();
                var natural = OriginalOrder.Where(key => live.Contains(key))
                    .Concat(live.Where(key => Entries[key].IsNew)).ToList();
                if (!live.SequenceEqual(natural))
                {
                    plan.Order = live.Select(key => Entries[key].IsNew
                        ? key : Entries[key].ElementKey.Value.ToString(CultureInfo.InvariantCulture)).ToList();
                }

                // The extra columns: stored whenever they changed, and pushed into their parameters on
                // every Apply while any column is mapped - a sheet whose current revision moved on takes
                // the new value even when no note was touched.
                bool pushed = Columns.Any(column => column.Pushed);
                bool others = !PlanIsEmpty(plan);
                bool customChanged = CustomChanged();
                plan.Push = pushed && (PushRequested || others || customChanged);
                if (customChanged || plan.Push)
                {
                    var ids = new HashSet<string>(Columns.Select(column => column.Id), StringComparer.Ordinal);
                    var values = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
                    foreach (var key in live)
                    {
                        var entry = Entries[key];
                        var row = new Dictionary<string, string>(StringComparer.Ordinal);
                        foreach (var pair in entry.Custom)
                            if (ids.Contains(pair.Key))
                                row[pair.Key] = pair.Value;
                        values[entry.IsNew ? key : entry.ElementKey.Value.ToString(CultureInfo.InvariantCulture)] = row;
                    }
                    plan.Custom = new PlanCustom
                    {
                        Columns = Columns.Select(column => column.Copy()).ToList(),
                        Values = values,
                    };
                }
                return plan;
            }
        }

        public static bool PlanIsEmpty(Plan plan)
        {
            return !(plan.Settings.Count > 0 || plan.Unissue.Count > 0 || plan.Creates.Count > 0 ||
                     plan.Edits.Count > 0 || plan.Merges.Count > 0 || plan.Deletes.Count > 0 ||
                     (plan.Order != null && plan.Order.Count > 0) || plan.Issue.Count > 0 ||
                     plan.Custom != null || plan.Push);
        }

        /// <summary>An element key from Plan text: the element id, or null for a "newN" key.</summary>
        private static long? ElementKeyOf(string key, Dictionary<string, long> made)
        {
            if (key != null && made.TryGetValue(key, out var id))
                return id;
            if (long.TryParse(key, NumberStyles.Integer, CultureInfo.InvariantCulture, out var number))
                return number;
            return null;
        }

        /// <summary>
        /// Write a plan through <paramref name="api"/>. (done, errors). <c>done</c> counts steps that went in.
        /// </summary>
        public static (int Done, List<string> Errors) Execute(RevitApi api, Plan plan)
        {
            int done = 0;
            var errors = new List<string>();

            bool Attempt(string label, Action action)
            {
                try
                {
                    action();
                    return true;
                }
                catch (Exception err)
                {
                    errors.Add(string.Format("{0}: {1}", label, err.Message));
                    return false;
                }
            }

            foreach (var pair in plan.Settings.OrderBy(p => p.Key, StringComparer.Ordinal))
            {
                if (Attempt(string.Format("Setting {0}", pair.Key), () => api.SetSetting(pair.Key, pair.Value)))
                    done += 1;
            }

            foreach (var elementKey in plan.Unissue)
            {
                if (Attempt(string.Format("Un-issuing {0}", api.Label(elementKey)), () => api.SetField(elementKey, "issued", false)))
                    done += 1;
            }

            var made = new Dictionary<string, long>(StringComparer.Ordinal);
            foreach (var (key, fields) in plan.Creates)
            {
                try
                {
                    made[key] = api.Create();
                }
                catch (Exception err)
                {
                    errors.Add(string.Format("Adding a revision: {0}", err.Message));
                    continue;
                }
                done += 1;
                foreach (var field in Fields)
                {
                    if (fields.TryGetValue(field, out var value) && value != null && !(value is string s && s.Length == 0))
                    {
                        long id = made[key];
                        Attempt(string.Format("New revision {0}", field), () => api.SetField(id, field, value));
                    }
                }
            }

            foreach (var (elementKey, edits) in plan.Edits)
            {
                bool ok = true;
                foreach (var field in Fields)
                {
                    if (edits.TryGetValue(field, out var value))
                        ok = Attempt(string.Format("Revision {0} {1}", api.Label(elementKey), field),
                                     () => api.SetField(elementKey, field, value)) && ok;
                }
                if (ok)
                    done += 1;
            }

            foreach (var (elementKey, into) in plan.Merges)
            {
                // Revit merges a revision into its neighbour only, so it is moved to sit straight after
                // the one it merges into, then combined with the one before it.
                void MergeOne()
                {
                    var order = api.Ids().Where(one => one != elementKey).ToList();
                    int at = order.IndexOf(into);
                    if (at < 0)
                        throw new InvalidOperationException("list.index(x): x not in list");
                    order.Insert(at + 1, elementKey);
                    api.Reorder(order);
                    api.CombineWithPrevious(elementKey);
                }
                if (Attempt(string.Format("Merging revision {0}", api.Label(elementKey)), MergeOne))
                    done += 1;
            }

            foreach (var elementKey in plan.Deletes)
            {
                if (Attempt(string.Format("Deleting revision {0}", api.Label(elementKey)), () => api.Delete(elementKey)))
                    done += 1;
            }

            if (plan.Order != null && plan.Order.Count > 0)
            {
                var wanted = plan.Order.Select(one => ElementKeyOf(one, made)).Where(one => one.HasValue).Select(one => one.Value).ToList();
                var present = api.Ids();
                // Anything in the model the plan does not know about keeps its place at the end rather
                // than making Revit refuse the whole list.
                var final = wanted.Where(one => present.Contains(one)).Concat(present.Where(one => !wanted.Contains(one))).ToList();
                if (!final.SequenceEqual(present) && Attempt("Reordering", () => api.Reorder(final)))
                    done += 1;
            }

            foreach (var one in plan.Issue)
            {
                var elementKey = ElementKeyOf(one, made);
                if (!elementKey.HasValue)
                    continue;
                long id = elementKey.Value;
                if (Attempt(string.Format("Issuing {0}", api.Label(id)), () => api.SetField(id, "issued", true)))
                    done += 1;
            }

            var custom = plan.Custom;
            if (custom != null)
            {
                var values = new Dictionary<long, Dictionary<string, string>>();
                foreach (var pair in custom.Values)
                {
                    var elementKey = ElementKeyOf(pair.Key, made);
                    if (elementKey.HasValue)
                        values[elementKey.Value] = pair.Value;
                }
                if (Attempt("Storing the extra columns", () => api.WriteCustom(custom.Columns, values)))
                    done += 1;
                if (plan.Push)
                {
                    try
                    {
                        var (pushed, problems) = api.Push(custom.Columns, values);
                        if (pushed > 0)
                            done += 1;
                        errors.AddRange(problems);
                    }
                    catch (Exception err)
                    {
                        errors.Add(string.Format("Pushing to parameters: {0}", err.Message));
                    }
                }
            }
            return (done, errors);
        }
    }
}
