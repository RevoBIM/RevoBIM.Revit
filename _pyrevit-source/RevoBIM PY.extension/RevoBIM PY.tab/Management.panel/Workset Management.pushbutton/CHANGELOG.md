# Workset Management - changelog

## 2.3.1
- Manage Worksets shows **Visible in all views** next to Editable - Revit's
  own setting, read from `Workset.IsVisibleByDefault`. Worksets that are off
  read **No** in orange; the column has a tick list, so unticking Yes lists
  just the worksets that are off in all views.

## 2.3.0
- New **Scope Boxes** tab: every scope box in a table with **Used** (Yes / No),
  **Views** (how many views use it), **Levels & grids** (how many levels, grids
  and reference planes use it) and **Used by** (the first few by name; hover
  for the full list). Sort, keyword filters on every heading and tick lists on
  Used and Change, as in Manage Worksets.
- Batch rename scope boxes from the same rename panel (find and replace,
  prefix, suffix, remove characters, case, tidy), on the selected rows or
  every row shown, or rename in place.
- Delete several scope boxes at once. Staged in red; **Apply scope box
  changes** lists what it will do - including which deletes are in use - and
  writes deletes then renames as one undo step, so a name freed by a delete
  can be reused in the same Apply. The scope boxes, and for a delete every
  view and datum using it, are borrowed first; anything someone else holds is
  named. Results are read back.
- The easter egg now counts clicks on the logo only; the shared hook's attach
  armed the whole window.
- The staged-table machinery is now a reusable module (`wsm_table.py`).

## 2.2.0
- **Modeless**: the window floats in front of Revit and Revit stays fully
  usable - pan, orbit and select with the tool open. Every read and write now
  goes to Revit through one ExternalEvent queue (waits behind a Pending
  request, drops only a refused one, 30s watchdog). Pressing the ribbon button
  again brings the open window forward. If a floating window ever fails to
  respond, the next launch offers to open it as a dialog instead.
- **Show in 3D** opens a 3D view named **Workset Management** (made the first
  time, reused after): no view template, section box off, Coordination
  discipline, Fine detail, shaded with edges, every model category and every
  workset visible, RVT links, CAD links and point clouds hidden. Every element
  is given a solid colour for its workset. Press it again to refresh.
- **Colour swatches** beside every workset in the table and in the assigner
  match the colours in the view. Colours are fixed per workset (ordered by
  workset id), so adding a workset never repaints the others.
- **Isolate selected** temporarily isolates the selected worksets' elements in
  the Workset Management view; **Un-isolate** shows everything again. The
  isolate is reset in its own transaction first, so an earlier one never
  shows through. Closing the window un-isolates.
- **Merge**: select two or more worksets, press Merge and choose the master.
  The others are staged in red to move their elements onto the master and go;
  Apply writes it like any other change (checked out first, one undo step,
  read back). A rename staged on the master is kept.

## 2.1.0
- Manage Worksets gains a **Categories** column: the biggest few categories on
  each workset with their counts (`Pipes 120 · Pipe Fittings 80 · +4 more`).
- A **▸ expander** at the start of each row opens the full breakdown
  underneath it: every category on the workset with its element count and a
  bar against the biggest. The ▸ in the heading opens or closes every row
  shown.
- The breakdown counts every element on the workset, whatever its category, so
  it always adds up to the Elements column; anything without a category is
  listed as `(no category)`.
- The Categories filter finds worksets holding a category (`cable tray`), with
  `-word` to leave out worksets holding one. Sorting the column orders worksets
  by how many categories they carry.
- The table now uses standard rather than recycling virtualisation, so an open
  breakdown can never be handed to another workset's row.

## 2.0.0
- Split into two tabs: **Manage Worksets** and **Workset Assigner**.
- Manage Worksets is a table of every workset: Workset, Elements, Editable,
  Owner and Change columns. Click a heading to sort (natural order, so
  "Level 2" sits before "Level 10"); Shift+click adds a second and third
  level. Every heading has a filter box - the Elements box takes `>0`, `=0`,
  `<=50`, `10-100` - and Editable, Owner and Change also have an Excel-style
  tick list. F5 re-takes the sort and filters; nothing moves while you type.
- Rename in place (double-click a name), or in bulk from the Rename panel:
  find and replace (match case optional), prefix, suffix, remove characters
  from the start or end, UPPER / lower / Title case, tidy spaces. A live
  preview shows old and new names; the panel works on the selected rows, or on
  every row shown when nothing is selected.
- Delete several worksets at once. A dialog asks for one workset to take all of
  their elements; deleting always moves elements, never deletes them.
- New workset button (Ctrl+N) adds a row to name inline.
- Everything is staged in red and written only by **Apply workset changes**,
  which lists what it will do first. Creates and renames run in one
  transaction, each delete in its own, all inside one group: one undo step,
  and one refused delete does not lose the rest. Results are read back from
  the model, not assumed.
- **Make worksets editable automatically** (on by default): worksets are
  checked out before a rename or delete, and elements are borrowed before the
  assigner moves them. A **Make editable** button checks the selected worksets
  out on demand. Anything owned by someone else is reported with their name.
- The active workset is moved to the target first when it is being deleted.
- Excel round trip moved to the Manage tab; the export now carries element
  counts. Imported changes land in the table in red alongside any other staged
  edits.
- Assigner now borrows elements before writing, reads every element back after
  the transaction, and reports who holds anything it could not move.
- House theme: Auto / Dark / Light chip top right, Auto following Revit's
  canvas theme; full screen (button, F11, double-click the header); eight
  resize grips; window size remembered; easter egg on the logo.
- Thin staged loader: a failure names the stage it happened at instead of
  leaving a blank window. `import_check.py` (19 rules, `--selftest`) and
  `bench_logic.py` ship with the tool.
- The panel `bundle.yaml` is no longer shipped - the Management panel already
  exists.

## 1.0.0
- First release: Excel round-trip workset creation and rename; category to
  workset assignment with Cable Tray Service Type sub groups; saved routines.
