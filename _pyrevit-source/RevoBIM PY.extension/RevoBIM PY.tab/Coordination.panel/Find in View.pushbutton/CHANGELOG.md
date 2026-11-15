# Find in View - changelog

## 1.14.0

An optimisation pass. Nothing the tool does has changed; three things it does
often are now cheaper.

- **The "is it drawn in this view" check is narrowed by category inside
  Revit.** It was collecting every element in the view, unfiltered, and
  walking the lot in Python to find the handful selected. It runs on every
  launch with a selection - the zoom-here check - and again after every Show
  Me, so on a busy services plan that was tens of thousands of ids marshalled
  through IronPython to answer a question about five pipes. It is now
  filtered to the selection's own categories before anything crosses over.
  The answer is identical, because an element can only be drawn under its own
  category - and the bench proves both that the filter is applied and that the
  answer has not changed.
- **Each view row builds its search text and sort keys once.** Every
  keystroke in the search box filters and re-sorts every row, and both were
  being rebuilt from scratch each time - natural sort keys included, which
  split every name on its numbers. They are now made on first use and reused.
- **The level parameters are resolved once per session**, not with a dozen
  reflection lookups per element. Still late, inside a function, so a member a
  release does not have still cannot take the module down at import.
- Bench: six checks, 169 in total, and a sixteenth regression in the selftest
  for the view check going back to unfiltered - correct and slow, which is the
  kind of regression nothing else would notice.

## 1.13.0

**Shrink to the taskbar, on every window the tool opens** - the main window,
Find by ID and the message window. The control sits top right, before full
screen and close. Pressing it slides the window down like a drawer closing,
leaving only its own header bar floating above the taskbar so Revit can be
worked in; the control becomes a **green up arrow** that opens it again. The
answer to "I need to see the model" that does not involve closing a window
holding unapplied work.

- Built once, as a `WindowDrawer` in `fiv_ui`, and handed to every window
  class - which is what keeps the gesture identical between a window whose
  chrome comes from a layout file and one that builds its chrome in code.
- `Ctrl+Shift+H`, the shortcut the suite uses for this.
- **Eased by hand on a 15ms timer**, 280ms, `1-(1-p)^3`. A Storyboard on a
  borderless window's Top and Height fights the layout pass - and an animation
  that is never released leaves a window that can never be moved or resized
  again, with nothing raised to say so. There is no animation to release here.
- **MinHeight, SizeToContent and ResizeMode are all relaxed for the slide and
  put back on the way out.** Each of the first two vetoes a Height change on
  its own, and a vetoed slide leaves the window half shut for the rest of the
  session.
- **The body is pinned** to its current height for the length of the slide.
  Without that the grid re-measures on every frame, the view list realises and
  drops rows twenty times a second, and it reads as a window being squashed
  rather than a drawer being drawn away.
- **The resize grips are parked with the window.** The grip overlay spans every
  row, so left visible it lines the parked bar with invisible drag handles and
  swallows the click on the arrow that brings the window back.
- The body is hidden only once the bar has landed, and shown again before the
  slide back. A panel that was already hidden stays hidden.
- **While parked:** Escape, Enter and F11 all reopen rather than answering a
  prompt nobody can see or filling the screen with an invisible window; a
  double click on the bar reopens rather than maximising; the bar still drags,
  and a bar that has been carried somewhere else **opens upward from where it
  now sits**.
- Bars stack 4px apart and a freed slot is reused, so a dialog parked over the
  main window does not land on top of it.
- Closing while parked puts the window back first, so the remembered size is
  the real one rather than a 60 pixel sliver.
- A frame that throws still lands the window, rather than leaving it half shut.
- Bench: a nineteenth rule, **every window shrinks to the taskbar**, which
  fails on a window with no drawer, a button drawn but never wired, a MinHeight
  left clamped or a body never unpinned. Thirteen checks on the arithmetic,
  including a second monitor above the primary one, where a negative work area
  top is what sends the bar to the wrong screen. 163 in total, plus two more
  regressions in the selftest - a bar measured from zero instead of its own
  screen, and a reopen that forgets the bar height.

## 1.12.0

- **Run it on a selection that is already drawn in the view you are in and it
  just zooms, there, with no window at all.** Opening a dialog to ask which
  view to go to, when the answer is "this one", is the long way round.
- Whether the elements are really drawn there is decided with a **view scoped
  collector**, the same honest test the tool uses everywhere else, so the crop
  region, a view filter, the phase, worksets, design options and the view
  range are all accounted for. A category switched off in V/G means it is not
  drawn, so the window opens and the view can be picked properly.
- **Part of the selection being here opens the window**, which is the point:
  four pipes on this level and one on the next is exactly when the view list is
  what you wanted. `zoom_here_needs_all=0` in the settings file zooms to the
  ones that are here instead.
- A view that cannot show model elements - a sheet, schedule, legend or
  drafting view - always opens the window.
- The zoom is the same one Show Me does, including reading the visible
  rectangle back and retrying where Revit will not hold it. If it will not
  hold, that is reported rather than the window opening as though the elements
  were somewhere else.
- **Only a selection made before the tool ran takes the shortcut.** Elements
  found through Find by ID always open the window, because asking for the tool
  and being given a zoom is not what was asked for.
- A tick box in the window, **If it is already in the view I am in, just zoom
  to it**, on by default and remembered - so the behaviour can be turned off
  from the window it skips.
- Bench: seven checks on the decision, 150 in total, plus a thirteenth
  regression in the selftest for the shortcut firing on a partial match.

## 1.11.1

- **Skipping Find by ID leaves the caret in the element id box** in the main
  window, ready to type an id. With a selection it goes to the view search, as
  before.

**And two fixes that should have shipped earlier.** Rebuilding the working
folder from the last release showed that two edits had never reached the
window code:

- **1.7.0's remembered view** was still being matched by **name only**. Matching
  by id first, and the note saying the view is hidden by the view types or the
  search, were both missing. Name matching plus the scroll on open did work,
  which is why it looked right. Both are in now.
- **1.6.0's tiling hint** still described the 1.5.0 rule - "Tile Views is only
  used if Revit does not leave the windows side by side" - when the tool had
  stopped doing that. The hint now says what actually happens: the layout is
  left alone whenever more than one view is open.

The cause was the editing method, not the code: a scripted find-and-replace
that does nothing, silently, when the text it looks for does not match
exactly. Two fixes:

- Every edit now goes through a strict helper that **fails loudly** unless its
  target matches exactly once.
- A new bench rule, **every shipped feature is actually wired**, lists each
  feature the changelog claims beside the call site that makes it real, and
  fails if any call site is missing. A function that exists but is never
  called passes every other rule and ships nothing. Proved by breaking it.
- Bench: 18 rules, and two checks on where the caret goes. 143 in total.

## 1.11.0

- **The selection's properties are shown in the window**, under the selection
  summary: **Level** first and in orange, then Category, Type and Id. Several
  elements get a breakdown of the levels instead - "L01 (3), L02 (2)", most
  used first - because twenty rows of the same value is not information.
- **The level is worked out per category, not from one parameter.** It lives
  somewhere different for nearly everything: `RBS_START_LEVEL_PARAM` on ducts,
  pipes, trays and conduit, `FAMILY_LEVEL_PARAM` on family instances,
  `SCHEDULE_LEVEL_PARAM`, `WALL_BASE_CONSTRAINT` and half a dozen more. The
  list is tried in order, then by parameter name, then the host's level.
- Where nothing says, the **nearest level below** the element stands in - the
  level below, because something 2.4m above L01 is on L01 rather than nearly
  on L02 - and the panel says it was worked out from the elevation rather than
  read. A derived answer presented as a read one is worse than no answer.
- Every `BuiltInParameter` member is looked up late, by name, so one that does
  not exist on a given release cannot take the module down at import.
- The panel follows the selection, so finding an element by id in the tool
  updates it.
- Bench: thirteen checks on the level rules - which level a point belongs to, a
  basement and a roof, an unordered level list, the counts and their tie
  break, and reading the parameter a pipe actually uses. 140 in total.

## 1.10.0

**Switch the category on if the view has it off.** A tick box in the window, on
by default and remembered. Where the view about to open has the selection's
category switched off in Visibility/Graphics, or the elements hidden one at a
time, it is turned back on so there is something to see.

- **Temporary view properties where the view has a view template.** Revit's own
  temporary mode is "apply this template temporarily", so a view with no
  template has nothing to enter the mode with. There the change is made to the
  view itself, in **one transaction**, so a single undo puts it back - and the
  run says which of the two happened rather than leaving it to be discovered.
- Elements hidden individually in the view come back with `UnhideElements`.
- **The write is proved.** The categories are read back afterwards; one that is
  still off is reported, usually because a view template controls it. Revit
  does not reliably raise when a write does not take.
- A category the view will not let anything switch is reported by name rather
  than failing silently. The view is checked out first, so a view somebody else
  has does not fail halfway through.
- **After the view opens, anything it still does not draw is counted and
  named.** Switching a category on does not fix a view filter, the crop region,
  the phase, a closed workset, a design option or the view range, and saying so
  beats leaving an empty looking view unexplained.
- The order is not a preference: a transaction has to be closed before the
  active view can change, so the visibility is fixed **before** the view is
  activated. This is the first thing the tool has ever written to the model,
  and it only writes when something is actually hidden.
- Bench: twelve checks on which mode is chosen, on finding a hidden category,
  and on what is reported afterwards, plus an eleventh regression in the
  selftest for writing to the view when nothing is hidden. 128 in total.

## 1.9.0

- **Skip, just open the views.** A button on the Find by ID window that goes
  straight to the view list with nothing selected. Show Me still opens the
  view; there is simply nothing to frame it on, and the tool says so rather
  than reporting the missing zoom as a problem.
- **A Select element by id box inside the tool**, under the selection summary:
  type an id, press Find (or Enter), and the element is selected in Revit -
  so its properties are showing - **and** becomes the selection Show Me will
  zoom to. Those being two different things is exactly the confusion worth
  avoiding.
- Ids not in the model are named, the same way the Find by ID window does it,
  and a Find that turns up nothing leaves the previous selection alone rather
  than emptying it.
- The selection summary, the footer count and the Show Me line all follow the
  new selection.
- The zoom now uses the selection the window **ended up with** rather than the
  one it opened with, which is what makes the id box work at all.
- Revit is blocked for input while the tool is open, so the properties palette
  updates behind the window rather than being clickable. Drag the tool aside
  to read it, or press Show Me and read it in the view.
- Bench: four checks on the selection changing by id agreeing with a selection
  made in Revit, 116 in total.

## 1.8.0

**Find by ID.** Running the tool with nothing selected used to say "nothing is
selected" and stop. It now opens a small window in the shape of Revit's own
Select Elements by ID: type the ids, press Find, and the elements are selected
in the model and handed straight to the view list.

- Semicolons separate ids, the way Revit's dialog says - and so do commas,
  spaces and new lines, because that is what actually gets pasted.
- The same id typed twice is looked up once.
- **Element unique ids work too**, which Revit's own dialog will not take, and
  which is what comes out of a coordination report.
- Ids not in this model are **named** rather than counted, and where some were
  found the run carries on with those. None found at all keeps the window open
  with the reason, rather than closing and leaving nothing to show for it.
- `ElementId` takes an Int32 up to Revit 2025 and an Int64 from 2026, and which
  one an IronPython int binds to varies - both are tried before a token is
  called a miss.
- Ctrl+Enter presses Find, Escape closes.

**The easter egg is wired in.** Three slow clicks on the RevoBIM logo, on every
window the tool has - the main window, the Find by ID window and the message
window, which has grown a logo of its own so it has something to click.

- The egg is reached at the shared `lib/revobim/egg`, found by walking up from
  the button folder to the extension root. **Nothing egg related ships with
  this tool** - it only wires its own logo to the one copy.
- Slow is the point: a gap shorter than 250ms is a double click and starts the
  count again, and a gap longer than two seconds is a new attempt.
- The click is taken on `PreviewMouseLeftButtonDown` and marked handled. The
  header bar's own handler starts a `DragMove`, which captures the mouse, and a
  captured mouse never delivers the button up the count would need.
- Bench: a seventeenth rule that every window carrying the logo wires it, which
  also loads the extension's own `egg_rule.py` from `lib/revobim/egg` and runs
  it where the extension is installed beside the bench. Six checks on the click
  timing and nine on typing ids: 112 in total.

## 1.7.0

- **The list opens on the view you used last**, selected and **scrolled to**.
  It was already being re-selected, but selecting a row does not scroll to it,
  so on a project with a few hundred views the selection was somewhere off the
  bottom of the list and invisible.
- The scroll runs again once the window is up, because the first read of the
  model happens before the grid is in a visual tree and a DataGrid will not
  scroll to a row it has not laid out yet.
- **The view is remembered by id as well as by name.** The id survives a
  rename; the name survives a model rebuilt from a template, where every id
  has moved but the views are the same views. The id is tried first.
- Where the remembered view is in the project but **hidden by the view types
  or the search**, the line under the list says so by name, rather than
  leaving an empty selection looking arbitrary.
- The search box takes the caret when the window opens, since typing is the
  usual next move.
- Bench: six checks on finding the view used last, 97 in total.

## 1.6.0

**Tile Views is now used in exactly one situation**: the view you came from is
the only window open. Any time Revit already has a second view window up, that
arrangement is the user's and the tool leaves it alone - it opens into the
layout rather than re-laying it out. Where Revit is tiled, the first tile that
is neither the one you came from nor the one you want is still closed so the
view takes its place and the window count holds.

**The zoom now proves it landed.** `ZoomAndCenterRectangle` raises nothing when
it does not take, and Revit does its own framing when it opens a window - so a
call that returned was never evidence that anything moved, which is why a newly
opened view could come up showing the whole model.

- After every zoom the visible rectangle is read back with
  `UIView.GetZoomCorners`, projected into the view's own frame, and compared
  with what was asked for: the selection has to be in the middle of the view,
  and the view must be showing neither more than about four times the
  selection nor less than the selection itself.
- Where it did not take, the view is refreshed, the `UIView` is looked up
  again and the zoom is repeated - three times by default (`zoom_attempts`).
  A window Revit has only just created usually holds it on the second go.
- Where it still will not hold, the message says **what the view is actually
  showing** - "about 30 times the selection", "cutting the selection off" -
  rather than reporting success.
- A view that will not report its corners at all is taken at face value after
  one attempt rather than retried pointlessly.
- Bench: seven checks on the framing test and five on the retry, 91 in total.

## 1.5.0

**Tile Views is now the last resort rather than the first move.** It is a
posted command that re-lays out every window and runs after this one ends,
which is what made the zoom approximate - so it is only used where there is no
arrangement worth keeping.

Three routes, in order of preference:

1. **The view is already open in its own tile** - it is simply brought
   forward, exactly where it is. Nothing closes, nothing re-tiles, no posted
   command, and the zoom is exact because nothing is about to resize. This is
   the good case and the one to aim for.
2. **Revit is tiled and the view is not open** - the first tile that is
   neither the one you came from nor the one you want is closed and the view
   opens in its place, keeping the window count. The layout is then **looked
   at again**: where Revit has left the windows side by side, nothing further
   happens. Tile Views is only posted if the new window landed over the
   others.
3. **The view you came from is the only window open** - there is nothing to
   preserve, so Tile Views is posted, as before.

- The line under the tick box now names which of the three will happen, and it
  updates as views are picked in the list, since it depends on whether the one
  highlighted is already open.
- The tile allowance on the zoom is only applied where a re-tile is genuinely
  going to happen, which is now decided **before** the zoom rather than
  assumed.
- Bench: the tiling checks reworked onto the three modes, plus the
  after-the-fact layout judgement, and a sixth regression in the selftest for
  tiling regardless. 78 in total.

## 1.4.1

Fixes "Revit would not take the Tile Windows command".

- **Every route to the command is tried**, not one. Four spellings of the
  `PostableCommand` member (`TileWindows`, `TileViews`, `Tile`, `TileWindow`)
  and four of Revit's own command ids (`ID_WINDOW_TILE` and friends). The
  member name has moved across releases and one guess was not enough.
- **`CanPostCommand` is no longer used as a gate**, only read for the report.
  Tile is greyed out while a single view window is open, and Revit does not
  necessarily create the second window until the current command ends - so the
  honest answer at the moment of asking can be "no" for a command that will be
  perfectly postable by the time it runs. This is the likeliest cause of the
  message. The post is now attempted regardless and only a throw counts as a
  failure.
- **The message says what was tried and what each route said**, rather than
  just that Revit said no - so a release that needs a fifth name can be fixed
  from what the message reports.
- It also names the menu item correctly (View > Tile Views, WT) and says how to
  turn the warning off: `warn_tile_failure=0` in
  `%APPDATA%\RevoBIM\find_in_view.txt`.
- The view still opens beside the one you came from either way. Only the
  layout is missing.
- Bench: nine checks on the posting, including one that fails if
  `CanPostCommand` is ever used as a gate again. 75 in total.

## 1.4.0

- **Open beside the view I came from.** A tick box in the window, remembered.
  With it on, the view you started in stays open and Revit tiles the two side
  by side.
- **If Revit is already tiled**, the first tile that is neither the one you
  came from nor the one you are opening is closed first, so the window count
  stays the same rather than growing a tile every run. "First" is the top left
  one, read down the page then across. Turn `reuse_tile` off in the settings
  file to add a tile instead.
- **A view already open beside the host is left exactly where it is** - no
  close, no re-tile - which also means its zoom is exact, because nothing is
  about to resize.
- The elements stay selected in the new view, as they did before. Revit's
  selection is per document rather than per window, so they highlight in both
  panes.
- The zoom is widened by a **tile allowance** (35% by default) when a re-tile
  is coming, because Revit's Tile Windows can only be **posted** and therefore
  runs after the zoom, shrinking the window the zoom was measured for.
- **There is no API that puts a view in a chosen pane.** `TileWindows` is
  Revit's own command and it arranges the windows itself; all the tool can do
  is control which windows are open before it runs. If Revit refuses the
  command the run says so and names the menu item.
- Bench: sixteen checks on the tiling rules, 66 in total.

## 1.3.0

- **The zoom now really fits around the selection.** The rectangle handed to
  `ZoomAndCenterRectangle` is worked out from all **eight** corners of the
  element box projected into the **view's own right/up frame**, not from two
  opposite corners of a model axis aligned box. The old way only spanned the
  right rectangle when the view happened to look down a model axis; on a
  section cut at an angle or a rotated 3D view those two corners project well
  inside the real extent and the zoom cut the selection off.
- The padding is applied in the view frame too, so it is a share of what is
  actually on screen rather than of the model box. A tall riser no longer pads
  a plan view by a share of its height.
- **A view that was not already open now zooms.** The `UIDocument` the command
  starts with has an open view list built before the view was activated, so
  `GetOpenUIViews` never contained the new one and the run fell through to
  `ShowElements` every time. Asking `UIApplication.ActiveUIDocument` again
  picks it up. `ShowElements` stays as the last resort.
- Default padding is **15%** rather than 25%: with the framing fixed, 25 read
  as zoomed out.
- Bench: six checks on the zoom rectangle, including one that proves the old
  two corner rectangle really was too small, so the fix is not just asserted.
  50 in total, and a fourth regression in the selftest.

## 1.2.0

- **The three content filters are gone**, and the per view scan behind them
  with them: "only views showing the selected categories", "only views these
  elements appear in" and "only views placed on a sheet". A view scoped
  collector per view is an honest answer to an expensive question, and on a
  real project the wait was not worth what it bought.
- The confirm added in 1.1.0 goes with them.
- The **Selected here** column and the progress band go too - both existed only
  to report the scan.
- **Nothing the window does now reads the document.** Everything is read once
  on open and every filter is a set membership or a string match, so the list
  reacts as fast as it can be typed at.
- The **Sheet** column stays: it is read in one pass with the views, so
  searching or sorting on it costs nothing and still answers "is this one on a
  sheet".
- `only_categories`, `only_elements`, `sheeted_only` and `scan_limit` are no
  longer settings. A settings file written by an older version still loads;
  the removed keys are ignored the way any unknown key is.
- Bench: 44 checks, reworked onto what is left, plus three regressions the
  selftest still catches.

## 1.1.0

- **"Only views these elements appear in" asks first.** Ticking it raises a
  themed Yes/No saying the scan looks inside every view in the project and can
  take some time on a large model. A no un-ticks the box and nothing runs.
- The question is only asked while there is still a wait to warn about. Once
  the scan has run its answer is cached, so ticking the box costs nothing and
  the warning would be a lie.
- **The tick always starts off and is never remembered.** It is the slowest
  thing the tool does, and a tick left on last week must not be sitting there
  waiting to scan the moment the window opens. Every other choice is still
  remembered.
- The confirm is owned by the tool's own window rather than by Revit, so it
  cannot open behind it and read as a hang.
- Bench: three more checks covering what is remembered and what is not, 57 in
  total.

## 1.0.0

First release.

- Runs off whatever is selected in the model. Nothing selected is reported in
  a themed window rather than a silent return.
- Lists every view the tool can open and zoom: floor, ceiling, structural and
  area plans, sections, elevations, detail views, 3D views and walkthroughs.
  Drafting views, legends, schedules, sheets and renderings are left out
  because they cannot show model elements.
- Per view type tick boxes with their own search box and All / None, plus a
  keyword search over view name, type, sheet and scale.
- "Only views showing the selected categories" runs a view scoped collector per
  view, so crops, view filters, phasing, worksets and design options are all
  accounted for. A cheap Visibility/Graphics pre check skips views where every
  selected category is switched off.
- "Only views these elements appear in" is the stricter version of the same
  scan, and the **Selected here** column reports the count per view in green.
- "Only views placed on a sheet" filters on the sheet map, read in one pass.
- Show Me is grey until a view is picked and green the moment there is one to
  go to. It opens the view, re-selects the elements and zooms to their combined
  extent with 25% padding, never less than 300mm.
- Dark and light palette, resize grips, full screen (button, F11, double click
  the header), version top right.
- Every choice is remembered in `%APPDATA%\RevoBIM\find_in_view.txt`: theme,
  ticked view types, all three filter ticks, window size, splitter position and
  the last view picked.
- `import_check.py` and `bench_logic.py` ship beside the tool, both with a
  `--selftest`.
