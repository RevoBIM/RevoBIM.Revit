# Auto RevCloud - changelog

## 2.13.0 - 2026-09-10
Two experimental options, each in its own block in Settings and both OFF by
default, so each can be tested on its own against a known view.

**Experimental 1 - VersionGuid.** Every element carries a GUID Revit changes on
ANY edit. Identical means untouched, and skips every other test. Different
means something changed - even something no other test can see: geometry
reshaped inside the same box, a parameter not on the list, a host reassigned.

- **Flag** mode: an identical GUID skips the element; a different one only
  counts if a test can say what changed. Safe, and a speed-up.
- **Trust** mode: a different GUID is clouded even when nothing else can say
  why, as **edited**. This is the mode that catches everything, if the GUID
  can be trusted.
- **The run reports whether it can.** "VersionGuid: N matched pair(s)
  identical, M differ, K unreadable". If almost every pair differs, the GUID
  does not survive however the previous version was made, and the run says so
  and tells you to turn it off. That is the ten-minute test, built in.

**Experimental 2 - only what this view shows.** A pipe that moved 300mm
straight up looks identical on a plan, and a cloud round it says "look here"
at nothing. With this on, a move or a resize is only clouded if it shows on
THIS view's drawing by more than a paper-millimetre distance, measured on the
view's own plane. The same move shows on a section and is clouded there.
Additions, removals, retypes, rotations and parameter changes are always kept
- an addition is visible by definition, and the rest change what is drawn
regardless of where they sit.

- Bench: 149 comparison checks (was 127). Both options are covered both ways
  round - the GUID that skips a visible move, the two modes disagreeing on
  exactly the case they differ on, the vertical move that is invisible on a
  plan and visible on a section.

## 2.12.0 - 2026-09-09
The tool compares **elements in space** - the host view's crop volume - not the
same view opened in the link. The link side has no view at all: no crop, no
view filters, no template, no phase. That asymmetry was inventing changes, and
both cases are fixed.

- **A category the view does not draw is now dropped from BOTH sides.** It was
  skipped in the host, because the host read respects category visibility, and
  read in full from the link, which has no view to respect. Every element of
  it in the link then looked like a deletion and got clouded. The comparison
  has to ask the same question of both models.
- **A removal now means gone from the model, not undrawn in this view.** An
  element hidden by the hide command, or sitting outside the crop after being
  moved, is missing from the host side and present in the link - which is
  indistinguishable from a deletion. Every apparent removal is now checked
  against the host document by UniqueId, and the count of ones that are still
  there is reported.
- The lookup is one per removal rather than one per element, so it costs
  nothing on a view where little has changed.
- Bench: 127 comparison checks (was 122), driving the real `still_in_host` out
  of the source rather than a copy of it.

## 2.11.1 - 2026-09-09
- **Fixed: every view failed with "module object has no attribute
  LAST_STATS".** 2.11.0 shipped the code that READ the matching statistics and
  not the code that produced them. The statistics are now handed over in a
  dict the caller owns rather than through a module level global, which was a
  poor idea anyway: a global is shared by every view in a run and by every
  window in the session.
- **The bench should have caught it and could not.** `MODULES` was a hardcoded
  list, and neither `arc_compare` nor `arc_diff` was ever added to it - so two
  of the tool's modules had never once been stub-loaded, and every
  `arc_compare.x` reference in the rest of the tool was skipped by the
  cross-module rule because the module was not in the loaded set. Both are now
  derived from the folder, exactly as `LAYOUTS` already was. Verified by
  putting the bug back and watching the rule fire.

## 2.11.0 - 2026-09-09
- **The link is a dropdown above the views table**, not a column of its own.
  There is only ever one link chosen, and a full height list to say so was the
  widest thing in the window for the least information in it. The views table
  now has the whole width.
- **The cloud cap was hiding new elements.** Groups were kept largest-first, so
  one new pipe lost to a big cluster of small movements - which is exactly
  backwards, since a new element is the thing least worth losing. Anything
  containing an element that is not in the link at all is now kept before
  anything merely different, and the cap is raised from 60 to **250** by
  migration.
- **The run says how the two models correspond**: "matched N by UniqueId, M by
  ElementId; K in the view with no counterpart, J in the link with none". All
  of "nothing matched", "everything matched" and "half matched" look identical
  from a cloud count, and this is the line that tells them apart.
- If **not one element** matches, the run says so outright and points at the
  spatial method, rather than reporting the whole view as replaced.
- Comparison by element id confirmed as the default (`match_method = id`,
  `match_by_eid = 1`), and the migration restores both on an older settings
  file in case they had been changed.
- Bench: 122 comparison checks, 74 core checks.

## 2.10.1 - 2026-09-09
- **An element whose id is nowhere in the link is always clouded as new.** No
  tolerance applies to something that was not there before, and the run counts
  them separately: "N element(s) have ids that are not in the link at all".
- **Fixed: a new element could be reported as moved instead of new.** The
  ElementId fallback paired on the id alone. An ElementId only means the same
  thing when the link is a copy of this model - where it is not, a brand new
  element can share an id with something unrelated in the link, and pairing
  them reported it as a move, or as unchanged if the two happened to sit near
  each other. The category now has to agree before an id match is believed,
  and the type too where type checking is on.
- Bench: 121 comparison checks (was 115).

## 2.10.0 - 2026-09-09
- **A second comparison method: spatial.** Chosen in Settings under "How
  elements are matched". No ids are used at all - every host element looks for
  something of the same category sitting in the same place in the link, and
  anything that cannot find one is clouded. A link element nothing claimed is
  clouded as a removal.
- **What it is for.** It does not care how an element came to be there. An
  element deleted and redrawn in the same position is not a change under it,
  where id matching reports one removal and one addition. A model rebuilt,
  copied in from elsewhere, or round-tripped through a format that regenerates
  ids compares cleanly, where id matching reports the entire sheet as replaced.
- **What it costs, plainly.** Two identical elements in the same place are
  indistinguishable, so swapping them is invisible. And without ids there is
  nothing to say two elements are the same one, so a move only reads as a move
  when a like-for-like element is found within the search distance - beyond
  it, honestly, a removal plus an addition. Both are settings.
- **Bucketed, not brute force.** Every host element against every link element
  is over two million comparisons for one view of this size, which is slow
  enough to look like a hang. Elements are indexed by position and only
  neighbours are tested: 1600 against 1600 runs in hundredths of a second.
- Category always has to agree - a pipe standing where a duct used to be is a
  change however well the boxes line up. Type only where type checking is on.
- Bench: 115 comparison checks (was 94), including the bucket boundary, a link
  element being claimed only once, and the two methods reporting opposite
  answers on a model whose ids have all changed.

## 2.9.0 - 2026-09-09
- **Existing revisions can be edited.** Highlight one in Set revision... and
  press **Edit...** - the same form opens, prefilled with its sequence, date,
  description, issued by and to, Show setting and numbering sequence.
- **Issued is written at whichever end makes the rest work.** Turning it ON
  goes last, because an issued revision is read-only and everything after it
  would be refused. Turning it OFF goes first, for the same reason in reverse.
  Editing an issued revision therefore works by unticking Issued in the same
  save.
- The form says so before the Save when the revision is issued, rather than
  reporting a list of fields that would not take afterwards.
- Rows showing a revision are **relabelled after an edit**, so changing a
  description does not leave every row showing the old wording.

## 2.8.0 - 2026-09-09
- **The revision creator carries what Revit's own dialog does**: Sequence
  (shown, set by Revit), Numbering, Date, Description, Issued by, Issued to,
  Issued, and Show - cloud and tag, tag only, or none.
- **Numbering adapts to the release.** Revit 2022 replaced the old Numeric /
  Alphanumeric setting with named numbering sequence elements, and both still
  exist across 2024-2027. The project's sequences are offered where the class
  is there, and the old enum where it is not.
- **Issued is written last, on purpose.** An issued revision is read-only, so
  setting it before the rest silently loses everything that follows it.
- **Every field is read back** and anything that would not take is reported by
  name after the revision is created, rather than being lost quietly.
- Ticking Issued says plainly, in the dialog, that the revision will not then
  be usable for the clouds this run is about to draw.
- **Icons on the sheets and views buttons**, and **Undo moved down beside
  them** - it undoes changes to that table, so it belongs with it rather than
  in the window chrome. All drawn from `Path` geometry, so none can render as
  an empty box.

## 2.7.0 - 2026-09-09
- **Fixed: a row button only changed its own row.** Pressing Categories or
  Revision on one of five highlighted rows changed that one and left the rest
  - which reads as "I cannot set them together". A row button now acts on the
  whole selection when its row is part of one, and on its own row alone when
  it is not.
- **Fixed: the selection was thrown away on every redraw.** The list is
  rebuilt from scratch whenever anything changes, so setting categories on
  five rows left nothing selected to then set a revision on. The selection is
  held across the rebuild.
- **The revision strip is gone from the bottom of the window.** Revisions are
  chosen per row through **Set revision...**, and **New revision...** inside
  that picker creates one in the project and puts it straight onto the rows
  that asked for it.
  The picker does not create it itself: it is a modal dialog, and creating a
  revision is a model write that goes out through the ExternalEvent, which
  Revit raises on that same thread. Blocking a modal dialog to wait for it is
  a deadlock. The details come back and the main window, which is not blocked,
  does the work.
- **Undo button, top right.** Every change to the table is snapshotted first -
  categories, revisions, the lot - and Undo puts the last one back, naming
  what it undid. Bounded at forty steps: it is an undo for a few misclicks,
  not a history of the session.
- **Icons on the header buttons**, drawn from `Path` geometry rather than set
  in a symbol font, so none of them can come out as an empty box on a machine
  without that font.

## 2.6.0 - 2026-09-09
- **The table shows the template name.** A row set from a saved template reads
  the template's name in its Categories column - a count says how many, a name
  says which, and which is what somebody actually chose. A hand-picked set
  that was never saved still reads "N cats", and ticking by hand clears the
  template name rather than letting the row go on claiming it.
- **Set categories... applies to every selected row**, as before, and now
  carries the template name with it.
- **A Revision column, per view.** Each row picks the revision its clouds go
  on, or follows the one chosen at the bottom of the window. "Set revision..."
  assigns to every selected row at once. Issued revisions are listed but
  cannot be picked, since Revit will not put a cloud on one.
- Compare is ready when **every row has a revision**, whether its own or the
  default, rather than requiring the strip at the bottom to be touched.
- The selection rule is shared by both: nothing selected means every row,
  because setting the whole list is the normal case.

## 2.5.0 - 2026-09-09
- **Fixed: Save as... did nothing.** The category picker read `self.palette`
  and nothing ever stored it, so the handler threw, the wrapper caught it and
  wrote a line into the status bar, and the button looked dead. Two more
  copies of the same bug were sitting in `SheetPicker`, where a global replace
  had duplicated the template methods into a class that has none of the state
  they need.
- **New bench rule `unset-attributes`**: every `self.x` read has to be set
  somewhere on the class. It found the two duplicates on its first run. 25
  rules, every one proven by --selftest.
- **Completed offers the sheets too.** The prompt names the sheets the clouded
  views print on and opens both, sheets first so a sheet is what is left in
  front. A cloud lives in a view but the sheet is what anybody wants to look
  at.
- **Fixed: closing the tool jumped to Explorer.** Revit was being raised AFTER
  the window closed, by which point Windows had already picked the next window
  in its own order. The window is owned by Revit, so it is activated FIRST -
  which brings Revit's whole group forward - and closing an active owned
  window hands activation to its owner.
- **Two more ways to find a change**, both read off the element record with no
  geometry and no view:
  - **Placement basis.** `FamilyInstance.GetTransform()` says which way a
    family faces in three dimensions. `Location.Rotation` only knows about
    turning around Z, so it missed a fitting rolled about the run it sits on.
    Compared by dot product against the rotation tolerance.
  - **Mirroring.** A flipped family occupies the same bounding box at the same
    angle and is a real change on a drawing. New kind, **flipped**.
- **Tighter defaults**, applied over an existing settings file by a migration:
  move and size tolerance 5mm to **1mm**, rotation 1 degree to **0.5**, cloud
  grouping 12mm to **8mm** on paper. 5mm was chosen before there was any
  evidence; a 5mm move is a real move on a services drawing.
- Bench: 94 comparison checks (was 85), 72 core checks (was 71).

## 2.4.0 - 2026-09-09
**More changes are found.** The comparison was bounding box centre and size,
which is blind to anything that changes an element without changing its box.
Three cheap signals are added - none of them builds geometry or touches a
view, so none of them costs what the old raster method did.

- **Location endpoints.** A pipe re-routed inside the same envelope, a run
  swung about its own middle, an element flipped end for end: all leave the
  box identical and were reported as unchanged. Compared both ways round, so
  an element simply redrawn from its far end is not a false move.
- **Rotation**, for point-placed families. A fitting turned in place leaves
  the centre where it was and, for a symmetric family, the box too. Tolerance
  in degrees, 1 by default.
- **Parameters**, from an editable list: Reference Level, Offset, Middle
  Elevation, System Type/Name/Classification, Diameter, Width, Height, Size,
  Comments, Mark. Catches a change that moves nothing and resizes nothing.
  Only parameters BOTH sides carry are compared, so a parameter added since
  the link was saved is not a change. The comment names the field that
  changed: "Pipe altered (Reference Level)".
- Two new kinds of change, **rotated** and **altered**, ranked below moved and
  resized so an element still reports one thing.

**Category templates.**

- Save what is ticked as a named template, from the picker. Load one from the
  dropdown, delete one you no longer want.
- Kept in `%APPDATA%\RevoBIM\auto_revcloud_category_templates.txt`, its own
  file rather than a settings key - a template name is typed by a person and
  will contain an `=` sooner or later, and the settings loader splits on the
  first one.
- **Assign to several rows at once**: the views list is multi-select, and
  "Set categories..." applies the choice to everything selected. Nothing
  selected means every row, since setting the whole list is the normal case.
- Bench: 85 comparison checks (was 68), 71 core checks (was 57).

## 2.3.2 - 2026-09-09
- **The clouds scallop outwards.** Which side a revision cloud's arcs bulge is
  decided by the winding order of the outline and nothing else - Revit exposes
  no flag to set it and nothing to read it back from - so the mapping shipped
  as a guess with `cloud_arc_side` as the escape hatch. The guess was the wrong
  way round: a **clockwise** loop is what puts the arcs outside. Now settled by
  having run it, which was the only way it was ever going to be settled.
- `Cloud arcs bulge` still flips it, for a release that disagrees.

## 2.3.1 - 2026-09-09
- **Fixed: every cloud was refused.** The revision was handed to
  `RevisionCloud.Create` as a plain integer - "expected ElementId, got Int64" -
  so all eleven clouds were rejected and the run reported success with nothing
  drawn. The window carries ids as integers because that is what its row dicts
  hold and compare, so the conversion now happens at the one place they reach
  the API rather than at each call site.
- `make_id` passes an `ElementId` straight back, so it is safe to call on
  anything and a caller never has to know which it is holding.
- **Repeated report lines fold into one with a count.** Eleven copies of "a
  cloud was refused" is one fact reported eleven times, and it buried the two
  lines underneath saying what actually happened.
- Bench: 57 core checks (was 53).

The comparison itself was working in 2.3.0 - 1595 elements against 1588, 28
changes found, grouped into 11 clouds. Only the drawing failed.

## 2.3.0 - 2026-09-09
The journal from this crash names the cause outright. After the Compare click
Revit goes into `generateViewSpecificGRep`, then
`updateGReps 11026 elements`, then `P_DRAINAGE_L00 - LEVEL 00: generating
greps`, with free RAM falling - and stops there.

- **The view-scoped collector is gone.**
  `FilteredElementCollector(doc, view.Id)` applies view visibility, and to do
  that Revit generates the view-specific graphics of **everything in the
  view**. On that drainage plan it was eleven thousand elements' worth of
  geometry built purely to answer "which of these are visible". That is the
  memory spike and that is where it died.
- **Scoped with a bounding box quick filter instead**, built from the view's
  crop. A quick filter reads the element record and nothing else: no geometry,
  no view graphics, no regeneration.
- **Visibility is decided per element with cheap tests** - the element's own
  hidden flag and its category's visibility in the view. An element hidden by
  a view filter or a phase setting is no longer caught, so it will be
  compared. Over-comparing is the right way to be wrong here: the worst it
  produces is a cloud round something the drawing does not show, and the
  alternative is regenerating the view to find out.
- **The link is scoped by the same crop**, transformed into the link's own
  coordinates, rather than read whole and thrown away.
- **New bench rule `no-view-collector`** banning the two-argument
  `FilteredElementCollector`, proven by --selftest. 24 rules.
- Elements read per category are logged with a kept count, so the log now
  shows both how many were found and how many survived the visibility tests.

## 2.2.1 - 2026-09-09
- **A link on a closed workset is refused with a sentence.** A workset that is
  closed in the session means the link is not in memory at all, and reading
  elements out of a document in that state is not something to attempt. A
  workset merely set "not visible in all views" is a different thing and is
  fine - the link side is read straight out of the linked document, never
  through a view.
- **Every element read is individually guarded.** One element that will not
  give up its geometry no longer takes the run with it. Nested links, imported
  CAD and elements on a workset closed in the document being read are the
  usual offenders.
- **A category returning more than 200,000 elements is abandoned and named**
  rather than ground through.
- **The log now records the element count per category**, written after the
  collector and before the reads, so the last line says which of the two Revit
  was in.

## 2.2.0 - 2026-09-09
The journal from the second crash ends the instant Compare is clicked, with
nothing after it - Revit died inside the first Revit calls of the job, in the
reading phase. That phase is rebuilt.

- **One collector per category, each guarded.** A single multi-category filter
  fails as a whole on the first category Revit will not accept, and it is not
  always possible to tell in advance which of the model categories those are.
  A category Revit refuses is now skipped and reported by name, and the
  comparison runs on the rest.
- **No manufactured enum values.** The category's `BuiltInCategory` is the only
  route. Reading its id as an integer and casting it to the enum - the old
  fallback - can produce a value that is not a member at all, and a value like
  that going into a native filter is the shape of a hard crash rather than an
  exception. `OST_INVALID` is refused for the same reason.
- **The same bounding box on both sides.** Host elements were measured with
  the view-specific box - clipped to the crop - while link elements got the
  model box, so anything crossing the crop edge read as resized for no reason.
  Both sides use the model box now; the view has already decided which
  elements are present.
- **The `DialogBoxShowing` suppressor is gone.** It was inert in this version,
  it was the last thing the journal recorded, and `OverrideResult` on a dialog
  that does not accept it is a documented crasher.
- **Sheets expand into their views at Compare**, whether or not "Use the views
  on them" was pressed. A sheet left in the list means "all the views on it",
  not "skip this one". A category list set on a sheet carries down to its
  views.
- **Views that cannot be compared are refused with a sentence** - sheets, 3D,
  schedules, legends - rather than being read anyway.
- **Every category is logged as it is read**, on both sides, so if Revit goes
  down again the last line of `auto_revcloud.log` names the category and the
  side it was reading.

## 2.1.3 - 2026-09-09
- **The category picker lists every model category**, read straight off the
  document's category table instead of by counting elements. Counting meant
  walking every element in the project to build the list - slow on a real
  model, and slow inside a modeless window is the worst place for it - and it
  hid categories that are perfectly valid to compare and simply have nothing
  in them yet. The counts and the in-view column are gone with it.
- Failing to read the categories now says so instead of reporting an empty
  list.

## 2.1.2 - 2026-09-09
- **Fixed: running the tool could take Revit down.** A `TransactionGroup` was
  held open across the whole run so that undo would see one step, and the
  progress callback pumps the dispatcher between views. Pumping dispatches
  real mouse and keyboard messages into Revit, and doing that with a
  transaction group open is the rule this extension has written down twice.
  The group is gone: reading and comparing need no transaction at all, and
  each view's clouds get their own with nothing pumped inside it. Undo is now
  one step per view rather than one for the run, which is a great deal better
  than a crash.
- **The bench rule that should have caught it now does.** `no-pump-in-
  transaction` tracked `Transaction` and `SubTransaction` but deliberately
  skipped `TransactionGroup` - true that a group is not a transaction, and
  irrelevant, because pumping inside one is what crashes. Groups are tracked,
  `Assimilate` counts as a close, and `report_row` joins the list of calls
  that pump. Verified by putting the crash back and watching the rule fire.
- **The window is hit-test-invisible while a run is going.** Pumping to move
  the progress bar also pumps input, so every button stayed live during a run
  and a click could land in the middle of it.
- **Every stage is logged, not just the result.** The log is written and
  closed per line, so if Revit does go down mid-view the last entry names the
  view and the stage it was in. Previously nothing was written until a view
  finished, so a crash left no trace at all.

## 2.1.1 - 2026-09-09
- **Fixed: the category list was short.** For a view row the scan was scoped
  to that view, so it listed only what the view happens to draw rather than
  what the model holds. It reads the **project** now, and reports the view's
  count beside the project count - "12 / 340" - so the choice can be made
  knowing both. A category drawn in the view is picked out; one that exists in
  the model but not in this view is still listed, greyed.
- **Fixed: "Use these" would not close the window.** Two things were wrong
  with it. `Close()` alone is not the reliable way to end a `ShowDialog` -
  `DialogResult` is, and both are now set. And every handler in that window
  was swallowing its own exceptions, so a failure inside one left the button
  doing nothing at all with nothing anywhere saying why. They are wrapped now
  and report into the window's own status line.
- **The tick rule is bench-tested.** A shift-click over a run where some are
  already ticked now ticks the whole run rather than flipping each one
  independently, which is what scrambles a mixed selection.
- Bench: 68 comparison checks (was 62).

## 2.1.0 - 2026-09-09
- **Fixed: no links listed, and views could not be added.** One cause for
  both. `self.doc` is a method and the new code left the brackets off, so a
  bound method went into Revit, failed inside, and a bare `except` turned it
  into "no links in the project". Both call sites fixed, both now report the
  failure instead of swallowing it.
- **New bench rule `method-not-called`**, which would have caught it: a bare
  `self.something` passed positionally to another module's function, where the
  class defines `something` as a method. Deliberate callbacks - keyword
  arguments and calls to the class's own helpers - are left alone, or the rule
  would be noise. 23 rules now, every one proven by --selftest.
- **Categories per view.** Every row in the views list carries a Categories
  button. It lists the categories actually **in use** - in that view where the
  row is a view, otherwise in the project - with counts, a search box, and All
  / None / MEP. Click to tick, **shift-click for a run**, ctrl-click to add.
  A view with its own list uses it; the rest follow Settings, and choosing
  exactly the Settings list clears the override rather than freezing a copy.
- **Clouds enclose both positions.** A moved element is clouded round where it
  went **and** where it left, so the cloud does not sit on empty paper beside
  the thing still drawn in the old place.
- **Element ID as a second key.** UniqueId is tried first; whatever is left
  over is matched on Element ID. Some routes to a copy of a model regenerate
  the UniqueId but keep the Element ID, and this rescues exactly those. An
  element matched either way and within the move tolerance is not clouded.
  Switchable in Settings.
- **Cloud offset default is now 10mm on paper** - about 500mm at 1:50 - and
  the grouping tolerance sits beside it in Settings.
- **The theme chip cycles Auto - Dark - Light.** Auto follows Revit's canvas.
  Two states left no way back to following Revit once the chip had been
  pressed, so a theme held by an older version is reset to auto once.
- **Clearout**: every remaining trace of the PDF method is gone - the
  rasteriser options, the Ghostscript path, the stub entries for the PDF
  export API, and the wording throughout. `LAYOUTS` in the bench is derived
  from the folder now rather than listed, so a new window cannot silently drop
  out of the checks.
- Bench: 62 comparison checks (was 49), 53 core checks (was 50).

## 2.0.1 - 2026-09-09
- **Fixed: the window would not open.** `selected_index` and `move` were
  deleted along with the PDF plumbing in 2.0.0 - the calls to them survived,
  so the tool died with AttributeError part way through building its window.
  Both are back.
- **New bench rule, `self-methods`, which would have caught it.** Every
  `self.something()` call now has to resolve to a method defined on the class,
  or to an attribute the class assigns. The `globals` rule walks module level
  names and the stub load imports each module, but neither of them opened a
  class to check that the methods it calls itself still exist - so a refactor
  that deletes a helper left every call to it intact and silent. 22 rules now,
  every one proven by --selftest.

## 2.0.0 - 2026-09-07
**The method has changed. PDF comparison is gone.**

Instead of rasterising a PDF and the sheet and comparing ink, the tool now
compares the model elements in a view against the same elements in a linked
model - a previous version of the model, linked into the project.

- **Elements are matched on UniqueId**, which survives a Save As, so the
  previous version carries the same id for the same element. That is what
  makes this exact rather than a guess. An element deleted and redrawn gets a
  new UniqueId and shows as one removal plus one addition, which is honest -
  that is what happened.
- **Five kinds of change**: added, removed, moved, resized, retyped. One
  element reports one thing, the most significant. Move and size tolerances
  are in model millimetres.
- **Clouds carry a description** in their Comments parameter - "3 pipes moved,
  cable tray added" - grouped by category and kind, most numerous first, and
  trimmed with "and N more" so it still fits a schedule column.
- **Clouds are drawn in the view**, in the view's own coordinates, so they
  follow the viewport. Grouping and clearance are in paper millimetres, so a
  cloud looks the same at 1:50 as at 1:100. Merging is transitive, so a chain
  of changes along a run becomes one cloud.
- **The window**: the left panel is now the Revit links in the project - click
  the one holding the previous version. The right panel takes sheets, then
  "Use the views on them", or views directly with "Add views..." for anything
  not placed on a sheet. Revisions, Compare, progress, the debug bar and
  Completed are unchanged.
- **Gone**: PDF browsing, the rasteriser and Ghostscript, registration, ink
  density and thresholds, the annotation guard, viewport masking and the page
  origin - none of it is needed when the comparison reads the model. Twenty
  settings went with it; sixteen remain.
- Settings version 4 resets the grouping distances, which were tuned against
  paper density cells and mean nothing now.
- Bench: `bench_compare.py` is new, 49 checks over the whole comparison;
  `bench_logic.py` rewritten, 50 checks over settings, categories and the
  report; `import_check.py` still 21 rules, every one proven by --selftest.

## 1.7.0 - 2026-09-07
- **Fixed: the page origin was an unchecked guess.** It came from the FIRST
  title block found on the sheet. A sheet with a second title block instance -
  a revision block in the same category - or one whose block is not the full
  paper size gave an origin that put every viewport off the page. The tool
  then found the mask empty, quietly compared the whole page, and clouded the
  title block along with everything else. That is the "the viewport areas did
  not land on the page" line in the log, and it is why one sheet made forty
  clouds while the sheet beside it made one.
- Every plausible origin is now tried - each title block largest first, all of
  them together, and the sheet outline - ranked by which one matches the size
  of the page that was actually rasterised, which is a measured fact rather
  than an assumption, and then kept only if the viewports really land on it.
  Each candidate and its coverage is reported.
- **A big difference in ink between the PDF and the sheet is now called out.**
  Two prints of the same drawing carry about the same amount of ink; 7.1%
  against 4.6% does not, and every cloud after that is noise. The run says so
  instead of drawing forty clouds and leaving it to be worked out.
- **Debug bar** along the bottom, collapsed by default, opened by the Debug
  button in the footer and by itself when a sheet fails. It holds the settings
  the run used and every line it produced, with Copy and Open log folder.
- Bench: 236 logic checks (was 228).

## 1.6.3 - 2026-09-06
- **"A managed exception was thrown by Revit" now says where it came from.**
  That message names neither the call nor the reason. The report carries the
  .NET exception TYPE and the module, line and function it was raised in, and
  the full traceback still goes to `%APPDATA%\RevoBIM\auto_revcloud.log`.
- **The PDF export retries with plainer options instead of losing the sheet.**
  Revit throws at `Export` rather than when an export option is set, so
  guarding each property assignment - which is what this did - catches
  nothing: a release that will not accept one property failed the whole sheet.
  It now tries the full options, then without zoom and quality (the two most
  often refused), then name only, and reports every combination it tried and
  what each was answered with.
- The export failure message lists what was tried rather than repeating
  Revit's generic sentence.
- Bench: 228 logic checks (was 217), including the retry order and that each
  fallback is strictly plainer than the last, so a retry cannot loop on the
  same refusal.

## 1.6.2 - 2026-09-06
- **The settings window scrolls and stretches.** The body is in a ScrollViewer,
  and the window carries the same eight resize grips as the main window - a
  borderless AllowsTransparency window has nothing hit testable in its frame,
  so WPF can never resize it however ResizeMode is set, and it has to bring
  its own. Chrome already knew how to wire them; the layout simply did not
  have any.
- The minimum size drops to 620 x 380 so it fits a laptop, and the default
  opens a little larger.
- The scroll bar is themed by the implicit ScrollBar style already in
  Theme.xaml: a ScrollViewer builds its own bars and there is no name to reach
  them by, so a keyed style would not have applied.

## 1.6.1 - 2026-09-06
- **Lines and Detail Items added to the compared categories**, alongside
  Generic Models which was already there, so schematics can be compared. A
  riser or a control diagram is drafted rather than modelled - without these a
  schematic sheet has no elements on it at all and nothing to compare.
- They are drafting categories, so on a modelled plan they also pick up detail
  lines and hatching. That is usually wanted; take them out of the list for a
  sheet where it is not.
- **An untouched category list follows the defaults; an edited one is left
  alone.** Every set of defaults the tool has shipped is remembered, and a
  saved list still matching one of them is quietly brought up to date. A
  migration that reset the key would have thrown away a list somebody had
  spent time on to give them three names they could have typed themselves.
- An empty category list falls back to the defaults rather than leaving
  nothing to compare.
- Bench: 217 logic checks (was 210).

## 1.6.0 - 2026-09-06
- **Tags, text and dimensions no longer generate clouds.** The isolated export
  already said where the services ARE, which dropped a change out on its own in
  a note. It could not drop a change sitting on a tag printed next to a pipe -
  and tags are printed next to pipes for a living, so those still came through.
  The other half is now built too: ink on the full sheet that is not one of the
  listed elements is annotation, and a change there is dropped even when it is
  within reach of a service. A change on the element ink itself is always kept,
  so a pipe under a tag is still a pipe.
- The comparison is deliberately still made against the FULL new sheet, with
  the isolated export used as a mask. Comparing the isolated export directly
  against the PDF cannot work: the PDF carries the tags, text and dimensions,
  so every one of them would read as removed.
- New settings: **ignore changes explained by tags, text and dimensions** (on)
  and **annotation blocks a change within N mm** (1.5mm).
- **Fixed: closing the tool jumped to File Explorer.** The window is owned by
  Revit, so closing it should hand activation back - but browsing for the PDFs
  opens a shell dialog, and Windows then hands activation to an Explorer window
  the user already had open. Revit is now raised explicitly on close, through
  the managed AppActivate on Revit's own process id rather than P/Invoke,
  guarded because the assembly moved between .NET Framework 4.8 and .NET 8.
- Bench: 210 logic checks (was 202), including a re-worded tag beside a pipe
  that must not cloud, and the same change with the guard off that must.

## 1.5.0 - 2026-09-06
- **Fixed: an unchanged sheet came back clouded.** Two compounding causes, both
  now covered by bench tests that fail if either comes back.
  - Cell **densities** were compared against a threshold. Two prints of the
    same line never produce the same densities - anti-aliasing, line weight and
    a fraction of a cell of registration error all move the numbers - and a
    density difference cannot tell "3% darker" from "not there any more". On a
    synthetic re-print of an identical drawing this flagged 560 cells and drew
    a cloud.
  - Registration **believed a scale inside its own noise**. An ink bounding box
    is only accurate to about a cell at each edge, so a one cell difference in
    the detected extent - normal between two prints - became a 1.0097 scale.
    Resampling by it shifted every line on the drawing: 650 changed cells and
    five clouds on a sheet nobody had touched.
- **Ink is now compared with a distance tolerance**, which is how drawing
  overlay tools do it. Ink counts as changed only when there is no ink within
  the tolerance on the other page. A line that shifted a hair still finds
  itself and is not a change; a pipe that moved 200mm does not, and is.
  `Match tolerance` (1mm default) replaces `Change threshold`.
- **A scale within 3% of 1 is taken as 1**, and the pages are then lined up by
  the centre of their content rather than a corner - a centre averages the edge
  noise out, a corner adds it in. A genuine fit-to-page print is well outside
  3% and is still corrected.
- Additions and removals are counted separately and both reported.
- Bench: 202 logic checks (was 189), including an unchanged sheet that must
  draw no clouds, and real changes that must still be found.

## 1.4.0 - 2026-09-06
- **Only elements are compared, not text.** The second export no longer just
  hides annotation - it hides everything except the categories you list, so
  the comparison is against the services themselves. A revised note, a moved
  tag, a filled-in revision schedule and a re-dated title block are no longer
  changes.
- **Categories to compare** is a list in Settings, one per line, seeded with
  the MEP services: pipes, ducts, cable trays, conduits, mechanical and
  electrical equipment, electrical fixtures, lighting, data, fire alarm,
  communication and security devices, sprinklers, air terminals and the
  fittings, accessories and insulation that move with them. A "Restore the MEP
  list" button puts it back without resetting anything else.
- Matching is by category **name**, so a name this release or this model does
  not have is reported and skipped rather than failing. The run says how many
  of the listed categories exist, names the ones that do not, and refuses to
  filter at all if none of them do rather than clouding nothing.
- **A change counts within N mm of an element** (default 2mm), so a line that
  moved is caught at both its old and new position without widening the cloud.
- **Things that were removed** is now a choice: cloud it if near an element
  (default), always, or never. Where ink has gone there is nothing left to
  identify and the old PDF has no categories in it, so a removed pipe and a
  removed note look the same - this is the honest lever for that.
- Bench: 189 logic checks (was 166), covering the element filter, all three
  removal modes, the reach, and the category list round trip.
- Fixed a bench rule that had gone blind: `settings-keys` read DEFAULTS with
  `literal_eval`, which fails the moment a default is computed rather than
  written out, and it then reported the table unreadable and checked nothing.
  Keys are read off the AST now.

## 1.3.1 - 2026-09-06
- **Completed closes the tool.** Pressing Completed now ends the session either
  way: answer no to opening the sheets and the window closes straight away;
  answer yes and it closes once the sheets are open. Answering no means "I do
  not want to look at them now", not "keep the window open" - there is nothing
  left to do with it once a run has finished and been reported.
- Closing is **deferred until the job returns** when the sheets are being
  opened, because the window cannot be torn down while a job still holds a
  reference to it and is calling back on Revit's thread. It also closes if
  opening fails, after the failure has been reported.
- No change to the easter egg, so `lib/` is not in this package.

## 1.3.0 - 2026-09-06
- **Clouds hug their changes.** Clustering merges nearby changes, which is
  right, but two changes at opposite ends of a viewport came out as one
  rectangle covering everything between them. Groups are now split on any
  empty band wider than the merge distance, recursively, so each cluster gets
  its own cloud.
- **Tighter defaults**, applied over an existing settings file by a migration
  rather than being ignored: density cell 2mm to **1.5mm**, merge distance
  8mm to **5mm**, cloud offset 4mm to **2mm**.
- **Cloud scallop size** is settable (`Cloud scallop size, mm on paper`).
  Opt-in and off by default, because arc length lives on the revision cloud
  TYPE - setting it re-draws every cloud already on that type in the project.
  It is written once per run, read back, and reported.
- **Completed button.** Once a run finishes and something was clouded, a
  Completed button appears at the bottom right. It asks whether to open the
  clouded sheets in Revit and, on yes, opens each one - through the same
  ExternalEvent as everything else, since a modeless window cannot change the
  active view directly. Sheets are held by id, not as Element handles.
- Bench: 166 logic checks (was 155).

## 1.2.0 - 2026-09-06
- **Fixed: the two pages were not compared like for like.** Up to 1.1.0 the old
  PDF was squashed straight into the cell grid sized from the *new* sheet - a
  blind whole-page stretch. A different paper size, or a fit-to-page print
  (content shrunk inside its own page with a margin), mis-scaled every line on
  the drawing, and no amount of the whole-cell shift could bring it back.
- **Registration is now on the content, not the page edge.** Each page gets a
  grid sized from its own paper, so a cell is the same real millimetres on
  both. The inked bounding box - dominated by the sheet border and title
  block, which are identical between issues - anchors the old page onto the
  new one with independent x and y scale plus offset. The whole-cell search
  then runs as a fine tune.
- **Fixed: a zero result could not be explained.** Several stages could take
  the count to zero and every one of them reported the same thing, "no change
  found". Cell counts are now carried through each stage and a run that finds
  differences but clouds nothing says which stage removed them.
- **Blank-page guards.** A sheet or PDF that rasterises to a blank page is
  reported instead of silently agreeing with whatever it is compared against.
  A model-only export that comes back blank no longer filters every change
  away - the annotation filter is skipped and the skip is reported. A viewport
  mask that lands off the page falls back to the whole page.
- **Fixed a cross-engine bug the bench caught:** `int(round(x))` rounds a half
  to the nearest even number on CPython 3 and away from zero on IronPython
  2.7, so cell indices differed between the bench and Revit. All cell indexing
  goes through `round_half_up`.
- **Easter egg wired in**, per the extension's standing rule: the header
  wordmark is `x:Name="RevoBimLogo"`, `egg_hook.attach` runs after the window
  loads inside a try/except, and a new bench rule fails any rebuild that
  forgets. The rule imports the canonical `rule_easter_egg_wired` from
  `lib/revobim/egg/egg_rule.py` when the tool is checked inside a full
  extension tree, so every tool is held to one definition.
- Bench: 21 import rules (was 20) and 155 logic checks (was 121).

## 1.1.0 - 2026-09-05
- **Renamed from Auto Recloud to Auto RevCloud.** The folder is renamed too,
  because pyRevit names a ribbon item after its folder - **delete the old
  `Auto Recloud.pushbutton` folder**, or two buttons appear and the load can
  fail with "The name already exists". The settings, log and error filenames
  under `%APPDATA%\RevoBIM\` are renamed to match; nothing is lost because
  the tool had not yet run successfully, so no settings file existed.
- **Cloud arcs bulge outwards.** Which side the scallops sit on is decided by
  the winding order of the sketched outline, not by any API flag, so every
  loop is now measured in the view's own basis and reversed when it is the
  wrong way round. Measured in the view's basis rather than world XY on
  purpose: a section or a rotated crop puts the same model-space loop the
  other way round on screen.
- **`Cloud arcs bulge` setting (Outwards / Inwards).** Revit exposes nothing to
  read the convention back from and it cannot be settled on the bench, so if
  the first run comes out scalloped inwards, flip this rather than waiting for
  a rebuild.
- **A real progress band**, appearing only while a run is going: sheet N of M,
  the sheet number and name under process, the stage (Exporting / Rasterising /
  Comparing / Clouding) and the percentage, over a bar that now advances
  *within* a sheet rather than jumping a whole sheet at a time.
- Bench: 121 logic checks (up from 108), covering the winding maths - signed
  area, the reverse decision both ways round, idempotence, and degenerate
  loops that must not be flipped on a rounding error.

## 1.0.0 - 2026-09-05
- First release. Modeless window owned by Revit: PDFs on the left (browse, one
  row per page for multi-page files, sorted by file name), sheets on the right
  (add from a picker, auto select by the sheet number in the file name, auto
  match, up / down / remove), revisions along the bottom with an add form,
  Compare Sheets in the footer lit only when every row has a partner and an
  un-issued revision is picked.
- Compare: each sheet is exported to PDF at 100%, both PDFs are rasterised
  through Revit's own PDF import (Ghostscript optional), binarised, read as a
  grid of ink-density cells, registered against each other, and every group of
  changed cells within the merge distance gets one revision cloud with an
  offset. Clouds go inside the view where the change sits in a viewport, via
  the viewport's model-to-projection transform, else on the sheet.
- Model-changes-only mask: a second export with annotation hidden decides
  whether a change is annotation-only and drops it.
- Dark and light, following Revit's canvas theme by default (2024+), with a
  header chip to override; full screen, resize grips, staged loading with a
  Revit dialog naming the failing stage.
- Results are reported in three kinds - info (silent), note (opens the window)
  and error - so a clean run does not interrupt. Registering a PDF a millimetre
  against its sheet is normal and is filed as info.
- Bench: `import_check.py`, 20 rules, every one proven by deliberately breaking
  it; `bench_logic.py`, 108 checks of the matching, grid, clustering and paper
  geometry rules against the real arc_core code under CPython.
