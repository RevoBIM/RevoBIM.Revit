// Excel for Revit: the data model (port of efr_core.py lines 897-1409).
// ScheduleModel reads a ViewSchedule into rows of cells and writes staged edits back.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevoBIM.Tools.ExcelForRevit
{
    /// <summary>
    /// Which staged-edit slot a cell writes to (Python: a tuple used as a dict key).
    /// A model key is (target element id, parameter id); a scratch key is
    /// ('S', row index, field index) and never reaches the model. Value equality,
    /// so it works as a Dictionary / HashSet key. "No key" is a null reference.
    /// </summary>
    public sealed class EditKey : IEquatable<EditKey>
    {
        /// <summary>True for a test-column ("scratch") cell; its values live in ScheduleModel.ScratchValues.</summary>
        public readonly bool IsScratch;
        // model key: _a = target id, _b = parameter id.  scratch key: _a = row index (ridx), _b = field index.
        private readonly long _a;
        private readonly long _b;

        private EditKey(bool scratch, long a, long b) { IsScratch = scratch; _a = a; _b = b; }

        /// <summary>(target element id, parameter id): Python key[0], key[1].</summary>
        public static EditKey Of(long target, long param) { return new EditKey(false, target, param); }
        /// <summary>('S', ridx, field index).</summary>
        public static EditKey Scratch(int ridx, int fieldIndex) { return new EditKey(true, ridx, fieldIndex); }

        /// <summary>Model key only: the element (instance or type) the parameter lives on (Python key[0]).</summary>
        public long Target { get { return _a; } }
        /// <summary>Model key only: the parameter id (Python key[1]).</summary>
        public long Param { get { return _b; } }
        /// <summary>Scratch key only: the row index in ScheduleModel.Rows (Python key[1]).</summary>
        public int Ridx { get { return (int)_a; } }
        /// <summary>Scratch key only: the field index (Python key[2]).</summary>
        public int FieldIndex { get { return (int)_b; } }

        public bool Equals(EditKey other)
        {
            return !ReferenceEquals(other, null) && other.IsScratch == IsScratch && other._a == _a && other._b == _b;
        }
        public override bool Equals(object obj) { return Equals(obj as EditKey); }
        public override int GetHashCode()
        {
            unchecked
            {
                int h = IsScratch ? 17 : 31;
                h = h * 397 ^ _a.GetHashCode();
                h = h * 397 ^ _b.GetHashCode();
                return h;
            }
        }
        public override string ToString()
        {
            return IsScratch ? "S:" + _a + ":" + _b : _a + ":" + _b;
        }
    }

    /// <summary>
    /// One visible column of the schedule (Python FieldInfo).
    /// </summary>
    public class FieldInfo
    {
        /// <summary>Position among the visible fields (also the index into RowInfo.Cells).</summary>
        public int Index;
        /// <summary>Column heading (ColumnHeading, else the field name).</summary>
        public string Name = "";
        /// <summary>Name of the grid column in the bound table: "c{index}" for schedule fields, "s{n}" for test columns.</summary>
        public string Col = "c0";
        /// <summary>True for a type parameter field (ScheduleFieldType.ElementType).</summary>
        public bool IsType;
        /// <summary>The parameter the field shows (invalid for combined / calculated fields).</summary>
        public ElementId ParamId = ElementId.InvalidElementId;
        /// <summary>False for combined and calculated fields: shown, never written.</summary>
        public bool Supported;
        /// <summary>Why the field is read only (empty when Supported).</summary>
        public string Reason = "";
        /// <summary>Spreadsheet column letter used in formulas (set by the window: Efr.ColLetter(index)).</summary>
        public string Letter = "";
        /// <summary>Parts of a combined-parameter field, or null (see Efr.CombinedParts).</summary>
        public List<(ElementId ParamId, string Prefix, string Suffix, string Separator)> Combined;
        /// <summary>True for a test column added in the window; never written to the model.</summary>
        public bool Scratch;
    }

    /// <summary>
    /// One cell of one row (Python CellInfo).
    /// </summary>
    public class CellInfo
    {
        /// <summary>Element the parameter lives on (the instance or its type); null when there is none.</summary>
        public ElementId TargetId;
        /// <summary>The parameter's id; null for scratch cells.</summary>
        public ElementId ParamId;
        /// <summary>True when the cell can be edited.</summary>
        public bool Editable;
        /// <summary>Why it cannot be edited (tooltip text).</summary>
        public string Reason = "";
        /// <summary>The text the model currently holds.</summary>
        public string Original = "";
        /// <summary>True when the parameter lives on the element's type.</summary>
        public bool IsType;
        /// <summary>True for a cell of a test column.</summary>
        public bool Scratch;

        // cached staged-edit key; worked out on first use (Python _NO_KEY sentinel => KeyKnown)
        internal EditKey KeyCache;
        internal bool KeyKnown;
    }

    /// <summary>
    /// One schedule row = one element (Python RowInfo).
    /// </summary>
    public class RowInfo
    {
        /// <summary>The element shown on this row.</summary>
        public ElementId ElemId;
        /// <summary>The element's type id (or the element itself when it is a type); null when it has none.</summary>
        public ElementId TypeId;
        /// <summary>One cell per field, in field order (test columns append a cell).</summary>
        public List<CellInfo> Cells = new List<CellInfo>();
        /// <summary>Each cell's text at read time, used for sorting.</summary>
        public List<string> SortText = new List<string>();
        /// <summary>Index of this row in ScheduleModel.Rows; assigned by the window when it builds the grid
        /// (Python set it as `row.ridx = n`), also part of scratch keys.</summary>
        public int Ridx;
    }

    /// <summary>
    /// What Apply did (Python: the dict returned by ScheduleModel.apply).
    /// </summary>
    public class ApplyResult
    {
        /// <summary>Cells written.</summary>
        public int Cells;
        /// <summary>Instance elements changed.</summary>
        public int Instances;
        /// <summary>Type elements changed.</summary>
        public int Types;
        /// <summary>Distinct grid rows touched.</summary>
        public int RowsAffected;
        /// <summary>Elements whose level was changed.</summary>
        public int Levels;
        /// <summary>(label, parameter name, message) per failure.</summary>
        public List<(string Label, string Param, string Message)> Failures = new List<(string Label, string Param, string Message)>();
        /// <summary>False when the transaction failed or a level change failed.</summary>
        public bool Ok = true;
    }

    /// <summary>
    /// Reads a ViewSchedule into rows of cells, and writes staged edits back.
    ///
    /// Public surface:
    ///   Doc, Sched, Error (null when the schedule read fine), Notes (status line parts),
    ///   Fields, Rows, Edits (EditKey -> text), Failed, ScratchValues, LevelEdits (row index -> level id and name),
    ///   Lookup, Worksets, WorksetFields,
    ///   KeyOf / StoreFor / CurrentText / IsEdited / RowsSharing, Apply, RefreshOriginals, RefreshCombined.
    /// </summary>
    public class ScheduleModel
    {
        public Document Doc;
        public ViewSchedule Sched;
        /// <summary>Set when the schedule could not be read (message to show), else null.</summary>
        public string Error;
        /// <summary>Lines for the window's subtitle ("12 rows, 5 fields (1 type, 4 instance).").</summary>
        public List<string> Notes = new List<string>();
        public List<FieldInfo> Fields = new List<FieldInfo>();
        public List<RowInfo> Rows = new List<RowInfo>();
        /// <summary>Staged edits: (target id, parameter id) -> text.</summary>
        public Dictionary<EditKey, string> Edits = new Dictionary<EditKey, string>();
        /// <summary>Keys whose last write was refused.</summary>
        public HashSet<EditKey> Failed = new HashSet<EditKey>();
        /// <summary>Values of test columns: ('S', ridx, field index) -> text, never applied.</summary>
        public Dictionary<EditKey, string> ScratchValues = new Dictionary<EditKey, string>();
        /// <summary>Staged level changes: row index -> (level id, level name).</summary>
        public Dictionary<int, (ElementId LevelId, string LevelName)> LevelEdits = new Dictionary<int, (ElementId LevelId, string LevelName)>();
        public ParamLookup Lookup;
        /// <summary>User worksets [(name, id)] in natural order (empty when not workshared).</summary>
        public List<(string Name, int Id)> Worksets = new List<(string Name, int Id)>();
        /// <summary>Indices of the fields that show an element's Workset.</summary>
        public HashSet<int> WorksetFields = new HashSet<int>();

        public ScheduleModel(Document doc, ViewSchedule sched)
        {
            Doc = doc;
            Sched = sched;
            try
            {
                Load();
            }
            catch (Exception ex)
            {
                Error = "Could not read this schedule:\n\n" + ex.ToString();
            }
        }

        // -- reading ------------------------------------------------------------

        private Dictionary<long, Parameter> ParamMapOf(Element elem)
        {
            return Efr.ParamMap(elem);
        }

        private void Load()
        {
            Document doc = Doc;
            ViewSchedule sched = Sched;
            ScheduleDefinition defn = sched.Definition;

            try
            {
                if (defn.IsMaterialTakeoff)
                {
                    Error = "Material takeoffs are not supported.\n\n" +
                            "Their rows are materials within elements rather than " +
                            "elements, so they cannot be edited cell for cell.";
                    return;
                }
            }
            catch (Exception) { }

            // fields -------------------------------------------------------------
            List<ScheduleFieldId> order;
            try
            {
                order = new List<ScheduleFieldId>(defn.GetFieldOrder());
            }
            catch (Exception)
            {
                order = new List<ScheduleFieldId>();
                for (int i = 0; i < defn.GetFieldCount(); i++)
                    order.Add(defn.GetFieldId(i));
            }

            int idx = 0;
            foreach (ScheduleFieldId fid in order)
            {
                ScheduleField f;
                try
                {
                    f = defn.GetField(fid);
                }
                catch (Exception)
                {
                    continue;
                }
                try
                {
                    if (f.IsHidden) continue;
                }
                catch (Exception) { }
                FieldInfo fi = new FieldInfo();
                fi.Index = idx;
                fi.Col = "c" + idx.ToString(CultureInfo.InvariantCulture);
                try
                {
                    string heading = f.ColumnHeading;
                    fi.Name = !string.IsNullOrEmpty(heading) ? heading : f.GetName();
                }
                catch (Exception)
                {
                    try
                    {
                        fi.Name = f.GetName();
                    }
                    catch (Exception)
                    {
                        fi.Name = "Field " + (idx + 1).ToString(CultureInfo.InvariantCulture);
                    }
                }
                ScheduleFieldType? ft;
                try
                {
                    ft = f.FieldType;
                }
                catch (Exception)
                {
                    ft = null;
                }
                fi.IsType = (ft != null && ft.Value == ScheduleFieldType.ElementType);
                try
                {
                    fi.ParamId = f.ParameterId;
                }
                catch (Exception)
                {
                    fi.ParamId = ElementId.InvalidElementId;
                }
                fi.Combined = Efr.CombinedParts(f);
                if (fi.Combined != null && fi.Combined.Count > 0)
                {
                    // shown as Revit builds it; it has no parameter of its own to
                    // write back to, so edits go to the parameters it is made from
                    fi.Supported = false;
                    fi.Reason = "combined parameter — shown as the schedule builds " +
                                "it; edit the parameters it is made from";
                }
                else if (ft != null && ft.Value != ScheduleFieldType.Instance && ft.Value != ScheduleFieldType.ElementType)
                {
                    fi.Supported = false;
                    fi.Reason = "calculated field (" + ft.Value.ToString() + ") — read only";
                }
                else if (!Efr.IsValidId(fi.ParamId))
                {
                    fi.Supported = false;
                    fi.Reason = "combined or calculated field — read only";
                }
                else
                {
                    fi.Supported = true;
                }
                Fields.Add(fi);
                idx++;
            }

            if (Fields.Count == 0)
            {
                Error = "This schedule has no visible fields.";
                return;
            }

            // elements -----------------------------------------------------------
            List<Element> elements;
            try
            {
                elements = new List<Element>(new FilteredElementCollector(doc, sched.Id).ToElements());
            }
            catch (Exception)
            {
                elements = new List<Element>();
            }

            List<Element> clean = new List<Element>();
            foreach (Element e in elements)
            {
                try
                {
                    if (e == null || !Efr.IsValidId(e.Id)) continue;
                    if (Efr.EidValue(e.Id) == Efr.EidValue(sched.Id)) continue;
                }
                catch (Exception)
                {
                    continue;
                }
                clean.Add(e);
            }

            // which columns show an element's Workset, and what it can be set to
            long? part = Efr.PartitionParamId();
            WorksetFields = new HashSet<int>();
            foreach (FieldInfo fi in Fields)
            {
                if (part != null && fi.ParamId != null && Efr.EidValue(fi.ParamId) == part.Value)
                    WorksetFields.Add(fi.Index);
            }
            if (WorksetFields.Count > 0)
                Worksets = Efr.ReadWorksets(doc);

            Dictionary<long, ParamView> typeMaps = new Dictionary<long, ParamView>();
            ParamSource noParams = new DictParamSource(new Dictionary<long, Parameter>());
            ParamLookup lookup = new ParamLookup();
            Lookup = lookup;
            foreach (Element e in clean)
            {
                RowInfo row = new RowInfo();
                row.ElemId = e.Id;
                ParamView imapView = lookup.View(e);
                ParamSource imap = imapView;

                ElementId tid = null;
                try
                {
                    tid = e.GetTypeId();
                }
                catch (Exception)
                {
                    tid = null;
                }
                Element telem;
                if (Efr.IsValidId(tid))
                {
                    telem = doc.GetElement(tid);
                }
                else
                {
                    telem = e as ElementType;
                    tid = telem != null ? telem.Id : null;
                }
                row.TypeId = tid;

                if (tid != null && !typeMaps.ContainsKey(Efr.EidValue(tid)))
                    typeMaps[Efr.EidValue(tid)] = lookup.View(telem);
                ParamSource tmap = noParams;
                if (tid != null)
                {
                    ParamView tview;
                    if (typeMaps.TryGetValue(Efr.EidValue(tid), out tview))
                        tmap = tview;
                }

                foreach (FieldInfo fi in Fields)
                {
                    CellInfo ci = new CellInfo();
                    ci.IsType = fi.IsType;
                    ci.ParamId = fi.ParamId;
                    if (!fi.Supported)
                    {
                        ci.Editable = false;
                        ci.Reason = fi.Reason;
                        if (fi.Combined != null && fi.Combined.Count > 0)
                            ci.Original = Efr.CombinedValue(doc, fi.Combined, imap, tmap);
                        row.Cells.Add(ci);
                        continue;
                    }
                    long pid = Efr.EidValue(fi.ParamId);
                    Parameter p;
                    if (fi.IsType)
                    {
                        ci.TargetId = tid;
                        p = tmap.Get(pid);
                    }
                    else
                    {
                        ci.TargetId = e.Id;
                        p = imap.Get(pid);
                        if (p == null)
                        {
                            p = tmap.Get(pid);
                            if (p != null)
                            {
                                ci.TargetId = tid;
                                ci.IsType = true;
                            }
                        }
                    }
                    if (p == null)
                    {
                        ci.Editable = false;
                        ci.Reason = "parameter not present on this element";
                        ci.Original = "";
                    }
                    else
                    {
                        ci.Original = Efr.ReadParam(doc, p);
                        bool readOnly;
                        try
                        {
                            readOnly = p.IsReadOnly;
                        }
                        catch (Exception)
                        {
                            readOnly = true;
                        }
                        if (readOnly)
                            ci.Reason = "read only in the model";
                        else if (p.StorageType == StorageType.ElementId)
                            ci.Reason = "element-valued parameter — read only in v1.0.0";
                        else if (WorksetFields.Contains(fi.Index) && Worksets.Count == 0)
                            ci.Reason = "not a workshared model — there are no worksets";
                        else
                            ci.Editable = true;
                    }
                    row.Cells.Add(ci);
                }

                row.SortText = new List<string>();
                foreach (CellInfo c in row.Cells) row.SortText.Add(c.Original);
                Rows.Add(row);
            }

            ApplyScheduleSort(defn);

            int nType = Fields.Count(f => f.IsType);
            Notes.Add(string.Format(CultureInfo.InvariantCulture, "{0} rows, {1} fields ({2} type, {3} instance).",
                Rows.Count, Fields.Count, nType, Fields.Count - nType));
        }

        /// <summary>Order rows the way the schedule orders them, as far as we can.</summary>
        private void ApplyScheduleSort(ScheduleDefinition defn)
        {
            IList<ScheduleSortGroupField> sorts;
            try
            {
                sorts = defn.GetSortGroupFields();
            }
            catch (Exception)
            {
                return;
            }
            if (sorts == null || sorts.Count == 0) return;
            Dictionary<string, int> fidToIndex = new Dictionary<string, int>();
            IList<ScheduleFieldId> order;
            try
            {
                order = defn.GetFieldOrder();
            }
            catch (Exception)
            {
                return;
            }
            int visible = 0;
            foreach (ScheduleFieldId fid in order)
            {
                bool hidden;
                try
                {
                    ScheduleField f = defn.GetField(fid);
                    hidden = f.IsHidden;
                }
                catch (Exception)
                {
                    continue;
                }
                if (hidden) continue;
                fidToIndex[Efr.FieldIdKey(fid)] = visible;
                visible++;
            }
            List<(int Index, bool Desc)> keys = new List<(int Index, bool Desc)>();
            foreach (ScheduleSortGroupField sf in sorts)
            {
                string k;
                try
                {
                    k = Efr.FieldIdKey(sf.FieldId);
                }
                catch (Exception)
                {
                    continue;
                }
                int i;
                if (!fidToIndex.TryGetValue(k, out i)) continue;
                bool desc = false;
                try
                {
                    desc = (sf.SortOrder == ScheduleSortOrder.Descending);
                }
                catch (Exception)
                {
                    desc = false;
                }
                keys.Add((i, desc));
            }
            if (keys.Count == 0) return;
            // least significant key first, each pass stable (OrderBy is stable, and so is
            // Python's sort with reverse=True), so the first key ends up the primary one
            for (int n = keys.Count - 1; n >= 0; n--)
            {
                int i = keys[n].Index;
                bool desc = keys[n].Desc;
                try
                {
                    List<RowInfo> sorted = desc
                        ? Rows.OrderByDescending(r => Efr.NaturalKey(r.SortText[i])).ToList()
                        : Rows.OrderBy(r => Efr.NaturalKey(r.SortText[i])).ToList();
                    Rows.Clear();
                    Rows.AddRange(sorted);
                }
                catch (Exception) { }
            }
        }

        // -- staged edits -------------------------------------------------------

        /// <summary>
        /// Which staged-edit slot a cell writes to; null when the cell has none.
        /// Asked for every cell on every repaint, so it is worked out once and
        /// kept on the cell (the target and the parameter are fixed at load).
        /// </summary>
        public EditKey KeyOf(RowInfo row, int fieldIndex)
        {
            CellInfo ci = row.Cells[fieldIndex];
            if (ci.Scratch)
            {
                // scratch cells are per row and column, and never reach the model;
                // not cached, because the row number is only fixed per build
                return EditKey.Scratch(row.Ridx, fieldIndex);
            }
            if (!ci.KeyKnown)
            {
                if (ci.TargetId == null || ci.ParamId == null)
                    ci.KeyCache = null;
                else
                    ci.KeyCache = EditKey.Of(Efr.EidValue(ci.TargetId), Efr.EidValue(ci.ParamId));
                ci.KeyKnown = true;
            }
            return ci.KeyCache;
        }

        /// <summary>The dictionary a key's staged text lives in: ScratchValues for test columns, else Edits.</summary>
        public Dictionary<EditKey, string> StoreFor(EditKey key)
        {
            return (key != null && key.IsScratch) ? ScratchValues : Edits;
        }

        /// <summary>The staged text for a cell, else what the model holds.</summary>
        public string CurrentText(RowInfo row, int fieldIndex)
        {
            EditKey key = KeyOf(row, fieldIndex);
            if (key != null)
            {
                Dictionary<EditKey, string> store = StoreFor(key);
                string text;
                if (store.TryGetValue(key, out text))
                    return text;
            }
            return row.Cells[fieldIndex].Original;
        }

        public bool IsEdited(RowInfo row, int fieldIndex)
        {
            EditKey key = KeyOf(row, fieldIndex);
            return key != null && !key.IsScratch && Edits.ContainsKey(key);
        }

        /// <summary>Every row that displays the same (target, parameter) pair.</summary>
        public List<(RowInfo Row, int Field)> RowsSharing(EditKey key)
        {
            List<(RowInfo Row, int Field)> output = new List<(RowInfo Row, int Field)>();
            foreach (RowInfo r in Rows)
            {
                for (int i = 0; i < Fields.Count; i++)
                {
                    EditKey k = KeyOf(r, i);
                    if (k == null ? key == null : k.Equals(key))
                        output.Add((r, i));
                }
            }
            return output;
        }

        // -- writing ------------------------------------------------------------

        /// <summary>Write every staged edit in one transaction. Call it inside Revit's API context.</summary>
        public ApplyResult Apply()
        {
            Document doc = Doc;
            ApplyResult res = new ApplyResult();
            if (Edits.Count == 0 && LevelEdits.Count == 0)
                return res;

            // which rows each edited key touches, for the affected-rows count
            Dictionary<EditKey, List<(RowInfo Row, int Field)>> index = Efr.BuildKeyIndex(this);
            HashSet<RowInfo> touchedRows = new HashSet<RowInfo>();
            Failed = new HashSet<EditKey>();

            // Real ElementId objects kept from the read pass, so nothing has to be rebuilt from an integer.
            Dictionary<long, ElementId> idMap = new Dictionary<long, ElementId>();
            foreach (RowInfo row in Rows)
            {
                foreach (CellInfo ci in row.Cells)
                {
                    if (ci.TargetId != null)
                    {
                        long v = Efr.EidValue(ci.TargetId);
                        if (!idMap.ContainsKey(v)) idMap[v] = ci.TargetId;
                    }
                }
            }

            // Borrow before the transaction opens. CheckoutElements is refused inside one, and the
            // refusal was swallowed, so Set Level, which used to borrow from inside the transaction,
            // borrowed nothing at all on a workshared model. Moving an element to another workset
            // needs the element borrowed just the same.
            long? part = Efr.PartitionParamId();
            List<ElementId> borrow = new List<ElementId>();
            foreach (EditKey key in Edits.Keys)
            {
                ElementId target;
                if (part != null && key.Param == part.Value && idMap.TryGetValue(key.Target, out target))
                    borrow.Add(target);
            }
            foreach (int r in LevelEdits.Keys)
            {
                if (r < Rows.Count)
                    borrow.Add(Rows[r].ElemId);
            }
            if (borrow.Count > 0)
                Efr.CheckoutElements(doc, borrow);

            using (Transaction tx = new Transaction(doc, "Excel for Revit — apply schedule edits"))
            {
            try
            {
                tx.Start();
                try
                {
                    FailureHandlingOptions opts = tx.GetFailureHandlingOptions();
                    opts.SetFailuresPreprocessor(new WarningSwallower());
                    opts.SetClearAfterRollback(true);
                    tx.SetFailureHandlingOptions(opts);
                }
                catch (Exception) { }

                List<EditKey> doneOk = new List<EditKey>();
                foreach (EditKey key in new List<EditKey>(Edits.Keys))
                {
                    string text = Edits[key];
                    long targetInt = key.Target;
                    long paramInt = key.Param;
                    Element elem = null;
                    ElementId targetEid;
                    idMap.TryGetValue(targetInt, out targetEid);
                    try
                    {
                        if (targetEid == null)
                            targetEid = RevoBIM.Helpers.RevitCompat.Id(targetInt);
                        elem = doc.GetElement(targetEid);
                    }
                    catch (Exception)
                    {
                        elem = null;
                    }
                    if (elem == null)
                    {
                        res.Failures.Add(("#" + targetInt.ToString(CultureInfo.InvariantCulture), "", "element no longer in the model"));
                        Failed.Add(key);
                        continue;
                    }
                    Parameter param = null;
                    try
                    {
                        foreach (Parameter p in elem.Parameters)
                        {
                            if (Efr.EidValue(p.Id) == paramInt)
                            {
                                param = p;
                                break;
                            }
                        }
                    }
                    catch (Exception)
                    {
                        param = null;
                    }
                    string nm = Efr.ElemName(elem);
                    string label = (string.IsNullOrEmpty(nm) ? "Element" : nm) + " [" + targetInt.ToString(CultureInfo.InvariantCulture) + "]";
                    string pname = "";
                    try
                    {
                        pname = param != null ? param.Definition.Name : "";
                    }
                    catch (Exception)
                    {
                        pname = "";
                    }
                    bool ok;
                    string msg;
                    if (part != null && paramInt == part.Value)
                        (ok, msg) = Efr.WriteWorkset(param, text, Worksets);
                    else
                        (ok, msg) = Efr.WriteParam(param, text);
                    if (ok)
                    {
                        res.Cells++;
                        doneOk.Add(key);
                        if (elem is ElementType)
                            res.Types++;
                        else
                            res.Instances++;
                        List<(RowInfo Row, int Field)> shared;
                        if (index.TryGetValue(key, out shared))
                        {
                            foreach (var rf in shared) touchedRows.Add(rf.Row);
                        }
                    }
                    else
                    {
                        Failed.Add(key);
                        res.Failures.Add((label, pname, string.IsNullOrEmpty(msg) ? "refused by Revit" : msg));
                    }
                }

                if (LevelEdits.Count > 0)
                    Efr.ApplyLevelEdits(doc, this, res, touchedRows);

                tx.Commit();
                res.RowsAffected = touchedRows.Count;
                foreach (EditKey key in doneOk)
                    Edits.Remove(key);
            }
            catch (Exception ex)
            {
                try
                {
                    if (tx.HasStarted() && !tx.HasEnded())
                        tx.RollBack();
                }
                catch (Exception) { }
                res.Ok = false;
                res.Failures.Add(("Transaction", "", ex.GetType().Name + ": " + ex.Message));
                return res;
            }
            }

            // refresh originals from the model so further edits diff correctly
            try
            {
                RefreshOriginals();
            }
            catch (Exception) { }
            return res;
        }

        public void RefreshOriginals()
        {
            Document doc = Doc;
            if (WorksetFields.Count > 0)
            {
                // a workset renamed or added in Revit while the window is open
                List<(string Name, int Id)> fresh = Efr.ReadWorksets(doc);
                if (fresh != null && fresh.Count > 0)
                    Worksets = fresh;
            }
            Dictionary<long, Dictionary<long, Parameter>> cache = new Dictionary<long, Dictionary<long, Parameter>>();
            foreach (RowInfo row in Rows)
            {
                foreach (CellInfo ci in row.Cells)
                {
                    if (ci.TargetId == null || ci.ParamId == null) continue;
                    long tkey = Efr.EidValue(ci.TargetId);
                    Dictionary<long, Parameter> pmap;
                    if (!cache.TryGetValue(tkey, out pmap))
                    {
                        pmap = ParamMapOf(doc.GetElement(ci.TargetId));
                        cache[tkey] = pmap;
                    }
                    Parameter p;
                    if (pmap.TryGetValue(Efr.EidValue(ci.ParamId), out p) && p != null)
                        ci.Original = Efr.ReadParam(doc, p);
                }
            }
            RefreshCombined(cache);
        }

        /// <summary>
        /// Rebuild combined cells from the model. A combined value is made of other parameters, so
        /// writing to one of them changes it. Re-read after APPLY and Reload, or it would show the
        /// text it had before the edit that changed it.
        /// </summary>
        public void RefreshCombined(Dictionary<long, Dictionary<long, Parameter>> cache = null)
        {
            List<FieldInfo> combined = Fields.Where(fi => fi.Combined != null && fi.Combined.Count > 0).ToList();
            if (combined.Count == 0) return;
            Document doc = Doc;
            if (cache == null) cache = new Dictionary<long, Dictionary<long, Parameter>>();

            Func<ElementId, ParamSource> pmapOf = eid =>
            {
                if (eid == null) return new DictParamSource(new Dictionary<long, Parameter>());
                long key = Efr.EidValue(eid);
                Dictionary<long, Parameter> map;
                if (!cache.TryGetValue(key, out map))
                {
                    map = ParamMapOf(doc.GetElement(eid));
                    cache[key] = map;
                }
                return new DictParamSource(map);
            };

            foreach (RowInfo row in Rows)
            {
                ParamSource imap = pmapOf(row.ElemId);
                ParamSource tmap = pmapOf(row.TypeId);
                foreach (FieldInfo fi in combined)
                {
                    try
                    {
                        row.Cells[fi.Index].Original = Efr.CombinedValue(doc, fi.Combined, imap, tmap);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
            }
        }
    }
}
