// Excel for Revit: the external-event work handler, failure swallower and grid helpers
// (port of efr_core.py lines 1671-1778).
using System;
using System.Collections.Generic;
using System.Data;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.UI.ExcelForRevit;

namespace RevoBIM.Tools.ExcelForRevit
{
    /// <summary>
    /// The only way a modeless window can touch the model.
    /// A modeless window runs outside Revit's API context, so it cannot open a transaction directly.
    /// Every write is queued here (set <see cref="Job"/>, then raise the ExternalEvent) and Revit calls
    /// Execute back when it is safe. One job at a time: Execute takes the job and clears it.
    /// </summary>
    public class WorkHandler : IExternalEventHandler
    {
        /// <summary>The queued job, or null. Receives the UIApplication Revit passes to Execute.</summary>
        public Action<UIApplication> Job;
        /// <summary>The name Revit shows for the event.</summary>
        public string Name = "RevoBIM Excel for Revit";

        public void Execute(UIApplication app)
        {
            Action<UIApplication> job = Job;
            Job = null;
            if (job == null) return;
            try
            {
                job(app);
            }
            catch (Exception ex)
            {
                try
                {
                    Efr.ReportError("Excel for Revit", ex.ToString());
                }
                catch (Exception) { }
            }
        }

        public string GetName()
        {
            return Name;
        }
    }

    /// <summary>Deletes warnings during a transaction so a warning dialog cannot stall a write.</summary>
    public class WarningSwallower : IFailuresPreprocessor
    {
        public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
        {
            try
            {
                foreach (FailureMessageAccessor f in accessor.GetFailureMessages())
                {
                    if (f.GetSeverity() == FailureSeverity.Warning)
                        accessor.DeleteWarning(f);
                }
            }
            catch (Exception) { }
            return FailureProcessingResult.Continue;
        }
    }

    public static partial class Efr
    {
        /// <summary>Show an error in the themed dialog (red accent, 700 wide).</summary>
        public static void ReportError(string title, string text)
        {
            EfrUi.ThemedMessage(title, text, accent: C_RED, width: 700);
        }

        /// <summary>
        /// Write a bookkeeping flag into a bound row only if it actually changes. Every write to a row
        /// of the bound table is reported through the DataView to the grid, which re-reads that row's
        /// bindings, whether or not the value moved. Reading first is one call; a write that changes
        /// nothing is a cascade of them. Returns true when the value was written.
        /// </summary>
        public static bool SetFlag(DataRow row, string name, string value)
        {
            try
            {
                if (ToText(row[name]) == value) return false;
            }
            catch (Exception) { }
            row[name] = value;
            return true;
        }

        /// <summary>The same for a row reached through a DataView (DataRowView).</summary>
        public static bool SetFlag(DataRowView row, string name, string value)
        {
            try
            {
                if (ToText(row[name]) == value) return false;
            }
            catch (Exception) { }
            row[name] = value;
            return true;
        }

        /// <summary>A remembered answer that has to be worked out again (Python _STALE sentinel).</summary>
        public static readonly object Stale = new object();

        /// <summary>Layout passes to wait for a row's cells to be generated.</summary>
        public const int PaintRetries = 4;

        /// <summary>
        /// The bookkeeping columns every grid row carries ahead of the schedule's own, in table order.
        /// Both the column list and each row's values are built from this one array.
        /// </summary>
        public static readonly string[] GRID_META_COLS =
        {
            "ridx",     // the row's index in the model
            "rn",       // the row number shown in the first column
            "eid",      // the element id shown in the second
            "vis",      // filter snapshot, never shown
            "gkey",     // sort key that keeps a heading with its group
            "grp",      // group number, set on heading rows only
            "show",     // vis, minus anything in a collapsed group
        };

        /// <summary>One grid row's values (all strings), in the same order as the table's columns:
        /// the GRID_META_COLS first, then one per schedule field.</summary>
        public static object[] GridRowValues(ScheduleModel model, RowInfo row, int n)
        {
            Dictionary<string, string> meta = new Dictionary<string, string>
            {
                { "ridx", ToText(n) },
                { "rn", ToText(n + 1) },
                { "eid", ToText(EidValue(row.ElemId)) },
                { "vis", "1" },
                { "gkey", "" },
                { "grp", "" },
                { "show", "1" },
            };
            List<object> values = new List<object>();
            foreach (string name in GRID_META_COLS)
                values.Add(meta[name]);
            foreach (FieldInfo fi in model.Fields)
                values.Add(model.CurrentText(row, fi.Index));
            return values.ToArray();
        }

        /// <summary>(target, param) -> [(row, field index), ...] for the whole grid (test columns excluded).</summary>
        public static Dictionary<EditKey, List<(RowInfo Row, int Field)>> BuildKeyIndex(ScheduleModel model)
        {
            Dictionary<EditKey, List<(RowInfo Row, int Field)>> index = new Dictionary<EditKey, List<(RowInfo Row, int Field)>>();
            foreach (RowInfo r in model.Rows)
            {
                for (int i = 0; i < model.Fields.Count; i++)
                {
                    EditKey k = model.KeyOf(r, i);
                    if (k == null || k.IsScratch) continue;
                    List<(RowInfo Row, int Field)> list;
                    if (!index.TryGetValue(k, out list))
                    {
                        list = new List<(RowInfo Row, int Field)>();
                        index[k] = list;
                    }
                    list.Add((r, i));
                }
            }
            return index;
        }
    }
}
