# Family Viewer - changelog

All notable changes to this tool. Semantic versioning: MAJOR.MINOR.PATCH.
`__version__` lives at the top of `fv_core.py`; both windows read it from
there, so bumping that one line is the only edit needed.

## 2.0.2

### Batch rename from the toolbar

- **New Batch rename button** on the toolbar, next to Excel. It is greyed out
  with nothing picked and **lights green** as soon as families or types are
  selected in the list.
- Pressing it drops down a small tool window with **Find and replace** (with
  Match case), **Add prefix** and **Add suffix**. It previews as you type -
  how many names will change, how many are unchanged, how many are refused and
  why - and shows the first rename as an example.
- **Apply to selected** stages the new names on the picked rows in **green**.
  Nothing is written until **Apply** on the edit bar, as with every other edit.
- **Right click > Batch rename** on a multi-selection now opens that same
  drop-down. The full batch rename window (picked cells, parameters, copy,
  paste and fill) is still there as **Batch rename editor** on the same menu,
  and as **Full editor...** inside the drop-down.
- Same rules as the full window, because it is built on the same code: a name
  that would clash with one already in the family or category, clash with
  another picked row, or come out blank is refused and left alone.

### Progress bar while Apply writes

- Applying a large set of changes - typically an imported workbook - now
  shows a **themed progress bar at the bottom**, in place of the edit bar, with
  the percentage and "Writing 1,240 of 3,000 changes". It walks through
  checking out the elements, writing, and committing (Revit regenerating).
- Still **one transaction**: a failure rolls the whole run back exactly as
  before. The bar repaints by giving the dispatcher a moment at Render
  priority, which runs the repaint but not mouse or keyboard input, so nothing
  can be clicked in the middle of the write. Updates are throttled (at least 1%
  and ~0.12 s apart) so drawing the bar does not slow the write.
- If Apply fails, the bar goes away and the edit bar comes back with the staged
  changes still on it.

Bench: 350 checks (was 321) - the percentage maths, throttling, a bar that
raises being dropped rather than stopping the write, and the quick rename's
clash rules.

## 2.0.1

### Family names changed in Excel did nothing

The workbook coloured the **Family** column orange and its legend sheet called
it editable - and the import had left that column out of the comparison since
1.3.0. A family renamed in Excel was read, compared, and thrown away, so the
import found nothing to stage and Apply had nothing to write.

- **The Family column is imported now, as a rename of the family.** The family
  name sits on the family's own row and on every type row under it, so every
  row carrying a new name votes for it: one new name across them is staged once
  on the family, in teal, with the family highlighted. Renaming it on the
  family row alone, on the type rows alone, or everywhere at once (Excel's find
  and replace) all work.
- Rows that give one family **two different new names** are refused, naming
  both, rather than one being picked.
- A blanked family name and a **system family** (walls, pipes, ducts - there is
  no family element to rename) are refused with the reason.
- The workbook's legend explains all of that.

**The bench gained the check that would have caught it**: every column the
workbook calls editable must come back from an import as a change or a refusal
- never read and silently dropped. Putting the 2.0.0 line back fails it.

### The debug report could not have shown this

- **Imports and Apply results are logged**: rows read, changes staged,
  unchanged, not imported, and the headings the workbook carried; values
  written, refused (each with its reason) and locked.
- The report has a **Last import** section with the full summary, and what is
  staged now by source.
- **The pane registration no longer fills the log.** pyRevit runs the startup
  block on every reload while Revit keeps the pane it already registered, and
  each run logged a "Cannot register the same dockable pane ID more than once"
  traceback - thirty of them in the last report, burying everything else. It
  checks `PaneIsRegistered` first now. The fix lives in `fv_dock.py`, so the
  block already pasted into `startup.py` does not need pasting again.

`bench_logic.py` up to **321 checks**.

## 2.0.0

A streamlining pass, Revit's own dark theme, the shrink-to-taskbar drawer the
project asks of every window, and an Excel import that tells you what it did.

### Excel import

- **Nothing is written until Apply.** That was already so; it is now proved -
  the bench walks every function on the import path and fails if any of them
  raises the Apply job.
- Imported changes are staged in **teal**, apart from orange (typed by hand)
  and green (batch rename), and **every family holding one gets a teal band**
  behind its whole row.
- A **summary prompt** after every import: rows read, values changed (and on
  how many rows, across how many families), rows unchanged, and rows not
  imported - split into values that could not be staged, ids the model does not
  have, and rows with no readable id - with the refusals listed by name.
- The comparison is now `fv_excel.plan_import`, a plain function the bench
  proves: every row read lands in exactly one bucket.
- Three faults fixed on the way:
  - rows were matched against the **rows on screen**, so anything a filter hid
    came back "not in the list". They are matched against the whole read now,
    instances included;
  - a row with an **unreadable id was skipped without being counted**;
  - an id that came back from the workbook as the text `501.0` did not
    match `501`.

### Revit's own dark theme

- The dark palette is **Revit's own greys**, sampled from its dark Project
  Browser and shared with Project Browser Pro, Filter Manager and Pro Sheets
  Exporter - title bar `#222933`, body `#3C4454`, fields `#2D3441`, Revit's
  active blue `#3A7392` for selection.
- On that lighter body the old green and red fell under 4:1 and are lifted;
  the group-value washes were redesigned, since the old ones were drawn for the
  near-black and vanished on Revit's grey.
- **Follows Revit's canvas theme** by default - Follow / Dark / Light in
  Settings - and tracks it live while open. The header chip still flips it by
  hand.
- `Theme.xaml`'s fallback brushes carry the same values, so a window never
  flashes the old colours before the palette lands.
- **Settings migration 2** resets the saved theme to follow Revit, and resets
  `phase_mode` too: 1.5.0 changed its default to "existing" - the fix for the
  list coming back empty - without a migration, so any settings file written
  before then still held the "created" value that caused it.

### Shrink to taskbar

Every window - the main window, batch rename, settings and every prompt -
carries the shrink control beside full screen and close. It slides the window
down to the bottom of **its own** screen, leaving the header floating clear of
the taskbar; the control becomes a green up arrow that opens it again.
Ctrl+Shift+H either way.

- Slides by setting `Top` and `Height` from a timer rather than
  `BeginAnimation`, which holds its end value and would leave the window unable
  to move or resize again.
- `MinHeight` and `SizeToContent` are relaxed for the slide and put back; the
  body is pinned so it is clipped rather than squashed; the resize grips are
  parked with the window.
- While parked, Escape, Enter and F11 open it; a double click on the bar opens
  it; the bar can be dragged, and opens **upward from wherever it was left**.
- A modal dialog takes its owner down with it, stacked beneath, and brings it
  back. A dialog opening over a parked owner centres on the screen.
- **The shrink button stays live while a job runs.** The body and the other
  header controls go deaf instead, and the parked bar will not drag mid-job.
- The prompt dialog now shows the version in its top right, like every other
  window.

### The toolbar

- A **show / hide family images** toggle. Same setting as the one in Settings,
  so the two never disagree.

### Streamlining and speed

- **Apply finds the instances of every edited type in one pass of the model.**
  An instance-level parameter used to open a fresh collector over the whole
  model per type, inside the Apply transaction. The project's worksets are
  listed once per run rather than once per element moved.
- The ancestor walk, the folder opener and the style-setting blocks were copied
  between modules; they live once in `fv_ui` now. Eighteen four-line style
  blocks became one call each.
- Dead code out: `_star`, `instances_of`, three unused dock helpers, an unused
  probe import, a stale constant.
- Staged changes record **where they came from** in one map rather than a set
  per source - and a parameter staged by batch rename is now green like its
  name, where it had been orange.
- The Apply prompt labels changes from the whole read, so a staged change a
  filter hides is named rather than shown as a bare id.
- About 330 lines of duplication and dead code removed. The tool is larger
  overall because the drawer, the import planner and the theme detection are
  new.

### Bench

- `import_check.py` **21 rules**, all 28 breakages caught. New:
  - **19 `defined_once`** - nothing defined twice in one scope;
  - **20 `revit_dark`** - the dark palette against Revit's values written into
    the check itself, Theme.xaml's fallbacks against the palette, and every
    text colour against every dark background at 4:1;
  - **21 `drawer_wired`** - every window has a shrink button, every shrink
    button is handed to a drawer, and no animation is left unreleased.
- **Rule 12 rewritten over the AST.** It matched only the text
  `SetResourceReference(`, so the streamlining - which moved those calls into
  `fv_ui.styled()` - had quietly blinded it, and a `brush('Key')` lookup of a
  key nobody defines returns `None` without a word. It now covers every route a
  key takes, and found the two teal keys missing before they shipped.
- `bench_logic.py` **308 checks**, among them: the follow rule including Revit's
  `UITheme.Dark == 0` trap, the migration, the import planner, and the drawer
  driven through a fake timer that - like the real one - never ticks inside
  `Start()` and records anything escaping a frame.

## 1.10.1

### The column filter was only looking at half the list

The tick list was gathered from the **type rows alone**. A parameter that lives
on the instance reads `(varies)` on a type line, so the filter for such a
column offered `(varies)` and one or two stragglers - which is to say, every
value the list can actually be filtered by was missing from the filter.

- The values are now gathered from the type rows **and the elements under
  them**.
- **`(varies)` is never offered.** It is the type line saying its instances
  disagree; the values it stands for are in the list already, from those
  instances, so offering it as well would only be a way to tick something that
  filters to nothing.
- A blank is offered like any other value - "which ones have nothing set" is
  usually the question being asked.
- **The column filters now apply to the elements too.** Offering a value and
  then not filtering by it would be worse than not offering it: the list would
  look filtered and not be.

### Picking elements means those elements

Select all instances acted on the **types** behind whatever was picked, so
picking one door out of forty selected all forty - the opposite of what picking
one of them says.

- Picking element rows now selects **exactly those elements**, in Revit, and
  Isolate in View isolates exactly those. A group heading counts as picking
  every element under it.
- The scope does not narrow them either: they were named, and a name is more
  specific than a scope. The report says "the model" rather than naming a scope
  that had no say.
- The footer says which it is doing - "12 elements picked. The buttons act on
  those, not on every instance of their types."
- Picking families or types is unchanged.

`bench_logic.py` up to **237 checks**, covering what the tick list offers, that
`(varies)` stays out of it, and that a blank stays in.

## 1.10.0

### Sorting reaches the elements

Clicking a column heading sorted the families and the types and left the
elements under them in their own order. It now sorts **every level**: the
elements under each type follow the same column, ties falling back to the
element's own order so the result is stable.

With no column - or sorted by the name - elements go in their natural order,
which for an element is its mark and then its id: D01, D02, D03, D10, not D01,
D10, D02.

**Every column can now be sorted by.** A parameter column's heading is the
picker chip, so clicking the heading opens the picker and could never be the
sort - which left no way at all to sort by a parameter, and grouping is by the
sorted column. The arrow is its own hit target now and sits on every heading,
muted until that column is the one in use.

### The sorted column is outlined orange

A border round the whole heading, lit orange while the list is sorted by it,
with the arrow lit to match. **The thickness never changes, only the colour**,
so lighting one cannot nudge the layout of the row of headings.

### The grouped column is colourised

Group the elements and **every distinct value gets its own wash** behind the
cells that share it - on the group heading and on the elements under it - so
which elements share a value reads at a glance instead of by comparing the text
of forty rows.

- The washes are **faint on purpose**: they sit behind the value, and a strong
  fill would fight the staged-edit and refusal colours, which have to stay the
  loudest things in the table.
- Six of them, cycling, and the order a value is first seen decides its colour,
  so the same grouping gives the same colours every time it is redrawn.
- Dark and light have their own set, worked out again on a palette switch.
- Only on the column being grouped by, and only on the rows the grouping
  applies to.

Headings expand and collapse by their chevron as before, and changing the sort
to a column that cannot be grouped ungroups rather than grouping by something
nobody asked for.

`bench_logic.py` up to **231 checks**, covering the element sort in both
directions, the natural order, the tie-break, and sorting then grouping.

## 1.9.1

### "That is a bug - please report it" was itself the bug

Ticking one category and looking at a view with none of it in produced an
accusation: *"None of the 2922 elements in the active view belong to any of the
13 types read. That is a bug."*

It was not a bug. The check counted **every** element whose type was not among
the ones read - and with a category ticked, nearly every element in a view
legitimately is not. A structural view holding 2922 slabs and nothing else is
supposed to miss all 2922 when Generic Models is what you asked for.

The read now counts two things apart:

- elements **in the categories that are ticked**, and
- of those, how many belonged to a type that was not read.

Only the second is evidence of anything wrong. The first being zero is the
ordinary case, and it now says so: *"None of the 2922 elements in this view are
in the categories you have ticked."* The empty-list note adds the useful part -
those categories do exist in the project, there is just nothing of them in this
view, so switch the scope or open a view that has some.

The bench could not have caught this, because **its fake element had no
`Category` at all** - so it could not tell "wrong category" from "type not
read", which is the entire distinction. The fakes carry a category now, the
fixture has a view holding nothing but a pipe (a structural view, to somebody
who has ticked Generic Models), and removing the new branch was confirmed to
fail the bench.

### Debug report

A **Debug report** button next to Restore Default writes a report and puts it
on the clipboard, then offers to open the folder. It holds:

- the Revit version and build, the document, whether it is workshared, the
  active view and its type;
- what the tool was set to - scope, phase, phase mode, every category ticked,
  the columns, which column filters are on, the search box;
- what the read found - types read, elements Revit offered, **how many were in
  the ticked categories**, how many of those had a type that was not read,
  nested and phase exclusions, the final count, and the tally by category;
- **what is actually in the active view, by category**, read fresh - the single
  most useful thing when the answer is "nothing showed up";
- every setting, and the last 150 lines of the log.

`bench_logic.py` up to **224 checks**.

## 1.9.0

### A third level: the elements themselves

The list was families and types. It now goes one level further, to **one line
per placed element** under its type, with a button at the top of the toolbar to
open every type down to that level and fold it away again.

- **Read on demand, not up front.** A real model has hundreds of types and tens
  of thousands of elements; reading every instance on every refresh to show a
  level most people never open would make the tool slow for everybody. The
  elements are read once, when the button is pressed, and kept.
- An element has **no name of its own** - `element.Name` on a family instance
  gives back the *type* name, which would repeat the line above it forty times.
  Its **Mark** identifies it, and its element id is what is left when there is
  no mark.
- The `#` column is **blank on an element row**: one element is one element,
  and a column of 1s is noise.
- Nested elements and the phase filter are applied exactly as the count applies
  them, so the elements listed under a type always add up to the number beside
  it.
- Capped, with **Most elements to list** in Settings, and the status line says
  when the cap was the reason a list stopped.

### Grouping the elements

Sort by a parameter column, then press the **group** button, and the elements
under each type gather under a heading per distinct value. Press it again to
ungroup.

- **Grouping is by whatever column the list is sorted on**, so it needs a
  parameter column: grouping by the name or the count would put one element
  under each heading, and the button says so rather than going quietly dead.
- Changing the sort to a column that cannot be grouped **ungroups rather than
  grouping by something nobody asked for**.
- A blank value gets **its own heading** rather than being dropped - "which
  ones have nothing set" is usually the question being asked.
- Grouping and ungrouping rearranges rows already in hand rather than reading
  the model again, which is what makes the button feel instant.

### Everything else follows the new levels

- Chevrons appear on anything with something under it - a family, a type whose
  elements have been read, a group heading - and each level is indented one
  step further, with an element under a heading a step further again so the two
  do not read as the same level.
- **The Select buttons mean the same thing whichever level was clicked**: a
  family gives its types, a heading gives the types under it, an element gives
  the type it is an instance of.
- **An element's parameters are editable and are written to that element**,
  not to every instance of its type. Its name is not, because what shows there
  is its mark or its id. A group heading holds no element, so it takes no edit.

### Bench

`bench_logic.py` up to **216 checks**: the instance read against the fake
document, the nested and cap rules, the grouping including the blank heading,
and `flatten` walking all four levels honouring each row's open state.

## 1.8.0

### The footer

- **The report moved onto its own line, above the buttons and across the whole
  width.** Squeezed in beside them it was trimmed to an ellipsis after a few
  words, which is no use for the one line that says what is picked. It wraps
  now rather than trimming.
- **Entire Project, Active View and Restore Default are narrower** - smaller
  minimum widths, tighter padding and a slightly smaller face.

### Isolate in View

A third button, to the left of the other two. It **zooms to the elements of the
picked types in the active view, then isolates them** - Revit's own Temporary
Hide/Isolate, so the view reads exactly as it would if the command had been run
by hand.

Zoom first, isolate second: isolating first would frame a view that had already
been emptied of everything else, which is not the same framing at all.

Once pressed the button **turns red and reads Restore View**, and running it
resets Temporary Hide/Isolate. The isolation is left in the view until then
rather than being reset on the way out.

- **Restore View stays live with nothing picked.** The view is isolated, and
  getting it back must not depend on keeping a selection.
- Where none of the picked types have anything in the view, it says so and
  changes nothing.
- Temporary Hide/Isolate is a view setting rather than a UI command, so it goes
  through a transaction and a rollback rather than a posted command.
- Narrowed to "Isolate" on a squeezed window - but **Restore View keeps its
  full name at any width**, because it is the one that undoes something.

## 1.7.0

### The picked cells were invisible

The batch grid knew perfectly well what was selected - the status line counted
it correctly the whole time - and nothing on screen said so. `ThemedCell`
painted its own background from a `TemplateBinding` and **never looked at
`IsSelected`**, so a picked cell drew exactly like an unpicked one. It now
takes the selection colour and a blue edge.

### Batch rename works like a spreadsheet

- **Find and replace is behind one button.** The two bars were taking a third
  of the toolbar to sit empty most of the time. The button reads back what is
  set behind it - `Find "FD30"` - so a find left in the popup cannot quietly go
  on applying.
- **Ctrl+C and Ctrl+V.** Copy writes the picked cells tab separated by column
  and newline separated by row, which is what Excel reads, so it pastes
  straight into a sheet and back. Paste starts at the picked cell and spreads
  down and across.
- **Drag the small square at a cell's bottom right to fill downwards.** A value
  ending in a number counts on from it, **keeping the width it was written
  with** - `BGL_Door_01` fills to `_02`, `_03` - and anything else repeats. A
  number in the middle is not the one counted.
- The handle only appears where there is one place to fill from: the lowest
  picked cell, and only when the picked cells are all in one column.
- **A locked cell is stepped over by both**, and the count says how many.
  Pasting a column over a bank that includes an instance parameter should not
  silently lose part of it.

### The family rows read as blocks

- A **darker band behind the whole family row**, so a bank of types reads as
  one block under the family it belongs to.
- The family name is **larger**.
- Both are settings: **Family row shade** takes a hex colour and **Family name
  size** takes a number. A blank shade follows the palette, so switching
  between dark and light still works rather than leaving one hard-coded shade
  on both. A colour that will not parse is refused when Apply is pressed rather
  than saved and then quietly ignored every time the grid draws.

The row band is set in a `LoadingRow` handler rather than a style trigger,
because the row's kind is a Python attribute and a WPF trigger cannot see one.

### Bench

`bench_logic.py` up to **198 checks**, the new ones covering the fill rule -
repeat, count on, leading zeros kept, a number in the middle left alone.

## 1.6.0

### Categories from the active view

A **Select categories from active view** button at the top of the category
picker ticks exactly the categories that have something in the view on screen
and unticks the rest. It reads that off the **elements**, not off the view's
category settings: a category can be switched on in a view and have nothing in
it, and ticking it would then be a lie. Categories in the view that this list
does not cover - system or annotation ones, off in Settings - are counted and
named rather than silently dropped.

### Worksets

Add **Workset** as a column and a type whose instances sit on different
worksets reads `(varies)`. Click the cell and it opens a **dropdown of the
worksets in the project** rather than a text box, because a workset has to be
one that exists and typing it is a way to get it wrong.

**Pick several types first and choosing one moves all of them**, which is the
reason to want this on a bank of types. A type does not sit on a workset - its
instances do - so applying moves every instance behind the row, and the summary
says so. The column is only offered on a workshared model.

### Restore Default

Bottom left, outlined red. Clears every column search and tick filter, sets the
phase to every phase and the scope to all families in project. **The categories
are deliberately kept** - they are usually a deliberate narrowing of a big
model, and throwing them away would mean picking them all again. It asks first,
and it writes nothing to the model.

### The count column

- Heading is **#**, it has moved to **the left of Family and type**, and both
  are **frozen** so the number stays in view while the parameter columns scroll.
- **Zeros are red** rather than greyed - nothing placed is worth seeing.
- Numbers are **centred**, and the **family total is bold**.
- Narrow enough to be tidy, wide enough for three digits, and still draggable.

The scope icon is an **eyeball**.

### Batch rename

What is picked now decides what the window is for:

- **Families only** - it renames families, and nothing else. A family line's
  parameter cells have no single element behind them, so there is nothing there
  to write.
- **Any type picked** - it is about types: their names and their editable
  parameters. The families those types belong to are listed **for grouping**,
  so a bank of types reads under the family it came from, and their cells are
  **locked**.
- A parameter that lives on the **instance** rather than the type is shown so
  the row reads properly, and locked, because writing it from here would mean
  writing it to every instance behind that row without saying so.
- A locked cell is **greyed, cannot be picked as a target, refuses to be typed
  into, and is never handed back** - three separate ways of not applying it,
  because one would have been enough only until somebody found the other two.
- The editable parameter set comes through from the main window's columns.

### Bench

`bench_logic.py` up to **188 checks**, the new ones covering every route into a
locked cell. `import_check.py` gained an audited exception: `workset_number`
may read `.IntegerValue`, because a `WorksetId` is not an `ElementId`, was not
touched by the 2026 removal, and carries no `.Value` - confined to one function
so the rule still means something everywhere else. The bench's column lookups
are by key rather than by position, which is what broke when the count column
moved.

## 1.5.0

### It was the phase, not the scope

The diagnostics added in 1.4.3 answered it: *"152 elements were left out by the
phase filter and nothing was left."* A phase had been picked at some point, it
was **saved between sessions**, and `phase_mode` defaulted to **created** -
which keeps only what was made in that exact phase and drops everything else.
So every scope came back empty, with nothing on screen saying a filter was even
on. The scope was doing as it was told the whole time.

Three changes, because one alone would have left the trap:

- **A phase is no longer remembered between sessions.** It belongs to a
  reading, not to a preference, and phases differ from job to job - a phase
  name saved on one model matching a phase on another is exactly how this
  happened. The window always opens on every phase.
- **`phase_mode` defaults to "what stands in the phase"**, not "what was
  created in it". Created drops everything not made in that exact phase, which
  on a real model is nearly everything.
- **An overarching filter that is on now looks like it.** The phase and
  category icons go orange while they are filtering. An invisible filter that
  empties the whole list is what cost three rounds of this.

### The scopes, rebuilt

Written from scratch as one function, `scope_rules`, which turns a scope name
into both halves of what it means - where to count, and whether to keep a type
with nothing placed. Every earlier version worked that out in two places that
could disagree, and did.

| Scope | What it lists |
| --- | --- |
| **Entire project** | every family placed anywhere in the project |
| **Active view** | every family placed in the active view only |
| **All families in project, including not placed** | every family in the project, whether placed or not |

- The third option is relabelled as asked.
- `read()` takes the scope **by name**. A view handed to a scope that does not
  want one is dropped inside the read, so the count can never be scoped to a
  view while the whole project was asked for.
- The view scope with no active view says so, rather than quietly counting the
  whole project.
- The window works nothing out for itself any more - the bench fails if the
  word `include_unused` appears in it at all.

### Bench

`bench_logic.py` up to **178 checks**. The three scopes run through the real
`read()`, `scope_rules` is checked directly, and the phase defaults are
asserted - putting `phase_mode` back to `created` was confirmed to fail it.

## 1.4.3

### "Nothing matches" was the wrong answer to the wrong question

The empty list had one message, and it blamed the column filters whatever the
cause. Two rounds of this bug were spent looking at filters that had never been
set, because the read itself had come back with nothing and the window had no
way to say so.

There are three different situations and they get three different answers now:

1. **The read found nothing** - says so, names the scope, and repeats whatever
   the read itself reported.
2. **The filters hid everything** - names the columns doing the hiding and how
   many rows they hid.
3. **Neither** - says that plainly, because that should not happen.

The read reports where the elements went, too: how many Revit offered, how
many belonged to none of the types read, how many were nested inside another
family, and how many the phase filter dropped. An empty list can now explain
itself instead of being guessed at.

### A second scope bug, found by the bench

The counter added in 1.4.2 to count elements offered was called `seen` - a name
already in use a few lines further down the same loop for the list of values
gathered per parameter. `seen += 1` against a list raises, and the whole read
died. Renamed.

Both scope bugs were runtime failures inside the count pass that no static
check could see, so **the bench now runs the real `read()` three ways** -
whole project, active view, and all families - against a document with a
family loaded and never placed, and asserts the counts. Deliberately
reintroducing each of the two bugs was confirmed to fail it.

`bench_logic.py` up to **168 checks**.

## 1.4.2

### Entire project and Active view listed nothing

The count pass carried an `ElementMulticategoryFilter` built from the category
ids. It was only ever a speed optimisation, and it is **the one step in the
count that can match nothing without raising**. When it did, every type came
back with a count of zero - so the two scopes that drop zero-count types listed
nothing at all, while All families looked fine because it keeps them.

The give-away was that **Select all instances worked the whole time**.
`instance_ids` runs the same loop over the same collector and never carried
that filter, which is why one worked and the other did not.

- The filter is gone. It was not doing the filtering anyway: a type that is
  not in the type dictionary is skipped, and that dictionary is already built
  from exactly the categories asked for.
- If types are read and **nothing counts against any of them**, the list now
  says so and points at All families, rather than going blank with no
  explanation.
- The bench asserts against the shipped source that the count pass carries no
  category filter, and that Select and Count use the same lookup.

### The window going missing behind Revit

Owning the window to Revit's main window stops it slipping behind Revit, but a
click into Revit can still put Revit's own child windows in front of it, and
then there is no way back except moving Revit.

- The main window and the batch rename window now carry
  `ShowInTaskbar="True"`. **Hovering Revit's task bar button shows them among
  the thumbnails**, and they have their own entry as well, so there is always a
  way to bring one back. The settings and prompt dialogs are left off the task
  bar, since they are modal and short-lived.
- The owner is **re-asserted on Activated**. Revit re-parents its main window on
  some operations and an owner set once can quietly come undone.
- Pressing the ribbon button on an already open window now un-minimises,
  shows, activates and focuses it, rather than only calling `Activate`.

### Importing a workbook isolates the list

- After an import the list shows **only the rows the workbook changed**,
  ignoring the category, the phase and every column filter - a filter set
  before the import would hide half of what came back.
- **Show everything** in the edit bar puts the filters back without touching
  the staged changes, so they can still be applied.
- **Apply puts the original filtering back by itself**, after the re-read. A
  read clears the filters on purpose, so the restore is handed to the read to
  do afterwards rather than being wiped by it.

## 1.4.1

### The scope options do what they say now

The three options were still being crossed with a "show types with a count of
zero" setting, so what the list showed depended on a checkbox in Settings as
well as the chip that had just been pressed - and the two could disagree.

The scope alone decides it, because that is the whole meaning of the three
options:

| Scope | What it lists |
| --- | --- |
| Entire project | every type with elements placed in the project |
| Active view | every type with elements in the view on screen |
| All families (not placed) | every type loaded, placed or not |

**The first two never show a type whose count is zero.** All three sit under
the category and phase filters, which are the overarching ones.

The Settings checkbox is gone; keeping it would only let it disagree again.

- **Scope now behaves like Phase**: an icon opening a list, one pick, the list
  closes and the model is re-read. The inline chips from 1.4.0 are gone.

### Batch rename

Picking cells did nothing, and the reason was self-inflicted: `refresh()` ran
on every keystroke in the tools and on every selection change, and it
reassigned the grid's `ItemsSource` each time. That rebuilds every row and
**empties the selection with it**, so a pick never survived long enough to be
used.

- The items are set **once**. Refresh redraws through `Items.Refresh()`.
- The window keeps **its own record of what is picked** and puts the selection
  back after every redraw, with a suspend flag so restoring it does not
  re-enter the handler that reads it.
- **Double click a cell and type the value straight in**, the way the Excel for
  Revit tool does. A typed value wins over the tools and is not undone by
  retyping them; typing a cell back to what it was clears it rather than
  staging a no-op. Clear tools clears typed values too.
- The footer counts them separately: what the tools would change, and what was
  typed in by hand.

### Bench

`bench_logic.py` up to **153 checks**. The scope rule is now asserted against
the shipped source rather than restated in the test, so the setting cannot
creep back in without the bench failing.

## 1.4.0

### The scope bug

Changing the scope read the model but the list did not follow. Two things:

- The chips were hung on the radio buttons' `Checked` event and the handler
  compared the new scope with the old before doing anything, so **clicking the
  scope you were already on raised nothing and read nothing**.
- Worse, a column search or tick filter from the previous read stayed active
  across the re-read, so rows the new scope had genuinely found were then
  hidden by a filter set against a reading that no longer existed. That is what
  looked like the list not refreshing.

**Every column search and tick filter is now cleared on every read** - on
Refresh, on a scope change, on a category change, and on opening the tool. A
filter is about the list on screen, and a re-read replaces that list. The chips
are on `Click`, so a chip is a request to read at that scope every time.

### The toolbar

- **Scope unfolds inline** beside its icon, the same way Search unfolds its
  box, rather than floating a popup over the list it is about to change.
- **Expand all and Collapse all are one icon** that flips to whichever the list
  is not already mostly in.
- **Export and Import are one Excel icon** that opens a small menu offering
  each.
- **Refresh is an icon** and has moved up with the others. It grows an **orange
  dot** and turns orange when the model has moved on, instead of the old
  `Refresh *`.

### Elsewhere

- **Apply goes green** the moment there is something it can write, and sits
  grey and disabled when there is not, so the button says whether it will do
  anything before it is pressed.
- The place button in each row is a **small pointing hand**, drawn as a Path
  rather than set in a symbol font.
- **Exporting offers to open the folder** afterwards, selecting the file in
  Explorer.

### Batch rename does parameters now

- The window carries **the same columns the main window is showing** - the
  name, and every parameter column added there.
- **Pick the cells the tools apply to**: click one, ctrl click to add more,
  shift click for a run down a column. With nothing picked they apply to every
  name, which is what they did before. So one window renames types *and*
  re-stamps a parameter without doing both to everything.
- It **goes full screen** (button, F11, double click the header), carries its
  own **resize grips**, and its **columns can be dragged wider** - pixel widths
  rather than stars, so the grid scrolls sideways instead of squeezing every
  column into nothing.
- **A repeated parameter value is not a clash.** Only names can clash; treating
  a repeat as one would stop the single thing re-stamping a parameter is for.
  A parameter emptied to nothing is allowed too, unlike a name.

### Bench

`bench_logic.py` up to **147 checks**, the new ones covering cell targeting -
that a picked parameter cell is the only thing touched, that the name in that
row is left alone, that a run down a column changes every picked cell, and that
a repeated parameter value is not flagged. All 18 `import_check.py` rules still
catch their own breakage.

## 1.3.1

Fixes the tool failing to load at all in 1.3.0.

### What broke

`fv_excel.py` imported `ZipArchive` from `System.IO.Compression` at the top of
the module, and nothing had referenced that assembly. On Revit 2024 - .NET
Framework 4.8 - `System.IO.Compression` is its own assembly, so the import
threw `ImportError` at module load, `fv_window` imports `fv_excel`, and the
whole tool died before any of it ran.

- `fv_clr.py` now references **System.IO.Compression** and
  **System.IO.Compression.FileSystem**, each on its own inside a try/except:
  the first is where `ZipArchive` lives on .NET Framework 4.8, and on .NET 8
  (Revit 2025+) both are in the shared framework.
- The zip types are now asked for **at the point of use** rather than at module
  load. Nothing about listing families needs a zip, so a Revit that will not
  give one up should cost the Excel export and nothing else.
- Export and Import check first and say plainly that Excel is unavailable,
  rather than throwing.

### The rule that should have caught it

`clr_first` only proves `fv_clr` was imported before a .NET name was reached
for. It never proved `fv_clr` actually asks for the assembly that name lives
in - so every one of the seventeen rules passed on a build that could not
start.

**Rule 18, `namespace_assemblies`**, maps every namespace the tool imports to
the assembly holding it and fails the build if `fv_clr` does not reference it.
A namespace the table does not know about is also a failure, so the table
cannot quietly fall behind the code. All 18 rules catch their own breakage
under `--selftest`.

`bench_logic.py` up to **138 checks**, including one that fails if the zip
import ever moves back to module load.

## 1.3.0

### Renaming a cell works now

The rename editor was a themed popup over the cell, and it flashed up and
vanished. A `Popup` with `StaysOpen` false closes on the next mouse event
outside itself, and **the mouse-up that completes the double click that opened
it is exactly that event** - so it was closed before it was ever seen.

There is no popup. The cell's own content is swapped for a themed text box with
the value **selected ready to type over**, and swapped back on the way out.
Enter or clicking away commits, Escape cancels. That is also what puts the
editor where the eye already is.

### Place Instance moved into the row

- Each type row carries a small **square place button** to the left of its
  name, in the Family and type column. Rounded, bordered, and it fills green on
  hover so it reads as pressable without shouting over the row.
- The footer button is gone. The thing being placed is the row, so the button
  belongs beside it - and one button for a list of rows always had to guess
  which row was meant.
- Family rows and system types have no button: there is nothing to place.

### Batch rename

Right click one or more picked rows and choose **Batch rename**. Its own modal
window lists what was picked, with **find and replace** (case sensitive or
not), **add prefix** and **add suffix**, applied in that order and said so on
the window.

- **Every row previews what it would become** before anything is staged.
- A result that clashes with a name already in that family, that clashes with
  another row in the same batch, or that would leave a type with no name, is
  **flagged red on its own row** rather than failing halfway through the batch.
  A row being renamed away frees its old name for another row; a row that is
  *not* being renamed still holds its name.
- Apply there **does not write**. The new names come back to the main window as
  staged changes **picked out in green**, so what the batch did is visible at a
  glance among edits made by hand, which stay orange. Apply in the main window
  is still the only thing that touches the model.

### Export and import are Excel now

**Export** writes a real `.xlsx` and **Import** reads it back and stages what
changed. Built straight as Office Open XML into a zip through
`System.IO.Compression` - no Excel, no installed package - the same way the
Drawing Register's exporter works.

- House convention: **orange cells are editable, grey ones are read only**,
  with a frozen header, an autofilter, column widths and a legend sheet saying
  which is which.
- **Every value is written as inline text.** A shared string table would be
  smaller, but a type mark of "007" coming back as the number 7 - with the
  leading zeros gone before anybody looks - is the classic way an Excel round
  trip quietly corrupts a schedule.
- The import matches on the **element id**, not the name. Names change: that is
  the point of exporting, and matching on one would lose the row the moment
  somebody renamed it.
- Rows whose id is not in the list on screen are ignored and counted, rather
  than half-applied.
- The import **stages**; it does not write.

### Preview images

The family images have **rounded corners**. A `Border` does not clip its child,
so it is a clip on the image itself, with the radius following the image size.

### Bench

- Seventeenth rule: **`excel_inline_text`**, which fails the build if the
  exporter stops writing inline text or starts writing numeric cells. The
  failure it guards against is silent, which is what makes it worth a rule.
- `bench_logic.py` up to **136 checks**, adding the rename tools, the case
  blind replace that leaves the rest of the text alone, every clash rule, and
  the XML the exporter builds.
- The bench found a real gap while it was being written: a row renamed onto a
  name held by an **unchanged** row in the same batch was not flagged, because
  the clash check only looked at the rows that were changing.

## 1.2.0

### Columns

- **Right click a heading to remove the column.** Family and type is the one
  that cannot go - it is the frozen column and it carries the chevron, the
  preview image and the name, so the list makes no sense without it. Its menu
  entry is shown disabled saying so rather than hidden, so the menu is the
  same everywhere.
- **Drag a heading to reorder the columns.** The row list is rebuilt to match,
  so a later rebuild agrees with what is on screen rather than relaying it back
  to where it was. Anything dropped in front of Family and type is put back
  behind it: the frozen column is the first one by definition, and a frozen
  column that is not first freezes the wrong thing.
- The green **plus** is now a plus drawn from a `Path` rather than a "+" set in
  a font, so it cannot come out as an empty box on a machine without it. It
  offers Category and Count back before it starts offering parameters, so a
  column removed by mistake is one click away.

### The toolbar is four square icons

Categories, Scope, Phase and Search are square icon buttons that open into the
action, instead of four wide chips. Four of these fit where one chip used to,
which is what makes the tool usable squeezed into a Revit dock.

- Hovering names the button **and says what it is set to** - "Categories - 3
  picked", "Phase - Existing", "Scope - the active view". An icon has no room
  for a label, so the tooltip carries it.
- **Search unfolds out of its icon** and clears its text when folded away, so
  putting it back never leaves an invisible filter running.

### Scope has a third option

**All families (not placed)** lists every type loaded in the project,
including ones with no elements placed. It overrides the "include unused
types" setting rather than quietly obeying it, since that is the whole point
of picking it.

### Place Instance

Picking a single loadable type lights up **Place Instance** in the footer. It
calls `PostRequestForElementTypePlacement`, which is the only way to hand over
Revit's normal placement - snapping, hosting, the options bar - rather than a
reimplementation of it.

- The symbol is **activated first**, in its own transaction. An unactivated
  symbol cannot be placed and the request is refused with nothing said.
- It stays dark when several types are picked. Revit places one type at a
  time, so several is ambiguous, and guessing which one was meant is worse
  than a dark button.
- Staged changes are pointed out before handing over, because the window stops
  being the thing in front of you and they would be easy to forget.

### Editing from the window

Double click a cell, or right click it and choose Rename / Edit value, and
type. **Nothing is written until Apply.**

- Staged values show **in orange and semibold** in the cell, in place of the
  model value, with a bar above the footer counting them and carrying Discard
  and Apply.
- Edits are keyed on the **element**, not the row, so the same type edited from
  two places is one change rather than two.
- Category and Count are read out of the model rather than typed into it, so
  they are not editable. A family line's parameter cells are not editable
  either - "(varies)" has no single element behind it - and a system family has
  no family element to rename. The right click menu says which of those applies
  rather than just greying out.
- **Apply lists exactly what it is about to do first.** It then borrows the
  elements before opening the transaction, writes in one transaction with
  warnings deleted, and **reads every value back**.
- A parameter that lives on the instance rather than the type is written to
  every instance of that type.
- Typing a value back to what it already is clears the staged change rather
  than staging a no-op.
- A re-read drops staged edits and says so, rather than leaving them pointing
  at rows that no longer exist.

### Decisions worth remembering

- **A write to an element nobody has checked out writes nothing and says
  nothing.** Revit asks in a dialog, and a run that suppresses dialogs answers
  it - which reads exactly like Apply doing nothing. Elements are borrowed with
  `CheckoutElements` before the transaction starts, and element ownership and
  workset ownership are asked about separately, because an element on a workset
  somebody else owns has a perfectly clean checkout status.
- **A void API call is not evidence.** Neither `elem.Name = x` nor
  `Element.Name.SetValue` reliably raises when a rename does not take, and
  which route works varies with the IronPython engine, so the name is read
  back. Same for every parameter.
- **An exact string match is too strict for a number read back.** 2400 typed
  into a length comes back as "2400.0" or "2400 mm", so the check compares the
  first number in each rather than the text.
- **The DataGrid is read-only and every column is a template column**, so there
  is no in-place editor to lean on - and building one out of DataGrid editing
  templates in IronPython is a great deal of machinery for a text box. The
  editor is a small themed popup over the cell instead.

### Bench

`bench_logic.py` up to **107 checks**, adding the write helpers - a read-only
parameter, a parameter the element does not carry, a write that silently does
not take, a rename Revit refuses silently, a blank name, reformatted numbers -
and the edit rules, including that the same type staged from two rows is one
edit. All 16 `import_check.py` rules still catch their own breakage.

## 1.1.0

Four things asked for after the first run on a real model.

### Family names were coming out as "(unnamed)"

`element.Name` does not reliably hand back a string through IronPython: on
some engines, and on some element classes that hide the property, it comes
back as the bound property object instead. It never raised, so the try/except
around it never fired, and every type fell through to the fallback.

- `type_name_of` and `family_name_of` check the result **is text** before
  accepting it, and try `ElementType.FamilyName`, then `element.Family`, then
  the built-in name parameters (`SYMBOL_NAME_PARAM`, `ALL_MODEL_TYPE_NAME`,
  `SYMBOL_FAMILY_NAME_PARAM`), then `Element.Name` reached through the class -
  which is the route that works where the instance property does not.
- Where every route refuses, the row shows the family name and carries a note
  saying so, rather than "(unnamed)", which told nobody anything.
- Bench-tested against an element whose `Name` comes back as something that is
  not a string, which is the exact shape of the bug.

### The parameter picker searches, and only offers what fits

- The column heading's ComboBox is replaced by a chip that opens a popup with
  a **keyword search box** over the list - the same shape as the category
  picker. On a real job the list runs to hundreds of names and a ComboBox
  gives no way to narrow it.
- The list is now **scoped to the categories on show**: a project parameter
  only appears where its binding actually covers one of them, and the rest is
  read off the elements themselves. A binding whose categories will not read
  is offered rather than hidden, so a parameter is never lost to a failure to
  read it.
- Parameters already used as a column are left out, so the same one cannot
  land in two columns.
- A search matching nothing says so and leaves the full list, rather than
  emptying the picker.

### Narrow windows, and a horizontal scrollbar with the first column frozen

- Window minimum width drops from 820px to **360px**.
- The grid gets `FrozenColumnCount="1"` and a horizontal scrollbar. Every
  column but the first is now sized in **pixels** rather than stars: star
  columns share out whatever the grid has and so can never overflow it, which
  is why there was no horizontal bar before. Family and type stays star-sized,
  so it takes the slack on a wide window and stops at its minimum on a narrow
  one.
- The toolbar is a `WrapPanel`, so its groups wrap onto another line instead
  of clipping off the right hand edge.
- The footer label, the dock chips and the version drop out below set widths,
  and the two Select buttons shorten to "Project" and "View".

### Revit's own dockable pane

The window can now dock into Revit the way Project Browser does - tabbed in
beside it, remembered between sessions, and resized by Revit's own splitters.

- `RegisterDockablePane` can only be called during `OnStartup`, which a
  pyRevit pushbutton never reaches. pyRevit's extension-level `startup.py`
  **is** that moment, so the pane is registered from there. A new `startup.py`
  ships at the root of the extension with the registration in a clearly
  banded block, to be pasted into an existing one rather than overwriting it.
- The layout is split: `FamilyViewerBody.xaml` holds the toolbar, list and
  footer and is hosted either by the floating window or by the pane;
  `FamilyViewer.xaml` is now the chrome around it. One body, two hosts, so the
  two cannot drift apart.
- The pane registers with an **empty host Grid parked in the AppDomain**,
  because pyRevit runs `startup.py` and a pushbutton in different engines: a
  .NET object crosses that line safely, an IronPython one does not.
- **Open in** is a setting - the pane or a floating window. The floating
  window carries a "Revit pane" chip that moves it across, and says plainly
  why it cannot when `startup.py` has not run.
- Where the pane is not registered, the tool falls back to the floating
  window, which keeps its own edge-snapping and is a complete tool rather than
  a degraded one.

### Bench

- Sixteenth rule: **`late_imports_namespaced`**. A .NET import inside a
  function is checked against the same namespace table as a top-level one.
  `modules_load` only executes what runs at import time, so a mis-namespaced
  import inside a function - and worse, inside a try/except, which is where
  the awkward ones live - is never reached by it. It is not a loud failure
  either; it is swallowed and the feature simply never works.
- All 16 rules caught their own breakage under `--selftest`. Two selftest
  breakages were themselves found to be no-ops after the layout split and
  were repointed - the selftest reports a breakage that changed nothing as a
  broken test rather than a passing rule.
- `bench_logic.py` up to **84 checks**, adding the name readers and the
  category scoping of the parameter list.

## 1.0.0

First release.

### The list

- Every family in the project down the page, grouped **family then type**,
  with the family image in the left column beside the family name and its
  types listed under it until the next family.
- **Count** column reporting how many elements of that type are in the project
  (or in the active view when the scope is set that way). The family line
  carries the sum of the type lines under it, and always agrees with them.
- Chevron, double click, **Expand all** and **Collapse all** open and shut a
  family.
- Every heading carries a keyword search box and an Excel style tick filter;
  a search box above the list searches all of them at once. Clicking a heading
  sorts by it.

### Filters

- **Category** multi-select, with its own search box and All / None. Only
  categories that actually have a type in this project are offered, each with
  how many types it has.
- **Scope**: entire project (default) or active view.
- **Phase**: every phase, or one phase counted either as what was *created* in
  it or as what *stands* in it. Elements carrying no phase at all are left out
  when a phase is chosen, and the status line says how many.

### Parameter columns

- **+** adds a parameter column; each column's own picker carries `(none)` to
  clear it and `(remove this column)` to take it away. The set is saved as a
  pipe separated `columns` setting and survives between sessions.
- The parameter list is what is bound to those categories in the project,
  unioned with what the elements themselves carry.
- A parameter the type does not carry is read off the instances instead, in the
  same pass that does the counting. Where the instances disagree the cell reads
  `(varies)` rather than picking one at random.

### Selecting

- Pick families or types and the two footer buttons light up: **Entire
  Project** and **Active View**. Both select under the same rules the list
  used, so what is selected agrees with the Count column.
- Optionally zooms to the selection afterwards.

### The window

- Docks to the **left or right edge of Revit**, follows Revit when it moves or
  resizes, and floats free again from the same chips. Dragging the window to a
  screen edge snaps it there.
- Stretches by its own eight edge grips, goes full screen from the button, F11
  or a double click on the header, and remembers a dark or light palette.
- Modeless and owned by Revit's main window, so Revit stays fully navigable.

### Settings

- Behind the gear in the header. Scale (window scale and family image size),
  what goes in the list, the scope and phase it opens on, behaviour, and the
  docking numbers. Reset to defaults keeps the parameter columns.

### Under it

- `fv_clr.py` references every assembly and is imported first by every other
  module.
- `import_check.py` and `bench_logic.py` both run under plain CPython from the
  tool folder.
- Revit 2024 through 2027: no f-strings, no `print`, no `System.Uri`, no bare
  `ElementId.IntegerValue`.
