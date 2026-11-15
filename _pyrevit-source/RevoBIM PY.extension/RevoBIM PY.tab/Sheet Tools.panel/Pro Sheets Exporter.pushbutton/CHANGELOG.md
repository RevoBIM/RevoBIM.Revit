# Pro Sheets Exporter — changelog

Version lives in `ps_version.py`. Bumping that string is the only edit a
release needs; every window reads it from there and shows it top right.

## 1.56.1

### Back and Next show properly when the tool opens

- **Fixed:** the window could open with Back and Next squeezed off the
  right-hand end of the footer, and only come back after a resize.
- **The footer is now a DockPanel.** The buttons are docked to the right
  and always get their full width first, at any window size. The status
  line takes whatever space is left.
- **A long status message is shortened with "..."** instead of pushing
  the buttons out. Hover over it to read the whole message.
- **One more layout pass** runs once the window is first drawn. It does
  what the resize used to do.

### Bench

- New rule `footer_layout`, 68 in all. 7 new breakages, 630 in all.

## 1.56.0

### Express Export on the Selection tab

- **A green Express Export button**, with a printer icon, sits bottom
  right on the Selection tab, just left of Back.
- **It exports the ticked sheets straight away**, using the template's
  settings as they are loaded: formats, PDF / DWG / NWC / IFC options,
  naming and folders. It skips the Format and Create pages and asks
  nothing before, during or after the run.
  - **No confirmation.** The Write N files? check is skipped.
  - **Revit's own dialogs** are answered automatically during the run,
    whatever Suppress dialogs is set to.
  - **No report window at the end.** The summary goes on the status line
    and names the first few sheets that did not write. The issue folder
    opens if the template has Open folder after ticked.
  - **A print driver with no "Driver saves to" folder** would write
    nothing, so Express Export uses Revit's own PDF exporter instead and
    says so on the status line.
  - With nothing ticked and **Add to export** on, it writes the Document
    Register on its own, the same as Export does.
- **It won't start when it can't do anything:** nothing ticked, no format
  in the template, no root folder, or a folder it can't write to. The
  status line says which.
- **The window stays on Selection** while it runs. The progress bar and
  Stop are in the footer as usual.
- The full **Export** button on the Create tab still confirms first and
  shows the report, as before. Both buttons now start the run through the
  same code.

### Bench

- New rule `express_export`, 67 in all. 21 new breakages, 623 in all.

## 1.55.0

### Custom file names: Sheets and Views each have their own

- **The Custom File Name window now edits only the mode you are in.**
  Its title says which: *Custom File Name - Sheets* or *Custom File Name -
  Views*. Changing one leaves the other as it was.
- **Views start from the view's name.** Reset in the window goes back to
  that mode's own default: Sheet Number - Sheet Name for sheets, View Name
  for views.
- **Templates save both.** Sheets keep the same keys as before, so older
  templates still open with their naming. If an older template had a custom
  name, Views get a copy of it. If it had the stock name, Views start from
  the view name.

### Selection: grouped on the sheet series, and your sort is remembered

- **Out of the box, Sheets open grouped on the sheet series** once Setup
  names one. Naming or changing the series in Setup now makes it the first
  grouping straight away, whatever the list was sorted by before.
- **The sort and grouping you set are remembered on this machine** and come
  back next time you open the tool. This covers clicking or shift-clicking
  a heading, and turning grouping on or off. Sheets and Views are
  remembered separately.
  - What you set by hand wins over a template's saved sort when the tool
    opens. Picking a template from the list still applies that template's
    sort, which then becomes the one remembered.
  - **Reset columns** forgets it and goes back to the series.
  - A remembered parameter column that is no longer on the list is put back
    in front of Custom File Name, the same way the series column is.
- Ticking **Group** with nothing sorted now groups on the series, not the
  sheet number.

### Open sheets on the right-click

- **Selection** and **Document Register**: highlight one or more sheets
  (Ctrl- or Shift-click), right-click and choose **Open sheets**. In Views
  mode it says **Open views**.
  - Revit opens each one. The one highest in the list ends up in front.
  - The window then slides down to the bottom of the screen, so the sheets
    can be seen. Use the green up arrow to bring it back.
  - Right-clicking a sheet that isn't highlighted highlights just that one
    first, the way Excel does.
  - On the register, Open sheets comes first in the menu, above Assign
    revision. Headings and issue rows are left out.
  - While an export is running it waits, rather than taking Revit's event
    away from the export.

### Bench

- 3 new rules (`naming_modes`, `sort_memory`, `open_sheets`), 66 in all.
  46 new breakages, 602 in all.

## 1.54.0

### Document Register: toolbar

- **The words under Settings are gone.** The tabs already say what they
  are.
- **The Revision Manager button** is a little taller (56 px) and only as
  wide as its words, plus padding.
- **Refresh** now has an icon, and sits on the first row where the search
  box was, after the View/Sheet Set controls.
- **The search box** has moved top right, before Settings and the Revision
  Manager.
- The second row now fits on one line, the freeze button included.

### The register's name and logos in the heading

- **While the issue rows are frozen,** the heading's empty space above the
  drawing columns' names shows the **Document Register name**, with the
  **company logo** and the **client logo** below it, as in the Excel's
  title band.
  - All three come from Settings: the register title, the logo and the
    client logo.
  - The space runs from the left edge to just before the Issue Status
    names. The logos share it, each up to 120 px high, keeping their
    proportions. If the space is too small, the logos are left out
    rather than squashed.
  - Clicks pass straight through to the headings underneath.
- **Issue rows open frozen every time** the tool opens. Unfreezing lasts
  until the tool is closed.

### Heading colours on the Selection tab, greyscale by default

- **The Selection tab** has the same heading colour button, next to
  Collapse all, showing whenever grouping is on.
  - **Grey** alternates two greys run by run, so neighbouring groups still
    differ.
  - **Coloured** uses the trade ramps.
  - **Custom** uses picked colours, grey elsewhere.
- **Right-click a Selection group heading** for the same colour menu:
  swatches, Custom colour..., and the resets.
- **One set of colours per project.** A colour picked on either tab is
  used by both, keyed by the heading's name.
- **Both tabs start in Grey headers.** Each tab's own choice is then
  remembered.

### Bench

- **`register_brand` (new rule)** checks:
  - where the name and logos go, and how big the logos are;
  - frozen only, Settings as the source, never hit-tested, built with or
    without an issue block, and placed after the names' block;
  - the toolbar: search top right, the words under Settings hidden,
    Refresh in row one with an icon;
  - greyscale by default on both tabs;
  - the Selection tab's grey, custom and coloured runs, its menu, wiring
    and right-click, and colours shared both ways.
- **`register_issue_rows`:** opening frozen, and the Revision Manager
  button's new size.
- **`register_ticks`:** compares in the current mode.
- **Totals:** 63 rules and 556 breakages (15 new), every one proven
  caught.

## 1.53.0

### Document Register: toolbar tidied

- **Settings** and the line saying what the tabs and groups come from
  ("Tabs by BGL_Sheet Discipline · grouped by BGL_Sheet Series") now sit
  top right, beside the Revision Manager.
- **The Revision Manager button** is one row high (46 px), not two.
- **The heading colour button** has moved to the end of the second row,
  after Refresh. It now has colours of its own: filled with the four trade
  colours, with white text and a four-colour swatch icon, so it stands out
  from the grey chips.

### Issue rows: frozen by default, or scrolling

- **A new button**, beside the heading colour button, chooses where Issue
  Status, Issued To and Method sit. The choice is remembered on this
  machine.
  - **Frozen** (the default; the button is solid): in the heading, as in
    1.52.0. They stay in view as you scroll down.
  - **Scrolling** (a plain chip): the first rows of the drawing list,
    above the headings. They scroll away with the drawings, like Excel
    without freeze panes.
- **Scrolling rows look like the frozen block:**
  - the group named in Drawing No ("Issued to", "Issued method");
  - the column name in Drawing Title;
  - an **x** under a revision for a tick, as in the Excel, and the status
    as typed;
  - the field colour, bold, with the same medium and thin lines.
- **Editing scrolling rows:**
  - Click a tick cell to flip it.
  - Click a status cell to type one; the prompt shows the legend.
  - Changes are staged, washed green, and on the same Undo / Redo and
    Apply revisions as everywhere else.
- **Scrolling rows are never drawings:**
  - a search or filter never hides them;
  - the header tick, Shift+click, filter lists and Assign revision all
    pass them by;
  - their tick is hidden.

### Custom headers start from grey

- **In Custom headers, a heading you haven't coloured is grey,** not its
  trade colour. Only the headings you've coloured stand out. Resetting a
  heading puts it back to grey.

### Bench

- **`register_issue_rows` (new rule)** checks:
  - the x and status text, and the block only in the heading when frozen;
  - the rows' keys, order (above every heading), tick, lines and names,
    and that an issue row is never a drawing;
  - staged and stored values painted into the rows, with the wash;
  - a click flipping a tick, and a click outside the revisions doing
    nothing;
  - the rows added only when unfrozen;
  - every row loop passing them by, and no search hiding them;
  - a recycled row losing their lines;
  - frozen by default, remembered, and wired;
  - the toolbar: Settings beside a shorter Revision Manager, the colour
    and freeze buttons after Refresh, and the colour button in its own
    style.
- **`heading_modes`:** Custom is grey where nothing is picked.
- **Totals:** 62 rules and 541 breakages (18 new), every one proven
  caught.

## 1.52.0

### Document Register: a tidier heading

- **The drawing columns' names and filters sit at the foot of the
  headings,** right above the drawings: Drawing No, Drawing Title, Size,
  Scale, Rev, Seq No and Rev Date.
  - Each revision's letter and filter sit at the same height, so one line
    of names and filters runs across the whole grid.
- **The issue block sits above that line.** Its row names (Issue Status:,
  Issued to, Method) are now laid over the drawing headings' empty space,
  right-aligned against the revisions.
  - The separate names column has gone, so the revisions start straight
    after Rev Date, and no empty column runs down every drawing.
  - The names follow the headings as columns are resized. They stay put as
    the revisions scroll, because the drawing columns are frozen.
- **The block's border** now runs unbroken from the names across the last
  revision.

### Heading colours: Coloured, Grey or Custom

- **A new button** on the register's toolbar cycles the headings through
  three modes. The mode is remembered on this machine:
  - **Coloured headers:** the trade colours, as before.
  - **Grey headers:** plain greys, darker for a discipline and lighter for
    a series, in step with the theme.
  - **Custom headers:** a colour you pick for each heading. A heading
    you haven't coloured keeps its trade colour.
- **Right-click a heading** for its colour. The menu offers:
  - a row of 18 swatches (each trade's dark, middle and light, plus reds,
    yellow, teal and grey);
  - **Custom colour...** to type any #RRGGBB;
  - **Reset this heading's colour** and **Reset every heading colour**.
  - Picking a colour switches to Custom headers.
- **Picked colours are kept per project, by heading name.** A series
  keeps its colour on the All tab and on its discipline's tab.
- The **discipline tabs** follow the mode too, and heading text stays black
  or white, whichever reads better on every grey and swatch.

### Bench

- **`heading_modes` (new rule)** checks:
  - the cycle;
  - which colour a heading wears in each mode;
  - a grey per level per theme;
  - readable text on every grey and swatch;
  - typed colours checked;
  - picked colours surviving a save, with "=" in a heading's name;
  - against a stand-in: picking, the menu, and reset;
  - the wiring: headings, tabs, button, right-click, swatches closing the
    menu, and grey refreshed on a theme change.
- **`register_issue_block`** now checks:
  - the names and filters at the foot, under the block;
  - the names' placement, right-aligned against the revisions;
  - the canvas over the grid: no background, so clicks go through, and
    clipped to the grid;
  - that no names column comes back.
- **Totals:** 61 rules and 523 breakages (19 new), every one proven
  caught.

## 1.51.0

### Document Register: Issue Status and Issued To, live and editable

- **The Excel's issue block is now on the register itself,** as rows under
  the revision headings:
  - **Issue Status** first;
  - then each **Issued To** column (WLG, MCL, Asite...);
  - then each **Issued Method** column.
  - The values come from the Revision Manager's columns on each revision,
    the same data the Excel export prints.
  - Every column is shown, ticked anywhere or not, so it can be ticked from
    the register.
  - The block sits in the headings, so it stays in view as you scroll down
    and lines up with its revisions as you scroll across.
- **Row names** sit in a new column just left of the revisions:
  - Issue Status:, then the names right-aligned, as in the Excel;
  - "Issued to" and "Method" named once beside each group;
  - the column is frozen with the drawing columns.
  - Hovering over Issue Status: shows the status legend.
- **Edit it here:**
  - Tick or untick a box under a revision.
  - Type a status into the box and press Enter (Escape puts it back).
  - Where no Issue Status is stored, the box shows the status most of
    that revision's drawings carry, faintly.
- **Nothing is written until Apply revisions.** Each change is staged like
  the sheet revision changes:
  - washed green;
  - counted on the Apply button;
  - on the same Undo / Redo, Ctrl+Z / Ctrl+Y;
  - listed if you close with changes staged.
- **Apply** writes all the staged issue data in one transaction, in the
  order you made it, into the Revision Manager's store. It then pushes any
  of those columns mapped to a sheet or cloud parameter, as the Revision
  Manager's own Apply does.
- **Borders:** a medium border frames the block. Medium lines sit under
  Issue Status and between Issued To and Method, with thin lines between
  rows and revisions, matching your Excel.
- **A click on the block never includes the revision's drawings.** That
  only happens on a click on the heading itself.

### Bench

- **`register_issue_block` (new rule)** checks:
  - the block's order, and its dividing lines;
  - an empty Yes/No reading as unticked;
  - staged data played over the store in order, with refused values and
    gone columns or revisions reported rather than stored;
  - edits overlaying, an edit made and then reversed not showing as a
    change, counting as one change, and never painted as a sheet change;
  - a read dropping edits whose revision or column has gone;
  - the view staging, painting, washing, Undo / Redo and the Apply list,
    against a stand-in;
  - the wiring: Apply's own transaction and the parameter push, the
    headings leaving room, the frozen row names, clicks swallowed, and the
    border closed on the last revision.
- **Updated:** `register_staging`, for Apply's split and the new prune.
- **Totals:** 60 rules and 504 breakages (18 new), every one proven
  caught.

## 1.50.0

### Dark theme: Revit's own dark colours

- **The dark theme now uses Revit's dark colours,** measured from Revit's
  dark Project Browser. They are the same family Project Browser Pro uses,
  so the tool looks like part of Revit rather than a near-black window in
  front of it.

  | Part | Was | Now (Revit) |
  | --- | --- | --- |
  | Title bar (`BarBg`) | `#1C1C1F` | `#222933` |
  | Window body (`WindowBg`) | `#232326` | `#3C4454` |
  | Fields and search boxes (`FieldBg`) | `#1C1C1F` | `#2D3441` |
  | Cards and the active tab | `#2B2B2E` | `#353D4B` |
  | Grid headings (`HeaderBg`) | `#26262A` | `#323C48` |
  | Chips (`ChipBg`) | `#303035` | `#323C48` |
  | Hover | `#35353A` | `#444E5E` |
  | Selection | `#2B5473` | `#3A7392` (Revit's active blue) |
  | Edges and grid lines | `#3E3E42` / `#4A4A50` / `#333337` | `#4A5464` / `#515C6B` / `#46505F` |
  | Text / muted / disabled | `#E4E4E4` / `#9A9A9E` / `#5E5E64` | `#EEF0F4` / `#A4AAB1` / `#6E7684` |

- **Some colours were adjusted for the lighter body:**
  - The blue is a step brighter (`#5AAEEB`), so headings and links still
    read.
  - The green, orange and red washes were re-blended over the new body.
  - The Revision Manager's series chips and group cells are a step
    lighter, so they stand off the body.
- **The light theme is unchanged.** Auto still follows Revit's canvas.

### Shrink button: brought in line with the RevoBIM theme reference

The project's theme reference records what other tools learned building
the same drawer. The 1.49.0 shrink button now follows it:

- **A dialog arriving while its owner is shrunk** opens centred on the
  screen, not on the 42-pixel bar, where most of it would be off screen.
  An export report, for example, can turn up while Pro Sheets is put away.
- **While shrunk, Escape, Enter and F11 bring the window back.** Escape no
  longer reaches a dialog's Cancel, and F11 no longer tries to go full
  screen. **Ctrl+Shift+H** shrinks or brings back any window.
- **The body is held at its height for the slide** and clipped by the
  window, so a long grid isn't re-laid out on every frame. It is let go
  when the slide ends.
- **The shrunk bar isn't dragged while an export runs.** Dragging starts a
  modal loop, which mustn't run inside Revit's API context. The button
  itself still works.

### Bench

- **`revit_dark` (new rule)** checks:
  - the dark palette against Revit's measured colours (title bar, body,
    field, hover, selection);
  - that `Theme.xaml`'s defaults match the dark palette, so a window never
    flashes the old colours;
  - text contrast on every dark background: text at least 7:1, muted and
    blue at least 4:1.
- **`shrink_drawer`:**
  - Its stand-in timer no longer runs ticks inside `Start()`. A real
    DispatcherTimer doesn't, and a fake that does hides a tick that throws.
    A pump runs the ticks the way the dispatcher would, and the rule fails
    on anything that escapes.
  - New tests: the body is pinned for the slide and let go after; no drag
    mid-export, but a drag otherwise; dialog centring over a shrunk owner;
    Ctrl+Shift+H; Escape bringing the window back; a window that refuses a
    move mid-slide still finishing.
- **Updated breakage:** the `group_colours` one, for the lighter dark cell
  tone.
- **Totals:** 59 rules and 486 breakages (12 new), every one proven
  caught.

## 1.49.0

### Shrink any window to its title bar

- **A shrink button now sits top right on every Pro Sheets window,**
  before full screen and close. That covers the main window, the Revision
  Manager, setup, and every dialog (12 windows).
- **Press it** and the window slides down to the bottom of its screen, like
  a drawer closing, until only its title bar is left, floating just above
  the taskbar. Revit can be seen behind it.
- **The button turns into a green up arrow.** Press it, or double-click
  the bar, and the window slides back to where it was, at the same size.
- **While it is shrunk:**
  - the bar can be dragged to move it;
  - it can't be resized, stretched or made full screen;
  - the close button still works.
- **A dialog takes the window under it down too.** Shrink a dialog
  opened from the main window and both shrink, the dialog's bar stacked
  above the main window's. Expanding the dialog, or closing it, brings the
  main window back.
  - A dialog that waits for an answer keeps Revit locked until it's
    answered, as before. Shrinking it lets you see the model, not edit it.
    The main window and the standalone Revision Manager leave Revit fully
    usable.
- **The size is remembered from the window, not the bar,** so closing it
  shrunk doesn't make it open 42 pixels high next time.
- **How:**
  - `ps_ui.Chrome` wires `ShrinkButton` on every window and animates `Top`
    and `Height` on a 15 ms DispatcherTimer for 0.28 s, easing out.
  - At the bottom, everything but the title bar is collapsed (the resize
    grips too) and the bar's corners are rounded.
  - The `ShrinkButton` style in `Theme.xaml` swaps its glyph to the green
    arrow when Chrome sets `Tag` to `shrunk`.

### Bench

- **`shrink_drawer` (new rule)** checks:
  - every layout has the button in its title bar, before full screen and
    close, in the right style;
  - the style's green up arrow is a ContentTemplate;
  - the wiring;
  - against a stand-in window, with a timer and clock driven by the test:
    - it slides down in steps to a 42-pixel bar on the bottom of the
      screen;
    - MinHeight is cleared and the body collapsed;
    - the arrow turns green, and the right size is remembered;
    - edge, full screen and resize are ignored while shrunk;
    - it slides back to the exact bounds;
    - a double-click on the bar brings it back;
    - a dialog takes its owner down, stacked above it, and brings it back
      on expand and on close;
    - `restore_now` works;
  - the main window remembers its true size.
- **Totals:** 58 rules and 474 breakages (25 new), every one proven
  caught.

## 1.48.0

### Heading colours from Project Browser Pro

- **Headings now use Project Browser Pro's colours,** so the two tools look
  like one product. This covers:
  - the Document Register's discipline and series headings;
  - the discipline tabs along the bottom of the register;
  - the group headings on the Selection tab.
- **Each trade has its own ramp**, and the ramps are the same on both
  themes:
  - electrical: greens (`#17572B` to `#A9DFA6`);
  - mechanical: blues (`#173F78` to `#A9D0F4`);
  - plumbing and public health: browns (`#4F3220` to `#D9B892`);
  - everything else: violets (`#4B2A6E` to `#CDB2EA`).
- **The trade comes from the heading's name**, matched on whole words.
  For example, Fire Alarm is electrical, Fire Protection is "other",
  Chilled Water is mechanical and Hot Water is plumbing.
  - A series whose name names no trade takes its discipline's.
  - On a discipline's own tab, the series take that tab's trade.
- **Shading:** headings of one trade under the same parent run dark to
  light down the list.
  - Disciplines sit at the dark end of the ramp (0 to 0.3).
  - Series sit in the lighter part (0.38 to 0.95), so a series reads as
    belonging to the discipline above it.
  - The Selection tab has one level of grouping, so it uses the whole
    ramp.
- **Heading text is black or white**, whichever has the better contrast.
  Every shade passes WCAG AA (4.5:1).
- **Headings are rounded pills with a drop shadow,** as in the browser.
  - The shadow is on its own layer behind the text, so the text is not
    shadowed.
  - Grid lines and the blue revision divider no longer cross a heading.
- **Rows under a heading** carry a faint wash of its colour.
- **Each discipline tab** has a tint of its colour, plus a solid swatch in
  the colour its heading wears on the All tab.
- **New module:** `ps_ramp.py` holds the ramps, the ladder, the trade
  words, the planning and the contrast.

### Express print from Project Browser Pro

- **Project Browser Pro's Express button now prints with no window.** It
  uses the sheets selected in the browser and Pro Sheets' last template.
  The browser's progress strip follows each file, then opens the folder.
- **`ps_express.py`** answers the browser's hand-off. `script.py` checks
  it right after the document checks, before anything is built.
- **The window opens as normal** for:
  - no hand-off;
  - a stale hand-off, or one for another project;
  - a plain Print;
  - no Project Browser Pro installed.
- **On an Express request, Pro Sheets:**
  - builds its window hidden, with the first-run setup check held off;
  - forces Sheets mode;
  - ticks exactly the sheets sent, matched by UniqueId. The sheet number
    is a fallback that only ever matches sheets. The template's own ticks
    are cleared.
  - swaps a print driver with no "Driver saves to" folder for Revit's own
    PDF exporter;
  - suppresses Revit's dialogs, and always hands that back;
  - runs the window's own export, with no confirmation and no report
    window;
  - reports back the folder, the file count and one line on anything that
    did not write.
- **Refusals and failures are always reported back**, so the browser
  never waits for its timeout:
  - no sheet found;
  - no format ticked;
  - nothing to export;
  - an export folder that cannot be written to;
  - Pro Sheets already exporting;
  - any error.
- **`pbp_handoff` is imported from Project Browser Pro's own folder**,
  never copied. Pro Sheets looks in the Management panel first, then
  anywhere under the tab.
  - The folder is appended to `sys.path`, never inserted, so Pro Sheets'
    own modules always win a shared name.
- **Log:** `%APPDATA%\RevoBIM\logs\pro_sheets_express.txt`.

### Bench

- **`express_print` (new rule)** drives `ps_express` against a stand-in
  window and a stand-in hand-off. It checks:
  - `script.py` asks before building, and stops when answered;
  - UniqueId matching, with a number fallback that only matches sheets;
  - template ticks don't leak;
  - a plain Print opens the window;
  - no browser opens the window;
  - an error is reported through `finish`;
  - the browser is found outside the Management panel;
  - its folder is appended to `sys.path`;
  - no report window is shown;
  - suppression is always handed back;
  - the setup check is held off for the build and put back;
  - a driver with no staging folder is swapped;
  - progress reaches the browser;
  - refusals carry a reason;
  - the hidden window is closed.
  - It also checks that every `ps_window` method express relies on still
    exists.
- **`heading_ramps` (new rule)** checks:
  - the ramps and ladder against Project Browser Pro's;
  - trade words against a table of real names;
  - AA contrast on every shade;
  - the planning, including the All tab's disciplines matching the tab
    strip and series inheriting a trade;
  - the wiring in both grids;
  - the pill template.
- **Totals:** 57 rules and 449 breakages (35 new), every one proven
  caught.

## 1.47.0

### Every resizable window: double-click the top or bottom edge

- **Double-click the top or bottom edge** of any Pro Sheets window you can
  resize, and it stretches to the full height of its screen. Its width and
  left edge stay where they are. Double-click either edge again to put it
  back.
  - This is what Windows does for its own windows. These windows draw
    their own edges, so it had to be added.
  - The corners still only resize.
  - A window in full screen is left alone; it fills the screen already.
- **It applies to:**
  - the main window;
  - the Revision Manager;
  - the order, pick, custom name, token and prompt windows.
- **The Revision Manager's bottom bar** double-click (1.46.0) now uses the
  same toggle, so a stretch from the bar can be undone from an edge, and
  the other way round.

### Bench

- **`register_tidp` gains tests for the edge double-click,** run against a
  stand-in window:
  - a single click does nothing;
  - a double-click stretches the window;
  - a second double-click puts it back;
  - full screen is left alone;
  - the edges and the bottom bar share one toggle.
- **Breakages:** 4 new ones, for 414 in total, every one proven caught.

## 1.46.0

### Document Register: tick the All tab into the export

- **The All tab** on the strip along the bottom now has a tick box, like
  the discipline tabs.
- **Ticked:** the Excel export gets an **All** worksheet, placed first,
  holding every drawing in the register.
  - Each discipline has its own heading.
  - Each sheet series is separated by a blank row.
- **The per-discipline worksheets** still follow their own ticks.
- **Unticked:** it is off until you tick it, so the export is the same as
  before.
- **Remembered:** the tick is kept per project, with the discipline ticks.
- **The logo** in the title band now starts a little further right, so the
  longer RD9 title never runs under it.

### Revision Manager: only as wide as it needs

- **The window opens at the width its columns need.** Description is
  sized to its longest text, between 240 and 480. The window is centred
  on the screen Revit is on. (1.45.0 stretched it across the whole
  screen.)
- **On a screen too narrow for every column,** the window stops at the
  screen's edge and a scroll bar along the bottom of the grid takes the
  rest. Description keeps at least 240 rather than being squeezed.
- **The first column (Sequence) stays put** while the rest scroll, so each
  row can still be told apart.
- **The window opens hidden until it is sized,** so it does not appear at
  one width and jump to another. It is always shown, even if the sizing
  fails.
- **Double-click the bar along the bottom** - not its buttons - and the
  window stretches to the full height of its screen. Double-click it again
  to put it back.

### Revision Manager: clouds in views on no sheet

- **Why a revision "on 0 sheets" can still be in use.** Its clouds can sit
  in views that aren't placed on any sheet. A view counts as on a sheet
  when:
  - it is a sheet itself;
  - it is placed on a sheet;
  - it is the parent of a placed dependent view.
- **A new Clouds off sheets column** counts those clouds per revision.
  - It is orange where there are some, and the tooltip lists the views.
  - It sits after Sheet series, even in a saved column order.
- **Delete's warning** now says how many of the revision's clouds are in
  views on no sheet, and where to find them.
- **Right-click a revision** (or several) and choose **Find clouds on
  views**.
  - Every view holding their clouds opens, sheets included. The first view
    ends up in front.
  - In each view the clouds are isolated with Revit's own Temporary
    Hide/Isolate, so the sunglasses reset it.
  - With more than 12 views to open, it asks first.
  - The menu also has Delete or Restore.
- **It works from either entry point.**
  - From the manager's own button, the views open while the manager stays
    open.
  - From the Document Register, they open as the manager closes. Staged
    changes can be applied on the way out, or left.

### Excel register: Issued to borders, logo order

- **The Issued to block** is bordered as on the office's own form:
  - a heavy line round it;
  - a heavy line between "Issued to:" and the names;
  - the issue columns carried through it on thin lines.
- **The logos** are swapped: the company logo comes first after the
  title, and the client's sits to its right.

### Bench

- **`register_tidp` gains tests for:**
  - the window's width: needed, capped at the screen, kept above the
    minimum;
  - Description's opening width;
  - the frozen first column;
  - the window always being shown;
  - the bottom bar stretching the window and putting it back;
  - clouds by view and the off-sheet count;
  - the views to open;
  - show_clouds run against a fake Revit: isolation, one transaction,
    opening order and a missing view;
  - the Clouds off sheets column's place;
  - the Find hand-off from both entry points;
  - the Issued to block's borders;
  - the logo order;
  - the All tick's default, ticking it and unticking it;
  - All coming first among the worksheets;
  - one section per discipline on the All worksheet, with its series;
  - the drawings on it, each under its discipline's heading.
- **Breakages:**
  - 20 new ones, for 410 in total, every one proven caught;
  - one older Excel breakage re-anchored;
  - the 1.45.0 full-width breakage replaced.

## 1.45.0

### Revision Manager: every column under a coloured, merged band

- **A strip of coloured bands sits above the headings.** Each band runs
  merged across all the columns of one kind, with its name centred:
  - **STANDARD** (purple): Revit's own revision fields, plus Used on sheets
    and Sheet series;
  - **CUSTOM** (green): Revision notes and any other column of your own;
  - **ISSUE STATUS** (teal);
  - **ISSUED TO** (blue);
  - **ISSUED METHOD** (orange).
- **The + on the CUSTOM, ISSUED TO and ISSUED METHOD bands** adds a column of
  that kind.
- **The bands follow the columns.** They are redrawn from the columns' own
  widths, so they stay lined up when a column is resized, dragged or
  scrolled. If a drag splits a kind, it gets one band per stretch.

### Revision Manager: opens full width

- **The window opens across the full width of the screen Revit is on.**
  Every column, Issued To and Issued Method included, is in view without
  scrolling.
- **Its height stays as it was**, centred top to bottom. It can still be
  resized, or made full screen, as before.

### New columns: Custom, Issued To or Issued Method

- **The column dialog's first choice is the type:**
  - **Custom:** any type of data;
  - **Issued To:** Yes/No;
  - **Issued Method:** Yes/No.
- **Method is renamed Issued Method** throughout. New models start with
  Issued Method 1 and 2. A model that already stored "Method 1" keeps its
  own names.

### Excel register: the RD9 title again

- **The template is back to "RD9 - Document Register & Issue Sheet".**
  Nothing else in it changed.
- **Settings v6** puts the title back only where 1.44.0 had set it and
  nobody had changed it since.

### Bench

- **`register_tidp`** gains tests for:
  - the band runs;
  - which band each column sits under;
  - the five band colours;
  - the full-width placement;
  - the three column types.
- **Breakages:** 8 new ones, for 390 in total, every one proven caught.

## 1.44.0

### Document Register Excel: the TIDP form

The Excel register is now built to the office's own *BGL Family Container -
Document Register* template, cell for cell. It still has one worksheet per
discipline.

**What changed from the RD9 form:**

- **Title.** TIDP - Task Information Delivery Plan, then the logos.
- **Current Rev** moves from the far right to the orange column E, just
  before the issues. Its codes are in Arial bold.
- **Issue dates** run up each issue column as one rotated date (dd/mm/yy),
  with Day / Month / Year beside them.
- **Issue Status row.** Each issue's status (S3, S4...) comes from the
  Revision Manager's new **Issue Status** column. The legend is now S0 = WIP
  to S5 = Authorisation.
- **Issued to rows.** One row per **Issued To** column of the Revision
  Manager, then one per **Method** column, with an x wherever the revision
  is ticked.
  - A heavy line separates the two groups.
  - A column that no issue on that worksheet is ticked in is left off.
- **Headings.** Document No / Document Title / Sheet Size / Scale / Current
  Rev / Document Issued.
- **Drawings.** The discipline's name sits over the drawings, and a blank
  row separates each sheet series.
- **Look.** Calibri throughout, with no status shading, and the template's
  widths, heights, borders and print setup.

### Revision Manager: Issue Status, Issued To and Method

- **Two groups of Yes/No columns** under coloured bands across the top of
  their headings. **ISSUED TO** is blue and **METHOD** is orange.
  - The defaults are Issued To 1, 2 and 3, and Method 1 and 2. Rename them
    with the pencil.
  - The **+** on each band adds another column to that group.
  - A group's columns always stay side by side, even after dragging.
- **The column dialog has a Group choice:** None, Issued To or Method. A
  grouped column is always Yes/No. A Yes/No column can be moved between
  the groups.
- **Issue Status** is a text column kept with each revision.
  - Where it is empty, it is filled from the sheets carrying the revision:
    the most common value of the sheet status parameter (BGL_Sheet Status).
  - The fill is staged in green, so **Apply keeps it**. An old issue then
    keeps its status after the sheets move on.
  - You can type over it.
- **Ticking several revisions at once.** Select several rows and click a
  tick in one of them: every selected revision takes it. This already worked
  for the manager's own Yes/No columns, so it works for the new groups too.
- **Existing models** get the Issue Status, Issued To and Method columns
  added once. A column of the same name already there is left alone.

### Settings

- **Sheet status:** the parameter each revision's Issue Status is filled
  from. The default is BGL_Sheet Status.
- **Scale:** choose how the register reports scale.
  - **From a parameter.** The default is BGL_Title Block Scale Text, read
    from the sheet and then from its title block. A sheet with nothing in
    the parameter falls back to Revit's own scale.
  - **Revit's own.** The scales of the views placed on the sheet.
- **Current revision:** the heading of the orange column, Current Rev by
  default. Blank leaves the column off.
- **Issued to:** the typed list has gone. The rows come from the Revision
  Manager.
- **Settings v5** moves the RD9 title, legend and "Asite Snapshot" heading
  to the TIDP ones, but only where they had never been changed.

### Document Register page

- **Apply revisions** moves to the bottom right. It is green once anything
  is staged and grey until then.
- **Discard changes** sits to its left, in red. It too is grey until
  something is staged.
- **Undo and Redo** stay at the top left.

### Bench

- **New rule `register_tidp`** (55 rules) covers:
  - the grouped columns: storing them, the v1 upgrade, layout order and
    the Issued to rows;
  - Issue Status: the fill from sheets, staging, stored-before-live and
    the most common status;
  - group membership;
  - scale: sheet, then title block, then Revit;
  - the band marks and keeping groups together;
  - the settings v5 migration;
  - the bottom-right Apply and Discard.
- **`register_xlsx`** is rewritten for the TIDP form, cell by cell:
  - the values;
  - the orange, blue and unshaded fills;
  - the rotation;
  - the heavy lines;
  - the footer.
- **Breakages:**
  - 19 new ones, for 382 in total, every one proven caught;
  - three older Excel breakages re-aimed at the new form.

## 1.43.0

### Document Register: revision changes wait for Apply

- **Staged, not written.** These are now staged in the grid and written
  only when you press **Apply revisions**:
  - Assign revision to selected;
  - Change revision;
  - Remove revision;
  - moving the picked cells onto a revision you have just created.
- **What staged cells look like:**
  - a cell gaining a revision shows a green **+**;
  - a cell losing one is red and struck through.
- **Further edits build on what is staged.** A cell staged on can be
  picked and changed again. A cell staged off cannot be picked.
- **Undo / Redo** sit at the top left of the register. **Ctrl+Z** undoes
  and **Ctrl+Y** redoes. In a search box, Ctrl+Z still undoes your typing.
  A new edit after an undo clears what could be redone.
- **Apply revisions (n)** is solid orange while anything is staged; n is
  the number of cells. It writes the edits in the order you made them,
  each in its own transaction, so one refusal does not undo the rest.
  - With removals staged, it asks first: "Deletes the rev clouds from all
    associated views on the sheet".
  - A cloud that also shows on a sheet you did not stage is asked about
    once, for all the edits together.
  - Whatever Revit refuses is listed afterwards.
- **Discard** throws away every staged edit; Revit is never touched.
- **Closing the window** with edits staged asks before throwing them away.
- **Refresh, the Revision Manager and the Edit window** keep your staged
  edits. An edit whose revision or sheet has gone from the model is
  dropped.
- **Still written straight away:**
  - making a revision, from the + or from Create new revision;
  - editing one in the Edit revision window.
- **The right-click menu** offers Apply revisions and Undo while edits are
  staged.
- **Excel** writes the model as it is, so staged edits appear only after
  Apply.

### Isolate shows sheets outside the set

- **All sheets switches on when needed.** You may click a revision heading,
  or use Isolate, while on **Included only**. If any sheet carrying that
  revision is not in the set, the register switches to **All sheets** so
  you can find it, and tells you how many sheets that was.

### Add revision window

- **The Sequence box is taller** (44px, with less padding), so the 18pt
  number is no longer cropped.

### Bench

- **New rule `register_staging`** (54 rules) covers:
  - what staged edits show, played in order;
  - Undo and Redo;
  - edits dropped after a read;
  - painting and un-painting the grid, through the register's own code;
  - isolating outside the set;
  - Ctrl+Z / Ctrl+Y;
  - the guard on closing the window;
  - the Sequence box height.
- **Breakages:**
  - 18 new ones, for 363 in total, every one proven caught;
  - three older ones re-anchored onto Apply revisions.

## 1.42.0

### Document Register: revision columns

- **A click on a revision's heading isolates it.** It no longer ticks or
  unticks the sheets. Only the sheets carrying that revision show, and the
  column is highlighted. Click the heading again to show every sheet.
  Ctrl+click adds another revision to the isolation, or takes one out.
- **A dividing line** (blue, 3px) now separates the drawing columns from the
  revisions. It is frozen with the drawing columns, so it stays put while
  the revisions scroll.
- **A green + after the last revision** opens the Add revision window. The
  revision is made as soon as you press Add. Every revision then shows, with
  the new column washed green.

### Document Register: highlighted sheets

- **Assign revision to selected.** Highlight sheets and a blue toolset
  appears at the top with the count and the **Assign revision to
  selected...** button. Pick a revision and it is added to each sheet by
  hand, as Revit's Revisions on Sheet does, in one transaction.
  - A sheet already carrying the revision is left as it is.
  - An issued revision cannot be chosen, because Revit locks it.
  - Anything left out is listed, with the reason.

### Document Register: the right-click menu

A right-click picks what is under the pointer first, then opens a themed
menu built from what is highlighted and picked:

- **Highlighted sheets:** Assign revision to N selected sheets...
- **A revision heading, or a revision cell:** Edit revision... With several
  revisions picked, this becomes "Edit N revisions in the Revision
  Manager...".
- **Revision cells:** Create new revision..., Change revision... and Remove
  revision...
- **A picked heading:** Isolate sheets with this revision, or Show all
  sheets when they are already isolated.
- **Always:** New revision... and Revision Manager...

### Document Register: editing revisions

- **Edit revision, with one revision picked,** opens the Edit revision
  window rather than the manager. It is the Add revision window in edit
  mode:
  - every field and custom column is filled in;
  - the sequence is fixed;
  - the button reads Apply.

  Apply writes the change and the register reads the model again. Issued
  is staged in Revit's order: a tick coming off goes first, so the rest can
  change, and a tick going on goes last.
- **With several revisions picked,** Edit opens the Revision Manager on
  them, as before.
- **Revision Manager from the register** now opens on the revision picked
  there, whether by its column or by a cell. Only when nothing is picked
  does it fall back to a cloud selected in Revit.

### Document Register: the tabs along the bottom

- Bold on every tab, 13pt, with more padding.
- Each tab is raised on a soft shadow that tightens when pressed. The live
  tab sits flatter, with a blue edge and bar.
- **Icons**, drawn in the tab's own text colour. They are matched by the
  tab's name, in any case:
  - **All**: a grid of four.
  - **Electrical**: a lightning bolt.
  - **Mechanical**: a fan.
  - **Coordination** (or Co-ordination): two linked rings.
  - **Builderswork** (or Builders Work, BWIC): a brick wall.

### Selection tab, Views mode: the Project Browser's columns

- **The Views list starts with the columns of your Project Browser.** It
  reads the project's current browser organisation for views and gives each
  folder parameter a column, top level first (for example Discipline, then
  Sub-Discipline). Then it adds View Type, because Revit always files views
  by type under the organisation's own folders.
- **The list is sorted the same way:** by the first folder, then the second,
  then the view type, then the view name. Grouping follows the first folder.
- If a template saved for Views is missing those columns, they are put back
  when the list opens with no sort of its own.
- An organisation that groups by nothing gives just the View Type column.
  If the organisation cannot be read on the Revit in use, nothing is added.

### Bench

- **New rule `register_tools`** (53 rules) covers:
  - the tab icons and the tab styles;
  - Assign, run against a fake model;
  - the Edit window's staging order;
  - the menu, picks and Edit routing, driven through the register's own
    methods;
  - the divider, the + and the Revision Manager focus;
  - the Views columns and sort.
- **Breakages:** 25 new ones, for 345 in total, every one proven caught.
- **Breakages updated.**
  - Re-anchored: three older ones whose text now also matched new code
    first (mode_columns, register_picks and revision_add). They are
    anchored to the code they were written for.
  - Replaced: the register_ticks "date click only ever includes"
    breakage. The heading no longer ticks, so it now breaks the second
    click that clears the isolation.

## 1.41.0

### Fixed: Change revision and Remove revision refusing almost every cloud

- **The message.** *"3 clouds for it also show on sheets not picked, so they
  were left and the sheet still carries it"*.
- **The cause.** To avoid changing a cloud that shows on a sheet you did not
  pick, the tool asked Revit which sheets each cloud reaches
  (`RevisionCloud.GetSheetIds`). That call lists every sheet a cloud **may**
  appear on. A cloud in a parent view was therefore counted on the sheet of
  **every dependent view** of that parent, inside its crop or not, and so
  nearly every cloud in a model split into dependent views was refused.
- **The fix - your suggestion.** For each sheet the tool now looks inside:
  the sheet itself, then every view placed on it. In each one it collects
  the clouds Revit says that view actually shows. A cloud counts as being on
  a sheet only if it was found there. Revit's "may appear" list is now only
  a shortlist of where to look, and a fallback if a view cannot be looked
  into.
- **A cloud that really is on another sheet** - drawn in a view placed on
  two sheets, like a legend - is no longer a dead end. You are told which
  sheets, and asked: **Change on those sheets too** or **Leave them**.
  Revit has no way to change a cloud for one sheet only, so this is the
  real choice. If you say yes, a second pass does just the cells still left.

### Document Register: Create new revision, Edit revision

The picked-cell toolset now has four actions.

- **Create new revision...** opens the Add revision window with the
  sequence **just after the revision picked**. Fill it in and press Add; the
  revision is created, then every picked cell is moved onto it - on the
  sheet, and in its clouds - exactly as Change revision does. Its column
  shows green. It works across many cells and sheets at once.
- **Edit revision...** opens the Revision Manager on the picked revisions,
  selected and in the middle of the list.
- **Change revision...** and **Remove revision...**, now working (above).

### Revision Manager

- **Opens on a selected revision cloud.** Select a cloud in Revit, open the
  manager (from its button or from the register) and it goes to that
  revision.
- **One value into several revisions.** Select several rows and edit a cell
  in any of them: the value goes into all of them. This works for Description,
  Issued to, Issued by, Show, Numbering, Issued and your own columns. The
  rows stay selected while you type.
  - **The Date column is the exception** and is set one revision at a time.
  - An issued revision refuses for itself, and the rest still take the value.
- **Filter revisions on current sheet.**
  - Greyed out when Revit is not on a sheet, lit when it is, and solid
    orange while the filter is on.
  - Press it to show only the revisions on the sheet that is open.
  - Change sheet in Revit and it re-filters by itself. On a view that is not
    a sheet, every revision shows until you open a sheet again.
  - A revision added and not yet applied always stays in view.

### Bench

- New rule **`revision_sheets`**. It starts from your exact failure: a
  model where two clouds in one parent view are each visible in a different
  dependent view's sheet, and Revit says both may appear on all three
  sheets. It also covers a legend that is genuinely on two sheets, asking
  first then taking the shared cloud, Remove the same way, Create new
  (including when no revision is made), several revisions at once, the
  sheet filter, and the wiring.
- The method checks now cut exactly one method. 1.40.0 showed how a method
  added in between can make a check pass for the wrong reason.
- 22 new breakages, all caught; 320 in all, 52 rules.

## 1.40.0

### Fixed: Change revision on sheet failed on Revit 2026 and later

- **The error.** *"Nothing was changed: Multiple targets could match:
  ElementId(BuiltInParameter), ElementId(BuiltInCategory),
  ElementId(Int64)"*. From Revit 2026, `ElementId` is built from a
  BuiltInCategory, a BuiltInParameter or an Int64, and a plain number fits
  all three, so IronPython refuses to pick one.
- **Wider than it looked.** Every Revision Manager write builds its
  `ElementId`s through the same call, so Apply would have failed the same
  way on 2026 and later.
- **The fix.** One helper, `ps_model.make_id`, now builds every `ElementId`
  in the tool. It says Int64 outright, and falls back to Int32 on releases
  older than 2024, which have no Int64 version.
- **Bench.** Building an `ElementId` anywhere else now fails the bench. The
  helper is also tested against a stand-in for Revit 2026 (which throws
  exactly this error on a plain number) and for 2023 (Int32 only).

### Revision Manager: Add opens a dialog

- **Add revision** now opens a window. It asks for every property Revit
  holds for a revision - Numbering, Date, Description, Issued to, Issued by,
  Show, Issued - plus your own columns.
- **Sequence comes first**, washed and edged in orange so it is the field
  you look at. It defaults to last. Type a number or use - and +. A note
  underneath says what will happen, e.g. *"Goes in at sequence 3. "Stage 3"
  moves down to 4, and the 2 after it each move down one."*
- **Add** puts the revision at that sequence, and the revision that had it
  moves down a slot. A row already staged to delete keeps its place but is
  not counted.
- **The new row is green**, washed and edged, and the grid **centres on
  it**. It is left unselected on purpose: a selected row is drawn blue. It
  is created on Apply, as before.
- If you tick **Issued** for a new revision, its other fields are written
  first, then it is issued - Revit locks an issued revision.

### Document Register: show all revisions; new ones in green

- **Show all revisions** replaces the *Hide unused revisions* tick box. It
  is a button that goes solid orange while every revision in the project is
  showing. The Excel export follows it, as before.
- **After creating revisions in the Revision Manager** (opened from the
  register), the register switches to showing every revision - a new one is
  on no sheet yet, so it would otherwise be hidden - and **washes each new
  revision's column green**. The green lasts until the register is next
  read. A column you have picked (orange) still shows orange.

### Document Register: a toolset for picked revision cells

- Pick revision cells as before. A toolset appears beside the toolbar
  saying how many cells on how many sheets, with two actions:
  - **Change revision...** - as in 1.39.0, now working on 2026+.
  - **Remove revision...** - asks first: *"Deletes the rev clouds from all
    associated views on the sheet."* It also takes off a revision added to
    the sheet by hand.
- **The same safeguards as Change:**
  - a cloud that also shows on a sheet you did not pick is **left**, and
    listed afterwards, because deleting it would take the revision off that
    sheet too;
  - issued revisions are left, because Revit locks them;
  - each sheet and cloud is tried on its own, in one transaction, through
    the external event.

### Bench

- New rule **`revision_add`**:
  - where a new revision goes, including around a row staged to go;
  - what the dialog reads and says;
  - the manager's green row, centring and Add wiring;
  - the register's show-all and green new columns, and orange beating
    green;
  - the toolset and Remove's prompt;
  - Remove run end to end against the stand-in model - which clouds are
    deleted, which are kept, the sheet's own revisions, one committed
    transaction.
- `api_version_imports` now also covers `ElementId`.
- 20 new breakages, all caught; 298 in all, 51 rules.

## 1.39.0

### Document Register: pick a revision, isolate its sheets

- **The sequence number at the top of each revision column is now a
  button.** Click it to pick that revision: the number turns solid orange
  and the column washes orange. **Ctrl+click** picks several, **Shift+click**
  a run of them; a second plain click lets it go.
- **Isolate sheets with this revision** lights up (solid orange) once a
  revision is picked. Press it and only the sheets carrying the picked
  revision show - with several picked, sheets carrying **any** of them. The
  button then reads **Show all sheets**; press it to bring the rest back.
  **Reset filters** clears it too. It is a view only - nothing in the model
  changes.
- **Clicking the date still does what it did**: includes every drawing on
  the tab carrying that revision. Only the sequence number picks.

### Document Register: change the revision on sheets

- **Click a revision cell** (one with a revision in it) to pick it: it turns
  into a solid orange chip. **Ctrl+click** for more, **Shift+click** for a
  block - empty cells in a block are skipped, since they have no revision to
  change. **Escape** lets go of everything picked.
- **Change revision on sheet** lights up and shows the count. It opens a
  list of every revision in the project to pick the new one, with a search
  box. Issued revisions are listed but greyed out - Revit locks them.
- **It follows the revision to both places it can live on a sheet:**
  - **added by hand** in Revit's Revisions on Sheet - swapped on the sheet;
  - **drawn as revision clouds** - on the sheet or in a view placed on it -
    the clouds are moved to the new revision.
- **A cloud that also shows on a sheet you did not pick is left alone.** A
  cloud in a legend placed on twenty sheets, moved for the two you picked,
  would quietly change the other eighteen. Those are listed afterwards with
  the sheet and why, so you can pick the rest or move the cloud.
- Issued revisions are never changed, and nothing is moved onto one. Each
  sheet and cloud is tried on its own, so one Revit refuses does not stop
  the rest. One transaction, through the external event, then the register
  reads the model again.
- Picking a cell is the register's own state on top of the grid: clicking
  still selects the row exactly as before, so ticks and the multi-row
  include are unchanged.

### The whole tool: - and +

- **- 100% +** in the header, before Set up. Smaller fits more on a small
  screen; bigger is easier to read. From 60% to 160%; click the percentage
  to go back to 100%. **Ctrl+minus**, **Ctrl+plus** and **Ctrl+0** do the
  same. Kept per machine (`ui_scale`).
- It is a layout scale, not a picture scale: at 80% the window lays out as
  if it were a quarter bigger and draws that to fit, so you genuinely see
  more columns and rows rather than the same ones smaller.
- `ps_ui.Zoom` is reusable: any window with ZoomOutButton, ZoomResetButton
  and ZoomInButton gets it in one line.

### Bench

- New rule **`register_picks`**, 25 breakages:
  - the click rules for columns and cells (Excel's plain/Ctrl/Shift, a
    second click letting go, empty cells never picked);
  - Isolate keeping sheets with ANY picked revision;
  - the swap plan - by hand, clouds, the shared cloud left and reported,
    issued revisions on either side, a cell already that revision, a sheet
    the revision has left;
  - **the swap executor run end to end** against a stand-in model: the
    sheets' own revisions, which clouds move and which stay, and one
    committed transaction;
  - the revision list (issued greyed, search);
  - the size steps, and that it is a LayoutTransform;
  - and the wiring - the sequence number a Button of its own so its click
    never falls through to the date's include, the picked chip styled last,
    the click not swallowed, the change going through the external event.
- Writing them found three weak checks of my own, now fixed: two tests that
  passed whether or not the guard they tested was there, and one that
  would have accepted the Revision Manager's identical line in place of
  this feature's.
- 278 breakages, 50 rules, all firing.

## 1.38.0

### The Revision Manager is modeless, and follows the selection

**Revit stays usable while the manager is open** - its own ribbon button
only. Pan, zoom, change view, pick things, keep modelling. The manager sits
in front of Revit and stays where you put it.

- **Picking a revision cloud takes the list to its revision.** Click a cloud
  in any view and the manager selects that revision's row and scrolls to it,
  with its sequence and description in the status line. Pick several clouds
  and it goes to the first one's revision.
- **Following can be turned off.** A chip in the left panel reads
  **Following selection** (orange) or **Not following selection**. The
  choice is remembered (`rev_follow_selection`).
- **It holds off while you are typing.** A cell being edited is never yanked
  out from under you; following resumes once the edit is committed.
- **Apply no longer closes the window.** It writes, then refreshes the
  manager from the model - your column order, widths, value filters and
  theme all stay as they were. **Setup > Keep the Revision Manager open
  after Apply** (the old "open again after Apply") still decides: untick it
  and the window closes once the change is in.
- **One manager at a time.** Pressing the button again brings the open one
  forward rather than opening a second over the same model.

Opened from **Pro Sheets Exporter > Document Register**, the manager is
unchanged: it stays modal there, because that flow hands its plan back to
the register to write. The ribbon button is the one to use alongside Revit.

### Why this is more than Show() instead of ShowDialog()

A modeless window is in **no Revit API context**, which breaks three things
at once. All three are handled the way the main window already handles them:

- **Apply cannot write where it stands.** The plan goes out through an
  `ExternalEvent` and the window is refreshed when the write comes back.
- **Reading the model needs a context too.** The selection is read in
  Revit's `Idling` event, which is raised on Revit's own main thread inside
  one. Reading it from a window handler is what throws.
- **The window outlives the command.** `__persistentengine__ = True` in the
  button's script.py, and module-level references to the window, handler and
  event, or pyRevit collects them and every handler in the window is dead -
  which looks exactly like a broken tool.
- The Idling handler is handed back when the window closes. One left
  subscribed is one Revit calls into a dead engine.

### Bench

- New rule **`revision_modeless`**, 11 breakages, covering all of the above
  plus the pure logic: which row a selection jumps to (the first selected
  cloud's revision the list holds, and *nothing* when the list is already
  there), clouds to revision keys (each once, in order, non-clouds skipped),
  and that reading the selection never throws - it runs on every Idling
  tick, so one throw there is a dialog in your face every second.
- It caught a real bug before delivery: `revision_keys_of` returned the
  element id as an **int** while `Entry.key` is **text**, so every jump
  would have matched nothing and the list would have sat still.
- `revision_button` now also requires `__persistentengine__`.
- `revision_series` and `revision_button` were updated to describe the
  modeless Apply rather than the old modal loop.
- 253 breakages, 49 rules, all firing.

## 1.37.0

### Fixed: the tool would not load at all on Revit 2021

- **The crash.** `ps_revisions` imported `RevisionNumberingSequence` in a
  grouped `from Autodesk.Revit.DB import (...)`. That class arrived in
  **Revit 2022**. A grouped import is all or nothing, so on 2021 the whole
  import threw *"Cannot import name RevisionNumberingSequence"* - and
  because `script.py` loads `ps_window`, which loads `ps_regview`, which
  loads `ps_revisions`, the entire tool died at load. No window, no export,
  nothing.
- **The fix.** The name is now asked for on its own, inside try/except,
  with `RevisionNumberingSequence = None` as the fallback. `SpecTypeId`
  (Revit 2021) is guarded the same way. The tool loads, and only the one
  feature that needs the newer API steps aside.
- **What 2021 now does.** The Revision Manager opens and says, in its
  status line, that numbering sequences arrived in Revit 2022. The
  **Numbering** column is empty and cannot be set - a Numbering change is
  refused with that reason rather than failing silently.

### Still not there on Revit 2021

Not a regression - these all need a newer Revit, and all of them already
step aside quietly:

- **Built-in PDF export** needs Revit 2022 (`PDFExportOptions`). The run
  log says "this Revit has no built-in PDF exporter". DWG, NWC and IFC are
  unaffected.
- **Document Register revision cells** fall back to the sequence number:
  `GetRevisionNumberOnSheet` is Revit 2022 too.
- **Dark/light following Revit's canvas** needs Revit 2024
  (`UIThemeManager`), so the theme starts on the saved one.
- **The right-click menu entry** needs Revit 2025, as before.

The tool is built and tested for **Revit 2024-2027**. 2021 now loads and
runs, but it is not a version these features are written for.

### Bench

- New rule **`api_version_imports`**. It carries a table of Revit API names
  and the release that introduced each one, and fails when one newer than
  Revit 2021 is imported where a missing name would take the module down:
  - in a grouped or unguarded module-level import - the 2021 crash itself;
  - guarded, but with no fallback assigned in the `except`, which only
    moves the crash to the first read of the name.
  It also checks the behaviour the fallback buys: a Numbering change is
  refused, naming Revit 2022, before the write touches the model.
  No run of the bench could have caught this on its own - the stub
  namespace answers to every name, so it is the shape of the import that
  has to be checked.
- `_module_names` now knows that a guarded import defines a name, so
  `module_calls` does not report one as missing.
- 4 new breakages, all caught (242 in all, 48 rules).

## 1.36.0

### Revision Manager: columns fit their text

- **Every column sizes itself** to its heading and its widest value, so
  nothing is clipped and no column is wider than it needs to be. Sequence,
  Numbering, Date, Issued, Issued to, Issued by, Show, Used on sheets and
  any column you add all fit themselves.
- **Two stay as they were.**
  - **Description** still takes whatever width is left, rather than growing
    to its longest line and pushing everything else off screen.
  - **Sheet series** keeps a set width, because its chips wrap to the
    column. A column that fits itself to its content gives them no edge to
    wrap at, so they would run off in one long line instead. Drag its edge
    to change how many chips fit on a line.
- **Floor and ceiling.** A fitted column never gets so narrow that its
  search box and list button stop being usable, and never wider than 300px,
  so one long description cannot push the rest out of sight.
- **Fit columns** (left panel, beside Reset columns) re-fits every column.
  Use it after dragging a column's edge, or after typing something longer
  than the column was built for.

### Bench

- `revision_series` now also checks:
  - every column but Description and Sheet series fits its text, and those
    two do not, for the reasons above;
  - added columns fit too;
  - the floor and ceiling exist;
  - Fit columns is wired and leaves Sheet series alone.
- 7 new breakages, all caught (238 in all, 47 rules).

## 1.35.0

### Revision Manager: the Change column is gone

- The first column, **Change**, has been removed. Staged changes still show
  the same way they did: a changed cell goes green and bold, and a row
  staged to go is red and struck through.
- What that column said - New, Edited, Delete, **Merge into 3** - is now the
  **Sequence** cell's tooltip, so a merge still says where it is going.
- 2 new breakages, both caught (231 in all, 47 rules).

## 1.34.0

### Revision Manager: every Sheet series showing

- **Expanded by default.** Every Sheet series cell now opens expanded,
  showing all the sheet series the revision appears on. Before, it showed
  the first series and "+2".
- **Chips wrap.** The coloured chips wrap to the column's width rather than
  stacking one per line, so rows stay as short as they can. Widen the column
  to fit more on each line.
- **Collapse series / Expand series** (left panel, beside Clear filters)
  folds or unfolds every row at once. The choice is remembered (setting
  `rev_series_open`). Clicking a single cell still folds or unfolds just
  that row.

### Bench

- `revision_series` now also checks:
  - cells are open by default;
  - the chips wrap;
  - the toggle reaches every row and is remembered.
- 5 new breakages, all caught (229 in all, 47 rules).

## 1.33.0

### Revision Manager: a value list on every column

- **Where.** Each heading has a small **▾** button beside its search box.
  It opens a list of every value in that column, Excel style:
  - a search box;
  - **All** / **None** for whatever the search leaves listed;
  - **Tick selected** / **Untick selected**;
  - a tick per value, then **OK** or **Cancel**.
- **Selecting several.** **Ctrl + click** and **Shift + click** select
  several values. Ticking one of the selected values ticks (or unticks) all
  of them, and so does **Space**.
- **What is listed.** The list shows what the searches and the *other*
  columns' lists leave, as Excel does. A column's own list never hides
  values from itself, so you can always tick them back on. Empty cells
  appear as "(Blanks)", last.
- **Sheet series.** Each series is listed on its own, as its coloured chip.
  A revision on BW and EC shows when either one is ticked.
- **When it is on.** A filtered column's button turns orange and shows how
  many values are ticked. Ticking everything turns the filter off.
- **Clear filters.** The old **Clear searches** button is now **Clear
  filters**. It empties every search box and resets every list.
- Value lists stay on when you add or edit a column of your own. The footer
  count ("12 revisions, 4 showing") includes them.

### Revision Manager settings: type into the Parameter box

- The separate **Search** column is gone. Type straight into the
  **Parameter** box: the list under it narrows to the parameter names that
  contain what you type ("rev note" finds *Revision Notes*).
- To pick a parameter, click it, or use **Down** then **Enter** (or just
  Enter when only one name matches). The caret beside the box shows the
  whole list.
- While what you have typed matches no parameter, the Status says so in
  orange.
- `ps_ui.SearchPicker` is a reusable type-to-search box for any long list.

### Bench

- New rule `revision_filters`. It checks:
  - the Staging filter logic (multi-value series, blanks, Excel's
    "other columns only" rule, searches and lists together);
  - Extended selection, tick-all-selected and Space;
  - Clear filters;
  - the Ctrl+Up guard;
  - the picker's narrowing and exact-pick logic;
  - that the settings have no Search column.
- 15 new breakages, all caught (224 in all, 47 rules).

## 1.32.0

### Revision Manager columns

- **One Sheet series column.** 1.31.0 drew it twice. The duplicate is gone.
- **Used on sheets sits just left of Sheet series.** The count is bold:
  **red at 0** (the revision is on no sheet) and **blue otherwise**. It is
  still struck through on a row marked for delete.
- **Drag columns into any order.** Drag a header left or right. The order is
  remembered per user (setting `rev_column_order`), including your own added
  columns. Columns added later appear at the end. The green **+** column
  stays last.
- **Reset columns** (beside Clear search) puts the default order back.

### Revision Manager settings: keyword search for parameters

- Each mapping row has a **Search** box before **Parameter**. Type words from
  the parameter's name, e.g. "rev note" finds *Revision Notes*. Every word
  must appear somewhere in the name, in any case.
- The list narrows as you type and drops open to show the matches. An
  already mapped parameter stays shown even if it does not match, so it is
  never lost.

### Bench

- The `revision_series` rule now also checks:
  - one Sheet series column, with Used on sheets just left of it;
  - red/blue on the count;
  - draggable columns, with the order kept and reapplied;
  - the keyword rules;
  - the search box wired to the list.
- Six new breakages, all caught (209 in all).

## 1.31.0

### Revision Manager: Sheet series column

- **What it shows.** The sheet series of every sheet the revision is on,
  e.g. BW-BUILDERSWORK and EC-CONTAINMENT. Each series appears once, and the
  value comes from the series parameter set in Setup (BGL_Sheet Series on
  the house template).
- **Collapsed and expanded.** Collapsed, the cell shows the first series as
  a coloured chip plus "+2". **Click the cell** to list every series, one
  chip each. Click again to fold it.
- **Colours.** Each series has one colour across the whole project, from the
  register's group palette, so a series looks the same on every row and
  follows Dark/Light.
- **Search.** The box at the top of the column filters by series, e.g.
  "contain".

### Revision Manager settings

- **Where.** A **Settings** button at the top right of the manager (house
  order: settings, light/dark, version) opens Revision Manager settings,
  under a **Revision Manager** heading.
- **The mapping table.** Every column you have added, with its name, type,
  **Push to** (Nowhere / Sheets / Revision clouds), **Parameter** and a
  **Status** line. The status turns orange and says why when a mapping will
  not work:
  - not in the project;
  - not bound to that category;
  - a type parameter;
  - the wrong type of data.
- **Only parameters that will work are listed.** These are instance
  parameters bound to Sheets or Revision Clouds, whose data the column can
  be written as:
  - Text for text, date and choice columns;
  - Yes/No (or Text) for Yes/No columns;
  - Number, Integer or Text for Number columns.

  They are read from the project's parameter bindings, so a parameter shows
  up even before any cloud exists.
- **Open Project Parameters...** closes the manager and opens Revit's own
  Project Parameters. Any staged changes are applied on the way out if you
  say so. Add the instance parameter there, then reopen the manager and map
  it.
- **Refresh list** re-reads the parameters.
- **Tooltips.** The "i" badge, the Push to and Parameter headings and every
  mapping box carry a tooltip. It explains how mapping works, which
  categories to use (Sheets for a title block label or sheet list; Revision
  Clouds for a cloud tag), why only instance parameters are offered, and
  which data types fit.
- **Staged like everything else.** Mapping and rename changes are staged and
  written on Apply.

### Setup

- A **Revision Manager** section. It explains where the series and the
  mappings come from, and has one per-machine choice: **open the manager
  again after Apply** (its own ribbon button). The default is on.

### Fixed before it shipped

- From the register tab, a staged Apply and Open Project Parameters are
  queued as **one** job. The external event holds a single piece of work,
  and a second job would have replaced the write.

### Bench

46 rules (one new: `revision_series`) and 203 breakages (8 new).

## 1.30.0

### Revision Manager has its own ribbon button

A **Revision Manager** button sits on the Sheet Tools panel beside Pro Sheets
Exporter. It opens the manager directly, without opening Pro Sheets
Exporter first.

- **One copy of the code.** The button is a thin loader in
  `Revision Manager.pushbutton\`. It puts `Pro Sheets Exporter.pushbutton\`
  on the path and calls `ps_revwin.run_standalone`. There is one manager,
  one version number (`ps_version.py`) and one set of settings, theme
  included.
- **Apply writes straight into the model**, in one transaction, because the
  manager runs inside the button's own command. It then opens again, read
  afresh, with what was applied in its status line. Close or Cancel ends it.
  Anything Revit refused is listed first.
- **Placement and theme.** It is owned by Revit's main window, so it never
  slips behind Revit. It follows the Revit canvas theme (or the theme pinned
  in Pro Sheets Exporter), with its own Dark/Light chip.
- **Icon.** A sheet with an orange revision cloud and a blue revision-delta
  badge, in the Pro Sheets icon's style.
- **Still on the register tab.** The big button on the Document Register tab
  works as before.

### Bench

45 rules (one new: `revision_button`) and 195 breakages (5 new).
`revision_button` checks:

- the button's loader stays thin and IronPython-safe;
- it finds Pro Sheets Exporter;
- it opens the manager on its own;
- it is titled Revision Manager;
- its 96 and 32 px icons are present;
- standalone Apply writes, reopens and is owned by Revit.

The selftest now copies the button beside the tool, so its breakages are
proved too.

## 1.29.0

### Revision Manager: columns of your own

- **A green + adds a column.** It is the last column's heading, and there is
  also **Add column** in the side panel. You are asked for the **name** and
  the **type of data**: Text, Yes/No, Number, Date or a Choice list (with
  its choices, one per line). The type is fixed once the column exists.
- **Revision notes**, a Text column, is there by default.
- **The headings show which columns are yours.** They are green, with a
  pencil to rename, change the choices, map to a parameter, or remove. If a
  removed column has values, you are asked first.
- **Values are staged like everything else.** They go green until Apply and
  each column has its own search box.
- **Issued revisions take values in these columns too.** They are this
  tool's data, not Revit's, and notes are usually written after an issue.
- **Stored in the model.** Revit takes no parameters on revisions, so the
  columns and their values are kept in the model through Extensible Storage,
  on one DataStorage element. They are keyed by each revision's UniqueId, so
  they travel with the model through sync with central.

### Pushing into parameters

Each column can be mapped (pencil, then **Push into a parameter**) to:

- **Sheets.** Each sheet takes its **current revision's** value, which is
  what a title block label can show. A sheet with no current revision, or
  whose revision has no value, is cleared, so it never shows a note from a
  superseded revision.
- **Revision clouds.** Each cloud takes its own revision's value, which is
  what a cloud tag can show.

How the push works:

- **Which parameter.** It must be a project or shared parameter you have
  already added to that category. The dialog lists the writable ones it
  finds, and refuses one of the wrong kind:
  - Text for text, date and choice columns;
  - Yes/No (or Text) for Yes/No columns;
  - Number, Integer or Text for Number columns.
- **Built-in parameters are never offered.**
- **When it runs.** Mapped columns are pushed on every Apply, last of all,
  after the revisions have their final order. A sheet whose current revision
  changes picks up the new value. **Push to parameters** stages a push with
  nothing else changed.
- **Reporting.** Sheets or clouds without the parameter, or owned by
  someone else, are listed after Apply.

### Bench

44 rules (one new: `revision_columns`) and 190 breakages (10 new). The new
rule covers:

- stored text that survives tabs, newlines and backslashes;
- values each type refuses;
- parameter kinds refused;
- sheets cleared rather than left stale;
- columns stored and pushed last, with a new revision's values under the id
  Revit gave it.

## 1.28.1

- **Revision Manager button.** The icon is a plain blue triangle, with no
  "1" in it.
- **Export to Excel** (and the manager's Apply, which shares its style) sits
  on a soft drop shadow that tightens when pressed.
- **Revision Manager side panel.**
  - Icons on Add (green plus), Delete (red bin), Move Up and Move Down (blue
    arrows).
  - The arc length box is taller (34 px, 13 pt), so its number is no longer
    clipped.
- **Bench.** 43 rules and 180 breakages (3 new).

## 1.28.0

### Revision Manager

A big **Revision Manager** button sits on the right of the Document Register
tab, beside both toolbar rows. It is raised on a drop shadow and sinks into
it when pressed. It opens a manager for every revision in the project.

**Everything Revit's Sheet Issues/Revisions dialog does:**

- Sequence, Numbering, Date, Description, Issued, Issued to, Issued by and
  Show, edited in the grid. A single click edits, as in Revit.
- Add and Delete.
- Move Up / Move Down, and Merge Up / Merge Down.
- Numbering Per Project / Per Sheet.
- Arc length, in mm.
- Issued revisions are locked as Revit locks them: untick Issued to edit
  one.

**Plus:**

- **Used on sheets.** A column showing how many sheets carry each revision.
  Hover over it for the sheet numbers and the number of clouds.
- **A search box on every column** (contains, any case, all columns at
  once), and **Clear searches**.
- **Batch moves.** Ctrl or Shift click to select several, then Move Up /
  Move Down (or Ctrl+Up / Ctrl+Down). A selected block moves as a block.
- **Delete asks first when a revision is in use.** The question lists each
  one with its sheet and cloud counts. Pressing Delete again on a row staged
  to go restores it.
- **Change column.** It says what will happen to each row: New, Edited,
  Moved, Delete, Merge into n.

**Nothing is written until Apply.**

- **Every change shows green** until then. Rows staged to be deleted or
  merged are red and struck through.
- **Apply** shows how many changes are staged. It writes them all in one
  transaction (one Undo in Revit), then closes and lands back on the
  Document Register, read again.
- **Cancel** with changes staged asks before discarding them.
- **Order of writing.** Un-issues go first and issues last, so edits to them
  go through. A merge moves the revision next to the one it merges into
  before combining, because Revit only merges neighbours.
- **Refusals.** Anything Revit still refuses is listed afterwards, and the
  rest goes in.

The manager follows the tool's theme, with its own Dark/Light chip top
right.

### Bench

43 rules (one new) and 177 breakages (11 new). The new `revision_manager`
rule drives the staging the way the window does, and writes plans through a
fake Revit that refuses what Revit refuses:

- edits to issued revisions;
- merges with anything but the one before;
- a reorder that leaves a revision out.

## 1.27.0

### Document Register

- **All sheets / Included only.** The chosen one is now **solid orange**, so
  which view you are on reads at a glance. The other stays a plain chip.
- **Export to Excel** is a **green, bold** button with a green spreadsheet
  icon.
- **With an Export run, the register goes into the issue folder**: the
  folder after the date, before the sheet series, e.g.
  `Wrexham AFC Kop Stand\2026-10-06_14_32\`. It covers every series in the
  issue. With one series ticked, 1.26.0 put it in that series' own folder
  (`...\BLANK PLANS\`). Without a series level in the subfolder tokens, it
  still goes in the folder above PDF/DWG.
- **The file name carries the date**:
  `Wrexham AFC Kop Stand - Document Register - 2026-10-06.xlsx`. Each
  issue's register is kept rather than overwritten by the next. This
  applies to Export to Excel, the Create tab and the register on its own.

### Bench

42 rules and 166 breakages (4 new).

## 1.26.0

### Fixed: the Document Register would not write in Revit

Every register export failed with *"Precision not allowed in integer format
specifier"*, both from Export to Excel and alongside a run.

- **Cause.** The Excel writer formatted row heights and column widths with
  two decimal places. IronPython, the engine pyRevit runs, refuses that on a
  whole number such as a row height of 15, where CPython (the bench) quietly
  converts it.
- **Fix.** Widths and heights are now stored as decimals. Every
  precision-formatted number in the tool is also put through `float()`: the
  print wait times, paper sizes in mm, the run time and saved column widths
  had the same exposure.
- **New bench rule `int_precision`.** It reads every `.format` and `%` call
  in the source and fails on any precision field whose value is not wrapped
  in `float()`. No CPython run can see this class of error, so it is checked
  in the source.

### The Document Register on its own

With **Add to export?** ticked and no sheets ticked:

- **The Create tab** lists the Document Register by itself.
- **Export is live** and writes just the register, through the same run,
  report and Open folder as any export.
- **The register goes into the folder the subfolder tokens name without a
  sheet.** Levels are taken from the top until the sheet series level, or
  the first token only a sheet can fill. On the default tokens that is
  `Root\Project Name\date_time`, the same issue folder a run with drawings
  uses.

### Document Register tab

- **Reset filters** button (funnel icon) clears every column filter at once.
  It is greyed until a column is filtered, then says how many, e.g. "Reset
  filters (2)". The search box and Included only are left alone.
- The **Rev** column is **bold and blue**. It still fades with the row when
  the drawing is out of the register.
- The sequence column is now **Seq No**, and narrower.

### Bench

42 rules (one new) and 162 breakages (9 new).

## 1.25.0

### Document Register: sequence numbers on screen

- **Each revision column's header shows the sequence number above the
  date**, small and muted, as Revit's Sheet Issues/Revisions dialog numbers
  it. Two issues on the same day can now be told apart at a glance.
- **A Sequence Number column next to Rev** shows the sequence number of each
  drawing's current revision. It filters like every other column.
- **Neither reaches the Excel export.** The RD9 sheet has no row or column
  for them, so the file is unchanged.

### Bench

41 rules and 153 breakages (6 new):

- the column is filled from the current revision's sequence, not its
  element id;
- it sits next to Rev;
- the header carries the number above the date;
- a revision with no sequence shows blank, not 0;
- the number never reaches the Excel file.

## 1.24.0

### Document Register Excel: the RD9 issue sheet, cell for cell

The export is laid out like the project's own **RD9 Drawing Register Issue
Sheet**, so it can go out in place of the hand-kept one:

- **Title band.** "RD9 - Document Register & Issue Sheet" in Gadugi 18 bold
  blue, then the **client logo**, then the **company logo**. Both logos are
  scaled to the same box, centred top to bottom, and shrunk together if the
  form is too narrow to hold them.
- **Project No: / Project Title:** on a light blue band, with **Day / Month /
  Year** beside them and each issue's date as three numbers down its column.
- **Issue Status:** with the letter over each column, and the status legend
  right-aligned under it.
- **Issued to:** runs up the side, with a recipient on each row and an **x**
  under each issue that went to them. One spare row is left at the bottom.
- **Document No / Document Title / Size / Scale / Document Issued** in the
  form's sizes. Size and Scale run up the page.
- A spacer row comes first, then the drawings. Each **sheet series is
  separated by a blank row** rather than a heading band.
- **Shading by status.** Drafts (D) are blue and every other issue is green,
  on the issue columns and on each revision code. Blank columns are left
  unshaded.
- **Snapshot column.** The last column is called **Asite Snapshot** (amber).
  It carries every drawing's current revision. The heading is set in Setup,
  and leaving it blank removes the column.
- At least **24 issue columns**, with blank ones for the issues to come, so
  the form keeps its shape.
- **Footer.** It is boxed across the foot of the form.
- **Page setup.** A4 portrait, fitted to the width, with the form's margins.
  Rows 1 to the headings repeat on every page. The print area is the form
  and nothing else.
- **Lines.** Black throughout: thin inside a medium frame, and medium either
  side of the headings and down the right of the titles.

The Issued By row and the Discipline line from 1.23.0 are gone, because the
RD9 sheet has neither. The worksheet name still says which discipline it is.

### Client logo

**Setup → Document Register** has a **Client logo** field under the company
logo. It has its own preview and its own Browse and Clear buttons. Like the
company logo, it is copied into `%APPDATA%\RevoBIM` (as
`register_client_logo.png/.jpg`) when chosen. A PNG and a JPEG can sit side
by side.

### Paper

The Paper choice is now **A4 portrait / A3 portrait / A4 landscape / A3
landscape**. The default is A4 portrait, matching the RD9 sheet.

### Register tab: tick boxes only where they mean something

- **Heading rows** (discipline and series) show a tick box **only under All
  sheets**. Under Included only, every drawing on screen is already in, so a
  heading tick could only take a whole series out at once.
- **With everything collapsed**, the heading ticks and the tick in the column
  heading are hidden. A column of ticks with no drawings under them reads as
  a list to tick.
- A drawing's own tick is never hidden. The boxes are hidden, not removed,
  so the column keeps its width.

### PDFs: Revit's own exporter is the default again

Setup saved the chosen print driver as this machine's default whenever a
driver option was picked, and from then on every run used it. Testing PDF24
once was enough to trigger this. A one-off settings update (version 4) puts
every machine back on **Revit's built-in PDF exporter**. A driver can still
be chosen in Setup afterwards and is then kept. A template that names a
driver still does not override the machine.

The same update moves the register's **untouched** defaults onto the RD9
sheet's: the title, the legend (Pro, D, P, PL, T, CN, C, AB, SK) and the
recipients (Client, Architect, Principal Designer, Project Manager,
Structural Engineer, Fire Engineer, Main Contractor). Anything you had typed
in those boxes is kept.

### Open folder goes to the issue, not one series

After a run, **Open folder** (both the button and the offer) opens the folder
**before the sheet series level** of the folder tokens. On the house template
that is the dated folder. Before, it opened the deepest folder written, which
was one series' PDF folder.

- The folder is worked out from the plan when the run starts, so a time
  token cannot drift by a minute before the report appears.
- Without a series level in the tokens, it opens the folder above the
  PDF/DWG folders.
- If that folder is not on disk, it falls back to where the files went.

### Bench

41 rules (two new) and 147 breakages (25 new):

- `register_ticks`: heading and header ticks hide and come back.
- `register_xlsx`: checks the RD9 layout cell by cell, the shading, both
  logos and their anchors, the print area, and that the defined names are in
  order.
- `pdf_default` (new): the v4 migration.
- `issue_folder` (new): the cut above the series, including a UNC root and a
  root in a different case, and the fallback.

## 1.23.0

### Document Register: Excel's column filters

The box under each heading is now a **filter button**. It opens a list of
every value in that column with a tick beside each, **(Blanks)** at the end
for empty cells, **All** and **None**, a search box to find a value in a long
list, and **OK** / **Cancel** - Excel's own filter, revision columns included.
Nothing changes until OK, so the grid does not reshape under the list while
you are ticking. A filtered column's button turns orange and says how many
values it lets through.

The list offers what the *other* filters leave, as Excel does, but never
narrows a column by its own filter - otherwise the values it is hiding would
not be there to tick back on.

### Hide unused revisions

A **Hide unused revisions** tick box. On (the default), the revision columns
are the ones the drawings on screen actually carry - after the filters and
Included only - so narrowing the list narrows the columns with it. Off, every
revision in the project is shown. A column you have filtered always stays,
or a filter could hide the very column it has to be cleared from.

The Excel export follows it: on, each worksheet carries only the revisions its
own drawings carry; off, every revision.

### Headings coloured like the Selection tab's groups

Each heading has a band of its own colour and its drawings a wash of it, from
the same palette and the same helper as the Selection tab's groups, so the two
tabs look like one tool.

The **All** tab is now grouped by **discipline, then by series** inside each.
Folding a discipline folds its series with it; ticking a discipline's heading
includes every drawing under all its series.

### The tabs along the bottom

Each discipline's tab wears **its colour** - the same as its heading on the
All tab - with a small swatch beside the name. Each has a **tick box: include
this discipline as a worksheet in the Excel export**. Ticked by default, kept
for the project, and greyed while the discipline has nothing in the register,
because an empty worksheet is never written. Untick every discipline that has
drawings and the export says so rather than writing an empty file.

### Toolbar

- **All sheets / Included only** sit together in a bordered box, with an icon
  each, so they read as one switch.
- **Collapse all / Expand all** has an icon that turns with it.
- **Include all on this tab** and **Include none on this tab** are gone. The
  tick box in the tick column's heading still includes or leaves out
  everything showing.

### Bench

`register_logic`: Excel filter sets including blanks and a filter allowing
nothing, the filter list's order, the All tab's discipline-then-series tree,
Hide unused on and off. `register_view`: the filter is a button, applies only
on OK, offers (Blanks), lives in the heading's panel for its colours, and its
clicks stop at its border rather than bubbling to the heading; a column's list
is not narrowed by its own filter; rows painted with the Selection tab's
colours and repainted on a palette swap. `register_ticks`: filters narrowing
other lists, (Blanks), a filtered column kept on screen, Hide unused following
what is showing, the All tab's headings, folding a discipline, a discipline
heading ticking all its series, heading colours matching tabs, and an unticked
discipline left out of the workbook. `register_xlsx`: unticked and empty
disciplines get no worksheet. Twelve new breakages, two retired with the
code they broke, 122 in all.

## 1.22.0

### Add to export: on the Create list, and above the PDF and DWG folders

Ticking **Add to export?** on the Document Register now puts a **Document
Register** row on the Create tab's list - XLSX, its file name and the folder
it will go to - and the summary says "plus the Document Register". During the
run it turns green or red like every other file.

It goes in the folder **above the PDF and DWG folders**: with the house
subfolder tokens and one series, that is the series folder holding PDF and
DWG; with several series, the dated issue folder holding them all. 1.21.0 used
the deepest folder the run's files had in common, which on a one-series,
one-format run was the PDF folder itself - so the register landed among the
drawings, where nobody looks for one. That may well be why it seemed not to be
there. The folder is now worked out from the run's plan, so the Create list
can show it before anything is written.

Every step of writing it goes in the debug log - the folder, then written or
FAILED and why - so "it was not there" can be told apart from "it went
somewhere else". And if .NET's zip writer refuses on a machine, the register
is written with Python's instead of being lost; where both refuse, both
reasons are reported.

### Included only hides the empty disciplines

Under **Included only**, a discipline with nothing in the register has its
tab taken off the strip. **All** always stays. The tab you are on stays until
you leave it, even if you untick its last drawing, rather than vanishing under
the cursor; switching to Included only while on an empty discipline moves you
to All. Ctrl+PageUp / Ctrl+PageDown step over the hidden tabs.

### Export to Excel asks to open the folder

After **Export to Excel** on the register tab: "Document Register exported.
Open the folder?" - **Open folder** opens Explorer with the file picked out.
If it was not written, it says why instead.

### Bench

`register_logic` gains the folder (one series, one or two formats, several
series, no format folders) and which tabs show. `register_ticks` checks
Included only moving off an empty discipline. `register_view` checks the
Create list row, its key, the refresh when the box is ticked and the run's
folder. `register_xlsx` makes .NET's writer refuse and checks the register is
still written. Seven new breakages, 112 in all.

## 1.21.0

### The register's ticks now mean "in the register", not "print"

1.20.0 shared one list of ticks between the Document Register and the
Selection tab. That was the wrong model - the drawings that belong on a
register are not the ones being printed today - so the register keeps its own
list now and never touches the print ticks. **A tick on the Document Register
puts that drawing in the register's Excel export.** Drawings left out are drawn
in the muted colour, so in and out read at a glance down a long list.

**All sheets / Included only** switch between every drawing and just the ones
in the register. Unticking a drawing while "Included only" is showing turns it
pale rather than whisking it away under the cursor; the view catches up on the
next filter, toggle or F5 - the same rule every RevoBIM table follows.

### Driven by a Revit View/Sheet Set

A **View/Sheet Set** drop-down at the top lists Revit's own sets. Choosing one
ticks exactly the sheets in it. Change the ticks and **Apply** lights up;
pressing it writes the ticks back into that set, through Revit's event like
every other write. Views already in the set are kept - the register only
manages the sheets.

**+** starts a new set: name it, tick its drawings, press **Save new set**.
Nothing is written until then, because Revit cannot hold an empty set.

With no set chosen the ticks are kept for the project as you make them - as the
drawings left *out*, so a sheet added to the model later starts in the register
rather than silently missing from it. Switching away from a set with changes
that were not applied asks first.

### Export to Excel, and Add to export?

**Export to Excel** writes the register now. **Add to export?** makes every
Export run write it too, into the deepest folder the run's drawings share -
with the house subfolder tokens, that is the dated issue folder, so the
register travels with the issue it describes. It is listed in the run's report
like any other file.

The workbook is the Drawing Register's **RD9 Document Register & Issue Sheet**:
the logo in the title band, Project No / Project Title / Discipline, the
**Day / Month / Year** of each issue as three rows of numbers, the issue status
letters in blue with the legend beside them, Issued By, the **Issued to** block
with an X wherever an issue went, then the drawings under their series, the
current revision in bold. One worksheet per discipline, each carrying only the
revision columns its own drawings use. The form down to the column headings
repeats on every printed page; landscape, fitted to the width, A3 by default.

Revision dates are whatever the office typed into Revit, so 01/02/26,
1.2.2026, 2026-02-01 and 1 Feb 2026 are all read, day first. Anything else is
shown as typed, up its column, rather than guessed at.

Written as Office Open XML straight into a zip - no Excel, no interop, no
package to install.

### Settings: a Document Register section

In **Set up** (the register tab's **Settings** button opens it at this
section): the title, the **company logo** (PNG or JPG, with a preview, copied
into the RevoBIM settings folder so the form keeps it if the original moves),
the status legend and the Issued to list one per line, the footer, and the
paper size. The discipline and series parameters stay where they were, just
above it.

### Formatting

- **Columns fit their text.** Every column is measured once per tab and set to
  its widest entry, between a floor that keeps the filter box usable and a
  ceiling. Never left on Auto, which re-measures as rows are realised and
  shifts the columns halfway down the list.
- **Revision columns are wider** - at least 48px, measured in bold because the
  current revision is drawn bold. 34px clipped the codes.
- **Series headings are readable.** The Drawing No column is fitted to the
  headings as well as the numbers, at their own 14pt bold, which is what was
  cutting them off.
- **A filter at the top of every column**, revision columns included. Filters
  narrow, Excel style; a filter on a revision column one discipline does not
  have is ignored on that tab rather than emptying it.
- **Series fold away.** Click a series heading to collapse it, again to expand;
  **Collapse all** does the tab. The heading's own tick box still includes the
  series rather than folding it.

### Fixed: Save V/S Set on the Selection tab

Found while writing Apply, and it predates it. `ViewSheetSetting` is only
usable with Revit's print range on *Select*, which nothing set - so on a model
left on Revit's default the save threw and reported "could not be saved" with
no reason. And saving under a name that already existed fell back to saving
whichever set happened to be current, under its own name. Both tabs now go
through one writer that sets the print range, makes an existing set current
before saving it, and uses Save As only for a new one.

### Bench, thirty nine rules

| Rule | Holds |
| --- | --- |
| `register_view` | rewritten for 1.21.0: the register never reaches the print ticks; a set is written only through the external event, keeping its views; a tick does not re-filter under the cursor; filter boxes do not click their heading; columns fitted in pixels, never Auto; revision columns at least 44px; Drawing No fitted to the 14pt headings; left-out drawings muted on the cell |
| `register_ticks` | rewritten, behavioural: by-hand ticks kept as the ones left out; Included only, and nothing vanishing mid-tick; heading includes its series; date click out and back; fold and unfold; a column filter; choose a set, change it, Apply through the event; + names an empty set and writes nothing until Save; then the Excel file is written |
| `register_xlsx` | new: dates as typed, the Issued to block, worksheet names Excel accepts and that stay unique after the 31-character cut, the run folder, and a whole register written and taken apart - schema element order, no single-cell merges, a height-only row kept, the logo's type declared, print titles, rotation used, and opened with openpyxl |
| `sheet_sets` | new, behavioural: print range set before the setting is touched, an existing set made current and saved with Save, a new one with Save As, the set's own views kept, an empty set never sent to Revit |

105 breakages, every one caught. Two of the new rules first passed their
own breakages for the wrong reason - a new set "sent early" only queued the
job, and the title band's lower row always carries styled cells so it could
never be height-only. Both now look where the fault would actually show.

## 1.20.0

### New tab: Document Register

Second tab, between Selection and Format. Every sheet in the project down
the page and every revision across it, in the Drawing Register's layout:

| | |
| --- | --- |
| Frozen on the left | tick, Drawing No, Drawing Title, Size, Scale, Rev, Rev Date |
| Across | one narrow column per revision, its date rotated up the header and the issue status letter under it in blue |
| In each cell | the revision number **that sheet prints** for that revision |
| Picked out | the sheet's current revision, in orange and bold |
| Down the page | drawings in natural number order, under series headings |
| Along the bottom | **one tab per discipline**, like a workbook's sheet tabs, with **All** first |

The discipline and series parameters are the ones from **Set up** (BGL_Sheet
Discipline and BGL_Sheet Series by default). The tab says which it is using,
and **Change** opens Set up. If either parameter holds nothing on any sheet the
tab says so in orange, rather than showing one tab or one heading over
everything with no explanation.

Each discipline tab carries only the revision columns its own drawings use, as
the paper register does - a Mechanical tab does not have forty empty
Electrical columns across it. The All tab is headed by discipline; a
discipline's own tab is headed by series.

### Ticking to print

**The ticks are the Selection tab's ticks.** There is one list of what gets
printed, seen from two tabs: tick a drawing on the register and it is ticked on
Selection, and the other way round. Nothing to copy across, and nothing that
can drift.

- Tick a drawing, a series heading (ticks the series) or the header box
  (ticks everything showing on the tab).
- Highlight several rows and tick one: they all tick, as on Selection.
- **Click a revision's date** to tick every drawing on the tab that carries
  that revision - "print everything that went out at P03" is one click. Click
  it again to untick them.
- The tabs along the bottom show how many drawings each holds and how many are
  ticked; the summary bottom right counts across the whole project.

If the Selection tab is listing views, ticking a drawing on the register
switches it back to sheets, and says so.

Search narrows by number and title. **F5** re-reads the model,
**Ctrl+PageUp / Ctrl+PageDown** move between disciplines. The register is read
the first time the tab is opened, not when the tool starts, so anybody who
never uses it pays nothing for it.

### Fixed: ticked sheets that were not on screen were not exported

Found while wiring the register in, and it predates it. The export walked the
Selection table's *visible* rows. A sheet ticked inside a collapsed group, or
ticked and then hidden by a search, was counted as ticked on the status line
and then silently left out of the run - the heading tick on a collapsed group
was the easy way to hit it.

Ticked now means exported, whatever is on screen, in the Selection tab's
order. The status line says when some of what is ticked is out of sight: *"40
of 212 sheets showing, 52 ticked. 12 of them are out of sight and will still
be exported."* The Create tab lists every one before anything is written.

### Under the hood

The tabs are named constants now. Every place the window had a bare `2`
meaning "the Create tab" would have quietly started meaning Format the moment
the register went in second - the Export button on the wrong page, a run
opening the wrong tab.

The register lifts the Drawing Register's decisions rather than its code:
`GetRevisionNumberOnSheet` for the cell (never the project-wide
`Revision.RevisionNumber`, deprecated since 2022 and gone in later releases),
one pass for revisions and one collector for scales, groups and tabs where
their first drawing is rather than alphabetical, blanks last. One deliberate
difference: the status letter is derived across the whole project rather than
per tab, so a column reads the same letter whichever discipline you are on.

### Bench, thirty seven rules

| Rule | Holds |
| --- | --- |
| `register_logic` | status letters by majority, groups and tabs in order of first appearance with blanks last, only used revisions per tab, scales, column keys that cannot collide with Rev and Rev Date - and the read itself, run against a fake model whose `RevisionNumber` throws if anything touches it |
| `register_view` | the register reads and writes the Selection tab's ticks rather than keeping its own; a header click is cancelled as a sort before anything else; dates rotate with `LayoutTransform`; the drawing columns are frozen; the current revision's orange is a `DynamicResource` |
| `tab_indices` | the tab constants match the layout's tabs by title, and nothing compares a tab index with a bare number |
| `export_ticked` | the export does not walk the filtered view, keeps the Selection tab's order, and steps over headings |
| `register_ticks` | behavioural: the real register driven against a stand-in table and window. Ticks a series heading, clicks a revision date twice, ticks a highlighted block, searches and ticks what is left, and checks the Selection tab's list after every step |

Nineteen new breakages, including the 1.19.2 export and the 1.19.2 tab
numbers. 37 rules, 89 breakages.

One existing rule had to be corrected on the way. `group_colours` checked
that Theme.xaml had a heading trigger *somewhere*; the register's new row
style has one too, so with the cell's own trigger deliberately broken the
rule still passed. The selftest caught it. It now reads inside the
`GridCell` style itself.

## 1.19.2

### The startup block resolves its own path the way the rest of the
### extension does

Drew sent over the real `startup.py`. It already carries the Family Viewer
dockable pane registration, and it resolves its folder with
`os.path.dirname(os.path.abspath(__file__))`. The ProSheets block was using
`dirname(__file__)` without the `abspath`, which gives an empty string if
`__file__` ever arrives relative — and an empty string is the one input the
walk-up cannot recover from. Now matched to the existing block.

Checked against a copy of the real layout: correct placement registers,
a `startup.py` one folder off is still found by the walk-up, and one
outside the extension writes the message naming where it looked.

## 1.19.1

### The startup block now says when it could not run

Drew right clicked on Revit 2026 and the entry was not there. 2026 is one
of the versions the 1.19.0 fix was *not* about — it had the method all
along — so the cause was the other one: the block has never been pasted
into the extension's `startup.py`.

What made that slow to establish is that the block had no way to report
anything. Its log is written by `ps_context`, and every failure that stops
`import ps_context` from succeeding therefore left no log at all — which
looks exactly like a block that was never pasted. Three quite different
situations produced one identical symptom.

The block now carries its own small logger and writes to the same file
before it needs the tool for anything:

- pasted into a `startup.py` that is not in the extension root, so the
  tool folder cannot be found — says so, and names the folder it looked
  from
- pyRevit handed it neither `__revit__` nor `__uicontrolledapplication__`
  — says so
- anything else threw and was swallowed — says so

So `%APPDATA%\RevoBIM\logs\pro_sheets_exporter_context_menu.txt` now
answers the question directly. **No file at all means the block never ran**
— it is not in the `startup.py` Revit actually loaded.

### And it looks a bit harder for itself

Rather than assuming `startup.py` sits exactly at the extension root, the
block now walks up to four levels looking for the tool folder. A
`startup.py` one folder off used to fail in complete silence.

### Bench

`context_menu_host` gains the fragment's own diagnostics: it must carry a
fallback logger, write to `APPDATA`, wrap its own logging, and walk up
rather than assume one location. Two more breakages.

Both new checks initially passed against a deliberately broken fragment —
the candidate names survive in the fragment's log messages, so "is the name
mentioned" was true even with the name dropped from the list. The check now
reads the list the fragment actually iterates. A rule that passes for the
wrong reason is worse than no rule, which is what the selftest is for.

32 rules, 70 breakages, every one fired when broken.

## 1.19.0

### "Print in ProSheets" on the Project Browser right click — and the
### reason you never saw it

Yes, it is possible on Revit 2025 and up, and it has been in every zip
since 1.9.0. It has also never worked on Revit 2025, which is the
version you asked for, and that is my fault.

`RegisterContextMenu` is the call that puts an entry on Revit's right
click menu. It lives on two different objects, and they did not get it
at the same time: `UIApplication` has had it since Revit **2025**,
`UIControlledApplication` only since Revit **2026**. The startup block
handed over a `UIControlledApplication` and the version gate asked that
object whether it had the method. On 2026 and 2027 it does, so the entry
appeared. On 2025 it does not, so the gate concluded the API was missing
and shut the feature down — on the one release it was built for. Nothing
threw, nothing showed on screen, and the only trace was a line in a log
file nobody had a reason to open.

So the host is no longer assumed. `register()` now takes any number of
candidates, asks each one whether it can actually register, and uses the
first that can. The startup block passes both `__revit__` and
`__uicontrolledapplication__`, because which of the two carries the
method depends on the pyRevit build as well as the Revit release.

There is also a last-resort route: where Revit has the context menu
types but no candidate carries the method, the registration waits for
`ApplicationInitialized` and builds a `UIApplication` itself, which does
have it on 2025.

### The entry is now called what you asked for

`Print in ProSheets`, where it used to say `Print Selected`. It sits at
the bottom of the right click menu in the Project Browser and in the
canvas — the API appends, so no add-in can put itself above Revit's own
entries.

Selecting sheets and right clicking opens the tool with exactly those
sheets listed and ticked. That half already worked: a Project Browser
selection behaves like any element selection, so the tool's existing
pre-selection handling picks it up with nothing new needed.

### One manual step, and it is the whole feature

The entry can only be added while Revit is still building its UI, and
the only place a pyRevit extension gets to run code then is the
extension's shared `startup.py`. That file is shared and singular, so
this delivery does not ship it — overwriting it would take out whatever
else lives in it. The block to paste is in `startup_fragment.py`, in the
pushbutton folder, with instructions at the top.

Paste it, then **restart Revit** — a pyRevit reload will not do it,
because by then Revit has finished starting.

Everything else in the tool works without this. The right click entry is
the only thing that depends on it.

### Why the tool cannot just do it itself

Worth writing down, because it looks like it should be able to. Every
pyRevit command gets `__revit__`, and from 2025 that has
`RegisterContextMenu` on it — so the tool could register itself the
first time you opened it and nobody would ever touch `startup.py`. It
does not work: the call is accepted, the entry can even appear, and
`BuildContextMenu` is then never called back, so the item does nothing.
App-init hooks are reported as failing the same way. Registering has to
happen while the UI is being built, which means `startup.py`.

What the tool does instead is notice. Every time it opens on 2025 or
above without the entry registered, it writes a line to
`%APPDATA%\RevoBIM\logs\pro_sheets_exporter_context_menu.txt` saying the
block is missing and that a restart is needed after pasting it. That is
how an overwritten `startup.py` gets caught in a week rather than a
month.

### Added to the bench, thirty two rules now

New rule `context_menu_host`, built around the bug above: the host must
be chosen by capability and never by `hasattr` on one assumed object,
`register()` must take several candidates, the deferred
`ApplicationInitialized` route must exist, the handler must not be
detached with `-=` (IronPython does not reliably match it again), the
startup fragment must offer both names and unpack them, and nothing may
try to register from the running tool. Eight breakages, including the
exact 1.18.1 line and a fragment that offers only the object which lacks
the method on 2025.

32 rules, 68 breakages, every one of them fired when broken.

## 1.18.1

### Fixed: the default sort gave up quietly

1.18.0 only applied the series sort when the series column happened to
be in the list already, and skipped it without a word when it was not.
A template saved before 1.18.0 carries its own column list, without
that column in it - so anybody with a template from last week opened
unsorted and had nothing to tell them why.

The column is put back now, in front of Custom File Name, and the sort
applied. You cannot sort on a column that is not there, and the right
answer to that is to put it there rather than to abandon the sort.

### A template's own sort still wins, and now says so

A template remembers the sort it was saved with, which is the point of
a template - and if you saved one while sorted by Size last week, that
is what it opens in, correctly. What was missing was any way of
knowing that from looking at it.

The status line now says which sort came from the template and how to
change it: sort by the series and save the template again.

If you would rather the series sort always won, over templates too,
say so - it is one line. I have left templates in charge on the
grounds that somebody who saved a sort meant to.

### Added to the bench rule, thirty one still

`mode_columns` gains the opening sort: no saved sort starts on the
series, a missing series column is put back rather than the sort being
dropped, it lands before Custom File Name, a template's own sort is
never overwritten, and a project with no series parameter gets no
default sort at all. The breakage is 1.18.0's behaviour - give up when
the column is absent. Thirty one rules, sixty one breakages, all
firing.

## 1.18.0

### The sheet list starts with the columns you actually use

Sheet Number, Sheet Name, Revision, Size, **Current Revision Date**,
**sheet series**, **discipline**, Custom File Name - and sorted by the
series, so the colouring and the collapsible groups are worth
something on the first open rather than after three clicks.

The parameter columns go in front of Custom File Name rather than on
the end, because that column is the one that reads best last. Views
mode does not get them: no view has a value for any of the three.

A template that carries its own columns still wins. This is where a
list starts, not what it is stuck with.

### Setup asks what those parameters are called

`BGL_Sheet Series` and `BGL_Sheet Discipline` are what A2 calls them.
Another client's model calls them something else, and a tool that
hardcodes one office's shared parameter names is a tool that shows two
empty columns on every job that is not theirs.

So setup now asks, with a dropdown of the parameters the sheets in
this model actually carry, and the usual names already selected where
the model has them - which on your projects means there is nothing to
do but look at it and press Save.

There is a **(this project has none)** option for a model with neither,
and the columns and the default sort simply do not appear.

A saved name that this particular model does not have is kept and
offered rather than quietly dropped, with a note saying so. The answer
to "which parameter is it" should not change to something else just
because one project has not got it - that is how a setting ends up
wrong on every project after the one that changed it.

Changing either in setup rebuilds the list around the new answer
without a reopen.

### Added to the bench rule, thirty one still

`mode_columns` now holds the starting set: the parameter columns are
present, they sit before Custom File Name, the fixed five still come
first, Views gets none of them, a project with neither named gets the
plain set, and a name given twice makes one column. It also holds
`default_column_order` to the fixed set alone - a parameter column in
there would come back every time somebody removed one, because that is
the list `_sane_order` uses to decide what belongs.

Two breakages: the columns appended after Custom File Name, and sheet
parameters pushed onto the Views list. Thirty one rules, sixty
breakages, all firing.

## 1.17.0

### The house subfolder layout is the default

```
{Project Name}\{Year}-{Month}-{Day}_{Hour}_{Minute}\{BGL_Sheet Series}
```

Project, then a stamp for the issue, then the sheet series. A model
without BGL_Sheet Series still lands somewhere findable: an unresolved
token becomes `_unset` rather than collapsing the level, because a
level that quietly disappears moves every file up a directory and
nobody notices until a hundred PDFs are in the wrong place.

It is a default, so a template that already carries its own tokens
keeps them.

### Export starts on the first press

Suppress dialogs is on by default now, for new machines and existing
ones. The confirmation existed because a run used to be hard to
picture before it happened; the Create tab has shown every path, name
and folder for several versions, so asking again was a click for
nothing.

**The one refusal that is not suppressed** is a print driver with no
folder to collect from. That is not a confirmation, it is the run
declining to fail on every sheet, and suppressing it would be
suppressing the only warning that matters.

### Sheets go green as they are written

The Create list now colours each row as its file lands - green for
written, red for failed - so a long issue can be watched rather than
guessed at from a percentage. The tool switches to that tab when a run
starts, since that is where the answer is.

A failure wins over a success on the same row, and is never undone.
With PDF and DWG both ticked, a row that went green because the DWG
landed while its PDF did not is a row that lies.

Driven off the report rather than threaded through each exporter's
arguments: five of them add outcomes, and all five would have needed
the same extra parameter. A window that cannot repaint can never stop
an export - the callback is wrapped.

Painted with data triggers rather than in LoadingRow, because the grid
recycles row containers and a colour set on a container follows it
onto whatever row it is handed next. That is the bug that used to put
a group heading's colour in the middle of the sheets.

### The hint under the Create list is gone

It said "Nothing is written until Export is pressed", which stopped
being true the moment the rows started going green.

### A bench rule that was wrong

`style_targets` reported a fault on `RowStyle="{DynamicResource
PlanRow}"` - correct XAML - because its pattern read the tail of
`RowStyle=` as `Style=` and checked the style against the DataGrid
rather than against its rows. It now knows that RowStyle, CellStyle,
ColumnHeaderStyle and the rest carry a style for something the element
contains, and checks each against the right type. A new breakage hands
RowStyle a cell style.

`group_ticks` gains the row colour decision as a table, with a
breakage that lets a failed row go back to green. Thirty one rules,
fifty eight breakages, all firing.

## 1.16.0

### Revit's own exporter is the house default

Not just what a fresh machine happens to get - what every machine
gets, unless somebody opts out of it deliberately.

Three things were keeping a driver in play, and all three are now
closed:

**A saved default from an older build.** A default only applies where
the settings file says nothing, so shipping a new one does nothing for
anybody who already has the tool. Every machine that ran 1.9.1 to
1.13.0 has a driver written into its settings by the tool itself,
which would have gone on being used forever. The settings file now
carries a version, and coming from an older one clears that printer
once. Nobody chose those drivers; the tool chose them, and on every
machine they were tried on they wrote nothing.

**A template.** A template remembers the printer it was saved with,
which is right for a template and wrong to obey without question - one
shared `.rbtpl` would otherwise put a whole team back on PDF24. A
template's driver no longer overrides the machine.

**Setup.** Still offers the driver, and picking one still switches to
it. What is new is the tickbox above it: *ignore what a template asks
for and always use Revit's own exporter*, on by default, and turned off
automatically the moment a driver is chosen, because saving both would
store a preference the next template load quietly undoes.

Revit 2021 and earlier are unaffected - with no built-in exporter to
fall back to, the driver is kept whatever else is true.

### Why this way round

A driver costs a spooler round trip, paper size matching against
whatever sizes it happens to offer, a folder to collect from and a
per-machine setup that cannot travel in a template. What it buys is the
driver's own output settings - compression, stamps, PDF/A. Worth it
where a house standard lives in the driver; not worth it otherwise, and
"otherwise" is the common case.

The three messages when a template's driver is set aside now say which
of the three reasons applied, rather than guessing at one.

### The bench table, rewritten

`known_printers` carries the decision with the house default both on
and off: on, a template driver is always refused and says why; off, the
old rules apply - installed and with a folder is kept, not installed or
no folder falls back. Two breakages, one of which ignores the house
default so a shared template drags a team onto a driver nobody chose.
Thirty one rules, fifty six breakages, all firing.

## 1.15.2

### The log now says whether the driver even got the sheet

The question every one of these failures has turned on, and the tool
could not answer it. Revit reporting a clean submit says only that
Revit handed the job over. What happened next was invisible, so "no
file appeared" had to cover a driver that saved somewhere unexpected, a
driver waiting on a dialog, and a driver that threw the job away -
three different problems with one message between them.

The Windows print queue for that printer is now read when nothing
turns up, and the three cases are told apart:

- **Jobs still queued.** The driver has the sheet and has not finished
  with it. That is it waiting on something, nearly always its own Save
  As or assistant window sitting behind Revit.
- **Queue empty.** It finished with the sheet and either wrote it
  somewhere other than the staging folder or discarded it. Automatic
  saving is most likely off.
- **Queue unreadable.** Said as much, rather than guessed at.

The count and the driver's own queue status go in the debug log either
way, along with how long the tool waited.

## 1.15.1

### The wait was too short

1.15.0 fixed the print. This fixes the waiting for it.

`SubmitPrint returned with no error after 8.97s` is the line that
matters: Revit really did render the sheet this time, where before it
was returning in 178 milliseconds having done nothing. Nine seconds of
spooling, and then the tool gave the driver **fifteen seconds** to
convert that spool file into a PDF and gave up.

Fifteen seconds was always a guess, and it is the wrong guess for the
sheets this tool exists for. A sheet slow enough to take nine seconds
to spool is a sheet slow to convert.

The wait is now scaled off the render - six times it - with a floor of
a minute and a ceiling of seven. Nine seconds of rendering gets a
minute of waiting rather than fifteen seconds. The budget goes in the
debug log before the wait starts, so it is never a guess again, and
Stop interrupts it.

### A file that lands late is no longer lost

The old behaviour after a timeout was to move on and report nothing
written, leaving the PDF to appear a few seconds later under the
driver's own name with nobody told. The run now takes one more look at
the staging folder before calling itself a failure, and where files
turned up late it says how many, where they are, and that the driver is
simply slower than the wait allowed.

### Added to the bench rule, thirty one still

`print_outside_transaction` gains the wait budget as a table: an
instant render still waits a real length of time, nine seconds gets a
minute, thirty seconds gets three, a very slow one is capped, and
nonsense falls back to the floor. Its new breakage puts the fixed
fifteen seconds back. Thirty one rules, fifty five breakages, all
firing.

## 1.15.0

### Fixed: nothing was ever printed through a driver

The real one. Not the folder, not the driver, not PDF24 - the tool.

`PrintManager.SubmitPrint()` was being called with a transaction still
open. Revit 2024 and later do not object to that: the call returns, at
once, successfully, having printed nothing whatsoever. The transaction
was there because the paper size lives on `PrintParameters`, which is a
document element and does need one - but it was opened around the whole
run instead of around the setup, so every submit happened inside it.

Two machines, two afternoons, and three plausible wrong answers -
PDF24's auto-save, the staging folder, DiRoots' private printer - all
chasing a driver that was never sent anything. What gave it away was
the timing in the second log: **178 milliseconds** to render an A0
sheet. Nothing renders an A0 sheet in 178 milliseconds. Sam's took 3.7
seconds, which is why his looked more like a real failure and misled me
for longer.

The transaction is now opened per sheet, around the print setup only,
and committed before the job is submitted. The debug log also times
every submit and says outright when one comes back too fast to have
done anything, so the next instance of this is one line rather than two
afternoons.

**This is almost certainly the whole of it.** The staging folder advice
was not wrong, but it could never have worked while nothing was being
sent to the driver at all.

### Finding the driver's folder, with a button

Browse was the only way to fill in "Driver saves to", which is no help
when the honest answer is that you do not know where the driver puts
things. Setup now spells out the order to do it in - turn on automatic
saving in the driver, print one page to it, then come back - and has a
**Find it** button that looks for PDFs written in the last ten minutes
and fills the box in.

Nothing found gets the reason and the three steps rather than a shrug.
More than one folder gets the list, because guessing between them would
be worse than asking.

### One more bench rule, thirty one in all

`print_outside_transaction` fails if `SubmitPrint` ever appears between
a `transaction.Start()` and its `Commit()` again, and if the debug log
stops flagging an implausibly fast submit. The breakage puts the
transaction back around the submit. Thirty one rules, fifty four
breakages, all firing.

## 1.14.1

### Fixed: the tool stopped looking for the file as soon as a folder was set

This is why Sam's second attempt failed the same way as the first, and
why the report was no help.

The scan for "where did the PDF actually go" was skipped entirely when
"Driver saves to" had something in it. The reasoning was that a folder
has been given, so there is nothing to find - which is wrong, because a
folder that is **set but wrong** looks from the outside exactly like a
driver that is prompting. The tool reported the second while the file
was sitting in the first, and told him to go and turn on automatic
saving in a driver that already has it on.

The scan now runs whichever it is, skipping the staging folder itself
so only a PDF somewhere unexpected counts. When one turns up the report
names the folder it went to, says that is not the folder it was told to
collect from, and offers to adopt it in one click.

### The heart of it: that folder is the driver's, not yours

"Driver saves to" tells the tool **where to look**. It cannot tell the
driver where to put things - no tool can, it is a setting inside the
driver. Typing the folder you want the PDFs in is therefore the natural
thing to do and it cannot work.

Both the setup window and the Format tab now say so in those words,
rather than the previous wording which could be read either way.

### Fixed: a template's printer obeyed on a machine that cannot use it

Setup can save "use Revit's own exporter" and the next run still go
through the driver, because the printer is also carried in the
template, and the template is applied after. That is right for a
template - it should remember what it was saved with - and wrong to
obey blindly, because a driver is a fact about a machine.

A template naming a driver that is **not installed here**, or one this
machine has no "Driver saves to" folder for, now falls back to Revit's
own exporter and says what it did and why. Where there is no built-in
exporter to fall back to - Revit 2021 and earlier - the driver is kept,
because a broken driver beats no route at all.

### What to do on Sam's machine

Use Revit's own exporter. It needs none of this, writes the exact file
name asked for, and is faster. `diroots.prosheets` is ProSheets' own
private instance of PDF24 and DiRoots drive it through their own
application - printing to it from outside that application is not
something it is set up for, and the log shows it taking the job,
reporting no error and producing nothing, which is what that looks
like. PDF24's assistant window opening behind Revit is the other
likely half of it.

### Two bench rules extended, thirty still

`known_printers` gains the template-printer decision as a table: a
driver with a folder here is kept, one with no folder falls back, one
not installed falls back, and on a Revit with no built-in exporter
nothing falls back.

`naming_behaviour` gains the folder comparison, which had a bug of its
own worth recording. It was built on `os.path.abspath` and
`os.path.normcase` - both of which answer for the platform they run
on. The bench runs on Linux and the tool runs on Windows, so a
comparison built on them passes here and fails there: the worst of both
places. It squares up the separators by hand now, and the breakage puts
the platform-dependent version back. Thirty rules, fifty three
breakages, all firing.

## 1.14.0

### Fixed: a fresh machine picked a driver it had not been told how to use

This is what happened on Sam's machine, and it is mine from 1.9.1.

That release made the tool select a known print driver automatically
whenever it found one installed - `diroots.prosheets` being the one it
knows. That is right for a machine already set up for that driver and
wrong for every other machine, because **a driver writes nothing at all
until "Driver saves to" is filled in**. It saves to its own output
folder, the tool collects the file from there and renames it, and with
no folder to collect from every sheet fails with "no file appeared" -
which reads like a Revit fault and is not one.

A known driver is now **offered**, never chosen unasked. Nothing but an
explicit choice goes into the printer setting, so a machine that has
said nothing gets Revit's own exporter, which needs no setup at all.

### A run that cannot write a file now refuses to start

A driver selected with no folder to collect from is the one state where
the outcome is certain before the first sheet. Export now stops on it
and says so, with **Use Revit's own exporter** as one button and
**Open setup** as the other. Suppress dialogs does not silence it,
because it is not a Revit dialog - it is the run declining to waste ten
seconds per sheet arriving at a foregone conclusion.

### Set up this machine

A window that opens the first time the tool runs on a computer, and
from **Set up** in the header afterwards. It asks the three things that
are per machine and therefore cannot travel in a template:

- **How PDFs get written** - Revit's own exporter, or a driver. The
  driver's printer and its "Driver saves to" folder are on the same
  screen as the choice, so it is not possible to pick the driver and
  walk away without the thing it needs.
- **Where exports land** by default, suggested from the model's own
  folder.
- **What this machine has** - whether Revit's exporter exists here,
  how many printers are installed, and whether the ProSheets driver is
  among them, with what it still needs spelled out.

**Test it** reports what would stop a run, without writing anything.
Closing the window without saving does not mark setup done, so it asks
again next time: the cost of asking twice is a click and the cost of
not asking was a failed test on somebody else's desk.

### Two more bench rules, thirty in all

`module_calls` is the one that matters. `ps_ui.theme_of()` - a helper
that does not exist and never did - got into this very release, sitting
in a branch that only runs when one button on one window is pressed, so
importing the module proved nothing and neither did opening it. Every
`ps_x.something` in the tool is now checked against what `ps_x`
actually defines, statically, so a branch nobody walked is checked
exactly like one that runs on load. Its breakage puts that call back.

`known_printers` gains the refuse-to-start decision as a table: a
driver with no folder blocks, with a folder does not, Revit's own
exporter never does, a run with no PDF in it never does, and a folder
of nothing but spaces counts as empty. Thirty rules, fifty one
breakages, all firing.

## 1.13.0

### Ticking one of a highlighted block ticks the block

Highlight a run of rows the usual way - click, then shift click, or
ctrl click a few - and tick any one of them. All of them follow, the
way a spreadsheet does. Unticking works the same.

A tick on a row **outside** the highlighted block is still just itself.
Otherwise ticking one sheet while a block was highlighted somewhere
further down the list would quietly tick that block too, and the count
at the bottom would be the only sign.

The highlighted rows are read in the click handler that runs *before*
the click has been dealt with, not when the tick is reported. By that
point the DataGrid may well have reduced the selection to the row that
was clicked, and the rest of the block is already gone. The captured
list is good for one tick only - a tick from the keyboard, or a second
tick without a fresh click, is one row's business.

Group headings in the highlight are skipped: a heading's own tick
already means "the whole group", and letting it be both would make the
result depend on where in the block it sat.

### Added to the bench rule, twenty nine still

`group_ticks` gains the decision as a table: a tick inside a block of
three reaches all three, outside it reaches only itself, a block of one
is itself, nothing highlighted is itself, and keys that arrive as
numbers rather than strings still match. Its new breakage drops the
"was the ticked row part of the block" test, which is the version that
drags in a block highlighted for something else. Twenty nine rules,
forty nine breakages, all firing.

## 1.12.1

### Sorting turns Group matching values back on

Sorting a column and colouring its matching values are the same intent -
you sort by discipline to see the disciplines - so finding the colours
off because the tick box was cleared twenty minutes ago is a surprise
with no explanation on screen. Clicking a heading now switches grouping
on if it is off.

The tick box stays, for the case where grouping is genuinely in the way:
untick it and the current sort goes plain. The next sort turns it back
on, which is the behaviour worth having - the box is a temporary "not
for this" rather than a setting to remember.

The tick is set with its own handler suppressed. Letting it run from
here would rebuild the groups against the order the sort is about to
replace, and do the whole pass twice.

### Fixed: a new sort reopened the list with unrelated groups collapsed

Longer standing, and only noticeable once there was something to
collapse. A group number is a position in **one sort's** list of values -
group 3 under Discipline and group 3 under Size have nothing to do with
each other - but the set of collapsed groups was carried across a sort,
so re-sorting could shut two or three groups for no visible reason. The
set is let go of when the sort changes.

### One more bench rule, twenty nine in all

`sort_groups` holds both: sorting turns grouping on and reports that it
did, `_on_sorting` clears the collapsed set, `toggle_grouping` honours
the suppression flag, and - the one that would be nastiest to find -
the flag is always let go of again. Leaving it set would kill the tick
box silently for the rest of the session, and nothing else would look
wrong. Its three breakages do one each. Twenty nine rules, forty eight
breakages, all firing.

## 1.12.0

### A mark of its own on each format tile

The tiles were a coloured page with the three letters in a band. Each
now carries a drawing that says what the format is for:

- **PDF** - a page of text, in a deeper red.
- **DWG** - an isometric wireframe in **yellow on blue**, which is the
  colour language people read as CAD.
- **NWC** - two models overlapping, which is what the format exists to
  do.
- **IFC** - a structure with its nodes: a building carrying data.
- **DWF** - the same family, quieter, since it is still not wired up.

These are drawn here rather than taken from anybody's brand. The
Acrobat, AutoCAD, Navisworks and buildingSMART marks are trademarks
their owners control, and a tool that ships copies of them puts that on
whoever installs it. What actually does the work at 32 pixels is the
colour and the silhouette, and those are free - so the DWG tile is blue
and yellow and reads as CAD instantly without being the AutoCAD logo.

If your organisation is licensed to use the real marks, the tiles are
plain XAML in `ProSheets.xaml` and the drawing in each is four or five
lines inside a `Canvas`; swapping one for an `<Image>` is a two minute
edit, and the delivery notes say where.

The palette moved with them. IFC is indigo rather than blue so it does
not read as a second DWG, DWF is grey now that violet is doing nothing,
and there is a second brush per format for the mark drawn on top of the
page.

### The bench now checks the tiles are actually different

Extended `format_registry`: each tile has to draw a Canvas, and no two
tiles may draw the same thing. A duplicated tile whose drawing was never
changed is the easy mistake here and the one nobody reports - two
formats wearing the same icon just look like a tool that could not be
bothered.

Its breakage gives NWC the PDF drawing. Writing it caught the rule
comparing the label underneath the tile as well as the picture, which
made every tile unique by definition and the rule useless; it compares
the drawing alone now. Twenty eight rules, forty five breakages, all
firing.

## 1.11.2

### Fixed: a heading's tick box collapsed the group instead of ticking it

1.11.1 added the behaviour and then made it unreachable. The collapse
handler runs on `PreviewMouseLeftButtonDown`, which fires **before** the
CheckBox sees the click, and it sets `Handled` to stop the click also
selecting the row - so every click on a heading, tick box included, was
eaten and turned into a collapse. The tick could not be reached at all,
which is why it looked like the feature had not been built.

The tick box is now an exception in that handler, where it has to be:
by the time the CheckBox's own handler would run, the click is already
gone. Clicking anywhere else on a heading still collapses it.

The decision is a three-line function of its own rather than a
condition buried in an event handler, so the bench can hold it to a
truth table - on a heading collapses, on a heading's tick box does not,
on an ordinary row does not, and with grouping off nothing does.

### Every value gets a heading now, including the ones that appear once

`MIN_RUN` is 1. A value that turns up once gets the same heading, the
same collapse and the same group tick as one that turns up nine times.

The cost is the one I flagged when arguing the other way, and it is
real: sorting by a column where nothing repeats - Sheet Number being the
obvious one - now puts a heading above every row and doubles the length
of the list. That is the sort you do to find a single sheet, so it is
the sort where grouping earns least; untick **Group matching values**
for it. Everything else is better with headings everywhere, and
consistency beats my cleverness.

### Two bench rules updated, twenty eight still

`value_runs` now fails if a single value is left without a heading - the
opposite of what it asserted yesterday - and its breakage puts `MIN_RUN`
back to 2. `group_ticks` gains the click truth table, with a breakage
that swallows the tick box into a collapse again. Twenty eight rules,
forty four breakages, all firing.

## 1.11.1

### A group heading's tick ticks the group

The tick box on a group heading was bound to the same field as every
other tick and did nothing, because a heading holds no sheet. It now
ticks or unticks every sheet in that group.

**Including the ones a collapsed group is hiding.** A tick that quietly
meant "all of these except the ones you cannot see" is the kind of thing
that gets found out at the end of a two hundred sheet issue.

It works the other way too: tick the last unticked sheet in a group by
hand and the heading lights up, untick any one of them and it clears.
A heading that says the group is ticked when it is not is worse than no
heading tick at all. Tick all, Tick none and Invert keep the headings in
step the same way, and a sort that rebuilds the groups puts the headings
back in step with whatever was already ticked.

### One more bench rule, twenty eight in all

`group_ticks` holds both directions against a stand-in table: a heading
reaches its hidden members, a heading with one member unticked does not
read as ticked, ticking the last member lights the heading, and the sync
leaves sheets outside any group alone. Its two breakages are a heading
tick that stops at the visible rows, and a heading that lights up on any
member rather than all of them.

Writing it turned up a real one straight away. `_sync_group_ticks`
returned early when there were no groups, which is an optimisation that
leaves a heading whose group has gone holding a tick nothing stands
behind. The walk is cheap; the early return is gone. Twenty eight rules,
forty three breakages, all firing.

## 1.11.0

### A colour of its own for every value, repeated or not

1.10.0 only coloured values that repeated, and alternated two strengths
of one colour to keep touching blocks apart. Every value now gets a
colour of its own, including the ones that appear once - so
E-100-CONTAINMENT and E-300-LIGHTING are as visible as the four drainage
sheets sitting between them.

With a colour per value the alternation is no longer what tells
neighbours apart, so it is gone. The colours are generated rather than
listed: twelve hues evenly spaced, at a saturation and lightness tuned
per theme, starting at the house orange so the first group still looks
like the rest of the window. A sort level list can be six entries long
because there are only ever six sort levels; a discipline column has as
many groups as it has values, which is not a thing you can write down in
advance.

**A run of one still gets no heading.** It gets the colour, which is
what was asked for, but a heading saying "1 sheet, Collapse" over
something there is nothing to collapse would be noise - and sorting by
Sheet Number, where nothing repeats, would double the length of the
list. So: every value coloured, headings only where there is something
behind them. The status line now says both numbers.

### Group headings read in blue, a size up

Set as a data trigger on the cell style rather than on the row. The cell
style sets `Foreground` and `FontSize` explicitly, and an explicit
setter beats anything the row hands down by inheritance, so blue set on
the row alone would never have reached the text.

The heading band is now the **quieter** tone of its colour and the cells
of the sorted column are the loud one - the opposite of how it looks
like it should work. Heading text is blue, and blue on a saturated green
or teal cannot be read at all, so the band is a dark tint of the hue in
dark mode and a pale one in light. The full strength colour still
appears where the eye is actually doing the matching, on the cells
themselves.

### Collapse all lights up while grouping is live

It was one more grey chip in a row of grey chips, which is the wrong
signal for the only control on that toolbar whose state changes what the
list looks like. It now wears an accented style with a blue edge while
there is something to collapse, and greys out properly when there is
not.

### One more bench rule, twenty seven in all

`group_colours` holds the generated ramp: every colour a valid hex, no
two groups the same, neighbours far enough apart to tell apart, the ramp
cycling cleanly past its end, and - the one that matters - the heading
band darker than the cell in dark mode and lighter in light mode, so the
blue heading text always has somewhere to sit.

It earned its place immediately. The light palette as first written had
neighbouring hues too washed out to separate, at three points in the
ramp, which the rule caught before the zip was built. The fix was more
saturation in light mode, not a looser threshold. Twenty seven rules,
forty one breakages, all firing.

## 1.10.1

### Fixed: a white bar across the selected row in dark mode

Mine, from yesterday, and the same mistake as 1.6.0 by the same
mechanism.

1.10.0 put a coloured cell style on whichever column is sorted. To keep
the other columns plain it set their `CellStyle` back to `None` - and a
local null on a style property is a **value**, not "unset". WPF stops
applying the implicit style the moment a local one exists, so every cell
outside the sorted column dropped to the default template. An unstyled
`DataGridCell` is transparent, which is invisible against a dark grid, so
nothing looked wrong until a row was selected - at which point the
default template painted it in the system highlight. White bar, only on
the selected row, only once a sort had put a style on some other column.
That is exactly why it appeared when sorting.

The fix is to hand those columns the plain cell style **by name** rather
than clearing the property. The lesson is the one already written above
`_styled` for the Custom File Name heading in 1.6.0; I had written the
warning and then walked into it from the other direction.

### Windows no longer gets to paint any of this

The second half of the same problem, fixed while in there. Anything that
does fall back to a default template draws its selection from
`SystemColors`, and the **inactive** variant on Windows 10 and 11 is near
white - so a grid that has just lost focus to a column heading, which is
what clicking a heading does, shows a pale bar even when everything else
is right. `theme.apply` now writes the palette behind
`HighlightBrushKey`, `HighlightTextBrushKey`, the two inactive
equivalents, `ControlBrushKey` and `WindowBrushKey`, keyed by the
`SystemColors` key objects so they swap with the theme like everything
else.

### Two more of the same bug, found by the new rule

The context menu and its items were also assigning a `TryFindResource`
straight to `Style`. Both keys exist, so it was latent rather than
broken, but a missing key would have given a white context menu in dark
mode for the same reason. Both go through `_styled` now.

### One more bench rule, twenty six in all

`selection_chrome` refuses a local null on any style property - `Style`,
`CellStyle`, `RowStyle`, `HeaderStyle`, `ElementStyle`, `CellTemplate`
and the rest - and refuses a resource lookup assigned straight to one of
them without a null guard. It also checks `theme.apply` overrides the
`SystemColors` selection brushes. Its three breakages are the 1.10.0
fault, the 1.6.0 fault, and dropping the inactive selection override.

Writing it turned up a wrinkle worth keeping: the rule read the warning
in `_styled`'s own docstring as an instance of the thing it warns about.
Source is now tokenised and every string and comment blanked before
scanning, with the line numbers preserved, so a rule can never again be
tripped by prose describing the bug it exists to catch. Twenty six
rules, thirty eight breakages, all firing.

## 1.10.0

### Dark and light now follow Revit, and keep following it

The theme chip has three states rather than two: **Auto**, **Dark**,
**Light**. Auto is the default and matches Revit's canvas, which is the
house standard.

The reason it needed fixing is that "follow Revit" already existed and
already worked on open - but the chip saved the *resolved palette* rather
than the mode, so the first time anybody touched it, "follow" was
overwritten with "dark" and the window never followed again. Mode and
palette are now two separate things: the mode is what gets saved, the
palette is what that mode currently resolves to. The chip reads
"Auto (dark)" so it is clear which is which.

The mode goes in a **new setting**. The old one held whatever palette the
chip last resolved to, and a "dark" sitting in it cannot be told apart
from a deliberate pin, so reusing it would leave everybody who ever
clicked the chip still pinned after upgrading - which is exactly the
thing being fixed. Everyone starts on Auto; the old key is left alone.

Auto is also live. Change Revit's theme with the window open and the
window changes with it, within a couple of seconds - the sort outlines,
the run colours and the group washes included, since those are brushes
set in code and do not follow a palette swap on their own.

That is a timer reading a property every two seconds, not a subscription
to Revit's theme changed event, and deliberately so: unsubscribing an
IronPython bound method from a .NET event does not reliably work - each
attribute access makes a fresh delegate, so the `-=` removes nothing -
and a modeless window that leaks a handler onto the application outlives
itself. A `DispatcherTimer` stops when it is told to, and it is told to on
close.

### Sorting colours the runs of matching values

Sort a column and each stretch of rows sharing a value in it is coloured
and becomes collapsible, with no separate step. The **cells** of the
sorted column carry the colour at full strength and the rest of the row
takes a wash of it, so a block is followed down the page without the
colour fighting the text. Touching runs alternate between two strengths,
or two blocks that happen to sit next to each other would read as one.

**A value that appears once is left alone.** This is the whole difference
between automatic grouping that helps and automatic grouping that is
worse than none: sort by Sheet Number, where nothing repeats, and the old
behaviour would have given four hundred headings above four hundred
groups of one. A run has to be at least two rows to become a group, and
the status line says so when a column has no repeats in it at all.

Runs are **consecutive** rows, not distinct values. After a sort those are
the same thing, and a stretch of touching rows is what the eye actually
reads as a block.

The tickbox is still there, now reading **Group matching values** and
ticked by default, so it can be turned off. Collapse, Collapse all and
the group counts work as they did.

Colouring a cell rather than a row needed one change in `Theme.xaml`: the
`DataGridCell` style is now keyed as well as implicit, so the sorted
column's cells can be `BasedOn` it instead of replacing it. A code built
style assigned to `CellStyle` beats the implicit one outright, and a cell
with no template renders as OS chrome - the same trap the Custom File
Name heading fell into in 1.6.0. The run colour is carried on the row
itself, in a column holding an actual brush, because a run's colour
depends on where it sits among the other runs and no style trigger can
know that. It always holds a real brush, never empty: a Setter handed
DBNull cannot convert it to a Brush and the cell loses its background
entirely.

### Two more bench rules, twenty five in all

`value_runs` holds the run splitting to a table of cases - a run of one
is not a group, every row lands in exactly one run, a value that comes
back later starts a new run - with breakages for the group-of-one fault
and for an off-by-one in where a run starts.

`theme_modes` holds the mode mapping and, more to the point, fails if
`ps_window` ever saves the resolved palette as the theme setting again.
That is the exact bug this release fixes and it is invisible from the
outside: everything looks right until one click on the chip, after which
it silently never follows Revit again. It also checks the watch timer
exists and is stopped. Twenty five rules, thirty five breakages, all
firing.

## 1.9.1

### "diroots.prosheets" is found and used as the driver default

ProSheets installs its own private instance of PDF24 under the name
`diroots.prosheets`, already set up not to ask where to save. That is the
whole reason their batch export runs unattended while a hand-rolled one
against the main PDF24 printer sits waiting on a Save As dialog - and it
is the thing that cost 1.0.1 to 1.2.1 to work out from the outside.

If it is on the machine, the tool now finds it. On a machine with no
printer choice saved yet it is picked as the default instead of the
built-in exporter, on the grounds that somebody who has ProSheets
installed almost certainly wants the PDF settings that came with it. A
saved default or a template's printer still wins - this only fills the gap
where nothing has been chosen.

Selecting it says what it is rather than repeating the generic warning:
the note under the dropdown no longer tells you to go and set it not to
prompt, because it already is not prompting. The pre-export confirmation
drops that line too, and the debug log records that the driver is a known
one - so a missing file on that printer is a staging folder problem rather
than a dialog sitting behind Revit, which is a much shorter thing to chase.

It is still PDF24 underneath, so it still writes to PDF24's own output
folder rather than to the path Revit asks for, and **Driver saves to**
still has to point at that folder. The run-one-sheet-and-use-the-folder
shortcut in the report already looks in the DiRoots folders.

When the built-in exporter is selected and `diroots.prosheets` is
installed, the note says so once. Leaving a driver that works sitting
undiscovered in a dropdown is its own kind of bug.

Matching is on letters and digits alone, so `DiRoots.ProSheets`,
`diroots prosheets` and a redirected copy carrying a session suffix all
count as the same printer.

### One more bench rule, twenty three in all

`known_printers` holds the match against a table of names, because both
ways of getting it wrong are quiet. Too strict - taking the dot in the
name literally - and a machine that has the driver is left on the built-in
exporter and nobody notices. Too loose and a plain `PDF24` printer gets
announced as one that does not prompt, which is precisely the advice that
wastes an afternoon. Its two breakages do one of each. Twenty three rules,
thirty breakages, all firing.

## 1.9.0

### "Print Selected" on the Project Browser right click menu

Right click in the Project Browser - or in the canvas - and there is a
**Print Selected** entry at the bottom that opens Pro Sheets Exporter with
whatever was selected already isolated and ticked. The tool has always
picked up a pre-selection; this saves the trip to the ribbon.

**Revit 2025 and up. Dormant on 2024 and earlier**, which is not a
limitation of the tool: `IContextMenuCreator`, `ContextMenu`,
`CommandMenuItem` and `UIControlledApplication.RegisterContextMenu` are all
2025 API and simply do not exist before that. On 2024 the feature writes
one line to its log saying so and nothing else happens - the tool is
otherwise identical.

Custom entries can only be appended to the end of Revit's own menu. There
is no way to insert one further up or to replace what Revit puts there.

### One block has to go into the shared startup.py

`RegisterContextMenu` has to be called during `OnStartup`, and the only
place a pyRevit extension gets a `UIControlledApplication` is the
extension's `startup.py`. That file is **shared and singular**, so this
delivery does not ship it. It ships `startup_fragment.py` instead: a
banded, wrapped, idempotent block to paste into the `startup.py` already
there.

Everything else in 1.9.0 works without pasting anything. The only thing
missing is the right click entry.

### Three decisions inside it worth knowing

**Nothing 2025-only is imported at module level.** `ps_context` is
imported from the shared `startup.py`, and a `startup.py` that throws
stops pyRevit loading *every* tool in the extension, not just this one. So
a 2025-only import at the top of that module would not break Pro Sheets
Exporter on Revit 2024, it would break the whole extension. Every one of
those names is imported inside a function past the version gate, including
the base class of the creator - a class statement runs at import just as
an import does. The new `context_menu_gate` bench rule fails if any of
them moves to the top of the file.

**The command is resolved on every right click, not once at startup.**
`CommandMenuItem` wants an `IExternalCommand` class name and the assembly
holding it, and pyRevit generates that assembly itself, rewriting it under
a fresh name on every reload. A path captured at startup is stale the
moment somebody reloads pyRevit, and the entry silently stops doing
anything - which is what the pyRevit forum thread on this ends with.
`BuildContextMenu` runs afresh on each right click, so the lookup happens
there, by scanning the loaded assemblies for a concrete
`IExternalCommand` whose name carries this tool's. That is deliberately
not a guess at pyRevit's naming scheme, which has changed between
releases.

**The entry is always added, never conditionally.** Autodesk have an open
bug, REVIT-251042, where a creator that adds nothing still leaves an empty
flyout hanging in the Project Browser - it does not happen in the canvas.
So rather than hiding the entry when the selection is not useful, it is
always there. An entry that is occasionally pointless beats a blank
sub-menu that looks broken.

### The second anchor

The shared files rule says a feature must not hang off one shared file,
because two anchors is one bad zip away from none. This feature can only
have one - a hook is too late, since by `ApplicationInitialized` there is
a `UIApplication`, which has no `RegisterContextMenu`. So the second
anchor is not another place to register from: it is the tool noticing.
Every time the window opens on Revit 2025 or later with the entry not
registered, it writes a line to
`%APPDATA%\RevoBIM\logs\pro_sheets_exporter_context_menu.txt` saying the
startup block has gone. An overwritten `startup.py` now leaves a trace
rather than a feature that quietly stopped existing.

### Two more bench rules, twenty two in all

`context_menu_gate` holds all of the above: no 2025-only import or base
class at module level, `MIN_VERSION` is 2025, `build_menu` resolves the
command rather than reusing a captured one, and the shipped fragment is
banded, wrapped and actually calls `register`.

`shared_files` is the project's shared-files rule made mechanical. It
walks the whole delivery and fails on a `startup.py`, a `hooks` folder, a
`lib\revobim\__init__.py` or a `<Panel>.panel\bundle.yaml` - the four
files there is exactly one of per extension, where shipping one silently
deletes whatever the last tool put there and nothing reports it. It should
be copied into every other RevoBIM tool's bench. Twenty two rules, twenty
eight breakages, all firing.

## 1.8.0

### Coloured format icons, and DGN and IMG gone

Each format now has a colour of its own - PDF red, DWG green, NWC teal,
IFC blue, DWF violet - drawn as a filled page with a folded corner and
the three letters in a band across the bottom. Which formats are ticked
now reads at a glance rather than by reading five labels in the same
grey.

DGN and IMG are removed rather than greyed. A tile nobody can ever tick
is noise, and the row has four live formats to carry now. DWF is still
drawn and still disabled, because it is the one of the five that is
genuinely next rather than hypothetical.

### NWC export

The Navisworks tile is live, with the settings from Revit's own exporter:
construction parts, element Ids, element parameters (All / Elements /
None), element properties, linked files, room as attribute, URLs,
coordinates (Shared / Internal), divide file into levels, export room
geometry, try and find missing materials, and the 2020-and-above three -
convert linked CAD format, convert lights and the faceting factor. The
defaults match Revit's.

**The tile is only live when a 3D view is ticked.** Navisworks export is
scoped to a view and has no concept of a sheet, so in Sheets mode the
tile is greyed with the reason on the tab, and in Views mode it waits for
a 3D view. Tick eight views with one 3D among them and only the 3D one is
exported; the report says how many were skipped and why.

The Navisworks exporter add-in ships with Navisworks, not with Revit. If
it is not installed the first view fails, the run stops rather than
repeating the same ten-second failure per view, and the report says so in
those words.

### IFC export

The IFC tile is live too, with Revit's full option set: Setup, General
(version, file type, phase, space boundaries, project origin, split by
level, steel elements), Additional Contents, Level of details, Property
Sets - including the two file pickers and everything that greys out with
its parent tickbox - and the whole Advanced column.

Three of Revit's buttons - File Header Information, Project Address and
Classification Settings - explain themselves rather than pretending. All
three are stored against the project by Revit and reused on every export
including this one, and the API offers no per-run override, so a value
typed here would be a value quietly thrown away. Each says where to set
it once so every export from this tool carries it.

**Import / Export** under Advanced saves the IFC options as a `.rbifc`
file and loads one back. Setups live in `%APPDATA%\RevoBIM\ifc_setups\`,
not per project - an IFC setup is a house standard, whereas a template is
about one job's folders and sheet list - and whatever is in that folder
fills the Current Setup dropdown. Importing from anywhere keeps a copy
there, so it shows up next time.

Like NWC, IFC waits for a 3D view.

### Views mode has its own columns

Switching to Views used to leave the sheet columns in place: Sheet
Number, Revision and Size, three permanently empty columns taking half
the grid, because no view has a value for any of them. Views now starts
with **View Name** and **Custom File Name**, and everything else is a
parameter column added by right clicking a heading - which in Views mode
offers view parameters, because the catalogue is built from the rows on
screen.

Each mode remembers its own columns, widths, sort and searches, so
switching across and back does not throw away either. A template saved
against sheets and opened in Views has its sheet-only columns dropped and
its parameter columns kept, rather than being refused; the other
direction puts Sheet Number, Revision and Size back.

The Create list follows the same rule - "Sheet" becomes "View type" and
Size is hidden.

### Fixed: the progress bar slid backwards with two formats ticked

It took each exporter's own position in its own list as the number done,
so the second format restarted the count and the bar went back to the
left halfway through the run. It now counts files across the whole run.

The file count was wrong in the same place and for a related reason: it
was sheets times formats, which overstates whenever NWC or IFC is ticked
(they only take the 3D views) or the PDFs are being combined into one. It
is now worked out per format, which matters because it is the number the
bar divides by.

### Fixed: a view's fallback file name was its view type

With no naming rules matching, a view fell back to `row.number`, which in
Views mode carries the view type - so a run could write `ThreeD.pdf`. It
falls back to the view's name now.

### Two more bench rules, twenty in all

`format_registry` holds the new one-row-per-format table against the
Format tab: every tick, tile, group and panel it names has to exist, every
live format has to have a panel, every tile drawn on the tab has to be in
the table, and DGN and IMG have to be gone from both. That table is what
replaced hardcoded control-name pairs in six separate methods, which is
how DGN and IMG came to be drawn with nothing behind them in the first
place.

`mode_columns` holds the two column sets to their contract: both start
with the tick column and carry Custom File Name, Views carries none of
the three sheet-only columns, and a template crossing between modes keeps
its parameter columns and gets the fixed ones back. Twenty rules, twenty
four breakages, all firing.

## 1.7.2

### Fixed: the Selection page was laid out on top of itself

The sheet table was missing `Grid.Row="2"`. I dropped it in 1.6.0 when the
columns moved out of the layout and into code, and nothing complained: a
child with no `Grid.Row` lands in row 0, so the table drew straight over
the first toolbar row - hiding Sheets/Views, the View/Sheet Set filter and
the search box completely - while row 2, the one that stretches, stayed
empty. That is the screen of blank space under the sheets.

It is only obvious with a handful of sheets showing, which is why
selecting from the project browser is what made it visible.

**New bench rule, `grid_placement`.** It parses every layout and fails
where a Grid declares rows or columns that nothing sits in, because an
empty declared row is the signature of exactly this mistake. Nothing
throws when it happens, the XAML is valid, and it can only be caught by
eye otherwise. A layout that genuinely wants a spacer can say "spacer row"
in a comment. Its selftest removes that `Grid.Row="2"` again. Eighteen
rules now.

### Format tab icons

The seven format tiles were empty bordered rectangles. They are now pages
with a folded corner, orange for PDF and DWG and muted grey for the five
that are reserved, with the whole tile as the click target rather than an
invisible button beside it.

## 1.7.1

### Fixed: the window would not shrink

Both toolbar rows were horizontal StackPanels sitting in Auto-width Grid
columns. A horizontal StackPanel reports the sum of its children as a hard
minimum, so every control ever added to those rows raised the width the
window could no longer go below - and 1.7.0's Group by sort and Collapse
all pushed it past the point where the resize grips appeared to do
nothing. They are WrapPanels now, so they reflow, and the fixed 230px and
260px on the sheet-set and search boxes are minimums rather than fixed
widths.

### A visible grip

A grip mark in the bottom right corner of the footer, and the corner drag
target is 18px square rather than the 5px the edges used to be. The edges
themselves went from 5px to 7px, which is noticeably easier to catch
without looking like a border.

### Grouping reads as groups

- **Member rows are washed in their group's colour**, full strength on the
  heading and about 13% underneath. Enough to follow a group down the page,
  not enough to fight the text.
- Each heading carries an explicit **[ - ] Collapse** / **[ + ] Expand**
  with the number of sheets in it, beside the caret, so the collapse is
  something you can see rather than something you have to try.

### The window remembers itself

- **Window size and column widths are remembered**, and restored next time.
- Which kind of width matters: a column never touched stays **star sized**
  so it keeps growing with the window, and one that has been **dragged**
  becomes an absolute width, because that is what dragging it meant.
  Saving everything as pixels would quietly stop the table stretching;
  saving everything as stars would throw the drag away.
- Both are saved in the **template** as well as globally. The global one is
  what a plain launch uses, since a size that suits a 4K panel is wrong on
  a laptop; a template's own size wins when it has one.

### Under the bonnet

- The `refs_first` selftest is anchored on the shape of `theme.py` rather
  than on its exact import list, which had silently disarmed it when a
  name was added to that import.

## 1.7.0

### Fixed: the white heading in dark mode

The Custom File Name heading came out as a light grey lozenge on the dark
table. The cause is worth writing down because it is a trap rather than a
typo.

The header elements are built in code and were styled with
`element.Style = window.TryFindResource(key)`. When that lookup comes back
empty the assignment is a **local null** - and a local value on `Style`
stops WPF applying the implicit style as well. So the Button did not fall
back to the themed default; it fell all the way to the OS chrome.

Every code-built element now uses `SetResourceReference` instead, which
resolves when the element is in the tree, never assigns null, and
re-resolves when the palette is swapped. A bench rule checks that every key
asked for by `TryFindResource`, `SetResourceReference` or the `_styled`
helper actually exists in `Theme.xaml`, and its selftest points one at a
key that does not.

### Fixed: the Revit selection arrived unticked

`_apply_preselection` ran before the rows existed, so it ticked nothing.
The sheets came in isolated, which looked right, and none of them were
ticked, which was the whole point. The tick now happens in `_fill_table` on
the first fill, where there are rows to tick.

### Multi-level sorting, like Excel for Revit

- **Click** a heading to sort by it; click again to flip the direction.
- **Shift click** another heading to sort on top of the first, up to six
  levels. Shift clicking one already in the stack flips that level and
  leaves the rest alone.
- Each level has **its own colour** - orange, blue, green, violet, teal,
  amber - shown as an outline round the heading and a badge reading `1`,
  `2`, `3` with the direction arrow. Which column is first and which is
  third is readable without counting.
- The layers are applied **least significant first**, relying on the sort
  being stable. One composite key cannot do it, because then only the
  whole thing could be reversed rather than each level on its own.
- The sort decoration is in the heading's **content**, not in a header
  style: a style per level per direction would be twelve styles and still
  could not colour an arbitrary level.

### Grouping

- **Group by sort** breaks the list into collapsible groups on whatever
  the first sort level is, each heading coloured by that level's colour.
- Click a group heading to collapse or expand it; **Collapse all** does
  the lot and turns into Expand all.
- Heading rows are **appended to the end of the table, never inserted**.
  Half this window addresses rows by position, and inserting a heading
  mid-table shifts every index after it. They are placed purely by their
  sort key: a heading sorts immediately above its own members because its
  key ends `\x00` and theirs `\x01`.
- **Two flags, not one.** `vis` is the filter's answer and `show` is `vis`
  minus anything in a collapsed group. Collapsed onto a single flag,
  reopening a group resurrects the rows the filter had removed.
- Anything walking row positions - tick all, invert, the counts - steps
  over headings. A heading occupies a position but holds no sheet, and a
  tick landing on decoration is a tick lost.
- The group label is written **into the table**, never set on the row
  container. With recycling on, a local value sticks to the container and
  turns up in the middle of the sheets later.
- The sort stack and the grouping state are saved in the template.

## 1.6.0

The Selection grid's columns are now built in code from one ordered list,
fixed and added alike. That sounds like plumbing and it is, but it is what
the next four things all needed: with the six standard columns declared in
the layout and the added ones appended afterwards, a parameter column could
only ever land on the far right and its position could never be saved.

- **An orange outline and an arrow on the column being sorted by.** The
  thickness of that outline is the same whether a column is sorted or not,
  and only its colour changes - growing a border on sort would nudge every
  other heading sideways as you click about. Clicking the same heading
  again flips the direction.
  - The sort is taken over from the DataGrid and cancelled, and the order
    written into a hidden key column instead. A view sorted on a value
    column re-evaluates the moment that value changes and the row you are
    working on slides away from under you.
  - Natural order, so P-9 comes before P-10 rather than after P-100.
- **A new column lands beside the heading you added it from**, not on the
  far right. Somebody adding Discipline next to Sheet Number wants to read
  them together.
- **A search box under every column heading**, Excel style. They narrow
  rather than widen: every box with something in it has to match. Typing
  is debounced 220ms, because re-filtering on each keystroke is visibly
  slow at four hundred sheets. Clicking a box no longer sorts the column -
  the preview click is handled and focus given by hand, which is the only
  way to have both.
  - "Clear every column search" is on the heading right click menu once
    anything is typed.
- **The template remembers the whole column order**, not just which
  parameters were added, plus which column is sorted and which way. A
  template written by 1.5.0 still loads: it holds only parameter names, so
  those go on the end where they used to be rather than being thrown away.
- **A new icon on the Save template button** - a floppy with its shutter
  and label rather than the flat slab, which read as another kind of plus
  next to the button beside it.

### Under the bonnet

- `rule_resources` now also checks XAML built inside Python, which a
  layout scan walks straight past. The tick column's cell template is a
  string in `ps_window` and its `{DynamicResource GridCheckBox}` was
  unchecked until now.

## 1.5.0

- **Parameter columns on the Selection grid.** Right click any column
  heading for **Add column...**, which opens a searchable list of every
  sheet and project parameter with the value each one has on a real sheet -
  so "(empty)" is visible before you add a column of nothing. Pick several
  at once. Right clicking a column you added offers to remove that one, and
  there is a **Back to the standard columns** entry once any are on.
  - The added columns are **searchable**. A column you can see but cannot
    find in is half a feature, so the search box looks in them too.
  - They are **saved in the template**, so a template carries the view as
    well as the settings.
  - Behind the grid each one is a DataTable column called `c0`, `c1` and so
    on rather than the parameter's own name: a binding path cannot carry a
    space, a bracket or a hash, and `BGL_Sheet Discipline` has one of those
    in it.
  - The right click is watched on the whole grid rather than wired to each
    heading, because the headings are rebuilt every time a column is added
    and per-heading wiring would have to be redone every time too.
- **Icons on the three tabs** - a ticked list for Selection, a page for
  Format, a page with an arrow leaving it for Create. Each icon takes its
  colour from the tab, so it dims and brightens with the label rather than
  sitting fully lit on an unselected tab.
- **ContextMenu, MenuItem and Separator are themed.** Like every other
  control that renders a surface, without a template they fall back to the
  OS chrome - a white menu hanging off a dark table.
- The bench check now covers `ps_pickwin` and `ProSheetsPick.xaml`, and
  knows which assemblies `System.Windows.Controls.Primitives`,
  `System.Windows.Data` and `VisualTreeHelper` come from.

### Still to come

Per-column search boxes, multi-level sorting with colour, and collapsible
grouping. Adding columns was the part that stands on its own; the other
three are one piece of work against the house table reference and are next.

## 1.4.0

- **The progress bar now actually moves.** It was there since 1.2.0 and it
  never animated, and the reason is worth writing down: the export runs
  inside an `ExternalEvent`, and Revit raises those **on its own main
  thread, which is the thread this window lives on**. So the bar's value
  was being set correctly and nothing ever rendered, because the message
  pump was sitting inside the export loop. The bar jumped from empty to
  full and the elapsed time only ever showed the total. Every UI update
  during a run is now followed by a Background-priority no-op through the
  dispatcher, which is WPF's DoEvents and lets the pending render pass run.
  Percentage, elapsed, time left and estimated finish all count up live.
- **Open folder lands where the files are**, at the bottom of the subfolder
  tree, and picks the file out in Explorer with `/select` rather than just
  opening a folder. Where a run wrote to several depths it takes the
  deepest.
- **Suppress dialogs already skipped the export confirmation** as of 1.3.0;
  no change needed, but worth saying since it was asked for again.
- **Sheets selected in Revit arrive ticked, and stay ticked.** The isolation
  chip is now a **Show all sheets** tickbox. Tick it to see the whole model
  again; what came in from your selection stays ticked, so you can widen
  the view to add one more sheet without losing the twelve you started
  with. A note beside it says how many came from the selection.
- **Templates can be saved to and loaded from a file**, with two new buttons
  beside the template dropdown. One file holds any number of templates,
  in the same plain key=value text as everything else with an
  `@template=<name>` line before each, so a house standard is diffable and
  hand-editable rather than a blob.
  - Exporting writes every template saved against the project, **plus
    whatever is on screen right now**, which would otherwise be silently
    left out.
  - Importing asks **Merge** or **Replace all** when there is anything to
    clash with. Merging keeps what you have and brings the new ones in
    alongside; a repeated name gains `(1)`, `(2)` and so on, and the status
    line says which were renamed. Names differing only in case count as a
    clash, because on Windows they are.
  - A plain single profile file with no `@template` line loads as one
    template named after the file, so an old profile copied off
    `%APPDATA%` still works.
- **Templates now carry the run preferences too** — suppress dialogs, offer
  to open the folder, debug log. The global setting is the default when no
  template is loaded; the template wins once one is.
- **New bench rule, `template_bundles`**: a bundle round trips with its
  names and values intact including awkward ones with `=` in them, a plain
  profile loads as a single template, and clashing names gain `(1)`, `(2)`
  including when they differ only in case. Seventeen rules now.

### Still to come

Per-parameter columns on the first page, a search box per column,
multi-level sorting with colour, and collapsible grouping are the next
release. They are a rebuild of that grid against the house table reference
rather than an addition to it, and doing them properly is worth more than
doing them alongside everything above.

## 1.3.0

- **Subfolders have their own picker now.** "Add parameter" used to open the
  Custom File Name dialog, which was wrong in a way that is obvious once you
  see it: naming a file and building a folder tree are different jobs. A
  name is one string with prefixes, suffixes and separators; a path is a
  stack of levels. The naming dialog offered four columns that mean nothing
  to a folder and no way to say "and this is a new level down".

  The new window is a searchable list of every sheet and project parameter
  with the value each one has on the first ticked sheet, and two buttons:
  **Add as a folder level** or **Add to this level**. The preview underneath
  resolves against that real sheet, so an empty parameter shows up before
  two hundred files have gone into a folder called `_unset`.
- **Date and time tokens**, at the top of that list: `{Year}`, `{Year Short}`,
  `{Month}`, `{Month Name}`, `{Month Short}`, `{Day}`, `{Day Name}`,
  `{Hour}`, `{Minute}`, `{Second}`, `{Date}`, `{Time}`, `{Date Time}`,
  `{Week}`.

  **strftime codes also work** — `%Y %y %m %b %B %d %a %A %H %I %M %S %p
  %j %W`, with `%h` accepted as an alias for `%H`. They follow strftime
  exactly, which means **`%m` is the month and `%M` is the minute**. That
  trap is the whole reason the named tokens exist and the whole reason the
  picker never offers the percent ones. The bench check has a case for it
  and the selftest breaks it to prove the case works.
- **DWG: "Export views on sheets and links as external references"**, off by
  default, matching Revit's own wording. Off means links and views are bound
  into the one DWG, which is what you wanted as standard. It replaces the
  old "Merge views onto one layer set" tickbox, which was the same setting
  inverted and named after the API rather than after the dialog.
- **"Suppress dialogs while exporting"** on the Create tab. It answers
  Revit's own dialogs and warnings, puts a warning-swallowing failure
  handler on the print transaction, and skips this tool's Export
  confirmation so a run goes straight through. The report at the end still
  appears, and the debug log window still opens when Debug log is ticked.

  Two honest limits. It **cannot** close a print driver's own Save As
  window — that is not Revit's dialog and nothing in the Revit API reaches
  it. And the number of dialogs it answered is reported afterwards, because
  silently answering Revit's questions is not something that should leave
  no trace.

  The handler is hooked once for the session and switched with a flag,
  never unhooked: unsubscribing an IronPython bound method from a .NET
  event does not reliably work, and the handlers would pile up run after
  run. It is turned off in a `finally`, so a run that throws cannot leave
  Revit answering its own dialogs afterwards.

### Under the bonnet

- The date and time code is **plain Python, not `System.DateTime`**. Using
  .NET made the one feature with a `%m`/`%M` trap in it impossible to test
  on the bench, which is exactly backwards.
- `ps_tokenwin` and `ProSheetsTokens.xaml` are in the bench check's module
  and layout lists, so the new window is covered like the rest.
- `ps_namewin.choose_parameter` is gone; the folder picker replaced its only
  caller.

## 1.2.2

Stops the easter egg going off by accident.

- **Only the main window arms it.** Every message window did — the export
  report, the confirmation, the delete prompt — and they all carry the same
  RevoBIM header. Clicking Close three times on a report was enough to start
  the game, which is why it seemed to appear out of nowhere.
- **The logo is passed as the element, never the window.** The old code
  brute-forced the call shape, trying `attach(window, logo)` first and
  falling through on TypeError. Where the extension's signature accepts
  that, the whole window becomes the hit area and three clicks anywhere set
  it off. The signature is now read by reflection — argument count and
  parameter names — and the right shape called directly.
- **No logo means nothing is armed.** It used to fall back to the window,
  which is the same bug by another route. An egg that does not fire is a
  small loss; an egg that fires mid-export is not.
- **New bench rule, `egg_arming`**, holding both halves shut: the egg is
  armed from exactly one place and that place is `ps_window`, `attach_egg`
  never passes the window as the element, and it never falls back to it. Its
  selftest arms the egg from the order dialog, which is the bug that
  shipped. Sixteen rules now.

This only covers how *this tool* arms it. If the game still appears on other
RevoBIM tools, the arming in the shared `startup.py` and `hooks\*.py` is
where to look — those are shared files this delivery deliberately does not
ship, so they need the same treatment by hand.

## 1.2.1

The scan that finds where a driver saved now actually finds it.

- **It looks in the vendors' own folders**, `DiRoots` and `ProSheets`
  alongside `PDF24`, under `%APPDATA%`, `%LOCALAPPDATA%` and `%ProgramData%`.
  ProSheets installs its own PDF24 instance pointed somewhere of its own,
  which is precisely the case the old scan kept missing.
- **A second, deeper pass when the quick one finds nothing.** It walks the
  profile but **only reads a directory's contents when that directory's own
  timestamp is recent** — creating a file updates the timestamp of the
  folder holding it and of no other, so a PDF six levels down is found
  without listing every folder on the machine. Capped at 5000 directories,
  six levels and four seconds, because a diagnostic that hangs is worse than
  one that gives up.
- **The window is now the run's own duration plus a margin**, not a flat few
  minutes. A PDF saved before the export started is not evidence of
  anything, and offering it as the driver's folder would be worse than
  offering nothing.
- **When nothing is found anywhere, it says so plainly** rather than
  repeating generic advice: the driver is most likely sitting on a prompt,
  or sending the job somewhere unusual.
- The debug log is written again after the scan, so what the scan saw is in
  the file rather than only on screen.

Note that the remembered "Driver saves to" folder lives in `%APPDATA%` on
each machine, so a new computer starts without it. That is deliberate — the
folder differs per machine — but it does mean the first driver run on a new
machine is expected to fail once and be picked up by the scan.

## 1.2.0

Live progress, the paper size on the Create tab, and a fix for the staging
folder going missing when the printer changed.

- **"Driver saves to" is now remembered per printer**, not per template.
  Where a driver saves is a fact about the driver, not about the job.
  Keeping it in the template meant switching from PDF24 to another driver
  silently carried the wrong folder over — or, as happened, none at all, and
  the run then failed for a reason that looked like nothing. The box now
  follows the Printer dropdown, and **Use that folder** on a failed run
  sticks for that printer from then on.
- **The progress bar now shows the live percentage, elapsed time, estimated
  time remaining and the clock time it should finish at.** The estimate is
  the mean of what has actually happened so far rather than a per-sheet
  guess, since sheets vary wildly, and it says nothing at all until one file
  has finished — an estimate from a sample of none is a fiction.
- **A driver run now stops after the first sheet produces no file.** It used
  to grind through the whole list at ten seconds a sheet to reach the same
  conclusion; three sheets cost half a minute and two hundred would cost
  half an hour. The report says how many were skipped and why.
- **The Create tab list now has a Size column**, so the paper each sheet is
  going out on is visible in the same place as its file name and folder.

## 1.1.0

Paper size is now worked out from the sheet's own extents, with orientation.

- **The size comes from the title block's width and height first, not its
  name.** A title block called "A1" that has been stretched is an A0 print,
  and the name would have lied about it. The order is now: a nominated
  parameter, then the extents matched to a standard size, then the extents
  fitted up, then an A-size in the type name, then the bare millimetres.
- **Orientation always comes from the extents.** A0, A1, A2, A3 and A4 are
  all recognised in both landscape and portrait, and the Size column now
  reads "A1 landscape" rather than "A1".
- **A sheet that is not a standard size is fitted up to the smallest
  standard size that contains it**, and labelled "(fitted)" so it is visible
  rather than silently rounded. The `PS_420x387` title block, for instance,
  now comes out as A2 portrait (fitted) instead of being passed to the
  driver as a paper name it has never heard of. Sizing down would clip the
  drawing and defaulting to A0 would waste the page, so neither is a
  kindness.
- Tolerance is 8mm, because title blocks are routinely drawn a millimetre or
  two under so the border does not sit on the paper edge.
- **`{Sheet Size}` in a file name is still the bare size** — "A1", not
  "A1 landscape". A file name that suddenly gained " landscape" because the
  column got chattier would be a nasty surprise on a re-issue. There is a
  separate **`{Sheet Orientation}`** token for anyone who wants it.
- The debug log now says where each sheet's size came from and whether it
  was fitted.
- **New bench rule, `paper_sizing`**, with a table of cases: every A-size in
  both orientations, a title block drawn two millimetres under, four
  non-standard sheets that must fit up correctly, a sheet bigger than A0
  that must give no answer rather than guessing, and the requirement that a
  fitted size says so. Fifteen rules now, all proved by breaking them.

### Also

- **A warning when the staging folder is one you actually use.** Collecting
  works by taking whatever new PDF appears during a run, so pointing it at
  the Desktop means a PDF saved there by anything else gets renamed and
  filed with the sheets. Said on the Format tab and again in the Export
  confirmation.

## 1.0.4

The tool now goes and finds where a driver put the files, instead of asking.

- **The debug log opens in its own window when "Debug log" is ticked**, with
  Copy detail on it. A log is only useful if it can be got out of the
  machine, and selecting it out of a report pane that is already holding the
  results is fiddly.
- **When a driver takes the job and nothing lands, the tool looks for it.**
  It scans the folders a PDF driver plausibly writes to — Desktop,
  Documents, Downloads, their OneDrive equivalents, `%TEMP%`, and PDF24's
  own folders under `%APPDATA%` and `%LOCALAPPDATA%` — one level deep and
  capped at 220 directories, for PDFs written in the last four minutes. The
  report lists what it found.
- Where all of those sit in **one** folder, that folder is named in the
  message and an **Use that folder** button fills in "Driver saves to" for
  you. Where they are spread over several, it lists them and says nothing
  further, because there is no honest single answer to give.

## 1.0.3

Makes drivers like PDF24 actually work, and stops the debug log depending on
somebody having remembered to ask for it.

- **New "Driver saves to" folder on the Format tab**, next to the printer.
  PDF24's printer port is a named pipe into the PDF24 service rather than a
  file port, so Revit's print-to-file redirect cannot reach it — the job goes
  down the pipe whatever path Revit sets, and no Revit-side setting changes
  that. With this folder set, the tool takes a snapshot of it, prints one
  sheet, waits for a PDF that was not there before, and moves it to the name
  the naming rules asked for. The driver names the file; the tool renames it.
  Matched on "was not there before" rather than on name, because the whole
  reason the route exists is that the driver's name is unpredictable.
- A file still growing does not count as arrived — a driver writes
  asynchronously, and half a PDF moved and reported as a success is worse
  than none. The move falls back to copy-and-delete when the staging folder
  is on another drive, which `os.rename` will not cross.
- Left empty, nothing changes: drivers that do take the path Revit gives them
  behave exactly as before.
- The report now says which of the two situations you are in — the driver
  never took the path, or it took the job and put nothing in the staging
  folder, which means it is still asking where to save.
- The Export confirmation says the same thing before the run.
- **The debug log is now always written**, to
  `%APPDATA%\RevoBIM\logs\pro_sheets_exporter_debug.txt`. It is a few
  kilobytes, overwritten each run, and a diagnostic that only exists when
  somebody remembered to tick a box is not there on the run that actually
  went wrong. The **Debug log** tickbox now decides whether the report shows
  the log inline, not whether it is kept.

## 1.0.2

Report window fixes, a debug log, and an offer to open the folder.

- **The report's detail pane now wraps.** It scrolled horizontally so that
  file paths stayed on one line, and the cost was that the only sentence
  that mattered — the reason a sheet did not export — ran off the right hand
  edge behind a scrollbar nobody drags. A wrapped path is untidy; an
  unreadable reason is a broken report.
- The failure reason now sits on its own line under the sheet it belongs to,
  rather than trailing off the end of it.
- An empty **Written:** heading with nothing under it is no longer shown — it
  read as a bug in the report rather than as an export that wrote nothing.
- The line under the headline now says what to do about it. Where a print
  driver took the job and nothing arrived, it names the driver, explains
  that Revit's print-to-file redirect only works on drivers that honour it,
  and points at the built-in exporter to rule the driver out.
- **The Export confirmation warns before the run**, not after it, when a
  print driver is selected: a driver set to ask where to save will prompt
  once per sheet and nothing will land. Finding that out on sheet one is
  cheaper than finding it out at the end of a 200 sheet issue.
- **New "Debug log" tickbox** on the Create tab. On, a run records what was
  actually asked of Revit and of the driver, in order — driver selected,
  paper sizes offered, paper matched per sheet, whether `PrintToFileName`
  was accepted, whether `SubmitPrint` threw, and whether anything arrived.
  Written to `%APPDATA%\RevoBIM\logs\pro_sheets_exporter_debug.txt` and named
  at the bottom of the report. It is the only way to tell "the driver
  refused" from "the driver saved it somewhere else", which look identical
  from outside.
- **New "Offer to open the folder afterwards" tickbox**, on by default. With
  it on, **Open folder** is the main button on the report and answering is
  one click; with it off, Close is the main button and the folder is still
  reachable beside it. Where more than one folder was written to, opening
  the first says so.
- Both tickboxes are global settings rather than part of a template — they
  are about how you like to work, not about the job.

## 1.0.1

Fixes the tool failing to open with **"No module named Data"**.

`System.Data` is its own assembly, separate from `System`, and `ps_refs` did
not reference it. Under IronPython a namespace is invisible until
`clr.AddReference` has been called for the assembly holding it, so
`from System.Data import DataTable` in `ps_window` threw at module load and
the staged loader reported it at the "loading the tool" stage.

- `ps_refs` now references `System.Data`, and `mscorlib` for good measure.
- **New bench rule, `assemblies_referenced`.** It maps every `System.*` and
  `Autodesk.*` import in the tool back to the assembly that provides it and
  fails when `ps_refs` does not ask for that assembly. The stub API could
  never catch this, because under CPython a namespace either resolves or it
  does not — there is no assembly to reference. Its selftest removes
  `System.Data` from `ps_refs` to prove it fires, which is this exact bug.

Fourteen rules now, all of them proved by breaking them.

## 1.0.0

First release.

- Three tabs: **Selection**, **Format**, **Create**, with Back and Next in
  the footer.
- **Selection** lists every sheet (or every printable view) with its number,
  name, current revision, paper size and the file name it will be given.
  Filter by a saved Revit View/Sheet Set, by keyword, or to sheets on the
  sheet list; tick all, none or invert.
- **Sheets selected in Revit before the tool opens arrive isolated**, with an
  orange chip in the toolbar saying so and clearing it in one click. Selecting
  something that sits *on* a sheet isolates to that sheet.
- **Custom File Name** dialog, opened from the column heading or either
  button: parameters on the left, the name being built on the right, pushed
  across with the arrows, with per-row prefix, suffix and separator and
  reorder buttons. Two preview lines — the shape of the name, and what it
  actually comes out as on the first ticked sheet.
- **Format** covers PDF and DWG. PDF carries paper placement, offsets, zoom,
  hidden line processing, raster quality, colour depth, the six visibility
  options, separate or combined files, and a printer dropdown listing Revit's
  own PDF exporter alongside every installed driver. DWG uses the export
  setups saved in the model.
- **Create** builds the output folder from a root plus `{Parameter}` tokens,
  shows the resulting path for every sheet before anything is written, and
  warns where two sheets would produce the same file name.
- **Templates** saved per project from the top right, holding the whole
  configuration: what is ticked, the formats, the naming rules, the folder
  tokens and every PDF and DWG option.
- Dark and light palettes, following Revit's own canvas theme on first run
  and switchable from the header chip.
- Modeless and owned to Revit's main window, so Revit stays fully usable.
- `import_check.py` ships beside the tool with thirteen rules, and a
  `--selftest` that breaks each one in turn to prove it fires.

### Known limits

- DGN, DWF, NWC, IFC and IMG appear on the Format tab but are not wired up.
- A combined PDF is only written through Revit's own exporter. Asked for
  through a printer driver, the sheets come out as separate files and the
  report says so.
- Printer export refuses a sheet whose paper size the driver does not offer,
  rather than printing it at the wrong scale.
- Views mode exports views, but paper size is a sheet idea, so Keep Paper
  Size has nothing to work from there.
- Revision-aware naming is available as a parameter, but there is no "skip
  sheets whose revision has not changed" option yet.
