# View Template Manager — v1.3.1

A pushbutton on the **RevoBIM PY** tab, **Management** panel:
**View Template Manager**. Every view template in the project as one
Excel-style table — what each is set to, how many views use it, and which
settings it actually controls — edited in place, copied and pasted across, and
written in one go.

## Problem it solves

View templates are managed one at a time through a dialog that shows a single
template's settings. Comparing two means opening one, remembering it, and
opening the other. Finding out whether a template is used at all means reading
every view's properties. Tidying a model that has collected forty templates
over three years is a job nobody does, so the list grows.

Everything needed is already in the model. Laid out as a grid it is a table,
and a table can be read across as well as down.

## The window

Modal — nothing here needs picking in the model. House chrome: icon,
**RevoBIM** / tool name, then the **theme chip**, version, **shrink**,
**full screen** and close. Eight resize grips round the edge; full screen by bounds from the
button, F11 or a double-click on the header; dragging the header leaves it.
The window's size is remembered.

Rows are templates. Frozen at the left by default: **Template Name**,
**View Type**, **Used**, **Default**. **Used** is the views carrying the
template; **Default** is the view family types naming it as their default —
both count as use, because deleting a default silently changes what new views
come out as. Hover **Used** for the views by name. Unused shows red.

Tool bar: **Search** (name and view type), **View type**, **Unused only**,
**Reset filters**, the **Values / Include ticks** switch, **Columns...** and
**Refresh**.

## Two modes

**Values** — what each setting is. **Include ticks** — which settings the
template controls (`GetTemplateParameterIds` /
`GetNonControlledTemplateParameterIds`): green ✓ pushes it to its views, grey –
leaves the view alone, blank means the template does not offer it. Each mode
keeps its own shown columns and its own filters.

## Shrink to the taskbar

On **every window the tool opens** — the main window and the confirm / results
dialog. The shrink button (down arrow onto a bar) slides the window to the
bottom of its screen like a drawer closing, leaving only the header bar
floating 8 px above the taskbar, so Revit can be seen. The button becomes a
**green up arrow**; press it to slide the window back.

- Also reopens on a **double-click on the bar**, **Escape**, **Enter** or
  **F11**; **Ctrl+Shift+H** toggles either way. Other keys are swallowed while
  parked, so nothing acts on the hidden table.
- The bar can be **dragged**. Dragged somewhere else, the window opens from
  where the bar now is, kept on that screen, instead of jumping back.
- Nothing is lost: staged edits, filters, selection and scroll all stay. The
  cell editor and any popup are closed first, and full screen is left first.
- Shrinking the **dialog takes the main window down too** and parks its own
  bar 4 px above; opening or closing the dialog brings the main window back.
- Opening a dialog over a parked main window opens the main window first, so
  the dialog is never centred on a bar.
- Closing while parked saves the window's **real** size, not the bar's.
- The window is modal, so a parked window shows Revit but Revit cannot be
  worked in until the tool is closed.

## Sorting and filtering

The chevron at the right of each heading — or a right-click on the heading —
opens that column's menu: **Sort A to Z / Z to A / Clear sort**, and an
Excel-style tick list with a search box, All / None, **Apply filter** and
**Clear filter**. Everything ticked means no filter; nothing ticked shows
nothing. The values offered are those the *other* filters leave standing.
Double-click a heading to sort on it, again to reverse.

**State is on the heading itself.** A column that is filtering is **tinted
orange** with an orange chevron; the sorted column gets an **orange outline**
and an arrow. The footer counts the filtering columns.

**Reset filters** clears every column filter in both modes, the search box,
the view type and Unused only. It is greyed out until something is filtering.
The sort is not a filter and stays.

## Selecting

Click a cell, drag across cells, Ctrl/Shift-click, or click the row header for
the whole row. **Every row holding a selected cell lights up across its full
width**, so it is plain which templates a selection touches.

## Editing

**Double-click a cell** (or F2) to edit: a text box, a whole number, or a
dropdown for yes/no, enum and element-valued parameters. Enter keeps it, Escape
drops it, clicking away keeps it. In Include ticks, a double-click toggles the
tick.

**Nothing is written until Apply.** A staged edit shows **orange on a dark
orange cell**; its tooltip says what it was. Editing back to the original
clears the edit. **Revert edits** throws them all away.

## Copy and paste

As in Excel for Revit:

- **Ctrl+C** copies the selection tab-separated, so it lands in Excel. The
  copied cells go **amber** until pasted or Escape. A cell standing for
  "not on this template" copies as blank.
- **Ctrl+V** pastes into the selection:
  - one value → into **every selected cell**;
  - a block over a full rectangle it divides into evenly → **tiled**, so one
    copied row pastes down fifty templates;
  - any other block → once, **from the top-left** of the selection.
- The same on a **right-click menu**, with **Edit cell**, **Revert edits in
  selection** and **Clear copy marks**.
- Works in Include ticks too — ✓/–, yes/no, 1/0 all read.
- The keyboard belongs to whatever has focus: in the search box or the cell
  editor, Ctrl+C and Ctrl+V are the text box's.

**Every pasted value goes through the same rule as typing it**
(`vtm_core.stage_text`): a choice is matched to its dropdown by name, ignoring
case; `1 : 50` reads as a scale of 50; a blank or "none" picks (None) on an
element parameter. Anything a cell cannot take — read only, not on that
template, not one of the choices — is **skipped and counted**; hover the status
line for the reasons.

## Moving columns

**Drag a heading** to move its column. The freeze follows: the identity
columns that are still at the left stay frozen, so drag Used to the far right
and it scrolls like any other. **Columns... > Reset column order and widths**
puts everything back.

## Remembered between sessions

`%APPDATA%\RevoBIM\view_template_manager.txt`, key=value:

| Setting | What |
| --- | --- |
| `theme` | `follow` (default) / `dark` / `light` |
| `column_order` | every column's position, shown or not |
| `visible_values`, `visible_controlled` | which columns each mode shows |
| `column_widths` | per column |
| `width`, `height` | the window |

Columns are remembered by **token**: built-ins as `b:<id>` (the same in every
model), everything else as `n:<name>`, since a project or shared parameter's id
differs between models. Saving in a project that lacks a column keeps that
column's place from the last save, so moving between projects with different
shared parameters does not forget anything. Filters are per session.

## Theme

Dark is **Revit's own dark theme**, sampled from its Project Browser: list
body `#3C4454` (window and table), panel title bar `#202830` (header, footer,
column headings), search field `#2D3441` (text boxes), selected-row band
`#323C48` (the whole-row highlight), text `#E0E6ED`, with the RevoBIM blue,
orange and green accents on top. Light is the house light palette. Every
foreground is checked on the bench for contrast against each background it is
drawn on, in both themes. The chip cycles **Auto → Dark → Light**. Auto
follows Revit's canvas: `UIThemeManager.CurrentCanvasTheme` (2024+, tested
`is not None` — `UITheme.Dark` is 0), then the canvas background colour's
luminance, then `CurrentTheme`, re-checked whenever the window comes to the
front. The swap is live — selection, scroll and staged edits survive it.

## Deleting

**Unused only** isolates them, **Delete unused** removes them, **Delete
selected** removes the selected rows regardless. Both preview the exact list
first, saying which are in use and how, and run in one transaction.

## Decisions worth remembering

- **One staging rule.** Typing, dropdown picks and paste all go through
  `stage_text`, which returns `STAGED` / `SAME` / `SKIPPED` with a reason. It
  touches no WPF and no Revit, so it is tested against a table of cases.
- **Clipboard maths is plain functions over positions** — `copy_text`,
  `parse_clipboard`, `paste_plan` — positions being (index in the shown rows,
  column `DisplayIndex`), which stay consistent after a drag.
- **Row highlight is a `Tag` on `DataGridRow`**, set on selection change for
  realised rows and in `LoadingRow` for the rest. Recycling hands a container to
  a new row, and `LoadingRow` runs for recycled containers too, so the tag
  always follows the row.
- **Heading state is a per-column `HeaderStyle`** — a style built in code,
  `BasedOn` the theme's `GridHeader`, setting `Tag` to `f` / `s` / `fs` for the
  template's triggers. A plain column has its `HeaderStyle` **cleared**, not set
  to `None`: a local `None` outranks the grid's `ColumnHeaderStyle` and drops to
  the stock system header.
- **A frozen column can only be dropped among the frozen ones.** The freeze is
  lifted in `ColumnHeaderDragStarted` (only when scrolled fully left, where
  nothing moves as a result) and put back **after** the drag, via the
  dispatcher — WPF raises `DragCompleted` before it checks the drop, so
  refreezing there refuses the drop.
- **A column heading is a `ButtonBase`.** Its own click raises `Click`, so the
  routed handler for the chevron checks the source is `PART_HeaderMenu`.
- **Converters read brushes at conversion time** from `vtm_theme.CURRENT`, so a
  theme swap or a copy mark refreshes just the realised cells.
- **The drawer slides on a `DispatcherTimer`, not a Storyboard.** An animation
  holds its end value and outranks every later assignment, which leaves a
  window that can never be moved or resized again with nothing raised. The
  timer writes plain `Left` / `Top` / `Height`: ease-out cubic, 0.28 s, 15 ms
  frames. `finish()` stops the timer and clears `sliding` in its own guard,
  and is also the way out when a frame or the start itself fails.
- **`MinHeight` and `SizeToContent` veto a smaller `Height`.** Both are
  relaxed before the slide and put back when the window reopens.
- **The body is pinned for the slide** — the root's `Height` held at its full
  `ActualHeight`, `VerticalAlignment` `Top` — so the window clips it like a
  drawer instead of re-measuring the grid every frame. Released once parked so
  the shell draws round the bar, pinned again before the body shows to reopen.
- **The resize grips are parked with the window**, or the bar is lined with
  invisible drag handles that swallow the arrow's click.
- **Parking arithmetic is plain functions** (`parked_top`, `expanded_rect`,
  `key_action`, `ease_out`), proved on the bench including a monitor *above*
  the primary, where a negative working-area top is what sends a bar to the
  wrong screen.
- **`vtm_clr` first.** Every module imports it before any `System.*` line;
  `import_check` maps each imported namespace to its assembly and fails if
  `vtm_clr.ASSEMBLIES` lacks it.

## Folder layout

```
Management.panel\
  View Template Manager.pushbutton\
    script.py          thin loader, staged, writes view_template_manager_error.txt
    vtm_clr.py         every clr.AddReference, imported first
    vtm_core.py        version, the model read, staging, clipboard rules, writes
    vtm_settings.py    remembered settings, column tokens and order (no .NET)
    vtm_theme.py       dark / light palettes, Auto -> Dark -> Light, canvas theme
    vtm_drawer.py      shrink to the taskbar: parking maths + Drawer, all windows
    vtm_window.py      the window, grid, editor overlay, chrome
    Theme.xaml  ViewTemplateManager.xaml  ViewTemplateReport.xaml
    icon.png  bundle.yaml  CHANGELOG.md
    import_check.py    27 static rules, --selftest (27 breakages)
    bench_logic.py     221 logic checks incl. a stand-in window and contrast, --selftest (21)
```

## Bench

```
python import_check.py && python import_check.py --selftest
python bench_logic.py  && python bench_logic.py --selftest
```

## Open items

- Copy/paste is one level: no undo beyond Revert. Fill down (Ctrl+D) and the
  drag fill handle from Excel for Revit are not carried across yet.
- Applying re-reads the whole model, so a large model pauses briefly.
- Overrides that are not parameters — V/G per category, filters, view range —
  appear in Include ticks but have no value to show in Values.
- Linked models' templates are not listed. No Excel export yet; the Drawing
  Register's `xlsx_writer.py` would drop in.
- The column drag across the frozen block is the piece most worth watching in
  live use: the freeze is lifted only when the table is scrolled fully left.
