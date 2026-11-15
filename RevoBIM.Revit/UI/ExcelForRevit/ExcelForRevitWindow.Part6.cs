// Excel for Revit: the main window, part 6 (port of efr_core.py lines 9355-10044):
// toolbar actions that reach into Revit (isolate, find in view, level staging), the formula context,
// undo / redo / revert, autofit, reload, APPLY, closing, the run-in-Revit queue and Show().
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.ExcelForRevit;
using static RevoBIM.Tools.ExcelForRevit.Efr;
using static RevoBIM.UI.ExcelForRevit.EfrUi;
using Document = Autodesk.Revit.DB.Document;
using FieldInfo = RevoBIM.Tools.ExcelForRevit.FieldInfo;

namespace RevoBIM.UI.ExcelForRevit
{
    public partial class ExcelForRevitWindow
    {
        // -- toolbar ------------------------------------------------------------

        /// <summary>Distinct row indexes covered by the selection, in view order.</summary>
        public List<int> SelectedRows()
        {
            var seen = new List<int>();
            foreach (SelCell c in SelCells())
            {
                if (!seen.Contains(c.Ridx))
                    seen.Add(c.Ridx);
            }
            return seen;
        }

        /// <summary>The level the element currently sits on (its element id value), or null.</summary>
        public long? LevelOfRow(int ridx)
        {
            try
            {
                Element elem = Doc.GetElement(Model.Rows[ridx].ElemId);
                Parameter param = LevelParamOf(elem);
                if (param == null)
                    return null;
                return EidValue(param.AsElementId());
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static string Pl6(int n)
        {
            return n == 1 ? "" : "s";
        }

        /// <summary>What the isolate job reports back to the window.</summary>
        private sealed class IsolateOutcome
        {
            public string State;
            public string ViewName;
            public bool Boxed;
        }

        /// <summary>The element ids of the given rows (rows that cannot be read are skipped).</summary>
        private List<ElementId> IdsOfRows(List<int> rows)
        {
            var ids = new List<ElementId>();
            foreach (int ridx in rows)
            {
                try
                {
                    ids.Add(Model.Rows[ridx].ElemId);
                }
                catch (Exception)
                {
                    continue;
                }
            }
            return ids;
        }

        /// <summary>
        /// Open the default 3D view and isolate the picked rows' elements.
        ///
        /// Temporary isolation, the same as Revit's own: it leaves the view's real visibility alone and
        /// goes away with Reset. The section box is kept on and kept visible, which means putting it in
        /// the isolated set: temporary isolation hides everything that is not in it, the section box
        /// element included, so the box would vanish while still cropping the view.
        /// </summary>
        public void OnIsolateSelected(object sender = null, EventArgs args = null)
        {
            List<int> rows = SelectedRows();
            if (rows.Count == 0)
            {
                SetStatus("Select cells on the rows you want to isolate first.");
                return;
            }
            List<ElementId> ids = IdsOfRows(rows);
            if (ids.Count == 0)
            {
                SetStatus("Nothing to isolate.");
                return;
            }

            Func<UIApplication, object> job = uiapp =>
            {
                Document doc = Doc;
                View3D view = Best3dView(doc);
                if (view == null)
                    return new IsolateOutcome { State = "noview" };
                try
                {
                    if (EidValue(Uidoc.ActiveView.Id) != EidValue(view.Id))
                    {
                        // the active view cannot be changed inside a transaction
                        Uidoc.ActiveView = view;
                    }
                }
                catch (Exception)
                {
                }

                var bag = new List<ElementId>(ids);
                bool boxed = false;
                try
                {
                    if (view.IsSectionBoxActive)
                    {
                        boxed = true;
                        foreach (Element box in new FilteredElementCollector(doc, view.Id)
                                     .OfCategory(BuiltInCategory.OST_SectionBox)
                                     .WhereElementIsNotElementType())
                            bag.Add(box.Id);
                    }
                }
                catch (Exception)
                {
                }

                using (var tx = new Transaction(doc, "Excel for Revit - isolate selected"))
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
                        catch (Exception)
                        {
                        }
                        view.IsolateElementsTemporary(bag);
                        tx.Commit();
                    }
                    catch (Exception)
                    {
                        try
                        {
                            tx.RollBack();
                        }
                        catch (Exception)
                        {
                        }
                        return new IsolateOutcome { State = "refused" };
                    }
                }
                try
                {
                    Uidoc.Selection.SetElementIds(bag);
                }
                catch (Exception)
                {
                }
                try
                {
                    // a view changed from a modeless window does not redraw itself
                    Uidoc.RefreshActiveView();
                }
                catch (Exception)
                {
                }
                return new IsolateOutcome { State = "done", ViewName = ElemName(view), Boxed = boxed };
            };

            int n = ids.Count;
            SetStatus(string.Format(CultureInfo.InvariantCulture, "Isolating {0} element{1}...", n, Pl6(n)));

            RunInRevit(job, outcomeObj =>
            {
                var outcome = outcomeObj as IsolateOutcome;
                string state = outcome != null ? outcome.State : "busy";
                if (state == "done")
                {
                    SetStatus(string.Format(CultureInfo.InvariantCulture,
                        "Isolated {0} element{1} in {2}.{3} Reset Temporary Hide/Isolate in Revit to put it back.",
                        n, Pl6(n), outcome.ViewName,
                        outcome.Boxed ? " The section box is still on, so anything outside it stays hidden." : ""));
                }
                else if (state == "noview")
                {
                    SetStatus("This project has no 3D view to isolate in.");
                }
                else if (state == "refused")
                {
                    SetStatus("Revit would not isolate those elements.");
                }
                else
                {
                    SetStatus("Revit would not take the request.");
                }
            });
        }

        /// <summary>
        /// Select the rows' elements in Revit and show them in a view.
        ///
        /// ShowElements is what Revit's own "Show" does from a warning dialog: it finds a view the
        /// elements appear in, opens it if needed, and zooms to them. Selecting them first is what
        /// leaves them highlighted once it has finished.
        /// </summary>
        public void OnFindInView(object sender = null, EventArgs args = null)
        {
            List<int> rows = SelectedRows();
            if (rows.Count == 0)
            {
                SetStatus("Select cells on the rows you want to find first.");
                return;
            }
            List<ElementId> ids = IdsOfRows(rows);
            if (ids.Count == 0)
            {
                SetStatus("Nothing to find.");
                return;
            }

            Func<UIApplication, object> job = uiapp =>
            {
                var bag = new List<ElementId>(ids);
                try
                {
                    Uidoc.Selection.SetElementIds(bag);
                }
                catch (Exception)
                {
                }
                try
                {
                    Uidoc.ShowElements(bag);
                    return "shown";
                }
                catch (Exception)
                {
                    // ShowElements raises when no open-able view contains them: the selection
                    // still stands, which is half the job
                    return "selected";
                }
            };

            int n = ids.Count;
            SetStatus(string.Format(CultureInfo.InvariantCulture, "Finding {0} element{1}...", n, Pl6(n)));
            RunInRevit(job, outcome =>
            {
                string state = outcome as string;
                if (state == "shown")
                {
                    SetStatus(string.Format(CultureInfo.InvariantCulture, "Found {0} element{1} in Revit.", n, Pl6(n)));
                }
                else if (state == "selected")
                {
                    SetStatus(string.Format(CultureInfo.InvariantCulture,
                        "Selected {0} element{1}, but no open view shows {2}.", n, Pl6(n), n == 1 ? "it" : "them"));
                }
                else
                {
                    SetStatus("Revit would not take the request.");
                }
            });
        }

        public void OnSetLevel(object sender = null, EventArgs args = null)
        {
            try
            {
                SetLevelDialog(this);
            }
            catch (Exception ex)
            {
                ThemedMessage("Set Level",
                    "Set Level could not be opened:\n\n" + ex,
                    Window, C_RED, 680);
            }
        }

        /// <summary>Stage a level change per row. Nothing touches the model until APPLY.</summary>
        public int StageLevels(IEnumerable<int> rows, Level level)
        {
            ElementId levelId = level.Id;
            string name = ElemName(level);
            if (string.IsNullOrEmpty(name))
                name = "Level";
            int n = 0;
            foreach (int ridx in rows)
            {
                Model.LevelEdits[ridx] = (levelId, name);
                n++;
            }
            UpdatePending();
            RepaintSoon();
            return n;
        }

        public int ClearLevelEdits()
        {
            int n = Model.LevelEdits.Count;
            Model.LevelEdits = new Dictionary<int, (ElementId LevelId, string LevelName)>();
            UpdatePending();
            RepaintSoon();
            return n;
        }

        /// <summary>What a formula can see for one target cell.</summary>
        public IFormulaContext FormulaContext(SelCell cell, int n)
        {
            ScheduleModel model = Model;
            RowInfo row = model.Rows[cell.Ridx];
            var cells = new Dictionary<string, string>();
            foreach (FieldInfo fi in model.Fields)
                cells[fi.Letter] = model.CurrentText(row, fi.Index);

            Func<string, int, string> lookup = (column, number) =>
            {
                int index = number - 1;
                if (index < 0 || index >= model.Rows.Count)
                    return null;
                RowInfo target = model.Rows[index];
                foreach (FieldInfo f in model.Fields)
                {
                    if (f.Letter == column)
                        return model.CurrentText(target, f.Index);
                }
                return null;
            };

            return new RevoBIM.Tools.ExcelForRevit.FormulaContext
            {
                Cells = cells,
                Row = row.Ridx + 1,
                Anchor = FormulaCells.Count > 0 ? FormulaCells[0].Ridx + 1 : row.Ridx + 1,
                N = n,
                Id = ToText(EidValue(row.ElemId)),
                This = model.CurrentText(row, cell.Fidx),
                Lookup = lookup,
            };
        }

        public void OnSequence(object sender = null, EventArgs args = null)
        {
            try
            {
                SequenceDialog(this);
            }
            catch (Exception)
            {
                SetStatus("The sequence tool could not be opened.");
            }
        }

        public void OnAffix(object sender = null, EventArgs args = null)
        {
            try
            {
                AffixDialog(this);
            }
            catch (Exception)
            {
                SetStatus("The prefix tool could not be opened.");
            }
        }

        public void OnFind(object sender = null, EventArgs args = null)
        {
            try
            {
                if (Finder == null)
                {
                    Finder = new FindReplace(this);
                    Finder.Dlg.Window.Closed += FinderClosed;
                }
                Finder.Show();
                Finder.Dlg.Window.Activate();
            }
            catch (Exception)
            {
                Finder = null;
                SetStatus("Could not open Find and Replace.");
            }
        }

        public void FinderClosed(object sender, EventArgs args)
        {
            Finder = null;
        }

        public void OnUndo(object sender = null, EventArgs args = null)
        {
            if (UndoStack.Count == 0)
            {
                SetStatus("Nothing to undo.");
                return;
            }
            Dictionary<EditKey, object> batch = UndoStack[UndoStack.Count - 1];
            UndoStack.RemoveAt(UndoStack.Count - 1);
            var redo = new Dictionary<EditKey, object>();
            foreach (KeyValuePair<EditKey, object> entry in batch)
            {
                EditKey key = entry.Key;
                object old = entry.Value;
                Dictionary<EditKey, string> store = Model.StoreFor(key);
                string current;
                redo[key] = store.TryGetValue(key, out current) ? (object)current : Absent;
                if (ReferenceEquals(old, Absent))
                    store.Remove(key);
                else
                    store[key] = (string)old;
                PushToTable(key);
            }
            RedoStack.Add(redo);
            UpdatePending();
            RepaintSoon();
            SetStatus(string.Format(CultureInfo.InvariantCulture, "Undid {0} cell change{1}.", batch.Count, Pl6(batch.Count)));
        }

        public void OnRedo(object sender = null, EventArgs args = null)
        {
            if (RedoStack.Count == 0)
            {
                SetStatus("Nothing to redo.");
                return;
            }
            Dictionary<EditKey, object> batch = RedoStack[RedoStack.Count - 1];
            RedoStack.RemoveAt(RedoStack.Count - 1);
            var undo = new Dictionary<EditKey, object>();
            foreach (KeyValuePair<EditKey, object> entry in batch)
            {
                EditKey key = entry.Key;
                object next = entry.Value;
                Dictionary<EditKey, string> store = Model.StoreFor(key);
                string current;
                undo[key] = store.TryGetValue(key, out current) ? (object)current : Absent;
                if (ReferenceEquals(next, Absent))
                    store.Remove(key);
                else
                    store[key] = (string)next;
                PushToTable(key);
            }
            UndoStack.Add(undo);
            UpdatePending();
            RepaintSoon();
            SetStatus(string.Format(CultureInfo.InvariantCulture, "Redid {0} cell change{1}.", batch.Count, Pl6(batch.Count)));
        }

        public void OnRevertSelected(object sender = null, EventArgs args = null)
        {
            List<SelCell> cells = SelCells();
            if (cells.Count == 0)
                return;
            BeginBatch();
            int n = 0;
            foreach (SelCell c in cells)
            {
                RowInfo row = Model.Rows[c.Ridx];
                if (Stage(c.Ridx, c.Fidx, row.Cells[c.Fidx].Original))
                    n++;
            }
            EndBatch();
            SetStatus(string.Format(CultureInfo.InvariantCulture, "Reverted {0} cell{1}.", n, Pl6(n)));
        }

        public void OnRevertAll(object sender = null, EventArgs args = null)
        {
            int levels = ClearLevelEdits();
            if (Model.Edits.Count == 0)
            {
                SetStatus(levels != 0
                    ? string.Format(CultureInfo.InvariantCulture, "Dropped {0} level change{1}.", levels, Pl6(levels))
                    : "There is nothing to revert.");
                return;
            }
            int n = Model.Edits.Count;
            BeginBatch();
            foreach (EditKey key in new List<EditKey>(Model.Edits.Keys))
            {
                if (_batch != null)
                {
                    string prior;
                    _batch[key] = Model.Edits.TryGetValue(key, out prior) ? (object)prior : Absent;
                }
                Model.Edits.Remove(key);
                PushToTable(key);
            }
            EndBatch();
            SetStatus(string.Format(CultureInfo.InvariantCulture, "Reverted all {0} pending edit{1}.", n, Pl6(n)));
        }

        /// <summary>
        /// Size every value column to its content, then freeze it in pixels.
        ///
        /// Two steps rather than just leaving the columns on Auto. Auto keeps re-measuring as new rows
        /// are realised while scrolling, so columns visibly jump about halfway down a long schedule; and
        /// Auto has no ceiling, so one long comments field can push everything else off the edge.
        /// Measuring once and then writing the result back as pixels gives a stable layout with a floor
        /// and a ceiling. The floor is not cosmetic: each header carries a filter box and a caret, so a
        /// column narrower than that clips its own controls.
        /// </summary>
        public void Autofit(bool announce = true)
        {
            var cols = new List<DataGridColumn>(FieldCols);
            if (cols.Count == 0)
                return;
            foreach (DataGridColumn col in cols)
            {
                try
                {
                    col.Width = new DataGridLength(1, DataGridLengthUnitType.Auto);
                }
                catch (Exception)
                {
                }
            }

            Action freeze = () =>
            {
                foreach (DataGridColumn col in cols)
                {
                    double width;
                    try
                    {
                        width = col.ActualWidth;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    if (width <= 0)
                        continue;
                    width = Math.Max(AUTOFIT_MIN, Math.Min(AUTOFIT_MAX, width + AUTOFIT_PAD));
                    try
                    {
                        col.Width = new DataGridLength(width, DataGridLengthUnitType.Pixel);
                    }
                    catch (Exception)
                    {
                    }
                }
                PlaceHandle();
                AlignGroupBar();
                RepaintSoon();
                if (announce)
                    SetStatus("Columns fitted to their content.");
            };

            // measurement is only meaningful once the rows have been laid out
            try
            {
                Window.Dispatcher.BeginInvoke(DispatcherPriority.Loaded, freeze);
            }
            catch (Exception)
            {
                freeze();
            }
        }

        public void OnAutofit(object sender = null, EventArgs args = null)
        {
            Autofit();
        }

        public void OnSizeChanged(object sender = null, EventArgs args = null)
        {
            if (Drawer != null && (Drawer.Shrunk || Drawer.Busy))
            {
                // the body is pinned for the slide, so there is nothing to reflow
                // and twenty toolbar relayouts a second is what makes it stutter
                return;
            }
            ReflowToolbar();
            PlaceHandle();
        }

        /// <summary>
        /// Fit the columns once, the first time the grid is actually drawn. ContentRendered rather than
        /// Loaded: the row containers do not exist until the grid has been through a layout pass, and
        /// measuring before that fits every column to its header alone.
        /// </summary>
        public void OnFirstRender(object sender = null, EventArgs args = null)
        {
            if (_firstRenderDone)
                return;
            _firstRenderDone = true;
            Autofit(false);
            AlignGroupBar();
        }

        public void OnReload(object sender = null, EventArgs args = null)
        {
            if (Model.Edits.Count > 0 || Model.LevelEdits.Count > 0)
            {
                var dlg = new ThemedDialog("Reload from model", 520, null, Window, C_RED);
                int pending = Model.Edits.Count + Model.LevelEdits.Count;
                dlg.Add(Tb(string.Format(CultureInfo.InvariantCulture, "Reloading discards {0} pending edit{1}.",
                    pending, Pl6(pending)), C_TEXT, 12, false, true));
                dlg.AddButton("Cancel", "ghost", null);
                dlg.AddButton("Discard and reload", "red", "go");
                if ((dlg.Show() as string) != "go")
                    return;
            }
            Model.Edits.Clear();
            Model.Failed.Clear();
            Model.LevelEdits = new Dictionary<int, (ElementId LevelId, string LevelName)>();
            Imported.Clear();
            UndoStack.Clear();
            RedoStack.Clear();
            try
            {
                Model.RefreshOriginals();
                foreach (RowInfo row in Model.Rows)
                {
                    foreach (FieldInfo fi in Model.Fields)
                        Table.Rows[row.Ridx][fi.Col] = Model.CurrentText(row, fi.Index);
                }
            }
            catch (Exception)
            {
            }
            // the sort, the grouping and the filters are all snapshots taken from
            // values that have just changed, so they are taken again rather than
            // left pointing at the old ones, and the sort survives a reload
            ApplyFilters();
            ApplySort();
            UpdatePending();
            RepaintSoon();
            SetStatus("Reloaded from the model.");
        }

        public void OnClearFilters(object sender = null, EventArgs args = null)
        {
            ClearAllFilters();
            SetStatus("All column filters cleared.");
        }

        // -- apply and close ----------------------------------------------------

        public void OnApply(object sender = null, EventArgs args = null)
        {
            OnApply(sender, args, null);
        }

        /// <summary>
        /// Queue the write. <paramref name="then"/> is called with true when it all went in.
        /// The work happens in Revit's own callback, so everything that follows it lives in
        /// ApplyFinished rather than after the call.
        /// </summary>
        public void OnApply(object sender, EventArgs args, Action<bool> then)
        {
            if (Model.Edits.Count == 0 && Model.LevelEdits.Count == 0)
            {
                SetStatus("There are no pending edits to apply.");
                if (then != null)
                    then(true);
                return;
            }
            if (Applying)
            {
                SetStatus("Already applying — one moment.");
                return;
            }
            int staged = Model.Edits.Count;
            Applying = true;
            try
            {
                BtnApply.IsEnabled = false;
            }
            catch (Exception)
            {
            }
            SetStatus(string.Format(CultureInfo.InvariantCulture, "Applying {0} edit{1}...", staged, Pl6(staged)));
            RunInRevit(uiapp => Model.Apply(),
                res => ApplyFinished(res as ApplyResult, staged, then));
        }

        public void ApplyFinished(ApplyResult res, int staged, Action<bool> then = null)
        {
            Applying = false;
            if (res == null)
            {
                SetStatus("Revit would not take the write — nothing was applied, and the edits are still staged.");
                UpdatePending();
                if (then != null)
                    then(false);
                return;
            }
            Model.LevelEdits = new Dictionary<int, (ElementId LevelId, string LevelName)>();
            Imported.Clear();
            UndoStack.Clear();
            RedoStack.Clear();
            try
            {
                foreach (RowInfo row in Model.Rows)
                {
                    foreach (FieldInfo fi in Model.Fields)
                        Table.Rows[row.Ridx][fi.Col] = Model.CurrentText(row, fi.Index);
                }
            }
            catch (Exception)
            {
            }
            UpdatePending();
            RepaintSoon();
            ShowResults(Window, res, staged);
            int elements = res.Instances + res.Types + res.Levels;
            SetStatus(string.Format(CultureInfo.InvariantCulture,
                "Applied — {0} element{1} changed. The window is still open for more edits.",
                elements, Pl6(elements)));
            if (then != null)
                then(res.Failures.Count == 0);
        }

        /// <summary>Switch between the modal and the modeless window, next time it runs.</summary>
        public void OnToggleModeless(object sender = null, EventArgs args = null)
        {
            bool now = GetBool(LoadSettings(), "modeless", true);
            var dlg = new ThemedDialog("Window behaviour", 600, null, Window, C_ORANGE);
            dlg.Add(Tb(string.Format("This window is currently {0}.",
                now ? "modeless — Revit stays usable while it is open"
                    : "modal — Revit is blocked while it is open"),
                C_TEXT, 13, true, true));
            // the pyRevit note about the persistent engine is not carried over: it does not apply here
            TextBlock note = Tb("Modeless lets you keep working in Revit while the schedule is open. " +
                                "Modal blocks Revit until the window is closed.\n\n" +
                                "The change takes effect the next time the tool is opened.",
                C_MUTED, 12, false, true);
            note.Margin = new Thickness(0, 10, 0, 0);
            dlg.Add(note);
            dlg.AddButton("Cancel", "ghost", null);
            dlg.AddButton(now ? "Use modal (Revit blocked)" : "Use modeless (Revit usable)", "green", "switch");
            if ((dlg.Show() as string) != "switch")
                return;
            SaveSetting("modeless", !now);
            SetStatus(string.Format("Saved — the window will be {0} next time it is opened.",
                now ? "modal" : "modeless"));
        }

        public void OnCloseClick(object sender = null, EventArgs args = null)
        {
            Window.Close();
        }

        public void OnClosing(object sender, CancelEventArgs args)
        {
            int pending = Model.Edits.Count + Model.LevelEdits.Count;
            if (_closingOk || pending == 0)
            {
                Shutdown();
                return;
            }
            args.Cancel = true;
            string choice = AskExit(Window, pending);
            if (choice == "apply")
            {
                Action<bool> after = ok =>
                {
                    if (Model.Edits.Count > 0 || Model.LevelEdits.Count > 0)
                    {
                        SetStatus("Some edits could not be applied — the window stayed open.");
                        return;
                    }
                    _closingOk = true;
                    Window.Close();
                };
                // the write happens in Revit's callback, so the close waits for it
                OnApply(null, null, after);
            }
            else if (choice == "discard")
            {
                _closingOk = true;
                Window.Close();
            }
        }

        /// <summary>
        /// Queue work for Revit and return at once.
        ///
        /// You cannot wait for an ExternalEvent from the window. Revit raises it on the same thread the
        /// window lives on, so blocking that thread to wait for the answer is a deadlock: the handler
        /// never gets a turn. So the job is queued and this returns immediately; whatever it produces
        /// comes back through <paramref name="done"/>, marshalled onto the dispatcher so it can touch
        /// the window safely. When the window is modal the command is still inside Revit's API context,
        /// so the job just runs here.
        /// </summary>
        public void RunInRevit(Func<UIApplication, object> job, Action<object> done = null)
        {
            if (!Modeless || Handler == null || Event == null)
            {
                // modal: the command is still inside Revit's API context, so the
                // work can simply be done here
                object outcome = null;
                try
                {
                    outcome = job(null);
                }
                catch (Exception ex)
                {
                    ThemedMessage("Excel for Revit", ex.ToString(), Window, C_RED, 700);
                }
                if (done != null)
                    done(outcome);
                return;
            }

            Action<UIApplication> wrapped = uiapp =>
            {
                object value = null;
                string error = null;
                try
                {
                    value = job(uiapp);
                }
                catch (Exception ex)
                {
                    error = ex.ToString();
                }

                Action back = () =>
                {
                    if (!string.IsNullOrEmpty(error))
                        ThemedMessage("Excel for Revit", error, Window, C_RED, 700);
                    else if (done != null)
                        done(value);
                };
                try
                {
                    Window.Dispatcher.BeginInvoke(DispatcherPriority.Background, back);
                }
                catch (Exception)
                {
                }
            };

            Handler.Job = wrapped;
            try
            {
                Event.Raise();
            }
            catch (Exception)
            {
                if (done != null)
                    done(null);
            }
        }

        public void Shutdown()
        {
            Live = null;
            try
            {
                if (Finder != null)
                    Finder.Dlg.Window.Close();
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Wire the shared RevoBIM easter egg to the logo: three slow clicks on the wordmark open the
        /// mini game launcher. Anything going wrong here is swallowed, because a decoration must never
        /// be able to stop a schedule being edited. <paramref name="f"/> finds an element by its x:Name
        /// (null: Window.FindName).
        /// </summary>
        public void AttachEgg(Func<string, object> f = null)
        {
            try
            {
                var targets = new List<UIElement>();
                foreach (string name in new[] { "LogoText", "IconImage" })
                {
                    try
                    {
                        object element = f != null ? f(name) : Window.FindName(name);
                        UIElement ui = element as UIElement;
                        if (ui != null)
                            targets.Add(ui);
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                }
                if (targets.Count == 0)
                    return;
                EggHook.Attach(Window, () => ThemeName(), targets.ToArray());
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Revit's main window handle (what a modeless window must be owned to), or IntPtr.Zero.</summary>
        private static IntPtr RevitWindowHandle()
        {
            try
            {
                IntPtr handle = Autodesk.Windows.ComponentManager.ApplicationWindow;
                if (handle != IntPtr.Zero)
                    return handle;
            }
            catch (Exception)
            {
            }
            // Revit's own process window is the same owner by another route
            try
            {
                return Process.GetCurrentProcess().MainWindowHandle;
            }
            catch (Exception)
            {
                return IntPtr.Zero;
            }
        }

        /// <summary>
        /// Modal by default; modeless when the setting asks for it. Modeless is owned to Revit's main
        /// window, or an unowned modeless window slips behind Revit and reads as a crash, and parked in
        /// <see cref="Live"/> as well so nothing can collect it.
        /// </summary>
        public void Show()
        {
            if (!Modeless)
            {
                // owned to Revit as well (the Python left the modal window unowned), so it stays in front of it
                try
                {
                    IntPtr modalOwner = RevitWindowHandle();
                    if (modalOwner != IntPtr.Zero)
                        new WindowInteropHelper(Window) { Owner = modalOwner };
                }
                catch (Exception)
                {
                }
                Window.ShowDialog();
                return;
            }
            // Owned is what keeps it in front of Revit; unowned, a click in the model sends it behind
            // Revit and it reads as a crash.
            try
            {
                IntPtr owner = RevitWindowHandle();
                if (owner != IntPtr.Zero)
                    new WindowInteropHelper(Window) { Owner = owner };
            }
            catch (Exception)
            {
            }
            try
            {
                // A modeless WPF window inside a host with its own message loop needs its keystrokes
                // routed to it, or typing in a cell can be taken by Revit's shortcuts instead.
                System.Windows.Forms.Integration.ElementHost.EnableModelessKeyboardInterop(Window);
            }
            catch (Exception)
            {
            }
            Live = this;
            // not ported: the modeless_pending health record (it only fed the removed engine check)
            Window.Show();
            try
            {
                Window.Activate();
            }
            catch (Exception)
            {
            }
            _shown = true;
        }
    }
}
