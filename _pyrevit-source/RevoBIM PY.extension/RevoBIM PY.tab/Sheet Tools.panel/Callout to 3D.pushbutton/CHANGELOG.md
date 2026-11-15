# Callout to 3D - changelog

## 2.7.0

**Settings in boxes**

- The settings along the top of each group are gathered into captioned boxes
  of settings that belong together:
  - *Callout selection* - **Show** (the Views box and the filters) and
    **Find** (search, Tick all, None);
  - *Section array* - **Section views**, **Cuts**, **Section reach**,
    **3D section box**, **Scales**, **Annotation**;
  - *Sheet settings and naming* - **Sheet**, **Numbering and naming**,
    **Viewports**.
  Every control has its label above it.

**Which views are listed**

- A **Views** dropdown at the top of Callout selection: *Callouts only* (the
  default), *Callouts and floor plans*, *Floor plans only*. It replaces the
  *Every cropped view* tick.
- **A new way to tell a callout from a plan.** A callout is drawn in its
  parent view as a marker carrying its name; a section has a marker too, but
  its view is a section. So a plan that has a marker anywhere is a callout,
  and one that does not is not. This route runs first, is fast, and finds the
  callouts on this model whatever their view family type is called - before,
  its callouts were only found by the type name, or else by listing every
  cropped plan. The Cut in column is filled from the view the marker sits in.
- A floor plan that is not a callout says so in the status column.
- *Read the view markers* can be turned off in Settings > Finding callouts.

Bench: 573 checks.

## 2.6.1

- Each viewport type dropdown in Sheet settings has its own label above it -
  *Callout*, *3D view*, *Sections* - under one *Viewport types* heading.

## 2.6.0

**Section array**

- **Drag a cut line to move that section** - an X cut up and down, a Y cut
  left and right - on the callout the preview is showing. A dashed ghost line
  follows the mouse; let go and the section is cut there. A click still turns
  it round; a right click puts it back on the even spacing. Moved cuts are
  dashed and marked with *. Kept as a fraction of the callout's span, so a
  nudged crop keeps them in proportion, and held clear of the crop edge.
- **Crop grids to the view**, on by default: every grid in each new section is
  cut down to the top and bottom of the section's crop. The ends go 2D in that
  section only, and each end keeps its own side, so the bubbles stay where
  they were. A grid that will not take it (pinned, or held by a scope box) is
  counted and said. *Stop the grid ends this far inside the crop* is in
  Settings.
- Dragged cuts and single-section flips now survive a Refresh.

**Sheet settings**

- **Viewport types for the callout, the 3D and the sections** in the strip -
  the title header each is placed with, red while on Revit's default.
- **Title gap**: each viewport's title is pulled up to this far under the base
  of its view (2mm by default), level with its left edge, before the views are
  measured and laid out. Empty leaves the titles where Revit puts them. The
  move is worked out from where the title actually is, not from what
  `LabelOffset` is measured against.

Bench: 563 checks.

## 2.5.1

- **Fixed: views landed off the title block.** The layout was worked out from
  the sheet's 0,0 as if that were the paper's bottom left corner. Revit puts a
  title block family's own origin at 0,0, and the BGL title blocks - like many
  - are not drawn from their bottom left, so every viewport sat up and to the
  side of the paper. The frame is now read off the title block placed on the
  sheet (its box in the sheet's own coordinates), then the sheet outline, and
  the layout, the margins and any custom setout all start from that corner.
  The log records where each title block was found.
- A custom setout is checked for fit after its boxes are moved, so a setout
  dragged clear of the bottom no longer reports MANUAL REVIEW, and one dragged
  off the paper still does.
- Bench: 544 checks.

## 2.5.0

**3D section box**

- **Crop offset, top offset and bottom offset** for the 3D's section box, in
  the Section array strip: how far the box reaches past the callout's crop on
  every side, where its top sits relative to the top of the band (negative is
  down), and how far below the bottom it starts.
- **The top defaults to 200mm below the top**, and a saved top offset is
  reset to it once.
- **The offsets now apply to the view range as well.** Before, they only
  moved the box on the level rule; on the default (the callout's own view
  range) the box was the view range exactly. The sections start from the same
  band, so they move with it, and their own below / above offsets still add on.

**Selection**

- A callout marker picked in a view is now matched by the name it carries
  whatever its category reports - the category lookup was the weak link -
  and by the view stored next to it where Revit keeps one.
- **Refresh picks up a new selection**: select callouts in the browser or the
  view with the window open, press Refresh, and the table narrows to them.
- Any number of views and markers can be selected together.

Bench: 535 checks.

## 2.4.0

- **Scale for the callout, the 3D and the sections**, side by side in the
  Section array strip. Each is only applied where that view's template leaves
  the scale unlocked; where the template holds it, the template wins and the
  results name it, once per kind per run.
- **Callout:** left on the default it keeps its own scale, as before. Set, it
  rescales the callout view itself (or its duplicate, when the callout was
  already on a sheet and *duplicate* is chosen) - that is an existing view, so
  it is only touched when asked.
- **3D and sections:** left on the default they follow the other views
  (`view_scale_rule`), as before.
- The sheet preview sizes the plan, the 3D and the section boxes at their own
  scales, and the confirm step lists any scale that was set.
- Bench: 530 checks.

## 2.3.0

- **Open the tool with callouts selected and the table shows only those.**
  Select them in the project browser, or click their markers in a plan, then
  press the button: the table opens narrowed to them, ticked, with a
  *Selected in Revit (n)* box in the Callout selection strip. Untick it to see
  the rest. A selected viewport counts as the view it shows, and a selected
  sheet as every callout placed on it.
- Selected callouts are shown **even if they are already on a sheet** - they
  were picked on purpose, so *Not on a sheet* does not hide them while the
  selection filter is on.
- If nothing selected is a callout the tool found, everything is shown as
  before and the status line says so.
- A callout marker picked in a view is a Viewer element rather than the view
  it opens, so it is matched by the view's name; everything else by id.
- Bench: 520 checks (selection by id, by name, through a viewport and a sheet,
  and nothing selected).

## 2.2.0

**Groups**

- **Section array and Sheet settings and naming start folded**; only Callout
  selection is open. Settings saved by 2.1.0 are not carried forward on this
  one key, so the change shows on first open.
- **Headers stay in sight.** Scroll a group's header off the top and a copy of
  it docks at the top of the window; one below what is on show docks at the
  bottom. Each carries its group's summary.
- **Click a docked header to open that group full** - it opens at once, its
  main panel grows to fill the window, and it scrolls to the top.

**Window**

- **Double click the top or bottom edge** to stretch the window to the full
  height of the screen it is on; double click again to put it back. On every
  window the tool opens.

**Dropdowns**

- **A dropdown left on its default is outlined red**; once something
  specific is picked it is outlined green with green bold text. Every dropdown
  with a default entry, in the main window and in Settings. The marking is in
  `fill_combo` itself, and a bench rule keeps it there.

**Section array**

- **Section scale.** Pick the sections' own scale, or leave it on the default
  to follow the other views. It is only applied where the section's view
  template leaves the scale unlocked; where the template holds it, the
  template wins and the results say which template did. The preview sizes the
  section boxes at that scale.

**Sheet settings**

- **The title block fills the placement preview**, drawn to scale. Its size is
  read off a placed title block of the type the sheet will use; until one has
  been placed it falls back to the ISO size, and the caption says so.
- **Drag a box and the layout becomes a Custom setout** - a fifth card in the
  cycler, dashed, named after the layout it was dragged from. It is saved, and
  used for **every** sheet the run makes, each real viewport centred where its
  box was left. Right click a box to put it back; *Clear the custom setout*
  returns to the layout it started from. In 2.1.0 a move belonged to one
  callout and was forgotten on refresh.

**Bench**

- `defaults_marked`: 28 rules, each caught by its own breakage.
- 509 logic checks: scales read and written, the section scale in the
  preview, the custom setout through the settings file and back to the run,
  docked header sides, the full-height panel, the tall-window toggle and the
  default test.

## 2.1.0

One button, one window. Everything is in the main window, stacked into three
groups that slide open and shut, with the settings for each group along its
top; the gear in the header opens the full Settings for everything else.

**Before installing:** delete the old `Callout to 3D.pulldown` folder (it held
the Callout Settings button) from `Sheet Tools.panel`. A zip merge cannot
remove a folder, and the old and new buttons share names.

**One button**

- The `Callout to 3D.pulldown` with its separate *Callout Settings* button is
  gone. The tool is a single `Callout to 3D.pushbutton`.
- **Settings is a gear icon** in the top right of the header, beside the
  dark/light chip.

**Three stacked groups**

- **Callout selection** - search, Tick all / None, *Not on a sheet* and
  *Every cropped view* along the top; the table beneath.
- **Section array** - section **view family type** and **template** picked
  right there (picking a type offers its own template, as Settings does), the
  X and Y counts, cut depth, the new **below level / above top** offsets, the
  flips, **Tag rooms** with its tag type, and *Set on ticked rows*; the section
  preview and *What will be created* beneath.
- **Sheet settings and naming** - sheet size, the **numbering rule** (with its
  start number) and the **naming rule**, each with a live example under it
  that turns red and names any token nothing will fill; the layout cards and
  the sheet preview beneath.
- Click a header to fold its group away; it slides shut and its chevron turns.
  Each header says what the group is set to, so a folded group still reads.
  Which groups were open is remembered.
- Drag the strip under a group's panel to make it taller or shorter;
  remembered too.

**Sheet layouts**

- Four layouts, shown as cards drawn with this callout's own section counts,
  cycled with the arrows or picked by clicking: *plan top left, 3D top right*
  with X sections down the left and Y down the right (what 2.0 did);
  the **mirror** of that; **rows** - every section in rows under the plan and
  3D; and **plan left** - plan and 3D down the left, every section stacked on
  the right.
- **The sheet preview** draws the sheet to scale - paper, margins, title
  strip - with a box per viewport where the layout puts it, sized from the
  callout's crop, the band and the scale. Overlaps go red; anything that
  overflows is drawn below the paper with a red sill.
- **Drag a box to move it.** It snaps to a whole millimetre and stays on the
  paper. Right click a box to put it back; *Put every box back* resets the
  sheet. Moved boxes are dashed and marked with *.
- The run uses the same layout function as the preview, then centres each
  real, measured viewport where its box was left. A bench rule keeps the two
  on one function.

**Sections**

- **Below level and above top offsets** open the sections up past the band
  the 3D box uses - the slab, the ceiling void, the floor above - without the
  3D growing with them. The plan lists both bands when they differ.
- **Rooms are tagged.** Every room a new section cuts that has no tag in it
  yet gets one, with the project's default room tag unless one is picked. The
  tag sits in the middle of the cut, 1200mm above the floor (or half way up a
  shorter room), inside the crop. Rooms a section does not cut are left alone.
  If no room tag is loaded that is said once.

**Removed**

- The offer to play PacMan when a run starts.

**Bench**

- Three new rules: `no_bare_brace` (an attribute starting `{level}` is a
  markup extension to WPF and kills the window as it loads - the naming rule
  tooltips needed `{}` in front), `groups_wired`, `one_layout`. 27 rules, each
  caught by its own breakage.
- 485 logic checks (was 387): every layout has no overlaps and keeps every
  view, the cycler goes round, moves recentre at the measured size, the
  preview converts sheet and canvas both ways, the fold slides and lands at
  an automatic height, the naming examples and token warnings, the section
  offsets, and where a room tag goes.

## 2.0.0

A rebuild of the 1.x code after twenty-one rounds of patching: every module
audited, the dead and superseded code cut, the slow paths tightened, one
feature that never actually shipped finished, and the suite's shrink-to-taskbar
drawer added. Behaviour on the sheet is the same as 1.21.0 - X sections down
the left, Y down the right, the 3D top right - just reached with less work.

**Faster**

- **One regenerate per sheet instead of about four per viewport.** Placing a
  viewport used to regenerate before asking `CanAddViewToSheet`, again before
  moving it, and again before measuring it. Now every viewport is dropped,
  the document regenerates **once**, everything is measured, then everything
  is moved. Regenerate is the expensive call on a large workshared model, and a
  sheet with a plan, a 3D and five sections did it some twenty-eight times.
- **The section direction is learned once, not every run.** Every run on this
  model built its first section, read it back, found it facing the wrong way,
  deleted it and built it again - the log said so on every single run. The
  direction that works is now remembered (`sec_sign`), so that happens once.
- **One crop read per callout per refresh.** The crop region was read once to
  settle which level elevation is internal and again for the row. It is cached
  for the length of a read now.
- **The levels are read once per refresh**, not twice.
- **The crop disagreement note is said once per callout per session.** The
  same six lines went into the log on every open and every refresh, burying
  everything around them.

**Finished**

- **Picking a view family type offers its own template** - in Settings, with
  a tick to offer every template rather than only the matching kind. This was
  announced in 1.13.0 and never actually reached the window: half of that
  patch failed to apply, the keys and lists landed without the tick boxes or
  the wiring, and nothing noticed for eight versions.

**New**

- **Shrink to taskbar on every window** - the main window, Settings and every
  prompt. Top right, before full screen and close. The window slides down like
  a drawer leaving only its header floating above the taskbar, and the control
  turns into a green up arrow that opens it again; `Ctrl+Shift+H` does both.
  Parked, Escape, Enter and F11 bring it back rather than answering a prompt
  nobody can see, and a double click on the bar reopens rather than maximising.
  Carried somewhere else, it opens upward from where the bar now sits.
  Built to the theme reference: eased by hand on a timer (no animation to
  release), `MinHeight` and `SizeToContent` relaxed for the slide and put back,
  the body pinned so the table does not re-measure every frame, the grips
  parked, a dialog shrinking takes its owner down with it and brings it back
  when it closes, a dialog opening over a parked owner centres on the screen,
  and the shrink button **stays live during a run** - the body and the other
  header controls go deaf instead of the whole window.

**Cut**

- The old grid and row layouts (`sheet_layout`, `columns_for`, `pack_row`, the
  cell-overflow check) and their settings - `layout_top_row`,
  `layout_max_cols`, `layout_report_overflow` - none of which the two-column
  layout reads. Also `sec_top_fixed_mm` and `list_width`, read by nothing, and
  six helpers nothing called.
- Unused imports and variables throughout.
- Viewport placement is three small functions - `create_viewport`,
  `measure_viewport`, `move_viewport` - with named records in place of
  positional tuples, and the footprint arithmetic (box + title, and where it
  sits against the point that moves it) is a pure `footprint_mm` the bench
  proves.

**Bench** - **24 rules**, all proved by deliberate breakage, and **387 logic
checks**. New rules: `settings_have_readers` (every setting has something that
reads it, every Settings field names a real setting - the rule that would have
caught the template feature), `drawer_on_every_window`, `shrink_stays_live` and
`no_held_animation`. The drawer is benched through a fake timer that never ticks
inside `Start()` and records anything a tick lets escape; removing the tick's own
fallback fails it.

## 1.21.0

**Five sections asked for, four built - the band was not writing through.**

The debug report had it: the row carried `2 X, 2 Y` while the band said
otherwise. The counts lived on the rows, put there when the table was read, and
only **Set on ticked rows** ever moved them. Changing the steppers redrew the
preview and nothing else, so the preview showed one thing and the run built
another, with nothing saying they disagreed.

- **The band is the control, so it writes straight through.** Changing X, Y,
  the cut depth or the sheet size applies to whatever the band applies to -
  the ticked rows, or everything on show when nothing is ticked, which is the
  same rule the Create button uses, so the preview cannot describe a different
  set from the run.
- **Create applies it once more before building**, in case a box is still
  holding a keystroke that has not committed.
- **The confirm step names any row that disagrees** with the band and says its
  own counts will be used, rather than quietly building something else.
- The write-through is a plain function in `c3d_core`, out of WPF, so it is
  tested rather than clicked.

Bench: **376 checks**, including three X asked for landing on every row, five
sections asked for being five sections on the row, and setting the same values
twice moving nothing.

## 1.20.0

**The layout work of the last several versions was never running.**

`c3d_ops.py` had a **duplicated tail** - `push_sheet_name`, `Results`, `run`,
`_make_group` and `_place_group` each appeared twice. Python does not complain
about that: it runs the first definition, throws it away, and keeps the last.
The stale copy was last, so every placement change since the grid layout has
been sitting in the file looking correct while Revit ran the old code. It is
why nothing changed on the sheet, and why the log still carried the old grid's
"does not fit its 255 x 400mm cell" warnings from a code path that should no
longer exist.

- **The duplicate block is gone**, and with it the old grid placement, the old
  `run` and a `Results` that had no review list.
- **A bench rule now catches it**: nothing may be defined twice in one module,
  top level or inside a class, and it names both line numbers. This is the
  `no method defined twice` rule from the table reference, which this tool
  should have carried from the start - it is exactly the failure that reference
  describes, and it cost several rounds of "I can't see any change".

So v1.19.0's two-column layout - X down the left under the plan, Y down the
right under the 3D, the gap squeezed to fit, overflow below the sheet with the
sheet flagged - takes effect for the first time here.

Bench: **20 rules**, all proved by deliberate breakage, and **368 checks**.

## 1.19.0

**Two columns instead of rows.** The X sections go down the left of the sheet
under the plan and the Y sections down the right under the 3D, each stacked
below the last - which is the layout on the marked up sheet and, more to the
point, one that cannot put two viewports side by side at all.

- The columns are **as wide as whatever has to go in them**, so a section wider
  than the plan pushes the right hand column across rather than being sat on,
  and the 3D sits at the head of the right hand column so a Y section lines up
  under it.
- **The gap is squeezed to fit as many in as will go** - down to a floor of
  2mm and no further, and evenly rather than taking it all out of the last
  joint. The plan and the 3D sit hard against the top margin, so everything
  below them gets the whole of the rest of the sheet.
- **When they still will not fit they carry on below the sheet**, as asked, and
  **the sheet is flagged for a manual review**: the summary marks that sheet
  `*** NEEDS A MANUAL REVIEW ***` and lists it separately. Nothing is shrunk
  and nothing is dropped - a viewport scaled to fit is a scale nobody asked
  for, and a section quietly missing is worse than one hanging off the sheet.
- The old row packing and its `sections_beside_3d` setting are gone. A setting
  nothing reads is worse than no setting.

- Bench: **368 checks**, including two full of each with an overlap test across
  every pair, a section wider than the plan setting the column width, the gap
  squeezed evenly, six that overflow being reported and still not overlapping,
  and an empty column.

## 1.18.0

- **The overlap was the viewport label, which is not in the box outline.**
  `GetBoxOutline` gives the view's own box; the title underneath it - the name,
  the detail number and that long rule beside them - is a **separate outline**,
  and it is usually **wider than the view**. Measuring only the box makes every
  section look narrower than it prints, so its neighbour gets packed on top of
  the title. The two outlines are unioned now, and there is a **clear air**
  setting (4mm) padding every viewport on top of that.

  Version 1.17.0 fixed a related half of this - the outline's middle is not the
  point `SetBoxCenter` moves - and that fix still stands; it just was not
  measuring the whole footprint yet.

- **PacMan: the egg can be a window class, not a function.** A class named for
  the game is now found by its name, built, and **shown** - a call that hands a
  window back and is never shown succeeds and puts nothing on screen, which
  looks exactly like nothing having happened. Anything a call returns with a
  `Show` or `ShowDialog` is opened.
- **It says which call opened it.** The status line names the route -
  `revobim.egg.games.PacmanWindow`, or whatever it turns out to be - and the
  debug report carries the last route taken. "It started" and "something was
  called and nothing appeared" are otherwise the same thing from outside.

- Bench: **347 checks**, including an egg that exposes only a window class:
  found, built, shown with the owner reaching it, and the route reported.

## 1.17.0

**The sections were overlapping and sitting too far down the sheet, and both
were the same mistake.**

A viewport's title sits below and to the left of the view itself, so its
**outline reaches further that way than the other** and the middle of the
outline is not the point `SetBoxCenter` moves. The layout was worked out from
the outlines and then applied to the box centres, so every viewport landed out
by the width and height of its own title - down and to the left. Down, which is
the empty band under the plan; and to the left, which is why each section sat
on top of the one before it.

- **The offset between the outline's middle and the box centre is measured when
  the viewport is dropped**, and taken off again when it is moved. So a cell is
  now where the whole thing sits, title and all.
- **The sections start a fresh row directly under the plan and the 3D** and
  fill it left to right, wrapping onto as many rows as they need - which is
  what the marked up sheet asks for. Carrying on beside the 3D first is still
  there as a setting for when every scrap of width matters.

- Bench: **344 checks**, including two viewports packed side by side and then
  moved, which stay side by side rather than drifting into each other by the
  width of a title.

## 1.16.0

**PacMan would not start, and the launcher was not saying why.** It guessed
three module names, and if none of them imported it logged one line and gave
up - so a folder that was simply not on `sys.path` looked identical to a game
that had thrown.

- **The egg folder is found on disk** by walking up from the tool to the
  extension root and looking for `lib\revobim\egg`, and its `lib` is put on
  `sys.path` if it is not already there. That alone is the likeliest fix: an
  import of `revobim.egg` fails outright if `lib` was never added.
- **Every module in the folder is tried**, not three guessed names, and every
  plausibly named callable in each: the game's own name, `launch_pacman`,
  `play`, `show`, `launch`, `run`, `main`, `start`.
- **Which argument goes first depends on the name.** A function already named
  for the game - `pacman.show`, `launch_pacman` - does not want the game's name
  passed to it; the first thing it takes is the owner window. Handing it
  `"pacman"` as the owner *succeeds*, and then the game has a string where its
  window should be. Only a generically named entry is told which game to open.
  That was a real bug in the first version of this and the bench now proves it.
- **A game that will not start says what it tried.** The window shows the egg
  folder, whether `lib` was on the path, what the folder contains, whether both
  levels are proper packages, and every module with the callables it offers.
  The same block is in the debug report, and the full list of attempts goes to
  the log.

Bench: **338 checks**, including a stand-in extension laid out exactly like the
real one - the game found and started with the owner reaching it, a folder that
only carries `egg_hook.attach` reported as having nothing that opens a game, a
game that throws not counted as started, and no egg folder at all.

## 1.15.0

- **The debug panel is a tick box.** *Debug report* sits beside the other
  options in the section band, and when it is on the whole report opens in its
  own window as soon as the run finishes - the state of things at the moment
  the run happened, which is what is worth sending on. The text is selectable
  and there is a **Copy it all** button beside Close. The panel along the
  bottom of the main window is gone, so the table gets that height back.

- **The sections fill the space left beside the 3D** before starting a new
  row. Starting a fresh row underneath wasted whatever width was left, and on a
  tight sheet that is the difference between them fitting and not. They also
  sit at their **own smaller gap** - 6mm rather than the 12mm between the plan
  and the 3D - so they bunch up closer. Both are settings.

  When a row does fill, the next one starts below the **tallest thing on the
  row above**, not just below the section beside it, so nothing overlaps. Rows
  carry on past the bottom of the sheet rather than the last few being dropped,
  as asked.

- **A section that will not go on the sheet at all is now named.** Each
  viewport is also dropped on its own spot rather than every one landing on the
  same point, which is asking Revit to refuse one of them.

- **A prompt before a run:** *Would you like to play "PacMan while you wait?"*
  Yes opens the easter egg's PacMan. It is asked **before** the work is handed
  to Revit rather than after, because once Revit is working the window cannot
  put a dialog up until it has finished - which rather defeats the point of
  something to do while waiting. There is a setting to stop asking.

- Bench: **329 checks**, including packing that starts part way along a row -
  the space beside the 3D filled, the next row clearing the tallest thing above
  it, and an over-wide viewport wrapping once without taking its neighbour with
  it.

## 1.14.0

- **The 3D looks down on the callout instead of up at it.** The stand-off
  direction for each compass corner had a **negative** Z, which put the camera
  30 metres below the slab looking up through it. It is positive now, so the
  camera stands above the box on the side asked for and looks down. The four
  corners are unchanged otherwise - south east still stands east and south.
- **How far above is a setting.** *Looking down at this angle* in degrees,
  default **35** - the true isometric, where a cube's three visible faces come
  out equal. Steeper looks more from overhead, shallower more from the side,
  and it is clamped between 5 and 85 so it cannot be turned upside down again.

- Bench: **321 checks**, including that every one of the four corners stands
  the camera above the box, that the compass directions still point where they
  say, and that an absurd pitch is clamped rather than flipped.

## 1.13.0

- **The 3D crops itself round its section box before it goes anywhere.** The
  crop of a 3D view is measured in the view's own frame, and Revit hands that
  frame over on the crop box itself, so the eight corners of the section box
  are pushed back through it and the crop is set to what comes out - the tight
  rectangle round the box, whatever corner the view looks from. An uncropped 3D
  is as big as whatever Revit decides is visible, which is why it landed on the
  sheet at the wrong size.

  Four settings: crop tight round the box, how much air to leave (150mm),
  crop the view - which is "do not crop view" off - and show the crop region.

- **The sheet is laid out from what the viewports actually measure**, not from
  a grid worked out in advance. Only Revit knows how big a view prints, so
  every viewport is dropped first, measured, and moved into place afterwards.
  The callout goes top left, the **3D beside it at its own measured width** so
  it cannot land on top of the plan, and the sections are packed left to right
  underneath, **wrapping to a new row when the sheet runs out of width**. A row
  is as tall as its tallest viewport, so the next row clears it. Running off
  the bottom is allowed and reported, as asked - a viewport shrunk to fit is a
  scale nobody asked for.

- **The plus and minus were being squeezed out of existence.** The ghost button
  style pads 14px each side, so a 28px button had nothing left to draw a glyph
  in. The stepper and flip buttons carry no padding now, and the symbols show.

- **Section view templates: the full list.** A template filed under Detail or
  Elevation applies to a section perfectly well, so all three view types now
  count as section templates. **Picking a view family type offers that type's
  own default template** and leaves the box editable, and there is a tick for
  offering every template in the project regardless of kind. Both are settings.

- Bench: **304 checks**, including the packing - three that fit on a row, five
  that wrap, nine that run off the bottom, one wider than the sheet, and mixed
  heights - with an overlap test across every pair in every case.

## 1.12.0

**Everything was being built 88 metres above the building.** The debug report
had the whole of it:

    GenLevel L00       Elevation 88230.0 mm    ProjectElevation 236.0 mm
    crop region                                its elevation 1736.0 mm
    view range         CutPlane = L00 + 1500 mm
    survey point       -87994.0 mm

A plan's crop plane sits at its view range cut plane, and the crop region's Z
is a model coordinate with nothing between it and the truth. So the level's
internal elevation is `1736 - 1500 = 236` - which is **ProjectElevation**, not
`Elevation`. On this job the elevation base is the survey point, so
`Level.Elevation` comes back as the *shared* elevation, 87994mm out. Every
section and every 3D box was built that far above the model, which is why the
views came up empty and why the 3D would not go on a sheet at all: a 3D view
containing nothing has no extents for Revit to make a viewport from.

- **Which level property is the internal one is now worked out from the model**
  rather than assumed. Several callouts are asked, each one's crop plane minus
  its cut plane offset compared against both properties, and the answer they
  mostly agree on wins - so one odd view cannot decide it. The choice, the
  votes and the sum behind it are all in the debug panel and in the log.
- **The band is checked against the callout's own crop plane.** A plan's crop
  sits inside its view range by definition, so a band that does not contain it
  is not measured from the same datum as the model. That is refused, with both
  numbers, and nothing is built for that callout - rather than building
  something correct-looking in the wrong place.
- The debug panel prints the sum: the crop plane Z, the cut plane offset, the
  level's internal elevation that implies, and how far each property is from
  it, with the winner marked.

Bench: **288 checks**, including the survey-point job that caused this, a
normally set up one, a mixed vote, and no evidence at all.

## 1.11.0

Three things the debug report settled, and two that were asked for.

- **The 3D would not go on a sheet because the view had not been committed.**
  `Viewport.Create` returned **null, without raising and without a reason**,
  for a 3D created earlier in the same transaction - which is why the warning
  read "no reason given". A regenerate is not enough; it takes a commit. The
  views and the sheet are made in one transaction and the viewports go in a
  **second**, both inside the same `TransactionGroup`, so undo still sees one
  step. Views are looked up again by id afterwards rather than reused as
  handles across the commit, and so is the sheet.

  When `Create` still hands back nothing, the warning now carries everything
  that could explain it: `CanAddViewToSheet`, the view's id, type, template,
  `CanBePrinted`, `IsTemplate`, scale, and how many sheets it is already on.

- **The callout is turned 90 degrees, and that was being left in a transform.**
  A quarter turn describes exactly the same rectangle as an axis-aligned box
  with its two half sizes swapped, and an axis-aligned box is the form
  `SetSectionBox` is most reliable with. A rotated transform that Revit ignores
  gives a box of the right size, in the right place, **turned 90 degrees off
  the callout** - correct arithmetic, wrong box. The quarter turn is taken out
  here rather than trusted to survive the API; a callout at a real angle still
  keeps its transform, because there is no other way to describe it.

- **A1 was picking the A0 title block.** The house family is called
  `BGL_TitleBlocks_A0-A1-A2`, so matching the size against the family name
  matched every size and handed back the family's first type. The **type name**
  is asked first now, the family only as a fallback, and the fallback says in
  the log that it happened. Setting the family and type per size in Settings
  still wins outright.

- **A progress band while the tool opens.** The scan reports where it has got
  to - levels, sheets, views, callouts - and the band shows it, so the wait has
  something in it. A manual Refresh shows it too.

- **The plus and minus on the section counts are drawn as shapes**, not set as
  font characters, so they cannot come out as empty boxes. Same for the flip
  arrows, which was the previous version's fix for the same class of problem.

- Bench: **279 checks**, including the quarter-turn rule both ways, a callout
  at a real angle, and the title block match against the house family that
  caused the A1/A0 bug.

## 1.10.0

- **A debug panel across the bottom of the window.** Press **Debug**, and it
  reads out everything the tool can see about the ticked callouts as plain
  text, with **Copy it all** beside it. Nothing in it changes the model.

  It carries:

  - **the document** - Revit build, whether it is workshared, the project base
    point, the survey point and the active project location's transform, since
    a survey point a long way from the model origin is the usual reason two
    sets of coordinates disagree;
  - **how the callouts were found** - each route's count and milliseconds;
  - **per callout** - its class, view type, view family type, scale, whether
    its crop is active, the template on it, its `GenLevel` with both
    `Elevation` and `ProjectElevation`;
  - **where it is, read both ways** - the crop region's answer, the crop box's
    answer, the raw `CropBox` Min, Max and Transform with the bases written
    out, `Transform x Min` and `Transform x Max` so the arithmetic can be
    checked by hand, **how far apart the two answers are**, and which one was
    used;
  - **the view range**, plane by plane, each as level plus offset and the
    millimetre it works out to;
  - **what would be built** - the band and whether it is sane, the 3D box's Min,
    Max, transform origin and centre, where the camera would stand, and every
    section's model origin, look direction and size;
  - **sheets and viewports** - every title block type, what the mapping would
    choose, every viewport type, and then the question that matters: Revit's own
    answer to `CanAddViewToSheet` for the 3D views already in the project,
    against a real sheet, with a note for any already placed;
  - **the last eighty log lines**.

- **The 3D takes the same scale as the callout and the sections**, and the
  scale write is now proved. A view template that controls the scale swallows
  the write without raising, so the 3D could come out at whatever Revit felt
  like while the sections sat at 1:50. It is read back, and a scale that would
  not take says what was asked for, what came back, and names the template
  holding it.

- Bench: **259 checks**, including a view whose template refuses the scale the
  way Revit does it - the write does not raise, it just does not take.

## 1.9.0

**The coordinates were being read the ambiguous way.** `CropBox` hands back Min
and Max in the **view's own coordinates** with a `Transform` that maps them out
to the model, and the two are easy to combine wrongly - do it twice and the
result is a point roughly twice as far from the origin as it should be, which
is exactly what "way off" looks like.

- **The crop region is read as curves instead.**
  `GetCropRegionShapeManager().GetCropShape()` hands back the crop as
  `CurveLoop`s **already in model coordinates** - there is no transform to
  apply, so there is no way to apply it twice. That is now the first route and
  `CropBox` is only the fallback.
- **The callout's own axis comes from the longest edge of that loop**, so a
  rotated callout is read from its geometry rather than assumed square.
- **When both routes can answer and they disagree, the difference is logged**
  with both centres, and the curves win. That is the line that will say whether
  this was the problem.
- The plan text and the run report both say **which route the numbers came
  from**, and the run notes where the box actually landed.
- **A view range that reads as nonsense is not used.** Revit will hand back an
  inside-out range, or a kilometre-tall one, when a plane is set oddly; using
  it makes a section box nothing will ever show through. Anything outside
  100mm to 30m falls back to the level rule.
- **The viewport is tried twice**, because a first failure is usually Revit not
  having caught up rather than a real refusal: at the cell, then regenerated
  and dropped at the sheet origin to be moved into place. Every attempt's
  exception is reported, with the view type in the message.
- **A 3D that was never made is said out loud.** The 3D missing from a sheet
  reads as a placement problem and half the time it is that the view failed
  earlier, so the report now says which.
- The bench rule on frame keys was taught about both routes, and now also
  insists **they build the same frame** - a reader working against one and
  failing against the other is the next version of the bug it was written for.

- Bench: **253 checks**, including the crop-region route, its precedence over a
  disagreeing crop box, both fallbacks, and the view-range guard.

## 1.8.0

**The 3D was empty because the camera was pointed at the project origin.**
`SetOrientation` moves the view's *target* as well as its direction, and the
eye was being left at (0, 0, 0). The section box was in the right place; the
view was looking tens of metres away from it at nothing. The camera now stands
off from the middle of the box along the isometric direction, so it looks back
at the callout.

- **The box is cut to the callout's own view range**, which is the new default
  and is literally what the plan shows - so the 3D box and every section show
  the same thing the callout does. Read from `GetViewRange()`: top clip plane
  for the top, view depth plane for the bottom, each a level plus its offset. A
  plane set to unlimited says nothing useful, so the level rule is used
  instead. The level rules are all still there as alternatives.
- **The section box is shown**, rather than hidden. That was a setting
  defaulting the wrong way.
- **The sections are cut over that same band**, unchanged in principle but now
  reaching it through the view range - so they cut what the callout shows,
  through the callout, at its level.
- **A band that comes out inside out is refused with its numbers**, rather than
  building a box Revit will not show anything in, and a callout with no level
  found says so instead of quietly measuring from datum.
- **"Show the plan" now prints the numbers**: the level and its elevation, the
  callout's size and where its centre is in the model, whether it is rotated,
  and the exact band the box and the cuts will use. "It shows nothing" is
  unanswerable without them, and they cost one line each before anything is
  written.

- Bench: **236 checks**, including the view-range band, its fallback, and where
  the camera stands for a callout a long way from the origin.

## 1.7.0

- **Fixed: the table came up empty.** The v1.5.0 rewrite of the callout frame
  renamed its keys, and two reads of the old names survived in
  `callout_rows` - `frame["z0"]` and `frame["x1"]`. Every row threw on the way
  out and the table came up empty **with nothing said**, because the whole loop
  was inside one try. Three fixes, not one:

  - the two stale reads are corrected, and the frame carries the crop's own
    elevation again for a callout with no level of its own;
  - **one row that will not build now costs only that row.** It is counted,
    logged and reported rather than taking the table with it;
  - **a bench rule catches it happening again.** Nothing may ask a callout
    frame for a key `crop_frame` does not put in it. The frame is a plain
    dictionary handed between four modules, so a renamed key fails everywhere
    at run time and nowhere at load time. That rule was itself nearly inert -
    it ran on the source with string contents blanked out, and a dictionary key
    **is** a string literal, so it saw nothing. It reads the raw source now.

- **The flip buttons work, and they show an arrow.** They were doing nothing
  visible because the preview they drive was empty. Each button now carries its
  axis letter and an arrow **drawn as a `Polygon`**, pointing the way that axis
  is currently looking, and pressing one applies to every ticked row rather
  than to the preview alone.

- **Each section can be turned round on its own.** Click a cut line in the
  preview and that one section flips - the line says which it is and the
  tooltip says what clicking does. The axis buttons still turn a whole axis,
  and clear any single sections on that axis at the same time, or the button
  would appear to do nothing to them. The **Flip** column reads `X` for a whole
  axis and `X3` for a single section, so it says exactly what will be built.

- Bench: **225 checks** and **19 rules**, all of which catch their own
  breakage.

## 1.6.0

**The wait to open the tool was one route.** Asking every view what callouts it
carries is an API call per view, and on a real model that was the whole of it.
The other two routes are cheap: the marker route is a quick filter over one
category and costs a pass over the callouts themselves - tens of elements, not
thousands - and the type route is one cached type read per view.

- **The two cheap routes run first, and the slow one only runs when they have
  come back with nothing.** It cannot find a callout they both missed unless
  the naming is unusual, so on a model where the markers or the type names
  answer, it never runs at all.
- **It can still be forced.** *Run the slow one even when the others found
  something* is a new setting, off by default. It is the only route that fills
  in the **Cut in** column, so tick it if that column matters more than the
  wait.
- **Every route is timed**, the total is on the status line, and the per-route
  milliseconds go to the log - so "it is slow" can be answered with which part.
  The status line also says outright when the slow route was not needed.
- The route tick boxes are listed in the order they actually run, each marked
  fast or slow.

Already in place and worth knowing, since both were doing their job here: the
scan collects `ViewPlan` and `ViewSection` by class in one pass and hands the
same list to every route, and the window is shown before the model is read, so
the wait is a progress line in a window rather than nothing happening after the
button is pressed.

- Bench: **211 checks**, including the ordering itself - the slow route skipped
  when the cheap ones answered, run when they did not, forced when the setting
  says so, and the parent view it alone supplies.

## 1.6.0

Opening the tool was slow because it asked **every view in the project** what
callouts it carried, one API call at a time, and then walked the project again
for each of the other routes.

- **The scan is by class, and it is one walk.** A callout of a plan is a
  `ViewPlan` and a detail callout is a `ViewSection`, so asking only those
  classes is not a shortcut - it is the right question, and `OfClass` does the
  filtering in native code rather than a property read per view. The list is
  collected once and handed to every route, so the project is walked once
  rather than four times.

- **Look at** is a setting: plan views only (the default and fastest), plans
  and sections, or every view in the project.

- **The name map is built on demand.** It reads a name off every view and only
  the marker route wants it, so it is no longer built every time the tool
  opens.

- **The window appears first and reads the model afterwards.** The read is
  queued at Background priority, so the window is painted and responsive
  before the scan starts, with "reading the model..." in the status line. A
  few seconds of nothing happening after the button is pressed reads as the
  tool having failed to start; this is most of what "slow to open" actually
  was. How long the read took, and how many callouts it found, goes to the
  log.

- **The settings window walks the project once for both template kinds**
  rather than once each.

- The dead view-name map helper is gone.

- Bench: **199 checks**, including the scan scope and that view templates never
  come back from it. 18 rules still catch their own breakage.

## 1.5.0

The placement was wrong, and it was wrong in one place: the callout's crop box
is handed over in **its own coordinates plus a transform onto the model**, and
the two were being mixed. Local minimums are not model minimums and a crop
transform's origin is not the model origin, so the 3D box and every section
were built near the project origin rather than on the callout.

- **The frame is flattened into model space once, up front.** `crop_frame` now
  works out three things and nothing downstream touches `CropBox` again: where
  the middle of the callout is in the model, how big it is, and which way its X
  axis points. Extents are measured from that centre, so the same four numbers
  describe a callout anywhere in the model and a rotated one needs no special
  case.

- **The 3D section box lands on the callout.** A callout square to the project
  gets an identity transform and plain model coordinates, which is the form
  `SetSectionBox` is most reliable with; a rotated one gets a transform whose
  origin is the callout centre at Z zero, so the elevations still go straight
  in. The box is read back and both its bottom **and its centre** are checked
  against what was asked for.

- **The sections are cut through the callout at the array positions**, over
  **exactly the same band as the 3D box** - bottom and top now come from one
  shared rule rather than two settings that happened to agree. The now-unused
  "Take the section below the level by" setting is gone; a setting nothing
  reads is worse than no setting.

- **Sections are labelled by axis.** The view name carries `Section X1`,
  `Section X2`, `Section Y1` and so on, and the **Title on Sheet** is set to
  match, so the label under the viewport reads `Section X1` rather than the
  whole view name. The pattern and whether to write it are settings.

- **The 3D is placed on the sheet.** `CanAddViewToSheet` was being used as a
  gate, and it answers no for a view Revit has not caught up with yet - which
  turned "Revit was not ready" into a view silently missing from the sheet.
  The document is regenerated, the predicate is asked, and the viewport is
  **attempted anyway**: the exception from `Create` says far more than the
  predicate does, and a view that goes on despite the no is noted.

- **Title blocks are picked as family and type, per paper size.** Two
  dropdowns on each size row - the family, then the type within it - and the
  type list follows the family. The title block read is hardened the same way
  the viewport types were, with a second route through `FamilySymbol` and its
  category, so the dropdown cannot come back empty.

- Bench: **194 checks**, including the frame, the 3D box for a square and a
  rotated callout, the section stations landing on the callout in model
  coordinates, and the shared band. 18 rules still catch their own breakage.

## 1.4.0

- **A callout can now be found by its view family type name.** A third route:
  every view whose own `ViewFamilyType` name contains one of a comma separated
  list of tokens, **Callout** by default. Any one token matching is enough and
  the match ignores case. This is the route that answers a model where
  `GetReferenceCallouts` and the callout markers both come back empty.

- **All three routes are settings**, in a new **Finding callouts** group:
  ask every view what callouts it carries, read the callout marker elements,
  match the view family type name, and the token itself. All three are on to
  begin with.

- **An empty table now says what is in the model.** Rather than only reporting
  that nothing matched, the status line reads out the view family type names
  that are actually in use with a count each, so the token can be set from what
  is there rather than guessed. The full list goes to the log.

- The status line names the type route alongside the others, so it is always
  clear which one produced the rows.

- Bench: **159 checks**, including the route itself against a fake document
  whose views carry real type names - the token, the comma separated list, the
  case insensitivity, a view template being skipped, the route switched off,
  an empty token, the type name cache and the type tally.

## 1.3.0

- **Callouts already on a sheet are hidden by default.** A **Not on a sheet**
  tick box in the section band, on to begin with, and remembered. The status
  line says how many are being held back, so the count never silently
  disagrees with the number of callouts found.

  It is a prefilter on the table rather than a rebuild of the row list, so the
  hidden rows are still there to be counted and the column tick lists only
  offer values that are actually on show.

- **A ticked row that is filtered out of sight no longer joins the run.**
  `ticked()` used to read the whole row list, so ticking something and then
  filtering it away would still have run it - what is being agreed to is what
  can be seen. The confirm step now names anything ticked but hidden and says
  it will not be run, rather than dropping it quietly or running it by
  surprise.

- Bench: the stub API takes generic subscripts (`List[Object]`), which is what
  lets the table itself be bench tested; **143 checks**, all passing, and all
  18 rules still catch their own breakage.

## 1.2.0

- **A progress band across the top of the window.** A blue bar under the header
  with the percentage and what it is on beside it, and the running count in the
  footer status line. It is hidden until a run starts.

  The bar moves **one step per sheet**, and that is deliberate rather than
  coarse: progress can only be reported between transactions. Letting Revit's
  message loop run between `Start` and `Commit` so a bar can move is a way to
  commit nothing at all, which is a failure this suite has already paid for
  once. The repaint pumps at **`Render` priority**, which processes Render and
  everything above it but not Input - the bar moves without real mouse and key
  messages being dispatched into a half finished run.

- **The new sheets are offered at the end.** A prompt lists the sheets that
  were made and asks whether to open them; **Open them** closes the tool and
  opens them, **Stay here** leaves everything as it is. The tool closes
  *before* the sheets open, because leaving a modeless window over the drawing
  you just asked for is not the point of asking.

  A new setting, **Once the run has finished**, makes that ask / open without
  asking / leave them closed.

- **Opening several sheets does not go through `RequestViewChange`.** That call
  is documented as taking effect once the API context returns, so calling it in
  a loop opens the last sheet only. Several sheets are opened by setting
  `ActiveView` in turn, which takes effect immediately, leaving the last one in
  front; a single sheet still uses `RequestViewChange`, which is what Revit
  itself does. An id no longer in the model is stepped over, and the list is
  cleared after the event so a second raise cannot repeat it.

- Bench: 18 rules still pass and still catch their own breakage; the logic
  bench is up to **135 checks**, including the open-sheets handler against a
  fake `UIDocument` that records which route each call took.

## 1.1.0

- **Only callouts are listed.** The last-resort route that lists every cropped
  plan and section no longer runs on its own when the first two routes come
  back empty - it is behind the tick box and nothing else. An empty table is
  the honest answer to a model whose callouts cannot be read; a table full of
  every cropped view is not. A row that does come from that route says **not
  confirmed as a callout** in its Note.
- **The sections can be flipped from the main window.** Two chips in the
  section band, X and Y, lit when that axis is reversed. The preview follows
  them straight away, **Set on ticked rows** carries them onto the rows with
  the counts and the depth, and a new **Flip** column says which axes each row
  reverses.
- **The preview no longer stays big after full screen.** `SizeChanged` is
  raised inside the arrange pass, and reading `ActualWidth` there hands back
  the size the canvas is coming *from*, not the one it is going to. Growing hid
  it because a later redraw tidied up; shrinking left the drawing at its full
  screen size with nothing to trigger another pass. The redraw is queued at
  `Render` priority now, and skipped when the size has not actually moved.
- **Viewport types can be picked.** The old read asked for element types by
  the `OST_Viewports` category, which comes back empty on plenty of models.
  Three routes are merged now: by category, every `ElementType` whose family
  name is Viewport, and the types of the viewports actually placed plus the
  project default.
- **The sheet name push takes its parameters from a list.** One numbered row
  per piece of the name, each a dropdown of the sheet parameters actually in
  the project, with an X to remove and **Add a parameter** underneath. The
  parameter list itself was nearly empty before: it read one sheet and stopped.
  It now reads the project's own bindings for the Sheets category and unions in
  what up to 25 sheets carry, which is what picks up a shared parameter
  delivered with the title block.
- **The band is remembered.** X, Y, cut depth, sheet size, both flips and the
  cropped-view tick are written back when the window closes, whatever
  "remember the window size" says - they are different questions. The window
  size is only written back when it is a real number, so closing from full
  screen no longer saves the whole screen as the size.
- **The top of the 3D section box is settable**, as
  **Cut the box top off the level above by (mm)**, defaulting to **-300** so
  the box stops short of the slab over it. It is deliberately not applied to
  the fixed height, which already answers the same question, and an offset that
  would put the top under the level falls back to the fixed height rather than
  making an inside-out box. `settings_version` is 2 and the migration resets
  the old key.
- Bench: 18 rules still pass and still catch their own breakage; the logic
  bench is up to **122 checks**.

## 1.0.0

First release.

**The tool**

- A pulldown on the **RevoBIM PY** tab, **Sheet Tools** panel, holding
  **Callout to 3D** (the window) and **Callout Settings**.
- Every callout view in the project listed in one table, with the level it cuts
  in, its scale, its extents in millimetres, whether it is already on a sheet,
  and per-row X, Y, cut depth and sheet size.
- Sortable by every column, a keyword search box under every heading and an
  Excel style tick filter behind each caret.
- The window is modeless and owned to Revit's main window, so Revit stays
  navigable while it is open. Every write goes out through an `ExternalEvent`.

**What a run creates, per ticked callout**

- A **3D view** cropped to the callout's X and Y extents, with the bottom of
  the section box at the callout's base level **minus 50mm** (a setting) and
  the top at the next level up, and the view template from settings, else the
  project's default 3D template.
- An **array of sections**, X count and Y count set per row, evenly spaced
  across the callout and never on an edge, all the sections on one axis facing
  the same way, cut depth **500mm** by default.
- A **new sheet** with the callout top left, the 3D top right and the sections
  arrayed underneath, wrapping onto further rows and filling the sheet evenly.
  A1 by default, per sheet size per callout group.
- The **callout renamed** `CO_<Callout>_<Level>_1`, new views named
  `CO_3D_<Level>_<Abbrev>_1` and `CO_Section_<Level>_<Abbrev>_1`.
- The **sheet name push** run afterwards, splitting the new sheet name on its
  separator into the sheet parameters, exactly as the Sheet Management tool
  does.

**Preview**

- The section band's X and Y counts draw live onto a preview canvas next to the
  table: the callout outline, the cut lines and which way each one looks.
- **Show the plan** writes out the sheet layout the run will produce, cell by
  cell, before anything is created.

**Settings**

- Nine groups down an icon rail - Views, The 3D, Sections, Naming, The
  abbreviation, Sheets, Layout, Viewports, The name push - each scrolling, the
  window stretchable.
- Saved as plain `key=value` text at
  `%APPDATA%\RevoBIM\callout_to_3d.txt`, versioned with `MIGRATIONS`.

**House style**

- Dark and light, with **Auto** as the default: the theme follows Revit's own
  canvas theme through `UIThemeManager.CurrentCanvasTheme`, falling back to
  `CurrentTheme` and then to the saved choice. The chip in the header cycles
  Auto / Dark / Light.
- Version top right, read from `c3d_core.__version__`.
- Runs unchanged on Revit 2024 to 2027: every `clr.AddReference` in `c3d_clr`,
  imported first by everything else; no `System.Uri`; no bare `.IntegerValue`;
  no f-strings and no `print`.
- The easter egg is wired to the RevoBIM logo in all three windows - three slow
  clicks, each gap between 0.25 and 2.0 seconds, so a double click resets
  rather than opening it.

**Bench**

- `import_check.py` - 18 rules, and `--selftest` proves every one of them by
  deliberate breakage. Two only worked after being fixed: the assembly rule was
  silently empty because a regex paired quotes wrongly across a docstring (it
  now reads `ASSEMBLIES` with `ast`), and the settings round trip could not
  fail because no shipped default contained an `=` sign (it now round trips the
  size to title block map).
- `bench_logic.py` - 116 checks over the abbreviation, the naming and
  uniqueness rules, the section stations and frames, the section box top, the
  sheet layout and its wrapping, the sheet numbering sequence, the name push
  split and the settings round trip.
