# Excel for Revit — changelog

## 1.20.0

### Workset dropdown

When the schedule includes **Workset**, its cells are chosen from a list of the
model's worksets instead of typed.

- **Open the list** by clicking a Workset cell that is already selected,
  double-clicking it, pressing **F2**, or starting to type on it (what you type
  goes into the list's search box). Right-click → **Set Workset...** does the
  same.
- **Several rows at once:** select Workset cells on as many rows as you like —
  drag, Shift-click, Ctrl-click — then click inside the selection. The
  selection is kept and the list opens; your choice is staged on every one.
  Read-only cells in the selection are left out.
- The list opens under the cell (above it near the bottom of the screen), has a
  search box, shows the current workset highlighted when all the chosen cells
  share one, and closes on Escape or a click anywhere else. Click a workset or
  press Enter to choose. It follows the dark and light themes.
- Staged like every other edit: green until **APPLY**, one undo step however
  many rows, nothing in the model changes until then.
- **Only real worksets get in.** Paste, fill, Find and Replace, Number
  Sequence, formulas and the Excel import all pass through the same check: a
  value must name a workset in this model. Case and spacing do not matter, and
  the model's own spelling is what is staged. Anything else is refused, and the
  status line says why instead of calling the cell read only.
- **Fill copies in a Workset column, never counts** — "Level 2 - Mechanical"
  dragged down stays "Level 2 - Mechanical" rather than becoming a "Level 3"
  that does not exist.
- APPLY writes the workset's id, which is what Revit stores, and borrows each
  element first on a workshared model. An element someone else has borrowed,
  or one inside a group, is reported with the reason.
- On a model that is not workshared, the Workset column is read only.
- Double-clicking a Workset cell opens the list once, cleanly, and keeps a
  multi-row selection intact. The list of worksets is re-read whenever the
  tool refreshes from the model, so one renamed or added in Revit while the
  window is open can be chosen.
- Status messages count read-only cells and refused values separately, and
  the Excel import says how many values it turned away.

### Fix

- **Set Level borrowed nothing on a workshared model.** It asked to borrow its
  elements from inside the open transaction, where Revit refuses
  `CheckoutElements`, and the refusal was swallowed. All borrowing now happens
  before the transaction opens.

### Bench

- `import_check.py`: `worksets_wired` — a Workset cell opens the list, `stage()`
  keeps its check, no fill bypasses copy-only (Ctrl+E included), clicking
  inside a selection keeps it, no key-modifier test compares a .NET enum with
  0, Apply writes ids, and borrowing happens before the transaction and never
  inside it. `names_bound` — every name the module reads is imported or
  defined; the stub API answers anything, so a forgotten import only failed
  inside Revit. 45 static breakages across 23 rules, all caught.
- `bench_logic.py`: name matching (case, spacing, partial names, blanks),
  copy-only fill (single seeds, blocks, upward), the `stage()` gate against a
  fake window, writing by id, and the skipped-cell wording. 28 logic
  breakages, all caught.
- Reviewed independently before release. It found two real bugs in the first
  draft, both fixed: clicking inside a multi-row selection never opened the
  list (a .NET enum compared with 0, always False under IronPython), and
  Ctrl+E counted through workset names into other real worksets. Its six
  smaller points are fixed too.

## 1.19.1

- **The prompts are themed all the way through.** Every window the tool builds
  in code — the schedule picker, Find and Replace, the column tick filter, Set
  Level, the results and every other prompt — now gets the same brushes and
  control styles as the main window. Before, everything inside them fell back
  to Windows' own light chrome in an otherwise dark window: grey scrollbars
  with arrow buttons, a pale grey selected row, a blue focus ring on the
  search box, and white tick boxes in the filter list.
- Themed now: scrollbars (the slim thumb the grid uses), list rows (hover, and
  a blue selected row that stays blue when the list loses focus), text boxes
  (orange focus edge, placeholder text), tick boxes and option buttons
  (orange tick and dot). All of it follows the dark and light themes.
- **The schedule picker sizes to its content.** At a fixed height its list
  and hint overran the body, so it showed a second scrollbar around the list's
  own. The search box says *Search schedules* while it is empty, and long
  schedule names trim instead of scrolling sideways.
- **The dark theme now matches the other RevoBIM tools exactly**, not just
  Revit: the shared "Revit dark" palette in the theme reference, already used
  by Project Browser Pro, Filter Manager and Pro Sheets Exporter. Title bar
  #222933, selection #3A7392, hover #444E5E, window edge #515C6B, text
  #EEF0F4, muted text #A4AAB1 and blue #5AAEEB; the 1.19.0 values were a
  separate sampling of the same screenshot and came out a shade apart.
- The brushes every window looks up by name now come from one list,
  `palette_brushes()`, used by the main window's theme switch and by every
  dialog.
- `import_check.py`: `dialogs_themed` — the dialog styles parse, every brush
  they name exists, every control type built in code has a style, and every
  dialog applies them. 35 static breakages, all caught.

## 1.19.0

### Revit stays usable while the tool is open

- **The window opens modeless again**, owned to Revit so it stays in front of
  the model while you select, navigate and edit in Revit behind it.
- **Why it had stopped:** the check that notices a dead modeless window was
  raising a false alarm on every launch. Its proof that the window was alive
  fired from the constructor — the "rows loaded" status line — before the
  window was even shown, which used up the one-shot proof. No launch was ever
  recorded as alive, so each next launch said "nothing in the window
  responded" and offered to switch to modal; accepting saved modal for good.
  Proof now only counts once `show()` has returned, from the first handler
  that runs or the first mouse move over the window.
- **Your setting is reset once** to modeless, with the old health record
  cleared. If you choose modal later from the menu, that choice is kept.
- The modal / modeless menu item read a different default from the window, so
  it could describe the wrong state. Both now agree.
- If the usual route to Revit's window fails, the tool owns itself to Revit's
  process window instead, so it cannot slip behind Revit.
- Keyboard input is routed to the modeless window explicitly, so typing in a
  cell reaches the grid rather than Revit's shortcuts.

### Dark theme matches Revit

- The dark palette is now Revit's own dark UI, sampled from the Project
  Browser: **#3C4454** panel, **#212932** title bar, **#1B1F24** toolbar,
  **#2D3441** fields, **#323C48** for the column headings, white text.
- Two deliberate departures, both for legibility on Revit's lighter
  blue-grey: muted text is **#A9B1BC** rather than Revit's #878F97 (4.5:1
  instead of 3:1 on the panel), and red is lifted to **#FA8880** so read-only
  column names stay readable on the headings.
- The cell colours (type, instance, read-only, staged, refused, imported,
  test, copied) were tuned against near-black and sat at the same lightness as
  Revit's field colour, leaving instance cells barely distinguishable. They
  are lifted so each stands clearly off the field, with their text at 5.2:1
  or better. Selection is a clearer blue to match.
- **Dialog buttons follow the theme.** They had dark greys written in by hand,
  so every prompt's buttons stayed dark on the light canvas.
- Light theme is unchanged.

### Bench

- `import_check.py`: `layout_matches_dark_palette` — the window opens on the
  brushes in the .xaml and everything built in code uses the palette, so the
  two must agree colour for colour; `liveness_proof_after_show` — the proof
  waits for `show()`, the flag is set once and only after `Show()`, and the
  one-time reset runs before the health check. The new rule that a missing
  selftest anchor fails caught a stale anchor the palette change left behind.
- `bench_logic.py`: the settings reset undoes the old modal setting, clears
  the health record, leaves other settings alone, and respects a later choice.
- 31 static and 24 logic breakages, all caught.

## 1.18.0

### Opening a schedule

- **Double-click a schedule in the picker to open it.** When nothing is active
  or selected and the picker appears, a double-click on a schedule opens it;
  one on the scrollbar or the empty space under a short list does nothing.
  **Enter** opens the highlighted schedule (or presses whichever button has
  focus, so Tab to Cancel then Enter still cancels), **Escape** closes, and
  **Down** steps from the search box into the list. The first match is always
  highlighted, so typing part of a name and pressing Enter is enough.
- The search box no longer asks Revit for every schedule's name on each
  keystroke — the names are read once.
- A wait cursor while a schedule is read and laid out, so a large one does not
  look as if the button did nothing.

### Speed

Measured as calls from IronPython into .NET, which is where this tool spends
its time. Nothing here changes what the tool does; every shortcut is either
checked against the slow answer or falls back to it.

- **Opening a schedule is up to ~25x lighter.** The read used to list every
  parameter on every element — 100 to 300 on a typical MEP family, two calls
  each — to use the dozen the schedule shows. It now asks each element for
  exactly the parameter it needs, by its Definition. That path is **checked
  against the full listing** on the first 25 elements of every category, and
  each type is asked once however many rows share it; one disagreement sends
  that parameter back to the full listing for the rest of the read. The worst
  case is the old speed, never a different answer.
- **The grid fills a row at a time**, not a cell at a time — one call per row
  instead of seven plus one per column.
- **Scrolling repaints only the rows that arrive.** Every scroll tick used to
  walk every row in the schedule to find the forty on screen. The tool now
  keeps the set of rows the grid has actually realised, and colours just the
  few that scrolling hands to new rows.
- **Drag-selecting is no longer quadratic.** The grid raises a selection
  event per cell, and each one rebuilt the whole selection twice — dragging
  over 2,000 cells did that 2,000 times per mouse move. The work is now
  queued once per burst, the rectangle is not redrawn while the pointer stays
  in the same cell, and the fill handle remembers which cell is bottom-right
  instead of sorting the selection on every scroll tick.
- **Row positions are remembered** between scrolls instead of rebuilt from
  every row each time, and are forgotten the moment the view reports a sort,
  filter or edit.
- Each cell's staged-edit key is worked out once, not twice per cell per
  repaint.
- Re-applying a filter or collapsing a group no longer rewrites a flag on
  every row — only on rows whose flag actually changes. Each write was a
  change notice through to the grid, whether or not anything moved.

### Fixes

- In a grouped table, an ordinary row could come out **30px tall** after
  scrolling: a recycled heading row kept the height it had been given as a
  heading. Its height is now handed back.
- **Revert Selected** no longer lights up when only the row-number or Id cells
  are selected.

### Bench

- `import_check.py` gains `hot_paths_stay_light`: nothing that runs per scroll
  tick, per layout pass or per selected cell may walk the whole schedule or
  the whole selection, the selection work must stay queued, and the two hooks
  the caches depend on must stay wired — without them recycled rows are never
  dropped, or edits land in the wrong cells. A selftest breakage whose anchor
  text is missing now **fails** the selftest instead of being skipped, since a
  breakage that never happened proves nothing.
- `bench_logic.py` proves the fast parameter read against an API that lies,
  one that throws, a parameter first seen late, a second category further down
  the schedule, and a type shared by a hundred rows; plus the grid row layout,
  the unchanged-flag skip and the key cache. 27 static and 22 logic breakages,
  all caught.
- Reviewed independently before release. The five issues it raised are
  fixed: the fast read's checks now count distinct elements, a drag that WPF
  has already extended onto the row-number column is redrawn rather than
  left, Enter on a focused button presses it, Revert Selected ignores the
  index columns, and the picker finds the clicked item without an overloaded
  .NET call IronPython might not bind.

## 1.17.1

- **Fixes `ImportError: Cannot import name ListSortDirection` at load.** The
  assembly list referenced `System.Core` but never `System` itself, and
  `System.dll` is what provides `System.ComponentModel` on .NET Framework 4.8.
  It was not a new fault — the list has been this way since the tool was
  built — but an assembly only has to be referenced *into IronPython's
  runtime* for its namespaces to be visible, and the one this relied on was
  arriving as a side effect of `System.Data` rather than being asked for. The
  day the load order changed, it stopped. The list now names every assembly
  the tool's imports actually need, in both their .NET Framework 4.8 (Revit
  2024) and .NET 8 (Revit 2025+) spellings — `System.ObjectModel` and the
  `System.ComponentModel.*` assemblies hold on .NET 8 what `System.dll` holds
  on 4.8 — plus `mscorlib`, `System.Runtime`, `System.Diagnostics.Process`,
  `System.Data.Common` and `AdWindows`, each requested on its own so a name
  absent on a given release is skipped rather than taking the list down.
- **`import_check.py` now has the one rule that could have caught it.** A
  stub-API bench cannot: under CPython a namespace either resolves or it does
  not, and there is no assembly to reference, so the module-loads rule passed
  happily on code that died at load inside Revit. The new
  `assemblies_referenced` rule maps every `System.*` and `Autodesk.*`
  namespace imported anywhere in the tool to the assemblies that provide it
  and fails unless one of them is referenced. Run against the list that
  shipped in 1.17.0 it names `System.ComponentModel` and five more that had
  not bitten yet.
- It only counts references made **at import time**. `script.py` keeps a
  couple inside its error reporter, which by definition only runs once
  `import efr_core` has already failed — counting those would have the check
  certify the very ordering that breaks.

## 1.17.0

- **Shrink to the taskbar**, a new control in the top right beside the theme
  chip. Press it and the window slides down to the bottom of the screen like a
  drawer closing, leaving only its own title bar floating clear of the taskbar
  so Revit can be worked in. The control becomes a **green up arrow**; press it
  again and the drawer opens back to exactly the size and place it came from.
  **Ctrl+Shift+H** does the same from the keyboard.
- **Every window in the tool shrinks the same way** — the main window and all of
  the prompts, which are built from one shared dialog. The button, its size, its
  hover and its two glyphs come from one place, so the gesture is identical
  wherever it appears and it follows the dark and light canvas like the rest of
  the chrome.
- **Nothing is lost while it is away.** Pending edits stay staged, the selection
  and the sort survive, and the parked bar can be dragged anywhere on screen; if
  it has been moved, the drawer opens upward from where it now sits rather than
  jumping back.
- While the window is parked, Escape and Enter bring it back rather than
  reaching the exit prompt, F11 reopens it instead of filling the screen with a
  window nobody can see, and the resize grips park with it so they cannot
  swallow a click on the arrow.
- The body is **pinned for the length of the slide** and the window clips it,
  rather than the grid re-laying out on every animation frame — which is what
  makes it read as a drawer being drawn away instead of a window being squashed.
- `bench_logic.py` covers the parking and reopening arithmetic, including a
  second monitor above the primary one; `import_check.py` fails if a window is
  built without a drawer, if a shrink button is drawn but not wired, or if the
  drawer stops handing `Height` and `Top` back after the animation — any of
  which leaves a window that can never be resized or moved again, silently.

## 1.16.0

- **Select all / Untick all** in a column's value list, as proper buttons above
  the list rather than small ones in the footer, with a live "n of m ticked"
  beside them. They act on **what the search box is showing**, so searching
  narrows what they tick.
- **Isolate Selected**, bottom right. Select cells on any rows and press it: the
  default 3D view opens and those elements are temporarily isolated in it, the
  same isolation Revit's own button uses, so Reset Temporary Hide/Isolate puts
  the view back and nothing permanent is changed.
- **The section box stays on and stays visible.** Temporary isolation hides
  everything that is not in the set — the section box element included — so the
  box would disappear while still cropping the view. It is added to the isolated
  set instead, and the status line says when anything outside it will stay
  hidden.
- The default 3D view is `{3D}` where there is one, then a per-user `{3D - ...}`,
  then any other 3D view; a project with none says so rather than doing nothing.
  The view is refreshed after the change, which a view driven from a modeless
  window does not do by itself.
- `bench_logic.py` covers the view-ranking rule; `import_check.py` fails if the
  section box is dropped from the isolation or the refresh is lost.

## 1.15.4

- **A right-click anywhere on a column heading opens that column's menu**, led
  by *Highlight duplicates in …*, then *Isolate duplicates in …* and *Clear
  highlighting in …*. 1.15.3 routed this through `ContextMenuOpening`, which
  depends on the grid choosing to raise it for a heading. The heading
  right-click is now caught on the button coming up — the moment Windows opens a
  context menu — and marked handled, so the heading menu opens at the pointer
  and nothing else can open the cell menu in its place.
- If the cell menu is ever opened from a heading after all, its duplicate
  commands now name **that** column rather than whichever cell was last
  right-clicked.
- The menu key (and Shift+F10) still reach the heading menu through
  `ContextMenuOpening`.
- `import_check.py` fails if the heading right-click stops being caught on the
  way up.

## 1.15.3

- **Fixes the column heading menu being unreachable.** It hung off a Border
  with no Background, and WPF does not hit-test the empty areas of a Border
  without one — so a right-click anywhere on the heading except exactly on the
  column name fell through to the grid and opened the cell menu, which had no
  duplicate commands. The grid now looks at what is under the pointer when a
  menu is about to open and, if it is a heading, opens that column's menu. The
  filter box keeps its own cut / copy / paste menu.
- **The duplicate commands are on the cell menu too**, for whichever column was
  right-clicked: *Highlight duplicates in …*, *Isolate duplicates in …* and
  *Clear highlighting in …*, named for the column so it is clear what they act
  on, and greyed when there is nothing to act on.
- **Isolate and un-isolate are one item whose label flips**, rather than a tick
  whose state cannot be trusted inside its own Click.
- **Un-isolating gives the column's earlier filter back.** Isolating overwrote
  any tick filter already on that column and un-isolating removed it, so a
  filter set by hand was silently lost.
- `bench_logic.py` covers which values count as duplicates and the
  isolate / un-isolate round trip, including isolating twice before
  un-isolating; its selftest restores the old behaviour and confirms the loss is
  caught. `import_check.py` fails if heading right-clicks stop being routed or
  the cell menu loses its duplicate commands.

## 1.15.2

- **Combined parameters now show their values.** A "Combine Parameters"
  schedule field has no parameter id of its own — it is a list of parts, each a
  parameter with a prefix, a suffix and a separator. The tool saw the invalid
  id, filed the column as a calculated field, and never read it, so it came out
  blank. It now reads the parts (Revit 2022 and later) and builds the text the
  way the schedule does: prefix + value + suffix for every part, each part's
  separator between it and the next, never after the last. A part whose value is
  empty keeps its prefix, suffix and separator, because the schedule does too.
- Each part is looked up on the element first and its type second, so a
  combination of type and instance parameters reads correctly.
- The column stays read only — it has nothing of its own to write back to — and
  says so: edit the parameters it is made from. It is **rebuilt after APPLY and
  Reload**, so editing one of those parameters shows up in it.
- **`bench_logic.py` ships with the tool**: the combining rule, the element-then-
  type lookup, reading the parts, and the fill rules, run against the stub API,
  with a selftest that breaks each one (separator after the last part, empty
  values dropped, prefix and suffix ignored, type never looked up, type winning
  over instance) and confirms it is caught.
- **`import_check.py` refuses a folder with stray files in it.** A test run had
  written its error log into the tool folder and it went out in the 1.15.1 zip;
  the loader now falls back to the temp folder rather than its own when
  `%APPDATA%` is missing.

## 1.15.1

- **The shared RevoBIM easter egg is wired in.** Three slow clicks on the
  RevoBIM wordmark — or the icon beside it — open the mini game launcher, in
  whichever palette the window is currently using.
- It is a **soft dependency**: the import and the call both sit inside their
  own try/except, so a missing or changed `lib\revobim\egg` can never stop a
  schedule being edited.
- **`import_check.py` gains `rule_easter_egg_wired`**, so a future rebuild that
  forgets the egg fails on the bench. It uses the extension's own `egg_rule`
  when the shared folder is present, and falls back to checking the wiring
  itself when this tool is benched on its own.

## 1.15.0

- **A column's filter list now offers only the values the other filters allow.**
  Filter by Level and the System list shows the systems on that level, not
  every system in the schedule.
- **A column's own filter is left out of that**, the way Excel does it — or a
  filter could only ever be narrowed and never widened again, because the
  values it is hiding would not be in its own list to tick back on.
- When values are being held back, the dialog says how many and why, so a short
  list is never mistaken for a short schedule.
- Highlight and Isolate duplicates still look at the whole schedule, not the
  filtered view, so a clash cannot hide behind a filter.

## 1.14.3

- **Fixes the window failing to build.** `_proved`, the flag that records
  whether a modeless window ever answered, was read by `set_status` — which
  almost everything calls — but the line that was meant to initialise it in
  `__init__` never landed, so the first status message raised
  `AttributeError` and the window never appeared. It is now the first thing
  `__init__` sets.
- **The bench rule that should have caught it now does.** It only followed
  calls one level deep, and the path here was three:
  `__init__ -> set_status -> prove_alive -> self._proved`. It now walks the
  call graph, and:
  - does not follow calls made inside a nested function, because those are
    event handlers being wired up rather than work happening during
    construction — following them buried the real fault in false alarms;
  - counts a write in the same method only when it comes **before** the read,
    which is the difference between a guard and a bug and is exactly the shape
    this one had;
  - reads `getattr(self, 'name', ...)` as a read, so a defensive default
    cannot hide a missing attribute from it;
  - takes the earliest write by line number rather than the first one the walk
    reaches, since traversal order is not source order.

## 1.14.2

Fixes the blank white window, and makes the next one impossible to miss.

- **Non-ASCII text is now written as `u''` literals** — 63 of them. Under
  IronPython 2.7 a plain `str` literal is bytes, and an em dash in one is
  decoded as ASCII the moment it reaches a .NET string property, which throws
  there. Tooltips, status lines, dialog text and a transaction name were all
  carrying em dashes in plain literals.
- **`script.py` is now a 79-line loader and the tool lives in `efr_core.py`.**
  A blank white pyRevit window means the script died before any of it ran, and
  a tool that is one big script cannot report its own import failure — there is
  no runtime left to raise anything. The loader imports the body inside a
  try/except, so a failure now arrives as a Revit dialog naming the stage with
  the traceback, and is written to
  `%APPDATA%\RevoBIM PY\excel_for_revit_last_error.txt`.
- **`import_check.py` gains three rules**, each proved by breaking it: no
  non-ASCII outside a `u''` literal; the loader stays thin and imports nothing
  that can fail at module level; and the body still loads against the stub API
  under its new name. Eleven rules in total.

## 1.14.1

- **Modeless is the default again** — Revit stays usable while the schedule is
  open.
- **It can now recover on its own if the engine is torn down.** That failure
  leaves the window on screen with every handler dead, so nothing inside it can
  report the problem or offer the way out. The tool writes down that a modeless
  window was opened and the first handler that runs clears the note; if it is
  still there at the next launch, the last window never responded, and a prompt
  offers to open modally instead — **before** the window is built, so it works
  even when the last one was inert.
- That prompt also says what actually fixes it: **reload pyRevit** after
  installing a new version, because the setting that keeps the engine alive
  only takes effect after a reload.
- A window that has worked once on this machine is trusted afterwards, so an
  ordinary close is never mistaken for a failure.

## 1.14.0

**The window is modal again by default, and everything works from it.**

- **Modeless is now opt in.** It relies on pyRevit keeping this tool's engine
  alive; where that does not happen the engine is torn down the moment the
  command returns and every handler in the window dies with it — the window is
  still on screen and nothing in it responds, which is exactly what 1.12.0
  onwards did. Modal cannot fail that way, so it is the default.
  **Right-click the grid → "Keep Revit usable while this is open..."** switches
  between the two, saved for next time, with the trade-off spelled out.
  In modal mode the work happens directly, as it did before 1.12.0; the
  ExternalEvent is only created and used when modeless is chosen.
- **Fixes the ExternalEvent being created twice.** A replace without a count
  put the whole setup block inside `wire_grips` as well as `__init__`, so a
  second event was built on every launch and the first thrown away.
- **`script.py` now loads in stages and says which stage failed** — reading the
  document, finding the schedule, reading it, building the window, showing it —
  with the traceback, and writes the same text to
  `%APPDATA%\RevoBIM PY\excel_for_revit_last_error.txt`.
- **`import_check.py` ships with the tool.** Nine rules, run under plain
  CPython, each proved by breaking it on purpose:
  every `.xaml` parses; every .NET name is imported from the namespace it
  really lives in; the whole module loads against a stub Revit and .NET API;
  no f-strings, `print`, `System.Uri` or bare `.IntegerValue`; every
  `FindName` has a matching `x:Name` and every wired handler exists; no method
  defined twice; no undefined resource key and no `BasedOn` with a
  `DynamicResource`; both palettes carry the same keys; no setup block that
  runs twice; and nothing `__init__` calls may read an attribute `__init__`
  has not set yet.
- **Isolate duplicates** re-verified end to end: it toggles from state the tool
  keeps itself, isolates only the column whose heading was clicked, reports the
  row count, and leaves every other filter, the sort and the grouping alone.

## 1.13.1

- **Fixes cells no longer opening for editing.** The selection drag added in
  1.5.4 was rebuilding the selection on *any* mouse movement, including the
  pixel or two between the two clicks of a double-click — which took the cell
  out from under the edit before it could start. Nothing counts as a drag now
  until the pointer has passed Windows' own drag threshold, and the second
  click of a double-click is left entirely to the DataGrid, which is what
  begins the edit.
- **Fixes Isolate duplicates doing nothing.** It read the tick's own state at
  the moment it was clicked, which is not something to rely on for a checkable
  menu item. The tool keeps that state itself now. It also reports how many
  rows it isolated, and touches **only that column** — any other column's
  filter, the sort and the grouping are all left alone.
- **Double-clicking an edge, and full screen, use the screen the window is
  actually on.** `SystemParameters.WorkArea` is the primary monitor, so on a
  second screen both threw the window back onto the first. The monitor is found
  from the window handle and its pixels divided by the DPI scale, or it
  overshoots on a scaled display.

## 1.13.0

- **Right-click a column heading** for a menu led by **Highlight Duplicates**.
  Every set of clashing values gets its own colour, so which rows collide with
  which is readable without comparing values by eye.
- **Isolate duplicates** is a tick in the same menu, enabled only when there is
  something to isolate and naming how many sets it found. It leaves the rest of
  the column's filter alone and unticks cleanly.
- The menu also clears that column's highlighting or its filter, and opens the
  value picker.
- **Create Unique Sequence** on the cell right-click menu. It renumbers the
  selected cells to values nothing else in the column uses, counting on the
  **rightmost number** in the value: `SD-01` with 02 and 03 taken becomes
  `SD-04`, and `L01-P-1` becomes `L01-P-3`. Zero padding is kept, a value with
  no number in it gets one added rather than being left clashing, and a cell
  that is already unique is left alone and reported.
- Blank cells are not counted as duplicates — an empty cell repeated forty
  times would drown the real clashes.

## 1.12.1

- **Fixes Find in View and APPLY doing nothing since 1.12.0.** Going modeless
  put every write behind an `ExternalEvent`, and the code then *waited* for
  that event to finish. It cannot: **Revit raises the event on the same thread
  the window lives on**, so blocking that thread to wait means the handler
  never gets a turn. The wait ran out and the command reported that Revit was
  busy, which is precisely what a deadlock looks like from the outside.
  Work is now queued and the call returns straight away; the result comes back
  through a callback marshalled onto the window's dispatcher.
- APPLY reports from that callback: the button greys while it is running, the
  results window appears when it is done, and **Apply and exit waits for the
  write** before closing rather than closing on the way past.
- An error inside the Revit callback is shown with its traceback rather than
  disappearing into the event handler.

## 1.12.0

- **The window is modeless** — Revit stays navigable and editable while the
  schedule is open. It is owned to Revit's main window so it floats above
  rather than slipping behind, carries `__persistentengine__` so pyRevit does
  not tear the engine down when the command returns, and is parked in a module
  level variable so the engine cannot collect it out from under you.
  A modeless window has no API context of its own, so **APPLY, Set Level and
  Find in View all go out through an `ExternalEvent`** and wait for Revit to
  call back. A busy Revit is reported rather than silently doing nothing.
- **Find in View.** Select cells on any rows and press it: the elements are
  selected in Revit and shown in a view — Revit finds one they appear in, opens
  it if it has to, and zooms to them. Where no view can show them the selection
  still stands, and it says so rather than looking like it failed.
- **Fixes the Formula button appearing to do nothing.** It refused to open with
  nothing selected and only said so in the status line, which is easy to miss.
  It now opens either way, says what it needs, and carries a **Pick refs**
  toggle: on, clicking a cell puts its reference into the formula; off,
  clicking picks the cells the result goes into, and the bar follows the
  selection live.

## 1.11.0

- **The Formula button opens a bar** below the toolbar rather than a dialog,
  pushing the table down so the cells stay visible while the formula is written.
  Enter writes it, Escape closes it, and the button closes it again.
- **The formula is syntax coloured as it is typed.** Functions are orange,
  quoted text green, numbers teal, operators muted, and **every distinct cell
  reference gets its own colour** — the same reference twice gets the same
  colour — so a long formula can be read at a glance. `=`, `(`, `)` and `,`
  stay plain: they are punctuation and colouring them only adds noise.
- **Click cells in the table to put their references into the formula** while
  the bar is open. The reference goes in at the caret.
- **Cell references now carry a row, like Excel.** `A5` means that cell and
  follows the row down, so the same formula on row 6 reads A6; `A$5` stays on
  row 5; a bare `A` is the short way of writing the same-row form. The bar
  previews the first result and names the error otherwise.
- **A green + at the right of the column headers adds a test column**, and each
  test column's own heading carries a **x** to drop it again. The Test Column
  button has left the toolbar. Test columns still take formulas like any other
  and are never written to the model.

## 1.10.2

- **Windows-style window buttons** in place of the macOS traffic lights: flat
  rectangles with the glyph always showing and a grey hover. Full screen on the
  left, close on the right.
- **The close button is red** — a red glyph at rest, filling red with a white
  glyph under the pointer, so it reads as the close button without waiting for
  a hover.

## 1.10.1

- **Pulling a vertically snapped window away from the snap puts it back to the
  height it had before**, rather than resizing from the stretched one. The edge
  under the cursor stays where the cursor is and the opposite edge moves, so
  the window does not jump out from under the pointer. Dragging the window by
  its header does the same, the way Windows does.
- There are six pixels of slack first, so a twitch on the way to a sideways
  drag cannot undo the snap by accident. A sideways drag never undoes it.

## 1.10.0

- **Reload keeps the sort.** It re-applies the sort, the grouping and the
  filters after re-reading the model — all three are snapshots taken from
  values that have just changed, so they are taken again rather than left
  pointing at the old ones.
- **Sorting goes as deep as you keep shift-clicking**, up to six levels, rather
  than stopping at two. Each level only breaks ties in the ones above it and
  keeps its own direction, and each gets its own colour round the heading —
  orange, blue, green, violet, teal, amber — with its place and arrow shown
  (1▲, 2▼, 3▲). The status line names the order in words.
- Grouping orders inside each group by every level below the first, not just
  the second.

## 1.9.5

- **The window buttons swap round**: green full screen on the left, red close on
  the right, so close sits in the far corner where a Windows user reaches for
  it.

## 1.9.4

- **The schedule name has moved into the header**, beside the tool name and
  separated by a rule, so the top of the window says what it is looking at.
- **Group and Collapse All share the toolbar row**, over on the right.
- **When the window is too narrow for both, the icons drop to a row of their
  own** underneath, leaving Sort Headings where it is, rather than being
  clipped or pushing it off the edge. The two thresholds are 24px apart so a
  window dragged slowly across the boundary settles instead of flickering
  between the two layouts.
- The row the schedule name and Sort Headings used to occupy is gone, which
  gives the table its height back.

## 1.9.3

- **The theme toggle reads Dark or Light** rather than being an amber traffic
  light — a small chip in the header, left of the red and green ones, naming
  the canvas it is currently on. The tooltip names the switch instead
  ("Dark canvas — click for light"), since both readings of a theme button are
  common and it should not have to be guessed at.

## 1.9.2

- **macOS-style window buttons.** Close, theme and full screen are three
  traffic lights in the top right, in the Mac's own order and colours — red,
  amber, green — each showing its glyph on hover. The three colours are
  literals rather than palette keys because they do not change between light
  and dark on a Mac either; only the glyph inside them is themed.
- **The light / dark toggle has moved up there**, as the amber light, and is
  off the toolbar. Ctrl+Shift+T still works.
- **Double-click the top or bottom edge to fill the screen height**, keeping
  the window's width — the vertical half of a maximise. Double-click again to
  put it back. Dragging an edge or going full screen clears the stretch, so the
  two cannot leave each other with a stale restore point.
  The double-click is caught on the preview event: a `Thumb` marks the mouse
  down handled to start its drag, which can swallow `MouseDoubleClick` entirely.

## 1.9.1

- **Column letters are now a small orange circle** beside the column name
  rather than part of it, so the formula reference is there when wanted and
  quiet when not.
- **Two-level sorting.** Click a heading to sort by it; **shift-click** a
  second to sort within the first. The primary column keeps its orange outline
  and the secondary gets a blue one, and each shows its place and direction
  (1▲, 2▼). Clicking a column already in the sort flips that level's own
  direction, leaving the other alone.
  Each level keeps its own direction because the sort is layered least
  significant first through a stable sort, which one composite key could not do.
  Grouping uses the primary column and orders inside each group by the second.
- **The formula-reference note beside Group is gone**, replaced by a boxed
  **Sort Headings** group holding Group and Collapse All.

## 1.9.0

- **Set Level.** Select cells on any number of rows, press Set Level, pick a
  level from the list — every level in the project with its elevation — and
  press OK. The elements move onto that level **without moving in the model**.
- **Nothing moves.** An element's elevation is stored against its level, so
  writing a new level normally drags it through space by the difference between
  the two. Some categories compensate on their own and some do not, and which
  is which varies by category and by release. Rather than pair every level
  parameter with the right offset parameter and hope, the position is measured
  before and after and any shift is undone — correct for every category,
  including ones this tool has never seen. The result is checked afterwards and
  a row that ended up anywhere other than where it started is reported with the
  distance rather than counted as a success.
- **Staged like everything else.** Nothing is written until APPLY, the change
  runs inside the same transaction as the cell edits, the row number goes green
  while it is waiting, and Revert All drops it. The results window counts the
  elements re-levelled separately.
- Pinned elements are unpinned for the change and pinned again after, and
  elements are borrowed from central before the write.

## 1.8.2

- **A sorted row no longer jumps when you type into it.** Sorting was a live
  `DataView` sort on the value column, which re-evaluates the moment that value
  changes — so typing into the sorted column moved the row away from the cursor
  before it could be finished. The order is now worked out once and written into
  a key column, so it holds until the sort is asked for again. This is the same
  treatment the filters and the grouping already had.
- **Sorting is natural rather than lexical** as a result: P-9, P-10, P-100
  rather than P-10, P-100, P-2, P-9.
- **F5 re-sorts** as well as reapplying the filters and regrouping, and the
  status line says how many rows are sitting out of order after an edit, so
  nothing is silently stale.

## 1.8.1

- **The filter caret in each column heading works.** It never could: the caret
  marked `PreviewMouseLeftButtonDown` as handled to stop the header sorting
  underneath it, and handling the preview stops the button ever raising
  `Click` — so the handler it was wired to could not fire. The filter now opens
  from the preview itself, which both opens it and stops the sort.
- **The caret is themed.** A bare WPF `Button` falls back to the OS chrome, so
  it was a light grey lozenge sitting in a dark header. It now has its own
  template and follows dark or light with everything else.
- **Clicking into a column's filter box no longer eats every click** — only the
  first one, which gives the box the keyboard without sorting the column.
  Handling all of them left no way to place the caret or select inside the
  text.
- **The Excel button is an ordinary button rather than an orange one**, with a
  larger icon.
- A failure opening a column filter now reports itself instead of a one-line
  status message, since a silent handler is exactly what made the dead caret
  hard to spot.

## 1.8.0

- **One Excel button.** The footer's Export to Excel is now an Excel icon that
  asks which way you are going — **Export to Excel** or **Import from Excel** —
  and the separate Import button has left the toolbar. Ctrl+Shift+E and
  Ctrl+Shift+I still go straight to each.
- **Undo and Redo buttons removed.** Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z, and both
  are on the right-click menu with their shortcuts shown.
- **Group and Collapse All line up with the right edge of the last column**
  rather than the edge of the window. Where the columns do not fill the window
  there is dead space to their right, and buttons floating in it read as
  belonging to nothing. Where the table is wider than the window there is no
  dead space, so they stay at the window edge as before. It follows a resize,
  an auto-fit and a test column being added or removed.

## 1.7.3

- **The Filter rows box at the top right is gone.** Every column has its own
  keyword box and tick list, which is both more precise and where the eye
  already goes, so the whole-table search was a second way to do a worse job.
- **Clear all filters** moves to the right-click menu, where Reapply filters
  already lived.
- Escape inside a column's filter box clears that box and returns to the grid,
  the same as it did for the search box.

## 1.7.2

- **The column being sorted by is outlined in orange**, and its heading turns
  orange with a small arrow showing the direction. The header template draws no
  sort arrow of its own, so until now a sorted table gave no clue which column
  it was sorted on or which way — which matters more since Group follows the
  sorted column.
- The outline is a border of the tool's own around the heading contents, at a
  fixed thickness with only the colour changing, so lighting it cannot nudge
  the column layout. The auto-fit floor rises to 124px to allow for it.

## 1.7.1

Toolbar tidied down to the things that need a button.

- **Cut, Copy and Paste buttons removed** — Ctrl+X, Ctrl+C and Ctrl+V, plus the
  right-click menu, which is where people look for them anyway.
- **Fill Series, Clear and Auto-fit buttons removed.** Fill Series is Ctrl+E,
  Clear is Delete, and Auto-fit runs on open; all three are on the right-click
  menu.
- **Find is now Find and Replace**, which is what it does.
- **Undo and Redo** keep their buttons and are on the right-click menu with
  their shortcuts shown: Ctrl+Z, Ctrl+Y, and Ctrl+Shift+Z for redo as well.
- **Group and Collapse All moved** to the schedule-name row, hard right against
  the edge of the table. The orange box around Group is gone — it shows its
  state by reading **Grouped** in orange instead.
- **The toolbar wraps onto a second row** when the window is too narrow, rather
  than scrolling sideways. With six fewer buttons it fits a small window on one
  line in the first place.

## 1.7.0

- **Groups open and close.** Each heading carries a caret and its row count on
  the left and an **Expand / Collapse** button in the column beside it, and
  clicking anywhere on the heading toggles it — the whole band is the button,
  so it is hard to miss.
- **Collapse All / Expand All** on the toolbar does every group at once. The
  label follows the state: with anything open it offers to close everything,
  and once everything is shut it offers to open it again.
- **Closing a group and filtering are kept apart.** A row hides for two
  different reasons and each is recorded separately, so reopening a group
  brings back exactly what the filter allows rather than resurrecting rows the
  filter had removed.
- **A group keeps its state through a refilter or a re-sort**, matched on its
  label, so reapplying a filter does not spring everything open again.
- Heading text is written into the table rather than onto the cell, because a
  local value on a bound property sticks to that element and recycling would
  later reuse it for a real row — leaving a group label sitting in the data.

## 1.6.2

- **Double-click the fill handle to fill down without dragging**, the way Excel
  does. It follows the same rules as a drag — a number steps, plain text
  copies, and a run with an even gap keeps that gap.
- **It stops at the group heading.** With Group on, a double-click fills to the
  last row of the block it is in and goes no further, so numbering a level does
  not run on into the next one. With Group off there are no headings, so it
  runs to the end of the list.
- Filling the last row of a group says so rather than doing nothing silently,
  and the view scrolls to where the fill ended.

## 1.6.1

- **Group by sorted column is now an icon on the toolbar**, in the same
  icon-above-label form as the rest, rather than a tickbox tucked beside the
  search box. It carries an **orange box**: outlined when grouping is off,
  filled when it is on, so the state reads at a glance from across the window.
- The icon has dark and light variants like every other, and the box follows a
  theme switch.

## 1.6.0

- **Group by sorted column**, a tickbox on the toolbar. With it on, the table
  breaks with a coloured heading every time the value in the sorted column
  changes — Level 01, Level 02, and so on — each group getting the next colour
  from the palette. Click a different column heading to regroup by it; click
  again to reverse. Groups are ordered naturally, so Level 10 follows Level 02
  rather than Level 1.
- **The headings are purely visual.** They hold no element, take no edit, are
  never selected, never copied, and are left out of both Excel exports. A paste
  or a fill that runs across one **steps over it without consuming a value**,
  so five pasted values still land on five real rows however many headings sit
  between them.
- Heading rows live at the end of the underlying table and are placed only by a
  sort key, so they cannot disturb the row indexing everything else relies on.
- Like the filters, the grouping is a snapshot: editing a value in the grouped
  column does not make the row jump to another heading under the cursor. **F5**
  regroups, as well as reapplying filters.

## 1.5.4

- **Fixes the drag auto-scroll never firing.** The overshoot was measured
  against the last *realised* row, but a virtualising panel keeps rows realised
  beyond the visible area — so dragging to the bottom of the window still
  landed inside a row and reported an overshoot of zero, and even 60px below
  the window reported only 4px, which is inside the dead zone. It could not
  scroll at all.
  Overshoot is now measured against **the viewport**, so scrolling starts the
  moment the pointer reaches the edge of the grid and accelerates from there.
- **Scrolling starts just inside the edge** (`EDGE_INSET`), the way Excel does,
  rather than only once the pointer is fully outside.
- **Dragging past the left or right edge scrolls sideways too**, at a slower
  rate than rows since columns are much wider.
- The row under the pointer now comes from a hit test while the pointer is
  inside the grid, instead of measuring every row on every mouse move — the
  old scan walked the whole schedule per event, which on a large one was slow
  enough to look broken by itself.
- Ctrl-dragging still adds to a selection rather than replacing it.

## 1.5.3

- **Columns are fitted to their content when the window opens**, so the grid
  is readable straight away instead of needing Auto-fit pressed first. It runs
  on the first render rather than at build time, because the row containers do
  not exist until the grid has been through a layout pass and measuring before
  that fits every column to its header alone.
- **Auto-fit now measures once and freezes the result in pixels**, with a floor
  and a ceiling, rather than leaving the columns on Auto:
  - Auto keeps re-measuring as rows are realised while scrolling, so columns
    visibly jump about part way down a long schedule.
  - Auto has no ceiling, so a single long comments field pushed everything
    else off the edge.
  - The floor matters because each header carries a filter box and a caret,
    and a narrower column clips its own controls.
  The limits are `AUTOFIT_MIN`, `AUTOFIT_MAX` and `AUTOFIT_PAD` at the top of
  `script.py`.

## 1.5.2

- **A filtered row no longer vanishes when you edit it.** Filtering was applied
  to the values themselves, so writing a value into a filtered column made that
  row stop matching and disappear the instant it was committed — usually
  mid-fill, taking the cell being copied from with it.
  Filters now work the way Excel's autofilter does: **applying a filter takes a
  snapshot**, and what is on screen stays on screen until a filter is changed
  or reapplied. This falls out of filtering on a hidden flag column rather than
  on the values, so editing a value cannot move a row.
- **Rows kept visible are reported, not hidden.** The status line says how many
  rows on screen no longer match, and the tick-filter dialog says so too, so
  the held-back rows are never a mystery.
- **F5 reapplies the filters**, dropping anything that no longer matches and
  saying how many went. Also on the right-click menu, alongside a new
  Clear all filters.

## 1.5.1

- **Auto-scroll now accelerates with the pointer, the way Excel does.** Holding
  a drag past the top or bottom edge scrolls at about 7 rows a second just
  past it, ramping to about 95 the further out the pointer goes. 1.5.0 advanced
  exactly one row per tick regardless of distance, which is unusable on a long
  schedule.
  Rates are rows per *second* rather than per tick, and the leftover fraction
  carries between ticks — without that, any rate below one row per tick would
  round to zero and never scroll at all.
- **Dragging a selection auto-scrolls too**, not just the fill handle. WPF
  handles a drag-select perfectly well while the pointer is inside the grid, so
  the scroller stays out of the way until the pointer is actually past the
  edge. A drag that crossed several columns keeps its width as it scrolls.
- The scroller stops itself if the mouse button comes up somewhere the window
  never saw it — released off-screen, or over something that swallowed the
  event — rather than scrolling on forever.
- `scroll_rate()` is a plain function with no WPF in it, bench-tested by
  simulating the tick loop, so the feel can be tuned by reading numbers rather
  than by dragging in Revit. The constants sit at the top of `script.py`:
  `SCROLL_MIN_RATE`, `SCROLL_MAX_RATE`, `SCROLL_RAMP_PX`, `SCROLL_CURVE`.

## 1.5.0

- **Copy marks its source.** Ctrl+C (and Ctrl+X) tint the copied cells amber
  and say so in the status line; select the destination, Ctrl+V, and the tint
  clears. Escape clears it without pasting. The marks are held against the
  element and column, so they follow the data through a filter rather than
  pointing at whatever later occupies that spot.
- **A filter on every column.** Each heading now carries a keyword box and a
  caret opening an Excel-style tick list, with its own search and All / None.
  Everything ticked means no filter, unticking narrows, nothing ticked shows
  nothing. A filtered column's caret turns orange and fills in, so it is never
  a mystery why rows are missing. The X beside the search box clears the search
  and every column filter at once. Column filters, the tick lists and the
  global search all compose into one row filter.
- **Drag fill rebuilt.** It now behaves the same way every time:
  - **no number in the cell — the value is copied down**
  - **a number in the cell — it steps, in the direction of the drag**
  - several cells with an even gap keep that gap (10, 20 fills 30, 40)
  - several cells with no series repeat as a block
- **Fixes a drag fill from AHU-1 producing AHU0.** The number parser read the
  hyphen in a tag as a minus sign, so AHU-1 was "AHU" and negative one. A minus
  now counts as a sign only at the start of the value or after a space.
- **Fixes padding being invented.** AHU-10 dragged up gave AHU-09; padding is
  now kept only where the value is genuinely zero-padded, so SD-005 still goes
  to SD-004 but AHU-10 goes to AHU-9.
- **Fixes the drag stopping short.** The target row was found by hit testing,
  which returns nothing once the pointer leaves the rows — past the last one,
  over the header, off the edge — so the fill silently stopped tracking. It is
  now worked out by measurement, and **the grid auto-scrolls** while the
  pointer is held past the top or bottom edge, so a fill can run well beyond
  one screen. Escape during a drag cancels it.
- The fill rules are plain functions (`fill_plan`, `split_number`,
  `infer_step`) with no WPF in them, and are bench-tested against a table of
  cases rather than by dragging in Revit.

## 1.4.1

- **Fixes "We found a problem with some content in ...".** OOXML fixes the
  order of the elements inside `<worksheet>` and Excel enforces it, even though
  lenient readers do not. The freeze-pane block was being inserted just before
  `<sheetData>`, which put it *after* `<cols>` — invalid, so Excel offered to
  repair and then failed. The worksheet is now built in schema order
  (dimension, sheetViews, sheetFormatPr, cols, sheetData, autoFilter,
  mergeCells) rather than assembled and patched.
  Hardened at the same time: single-cell merges are dropped (Excel rejects
  them), duplicate tab names are numbered — including two long names that
  collide only after the 31-character truncation — only the first tab is marked
  selected, `<b/>` precedes `<i/>` in a font, degenerate autofilters are left
  out, and column widths are rounded.
- **`xlsx_check.py` ships with the tool.** It validates every generated
  workbook against the OOXML structure rules — element order, merge refs, cell
  references matching their row, style ids in range, content types, sheet
  relationships, tab names — across five shapes of export including one column,
  no rows and an illegal schedule name. `python xlsx_check.py --selftest`
  breaks each rule on purpose and confirms the check catches it; the element
  order rule catches exactly the bug above.
- **The toolbar stays on one row.** It was a `WrapPanel`, so a narrow window
  pushed buttons onto a second line. It is now a single horizontal strip that
  scrolls if it has to.
- **The window resizes by dragging any edge or corner.** A borderless
  `AllowsTransparency` window has nothing hit testable in its frame, so WPF's
  resize border never fires whatever `ResizeMode` says — it now carries eight
  invisible thumbs of its own, clamped at the minimum size. With the toolbar no
  longer wrapping, that minimum drops to 900 x 520.
- **The scrollbar thumb reflects how much data there is**, the way Excel's
  does. `Track` only sizes its thumb proportionally when `ViewportSize`,
  `Minimum`, `Maximum` and `Value` are template-bound; without them
  `ViewportSize` is `NaN` and Track falls back to the thumb's own desired size —
  a tiny fixed grip whatever the row count. The bar is also slightly wider,
  with a hover and drag colour.

## 1.4.0

Excel export and import, both directions, with no external dependency —
the workbook is written and read as Office Open XML through
`System.IO.Compression`, so there is no Excel interop and no pip package.

- **Export to Excel** on the footer, left of APPLY (Ctrl+Shift+E). Two layouts,
  chosen in a dialog:
  - **Round trip** — a flat, filterable list with a Revit ID key column and
    every value column coloured the way the grid colours it. A second sheet
    carries the legend and the stamp.
  - **Presentation** — title band, headers, borders, banded rows, widths sized
    to the content, wrapped text, numbers as real numbers. One direction only.
- **Import from Excel** on the toolbar (Ctrl+Shift+I). Rows are matched on the
  **Revit ID, not on position**, so sorting and filtering the sheet in Excel is
  safe. Headings match loosely on case and punctuation.
- **The save location is remembered** and reused by the next export and import.
- **A report before anything is staged**, listing what will change with its old
  and new value, what was ignored because the parameter is read only, which IDs
  are not in this schedule and which headings do not match. Cancel stages
  nothing.
- **Imported changes are painted teal** in the grid, distinct from hand edits,
  with their own footer legend entry, so what came in from the file is obvious
  before APPLY. Editing an imported cell by hand returns it to the normal edit
  colour.
- **Open file location** after an export takes you to the file in Explorer.
- Fixed **Ctrl+Shift+E** being swallowed by Ctrl+E (fill series) and
  **Ctrl+Shift+Z** by Ctrl+Z (undo) — first match wins in the key handler, so
  the more specific combination has to be tested first. All 18 shortcuts are
  now checked against every Ctrl/Shift combination on the bench.

## 1.3.0

Windows clipboard and keyboard conventions, properly.

- **Shortcuts are now focus-aware.** The window handled every key at the top
  level, so Ctrl+C, Ctrl+V, Delete and Backspace were taken from the grid even
  when the search box had the keyboard — Backspace while typing a filter was
  clearing the selected cells, and Escape closed the tool mid-word. Text boxes
  now keep their own keys, and Escape in the search box clears the filter and
  returns focus to the grid instead of closing the window.
- **The edit flag can no longer stick.** If BeginningEdit threw, `editing`
  stayed True and every shortcut in the window went dead until restart. It is
  now cleared on failure and whenever the current cell changes, and read from
  the keyboard focus as well as the flag.
- **Ctrl+X cut**, with its own toolbar button: copies the selection, then
  empties the cells that can be emptied and reports the ones it could not.
- **Right-click menu** on the grid — cut, copy, paste, clear, fills, the four
  cell tools, find and replace, revert — themed with the rest of the window and
  showing each shortcut beside its command. Right-clicking a cell selects it
  first unless it is already part of the selection.
- **F2** starts editing the current cell.
- The DataGrid's own clipboard copy is enabled again as a fallback route, so
  Ctrl+C still produces a tab-separated block even if the custom handler is
  bypassed.

## 1.2.1

- **Fixes the white-screen crash on launch in 1.2.0.** Making the window
  themeable turned every `StaticResource` into a `DynamicResource`, including
  the two `BasedOn` references on the footer button styles. `BasedOn` is a plain
  CLR property on `Style`, not a dependency property, so `XamlReader.Load` threw
  `SystemError: A 'DynamicResourceExtension' cannot be set on the 'BasedOn'
  property of type 'Style'` before the window could open. Those two are back to
  `StaticResource`; every other reference is a dependency property or a
  `Setter.Value` and stays dynamic, so live theme switching is unaffected.

## 1.2.0

- **Dark / light canvas.** A Theme button flips the whole window between the
  RevoBIM dark shell and a light one. Every colour is a dynamic resource, so
  the switch is live; the choice is remembered in the settings file.
- **Toolbar icons**, drawn in the RevoBIM palette, icon above label, with a
  separate glyph set for each theme so the strip stays clean either way.
- **Highlight tool** (Ctrl+Shift+H). Eight colours, applied as fill, text or
  both, to the selected cells, their whole rows, or their whole columns.
  Highlights are keyed to the element and the column, so they stay put through
  filtering, sorting and reload. They never hide a staged edit or a refusal.
- **Test columns.** Scratch columns after the last real one, with their own
  formula letters, for trying an expression before pointing it at a parameter.
  They take fills, pastes and formulas, and are never written to the model.
- **Sequence padding follows the start number** — 001 gives 001, 002, 003 and
  rolls on to 010 and 100; 01 gives 01, 02, 03. The pad box now only widens
  beyond what the start number implies.
- **Full screen** button in the header, F11, or a double-click on the header.
  The window fills the working area rather than covering the taskbar.
- **Minimum window size** raised to 1180 x 640 so the toolbar can never be
  squeezed to the point of hiding buttons.

## 1.1.0

- **Formula tool** (Ctrl+Shift+F). Column letters run across the header — A, B,
  C — and a formula is evaluated once per selected cell and written in as static
  text. `&` joins, `+ - * /` calculate, and CONCAT, UPPER, LOWER, PROPER, TRIM,
  LEFT, RIGHT, MID, LEN, REPLACE, PAD, SEQ, ROUND, VALUE and IF are available,
  alongside THIS, ROW, N and ID. Live preview of the first rows, and the whole
  run is refused rather than half written if any row errors.
- **Sequence tool** (Ctrl+Shift+N). Start, step, zero padding, prefix and
  suffix, numbered down the selection and restarted per column, with the option
  to keep the existing cell text in front.
- **Prefix / Suffix tool** (Ctrl+Shift+P). Wraps text around what the selected
  cells already hold, skipping empty cells and cells already carrying the
  prefix so a second run does not double up.
- **Cell colour legend moved to the footer**, and now names all five states.
- **Read-only cells are light red** rather than grey. Cells Revit refused on
  APPLY moved to a stronger red so the two do not read as the same thing.
- Formula, sequence and prefix writes all stage as a single undo step.

## 1.0.0

First release.

- Opens the active schedule view, or the schedule selected in the Project
  Browser; falls back to a themed picker listing every schedule in the model.
- Reads the schedule as a grid of elements against visible fields, ordered by
  the schedule's own sort fields.
- Cell colouring: orange for type parameters, blue for instance parameters,
  grey for read-only, green for staged edits, red for edits Revit refused.
- Excel-style editing: copy, paste (single value or a whole block), fill down,
  fill series, drag-fill handle, clear, find and replace, undo and redo,
  revert selected, revert all, row filter, auto-fit, reload.
- Editing a type parameter cell updates every row that shares that type.
- Nothing is written until APPLY. APPLY runs one transaction, reports the
  number of elements changed in a themed window, and leaves the window open.
- Escape or the close button offers Apply and exit, Exit without saving,
  or Cancel, whenever edits are pending.
- Runs on Revit 2024 - 2027: no `System.Uri`, no `ElementId.IntegerValue`,
  no f-strings, assemblies requested individually.

### Known limits

- Material takeoffs are refused — their rows are materials, not elements.
- Element-valued parameters (family and type, materials, levels) are read only.
- Calculated, formula, percentage and combined fields are read only.
- Rows are one per element; grouping, totals and non-itemised rows are not
  reproduced.
