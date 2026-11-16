using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
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
    //  TAB 2 - FILTER MANAGER TABLE: one filter   (script.py 2864-3326)
    // =======================================================================
    public partial class FmWindow
    {
        // -- one filter -----------------------------------------------------------
        /// <summary>
        /// A block, created without reading the filter's rules. Reading every filter's rules to open the tab
        /// means a full parse of the whole project before a single row is on screen. A block starts with what
        /// is cheap - its name and its categories - and its rules are read the moment it is shown, exported,
        /// imported into or applied.
        /// </summary>
        private FmBlock TableBlock(ParameterFilterElement pfe)
        {
            var host = new Border
            {
                BorderBrush = FmUi.PBrush("EdgeFaint"),
                BorderThickness = new Thickness(0, 0, 0, 1),
                Padding = new Thickness(0, 3, 0, 3),
            };

            return new FmBlock
            {
                Pfe = pfe,
                Name = pfe.Name,
                Match = "AND",
                Cats = FmFilters.FilterCategoryIds(pfe),
                Rules = new List<FmRule>(),
                Probe = null,
                Dirty = false,
                Changes = new HashSet<string>(),
                Search = null,
                Grid = null,
                Hydrated = false,
                Host = host,
            };
        }

        /// <summary>Read the block's rules and draw it, once.</summary>
        private FmBlock Hydrate(FmBlock block)
        {
            if (block.Hydrated) return block;
            block.Hydrated = true;

            var read = FmFilters.ReadFilter(Doc, block.Pfe);
            block.Match = read.Item1;
            block.Rules = read.Item2;

            // a rule stored in feet needs the parameter's unit to be readable,
            // so a filter with a numeric rule is sampled; the rest are not
            if (block.Rules.Any(r => r.Storage == "Double"))
            {
                TableProbe(block);
                foreach (FmRule rule in block.Rules) TableEnrich(block, rule);
            }
            foreach (FmRule rule in block.Rules) NormaliseRule(rule);

            block.Search = null;
            PaintBlock(block);
            return block;
        }

        /// <summary>
        /// Sample elements for this filter's categories, once and only when something actually needs the
        /// parameter list or a storage type.
        /// </summary>
        private ParameterProbe TableProbe(FmBlock block)
        {
            if (block.Probe == null) block.Probe = FmFilters.ProbeFor(Doc, block.Cats);
            return block.Probe;
        }

        /// <summary>
        /// Put a rule's value into the form the table works in. A rule read from Revit holds a number in
        /// internal units; a rule typed in or read from a sheet holds display text. Two conventions in one
        /// field made every comparison lie - which is why an import reported changes nobody had made.
        /// Everything is display text from here on, except an element id, which stays an id so equals can be
        /// written.
        /// </summary>
        private FmRule NormaliseRule(FmRule rule)
        {
            if (!FmFilters.NeedsValue(rule.Op))
            {
                rule.Value = "";
                return rule;
            }

            object value = rule.Value;
            if (value is ElementId) return rule;

            if (rule.Storage == "Double")
            {
                try
                {
                    double shown = FmFilters.ToDisplay(Doc, Convert.ToDouble(value, CultureInfo.InvariantCulture), rule.Spec);
                    rule.Value = PyText(Math.Round(shown, 6, MidpointRounding.AwayFromZero));
                }
                catch (Exception) { rule.Value = PyText(value); }
            }
            else rule.Value = value == null ? "" : PyText(value);
            return rule;
        }

        /// <summary>A value as python's u"{0}".format(value) would write it.</summary>
        private static string PyText(object value)
        {
            if (value == null) return "";
            string text = value as string;
            if (text != null) return text;
            if (value is double) return PyFloat((double)value);
            if (value is float) return PyFloat((float)value);
            if (value is bool) return (bool)value ? "True" : "False";
            var id = value as ElementId;
            if (id != null) return FmCore.EidValue(id).ToString();
            return Convert.ToString(value, CultureInfo.InvariantCulture) ?? "";
        }

        private static string PyFloat(double value)
        {
            if (double.IsNaN(value)) return "nan";
            if (double.IsInfinity(value)) return value > 0 ? "inf" : "-inf";
            string text = value.ToString("0.######", CultureInfo.InvariantCulture);
            if (text == "-0") text = "-0.0";
            else if (text.IndexOf('.') < 0 && text.IndexOf('E') < 0) text += ".0";
            return text;
        }

        /// <summary>Fill in the unit and yes/no flag a decoded rule cannot know.</summary>
        private void TableEnrich(FmBlock block, FmRule rule)
        {
            ParameterProbe probe = block.Probe;
            if (probe == null || rule.ParamId == null) return;
            var found = probe.Find(rule.ParamId);
            if (rule.Storage == "Double" && found.Item2 != null) rule.Spec = found.Item2;
            rule.YesNo = found.Item3;
        }

        /// <summary>
        /// Remember that a block changed, and which cells did. The keys drive the highlight, so an import can
        /// point at exactly what it touched rather than just colouring a whole filter.
        /// </summary>
        private void MarkDirty(FmBlock block, params string[] keys)
        {
            block.Dirty = true;
            foreach (string key in keys) block.Changes.Add(key);
            RefreshFooter();
        }

        // -- painting -------------------------------------------------------------
        private void PaintBlock(FmBlock block)
        {
            block.Search = null;

            int rows = Math.Max(1, Math.Max(block.Cats.Count, block.Rules.Count));
            var grid = new Grid();
            grid.Width = TableTotalWidth();
            foreach (TableColumn column in TableColumns) grid.ColumnDefinitions.Add(FmUi.Col(pixels: column.Width));
            for (int i = 0; i < rows + 1; i++) grid.RowDefinitions.Add(FmUi.Row());

            // ---- name
            TextBox nameBox = FmUi.NewTextBox(block.Name);
            nameBox.Height = FmUi.CellHeight;
            nameBox.Margin = new Thickness(6, 3, 6, 3);
            nameBox.TextChanged += FmUi.SafeText((s, a) =>
            {
                block.Name = ((TextBox)s).Text;
                MarkDirty(block, "name");
            }, "table name");
            Highlight(nameBox, block, "name");
            TablePlace(grid, nameBox, 0, 0);

            var uses = new TextBlock
            {
                Text = BlockUses(block).ToString(),
                FontSize = 11,
                Margin = new Thickness(0, 9, 0, 0),
                HorizontalAlignment = FmUi.Centre(),
                ToolTip = "How many views and view templates use this filter",
            };
            uses.SetResourceReference(TextBlock.ForegroundProperty, "Dim");
            TablePlace(grid, uses, 0, 1);

            // ---- match mode
            var labels = new List<string> { "AND - all", "OR - any" };
            var keys = new List<object> { "AND", "OR" };
            ComboBox matchCombo = FmUi.NewCombo(labels, keys.IndexOf(block.Match) >= 0 ? keys.IndexOf(block.Match) : 0,
                                                tags: keys, height: FmUi.CellHeight);
            matchCombo.Margin = new Thickness(4, 3, 6, 3);
            matchCombo.SelectionChanged += FmUi.SafeSelection((s, a) =>
            {
                var picked = FmUi.ComboTag((ComboBox)s) as string;
                if (!string.IsNullOrEmpty(picked) && picked != block.Match)
                {
                    block.Match = picked;
                    MarkDirty(block, "match");
                }
            }, "table match");
            Highlight(matchCombo, block, "match");
            TablePlace(grid, matchCombo, 0, 3);

            // ---- categories, one under the other
            for (int index = 0; index < block.Cats.Count; index++)
                TablePlace(grid, CategoryCell(block, index, block.Cats[index]), index, 2);

            // ---- rules, one per row
            for (int index = 0; index < block.Rules.Count; index++)
            {
                TablePlace(grid, RuleParameterCell(block, index), index, 4);
                TablePlace(grid, RuleOperatorCell(block, index), index, 5);
                TablePlace(grid, RuleValueCell(block, index), index, 6);
                TablePlace(grid, RuleRemoveCell(block, index), index, 7);
            }

            if (block.Rules.Count == 0)
            {
                var note = new TextBlock
                {
                    Text = "no rules - matches everything in its categories",
                    FontSize = 10,
                    VerticalAlignment = VerticalAlignment.Center,
                    Margin = new Thickness(6, 3, 6, 3),
                };
                note.SetResourceReference(TextBlock.ForegroundProperty, "Dim");
                TablePlace(grid, note, 0, 4);
            }

            // ---- the add row
            TablePlace(grid, AddButton("+ category", () => TableAddCategory(block)), rows, 2);
            TablePlace(grid, AddButton("+ rule", () => TableAddRule(block)), rows, 4);

            // a block painted by an edit takes the widths the rest of the table is using
            PlaceWidths(grid);
            block.Grid = grid;
            block.Host.Child = grid;
            return;
        }

        /// <summary>Tint a cell the import or an edit has touched.</summary>
        private static T Highlight<T>(T element, FmBlock block, string key) where T : System.Windows.Controls.Control
        {
            if (!block.Changes.Contains(key)) return element;
            try { element.Background = FmUi.PBrush("ChangedBg"); }
            catch (Exception) { }
            try
            {
                element.BorderBrush = FmUi.PBrush("ChangedEdge");
                element.BorderThickness = new Thickness(1);
            }
            catch (Exception) { }
            return element;
        }

        private Button AddButton(string text, Action action)
        {
            Button button = FmUi.NewButton(text, "Ghost", height: 22);
            button.FontSize = 10;
            button.Margin = new Thickness(6, 2, 6, 4);
            button.HorizontalAlignment = HorizontalAlignment.Left;
            button.Click += FmUi.Safe((s, a) => action(), "table add");
            return button;
        }

        // -- category cell --------------------------------------------------------
        private Grid CategoryCell(FmBlock block, int index, ElementId cid)
        {
            var holder = new Grid();
            holder.ColumnDefinitions.Add(FmUi.Col(1));
            holder.ColumnDefinitions.Add(FmUi.Col(pixels: 24));
            holder.Margin = new Thickness(4, 3, 4, 3);

            var names = allCategories.Select(c => c.Item2).ToList();
            var tags = allCategories.Select(c => (object)c.Item1).ToList();
            int selected = -1;
            for (int i = 0; i < tags.Count; i++)
            {
                if (FmCore.EidValue((ElementId)tags[i]) == FmCore.EidValue(cid))
                {
                    selected = i;
                    break;
                }
            }
            ComboBox combo = FmUi.NewCombo(names, selected, tags: tags, height: FmUi.CellHeight);

            int position = index;
            combo.SelectionChanged += FmUi.SafeSelection((s, a) =>
            {
                var picked = FmUi.ComboTag((ComboBox)s) as ElementId;
                if (picked == null) return;
                if (position >= block.Cats.Count) return;
                if (FmCore.EidValue(picked) == FmCore.EidValue(block.Cats[position])) return;
                block.Cats[position] = picked;
                block.Probe = null;      // the shared parameter list has moved
                MarkDirty(block, "cat:" + position);
            }, "table category");
            Highlight(combo, block, "cat:" + index);
            FmUi.Place(combo, holder, 0);

            Button kill = FmUi.NewButton("x", "RowKill", width: 20, height: 22);
            kill.Click += FmUi.Safe((s, a) =>
            {
                if (block.Cats.Count <= 1)
                {
                    txtStatus.Text = "A filter must keep at least one category.";
                    return;
                }
                block.Cats.RemoveAt(position);
                block.Probe = null;
                MarkDirty(block);
                PaintBlock(block);
            }, "table remove category");
            FmUi.Place(kill, holder, 1);
            return holder;
        }

        private void TableAddCategory(FmBlock block)
        {
            foreach (var c in allCategories)
            {
                bool present = block.Cats.Any(x => FmCore.EidValue(c.Item1) == FmCore.EidValue(x));
                if (!present)
                {
                    block.Cats.Add(c.Item1);
                    block.Probe = null;
                    MarkDirty(block);
                    PaintBlock(block);
                    return;
                }
            }
            txtStatus.Text = "Every category is already on this filter.";
        }

        // -- rule cells -----------------------------------------------------------
        private ComboBox RuleParameterCell(FmBlock block, int index)
        {
            FmRule rule = block.Rules[index];
            string current = rule.ParamId != null ? FmFilters.ParameterName(Doc, rule.ParamId) : "(pick a parameter)";

            ComboBox combo = FmUi.NewCombo(new List<string> { current }, 0, tags: new List<object> { rule.ParamId },
                                           height: FmUi.CellHeight);
            combo.Margin = new Thickness(4, 3, 4, 3);
            bool filled = false;
            int position = index;

            combo.DropDownOpened += FmUi.SafeEvent((s, a) =>
            {
                // the full list costs a scan of the model, so it is not built
                // until the list is actually opened
                if (filled) return;
                filled = true;
                var sender = (ComboBox)s;
                TableProbe(block);
                var options = FmFilters.CommonParameters(Doc, block.Cats);
                ElementId keep = rule.ParamId;
                sender.Items.Clear();
                int chosen = 0;
                for (int i = 0; i < options.Count; i++)
                {
                    sender.Items.Add(FmUi.ComboItem(options[i].Item2, options[i].Item1));
                    if (keep != null && FmCore.EidValue(options[i].Item1) == FmCore.EidValue(keep)) chosen = i;
                }
                if (sender.Items.Count == 0) sender.Items.Add(FmUi.ComboItem(current, keep));
                sender.SelectedIndex = chosen;
            }, "table parameter list");

            combo.SelectionChanged += FmUi.SafeSelection((s, a) =>
            {
                if (!filled) return;
                var picked = FmUi.ComboTag((ComboBox)s) as ElementId;
                if (picked == null || (rule.ParamId != null && FmCore.EidValue(picked) == FmCore.EidValue(rule.ParamId))) return;
                rule.ParamId = picked;
                ParameterProbe probe = TableProbe(block);
                var found = probe.Find(picked);
                rule.Storage = found.Item1;
                rule.Spec = found.Item2;
                rule.YesNo = found.Item3;
                string[] allowed = FmFilters.OpsForStorage(rule.Storage, rule.YesNo);
                if (Array.IndexOf(allowed, rule.Op) < 0) rule.Op = allowed[0];
                rule.Value = "";
                MarkDirty(block, "rule:" + position);
                PaintBlock(block);
            }, "table parameter");

            return Highlight(combo, block, "rule:" + index);
        }

        private ComboBox RuleOperatorCell(FmBlock block, int index)
        {
            FmRule rule = block.Rules[index];
            string[] keys = FmFilters.OpsForStorage(rule.Storage ?? "String", rule.YesNo);
            var labels = keys.Select(k => FmFilters.OpLabel[k]).ToList();
            int chosen = Array.IndexOf(keys, rule.Op);
            if (chosen < 0) chosen = 0;

            ComboBox combo = FmUi.NewCombo(labels, chosen, tags: keys.Select(k => (object)k).ToList(), height: FmUi.CellHeight);
            combo.Margin = new Thickness(4, 3, 4, 3);
            int position = index;

            combo.SelectionChanged += FmUi.SafeSelection((s, a) =>
            {
                var picked = FmUi.ComboTag((ComboBox)s) as string;
                if (picked == null || picked == rule.Op) return;
                bool neededBefore = FmFilters.NeedsValue(rule.Op);
                rule.Op = picked;
                MarkDirty(block, "rule:" + position);
                if (neededBefore != FmFilters.NeedsValue(picked)) PaintBlock(block);
            }, "table operator");

            return Highlight(combo, block, "rule:" + index);
        }

        private FrameworkElement RuleValueCell(FmBlock block, int index)
        {
            FmRule rule = block.Rules[index];
            int position = index;

            if (!FmFilters.NeedsValue(rule.Op))
            {
                var note = new TextBlock
                {
                    Text = "no value needed",
                    FontSize = 10,
                    VerticalAlignment = VerticalAlignment.Center,
                    Margin = new Thickness(6, 3, 6, 3),
                };
                note.SetResourceReference(TextBlock.ForegroundProperty, "Dim");
                return note;
            }

            string storage = rule.Storage ?? "String";
            object shown = rule.Value;

            if (storage == "Integer" && rule.YesNo)
            {
                string shownText = PyText(shown);
                bool yes = shownText == "1" || shownText == "True" || shownText == "Yes";
                ComboBox combo = FmUi.NewCombo(new List<string> { "Yes", "No" }, yes ? 0 : 1,
                                               tags: new List<object> { "1", "0" }, height: FmUi.CellHeight);
                combo.Margin = new Thickness(4, 3, 4, 3);
                combo.SelectionChanged += FmUi.SafeSelection((s, a) =>
                {
                    rule.Value = FmUi.ComboTag((ComboBox)s);
                    MarkDirty(block, "rule:" + position);
                }, "table yes no");
                return Highlight(combo, block, "rule:" + index);
            }

            string text;
            var shownId = shown as ElementId;
            if (shownId != null) text = FmFilters.ElementName(Doc, shownId, FmCore.EidValue(shownId).ToString());
            else text = PyText(shown);

            TextBox box = FmUi.NewTextBox(text, storage == "Double" ? FmFilters.UnitLabel(Doc, rule.Spec) : "");
            box.Height = FmUi.CellHeight;
            box.Margin = new Thickness(4, 3, 4, 3);
            box.TextChanged += FmUi.SafeText((s, a) =>
            {
                rule.Value = ((TextBox)s).Text;
                MarkDirty(block, "rule:" + position);
            }, "table value");
            return Highlight(box, block, "rule:" + index);
        }

        private Button RuleRemoveCell(FmBlock block, int index)
        {
            Button kill = FmUi.NewButton("x", "RowKill", width: 22, height: 22);
            kill.Margin = new Thickness(4, 3, 4, 3);
            kill.HorizontalAlignment = HorizontalAlignment.Left;
            int position = index;
            kill.Click += FmUi.Safe((s, a) =>
            {
                block.Rules.RemoveAt(position);
                MarkDirty(block);
                PaintBlock(block);
            }, "table remove rule");
            return kill;
        }

        private void TableAddRule(FmBlock block)
        {
            ParameterProbe probe = TableProbe(block);
            var options = FmFilters.CommonParameters(Doc, block.Cats);
            if (options.Count == 0)
            {
                txtStatus.Text = "These categories share no filterable parameters.";
                return;
            }
            ElementId pid = options[0].Item1;
            var found = probe.Find(pid);
            block.Rules.Add(new FmRule
            {
                ParamId = pid,
                Op = FmFilters.OpsForStorage(found.Item1, found.Item3)[0],
                Value = "",
                Storage = found.Item1,
                Spec = found.Item2,
                YesNo = found.Item3,
            });
            MarkDirty(block);
            PaintBlock(block);
        }
    }
}
