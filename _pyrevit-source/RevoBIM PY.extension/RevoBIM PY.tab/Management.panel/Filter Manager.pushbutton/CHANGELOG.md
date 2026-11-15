# Filter Manager - changelog

(Renamed from Filter Pusher at v2.0.0. The pusher is now a tab inside it.)

## v3.31.0

**Dark theme matched to Revit's own.** The dark palette is now Revit's
dark theme (2024+) rather than neutral greys: the slate blue-greys of its
Project Browser, sampled from a screenshot.

| Role | Revit | Key |
| --- | --- | --- |
| Title / header and footer bars | `#222931` | Head |
| Toolbar strip, window edge, arrows | `#1B1F24` | EdgeWindow, ArrowBg |
| Panels | `#3C4454` | Panel |
| Search boxes, lists, buttons | `#2D3441` | Field, Btn |
| Selected row / table headings | `#323C48` | HeaderRow |
| Tree lines, scrollbar thumbs | `#5A6372` | EdgeStrong, Thumb |
| Text | `#EBF5FF` | Txt (`#E6EEF7`) |
| Muted text | `#9DA4B2` | Dim (lifted to `#ACB4C2`) |
| Close / glyphs | `#ACB2B9` | Glyph, TabIdle |

- The window background sits between Revit's panel and selection tones
  (`#323A47`) so the panels still read as cards on it.
- Muted text, labels and red are a shade lighter than Revit's, because
  Revit's panel is lighter than the old grey and the bench holds text to
  4.5:1 and accents to 3:1 on every surface.
- The house accents (RevoBIM blue, orange, green) are unchanged. The light
  palette is unchanged.
- The default brushes in all six layouts carry the new colours too, so
  there is no flash of the old grey before the palette is applied.

## v3.30.0

**Shrink to the taskbar, on every window.** A new button at the top right
of the main window and of every dialog (Create Filter, Rename, Override
graphics, Colour, and the push results), just before full screen / close.

- Pressing it slides the window down like a drawer - top and height eased
  together over 0.28 s - until only the title bar is left, floating just
  above the taskbar, so the model can be seen.
- The button then turns into a **green up arrow**. Press it, or double
  click the bar, and the window slides back to where it was, at the size
  it was.
- While shrunk the bar can still be dragged anywhere. If it has been moved,
  the window grows up out of where the bar is now, kept on the screen.
  Resizing, full screen, F11 and the top-edge double click are refused
  while shrunk (full screen / F11 expand it instead).
- A dialog takes the main window down with it, so the main window does not
  stay over Revit; their bars stack, one above the other. Expanding or
  closing the dialog brings the main window back.
- Note: Create, Rename, Override and Colour are modal, the same as Revit's
  own dialogs - shrinking one shows the model but Revit still waits for
  that dialog to be closed. The main window is modeless, so shrinking it
  leaves Revit fully usable.
- Windows that size to their content (Override, Colour) go back to doing
  so when expanded.

The pattern is the house one from Pro Sheets Document Register and Hanger
Automation, in a new `fm_drawer.py`: the frames are driven by a 15 ms
DispatcherTimer rather than a Storyboard, the body is collapsed only once
the bar has landed and shown again before the slide back.

- `import_check.py`: 45 rules (+1: every window has the button, a green
  expand arrow, a drawer, `on_shrink`, and a header that drags or expands
  the bar while shrunk), 48/48 breakages caught.
- `bench_logic.py`: 435 checks (+34), driving the drawer against a
  stand-in window with a timer that runs its frames at once: the slide,
  where the bar lands, stacking, owners going down and coming back, closing
  a shrunk dialog, sizing to content, and a dragged bar.

## v3.29.0

**Filters to push fills the panel.**

- The filter name column now takes all the width the setting columns do
  not, so on first open the names read in full wherever they fit, and the
  ticks sit hard against the right. Stretch the window or the column
  splitter and the ticks stay right-justified; only the names grow. (The
  drag grip on the name heading is gone - the panel width is the control
  now, and `pushNameWidth` is no longer saved.)
- The heading follows the list's scrollbar: when the scrollbar shows, the
  heading gives up the same width on its right, so each turned heading
  stays over its column of ticks.
- Setting columns are 30 px (were 26) and the ticks use their own
  `CellCheck` style - a 16 px box with no label gap or margin - so they are
  no longer cropped.

- `import_check.py` rule 41 now also fails if the name column stops filling
  or the ticks fall back to the padded list checkbox. 44 rules, 45
  breakages, all caught.

## v3.28.0

**Target Views: Current view and Show only selected.** Two buttons at the
top of the Target Views tab.

- **Current view** ticks the view that is open in Revit now, selects it and
  scrolls to it. If anything would hide it (its type unticked in the
  dropdown, the search box, Hide greyed) that is cleared first, so it is
  always on screen afterwards. A view controlled by a template is shown
  and selected but not ticked, with the template named on the status line.
  A sheet, schedule or a view in another open project says so instead.
- **Show only selected** narrows the list to the ticked views, still within
  the View type dropdown and the search. The button turns orange while on
  and reads "Showing only selected"; press again to show everything.
  Unticking a view while it is on does not make it vanish under the
  cursor - the list catches up the next time it is redrawn.

- `import_check.py`: 44 rules (+1: both buttons wired, the current view is
  ticked and un-hidden, the list reads the toggle), 44/44 breakages caught.
- `bench_logic.py`: 401 checks.

## v3.27.0

**Target Views: one View type dropdown.** The family and type tick rows are
gone. In their place is a single **View type** dropdown, Excel-filter
style: every type starts ticked, **All** / **None** at the top, and you
untick or tick types by hand. Nothing ticked shows nothing. New types
arrive ticked. A type that shares its name with one in another family
reads `Mechanical Plan  (Ceiling Plan)`.

- Fixes v3.26.0 reading every view type as its family ("Floor Plan" under
  View type). `ElementType.Name` raises under some IronPython builds and the
  next fallback was `FamilyName`. Types are now read through
  `Element.Name.GetValue`, then `ALL_MODEL_TYPE_NAME`.

**Auto theme.** The header chip cycles **Auto -> Dark -> Light**. Auto is
the default and follows Revit: the canvas theme
(`UIThemeManager.CurrentCanvasTheme`), then the UI theme, then Windows'
app setting, then dark. A theme change made in Revit while the window is
open is picked up the next time the window is activated. Saved as
`theme_mode`; the old `theme` key is ignored on purpose, or Auto would
never become the default for anyone who had used the tool before. The
chip is green in Auto.

**Filters to push: a tick per setting.** Column 2 on the Templates sub-tab
is now a table:

- A column per setting, in Revit's V/G order: Enable Filter, Visibility,
  Projection Lines, Projection Patterns, Transparency, Cut Lines, Cut
  Patterns, Halftone. Headings are turned on end; every setting column is
  the same fixed 26 px and does not resize.
- The **filter name column resizes** by dragging the grip at the right of
  its heading. The width is remembered.
- Every setting starts ticked. **Ctrl/Shift-click rows** (click the name),
  then tick or untick any box in one of the selected rows and it applies
  to all of them. The push tick works the same way. Clicking a heading
  flips that setting for the selected rows, or every row if none is
  selected.
- An unticked setting is **not pushed**: an existing filter on the target
  keeps its own value for it; a filter new to the target is left at
  Revit's default. Visibility and Enable are skipped when unticked.
  Overrides are merged group by group from a fresh
  OverrideGraphicSettings, so no invalid colour or id is ever written.
- The log lists, per filter, which settings were left out.

**Overwrite mode.** A dropdown at the top right of column 2 (on both source
sub-tabs): **Overwrite Target All** (default) or **Overwrite Target New
Only**. New Only adds filters the target does not have and leaves any it
already has untouched - reported as KEPT. The footer shows "(new only)"
when it is on.

- `import_check.py`: 43 rules (+3: 41 the ticks reach the write, 42 the
  overwrite mode is honoured, 43 the theme follows Revit), 43/43 breakages
  caught.
- `bench_logic.py`: 397 checks - the view-type dropdown, theme modes, and
  the settings merge against a fake OverrideGraphicSettings.

## v3.26.0

**Target Views.** Column 3 of the Filter Pusher now has two sub-tabs:
**Target View Templates** (as before) and **Target Views**.

- Target Views lists every ordinary view in the project that can carry
  filters - plans, ceiling plans, sections, elevations, 3D, drafting,
  details, legends. Sheets and schedules are left out.
- Across the top, tick **View family** (Floor Plan, Section, 3D View ...)
  and **View type** (Mechanical Plan, Building Section ...) to narrow the
  list. Nothing ticked means no narrowing. Ticking a family cuts the type
  row down to that family's types. Counts sit on every chip. **Clear ticks**
  resets both rows.
- Search matches the view name, family, type and the name of its template.
- A view whose template **controls V/G Filters** is greyed, with the
  template named beside it - Revit will not take filters on that view, so
  push to the template instead. **Hide greyed** drops them from the list.
- The views are read when the tab is first opened, not at start-up, so a
  model with thousands of views opens no slower.
- A push goes to everything ticked on **both** sub-tabs. The footer counts
  templates and views separately.
- If a view picks up a controlling template between ticking and pushing,
  it is reported as **SKIPPED** with the reason rather than as a failure.
  "Take V/G Filters into the template" only ever touches templates.
- Prompt and log now read "targets" and label views as `Name  (Floor Plan)`.

**The easter egg, called properly.** v3.25.0 guessed at entry point names
in `revobim.egg`; none of them exist, so the game was most likely being
opened by the egg's own auto-attach (which finds any TextBlock reading
RevoBIM), not by this tool. If both fire, the egg brings the open game to
the front rather than opening a second one. It now calls the real
`revobim.egg.egg_hook.launch(host_window=..., theme=..., game_key=None)`
by keyword, adds the extension's `lib` to `sys.path` if nothing has, and
passes the current dark/light theme so the game matches the window.

The single life is the egg's own setting (`LIVES = 1` in
`lib\revobim\egg\games\pacman.py`), not something this tool sets.

- `import_check.py`: **rule 39** (the target sub-tabs each have a panel,
  the switch sets both, and the push reads the ticked views) and **rule 40**
  (the egg is launched through `egg_hook.launch` with `host_window=` by
  keyword). Both proved by `--selftest`: 40 rules, 40 breakages caught.
- `bench_logic.py`: 373 checks (+25) - view family/type narrowing, chip
  counts, the template lock, view labels, and the egg's keyword call against
  a fake `egg_hook`.

## v3.25.0

**The easter egg link.** Three slow clicks on the RevoBIM logo in the
header, the same as the rest of the extension.

Slow is the point. An ordinary double click, or an impatient triple, does
not do it: each gap has to fall between 0.35 and 1.6 seconds, so the clicks
have to be deliberate. A gap that is too long starts the count again rather
than losing it, and a double click part way through resets rather than
counting.

The click is **not marked handled**, so dragging the window by the logo
still works - the press is counted on the way past.

The launch reaches into the extension's shared `revobim.egg` package and
tries the usual entry points. It is wrapped end to end: a missing egg, or
one whose entry point has been renamed, says so on the status line rather
than raising. It is decoration, and decoration does not get to break a
filter editor.

`lib` is not in this zip - the egg itself has not changed, so there is
nothing to overwrite.

- `import_check.py` gains **rule 38**, which prefers the extension's own
  `lib\revobim\egg\egg_rule.py` when the tool is checked inside the
  extension, and falls back to an equivalent when it is checked on its own.
  The rule belongs with the egg rather than copied into each tool, so a
  change to how the egg is wired is made once. Proved by breaking it.
- `bench_logic.py` is **348 checks**, fifteen on the click pattern: three
  slow clicks opening it, one and two not, a double click not, a fast triple
  not, the edges either side of the timing window, the count restarting
  after too long a pause, and the counter clearing itself afterwards so the
  next click starts fresh.

## v3.24.0

**The table fills the page.** Every column now has a width it will not go
below and a **share of whatever space is spare**, so the table grows with
the window instead of leaving a gap down the right hand side or having to be
slid left and right.

The Filter Name takes the largest share by some way - three times the
Categories or the Parameter, twice the Value - because a filter name is the
thing worth having room for. The Value column takes the next largest, and
the two of them together mean the last column ends flush with the edge of
the page. The count, the match mode and the remove buttons take no share at
all: they gain nothing from being wider.

| Page | Filter Name | Value |
| --- | --- | --- |
| 1292, the narrowest | 232 | 186 |
| 1600 | 364 | 252 |
| 1900 | 493 | 316 |
| 2540, full screen on a wide display | 767 | 453 |

Narrower than the minimums allow, the minimums win and the table scrolls -
the honest answer rather than squashing every column until nothing can be
read.

The widths are **pushed onto the existing rows rather than rebuilding
them**, so a resize costs almost nothing and does not take the focus out of
whatever cell is being typed in.

- The rule that shares the width out is a plain function,
  `fm_core.distribute_widths`, and `bench_logic.py` is **333 checks** with
  thirteen on it: too narrow keeping the minimums, the columns filling the
  page exactly, no column under its minimum, the shares in proportion, a
  column with no share never growing, and a wider page never making any
  column narrower.
- `import_check.py` gains **rule 37**: every column declares four values,
  and at least one takes a share, or the table cannot fill the page.

## v3.23.3

**The Filter Name and Value cells still cropped their text**, with the line
sitting low in the box - so the box was tall enough, and the line was simply
not in the middle of it.

The vertical padding is now **zero** and the content host is **centred**
inside the box rather than stretched. A single line is then placed in the
middle of the full inner height and cannot end up against an edge, whatever
height the cell is given or the row grows to. Horizontal padding is
unchanged at 7.

Sizes went up again with it: a text box is at least 32, a table cell 34, and
the boxes above the table 34. At 34 the inner height is 32 for a line of
about 17, so there is roughly 7px clear above and below - enough that this
cannot come back from a font or a DPI difference.

- **Rule 36** now also requires the content host to be centred, not only
  that the padding sits on the border.

## v3.23.2

**The Filter Name and Value cells, and their header boxes, were clipping.**
Only the text boxes - the dropdowns beside them were fine - which pointed
straight at the text box template rather than at the heights.

The padding was being applied **twice**. It sat on the border *and* as a
margin on the content host inside it, so a 32px box with 5px of padding had
10px taken off it and then another 10, leaving the text a strip too narrow
to sit in. WPF's own template puts the padding on the border and nothing on
the content host, and so does this one now.

While there: the floor for a text box is 30px, a cell is 32, and the boxes
above the table are 34. Padding is 7,5.

- `import_check.py` gains **rule 36**: a text box's padding goes on its
  border, and its content host carries no margin. Proved by breaking it.
- The height rule's own breakage had gone stale - it named a height that no
  longer appears in the file, so it passed without testing anything. That is
  the third stale breakage in this bench; they are only ever found by
  running the self test, which is the argument for running it every time.

## v3.23.1

**The name and value cells were clipping their text.** My own doing, in
v3.23.0: I centred the text box's content host inside the box *and* gave it
a margin equal to the padding. A centred child sizes to its content and is
then squeezed by its own margin, so in a fixed height box the text loses its
top and bottom. The content host stretches again, and the centring is left
to `VerticalContentAlignment`, which is what it is for.

**Every cell in a table row is now one height.** The text boxes were 28 and
the dropdowns 26, so a row was never quite level. There is a single
`CELL_HEIGHT` of 30 and every cell uses it: the filter name, the categories,
the match mode, the parameter, the operator, the value, the column search
boxes. 30 leaves 20px inside once the padding and border are taken off, for
a line that needs about 16.

- `import_check.py` gains **rule 35**: every method that builds a table cell
  has to use `ui.CELL_HEIGHT`, and the constant has to exist. Proved by
  breaking it - and the first version of the breakage did not fail, because
  the method it targeted used the constant more than once, so it was pointed
  at one that uses it exactly once.

## v3.23.0

**The search boxes are tall enough to read.** A line of Segoe UI needs about
17px, and a box has to hold that plus its padding and its border. The column
search boxes were 22px with 6px of padding, leaving 14px for a line that
needs more, so they clipped their own descenders - which reads as blurred
text rather than as a mistake. Every text box in the tool is now at least
28px, the boxes above the table are 32, and the padding went from 5,3 to 6,4.

**The hints inside them now actually appear.** The boxes have carried a
placeholder since they were built - "name", "category", "0, >2, 1-4" - but
the themed text box had no way to draw it, so none of them ever showed. The
template renders it now, in muted italics, and it disappears as soon as
there is something in the box. So the # box says what it will take without
anyone having to hover it.

Text is also vertically centred in the box rather than sitting against the
top.

- `import_check.py` gains **rule 34**: no text box under 28px, and
  `new_textbox` must set a minimum so a box built in code cannot be made too
  short either. Proved by breaking it.

## v3.22.0

**Fixed the crash on opening the table tab.** `sort_header` did not exist -
my edit that rewrote the heading row took the method next to it with it. The
heading is restored.

- `import_check.py` gains **rule 33**: every `self.method()` a class calls
  must be defined on that class. Only lower case names are checked, since
  the WPF methods a window inherits are PascalCase, and an attribute holding
  a callable counts as defined.

**It found three more of the same thing straight away**, none of which had
been noticed:

- `block_uses` had been swallowed by another block rewrite in this very
  session - the table would have crashed the same way.
- **Ctrl+D** called `duplicate_current`, which does not exist.
- **F2** called `begin_rename`, which does not exist.

Both shortcuts were inside a blanket `try/except` that swallowed the error,
so they had simply done nothing since they were added. They call the right
handlers now, and the blanket catch is gone - the method is guarded, and
swallowing everything is what hid this.

**Speed: the table no longer reads every filter to open.** It was parsing
the rules of every filter in the project before a single row appeared. A
block is now created with only what is cheap - its name and its categories -
and its rules are read the moment it is actually needed: when it is shown,
exported, imported into, or applied. On a project with hundreds of filters
where a dozen are on screen, that is a dozen reads instead of hundreds.

Searching stays cheap with it. The box above the table searches **names and
categories**, neither of which needs the rules. Only the Parameter, Operator
and Value boxes reach for them, and only for as long as one of those boxes
has something in it.

Two follow ons: Apply skips any filter nobody has opened, because it cannot
have been edited, and a palette switch only redraws the blocks that exist.

## v3.21.0

**The headings were sitting off their columns.** WPF centres an element that
has an explicit Width inside a parent that stretches, and the heading row's
container did stretch while the table's did not - so one was centred, the
other left aligned, and the two drifted apart by half the difference. The
heading row is left aligned now, and it also **slides with the table when it
is scrolled sideways**, so the headings stay over their columns at any
width.

**The keyword search covers categories**, and everything else a filter is
made of. A word can be found in the name and another in a category and the
filter still counts as a match, so "tray duct" finds a filter called
BGL_Tray on Duct Accessories. The box above the table searches the lot;
parameters, operators and values are all in scope.

**A search box under every column heading**, the same shape as the Excel
tool: Filter Name, #, Categories, Parameter, Operator and Value each carry
their own keyword box, and they combine with each other and with the box
above the table. The # box takes the same expressions as before - a number,
`>2`, `<=1`, `<>0`, `2-5` - and it has moved out of the top bar into the
column it belongs to.

**The heading row is built once rather than on every keystroke.** Rebuilding
it while filtering would have destroyed the very box being typed into. It is
rebuilt only when the sort or the palette changes; filtering re-fills the
rows alone.

A block's searchable text - its categories, parameters, operators and values
- is worked out once and kept, and dropped whenever the block is redrawn, so
searching does not re-read the model on every key press.

- `import_check.py` gains **rule 32**: a panel holding fixed width content
  has to say how it aligns. Proved by breaking it.
- `bench_logic.py` is **320 checks**, six of them on searching across a row's
  extra text.

## v3.20.0

**A Debug section under the Filter Manager Table, closed by default.** Open
it when something is not behaving and it says what the tool knows about
itself:

- the tool, Revit and Python versions, and the model
- both switches, `MODELESS` and `READ_FILTER_USAGE`
- **how writing is set up**: whether the ExternalEvent was created, whether
  it is running directly instead, what Revit answered the last time work was
  handed over, and how much is still queued
- how many filters, templates and table blocks are loaded, how many are
  showing, and every filter edited but not yet applied - with which cells
- the last fourteen stages recorded during this run

**Copy** puts the lot on the clipboard, **Open the log folder** goes to
`%APPDATA%\RevoBIM`. That is everything I have been asking you to dig out by
hand.

**A # column** after Filter Name, showing how many views and view templates
use each filter. Narrow, right where the count belongs, and its tooltip says
what it counts.

**Both columns sort.** Click Filter Name or # to sort, click again to
reverse; the arrow shows which way. The blocks themselves are sorted rather
than the display, so the order survives searching, isolating and importing.

**And both can be searched.** The keyword box takes several words and every
one has to appear in the name. The new **#** box takes a number, or an
expression: `>2`, `>=2`, `<5`, `<=1`, `<>0`, or a range like `2-5`. A half
typed expression is treated as no filter rather than as "match nothing", so
the table does not blank while you are still typing.

- `bench_logic.py` is **314 checks**, fourteen of them on the # expression:
  every comparison, ranges inclusive at both ends, spaces ignored, a blank
  matching everything, nonsense treated as no filter, and a missing count
  read as zero.

## v3.19.0

**Apply doing nothing - the last thing that was never checked.**
`ExternalEvent.Raise()` returns a status, and the tool was throwing it away.
A refused request queues nothing, raises nothing and writes nothing, so the
button appears dead and there is no error anywhere to find. The status is
now read: if Revit will not take the request the work is run directly
instead, and the tool says what Revit answered rather than losing it.

Apply also leaves breadcrumbs in
`%APPDATA%\RevoBIM\filter_manager_last_run.txt` - started, how many filters
differ, how many are ready to write, and what Revit answered. If it still
does nothing, that file will say where it stopped.

**An import reporting a change nobody made.** A rule's value was being held
in two different conventions in the same field: read from Revit it was a
number in internal units, typed in or read from a sheet it was display text.
So a length of 100mm read back as 0.328084 and compared as different, every
time, on filters nobody had touched. There is one convention now - display
text, set when the table is built and used everywhere - and values are
compared **as numbers where both are numbers**, so 100, 100.0 and 100.000000
are one value rather than three.

**The sheet's colours are stronger and further apart.** The three editable
fills now differ in lightness as well as hue, so they can be told apart
without relying on colour alone, and the locked Id column is a real grey
rather than near-white. Black text clears 8:1 on every one of them.

- `bench_logic.py` is **300 checks**. The colours are measured rather than
  eyeballed: black text on each editable fill, white on the header and on
  the guide's dark fill, every fill distinct, and each pair of editable
  fills differing in lightness. Verified by making two of them the same
  colour.
- One of those checks had the old colours written into it, so changing them
  failed the test instead of testing anything. It reads the fills out of the
  file now - the same mistake as the style counts in v3.17.0, which is twice
  now, so it is worth stating plainly: a check with an expected value copied
  into it goes stale the moment the thing it checks moves.

## v3.18.0

**Manual edits not applying - the cause.** The window's `on_*` methods have
been guarded since v3.4.0, but the table's cells do not use methods. Each
cell wires its events to a **closure** defined inside the method that built
it, and those were not guarded at all. An error in one is swallowed by WPF:
the edit silently does not happen, the filter is never marked as changed, and
Apply then correctly reports there is nothing to write. **Eighteen** handlers
were wired that way - every cell in the table, the inline rename, the colour
swatches, the override buttons. All eighteen are guarded now, so a failure
names itself instead of losing the edit.

Two of them were also asking for trouble: a rule's position was being looked
up with `list.index` on a list of dictionaries, which compares by value and
can raise. The position is known when the cell is built, so it is simply
carried.

**Apply now writes anything that differs from the model**, whether it came
from Excel or was typed in. It no longer trusts the changed flag on its own:
every filter in the table is compared against what Revit actually holds - its
name, its categories, its match mode and each of its rules - and anything
that differs is written. A flag can be missed; a comparison cannot.

For the same reason the Apply button on that tab is **always clickable**.
Pressing it with nothing flagged still asks the question, and says plainly
that nothing differs rather than appearing to do nothing.

Both Apply paths now say "Writing..." on the status line as they start, so
there is feedback before Revit picks the work up.

- `import_check.py` gains **rule 31**: a handler defined inside a method and
  wired to an event must go through `ui.ui_safe`. This is the third bug in
  this tool caused by a silently swallowed handler, and the first two were
  only found because you reported them. Proved by breaking it.
- `bench_logic.py` is **290 checks**, four of them on the guard itself: a
  broken handler does not raise out into WPF, it reports instead, the
  handler keeps its name, and a working handler still returns its value.
  Verified by disabling the guard.

## v3.17.1

**The Filter Manager Table now follows the light palette.** Two separate
causes:

- **The table was never redrawn on a switch.** Everything built in code -
  the table's rows, its header, the staging table, the pattern previews -
  holds the brushes it was built with, so it keeps the old palette until it
  is built again. The XAML follows on its own through `DynamicResource`;
  code-built panels have to be told. `repaint_theme` rebuilds the table now,
  as it already did for the staging table and the category list.
- **Six colours were written into the Python** rather than taken from the
  palette: the staging header's border, the pattern preview backgrounds and
  their default stroke, the swatch border, and the swatch's empty fill.
  Those could never change with the theme whatever was redrawn. All six now
  come from `fm_theme`.

- `import_check.py` gains **rule 29**: no colour written into Python outside
  the palette, whether as a hex string or built from numbers. One line may
  opt out with a trailing `# palette fallback` comment, for the single case
  that has to work when the palette itself cannot be reached.
- And **rule 30**: every panel the window fills itself has to be refilled
  from `repaint_theme`. This is the rule that would have caught the bug
  directly.
- Rule 30 was wrong on its first attempt and passed with the fix deliberately
  removed: it read to the next method beginning `def on_`, which ran past the
  helper `repaint_theme` calls, so the helper's own name appeared in the
  slice. It reads to the next method of any name now.

## v3.17.0

**Apply Table doing nothing - the cause.** Three methods were defined twice
in the same class. Python keeps the last one and says nothing, so an older
definition quietly answered for a newer one, and worse, the **staging
table's `table_header` was answering for the Filter Manager Table's** - two
different tables, same method name. `manager_tab` and
`selected_filters_in_list` were duplicated too. The pusher's header is now
`staging_header`, and the straight duplicates are gone.

- `import_check.py` gains **rule 28**: a class may not define the same
  method twice. Proved by breaking it. This is the sort of thing that only
  shows up as "the button does nothing".

**Apply Table now proves its own work**, the way the rest of the tool does:

- `Transaction.Commit()`'s status is checked rather than assumed.
- Every filter is **read back afterwards** - its name and how many
  categories it ended up with - and anything that did not take is listed by
  name in the report rather than counted as a success.
- **It can no longer exit silently.** The one path that returned without a
  word - dirty filters that produced nothing to write - now says so. A
  button that appears to do nothing is indistinguishable from a broken one.
- The status line says "Writing N filter(s)..." as it starts, so there is
  feedback even before Revit picks the work up.

**A Guide tab in the exported workbook**, dark themed to match the tool.
Each colour is shown as a real swatch in the colour the Filters tab uses,
beside what it means - the Id column and why not to touch it, the filter's
own cells, its categories, its rules - followed by the four steps of the
round trip and what happens to anything that cannot be matched. The sheet
now explains itself.

- `bench_logic.py` is **286 checks**. The style count checks were rewritten
  to **read the declared count out of the file** and compare it with what is
  actually there, rather than having the number written into the test -
  adding two styles for the guide had just made both of them fail for the
  wrong reason. Fonts are checked the same way now. Verified by putting a
  wrong count back.

## v3.16.0

**Export writes what the table is showing.** Narrow the list to six filters
and the sheet holds those six, not the whole project - which is what the
search box was for. The confirmation says so when the list has been
narrowed: "Exported 6 of 60 filter(s)". The Lists tab narrows with it, so the
parameter dropdown offers what those filters actually use. With no filter
applied it exports everything, as before.

**One Excel button instead of two.** It carries the same green mark and a
small caret, and opens a menu with **Export to Excel...** and **Import from
Excel...**. Fewer things in the top bar, and the two actions read as one
feature rather than two.

- `import_check.py` gains **rule 27**: a button whose handler opens
  `sender.ContextMenu` has to declare one. Opening a menu that is not there
  does nothing at all, which looks exactly like a broken button - and this
  tool has already shipped two of those. Proved by breaking it.
- That rule immediately earned its place in a second way: it reported nothing
  on the first run because the layout had not been regenerated yet, so it was
  still inspecting the old two-button version. Worth remembering that a rule
  passing on a stale file is not the same as a rule passing.

## v3.15.0

**The table search is a proper keyword search.** It was already "contains",
but on one word only. Every word now has to be found, in any order, so
"bgl tray" narrows to the rows holding both - which is what makes a search
useful on names built from the same handful of prefixes. Every list in the
tool uses the same rule: filters, categories, view templates, both pusher
lists.

**Speed.** Four things were doing far more work than they needed to.

- **The category table was read from the model on every lookup.** Naming the
  categories of sixty filters meant sixty full reads of
  `doc.Settings.Categories`. It is read once now: 500 lookups went from 500
  reads to 1 on the bench.
- **The host template list counted every template's filters on every
  keystroke.** A `GetFilters` call per template, per key press, on a model
  with hundreds of templates. The counts are worked out once when the
  templates are read.
- **Element sampling was per filter.** It is the most expensive thing the
  tool does, and a project's filters use the same few category sets over and
  over, so one sample is now shared by every filter with the same categories.
  The same goes for the shared parameter list and the widened parameter
  lookup.
- **Sampling built the whole list before taking the first few hundred.**
  `ToElements()` materialises everything; the collector is iterated and
  stopped at the sample size instead. The view scans do the same.

**Every search box is debounced** by 220ms, so a list rebuilds once when the
typing stops rather than five or six times for a word that is not finished.

All of the caches are dropped whenever the model is re-read - on Refresh and
after every write - so nothing can go stale.

- `bench_logic.py` is **284 checks**, with nine on the caching itself:
  the category table read once rather than per lookup, clearing really
  re-reading, a category set keying the same whatever order it arrives in,
  and two filters on the same categories sharing one probe. Verified by
  removing both caches and confirming two checks failed.
- A bug caught while writing those checks: the edit that was supposed to add
  `probe_for` and make the parameter cache write had **silently not applied**
  - its anchor no longer existed, so `common_parameters` was reading a cache
  nothing ever filled. The bench found it immediately by asking for a
  function that was not there.

## v3.14.0

**No dialog after an Excel import.** The counts go on the status line
instead, and anything that needed a decision - a category that does not
exist, a parameter these categories do not share, an id no longer in the
model - is written to a log in `Documents\RevoBIM PY\Logs`, with the status
line saying how many rows and where to find them. Nothing is lost, it just
stops interrupting.

**The window can be made smaller.** The minimum came down from 1480 x 760 to
1280 x 700. The table tab is 1246 wide, so it still fits without scrolling
sideways at the new minimum, and scrolls rather than clipping below it.

**Full screen works on a screen smaller than the window's minimum.** WPF
honours `MinWidth` and `MinHeight` above everything else, so a window whose
minimum is wider than the working area simply cannot go full screen - it
stays too big and hangs off the edge, which is what was happening. The
minimums are now relaxed while full screen and restored on the way out, and
the same applies to the vertical expand.

The window also **fits itself to the screen it opens on**: if it is larger
than the working area, both its size and its minimums come down to match and
it is nudged back inside the edges. That runs from `Loaded`, since the window
has to have a handle before the screen it is on can be identified.

- The sizing rule is a plain function, `fm_core.shrink_to_fit`, so it is
  tested: a window that already fits left alone, one wider than the screen
  brought in, the minimum coming down with the size, the size never ending
  up under the minimum, a floor so a tiny screen still leaves something
  usable, and a zero or nonsense size ignored rather than collapsing the
  window. Nine checks, verified by restoring the old behaviour of shrinking
  the size but not the minimum and confirming four of them failed.

## v3.13.0

**The rules are coloured apart from the filter in the sheet.** Three editable
colours instead of one: **amber** for the filter's own cells (name and match
mode), **blue** for its categories, **green** for its rules. A rule row now
reads as a rule at a glance rather than as more of the filter above it. The
Id column stays grey, because it is the key the import matches on.

**What the import changed is highlighted in the tool.** Every cell the sheet
altered is tinted and outlined, cell by cell rather than a whole filter at a
time - so a single value changed in a single rule shows exactly there.
Editing on screen marks cells the same way, so the highlight always means
"changed and not yet applied". Apply clears it.

**"Only edited filters"** beside the existing unused tick isolates them, and
the count line says how many are waiting: "12 of 60 filters - 3 edited". The
tick enables itself only when there is something to isolate.

**A bug this uncovered.** The table rebuilt its blocks from the model every
time the search box was typed in, which threw away every pending edit. Blocks
are now built once and kept; searching and isolating only decide which of
them are on show. Without that, isolating the changed filters would have
erased the very changes it was isolating.

- `bench_logic.py` is **260 checks**. Two of the new ones were written badly
  and fixed: the fill-count check looked for `count="7"` anywhere in
  styles.xml, which also matches `cellXfs`, so it passed with the fill count
  deliberately wrong. It now matches against the `fills` element itself, and
  there is a matching check for the cell formats. Both verified by breaking
  the counts.

## v3.12.0

**"'contains' is not an operator that suits 'System Type'" - my mistake.**
An element id parameter was only being offered equals, does not equal, has a
value and has no value. Revit offers the text operators on those parameters
as well, because it matches against the **name** of the element the
parameter points at, which is exactly what makes "System Type contains" an
ordinary filter rule. Contains, begins with, ends with and their negations
are now offered and written, on the table tab and in the manager tab alike.

Equals on an element id still needs a real value rather than free text, and
a name typed into the sheet is now looked up among the values elements
actually hold. Where it cannot be matched the message says to use contains
instead, rather than just refusing.

**A parameter that exists in the project is now accepted on import.**
`_Filter Comments 01` was refused because it is not shared by *every* one of
that filter's categories, which is the set Revit's own dialog offers. Import
now looks in three widening circles - shared by all the categories, held by
at least one of them, or a parameter of that name anywhere in the project -
uses the first it finds, and says which circle it came from so an unusual
one is visible rather than silent.

Operators are matched more forgivingly too: the tool's own wording, the
internal key, or the shorthand people actually type (`=`, `<>`, `>=`).

**The sheet is colour coded.**

- **Amber** cells are the ones to edit: name, categories, match, parameter,
  operator, value.
- **Grey** is the Id column, which is the key the import matches on and
  should be left alone.
- A dark green header row, frozen, with thin borders throughout.

**And it says what each cell can be changed to.** A second **Lists** tab
carries every filterable category, every operator in the tool's own wording,
AND / OR, and the parameters the exported filters offer - and the editable
columns are wired to them as **Excel dropdowns**. The validation is
deliberately set to prompt rather than block, so a value the list does not
know about can still be typed.

- `fm_xlsx.py` now writes multiple sheets, per-cell styles and data
  validation.
- `bench_logic.py` is **252 checks**. A regression found while testing: the
  check on validation ordering used `.index`, which raises when the
  substring is missing - so disabling validations killed the whole bench
  instead of failing one check, hiding every check after it. It uses `find`
  now and reports the positions.

## v3.11.0

**Export and Import buttons on the Filter Manager Table tab**, in the house
Excel green.

**The sheet is grouped exactly as the tab is.** One block per filter: the
name and the match mode on its first row, categories filling down their
column one per row, rules filling down theirs. A filter with three categories
and one rule is three rows in Excel as well as three rows on screen.

| Column | |
| --- | --- |
| Id | the Revit element id, and the key on the way back in |
| Filter Name | editable |
| Categories | one per row, by name |
| Elements must match | AND or OR |
| Parameter | editable, by name |
| Operator | editable, the wording the tool uses |
| Value | editable |

**The id is what matches a row back to a filter**, not the name - which is
what makes renaming in Excel work at all. Change a name in column B, import,
and the filter is renamed; if the name were the key there would be nothing
left to match on.

**Import updates the table, not the model.** Everything read in lands as a
pending edit with the block marked dirty, so it goes through the same Apply,
the same validation and the same log as an edit made on screen. Nothing
touches the model until Apply is pressed.

Anything that cannot be matched is reported by row number rather than
skipped: a category name that does not exist, a parameter these categories
do not share, an operator that does not suit the parameter, an id no longer
in the model.

**The reader expects Excel's output, not its own.** Excel rewrites the file
when it saves: inline strings become shared strings, empty cells vanish
entirely rather than being written empty, and rows are numbered rather than
ordered. All three are handled, and all three are on the bench.

- `fm_xlsx.py` writes Office Open XML straight into a zip through
  `System.IO.Compression` - no Excel, no installed package. The XML building
  and parsing are plain string work, so they are tested rather than assumed.
- `bench_logic.py` is now **237 checks**, 31 of them on Excel: column letters
  both ways, escaping and its round trip, a written sheet read back
  unchanged, every workbook part being well formed XML, and a hand written
  sample in Excel's own idiom with shared strings, a missing cell and a
  skipped row. Verified by breaking the ampersand escaping and the
  missing-cell fill and confirming the bench failed both times.

## v3.10.1

**Fixed the table tab failing to open.** `AttributeError: Name` - a filter
rule pointed at an element whose class does not implement `Element.Name`.
The Revit API does not implement it for every class, and where it does not
it raises rather than returning nothing, so reading it off whatever
`doc.GetElement` hands back is never safe.

`ff.element_name` now does that lookup properly: it tries `Name`, falls back
to `FamilyName` and `Title`, then to a static read, then to a caller-supplied
fallback, and finally to the element id. Every place that put a looked-up
element's name on screen goes through it - the table's value cells, the
manager tab's value dropdown, the element id value list, and both logs.

- `import_check.py` gains **rule 26**: never read `.Name` straight off a
  `doc.GetElement` result, whether in one expression or through a variable,
  unless it sits inside a try. It found a second instance immediately, in the
  push verification, where a refused push would have reported the wrong thing
  or raised while listing what had not stuck. Proved by putting the crashing
  line back and confirming the rule named it.
- `element_name` recognises an element id **by shape rather than by type**,
  so a stub, or an id from a second loaded copy of the API, is still treated
  as an id instead of silently coming back "(unnamed)". The bench caught that
  one: its stub ids were not instances of the stub ElementId and the helper
  quietly gave the wrong answer.
- `bench_logic.py` is now **206 checks**, seven of them on `element_name`
  against stand-ins for the awkward classes: a normal element, one whose
  Name raises, one that only has a family name, a missing element, an invalid
  id, and an empty name.

## v3.10.0

**A third tab, Filter Manager Table**, sitting between Filter Manager and
Filter Pusher. Same job as the manager tab, laid out as a table instead of
three columns, so a whole project's filters can be read down the page rather
than clicked through one at a time.

One block per filter, with the columns asked for:

| Column | What it holds |
| --- | --- |
| Filter Name | editable in place |
| Categories | one per row, stacked, each a dropdown with an x to remove |
| Elements must match | AND - all, or OR - any |
| Parameter | one row per rule |
| Operator | the operators that suit the parameter's type |
| Value | a text box, a Yes/No dropdown, or the unit the parameter uses |

A filter with three categories and one rule is three rows deep; one with two
rules and one category is two. Every block ends with **+ category** and
**+ rule**, and each row carries an **x** to take it away again. Nothing is
written until Apply, which lights up with a count of how many filters have
been edited, and reports what it changed afterwards.

**Two things were done to keep it quick on a real project.** The parameter
dropdowns start holding only the parameter the rule already uses and build
the full shared list the first time the list is opened, because that list
costs a scan of the model per filter. And element sampling - which is what
tells the tool whether a parameter is text, a number or a yes/no - happens
per filter on demand, except where a filter already has a numeric rule, since
those are stored in feet and would be unreadable without knowing the unit.

Changing a category clears that filter's cached sample, since the parameters
its categories share have just moved.

- `import_check.py` gains **rule 25**: every tab button has a panel, and
  `select_tab` sets each button and shows or hides each panel. A tab strip
  built from plain buttons has nothing enforcing that a new tab was added to
  the switch, so it would otherwise render blank with the previous tab
  showing underneath. Proved by breaking it.

## v3.9.0

**A tick box above the filter list isolates the ones nothing uses** - the
filters no view or view template references anywhere in the project, which
are the ones worth deleting or tidying up.

- It works alongside the search box rather than replacing it, so a keyword
  still narrows the isolated set.
- The count line under the list always says how many are unused, ticked or
  not: "42 of 60 filters - 18 unused", and "12 of 18 unused filters" while
  isolating.
- If `READ_FILTER_USAGE` has been switched off at the top of `script.py`,
  there are no counts to isolate on, so the tick box disables itself and
  says why rather than silently showing nothing.

The visibility rule is a plain function, `fm_core.row_visible`, so the search
and the tick interacting correctly is tested rather than assumed: nine checks
covering an unused filter showing, a used one hiding, the search narrowing
an isolated set, case insensitivity, a blank search, a missing count and a
missing name. Verified by disabling the unused test and confirming the bench
failed.

## v3.8.1

**Fixed the launch failure.** The ContextMenu, MenuItem and Separator styles
were declared **twice** in the theme. A `ResourceDictionary` refuses a key it
already holds, and the message is exactly "Add value to dictionary of type
'System.Windows.ResourceDictionary' threw an exception", thrown at load
before a single control is built - the same shape as the TabControl failure
in v3.0.0.

The duplication came from my own build step: the block was appended to a
theme file that already carried a copy, and every check I had passed happily
because the XML is perfectly well formed. Only WPF objects to it.

- `import_check.py` gains **rule 24**: a resource key may be declared only
  once per layout, implicit styles included, where the key is the TargetType.
  Verified two ways - by breaking it deliberately, and by restoring the exact
  v3.8.0 duplication and confirming the rule named all three styles.

**Also fixed: "Revit 0" in the error dialogs.** `VersionNumber` lives on the
DB `Application`, reached through the `UIApplication`, not on the
`UIApplication` itself. Every route the old code tried was wrong, so it fell
through to zero every time. Error dialogs will now name the real release.

## v3.8.0

Four ways to manage filter names on the Filter Manager tab.

**Duplicate.** Right click a filter, press the **DUPLICATE** button in the
footer, or Ctrl+D. The copy carries the same categories and the same rules,
takes the original's name with a **(1)** suffix - **(2)** if that is taken,
and an existing "(1)" is replaced rather than stacked - and the tool lands
straight on it with its rules open on the right and the name selected, ready
to change. The button is greyed until a filter is picked.

**Rename in place.** Double click a row, or F2, or right click and Rename.
The row becomes a text box: Enter commits, Escape cancels, clicking away
commits. A name another filter already holds is refused before anything is
written.

**Batch rename.** Select several filters, right click, and *Find and replace
across the selected...* opens a dialog with **Find / Replace with**, **Match
case**, **Prefix** and **Suffix**, and a **live preview** of every name - old
on the left, new on the right, unchanged rows in grey, changes in orange and
anything that cannot be used in red with the reason beside it. Nothing is
written until Rename, and rows with a problem are left alone rather than
failing the batch.

The rename itself runs in **two passes through a parked name**, so swapping
two names round, or shuffling a set along by one, does not fail on a clash
with itself. Every name is read back after it is written, because neither
route to renaming an element reliably raises on failure.

**The list is multi-select**, so Delete now works on the whole selection and
names them in the confirmation.

- `rename_preview` is pure string work, so it is properly tested:
  **12 checks** covering replace, case sensitivity, prefix and suffix order,
  two names colliding with each other, a clash with a filter outside the
  selection, a rule that would empty a name, and that the search text is
  treated literally rather than as a regular expression. That last pair is
  not theoretical - a filter called "Ductwork (1)" searched for "(1)" would
  otherwise match nothing and a search for "." would replace every character.
  Verified by removing the escaping and confirming both failed.
- `bench_logic.py` is now **161 checks**. `import_check.py` covers the new
  rename window; 23 rules, all still catching their own breakage.

## v3.8.0

**Duplicate.** Right click a filter, or press the footer button that lights
up as soon as one is selected. The copy takes the source's categories and
rules and is named `Name (1)`, stepping to `(2)`, `(3)` and so on if that is
taken. The tool then **lands on the copy** with it selected, scrolled into
view, its categories and rules loaded on the right and the cursor in the
name box, ready to be changed.

**Rename in place.** Double click a filter and the row turns into a text
box. Enter commits, Escape abandons, clicking away commits. A name another
filter already holds is refused before anything is written.

**Batch rename**, the same shape as the Panel Template Mngr dialog: find and
replace with a match case switch, a prefix and a suffix, and **every row
previewed before anything is written** - what it is called now, what it would
become, and a note on the ones that cannot go ahead. A row that would end up
empty, clash with a filter that is staying put, or collide with another row
in the selection is flagged on its own line and the Rename button stays off
until it is resolved.

The list is multi-select, so the batch works on whatever is highlighted, and
the rename runs in **two passes through a parked name** - a batch that swaps
two names round, or shuffles a set along by one, clashes with itself in a
single pass.

Every rename is read back afterwards; Revit does not reliably raise when a
rename does not take, so anything refused is reported by name rather than
assumed to have worked.

**A bug the bench found while it was being written.** The clash rules judged
each row as it went, so a row that was not itself being renamed was marked
"unchanged" and skipped the collision test - renaming `XA` to `A` while a
filter called `A` sat in the same selection would have quietly produced two
filters with the same name. All the new names are now worked out first and
judged together. This surfaced because deliberately disabling the
within-selection clash rule failed to break any test, which meant the test
was not really testing it.

- `fm_names.py` holds the naming rules as plain functions, and
  `bench_logic.py` is now **190 checks**, with 30 of them on naming: case
  sensitivity, regex characters treated literally, ordering of replace
  against prefix and suffix, duplicate numbering, parked names, and every
  clash case. Both clash rules were verified by turning them off and
  confirming the bench failed.

## v3.7.0

**Column one on the Filters tab would barely move**, and the reason was
structural rather than cosmetic: the three columns were not siblings. The
filter list and the staging table lived in a grid nested inside the source
half of the pusher, and the target templates lived in the grid outside it, so
a splitter between the first two could never take width from the third. It
had only the few pixels of slack the outer split happened to leave.

**The pusher tab is now one grid with three sibling columns**, with the
Templates and Filters panels swapping in and out of the same cells. That
makes the requested behaviour possible:

- **Dragging column one takes its width from column three.** The middle
  column keeps exactly the width it had, so the settings never squeeze.
- **The middle column is cropped to its own contents** on the Filters tab -
  the staging table's real width plus the arrows and the padding - and is
  pinned there rather than sharing space.
- **Column one opens cropped to the longest filter name**, measured from the
  text itself rather than guessed, clamped between 190 and 560 so one absurd
  name cannot swallow the window. A **Fit** button under the list re-crops it
  on demand, and a width you have dragged is remembered and used instead.
- On the Templates tab, where there is no fixed table to protect, the columns
  behave normally: the first splitter works column one against column two.

The two splitters in the pusher are now `Thumb` controls driven in code
rather than `GridSplitter`s, because a `GridSplitter` can only ever resize
its two immediate neighbours and the whole point here is that column one
trades with column three.

**The drag arithmetic is a plain function**, `fm_core.split_widths`, so it
could be tested properly: the pool the two columns share never changes size,
a drag stops dead at either minimum, two minimums that cannot both fit still
share out what there is, and a zero pool is left alone. Nine checks, verified
by removing the clamp and confirming two of them failed.

Widths are still written back as star values, and what is saved is now the
three pusher columns.

## v3.6.0

**A dark / light chip in the top right of the header**, beside the version
and the window buttons. It switches the whole tool live - no reload, no loss
of what is selected or staged - and the choice is remembered alongside the
column widths.

Getting there meant making every colour a palette key. `fm_theme.py` now
holds **45 keys in two palettes**, the layouts reference them with
`DynamicResource` only, and the palette is written straight onto
`window.Resources`, which sits in front of everything the layout declared.
Elements built in code - the staging table rows, the pattern previews, the
colour swatches - read the same keys and are rebuilt on a switch, since they
carry their colours rather than looking them up.

**The light palette is not the dark one inverted.** The accents are darkened
(`#3D9BE9` to `#1B72BE`, `#E8862D` to `#B96A12`, `#3FA75A` to `#2E8546`)
because the dark palette's accents are chosen to sit on near-black and wash
out on white.

`BasedOn` was left on `StaticResource` throughout: it is a plain CLR
property, not a dependency property, so it cannot take a `DynamicResource`
and a blanket swap would have crashed every style that inherits.

**Muted text was too faint in both palettes.** Checking each text colour
against every surface it sits on turned up `Dim` at 3.7:1 on dark and 3.8:1
on light, under the 4.5:1 readability threshold. Both were adjusted until
the worst pairing in each palette clears it.

- `import_check.py` gains **rule 22** (every palette key exists in both
  palettes and has a brush in the theme) and **rule 23** (no literal colour
  anywhere in a layout, since a hard coded hex cannot follow a switch).
  23 rules, all proved by breaking them.
- `bench_logic.py` is now **140 checks**, adding the palettes: matching keys,
  well formed colours, a contrast ratio for every text colour on every
  surface and every accent against every surface, that the light accents are
  genuinely darker, and the toggle and fallback behaviour. Verified by
  putting the faint grey back and confirming the bench failed.

## v3.5.0

**The three Filter Pusher columns are sized to their content**, not to an
arbitrary share of the window: the project filter list and the target
template list to the width a filter or template name actually needs, and the
staging table to the full width of its own settings columns, so nothing is
cut off or scrolled sideways at the default size.

**Every one of them can be dragged**, and where they are left is remembered.
The Filters sub-tab gained a splitter it did not have - the arrow stack was
sitting between the list and the table with no way to resize either, so the
arrows moved inside the right hand area and the splitter now separates two
star sized columns.

**Widths persist between sessions** in `%APPDATA%\RevoBIM\
filter_manager_layout.txt`, plain `key=value` text. They are saved as **star
values rather than pixels**: both columns either side of a splitter are star
sized, so that is what the splitter writes back, and star widths still share
the window out sensibly whatever size it is opened at. A missing or damaged
file falls back to the defaults key by key, and a value that will not parse
is ignored rather than breaking the load.

Columns remembered: the source and target columns of the pusher, the host
and filter columns of the Templates sub-tab, and the list and table columns
of the Filters sub-tab.

- `import_check.py` gains **rule 21**: both columns either side of a
  `GridSplitter` must be star sized. With one of them absolute the splitter
  writes pixels into it, `Grid` never shrinks an absolute column, and
  widening the panel then shrinking the window pushes the table off the edge
  with no scrollbar to get it back.
- Rule 10 now also covers named `ColumnDefinition` elements, and only treats
  a name as a control when the character after the prefix is upper case -
  otherwise a method like `collect_rules` reads as a control called "col...".
  It flagged exactly that on the first run.
- The settings round trip was tested directly against the real load and save
  code: written, read back, then re-read from a damaged file and a missing
  one.

## v3.4.1

**The override dialog now opens.** `Orientation` was being imported from
`System.Windows`; it lives in `System.Windows.Controls`. That raised
`ImportError: Cannot import name Orientation` the moment
`paint_colour_button` ran, which is why every override button appeared dead.
Fixed in the three places it occurred - `script.py` and twice in `fm_ui.py`.

This is the failure the v3.4.0 handler guard was added to expose, and it did
its job: instead of a control that silently does nothing, the traceback
named the file, the line and the missing name.

- `import_check.py` gains **rule 20**: every .NET name must be imported from
  the namespace the real API puts it in, checked against a table of the WPF
  and .NET types this tool uses. A wrong namespace does not fail until the
  line runs, so it can sit unnoticed in a handler indefinitely. Verified two
  ways - by breaking it deliberately, and by putting the exact shipped
  v3.4.0 line back and confirming the rule reported it.

## v3.4.0

**The override buttons.** I could not reproduce the dead buttons here, so
rather than guess I made the failure visible. An unhandled Python error
inside a WPF handler is swallowed by WPF - the control silently does nothing
and there is no traceback, which is exactly what a button that "isn't
working" looks like. Every handler on every window is now wrapped by
`ui.guard_handlers`, so a failure raises a message naming the handler and
the line. If the buttons still do nothing, that message will say why.

Two things were tightened at the same time, both plausible causes:
- The lazily loaded pattern lists were `@property` objects on a class derived
  from a .NET window type. They are ordinary methods now - a construct with
  no surprises.
- `import_check.py` gains **rule 19**: every window class must be passed to
  `ui.guard_handlers`. It earned its place immediately - the guard block I
  wrote had failed to insert at all because it matched an anchor that no
  longer existed, and the rule caught it before packaging.

**The arrows.** Both are now black with a rounded border: the add arrow is
green, the back arrow red, and they darken on hover.

**Nothing is scrolled sideways any more.** The staging table is laid out to
its own natural width (868px, from the column widths themselves) and the
panel holding it has that as a minimum, so every column from Name through
Halftone is visible without a horizontal scrollbar. The window opens at
1620 x 900 with a 1480 minimum, and the override, colour, create and results
windows were all widened to the width their content actually needs.

## v3.3.0

**Why the push was not working.** In v3.2.0 I moved `ExternalEvent.Create`
out of the window constructor to make opening safer. That was wrong: it left
the event being created from a plain WPF button click, which has no Revit API
context. A raised event that was never created writes nothing and says
nothing, which is exactly what a push that does not work looks like. It is
created in the constructor again, while the command is still running, and a
failure to create it now falls back to running the write directly and says
so rather than going quiet.

Three more things were fixed at the same time, all of the same family:
- **Target templates are re-fetched by id inside the transaction.** Element
  handles captured when the window opened go stale, and a modeless window can
  sit open through any amount of Revit work.
- **`Transaction.Commit()`'s status is checked** rather than assumed.
- **The push is proved.** Every target template is read back afterwards and
  any filter that is not on it is reported by name. The summary counts what
  is actually on the templates, not how many calls Revit accepted.

**Set several filters at once.** Editing a cell on a ticked row now applies
to every ticked row, so a colour, a pattern or a transparency can be set
across a whole selection in one go. Editing a row that is not ticked still
touches only that row. The override dialog says how many filters it is about
to change.

**A proper colour picker**, built to the same shape as Revit's own: 48 basic
colours, a custom colour row, a hue by saturation field with a luminosity
strip beside it, live Hue/Sat/Lum and Red/Green/Blue boxes, a hex box, an
Original/New preview and a **No Override** button. It is used for every
colour in the tool - projection lines, cut lines, and all four pattern
colours. Written from scratch rather than calling the WinForms colour dialog,
which would mean pumping a second message loop inside Revit.

**Patterns are searchable, with a preview.** Both the line pattern list and
the two fill pattern lists have a keyword box, and the preview beside each
one is drawn from the pattern's own definition - the real dash and dot
lengths for a line pattern, the real fill grids at their real angles and
spacings for a fill pattern - in the colour that pattern is set to. The
current selection is always kept in the list even when it does not match the
search, so narrowing cannot silently change it.

**The completion prompt now says what went where**, grouped by target
template with each filter and whether it was added or overwritten, and a
separate section for anything that did not stick. The same grouping goes into
the log file.

- `bench_logic.py` is now **116 checks**, adding the colour maths: RGB to HSL
  and back for nine colours, the 0-239 / 0-240 ranges, clamping, hex parsing
  and the basic colour table. Verified by breaking the hue clamp and
  confirming the bench failed.

## v3.2.0  -  crash investigation

The journal for the crashed session ends on the line that launches the
command and contains nothing after it. Revit died before writing another
byte, which means a **native crash, not a Python error** - there was no
runtime left to raise anything, which is why no traceback appeared. The
journal cannot narrow it further, so this version makes the tool report on
itself and removes the most likely causes.

**Findings**
- Nothing before v3.0.1 ever got past parsing the XAML, so every model read,
  the `ExternalEvent` and the modeless `Show()` were running for the first
  time in v3.1.0.
- The one thing the tool did at start up that touches **every view in the
  model** was counting how many views use each filter. On a large cloud
  workshared model that is by far the most invasive call, and it ran
  `GetFilters()` on views that cannot carry filters at all.
- `fm_clr.py` was re-referencing **RevitAPI** and **RevitAPIUI**. pyRevit has
  already loaded both, and asking again by simple name can bind a second copy
  from a different path - two distinct `Autodesk.Revit.DB` types in one
  process, which surfaces as an access violation rather than an exception.

**Changes**
- **Breadcrumbs.** Each stage is written to
  `%APPDATA%\RevoBIM\filter_manager_last_run.txt` and flushed *before* the
  step is taken. After a crash the last line in that file names the stage
  that caused it. If the previous run did not finish, the footer says where
  it stopped.
- `GetFilters()` is never called on a view that fails
  `AreGraphicsOverridesAllowed()`.
- `Category.GetCategory` is gone from the start up path; category names come
  from the document's own category table in one pass, falling back to
  `LabelUtils`.
- **RevitAPI and RevitAPIUI are no longer re-referenced.**
- The `ExternalEvent` is created on first write rather than when the window
  is built, so opening the tool cannot fail on it.
- Line and fill pattern lists load on first use rather than at start up.
- **Two switches at the top of `script.py`**, one line each:
  - `MODELESS = False` opens the tool as an ordinary modal dialog - no
    modeless window, no persistent engine, no `ExternalEvent`. Writes run
    directly, because a modal window blocks the idle loop a raised
    `ExternalEvent` would need.
  - `READ_FILTER_USAGE = False` skips the per-view count entirely.
- `import_check.py` gains **rule 18**: no `clr.AddReference` of RevitAPI or
  RevitAPIUI. Proved by breaking it. 18 rules, all catching their own
  breakage.

## v3.1.0
- **The Filters source tab is now a staging table.** Tick filters in the
  project list on the left, press the **green arrow** to bring them into the
  middle, and the **back arrow** to take ticked rows out again. A filter
  already staged is greyed in the left list so it cannot be added twice.
- **The table is laid out like Revit's own Filters tab**: Name, Enable
  Filter, Visibility, then Projection/Surface (Lines, Patterns,
  Transparency), Cut (Lines, Patterns) and Halftone, with the two grouped
  headings spanning their columns.
- **Every cell is editable.** The tick boxes and the transparency box edit
  in place; the four Lines and Patterns cells open a themed override dialog
  the way Revit's "Override..." cells do - colour, line weight and line
  pattern for lines; foreground and background pattern and colour for
  patterns - with **Clear overrides** to put a cell back to no override.
- **Cells preview what they hold**: a lines cell draws a sample line in its
  colour at its weight, a patterns cell draws a colour block, and a cell
  with nothing set still reads "Override...".
- **Push sends the staged table**, each filter carrying its own row's
  graphics, to whichever view templates are ticked on the right. The log
  records the graphics assigned per filter as well as where each one went.
- The three table buttons work on ticked rows: copy the first ticked row's
  settings onto the rest, read the ticked rows' graphics out of the host
  template picked on the Templates tab, or reset them.
- The project list's ticks are now harvested **keyed off the element id**
  rather than parsed back out of the label, which carries a "(staged)"
  suffix.

## v3.0.1
- **Fixed the launch crash.** "Initialization of
  'System.Windows.Controls.TabControl' threw an exception" - a retemplated
  `TabControl` will not load under IronPython's `wpf.LoadComponent`, and it
  threw before a single control was built. Both tab strips are now plain
  **Buttons** whose `Tag` drives the styling, switching the visibility of
  sibling panels. Same look, no `TabControl` anywhere.
- **Fixed "Revit 0" in the error dialog.** `__revit__` is injected into the
  running script's own globals, not into `__main__`, so `fm_core` could
  never reach it. `script.py` now hands it over with `set_uiapp`.
- `import_check.py` gains **rule 17**: no `TabControl` or `TabItem` in a
  layout. Proved by breaking it.
- The bench also caught a regression introduced while making this fix: the
  edit that removed the tab styles took the Ghost, CloseBtn, Primary,
  Create, Danger and RowKill button styles with it. Rule 9 (every resource
  key defined) reported all 29 missing references before the tool ever
  reached Revit.

## v3.0.0
- **Modeless.** Revit stays fully usable with the window open. That means
  `__persistentengine__ = True`, every write going out through an
  `ExternalEvent` (a modeless window cannot start a transaction directly),
  the window owned to Revit's main window handle so it cannot slip behind
  Revit and read as a crash, and the window parked in AppDomain storage
  under a **version stamped key** so an upgrade cannot pick up a stale
  handler. Clicking the button again brings the open window forward rather
  than opening a second copy.
- **Refresh** button and **F5**. Because the window is modeless the model
  can move on underneath it; Refresh re-reads filters, templates,
  categories and pattern lists, keeping the current selections.
- **Icons on both sets of tabs** - a funnel for the manager and the project
  filter list, an arrow for the pusher, a template glyph for templates.
- **Draggable splitters** between every column, on both tabs and inside the
  pusher's own tabs. Both columns either side of each splitter are star
  sized, or a widened panel plus a shrunk window pushes the table off the
  edge with no scrollbar to recover it.
- **Full screen**: a button beside close, **F11**, or a double click on the
  header. **Double clicking the very top edge** fills the screen vertically
  only, keeping the width and the left edge. **Dragging while full screen**
  breaks out to the previous size with the pointer kept at the same
  fraction along the header. Escape leaves full screen. All by bounds and
  divided by the DPI scale, never `WindowState.Maximized`.
- **Filter Pusher restructured.** The first two columns are now a
  **Templates** tab (host template plus its filters, as before) alongside a
  new **Filters** tab listing every filter in the project.
- On the Filters tab, tick any filters to push and click a name to set
  **the graphics they will be given in the targets** - the same properties
  Revit's own Visibility/Graphics Filters tab asks for: visible, enable
  filter, halftone, transparency, projection/surface line colour, weight
  and pattern, surface foreground and background pattern and colour, and
  the same four again for cut. **Copy to all ticked** applies one set to
  every ticked filter; **Read from template** lifts a filter's existing
  graphics off the host template picked on the Templates tab.
- Blank or `<no override>` leaves that property to the target template
  rather than writing a default over it.
- Every push logs which graphics were assigned as well as where each filter
  went.
- `import_check.py` is now **16 rules**, adding two for the modeless
  architecture: a window shown with `.Show()` must declare
  `__persistentengine__`, and no `Transaction` may be started outside the
  callable handed to the `ExternalEvent`. Both proved by breaking them.
- `bench_logic.py` is now **92 checks**, adding colour parsing, the
  transparency clamp, pattern visibility following a pattern, and the line
  weight list.

## v2.0.0
- **Renamed to Filter Manager.** pyRevit names a ribbon item after its
  folder, so the folder is now `Filter Manager.pushbutton` - delete the old
  `Filter Pusher.pushbutton` or you get two buttons.
- **Two tabs**, Filter Manager first and selected by default, Filter Pusher
  second. The footer's primary button retitles itself per tab, and Create /
  Delete only appear on the manager tab.
- **Filter Manager tab**: every ParameterFilterElement in the project down
  the left with a keyword search and the number of views using it; the
  filter's categories in the middle with their own search, All / None and an
  "only categories in use" toggle; its rules on the right, laid out the way
  Revit's own dialog does it - parameter, operator, value - and editable.
- **Rules are typed from real elements.** A parameter's storage type decides
  which operators are offered and what the value editor is: a text box, a
  Yes/No dropdown for boolean parameters, or a dropdown of the values
  elements actually hold for ElementId parameters. Built-in parameters have
  no ParameterElement to interrogate, so `ParameterProbe` samples elements
  of the ticked categories and reads the type off a real parameter.
- **Double values are shown in project display units**, converted through
  `UnitUtils` and the document's own `FormatOptions`, and converted back on
  write. Filter rules are stored in internal feet; showing those raw would
  be unusable in a millimetre model.
- **AND / OR** match mode read from and written back as `LogicalAndFilter` /
  `LogicalOrFilter`.
- **Create Filter**: name plus a searchable category tick list, checked for
  a clashing name before it writes. The available rules then follow from the
  categories, since Revit only offers parameters those categories share.
- **Delete Filter** in red, warning how many views or templates use it.
- A rule pointing at a parameter the ticked categories do not share is kept
  and labelled rather than dropped silently.
- Every edit and every push is logged to `Documents\RevoBIM PY\Logs`.
- `import_check.py` with **14 rules**, each proved by deliberately breaking
  it: XAML parses as XML, Python compiles, no f-strings, no print, no
  `script.get_output()`, no bare `.IntegerValue`, no `System.Uri`, `fm_clr`
  imported before any .NET name, every resource key defined, every
  `self.<control>` has an `x:Name`, every XAML handler exists on the owning
  class, no double hyphen in an XML comment, no `x:Static SystemColors` key,
  and no undefined module-level call (via `symtable`).
- `bench_logic.py` with **67 checks** against a stub Revit API, covering the
  operator table, the operator sets per storage type, the evaluator ordering
  used when reading rules back, the negation map, and rule building.

## v1.1.0
- Rebuilt for **Revit 2021 through 2027**.
- `eid_value()` helper everywhere; `ElementId.IntegerValue` never touched
  (removed in Revit 2026). Filter and template identity now compared by
  value rather than by object.
- Icon loaded from bytes via `MemoryStream` + `BitmapCacheOption.OnLoad`,
  never `BitmapImage.UriSource` - `from System import Uri` throws
  `ImportError` on Revit 2025+.
- `open_externally()` uses `ProcessStartInfo` with `UseShellExecute = True`.
  .NET 8 (Revit 2025+) defaults it to False, where `Process.Start` on a
  data file throws. Falls back to `os.startfile`.
- Log written through `io.open(..., encoding='utf-8')` so it behaves the
  same on IronPython 2.7 and IronPython 3 / CPython. CRLF line endings.
- Assemblies requested individually inside try/except.
- WPF controls imported inside the functions that build them, so a missing
  name cannot kill the module at load.
- `SetIsFilterEnabled` / `GetIsFilterEnabled` and
  `GetNonControlledTemplateParameterIds` guarded per call.
- Startup failure message now reports Revit version and Python version
  alongside the traceback.
- `__min_revit_ver__` / `__max_revit_ver__` declared.

## v1.0.4
- Removed the `{x:Static SystemColors.*BrushKey}` resource overrides.
  IronPython's `wpf.LoadComponent` cannot add `SystemResourceKey` entries
  to a `ResourceDictionary` and threw before any control was built.
- Replaced with a keyed `DarkScroll` ScrollViewer template carrying its
  own dark scrollbar corner.

## v1.0.3
- Dropped `script.get_output()`. Running at import time, it opened
  pyRevit's output console - the blank white window.
- Startup wrapped in try/except with a readable message.

## v1.0.2
- Moved out of the Filters panel dropdown onto its own **Management** panel.

## v1.0.1
- Full dark ControlTemplates for ListBox, ListBoxItem, TextBox, CheckBox,
  Button and ScrollBar.
- Window given a `WindowChrome` with `CaptionHeight="0"`.
- Equal-width stretching columns with `MinWidth` / `MinHeight` pinned to
  the design size so buttons cannot be squashed.

## v1.0.0
- First release.
