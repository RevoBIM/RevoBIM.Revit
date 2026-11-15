# View Template Manager - changelog

## 1.3.1
- **Dark theme now uses Revit's own dark colours**, sampled from its Project
  Browser: the blue-slate list body (`#3C4454`), the darker panel title bar
  (`#202830`) for the header, footer and column headings, the search-field
  colour (`#2D3441`) for text boxes, Revit's selected-row band (`#323C48`) for
  the whole-row highlight, and its pale text (`#E0E6ED`). The RevoBIM blue,
  orange and green accents are kept. Light theme unchanged.
- The table has its own background key (`BrushGrid`), so it can be the list
  slate while text boxes stay the darker field colour.
- Red lifted slightly (`#EF7B76`) to stay readable on the slate grid.
- Bench: every text and glyph colour is checked for WCAG contrast against each
  background it is drawn on, in both themes (`check_contrast`, 50 pairs).

## 1.3.0
- **Shrink to the taskbar**, on every window the tool opens (the main window
  and the confirm / results dialog). The new button top right, beside full
  screen and close, slides the window down to the bottom of its screen like a
  drawer closing, leaving only its header bar floating there so Revit can be
  seen. The button turns into a **green up arrow**; press it to slide the
  window back.
- Also reopens on a double-click on the bar, Escape, Enter or F11, and
  Ctrl+Shift+H toggles it either way. The bar can be dragged; dragged
  somewhere else, the window opens from where the bar now is, kept on that
  screen.
- Nothing is lost while parked: staged edits, filters, selection and scroll
  all stay. Popups and the cell editor are closed first, and full screen is
  left first.
- Shrinking the dialog takes the main window down with it and parks the
  dialog's bar just above; opening or closing the dialog brings the main
  window back.
- Closing while parked remembers the window's real size, not the bar's.
- Bench: five new `import_check` rules (each window has a wired shrink button,
  asks the drawer first on header clicks and keys, releases the slide, saves
  its true size) and drawer drive tests in `bench_logic`, including a second
  monitor above the primary.

## 1.2.0
- **Reset filters** in the tool bar clears every column filter (both modes),
  the search box, the view type and Unused only in one click. It lights only
  while something is filtering. The sort is not a filter and stays.
- **A filtering column's heading is tinted orange**, chevron included; the
  sorted column gets an orange outline as well as its arrow.
- **Selecting a cell lights its whole row**, for every row in the selection.
- **Copy and paste across many cells**, as in Excel for Revit. Ctrl+C copies
  tab-separated so it lands in Excel and marks its source amber until pasted
  or Escape. Ctrl+V puts a single value into every selected cell, a block from
  the top-left of the selection, or tiles a block down or across a larger
  selection it divides into evenly. Every pasted value goes through the same
  rule as typing it, so a choice is matched to its dropdown, `1 : 50` reads as
  a scale, and anything a cell cannot take is skipped and counted - hover the
  status line for why. Also on a right-click menu with Edit, Revert edits in
  selection and Clear copy marks. Works in Include ticks mode too.
- **Drag a column heading to move the column.** The order is remembered for
  next time, as are which columns are shown in each mode and their widths.
  Built-in parameters are remembered by id; project and shared parameters by
  name, and a column another project has keeps its place. Drag Used to the far
  right and it stops being frozen. **Columns... > Reset column order and
  widths** puts them back.
- **Dark and light themes**, missed from 1.0.0. The chip top right cycles
  **Auto -> Dark -> Light** and is remembered; Auto follows Revit's canvas
  theme and re-checks it whenever the window comes to the front.
- House chrome brought up to standard: full screen by bounds (button, F11,
  double-click the header), eight resize grips (the window could not be
  stretched before), window size remembered.
- Right-click a column heading for its sort and filter menu.
- Fixed: a single click anywhere on a column heading opened its filter menu
  (in 1.1.0 as well) and swallowed double-click-to-sort. Only the chevron
  opens it now - a heading is itself a button to WPF.
- Loader runs in named stages and writes failures to
  `%APPDATA%\RevoBIM\view_template_manager_error.txt`.
- `vtm_clr.py` references every assembly before anything imports from it.
- `import_check.py` rebuilt: 22 rules, each proved by `--selftest`, three of
  them from a cold review of this release. `bench_logic.py` added: 106 checks
  on the staging, clipboard, column-order, settings and theme rules, 11
  deliberate breakages in `--selftest`.

## 1.1.0
- **Sort and filter on every column.** Each column header carries a small
  chevron; clicking it opens a menu with **Sort A to Z / Z to A / Clear sort**
  and an Excel-style tick list of the values in that column, with a search box,
  All / None, **Apply filter** and **Clear filter**.
- Ticking follows Excel's autofilter: everything ticked means no filter,
  unticking narrows, nothing ticked shows nothing. The values offered are the
  ones still standing after every *other* filter.
- Filters stack across columns and sit on top of the search box, the view type
  box and **Unused only**. The footer counts how many columns are filtering.
- Header text carries the state: an arrow for the sorted column, a bar glyph
  for a column that is filtering.
- Filters are kept **per mode**, since Values and Include ticks show different
  things in the same column.
- Double clicking a header still sorts, and is now in step with the menu.
- The ribbon button is renamed from *RevoBIM View Template Manager* to
  **View Template Manager**.

## 1.0.0
First release.

- Every view template in the project in one Excel-style grid, one row each.
- **Used** and **Default** columns: how many views carry the template, and how
  many view family types name it as their default. Both frozen at the left with
  the name and view type so they stay on screen however far the grid is scrolled.
- Columns are the union of every parameter across every template, discovered
  from the model rather than hardcoded, with a **Columns...** picker
  (search, All / None / Core set / In use only).
- Two modes: **Values** (what each setting is) and **Include ticks** (which
  settings the template actually controls, from
  `GetTemplateParameterIds` / `GetNonControlledTemplateParameterIds`).
- Double click a cell to edit it in place - text box, whole number, or dropdown
  for yes/no, enum and element-valued parameters. F2 does the same on the
  selected cell. Enter commits, Escape cancels.
- Staged edits show **orange on a dark orange cell** and nothing is written to
  the model until **Apply**. **Revert edits** throws them away.
- Rename a template by editing its name cell; a clash with an existing view
  name is refused before the write rather than half-applied.
- **Unused only** isolates the templates nothing is using; **Delete unused** and
  **Delete selected** both preview exactly what they will remove first.
- Double click a column header to sort on it, again to reverse.
- One transaction per operation, warnings swallowed, and anything refused is
  reported in a themed window rather than skipped quietly.
- Ships with `import_check.py`.
