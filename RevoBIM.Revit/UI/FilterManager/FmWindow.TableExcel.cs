using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using Autodesk.Revit.DB;
using RevoBIM.Tools.FilterManager;
using ComboBox = System.Windows.Controls.ComboBox;
using TextBox = System.Windows.Controls.TextBox;
using Panel = System.Windows.Controls.Panel;
using Visibility = System.Windows.Visibility;

using Grid = System.Windows.Controls.Grid;

namespace RevoBIM.UI.FilterManager
{
    // =======================================================================
    //  TAB 2 - FILTER MANAGER TABLE: the Excel round trip   (script.py 3423-3904)
    // =======================================================================
    public partial class FmWindow
    {
        private static readonly string[] XlsHeaders =
            { "Id", "Filter Name", "Categories", "Elements must match", "Parameter", "Operator", "Value" };
        private static readonly double[] XlsWidths = { 10, 38, 30, 20, 34, 28, 26 };

        /// <summary>
        /// The table laid out for a sheet, grouped exactly as on screen. The id is the key on the way back in,
        /// so a filter can be renamed in Excel and still be matched to the right element.
        /// </summary>
        private List<List<string>> TableToRows()
        {
            var rows = new List<List<string>> { new List<string>(XlsHeaders) };
            foreach (FmBlock block in ExportableBlocks())
            {
                Hydrate(block);
                List<ElementId> cats = block.Cats;
                List<FmRule> rules = block.Rules;
                int depth = Math.Max(1, Math.Max(cats.Count, rules.Count));
                for (int line = 0; line < depth; line++)
                {
                    var row = new List<string> { "", "", "", "", "", "", "" };
                    if (line == 0)
                    {
                        row[0] = FmCore.EidValue(block.Pfe.Id).ToString();
                        row[1] = block.Name;
                        row[3] = block.Match;
                    }
                    if (line < cats.Count) row[2] = FmFilters.CategoryName(Doc, cats[line]) ?? "";
                    if (line < rules.Count)
                    {
                        FmRule rule = rules[line];
                        row[4] = rule.ParamId != null ? FmFilters.ParameterName(Doc, rule.ParamId) : "";
                        row[5] = FmFilters.LabelOf(rule.Op);
                        row[6] = RuleValueText(rule);
                    }
                    rows.Add(row);
                }
            }
            return rows;
        }

        /// <summary>
        /// What the sheet covers: whatever the table is currently showing. Exporting the whole project when
        /// the list has been narrowed to six filters is not what the search was for.
        /// </summary>
        private List<FmBlock> ExportableBlocks()
        {
            return tableVisible.Count > 0 ? tableVisible : tableBlocks;
        }

        /// <summary>A rule's value as it should read on screen and in a sheet.</summary>
        private string RuleValueText(FmRule rule)
        {
            if (!FmFilters.NeedsValue(rule.Op)) return "";
            object value = rule.Value;
            var id = value as ElementId;
            if (id != null) return FmFilters.ElementName(Doc, id, FmCore.EidValue(id).ToString());
            return value == null ? "" : PyText(value);
        }

        /// <summary>
        /// Whether two values mean the same thing. Compared as numbers where both are numbers, so 100 and
        /// 100.0 and 100.000000 are one value rather than three - the difference that had an import
        /// reporting changes nobody made.
        /// </summary>
        private bool SameValue(FmRule left, FmRule right)
        {
            string a = RuleValueText(left).Trim();
            string b = RuleValueText(right).Trim();
            if (a == b) return true;
            double x, y;
            if (double.TryParse(a, NumberStyles.Float, CultureInfo.InvariantCulture, out x) &&
                double.TryParse(b, NumberStyles.Float, CultureInfo.InvariantCulture, out y))
                return Math.Abs(x - y) < 0.000001;
            return false;
        }

        //  Id | Name | Categories | Match | Parameter | Operator | Value
        private static readonly int[] XlsColumnStyle =
        {
            FmXlsx.StyleLocked,     // the key the import matches on
            FmXlsx.StyleEditable,   // the filter's own cells
            FmXlsx.StyleCategory,
            FmXlsx.StyleEditable,
            FmXlsx.StyleRule,       // the rule cells, kept visually apart
            FmXlsx.StyleRule,
            FmXlsx.StyleRule,
        };

        /// <summary>
        /// Which cells may be edited, and what each one is. Three editable colours rather than one: the
        /// filter's own cells, its categories, and its rules. A rule row reads as a rule at a glance instead
        /// of as more of the filter above it.
        /// </summary>
        private List<List<int>> TableStyles(List<List<string>> rows)
        {
            var styles = new List<List<int>> { Enumerable.Repeat(FmXlsx.StyleHeader, XlsHeaders.Length).ToList() };
            for (int i = 1; i < rows.Count; i++) styles.Add(new List<int>(XlsColumnStyle));
            return styles;
        }

        /// <summary>The values each editable column will take, for the dropdowns.</summary>
        private Tuple<List<List<string>>, int> ListsSheet()
        {
            var categories = allCategories.Select(c => c.Item2).OrderBy(n => n, StringComparer.Ordinal).ToList();
            var operators = FmFilters.Operators.Select(o => o.Label).ToList();

            var found = new HashSet<string>();
            foreach (FmBlock block in ExportableBlocks())
            {
                Hydrate(block);
                foreach (var p in FmFilters.CommonParameters(Doc, block.Cats)) found.Add(p.Item2);
            }
            var parameters = found.OrderBy(n => n, StringComparer.Ordinal).ToList();

            int depth = Math.Max(Math.Max(categories.Count, operators.Count), Math.Max(parameters.Count, 2));
            var rows = new List<List<string>>
            {
                new List<string> { "Categories", "Operators", "Elements must match", "Parameters used by the filters in this sheet" },
            };
            string[] matches = { "AND", "OR" };
            for (int index = 0; index < depth; index++)
            {
                rows.Add(new List<string>
                {
                    index < categories.Count ? categories[index] : "",
                    index < operators.Count ? operators[index] : "",
                    index < 2 ? matches[index] : "",
                    index < parameters.Count ? parameters[index] : "",
                });
            }
            return Tuple.Create(rows, depth);
        }

        /// <summary>
        /// A dark-themed key, on its own tab, explaining the colours. Each colour is shown as a filled swatch
        /// beside what it means, in the same colours the Filters tab uses, so the sheet explains itself
        /// without anyone having to remember.
        /// </summary>
        private Tuple<List<List<string>>, List<List<int>>> GuideSheet()
        {
            int D = FmXlsx.StyleDark;
            int T = FmXlsx.StyleDarkTitle;

            var entries = new List<Tuple<int, string, string>>
            {
                Tuple.Create(FmXlsx.StyleLocked, "Id",
                    "The Revit element id. This is how Import finds the filter again, so a name can be changed and still be " +
                    "matched. Do not edit this column, and do not delete its row."),
                Tuple.Create(FmXlsx.StyleEditable, "The filter",
                    "Its name, and whether an element has to match ALL of the rules or ANY of them. Only the first row of " +
                    "each filter carries these."),
                Tuple.Create(FmXlsx.StyleCategory, "Categories",
                    "One per row, by name. Add a row under the last one to add a category; clear a cell to drop it. Pick " +
                    "from the dropdown - the names have to match Revit's exactly."),
                Tuple.Create(FmXlsx.StyleRule, "Rules",
                    "Parameter, operator and value, one rule per row. Add a row to add a rule. The operator has to be one " +
                    "the parameter suits, which is what the dropdown offers."),
            };

            var rows = new List<List<string>> { new List<string> { "RevoBIM Filter Manager", "How to use this workbook" }, new List<string> { "", "" } };
            var styles = new List<List<int>> { new List<int> { T, T }, new List<int> { D, D } };

            rows.Add(new List<string> { "Colour", "What it is" });
            styles.Add(new List<int> { T, T });
            foreach (var entry in entries)
            {
                rows.Add(new List<string> { "", entry.Item2 + " - " + entry.Item3 });
                styles.Add(new List<int> { entry.Item1, D });
                rows.Add(new List<string> { "", "" });
                styles.Add(new List<int> { D, D });
            }

            string[] notes =
            {
                "How it works",
                "1. Export writes whatever the table is showing, so narrow it first if you only want some of the filters.",
                "2. Edit the coloured cells here. The dropdowns on the Lists tab show what each column will take.",
                "3. Import reads the sheet back into the tool and highlights everything it changed. Nothing touches the model yet.",
                "4. Check the highlighted cells, then press Apply Table. That is the step that writes to Revit.",
                "",
                "Anything that cannot be matched - a category that does not exist, a parameter the categories do not share, " +
                "an id that has gone - is listed in a log rather than applied quietly.",
            };
            for (int index = 0; index < notes.Length; index++)
            {
                rows.Add(new List<string> { notes[index], "" });
                styles.Add(new List<int> { index == 0 ? T : D, D });
            }

            return Tuple.Create(rows, styles);
        }

        /// <summary>One button, then a choice - export or import.</summary>
        public void OnExcelMenu(object sender, RoutedEventArgs args)
        {
            var button = sender as Button;
            ContextMenu menu = button == null ? null : button.ContextMenu;
            if (menu == null) return;
            menu.PlacementTarget = button;
            menu.Placement = PlacementMode.Bottom;
            menu.IsOpen = true;
        }

        public void OnExportExcel(object sender, RoutedEventArgs args)
        {
            List<FmBlock> blocks = ExportableBlocks();
            if (blocks.Count == 0)
            {
                txtStatus.Text = "There is nothing in the table to export.";
                return;
            }
            bool narrowed = blocks.Count < tableBlocks.Count;
            var dialog = new Microsoft.Win32.SaveFileDialog
            {
                Filter = "Excel workbook (*.xlsx)|*.xlsx",
                FileName = "RevoBIM filters.xlsx",
                Title = "Export the filter table",
            };
            if (dialog.ShowDialog(Win) != true) return;

            List<List<string>> rows = TableToRows();
            var lists = ListsSheet();
            int depth = lists.Item2;
            int last = rows.Count + 200;        // room for rows added by hand

            var guide = GuideSheet();
            var sheets = new List<FmSheet>
            {
                new FmSheet
                {
                    Name = "Filters",
                    Rows = rows,
                    Widths = XlsWidths,
                    Styles = TableStyles(rows),
                    Validations = new List<Tuple<string, string>>
                    {
                        Tuple.Create("C2:C" + last, "Lists!$A$2:$A$" + (depth + 1)),
                        Tuple.Create("D2:D" + last, "Lists!$C$2:$C$3"),
                        Tuple.Create("E2:E" + last, "Lists!$D$2:$D$" + (depth + 1)),
                        Tuple.Create("F2:F" + last, "Lists!$B$2:$B$" + (depth + 1)),
                    },
                },
                new FmSheet
                {
                    Name = "Guide",
                    Rows = guide.Item1,
                    Styles = guide.Item2,
                    Widths = new double[] { 16, 104 },
                    HeaderRows = 0,
                    Freeze = false,
                },
                new FmSheet
                {
                    Name = "Lists",
                    Rows = lists.Item1,
                    Widths = new double[] { 34, 30, 22, 40 },
                },
            };

            try { FmXlsx.WriteWorkbook(dialog.FileName, sheets); }
            catch (Exception ex)
            {
                FmMessage.Alert("The sheet was not written:\n\n" + ex);
                return;
            }

            txtStatus.Text = "Exported " + blocks.Count + (narrowed ? " of " + tableBlocks.Count : "") +
                             " filter(s) to " + dialog.FileName;
            if (FmMessage.Confirm(
                "Exported " + blocks.Count + " filter(s)" + (narrowed ? " - the ones the table is showing" : "") + ".\n\n" +
                "The Guide tab explains the colours and how the round trip works; the Lists tab holds the values each " +
                "column will take.\n\n" +
                "Open it now?"))
                FmCore.OpenExternally(dialog.FileName);
        }

        public void OnImportExcel(object sender, RoutedEventArgs args)
        {
            var dialog = new Microsoft.Win32.OpenFileDialog
            {
                Filter = "Excel workbook (*.xlsx)|*.xlsx",
                Title = "Import an edited filter table",
            };
            if (dialog.ShowDialog(Win) != true) return;

            List<List<string>> rows;
            try { rows = FmXlsx.ReadWorkbook(dialog.FileName); }
            catch (Exception ex)
            {
                FmMessage.Alert("The sheet could not be read:\n\n" + ex);
                return;
            }

            if (tableBlocks.Count == 0) BuildTableTab();
            var applied = ApplySheet(rows);
            int changed = applied.Item1;
            List<string> notes = applied.Item2;

            // no dialog: the counts go on the status line, and anything that
            // needed a decision goes to the log where it can be read at leisure
            string logPath = "";
            if (notes.Count > 0)
            {
                var body = new List<string> { "Imported from: " + dialog.FileName, changed + " filter(s) updated", "" };
                body.AddRange(notes);
                logPath = WriteLog("FilterManagerImport", body, "Imported the filter table");
            }

            string message;
            if (changed > 0)
            {
                BuildTableTab();
                RefreshFooter();
                message = "Imported " + changed + " filter(s) - the changes are highlighted, 'Only edited filters' isolates " +
                          "them, and nothing is written until Apply.";
            }
            else message = "Nothing in the sheet differed from the table.";

            if (notes.Count > 0) message += "   " + notes.Count + " row(s) needed a look - see " + logPath;
            txtStatus.Text = message;
        }

        /// <summary>One filter's rows in a sheet: the row with its id, and the blank-id rows under it.</summary>
        private class SheetGroup
        {
            public long Key;
            public List<List<string>> Rows = new List<List<string>>();
            public int Line;
        }

        /// <summary>Read the sheet back into the table, without touching the model.</summary>
        private Tuple<int, List<string>> ApplySheet(List<List<string>> rows)
        {
            var byId = new Dictionary<long, FmBlock>();
            foreach (FmBlock block in tableBlocks) byId[FmCore.EidValue(block.Pfe.Id)] = block;

            var catByName = new Dictionary<string, ElementId>();
            foreach (var c in allCategories) catByName[c.Item2.ToLowerInvariant()] = c.Item1;

            var groups = new List<SheetGroup>();
            SheetGroup currentGroup = null;
            for (int index = 0; index < rows.Count; index++)
            {
                var cells = rows[index].Select(c => (c ?? "").Trim()).ToList();
                for (int pad = 0; pad < 7; pad++) cells.Add("");
                if (index == 0 && cells[0].ToLowerInvariant() == "id") continue;
                if (cells[0].Length > 0)
                {
                    double parsed;
                    if (!double.TryParse(cells[0], NumberStyles.Float, CultureInfo.InvariantCulture, out parsed) ||
                        double.IsNaN(parsed) || double.IsInfinity(parsed))
                        continue;
                    currentGroup = new SheetGroup { Key = (long)parsed, Line = index + 1 };
                    currentGroup.Rows.Add(cells);
                    groups.Add(currentGroup);
                }
                else if (currentGroup != null) currentGroup.Rows.Add(cells);
            }

            int changed = 0;
            var notes = new List<string>();
            foreach (SheetGroup group in groups)
            {
                FmBlock block;
                if (!byId.TryGetValue(group.Key, out block))
                {
                    notes.Add("Row " + group.Line + ": no filter with id " + group.Key + " in this model.");
                    continue;
                }
                if (ApplySheetBlock(block, group, catByName, notes)) changed++;
            }
            return Tuple.Create(changed, notes);
        }

        private bool ApplySheetBlock(FmBlock block, SheetGroup group, Dictionary<string, ElementId> catByName, List<string> notes)
        {
            Hydrate(block);
            List<string> head = group.Rows[0];
            int line = group.Line;
            bool touched = false;

            string name = head[1];
            if (name.Length > 0 && name != block.Name)
            {
                block.Name = name;
                block.Changes.Add("name");
                touched = true;
            }

            string match = head[3].ToUpperInvariant();
            if (match.StartsWith("OR", StringComparison.Ordinal)) match = "OR";
            else if (match.StartsWith("AND", StringComparison.Ordinal)) match = "AND";
            else match = block.Match;
            if (match != block.Match)
            {
                block.Match = match;
                block.Changes.Add("match");
                touched = true;
            }

            var cats = new List<ElementId>();
            for (int offset = 0; offset < group.Rows.Count; offset++)
            {
                List<string> row = group.Rows[offset];
                if (row[2].Length == 0) continue;
                ElementId cid;
                if (!catByName.TryGetValue(row[2].ToLowerInvariant(), out cid))
                {
                    notes.Add("Row " + (line + offset) + ": no category called '" + row[2] + "'.");
                    continue;
                }
                if (!cats.Any(c => FmCore.EidValue(cid) == FmCore.EidValue(c))) cats.Add(cid);
            }
            if (cats.Count > 0 &&
                !cats.Select(c => FmCore.EidValue(c)).SequenceEqual(block.Cats.Select(c => FmCore.EidValue(c))))
            {
                for (int position = 0; position < cats.Count; position++)
                {
                    ElementId was = position < block.Cats.Count ? block.Cats[position] : null;
                    if (was == null || FmCore.EidValue(was) != FmCore.EidValue(cats[position]))
                        block.Changes.Add("cat:" + position);
                }
                block.Cats = cats;
                block.Probe = null;
                touched = true;
            }

            var wanted = new List<KeyValuePair<int, List<string>>>();
            for (int offset = 0; offset < group.Rows.Count; offset++)
            {
                if (group.Rows[offset][4].Length > 0)
                    wanted.Add(new KeyValuePair<int, List<string>>(offset, group.Rows[offset]));
            }
            if (wanted.Count > 0)
            {
                ParameterProbe probe = TableProbe(block);
                var lookup = FmFilters.ParameterLookup(Doc, block.Cats);

                var rules = new List<FmRule>();
                foreach (var item in wanted)
                {
                    int offset = item.Key;
                    List<string> row = item.Value;
                    Tuple<ElementId, string> found;
                    if (!lookup.TryGetValue(row[4].ToLowerInvariant(), out found))
                    {
                        notes.Add("Row " + (line + offset) + ": no parameter called '" + row[4] + "' in this project.");
                        continue;
                    }
                    ElementId pid = found.Item1;
                    string scope = found.Item2;
                    if (scope == "partial")
                        notes.Add("Row " + (line + offset) + ": '" + row[4] + "' is not shared by every one of this filter's " +
                                  "categories - used anyway.");
                    else if (scope == "project")
                        notes.Add("Row " + (line + offset) + ": '" + row[4] + "' is a project parameter rather than one these " +
                                  "categories offer - used anyway, Revit may refuse it on Apply.");

                    var info = probe.Find(pid);
                    string storage = info.Item1;
                    ForgeTypeId spec = info.Item2;
                    bool yesno = info.Item3;
                    string op = OperatorFromText(row[5], storage, yesno);
                    if (op == null)
                    {
                        notes.Add("Row " + (line + offset) + ": '" + row[5] + "' is not an operator that suits '" + row[4] + "'.");
                        continue;
                    }

                    object value = row[6];
                    if (storage == "ElementId" && (op == "equals" || op == "not_equals") && row[6].Length > 0)
                    {
                        ElementId resolved = ElementValueFromText(probe, pid, row[6]);
                        if (resolved == null)
                        {
                            notes.Add("Row " + (line + offset) + ": nothing called '" + row[6] + "' for '" + row[4] +
                                      "' - use contains for a text match.");
                            continue;
                        }
                        value = resolved;
                    }

                    rules.Add(new FmRule { ParamId = pid, Op = op, Value = value, Storage = storage, Spec = spec, YesNo = yesno });
                }
                if (rules.Count > 0 && RulesDiffer(block.Rules, rules))
                {
                    for (int position = 0; position < rules.Count; position++)
                    {
                        FmRule was = position < block.Rules.Count ? block.Rules[position] : null;
                        if (was == null || RulesDiffer(new List<FmRule> { was }, new List<FmRule> { rules[position] }))
                            block.Changes.Add("rule:" + position);
                    }
                    block.Rules = rules;
                    touched = true;
                }
            }

            if (touched)
            {
                block.Dirty = true;
                PaintBlock(block);
            }
            return touched;
        }

        /// <summary>Match an operator by its wording, however it was typed.</summary>
        private string OperatorFromText(string text, string storage, bool yesno)
        {
            string wanted = (text ?? "").Trim().ToLowerInvariant();
            if (wanted.Length == 0) return null;
            string[] allowed = FmFilters.OpsForStorage(storage, yesno);
            foreach (string key in allowed)
            {
                if (FmFilters.OpLabel[key].ToLowerInvariant() == wanted) return key;
            }
            foreach (string key in allowed)
            {
                if (key == wanted) return key;
            }
            // tolerate the shorthand people type
            var shorthand = new Dictionary<string, string>
            {
                { "=", "equals" }, { "==", "equals" }, { "!=", "not_equals" }, { "<>", "not_equals" },
                { ">", "greater" }, { ">=", "greater_equal" }, { "<", "less" }, { "<=", "less_equal" },
            };
            string mapped;
            if (shorthand.TryGetValue(wanted, out mapped) && Array.IndexOf(allowed, mapped) >= 0) return mapped;
            return null;
        }

        /// <summary>Turn a typed element name back into the id it stands for.</summary>
        private ElementId ElementValueFromText(ParameterProbe probe, ElementId pid, string text)
        {
            string wanted = (text ?? "").Trim().ToLowerInvariant();
            try
            {
                foreach (var pair in probe.IdValues(pid))
                {
                    if ((pair.Item2 ?? "").Trim().ToLowerInvariant() == wanted) return pair.Item1;
                }
            }
            catch (Exception) { }
            try
            {
                long parsed;
                if (long.TryParse((text ?? "").Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out parsed))
                    return new ElementId(parsed);
            }
            catch (Exception) { }
            return null;
        }

        private bool RulesDiffer(List<FmRule> before, List<FmRule> after)
        {
            if (before.Count != after.Count) return true;
            for (int i = 0; i < before.Count; i++)
            {
                FmRule old = before[i];
                FmRule now = after[i];
                if (FmCore.EidValue(old.ParamId) != FmCore.EidValue(now.ParamId)) return true;
                if (old.Op != now.Op) return true;
                if (!SameValue(old, now)) return true;
            }
            return false;
        }
    }
}
