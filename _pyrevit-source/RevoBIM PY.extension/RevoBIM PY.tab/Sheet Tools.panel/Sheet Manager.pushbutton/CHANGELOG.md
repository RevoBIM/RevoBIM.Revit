# Sheet Manager - changelog

## 1.10.0

**Fixed: Edit on a view template did nothing.** The editor built its columns
with a helper that only took text widths; it was handed numbers, threw before
the window opened, and the error went only to the log. The helper now takes
every kind of width, a bench rule runs it with each, and an editor that fails
to open now says why on screen.

**The view template editor edits every part of the template**, in tabs:

- **Properties** - every parameter the template controls, Value and Include,
  as before, and now:
  - the integer choice lists Revit shows as drop-downs (Show Hidden Lines,
    Far Clipping, Color Scheme Location, Underlay Orientation, Orientation and
    the like) are drop-downs here too, offering the values this project
    already uses for them;
  - **Visual Style** (Model Display's style: Wireframe, Hidden Line, Shaded,
    Consistent Colors, Realistic...);
  - the "Edit..." rows - V/G Overrides Model, Annotation, Filters and View
    Range - open their tab.
- **V/G Model** and **V/G Annotation** - every category: Visible and Halftone.
- **V/G Filters** - each filter on the template: Enabled, Visible, Halftone;
  add any filter in the project, or take one off.
- **View Range** (plan templates) - Top, Cut plane, Bottom and View depth:
  level (Associated Level, Level Above, Level Below, Unlimited) and offset in
  millimetres.

The search box searches whichever tab is open. Changes count up on Apply and
are written together, in one transaction; anything Revit refuses is listed.

**Double-click the top or bottom edge of any window** to stretch it to the
full height of its monitor; double-click again to put it back. (Prompts and
Settings got a top edge to do it on.)

**Sets to create: colour-matched boxes.** The Sheet number, Sheet name and
View name boxes are tinted, and their headings coloured, in their find's
colour - blue, orange and green, the same colours the source list highlights
those finds in.

**Columns as wide as their text.** The set table's columns are measured to
their heading, hint and every value, so nothing is cut off - parameter
headings now show their full name. The view template list's Family and Type
columns size to their longest entry too.

**Sheet names into sheet parameters, with your own delimiter.** Under Text to
find: *Write the sheet names into sheet parameters*, the **delimiter** (default
_; any text, e.g. - ) and the three parameters, picked by keyword search from
the project's sheet parameters, with the first source sheet split out as an
example. The tick is the same one as Preview's *Push sheet names?*; the
parameters and delimiter are the same as Settings > Push sheet names, which
gains a Delimiter box. Change any of them and the others follow. A delimiter
with spaces (" - ") is kept exactly - stored in brackets, since the settings
file trims every value - and each part is trimmed, so a bare "-" never writes
"MECH ". The example splits the new name, after find and replace.

Also from the independent review before release: a filter being taken off a
template has its other ticks dropped rather than written after it is gone;
read-only integer parameters stay read-only; the View Range warning clears
once fixed; Visual Style shows only on templates that have one; only
rule-based filters are offered (Revit will not put a selection filter on a
template); the Family and Type columns are capped so template names keep
their room; a picked cell in the set table is outlined in the text colour, so
it shows on the blue number boxes; and the edge double-click is not undone by
the jitter of the click itself.

Bench: 34 import rules (1 new: the column helper takes every width), 46
deliberate breakages all caught; 463 logic checks.

## 1.9.0

**Source sheets list the views on them.** Under each sheet, one line per
view (up to six, then "+N more"), with what the run will do to it: the view
find's catch bold green in the name; a dependent says a copy of its parent
comes too; a legend says it is left off or placed again as it is. A view that
keeps its name is never marked.

**Legends are left off unless asked for.** A new tick under the source list,
*Include the legends from the original sheets*, off by default. Ticked, the
Legends option (place again / duplicate) applies as before.

**Dependent views always keep their parent.** A dependent on a source sheet
comes across as a dependent of a copy of its parent and is placed where the
old one was - the "A dependent brings its parent" option is gone, because
unticking it copied the dependent as a stand-alone view. The run checks each
new dependent really hangs off the new parent and says if Revit made it
otherwise.

**New sheets and views start with no revisions** - forced, no option.
Revision clouds are deleted from every copied view (with detailing brought
them), and new sheets get no revisions and no clouds. A legend placed again as
it is is the original, so its clouds cannot be touched; the results say so
when one carries any. "Carry the revisions across" is gone.

**Three new ticks for cleaning the copies** (under the source list, off by
default, remembered):

- *Remove text notes and tags from the new views and sheets* - text notes and
  element tags (keynotes included). Room and space tags follow the room
  options.
- *Tag every room, and remove '?' room tags, on the new views* - plan views:
  every placed room on the view's level, this model's and those in loaded
  links, gets a room tag if it has none (inside the crop when the crop is on);
  room tags showing '?' (tagging no room) are deleted.
- *Remove detail lines and filled regions from the new views and sheets* -
  detail lines only; room separation and area boundary lines are left alone.

Only elements a new view owns are touched - never anything on a source view
or a view placed again - and nothing inside a group (counted as "left in
groups"). Each clean-up runs in a sub-transaction of its own, so one Revit
refuses is rolled back alone and never costs the view or sheet; a sheet's
revisions are cleared in a step of their own. A cloud on an issued revision
is taken off by un-issuing that revision for the delete and issuing it again
straight after. Linked rooms are matched to the level on its project
elevation (internal origin), a foot either way. The finish line says what was
taken off.

**View templates: Duplicate..., Rename..., Edit...** for the template picked
(clicked) in the list.

- Duplicate asks for a name (default "<name> Copy") and copies every setting
  and Include tick.
- Rename carries the new name through the sets and the template's preset.
- **Edit** opens a window laid out like Revit's View Templates dialog: the
  name, "Number of views with this template assigned", and Parameter / Value
  / Include for every parameter the template controls. View Scale, Detail
  Level, Discipline, Parts Visibility, phase filter and other element choices,
  yes/no, text and number values are editable; what Revit only edits in its
  own dialog (V/G overrides, View Range, Model Display, and the integer
  choice lists such as Show Hidden Lines) keeps its Include tick and shows its
  value read-only. A value Revit will not set is reported, never counted as
  written; the editor has its own theme chip and never waits more than 30
  seconds on Revit. Search the parameters, Include all / none;
  changed rows go orange, nothing is written until Apply, and a value Revit
  refuses goes red with the reason.
- The list now opens on **Plans** and is **sorted by name**.
- **Add ticked shuts View templates** (and opens Sets to create).

**Saved text to find.** A drop-down over the find boxes: *Save...* keeps the
three finds and Match case under a name; pick one to fill the boxes; Delete
takes one out. Kept in settings for next time.

**Sets to create show a view rename example** under each set's sheet example -
the first view whose name changes, before and after, and how many more.

**Fixed: a blank replacement cell deleted the found text.** A set with a find
in the sheet names (or view names) and a blank cell removed the found text
from every name, though the cell's hint says "blank keeps it". Blank now keeps
the names, in the example under the finds too.

Bench: 33 import rules (3 new: new sheets and views start with no revisions -
each clean-up in its own sub-transaction, limited to what a view owns and to
detail lines; external events made only in the command's context; no local
read before it is set), 44 deliberate breakages all caught; 445 logic checks.
An independent review found eight defects before release - one would have
stopped the Duplicate window refreshing as soon as a set was added - all
fixed, and the new read-before-set rule now guards that whole class.

## 1.8.0

**Sheets selected in Revit filter the table.** Select sheets (in the Project
Browser or anywhere) before opening Sheet Manager and the table shows only
those, already selected so **Duplicate Selected** is ready. A strip under the
toolbar says so: **untick "Only the N selected in Revit"** to show every
sheet, tick it to go back. Pressing the ribbon button again with a new
selection hands it to the open window; pressed with only a wall or a viewport
selected, or the same sheets, it leaves the filter as you left it. Clear filters
leaves it alone, and sheets made by a Duplicate run join it so they stay in
sight.

**Duplicate starts from what you picked.** The rows selected in the table are
ticked as sources and the source list shows only them; untick **Only the N
sheets selected** above the list to see every sheet. Pressing Duplicate again
with other rows picked hands them to the open window.

**Duplicate's build page is restacked** - three groups, one above the other,
each opening and shutting from its heading, with an icon each:

- **Source sheets** (open to start with), with **Text to find beside it on
  the right**, and the Options under the finds.
- **View templates** (shut to start with).
- **Sets to create** (shut to start with; opens by itself when you add
  templates, so the new sets are in sight).

Each heading carries a one-line summary (ticked sheets, templates shown and
ticked, sets x sheets = new sheets), so a shut group still says where it is.
Open groups share the height.

**What a find catches is highlighted in the source list** - bold, in the
find's own colour: the sheet number find in **blue**, the sheet name find in
**orange**, and the view find in **green** on a line under each sheet listing
the views on it that it catches (the first three, then "+N more"). Only views
the run will copy - and so rename - are listed: a legend or schedule placed
again as it is keeps its name, so it is not shown as caught. The labels
over the find boxes carry the same colour keys. It matches exactly what the
find and replace will replace, case rule included.

**Dark is now Revit's own dark theme**, sampled from Revit's Project Browser
(title bar #222933, body #3C4454, fields #2D3441, headings #323C48, Revit's
selection blue #3A7392), with muted text and blue lifted to stay readable.
Group, band and status colours are retuned onto the new greys. Light is
unchanged. **Auto now follows Revit's canvas** (the drawing area) first, then
its ribbon theme.

**Shrink to taskbar on every window** - main, Duplicate, Settings, Edit and
every prompt. The button sits top right before full screen and close; pressed,
the window slides down like a drawer leaving only its header bar floating just
above the taskbar, and the button becomes a green up arrow. Up arrow,
double-click on the bar, Enter, Esc or F11 bring it back; Ctrl+Shift+H works
both ways. Windows go down and come back together (the main window and
whatever it has open), stacking their bars. The bar can be dragged, and
opens upward from where it is left. The button stays live while sheets are
being created. Pressing the ribbon button while the tool is shrunk brings it
back.

Bench: 30 import rules (5 new: every window shrinks, the drawer cannot strand
a window - including one brought back mid-slide - owners brought back first,
shrink stays live during a run, Revit dark palette with canvas first), 39
deliberate breakages all caught; 409 logic checks (highlight spans, selection
filter, drawer maths, palette contrast, canvas theme). An independent review
found five defects before release, all fixed.

## 1.7.0

**Push sheet names? - now a tick box on Duplicate's Preview page.**

- Tick **Push sheet names?** above the preview and each new sheet's name is
  split on `_` and written, in the order it was written, into the three sheet
  parameters set in Settings - `MECHANICAL SERVICES_VENTILATION_LAYOUT` gives
  `MECHANICAL SERVICES`, `VENTILATION` and `LAYOUT`. Extra parts join onto the
  last parameter; missing parts leave it blank.
- While ticked the preview gains a column per parameter, so you see exactly
  what each sheet will get before Create. The line beside the tick shows the
  first sheet split out, and warns in orange if a parameter isn't a sheet
  parameter in this project.
- The tick is remembered between uses and locked while Create runs. It is
  greyed out with a pointer to Settings when no parameters are set.
- The old "Write name parameters" option on the Options page is gone - this
  replaces it.

**Settings > Push sheet names** (was "Sheet name mapping"): three keyword-
searchable drop-downs of the project's sheet parameters, labelled Sheet name
part 1 / 2 / 3. They default to **BGL_Sheet Name 1 / 2 / 3** - a blank mapping
picks these up on first open; a mapping you've already set is left alone.

Where a parameter is also a browser grouping column and the set has a grouping
value for it, the grouping value still wins, and the preview shows that.

## 1.6.0

**Fixed: Settings > Sheet name mapping was wiped every time the tool
opened.** The 1.2.0 migration that clears the old default was keyed to
settings version 2, but the version was never raised from 1 - so instead of
running once it ran on every load. The version is now 2, and the bench saves
and reloads every setting and checks none is lost, and that the version is
never below the highest migration. **Set your sheet name mapping again once**;
it will stick from now on.

**Pick several cells in the table of sets and give them one value.**

- Click a cell to pick it; **Ctrl-click** to add or take out another;
  **Shift-click** for every cell between; **click a column heading** for the
  whole column, Ctrl-click another heading to add it. Picked cells are outlined
  in blue.
- The **fill bar** above the table says what is picked. Type or pick a value
  and press **Apply to picked** (or Enter) to put it in every picked cell.
  **Fill series** steps each picked column down from its top cell - 0013, 0014,
  0015 - keeping the zeros. **Clear** empties them; **Undo** takes back the
  last apply, fill or clear.
- **Ctrl+Enter** in a cell puts that cell's value into every picked cell, as
  in Excel. **Enter** moves down a row in the same column, **Shift+Enter** up.

**View template presets**, in Settings. Pick a template and fill in what it
brings with it - the sheet number, sheet name and view name replacements and
the grouping values. When that template is added to the table of sets, its row
fills in by itself. Presets are kept by template name, so they follow the
template into every project; values for parameters a project does not have are
kept, not lost, when a preset is updated there. The **star on any row** in the
table keeps that row's values as its template's preset, and a star beside a
template in the list shows it has one.

**The main table opens sorted the way it was left** - every sort level and its
direction. A column no longer in the table is dropped from the sort. The
preview in Duplicate remembers its sort the same way.

**Polish in the table of sets**

- Each row has a coloured stripe and a line under it: green with its first
  sheet before and after, orange with what it still needs, red with why its
  sheets would clash.
- The headings say what each replacement replaces - "replaces "0012"" - and
  stay in view while the rows scroll, following them sideways.
- **Copy set** on each row adds another set from the same template with the
  same values, for the same template on another level.
- Double-click a template to add it as a set straight away.
- Counts read "1 sheet", "3 sets" rather than "sheet(s)".

**Text cells fixed**

- A placeholder in a narrow box - "(leave each sheet's own)" - drew past the
  edge of the box, under the dropdown arrow and into the next cell. Every
  placeholder now ends in an ellipsis and every box clips what it holds. Bench
  rule.
- The boxes in a row stretched to the height of the template's two-line label;
  every cell is now the same height and centred.
- Long sheet and template names in the lists were cut through the middle of a
  letter; they now end in an ellipsis, with the full name in the tooltip.
- Text on glyph buttons had no colour of its own and drew black on the dark
  theme.

**Fixed: the Duplicate window saved a stale copy of the settings.** It kept the
settings it was opened with; after a trip to Settings, its next Create saved
that copy back over what had just been applied. It now reads the main window's
settings as they are. Bench rule.

**Found in review and fixed:** the heading drifted when typing past a cell's
width (scroll events bubble up from every text box); Enter in a grouping
cell's dropdown search moved down a row instead of picking; a deleted preset
came back on Apply; closing Settings with the X lost kept presets without
asking; a ctrl-click left the keyboard in a find box; switching back from Revit
could throw away a picked column; the heading stopped short of the rows by a
scroll bar's width; a Settings change did not reach an open Duplicate window.

Three bench rules added, each proved by deliberate breakage - placeholders
stay inside their boxes, the Duplicate window reads live settings, routed-event
handlers check where the event came from - plus a logic check that every
setting survives a save and reload. 25 rules, 28 breakages, all caught.
`bench_logic.py` is up to 358 checks.

## 1.5.0

**Duplicate is rebuilt around view templates.** The old Sheets / Views /
Preview dialog is gone; in its place is one window with two tabs.

**1 - Sheets and views**, three columns side by side:

- **Source sheets** - every sheet in the table, searchable, with the rows
  picked in the main window ticked to start with. Tick more or fewer here.
- **Text to find** - one box each for the sheet numbers, the sheet names and
  the view names, with match case, and a worked example of the first sheet run
  through the first set as you type. The view and sheet options are under
  **Options**.
- **View templates** - every template in the project, filtered by **Family**
  (Plans, Sections, 3D Views...) and **Type** (Floor Plan, Ceiling Plan...),
  with a keyword search, and a count of how many views on the ticked sheets
  each template would go on. Tick some and press **Add ticked**.
- **Sets to create** - each template pushed across is one row, and each row is
  one *set*: a full copy of every source sheet and its views, with that
  template on the duplicated views of its type. On each row type what the found
  sheet number, sheet name and view name text is replaced with, and the value
  for each grouping parameter - Stage, Discipline, Series and WIP Tag by
  default, the four set in Settings, each with a picker of the values the
  project already uses. A blank grouping cell leaves each sheet the value it
  already has. **Next lights up green** the moment every set has what it needs
  and nothing would clash; until then the footer says what is missing.

**2 - Preview and create** - every sheet that will be made, in one table:
number, name, the views on it, the template, each grouping value, the sheet it
came from and its status. Sorted and **grouped by Sheet Series** with each
group banded in its own colour like Excel for Revit; click any heading to sort
by it instead, and the grouping follows. **Create** runs it: each row **goes
green** as its sheet lands, and a progress bar shows the percentage done and
how many are left.

- **The PacMan question is gone.**
- The window is modeless and stays open while Revit works - a modal dialog
  keeps Revit busy and an external event only runs when Revit is idle, so the
  rows could not go green any other way. It cannot be closed mid-run.
- **A rollback takes the green back.** A sheet made inside a set that Revit
  then rolls back does not exist, so its row is repainted red and it is taken
  out of the results, rather than left green and offered to be opened.
- **Each job writes to the project it was set up in.** Both windows are
  modeless and outlive a switch of project; the element ids a job carries
  belong to one document, and used against another they name the wrong sheets.
  A job whose project has since been closed is refused. Edits included.
- **A job Revit accepts but never starts is withdrawn after 20 seconds**, so
  a dialog or command open in Revit cannot leave both windows busy for ever.
- The main window will not close while Revit is part way through a job.
- The main window's Duplicate button is always available; sources are picked
  in the new window.

**Fixed: group headings never showed `[ + ] Expand` / `[ - ] Collapse`.**
The 1.4.1 change that told each cell which column it is in matched nothing and
nothing said so, so every column of a heading repeated the label. Fixed, with
a bench rule; and every edit to the code now asserts its target exists.

**Group bands, like Excel for Revit.** Each top-level group gets its own
colour, its heading strong and its rows a soft tint of the same, in the main
table and the preview.

Three bench rules added, each proved by deliberate breakage: every
`module.name` one module reaches for exists in that module; the cell converter
is told its column; every job writes to its own document. 23 breakages, 23
caught. `bench_logic.py` is up to 301 checks, including the whole
template-to-sheets build: one set per template, clashes across sets, view
names unique across sets, the parent copied again in each set, readiness, and
the one-pass template count agreeing with the per-template one.

## 1.4.2

**Fixed: the window opened, drew its rows, and answered nothing.** Selection,
Duplicate, collapse and expand, the grouping dropdowns, the keyboard and
therefore the debug report were all dead at once, which is one cause and not
five: `_wire` was a single chain of handler hook-ups, so the first line in it
that threw left everything after it unhooked, with no traceback anywhere
because the window itself had opened fine.

- **The wiring goes in ordered, individually guarded steps**, the things the
  tool cannot be used without first: the sheet list, the keyboard, the toolbar,
  the footer, grouping, the search box, sorting, then the decorative parts.
  Anything that fails is named in the status bar and written to
  `%APPDATA%\RevoBIM\sheet_manager_wiring.txt` rather than taking the rest
  with it. A bench rule now refuses a bare hook-up inside `_wire`.
- **A Diagnostics button**, wired first and on its own, is the one thing that
  works when nothing else does: the version, the Revit build, which assemblies
  loaded, what did not wire up, the columns, sorts, grouping, filters,
  selection and pending edits, and the last run's trace - to a file and the
  clipboard.

**Fixed: back to whole-row selection.** 1.4.0 turned the grid over to cell
selection so the clipboard had cells to work on, and that is what stopped rows
being picked, headings behaving and Duplicate lighting up. Rows are selected
again; the cell commands work on the selected rows crossed with the column the
cursor is in.

**Fixed: collapse and expand.** The heading click is taken on the **press**,
not the release - the press is what selects a row, so on release the row had
already been taken and the click counted. And `hit_row` now falls back to the
logical parent: `VisualTreeHelper` only walks visuals, and the source of a
click can be a content element that is not one, in which case the walk ended at
the first non-visual and reported no row at all.

**The Export button carries an Excel badge** - a green rounded square with an X
in it, drawn from a `Border` and a `TextBlock` rather than set in a symbol
font, so it cannot render as an empty box.

## 1.4.1

**Fixed: sheets could not be selected and Duplicate stayed grey.** 1.4.0 turned
the grid over to cell selection so the clipboard and fill had cells to work on,
and `SelectedItems` is empty in that mode - only `SelectedCells` is filled.
`selected_sheets` read the first and not the second, so however many rows were
highlighted the tool believed nothing was picked. Both are read now, the result
de-duplicated and put back into table order.

**Group headings read like the ones in Excel for Revit.** A band across the
whole row with **its own colour per level**, so a three-deep grouping reads as
three depths rather than three identical stripes; the arrow and the label in
the first column; and **`[ + ] Expand` / `[ − ] Collapse` with the count** in
the second, because a heading that does not say it can be opened does not look
as though it can. The chip reads **Grouped** and names the columns it is
grouping by.

- **A heading is never part of the selection.** It holds no element, so
  clicking one toggles it and clears the cell rather than leaving a heading
  counted as a picked sheet. The handler that does it carries a re-entry flag,
  since changing the selection inside a `SelectionChanged` handler raises the
  event again.

## 1.4.0

Brought up to the RevoBIM table reference.

**The view is a snapshot.** Filtering, sorting and grouping are taken once
against a held decision and bound to that, never to the values themselves - so
nothing moves or disappears under the cursor while it is being edited. The
status line says how many rows are sitting out of order or outside the filter,
so a stale view is never silent, and **F5 re-takes the filter, the sort and the
grouping together** without touching the pending edits. Refresh still re-reads
the model.

**Cell colours, with the legend in the footer named in full**: strong red where
Revit refused the write on the last Apply, green for an edit staged and not yet
written, teal for one that came from an import, amber for the source of the
clipboard, light red for a cell that is not editable. A refusal outranks
everything, because it has to stay readable, and a copy mark never covers a
pending edit.

**Six sort levels, not three**, each with its own colour round the heading -
orange, blue, green, violet, teal, amber - and its place and arrow in the
title: `1▲`, `2▼`, `3▲`.

**A column's tick list shows what the other filters allow.** Its own filter is
excluded from its own list, the way Excel does it: otherwise the values it is
hiding would not be there to tick back on, and a filter could only ever be
narrowed. Each value carries its count.

**Clipboard, fill and undo.**

- Ctrl+C / Ctrl+X / Ctrl+V, tab separated so it lands in Excel. Copy marks its
  source amber until it is pasted or the selection changes.
- Ctrl+D fill down, Ctrl+E fill series. The whole rule: no number in the seed
  and it is copied; a number and it is stepped; several cells with an even gap
  and that gap is kept; several with no series and they repeat as a block.
- Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z, in **batches**: one operation, however many
  cells, is one undo step.
- Delete clears the selected cells, F2 edits the current one.
- **The keyboard belongs to whatever has focus** - inside a search box or the
  cell editor, Ctrl+C and Delete are the text box's, not the grid's.

**Duplicates.** Right-click a column heading for Highlight duplicates - each
clashing set gets its own colour - Isolate duplicates, which reuses the
column's own tick filter so it composes with everything else, and **Create
unique sequence**, which renumbers the selection to values nothing else uses,
counting on the rightmost number and keeping the padding. Blanks are not
duplicates.

**Column widths are measured once after the first render and frozen in
pixels**, between a floor and a ceiling. Leaving columns on Auto looks like
autofit and is not: it re-measures as rows are realised, so widths shift under
the reader, and it has no ceiling, so one long value pushes the rest off the
edge. **Fit columns** re-measures on demand.

**A cell that cannot be written refuses the edit before Apply**, not after -
in the grid, in the bulk dialog and on import.

Three bench rules added, each proved by deliberate breakage: **no method
defined twice**, **no non-ASCII outside a `u''` literal**, and the
DynamicResource key check now covers `Theme.xaml` against itself. 19 breakages,
19 caught. `bench_logic.py` is up to **261 checks**, including every fill and
series rule from the reference - the hyphen that is not a minus sign, the
padding that must not be invented, and the rightmost number being the counter.

## 1.3.0

**The table is editable.** Everything Excel for Revit does for a schedule,
done for the sheet list, and on the same rule: **nothing is written until
Apply**.

- **Double-click a cell** to edit it in place. Enter keeps it, Escape drops
  it. A cell with an edit waiting goes **orange** and shows the pending value.
- **Edit...** opens a dialog with three tabs - **Find and replace**, **Prefix
  and suffix**, **Fill down** - over the selected rows or every row shown, in
  the ticked columns, with a preview of every cell it would change before it
  is added. A second find and replace works on the pending value, the way it
  would in Excel.
- **Apply** writes every pending edit in one transaction, borrowed first,
  with the failure preprocessor recording what Revit says, and **reads every
  value back**. After a partial write only the cells the model does not
  already show stay pending. A sheet number that would collide, or would be
  blank, is refused before anything is written.
- **Discard edits** throws the pending ones away, after asking.
- **Export xlsx** writes the table as shown, pending edits included, to a real
  .xlsx (or .csv) of your choosing - straight out as Office Open XML, no Excel
  needed. Header bold, first row frozen, autofilter on, columns sized.
- **Import xlsx** reads that file (or any spreadsheet with a Sheet Number
  column) back in, matched on Sheet Number in any order, and turns the
  differences into pending edits. Columns the table does not carry are
  ignored, numbers matching nothing are reported, and the number column itself
  is never written from the file.

**Fixed: sorting only worked when the click landed on the letters of the
title.** Two causes. The header template did not stretch its content, so the
clickable part was only as wide as the text; and a `DataGridColumnHeader` is a
`ButtonBase` that captures the mouse on press, so a release never reaches a
child at all. Sorting now goes through the grid's own `Sorting` event, which
fires for a click anywhere in the header cell, and is marked handled so the
grid does not also sort through a CollectionView that knows nothing about
group rows.

- **The colour bar runs down the whole column.** The sorted column's cells
  carry the sort colour on both edges, the header is outlined in it and its
  title is coloured, and the arrow says which way: blue, then orange, then
  green for a second and third level added with shift.
- **Column filters apply as you tick.** Every tick re-filters the rows at
  once, each value shows how many sheets carry it, and the caret turns orange
  with a dot while a filter is on. Filtering never rebuilds the columns, which
  is what used to close the popup under the mouse.

## 1.2.3

**Fixed: the grid stretch on a dependent was refused, so it kept the parent's
model extent.** The debug report from 1.2.2 showed every write on a dependent
refused with "The curve is unbound or not coincident with the original one of
the datum plane". `SetCurveInView` demands a curve lying exactly on the
datum's own line *in the target view* - and the line read out of the old
dependent is on the same grid but at *that* view's cut plane. The new parent has
a view template applied, which can move the cut plane, so the old line arrived
as a parallel line a few hundred millimetres off, and Revit said no. Nothing
was written, and the dependent kept what it had inherited from the new parent:
3D, the model extent.

The old line's head and tail are now **projected onto the new view's own
line** before the write - same direction, same Z, ends in the target's own
order - so the curve is coincident by construction and the head and tail land
exactly where they were in the view being copied from. Both ends are forced
view specific in the target first, since a 3D end will not report a line of its
own.

- The read-back compares head and tail against the fitted line, so a cut plane
  difference is no longer reported as a mismatch.
- `fit_line` is a pure function with its own bench checks: cut plane
  difference, a hair off the line, ends the other way round, a diagonal grid,
  and a line square to the grid that collapses and is refused.

## 1.2.2

**Fixed: the grid stretch still came out wrong on dependent views.** The write
was happening and was then being undone. Revit propagates a primary view's
datum extents down to its dependents when the document regenerates, so setting
the parent and then the dependent inside one transaction loses the dependent's
own stretch at the commit - the parent's version lands on top.

Matching the stretch is now its own pass, run after the views exist and in two
waves with a commit between them. The parents and plain duplicates go first and
are committed, so the propagation happens and is out of the way; only then does
each dependent get its own. **Every dependent is treated as a view in its own
right** and matched against the dependent it was duplicated from, never against
the parent.

- **The result is read back and proved.** Every line that was supposed to be
  copied is read out of the new view and compared with the one it came from,
  either way round, to within a millimetre. Anything that did not take is
  reported and named. A void API call is not evidence.
- **A datum Revit refuses is no longer swallowed.** The reason goes into the
  debug report, so "the grids did not move" and "the grids match" can be told
  apart.
- `same_line` is a pure function with its own bench checks.

## 1.2.1

**Fixed: matching the grid stretch pinned every grid to the model extent.**
A datum end is either 3D, where the line runs to the model extent and every
view shares it, or view specific, where the view holds its own shortened line.
1.2.0 read the view-specific curve and wrote it whatever the source end was
actually doing - and `GetCurvesInView(ViewSpecific, view)` hands back the
model-extent line for a datum that is in 3D mode, while `SetCurveInView` puts
the target end *into* view-specific mode to accept it. So every grid in the new
view was pinned to the full model extent, the annotation crop grew to contain
the bubbles, the viewport grew with it, and the plan came out a third of the
size it should have been on a sheet of grid lines running off the page.

The extent type is now copied end by end, and the curve is only written where
the source end really is view specific. An override is copied; one is never
invented. A dependent takes its stretch from the dependent it was duplicated
from, as it did before.

- The debug report says how many datums were stretched to match and how many
  were left on their 3D extent, so the two cases can be told apart.
- `datum_needs_curve` is a pure function with its own bench checks.

## 1.2.0

**Fixed: the sheet name was being written into the browser grouping
parameters.** `name_parameters` defaulted to the same four parameters as the
browser grouping, and the name push ran *after* the grouping - so the segments
of the sheet name overwrote the values that had just been set, and
BGL_Sheet Discipline came out as "Level 01" instead of "BUILDERSWORK". Three
changes: the default is now blank, so nothing is written until it is mapped on
purpose; the name push runs first and is not allowed to touch a parameter the
grouping is writing, reporting it as skipped rather than writing it twice; and
a migration resets the old default for anyone already carrying it.

- **Settings > Sheet name mapping** - three keyword-searchable pickers, one per
  segment of the sheet name. They are deliberately separate from the four
  browser grouping pickers, because they are separate jobs.
- **A blank slot keeps its place.** Leaving the first mapping as (none) means
  the first segment is not written; it does not shuffle the second segment up.
- **Match the grid and level stretch** from the view being copied from, on by
  default in the Views tab. Each grid's and level's 2D extents and bubble ends
  are copied into the new view, so a duplicated plan looks like the one it came
  from rather than showing the grids at their model extent.
- **Fixed: the table only sorted when the click landed on the letters of the
  heading.** A `Border` with no `Background` is not hit testable, so most of
  the header cell was a hole. The whole cell sorts now, the search box and the
  filter caret still handle their own clicks, and the DataGrid's own header
  sorting and reordering are turned off so they cannot fight it.
- **The sorted column is easier to see**: the title takes the sort colour as
  well as the outline - blue for the first level, orange for the second, green
  for the third.
- **Clicking a heading groups by it as well**, since "Group by sort" now
  defaults on. Collapse all then collapses every group of rows sharing that
  value. Shift-click a second heading for a second level of both.
- **The easter egg is reached the way `startup.py` reaches it**: the
  extension's `lib` is put on `sys.path` first and `egg_auto.install()` is
  armed. pyRevit only has `lib` on the path if something put it there this
  session, so relying on it meant the egg worked or did not depending on
  whether startup.py had run.

## 1.1.2

**Fixed: PacMan did not open.** The egg's entry points were guessed at rather
than looked up. `egg_hook.launch(host_window, theme, game_key)` is the way in
without the clicks, and it was being called with the string "pacman" as its
first positional argument - which is `host_window`. Every guessed spelling
after that failed too, so the answer to "would you like to play PacMan" was a
status line saying the egg was not installed. It now calls `launch` properly,
with `game_key` naming the game's own file in `egg\games`.

- **The logo hook uses `attach_to_window`**, the egg's current call, which
  finds the RevoBIM logo itself whatever the layout calls it. The older
  `attach(logo, host_window=...)` form is kept as a fallback for an older copy
  of the shared package.
- **The egg follows the theme chip.** Both the hook and the direct launch are
  handed a callable rather than a value, so switching the tool between dark and
  light while the game is open takes the game with it.
- The bench now insists on the real spellings - `attach_to_window`, `launch`
  and `game_key` - so a guessed API name fails here rather than in Revit as a
  button that appears to do nothing.
- The settings window was not holding its own theme, which would have thrown
  the moment its logo was wired to the egg.

- **A Previous button** beside Next in the duplicate dialog. It keeps its
  place on the first tab and greys out rather than disappearing, because a
  button that moves as you walk through is harder to hit than one that does not.

## 1.1.1

**Fixed: every new sheet came out called Unnamed and filling it in reported
RolledBack.** A title block instance also shows the *sheet's* parameters -
Sheet Number, Sheet Name, the issue date, Drawn By and the rest - and writing
one of those writes through to the sheet. Copying every writable parameter from
the old title block to the new one therefore put the old sheet number back on
the new sheet, Revit refused the duplicate, and the transaction rolled back,
taking the name and the browser grouping with it. Anything the sheet itself
carries is now skipped when copying the title block: it has already been copied
onto the sheet, where it belongs.

- **A rolled-back commit now says what Revit objected to.** The failure
  preprocessor records every message with its severity and its failing element
  ids, and the report quotes them. Previously the only thing on screen was the
  word RolledBack, which explains nothing.
- **The failure preprocessor takes each message on its own.** `DeleteWarning`
  throws when handed an error, and one throw was abandoning the whole loop, so
  everything after the first error went unhandled. Warnings are deleted, errors
  are recorded and left to fail honestly.
- **The preprocessor is kept alive on the Python side.** An object whose only
  reference is the .NET side can be collected out from under Revit.
- **Filling a sheet in is three transactions, not one**: the name and the
  sheet's parameters, then placing the views, then the grouping and the name
  parameters. A step Revit refuses now costs that step and not the other two.
- The rule that caused this is a pure function with its own bench checks
  (`titleblock_copy_names`), so it cannot quietly come back.

## 1.1.0

**Fixed: views were made and the sheets were not.** Everything about a new
sheet went into one transaction - create it, number it, name it, copy the
sheet's parameters, copy the title block's parameters, carry the revisions,
place the views, set the browser grouping, push the name parameters. Anything
in that list throwing rolled the transaction back and took the sheet with it,
while the views, made earlier in their own transactions, survived. It is two
transactions per sheet now: the first creates it and numbers it, the second
does everything optional. A failure in the second leaves the sheet in the model
and says what went wrong.

- **Debug tickbox** in the footer. Records the Revit version and build, every
  option, the grouping, every view job, every sheet row with its status, and
  each sheet step by step. Written to
  `%APPDATA%\RevoBIM\sheet_manager_debug.txt` and shown afterwards with a
  copy-to-clipboard button. Exception type names are recorded as well as their
  text, because several Revit exceptions carry no text at all.
- **Sorting in levels.** Clicking a heading sorts by it and outlines it in
  blue. Shift-clicking another heading adds a second level, outlined in orange,
  and a third in green. Shift-clicking a level already there flips its
  direction.
- **Group by sort**, a chip in the toolbar: the table groups by whatever it is
  sorted by, so a shift-added second sort level becomes a second level of
  groups that collapses like any other.
- **Live examples** under the sheet number, sheet name and view name boxes,
  worked off the first sheet in the selection and updating as you type.
- **A green Next button** walks Sheets, Views, Preview. Duplicate stays grey
  until all three have been looked at, then goes green - the preview is where a
  number clash shows up, so pressing Duplicate without having seen it is the
  one mistake the dialog can prevent.
- **A real progress bar** with a running count, updated between transactions.
- **PacMan** is offered while the run goes on.
- **The new sheets are offered afterwards**, and the one picked is opened.
- **View templates are picked from a keyword search**, not a dropdown.
- **The browser grouping parameters are four searchable pickers** in Settings -
  1st, 2nd, 3rd and 4th Grouping, the same four levels Revit's own Browser
  Organization Properties dialog offers, in the same order.
- A stable descending sort. Sorting and then reversing the list also reverses
  what the levels below it did, which silently undid the second and third sort;
  caught on the bench.

## 1.0.1

- **Fixed: the window would not open.** A `DataGrid` column's `Width` is a
  `DataGridLength`, not the `GridLength` a `Grid`'s own rows and columns take.
  The two read identically and are not interchangeable, and Revit answers the
  wrong one with `TypeError: expected DataGridLength, got GridLength` at the
  moment the window is built - which the staged loader reported as a failure at
  the "showing the window" stage. Both the main table and the duplicate
  dialog's preview tables were affected.
- A sixteenth bench rule catches it: a DataGrid column measured in
  `GridLength`, or a `Grid` definition measured in `DataGridLength`. Proved by
  deliberate breakage like the other fifteen.

## 1.0.0

First release.

- Every sheet in the project in one table, read in a single pass rather than a
  collector per sheet.
- Parameter columns chosen from a tick list of every parameter the sheets
  actually carry; the set is remembered. Sheet Number and Sheet Name are
  always shown.
- Every column heading carries a keyword search box and an Excel style tick
  filter, and clicking the heading sorts by it. A search box above the table
  searches every column at once, debounced.
- Up to three levels of grouping, cascading open and shut, with counts on each
  group row and Expand all / Collapse all. The group-by choice is remembered.
- Columns open on the project browser's own sheet grouping parameters when
  nothing is set in Settings.
- Select any number of sheets and duplicate them with the views on them.
- Duplicate options: find and replace plus a prefix for sheet numbers, sheet
  names and view names, each with a live preview; view template per view type;
  with or without detailing; retain room names; legends, schedules and drafting
  views reused or duplicated; carry revisions; copy the sheet's and the title
  block's other parameters.
- A dependent view on a sheet brings its parent across, and the parent's whole
  family of dependents with it, so the new sheets keep the same view
  organisation. A dependent whose own sheet is not in the selection is still
  made, and is reported as landing on no sheet.
- The new sheet name can be split on underscores and pushed into the name
  parameters set in Settings, the same rule Sheet Management uses.
- The project browser grouping is set as the sheets are made, prefilled with
  what the source sheets carry, with a picker of every value already used in
  the project and free text allowed.
- Dark and light, with Auto following Revit's own canvas theme through
  `UIThemeManager.CurrentTheme`.
- Easter egg on the RevoBIM logo, three slow clicks, in every window.
- `import_check.py` with fifteen rules, every one proved by deliberate
  breakage in `--selftest`. `bench_logic.py` with 97 checks of the naming
  rules, the duplication plan and the table's filtering, sorting and grouping,
  under plain CPython.
