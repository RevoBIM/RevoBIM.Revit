# MEP System Manager - changelog

(Pipe System Manager up to 1.6.0.)

## 3.9.0

- **Shrink to the taskbar** on every window the tool opens: the main window,
  Settings, Checks, Change Type, Resize, Service Type and every message.
  The new button at the top right, beside close, slides the window down to
  the bottom of its screen like a drawer closing, leaving only its header bar
  floating just above the taskbar so the model can be seen and worked in.
  The button becomes a **green up arrow**; press it and the window slides
  back up to where it was. Nothing is lost - edits, selection, filters and
  scroll all stay.
  - Ctrl+Shift+H shrinks and brings back. While shrunk, a double-click on
    the bar, Escape, Enter or F11 bring it back, and other keys are held so
    nothing acts on what is hidden.
  - The bar can be dragged. Moved somewhere else, the window opens upward
    from where the bar now sits, kept on that screen.
  - A dialog that shrinks takes the main window down with it and parks its
    bar above the main window's. Bringing either back brings both; closing a
    shrunk dialog brings the main window back. A message that appears while
    the main window is shrunk (the end of a run, say) brings it back first.
  - Built once (`WindowDrawer` in msm_ui, wired by `Chrome`), following the
    house standard in the RevoBIM theme reference; the parking arithmetic is
    in msm_core. The message window now uses the same Chrome as the others.
- Code polish: removed code left over from superseded approaches (the
  origin-based group maths `to_world` / `group_place`, `collect_pipes`,
  `clear_filters`, the unused error writer and old aliases), tidied an
  unused loop variable and a duplicate import.
- Bench: `rule_every_window_can_shrink` (button and both glyphs in every
  window, Chrome on every window, the button wired, Top and Height released)
  with six breakages; ten logic checks drive whole slides against a
  stand-in window, including a monitor above the primary, a bar carried
  away, a slide reversed halfway, a timer that cannot start and a dialog
  taking its owner down; thirteen new regressions.

## 3.8.1

- From a debug table where 27 of 27 took the new type, 21 of 27 resized, and
  the last six failed the same way twice:
  - The same refusal is now reported once. Every attempt was being written
    down, so each of the six read as two identical paragraphs.
  - A pipe Revit calls "Line is too short" is not tried again at the end -
    its neighbours moving cannot change it, and the retry only repeated the
    warning.
  - A refused pipe's log line says how long that pipe is, so what has to be
    lengthened is in the log.
  - "Disconnect the family from the network?" now names the setting that
    answers it, and "Line is too short" says the pipe is shorter than the
    fittings the new size needs.

## 3.8.0

- From a debug table where all 27 pipes took the new type and 21 of 27
  resized, with Revit's own reasons for the six:
  - A pipe Revit refused in the size pass gets **one more go at the end**,
    once its neighbours have moved - a pipe refused between two pipes still
    at the old size often takes the change when they are done.
  - Settings: "Let Revit disconnect a family it cannot keep". Revit asks
    "The family is connected in a network and can no longer keep the
    connectivity. Disconnect the family from the network?" - off (the
    default) the answer is no and the pipe is left as it was; on, Revit is
    allowed to disconnect and everything it disconnects is listed under
    "Disconnected by Revit - reconnect these".
  - "Line is too short" and "modified to be in the opposite direction" are
    Revit saying the pipe cannot take the fittings the new size needs; those
    are reported with their element ids for a hand edit.

## 3.7.1

- Fixed: 3.7.0's two passes never ran for anyone who already had a settings
  file - the saved "Fittings when changing type" kept the old one-step order,
  so the run was identical to 3.6.1. A settings file written before this
  version now moves to the two-pass order; a choice made after it stands.
- Fixed: a pipe accessory was never found, so none were resized and nothing
  was reported. The search only looked at what touches a changed pipe, and a
  valve usually sits past an elbow or a tee. It now looks one fitting
  further. The debug table says how many accessories were seen, and an
  accessory whose size parameters do not match names the instance parameters
  it actually carries.
- A pipe Revit refuses now reports what Revit said ("Revit refused: ...",
  with the plain-English hint where there is one) instead of "Revit rolled it
  back", by recording the failures rather than dismissing them.

## 3.7.0

- Change Pipe Type goes in two passes, which is the new default ("Type and
  fittings first, sizes after"):
  1. every pipe takes the new type at the size it already has, with its
     fittings swapped to the new type's routing preferences in the same
     transaction - nothing changes dimensionally, so a fitting only has to
     match a type;
  2. the pipes that need a different size then go to it, in batches with
     their fittings, and any fitting the routing preferences want at that
     size is swapped.
  A routing preference picks a fitting by size, so doing both at once asked
  Revit to swap every fitting and resize the run in one move. On a 27-pipe
  run the one-step order left 6 refused; this splits that work in two.
  Only the pipes whose size actually moves go through the second pass, and
  the results say how many of them made it.
- The other orders are still there: type, size and fittings in one step;
  Revit's Reapply Type; and fittings after the pipes one at a time.

## 3.6.1

- Fixed, from a debug table where 1 pipe of 27 changed and the rest were
  logged "still Copper": adding up a batch's tallies referred to a counter
  ("fittings_already") that the change had never set up. It threw after the
  batch had committed and took every later batch with it. The counter is
  there now, the tallies are added up without ever touching a key that might
  be missing, and a bench rule fails if any helper adds to a counter the job
  does not set up.
- One batch can no longer stop the rest: whatever goes wrong in a batch is
  that batch's trouble, the batch is replayed a pipe at a time, and the run
  carries on.
- The sequencing itself stands: in that run 22 fittings were swapped with
  their pipes and none were left, so "With the pipes, in one step" remains
  the default.

## 3.6.0

- Change Type is sequenced differently, which is where the warnings and
  refusals came from: each batch of pipes now takes its **type, its size and
  its fittings in one transaction**, instead of changing every pipe first and
  the fittings afterwards - which left every fitting on the old size in
  between. Settings: "Fittings when changing type":
  - With the pipes, in one step (the new default)
  - Revit's Reapply Type, after the pipes - the pipes and their fittings are
    selected and Revit's own command is posted. Revit runs a posted command
    once the tool's work returns, so the log says the fittings follow. Where
    Revit will not let an add-in post it, the fittings are changed with the
    pipes instead and the results say so.
  - After the pipes, one fitting at a time - what 3.5.0 did.
  A fitting a rolled-back batch left behind is still picked up afterwards.
- Settings: "Accessory size parameters", starting at BGL_Diameter, as a list
  you can add to. A pipe accessory joined to a resized pipe has those
  instance parameters set to the new size, in that order, whatever they hold
  now. Where an accessory carries none of them, its own size parameters are
  matched by name and old value as before. A type-driven or read-only one is
  still left and reported.

## 3.5.0

- Fixed, from a debug table of a change inside a group: the pipes changed,
  then the run stopped with "The referenced object is not valid" and the
  group was never put back, leaving its elements loose. Changing a pipe's
  type makes Revit delete some members and create replacements, so the list
  the group was opened with is not the list it closes with - the deleted ids
  stopped the rebuild outright.
  - What Revit created in place of a deleted member - joined to a surviving
    member, in no group - goes back into the group with it.
  - The rebuild never gives up: an element Revit will not take is dropped and
    the rest are grouped again, so the group always comes back. Only if
    nothing at all can be grouped are the elements named as left ungrouped.
  - A group is closed once, whatever happened before it, and a failure to
    close one group cannot stop the others.
  - Where a run stops, the debug table now names the line it stopped on.
- Change Pipe Type: the current size column sits beside the new size column,
  as "From size (mm)" and "New size (mm)".

## 3.4.0

- Pipe accessories follow the pipe's new size: a valve, strainer or other
  accessory joined to a pipe that changed size takes the new size where its
  diameter is an instance parameter. The parameter has to be named for the
  size (diameter, size, DN, nominal, bore) and hold the old size now, which
  keeps a body length or an offset out of it. A diameter driven by the type
  is left and reported, since it belongs to every accessory of that type;
  so is a read-only one. Resized accessories are counted in the summary and
  listed in the change log; the rest are listed under "Accessories left at
  their old size".

## 3.3.0

- Fixed, from a debug table of a change inside a group: the run stopped part
  way, everything it had done was rolled back, and nothing said why.
  - Groups no longer depend on a group's origin, which is what broke: each
    copy's frame is taken from its own members (their centre and the
    direction of the furthest), and a copy is put back after the swap by
    comparing where its members were with where they are now. Proved on the
    bench to land exactly for any position and rotation.
  - A failure in one phase (the type changes, the fittings, the retained
    values) is reported and the run carries on, so finished work is kept and
    an opened group is always closed again.
  - The watchdog only covers a request Revit has not started: the handler
    tells the window the moment Revit begins the work, so a long run is
    never mistaken for a stuck one (a 51 s change was cut off at 20 s).
  - A traceback goes into the debug table as rows - the message, then the
    last few frames as "file line - code" - instead of one cell that gets
    cut off.

## 3.2.0

- Selecting in another system clears the others, as Windows does: a plain
  click, Shift-click or arrow key that selects rows in one group clears
  every other group's selection. Ctrl-click adds to it instead. Select all
  does the same - the other groups are cleared, Ctrl + Select all adds the
  group. Selections the tool makes itself (Pick System, keeping the selection
  through a refresh, Assign on the Workset Assigner) are unaffected.

## 3.1.1

- Select none beside Select all on every group heading: clears that group's
  selection; the other groups keep theirs.

## 3.1.0

- Pipes in groups with copies are now changed, as Edit Group would. From a
  debug table where 62 pipes in one group type with 41 copies were all left
  (3.0.0 only edited a group with no other copies):
  - the copy holding most of the selection is opened (ungrouped); a pipe
    picked in any other copy is matched to the same pipe in that one by
    where it sits in its group, so the edit covers it;
  - the pipes are changed, fittings swapped and parameters kept, and the
    copy is rebuilt as a group;
  - every other copy is moved onto the rebuilt group type, turned and moved
    to correct for where Revit put the new type's origin, so its members sit
    exactly where they were - then measured: a copy whose extents moved more
    than 250 mm is put back on the old group and named, never left out of
    place;
  - when every copy made it, the old group type is deleted and the rebuilt
    one takes its name; otherwise the old type is renamed "(copies not
    changed)" for the copies left on it.
  - Every copy is borrowed first; if somebody else holds any copy the whole
    group is left and named, since changing some copies and not others would
    split it. A group nested in another group is still left and reported.
- Fixed: the change log window took its title from the last section of the
  results ("Fittings left as they were - log").

## 3.0.0

- Pipe System Manager: Group by System No is on by default, so rows sit in
  collapsible System No subgroups under each service type. Each subgroup's
  header has its own colour - a bar and the system number in that colour -
  kept by system number across the tab.
- Change Pipe Type opens a mapping window (pipes):
  - left: every current pipe type and size in the selection, grouped by size
    with each size in its own colour, sortable by size, current type or
    count;
  - right: the new pipe type and, per row, the size it goes to - a dropdown
    of the sizes that type's routing preferences offer, defaulting to the
    same size, else the next size up;
  - Apply changes those pipes to the new type at the mapped sizes, then swaps
    the fittings to the new type's routing preferences, keeping the
    parameters ticked in Settings.
- Pipes in groups: a group with no other copies is opened (ungrouped), the
  change made, and closed again under its old name - as Edit Group would.
  Where the group has other copies, or is nested, Revit's API cannot carry
  the change to them without risking where they sit: those pipes are left
  and listed as errors.
- A change log once it finishes: every success ("id - Copper 22 -> PEX 25",
  fittings swapped) and every error with its element id, shown in a window
  and saved to %APPDATA%\RevoBIM\mep_system_manager_change_log.txt.
- If there are errors, an offer to show them in 3D: the converted systems in
  full are isolated temporarily in the 3D view, successes overridden to 60%
  surface transparency, errors to solid magenta projection lines (as View
  Specific Element Graphics would). Reset Isolate takes it all off.

## 2.15.0

- Settings: "Look up linked elements", off by default. Off, Pick System
  never takes anything from a linked model: the pick filter refuses a linked
  model and anything inside one, and should Revit still hand one back it is
  thrown away and the status line says so. On, clicking a linked model asks
  for the element inside it, which is reported in the status line - link,
  category, id, system, type, size - read-only. Linked elements are never
  listed, isolated or changed either way; every list, isolate and change
  works on this model only.
- The Settings window is a little taller for the new tick.

## 2.14.0

- Re-apply Type (Change Settings row, Pipe and Duct tabs, lit when systems
  are selected): does what Revit's Reapply Type does, which the API does not
  offer - every fitting on the selected pipes or ducts is put back to what
  its type's routing preferences call for, matched by part type and size. A
  fitting joining a selected pipe to one left alone, or joining two types,
  is not touched. Parameters ticked to keep in Settings are carried over and
  read back, as with Change Type. The results say how many fittings were put
  back, how many were already right, and any that could not be.
- Minimum window width 1180 for the extra button.

## 2.13.0

- Group by System No (toolbar, on by default on the Duct tab, a tick on
  Pipe and Containment too): each service type becomes a fold of System No
  folds, each holding that system's rows with the usual sorts and filters.
  A service type's heading gives its systems, element count, flagged rows
  and (containment) its types, with Open all / Close all for its system
  numbers. Collapse all folds to the service types; Expand all opens
  everything; what is open is remembered. The frozen heading reads
  "Supply Air > SA 2". It only applies while rows are split by System No.
  Pick System and the selection kept through a refresh open the folds they
  need.
- The folds that hold sections - disciplines on the Workset Assigner,
  service types here - are kept per tab, so switching tabs puts the right
  ones back.

## 2.12.0

- Pick System (blue, with a pick icon, on every tab, beside Expand all):
  pick a pipe, duct, cable tray or conduit in Revit - or a fitting or
  accessory on one - and its system is found and selected in the list, ready
  to change. From any discipline tab, picking another discipline's element
  takes you to its tab (reading it if it has not been read) - pick a duct
  from Containment and the Duct tab opens on that duct's system. The
  Workset Assigner stays put and selects the system there.
  - The whole system is selected - every row on the same System No (Run on
    containment) in the same service type, however the rows are split. A
    fitting is found through what it joins.
  - Its service type is opened and scrolled to; a filter, search box or
    Issues only that hid it is loosened, and a page filter (more than one
    type / more than one workset) is switched off, all said in the status
    line.
  - Esc cancels. The pick waits on you, so the 20 s watchdog stays off while
    you pick.

## 2.11.0

- Fixed: Isolate Selected stopped working after a few goes and needed the
  tool restarting. Every job goes to Revit as a request Revit runs when it is
  idle. If a request was made while Revit had not yet run the last one,
  the tool emptied the whole queue - the earlier job's "done" never came, the
  window stayed busy (and unclickable) for ever, and every click after was
  ignored without a word.
  - The queue never drops a job: a request made while one is waiting is
    queued behind it and runs in the same pass; a refused request takes back
    only itself.
  - A watchdog: if Revit has not run a request within 20 seconds the window
    is freed and the status line says why; the job still runs when Revit
    gets to it.
  - A click while waiting says so in the status line and the debug table,
    instead of being ignored silently.
  - After isolating, the view is made active if it is not, and Revit is told
    to redraw it - a view changed from a modeless window is not always
    repainted until touched, which made a good isolate look like nothing.
  - Debug table: every press of Isolate, what Revit said to the request,
    whether the view was switched, zoomed and redrawn.
- Change Type turns green once a type to change to is chosen.
- A search box beside the Type dropdown narrows it to the types holding every
  word typed; one match is picked for you, no match keeps the whole list and
  says so. The pick is read from the list on screen - the same rule the
  workset search follows, held by the same bench rule.
- Minimum window width 1080 for the search box.

## 2.10.0

- A colour per type. The Type column shows each type with a coloured bar and
  its name in that colour, so the different types stand out down a list; on
  the Containment tab each service type's heading lists its types in the
  same colours. Colours are handed out by type name across all of a tab's
  types, so a type keeps its colour through refreshes, filters and whichever
  service it turns up in. Ten colours, each tuned for dark and for light;
  red is kept out, since red means "needs a look". A row that merges several
  types (Type not split) stays plain. On every discipline tab.

## 2.9.0

- Frozen column headings: scrolling down through a system type, its column
  headings (Run / System No, Type, Size, Count...) stay pinned under the
  frozen system type heading, the same widths and at the same place as the
  table's own, following a column resize. Clicking one sorts that table, as
  its own heading would (Shift adds a level); clicking the name still goes
  back up to the system type.
- The heading being sorted by has an orange box round it - in the table and
  in the frozen headings. A second level is boxed blue, a third green. The
  box is always drawn and only its colour changes, so lighting one never
  moves the layout.
- Containment: rows sort by Type within each service type by default, then
  by Run. A sort you pick still wins, and carries through a refresh.

## 2.8.0

- Isolating one system after another is more robust:
  - The view the last isolate went into is reset as well as the one being
    isolated in, so changing the View dropdown between checks no longer
    leaves an old isolate standing in the other view. The tool remembers the
    last view it isolated in.
  - A reset now also turns off Revit's Reveal Hidden Elements mode, which
    makes a new isolate look muddled when left on.
  - After isolating, the tool looks at the view: any pipe, duct, tray,
    conduit, fitting or accessory still showing that is not in the new
    selection is a leftover. If there is any, it resets and isolates once
    more; anything still showing after that is reported in the status line
    and the debug table, never hidden.
  - Reset Isolate resets both views the same way.
  - The same applies to Isolate and highlight after a resize.

## 2.7.2

- The footer is laid out in rows, so every button shows on a normal screen
  with its text in full (on the Containment tab the tools ran past the
  window's edge):
  - Change Settings - Type, Change Type, Resize runs, Change Service
  - Isolate in - View, Isolate Selected, Reset Isolate, and the selection
    summary on the right
  - Debug and the status line
  On the Workset Assigner the same rows hold Workset / Assign to selected /
  Clear selected with Apply at the far right, then what is staged and
  Clear all.
- Icons on those buttons: swap arrows for Change Type, a stretch arrow for
  Resize runs, a tag for Change Service, a framed target for Isolate
  Selected, a turning arrow for Reset Isolate, a down arrow for Assign.
  Reset is now labelled Reset Isolate.
- The toolbar is two rows too - search and Rows split by, then Scope, the
  Checks switch and the filters - so the Containment tab's extra tick no
  longer pushes it off the edge. The minimum window width comes down from
  1260 to 1000.

## 2.7.1

- Fixed: resizing a run's height put the new height on the fittings' width.
  From a debug table and a view of the model: trays taken from 25 to 50 high
  came out with fittings pinched to 50 wide, while the table counted 60
  fittings at the new size. 2.7.0 set fitting sizes through the fitting's
  connectors, and in these cable tray fitting families a connector's
  "Height" is tied to the tray's width.
  - Fittings are now sized only through their own parameters, named for the
    dimension: a height goes on "Tray Height" (or Height / Depth), a width on
    "Tray Width", a conduit diameter on its diameter. Offsets, elevations,
    bend radii, lengths and the like are never touched, whatever they are
    called. Connectors are never set; a bench rule holds it.
  - A fitting takes the actual width and height of the trays joined to it,
    read from the trays' own parameters. Where those trays differ - a reducer,
    a tee onto a narrower branch - that dimension is left to the family.
  - Because fittings are matched to their trays, resizing a run again puts
    fittings pinched by 2.7.0 back to their trays' width.
  - A fitting is proved at the end by its parameters, and one with no
    parameter for the dimension is reported, not guessed at.
- Debug table: which fitting parameters were set, and on how many fittings.

## 2.7.0

- Resize runs sizes the fittings too. From a debug table where the trays of
  a run took their new height but the fittings between them kept the old
  one: the tool set sizes on trays only and left the fittings to Revit,
  which does not always follow. Now, in the same transaction as the trays,
  every end of a fitting joined to a resized tray is put at that tray's new
  size - the connector itself where the family allows it, else the
  fitting's own width / height parameters that hold the old size (a
  parameter must be named for the dimension and hold the old value, which
  keeps a bend radius or an offset out of it). A tee joining a resized tray
  to one that is staying keeps the other end as it was. Revit gets the first
  go - only ends still at the old size are touched.
- Fittings are read back at the end with the trays: the results say how many
  fittings are at the new size and list any left at the old one, which
  Isolate and highlight shows in red.
- "Resize the fittings joined to them too" in the Resize dialog, on by
  default, remembered.

## 2.6.0

- Containment: every service type's heading lists the cable tray and conduit
  types it uses, most used first, with how many of each - e.g. "3 types:
  BHE_CableTray (25mm High) x12 . BHE_Ladder x3 . Conduit: 25mm PVC x1". A
  service using more than one type shows its list in orange; hovering shows
  it in full. Counted from every tray and conduit read, so it is right even
  when Type is not split into rows. The frozen heading carries it too.
- "Only service types using more than one type (N)" (Containment toolbar)
  narrows the page to those service types, to put them right.

## 2.5.1

- Fixed: resizing a run could leave all but one tray at the old size while
  reporting 7 of 8 resized. The debug table gave it away: a second resize of
  the same run found all 8 still to change. When Revit refused the run in
  one go, the fallback resized each tray on its own - leaving the fitting
  between two trays half old, half new at every step, which Revit can settle
  by putting a tray back - and the sizes were checked before the job ended.
  Now:
  - if Revit refuses the run, the trays it names are set aside and the rest
    are resized again together, so neighbours stay matched; if it names none
    of them the run is halved and each half tried the same way, up to a cap
    on attempts;
  - every tray is read back after the whole job has finished; only a tray at
    its new size then counts as resized, and one that was changed and came
    back is reported as put back by Revit;
  - the sizes are also read just before the undo step closes, and the results
    and debug table say if closing it moved anything.
- Debug table: per run, how many attempts it took and every tray's size at
  the end.

## 2.5.0

- A frozen system type heading: scrolling down through a system type's rows,
  its heading stays pinned across the top - name, counts, flags and (on the
  Workset Assigner) the discipline and the workset the type is on - until
  the next system type's heading comes up and pushes it out. Clicking the
  pinned heading scrolls back to that system type's own heading. On every
  tab.
- Fixed: switching away from the Workset Assigner and back failed - the tab
  re-added its system type sections straight to the page, but they belong to
  their discipline expanders. The disciplines are re-added now, and a bench
  rule holds it.

## 2.4.0

- Faster applies, from a debug table where 132 systems / 4807 elements took
  46s though only 907 needed to change:
  - Workset Assigner: elements already on their target workset are left out
    before anything is borrowed or written (3900 of the 4807 in that run).
  - Borrowing, everywhere the tool writes: CheckoutElements already answers
    with everything the user now holds, so only elements missing from that
    answer are looked up to name their owner. Every element used to be asked
    about one call at a time as well.
  - Workset Assigner: one transaction for the whole apply instead of one per
    200 elements; if Revit refuses the lot it is rolled back and done in
    batches of 200, so one bad element still cannot lose the rest.
  - Change Service: elements already on the new service type are left out
    before borrowing.
- Workset Assigner results report "N moved, M already on the right workset"
  - the old "moved" figure counted both. The debug table gains a timing row:
  sorting, borrowing, writing and proving, each in seconds.

## 2.3.2

- Workset Assigner, from a debug table where a workset was staged twice and
  never applied - Apply never ran:
  - Apply now sits at the far bottom right, docked on its own, reading
    "Apply (N)" with the number staged. Before, it sat mid-footer where, on a
    narrow window, the selection text could cover it.
  - Staging clears the selection so the staged rows show orange - a selected
    row is drawn in the selection colour, which hid that anything had
    happened. The footer reads "N systems staged - not written until Apply",
    and the status line says where Apply is.
  - Closing the window with changes staged asks first.
- Fixed: Apply built its list from the rows the table showed, so a staged
  system hidden by a filter or by "Only systems on more than one workset"
  was silently left out. It now takes every staged system from the whole
  read (core.staged_rows).
- Debug table: Apply pressed, what it stopped on (nothing staged, another
  model active, cancelled at the confirm, Revit refusing the request) and
  what it sent, and the systems each stage covered.

## 2.3.1

- Workset Assigner: a search box beside the workset dropdown narrows it to
  the worksets holding every word typed, in any order, any case. A single
  match is picked for you; a search that matches nothing keeps the whole
  list and says so rather than emptying the dropdown.
- Fixed with it: staging read the chosen workset by its place in the full
  list, which a narrowed list would have got wrong. The pick is now read
  from the list on screen.

## 2.3.0

- Workset Assigner in two levels: Containment, Pipework and Ductwork (in that
  order) each fold on their own, with the system types inside them folding
  again. Each discipline header gives its systems, system types and how many
  are on more than one workset (red), with Open all / Close all for its
  types. Collapse all folds down to the three disciplines; Expand all opens
  everything; what is open is remembered.
- Group by (toolbar): "Discipline > system type > system", or "Discipline >
  system", which lists each discipline's systems in one sortable table with
  System Type as a column.
- "Only systems on more than one workset (N)" (toolbar) isolates the systems
  whose elements are split across worksets, opening them ready to select,
  assign the right workset and Apply. Works with either grouping.
- The Workset now cell of a system on more than one workset is red.
- Pipe / Duct discipline names read Pipework / Ductwork on this tab.

## 2.2.1

- Fixed: Resize runs did nothing when Revit objected to one spot. The debug
  table showed a run of 11 trays going to 100 high refused with "insufficient
  space to create the required fittings" at one element; the whole run was
  rolled back, so nothing changed, ticked or not. A new "If Revit objects"
  choice, defaulting to "Resize everything Revit allows - leave and show the
  rest": the run is tried in one go, and if Revit objects each tray is tried
  on its own, then those refused are tried once more (a tray can take its new
  size once its neighbours have theirs). Only what Revit still refuses is left
  as it was - still never left broken. "Put the whole run back" is the other
  choice, as before.
- The results say per run how many trays were resized and how many left,
  quote Revit, and say in plain words what the message usually means and what
  to do - for this one: a straight too short between two fittings, or a bend
  or tee that would overlap the next when bigger.
- Isolate and highlight now shows in red both the elements Revit named and
  the trays left at their old size.
- Debug table: the 40 sample rows of a read are written on a tab's first read
  only, not on every refresh.

## 2.2.0

- A fourth tab, Workset Assigner. Every pipe system, duct system and
  containment run in the model, grouped Pipe, then Duct, then Containment,
  one expandable group per system type, each group's header saying which
  workset(s) that type's elements are on. Columns: System, Workset now
  (one workset, or "Mixed: A (12), B (3)"), Elements, New workset - sortable
  and filterable like every other tab. Select systems, or whole system types
  with Select all (Ctrl for more groups), pick a workset and Assign to
  selected: the rows turn orange and show the new workset. Nothing is written
  until Apply, which lists everything it is about to do, then borrows, moves
  in batches inside one undo step, reads every element back and reports any
  system not fully moved. Only pipework moves: pipes, ducts, trays, conduits,
  their fittings and accessories - not equipment, fixtures or insulation
  (insulation follows its host). Containment runs are the same runs the
  Containment tab shows. A model that is not workshared says so.
- Containment: Change Service. Give the selected rows, their whole runs, or
  every run under their service types a new service type - typed, or picked
  from those in use - with the dialog saying exactly how many trays and
  conduits each choice reaches. Writes the parameter the tab groups by (the
  Service Type parameter, or the custom service parameter), optionally also
  on the runs' own fittings; a fitting belonging to another service is the
  run's edge and is left alone. Every value is read back; the selection
  follows the runs into their new group.
- Icons on every tab: a pipe, a duct, a cable ladder and stacked worksets.
- Minimum window width 1260 so the Containment footer fits.
- Bench: workset grouping, ordering and summaries, staging and the Apply
  plan, service scopes; the workset job and the service job against a fake
  Revit, including a part-moved system and another service's fitting.

## 2.1.1

- Fixed: a containment run crossed service boundaries. The run walk went
  through every fitting, so a VRF tray teed into an ICT tray was one "run" -
  in the Run column, in Isolate "whole systems", and in Resize runs with
  "whole run" ticked, which could resize trays of another service. A run now
  stays on one kind (tray or conduit) and one service type (or the custom
  service parameter): a tray or conduit of another service is never entered,
  and a fitting belonging to another service is kept as the boundary but not
  walked through. One walk (model.walk_run) now names the Run column and
  drives isolate and resize, so they cannot disagree.
- The Resize dialog says exactly what "whole run" takes before anything is
  changed - e.g. "36 trays instead of 16" - counted from the table's own
  runs, and the confirm uses the count that will actually be resized.
- After a resize, Show in 3D isolates exactly what was resized: the resized
  runs with their fittings.
- The debug table lists each run's size: how many to resize, how many were
  selected, and how many elements with its fittings.

## 2.1.0

- A Debug tick at the bottom left, off by default. While it is ticked every
  action is recorded - each read (counts, timing and a sample of what was
  read), isolate, reset, change type, resize and every error with its
  traceback, every item a job reports on a row of its own. Copy table puts
  it on the clipboard as a Markdown table ready to paste into a chat, headed
  by the tool, Revit, engine and pyRevit versions, the model and the tab's
  settings, and saves the same table to
  %APPDATA%\RevoBIM\mep_system_manager_debug_table.md. The newest 2000 rows
  are kept. The debug log that used to be on by default is off until ticked
  (settings migration 3).
- Containment: Resize runs, beside Change Type on the Containment tab. Pick
  rows, give a new cable tray width and/or height and/or conduit diameter
  (blank keeps what is there), optionally the whole run of each row. Each
  run is resized in its own transaction and every value read back. Warnings
  are dismissed and listed; if Revit raises an error the run is rolled back,
  so the model is never left broken, and the run is listed with what Revit
  said and the elements it named.
- When runs will not resize: Isolate and highlight isolates those runs in the
  chosen 3D view - the same reset-then-isolate as Isolate Selected - with the
  elements Revit named coloured red and selected. The tool remembers what it
  coloured; Reset, and the next isolate, take the red off again.
- Footer combos narrowed and the minimum width is 1140 so the new button
  fits.
- Bench: size input, resize plan, confirm wording, highlight memory, the
  debug table and row cap, the debug migration; the failure recorder and a
  resize run - committed and proved, or rolled back with its broken elements -
  against a fake Revit.

## 2.0.1

- Isolate Selected always resets the view's earlier isolate before making
  the new one, on every tab. Revit isolates within what is already isolated,
  so an earlier isolate left on showed through the new one. The reset used
  to happen only when Revit reported the view as isolated, and in the same
  transaction as the new isolate; it is now done unconditionally and
  committed on its own - exactly what Reset Isolate does - then checked.
  Reset and isolate stay one undo step (one transaction group).
- If the earlier isolate will not come off, the new one is not stacked on
  top of it: the run stops and says to use Reset Temporary Hide/Isolate.
- The status line says when an earlier isolate was reset first.
- Bench: the order is tested against a fake view - reset committed before
  the new isolate, reset done even when the view says it is not isolated,
  nothing stacked on an isolate that will not come off.

## 2.0.0

- Renamed MEP System Manager. The folder, module names (msm_*) and window
  titles follow; the old Pipe System Manager.pushbutton folder is to be
  deleted.
- Three tabs across the top: Pipe System Manager, Duct System Manager and
  Containment System Manager. Each offers everything the pipe tool did -
  grouping by service type, sort and filter per service, rows split by, checks
  and type standards, Issues only, isolate in 3D, change type keeping chosen
  parameters, keep selection through a refresh, export. Each tab reads the
  model the first time it is opened and keeps its own read, sections,
  selection, scroll and chosen type while another tab is in front.
- Every per-discipline setting is kept per tab (grouping, rows split by,
  scope, checks, standards, retained parameters, keep size, swap fittings,
  Issues only, expanded services); theme, isolate options and results are
  shared. Settings, and Checks, open for the tab in front.
- Ducts: grouped by System Type or Classification like pipes. Sizes read as
  a diameter or width x height, sorted by cross-section area. The size check
  uses the project's duct sizes for the duct's shape. Keep size keeps the
  diameter, or the width and height. Isolate keeps duct fittings,
  accessories, flex duct, insulation and lining on the picked systems.
- Containment: cable trays and conduits together. The service type - which
  decides the grouping - comes from Revit's Service Type parameter by
  default, or a custom parameter chosen in Settings. With no systems to name,
  the System No column is the Run: everything joined through fittings, named
  after its lowest element id. Types read "Cable Tray: ..." / "Conduit: ...",
  and a type only goes onto elements of its own kind - the rest are skipped
  and listed. Fittings are swapped by slot: whatever the new type holds in
  the slot the old type used the fitting for. The fitting check compares
  service types; No service type replaces No system; there is no size check.
  Isolate Whole systems means whole runs.
- Settings carry over from pipe_system_manager.txt the first time, into the
  Pipe tab, and are then kept in mep_system_manager.txt.
- A new icon drawn from the name: a pipe, a duct and a cable ladder.
- Bench: 28 import rules; bench_logic covers the tab settings view, the
  carry-over, each discipline's wording and checks, rectangular and round
  sizes, containment slots and runs, and duct and containment size reads
  against a fake Revit; xlsx_check builds duct and containment workbooks.

## 1.6.0

- A Checks on / Checks off switch in the toolbar turns every check off at
  once: no red rows, no "rows need a look" in the service headers, and the
  Checks column hidden. Issues only is greyed out while they are off. Which
  checks are ticked, and the pipe type standards, are kept, so switching back
  on restores them. Remembered between sessions.
- Export follows the switch: with checks off the workbook has no Checks or
  Rows needing a look column and nothing washed red.

## 1.5.0

- Checks. Every pipe is checked as it is read and each row adds up its
  pipes' problems: pipe type not allowed for its service, size not in the
  pipe type's routing preferences, open ends, a fitting or accessory on a
  different system, and pipes on no system. A row with anything wrong gets a
  red wash and says what in a new Checks column (sortable, filterable, worst
  first when sorted descending). Each service header counts its flagged rows.
- Pipe type standards. A new Checks window (header chip) sets, per service,
  which pipe types it may be built from, and which checks are switched on.
  A service with no standard is never flagged. Saved in the settings file as
  a readable line: Cold Water>>Copper|MLCP;;Hot Water>>Copper.
- Issues only (toolbar) shows just the flagged rows. It switches itself off,
  and says so, if it would hide the selection after a refresh.
- Change Pipe Type offers the service's first allowed type when the selected
  rows all sit in one service with a standard and no type is picked yet.
- A Fittings column: fittings and accessories joined to the row's pipes,
  each counted once.
- Export (header chip) writes the rows as shown - filters and sort included -
  to an .xlsx: a Pipe systems tab with flagged rows washed red, and a Summary
  tab per service with totals. Frozen header, autofilter, numbers as numbers,
  A4 landscape one page wide. Offers to open the folder; remembers where.
- Minimum window width 1080 so the toolbar fits.
- Bench: xlsx_check.py validates generated workbooks of five shapes against
  the rules Excel enforces (12 deliberate breakages, all caught); bench_logic
  covers the checks, standards, the row totals and the per-pipe health read
  against a fake Revit.

## 1.4.0

- Refresh keeps the selection. Rows selected before a refresh are selected
  again once it completes - also after Change Pipe Type, a scope change and
  a Rows split by change. The selection is held by pipe element id as well as
  row, so rows whose pipes changed type (and so moved to a new row) are found
  again. The services holding them are opened and the page scroll is kept.
- Each service's sort and column filters survive a refresh too, as long as
  the row layout (grouping and Rows split by) has not changed.
- A column filter that would now hide a reselected row is widened just enough
  to show it - its value ticked back on, or the keyword on that column
  cleared - and the search box is cleared if it hides one. The status line
  says what was kept, widened, and any selected pipes no longer there.

## 1.3.0

- Moved to the Management panel.
- Fixed: every first launch asked "Last time the window opened but did not
  respond to anything - open it modal?" when nothing was wrong. The note that
  a modeless window opened is meant to be cleared by the first handler to run
  after the window is shown. Filling the pipe type dropdown while the window
  built fired its SelectionChanged first, inside the command, which counted
  as proof before the note had even been written - so the note written just
  after was never cleared. The proof now only counts once launch() has
  written the note and armed it, immediately before Show().
- The note records the version, and a leftover from an older version is
  cleared rather than acted on, so upgrading cannot raise the prompt.
- Bench: a rule that prove_alive waits for the arm and that launch() builds,
  notes, arms and shows in that order, each proved by breaking it.

## 1.2.0

- Isolate shows only what is on the picked pipes' own systems. Anything the
  walk finds is dropped unless it is pipework (pipes, fittings, accessories,
  flex pipe, insulation) on one of those systems - a valve or fitting at a
  boundary that belongs to the next system along, and equipment or fixtures a
  whole system runs through, no longer show. Insulation on what is kept is
  kept with it. What was left out is written to the debug log by category.
- The section box stays visible in the isolate. It is fitted first, then the
  view's section box element is found and isolated along with the pipework,
  so it can still be grabbed and dragged. An earlier isolate is cleared before
  the box is fitted.
- Retained parameters: every value is read before anything changes, for the
  pipes and for every fitting and accessory joined to them. After all the
  type changes and fitting swaps, one final pass writes back every value that
  differs, then reads them all again after the commit and tries once more if
  anything moved. Previously each pipe was restored inside its own batch, so
  changing a later pipe could reset an earlier one's fittings after they had
  been checked, and fittings were only read after the pipes around them had
  already changed.
- A fitting Revit replaces during the change is found again by position on
  the same pipes, and its retained values are carried onto the new one.
- Fittings and accessories whose values are retained are borrowed too on a
  workshared model.

## 1.1.0

- Isolate Selected in the default 3D view now always fits the section box
  round what was isolated, using the margin in Settings (300mm default).
- The Settings tick for the section box now applies to 3D views picked from
  the list; the default view does it regardless. A chosen coordination view
  keeps its hand-placed box unless asked.
- The status line says when the section box was fitted.

## 1.0.0

- First release. RevoBIM PY tab, MEP panel, single button.
- Every pipe in the project (or the active view) grouped by service type -
  Piping System Type by default, or System Classification, or any parameter.
- Each service expands to its own grid: System No, Pipe Type, Size (mm),
  Count and Length (m). Sort by any heading (shift-click adds levels), keyword
  filter and Excel-style tick filter under every heading, per service.
- "Rows split by" System No / Pipe Type / Size: untick one and the rows merge
  and the counts recount.
- Isolate Selected: temporary isolate in the chosen 3D view, or the default 3D
  view (made if it does not exist). Pipes only, pipes plus connected fittings
  and accessories, or whole systems. Zoom, section box and select are settings.
  Double-click a row to isolate it.
- Change Pipe Type: confirm lists what will happen, then every pipe is
  changed, each chosen parameter read back and restored if the type change
  moved it, sizes kept, and fittings swapped to the new type's routing
  preferences where every pipe they join is changing. Workshared elements are
  borrowed first; anything held by somebody else is named and skipped.
  Batches of 25 in a TransactionGroup, a refused batch replayed a pipe at a
  time, and the result counted from the model afterwards.
- Auto / Dark / Light theme chip, Auto following Revit's canvas theme.
- Easter egg on three slow clicks of the RevoBIM logo, in every window.
- Revit 2024 - 2027.
- Bench: import_check.py (24 rules, 33 deliberate breakages all caught) and
  bench_logic.py (35 checks on grouping, sorting, filtering, the default 3D
  view, the restore plan and settings; 11 regressions all caught).
