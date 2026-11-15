# Family Find & Replace — changelog

All notable changes to this tool. Semantic versioning: MAJOR for a change in
what the tool does to the model, MINOR for new capability, PATCH for fixes.

## 1.7.0

### Added

- **Shrink to taskbar on every window** - the main window, the adjust window
  and the confirm / completion prompt. A shrink button in the top right,
  beside close, slides the window down to the bottom of its screen like a
  drawer closing, leaving only its header bar floating 8px clear of the
  taskbar so Revit can be seen. The button turns into a **green up arrow** that
  slides it back up. A double click on the bar, Enter or Esc reopen it too, and
  **Ctrl+Shift+H** works both ways. Built to the house standard in the RevoBIM
  theme reference, matching Pro Sheets, Filter Manager and View Manager.
  - The parked bar stays draggable; moved, the window opens upward from where
    the bar now sits, kept on that screen.
  - A dialog takes the main window down with it and parks above it; the main
    window takes an open adjust window down with it. Bringing either back
    brings both, and closing a parked dialog brings the main window back.
  - Several parked bars stack 4px apart.
  - Held still while a run is going.
  - The prompt is modal: shrinking it shows the model, but Revit stays locked
    until it is answered.
- **`ffr_drawer.py`**, the one Drawer every window uses. Top and Height eased
  together on a 15 ms DispatcherTimer, 280 ms, cubic ease out. Handles each of
  the five things the standard says break a drawer: the animation released on
  both properties, MinHeight and SizeToContent relaxed and put back, the body
  pinned during the slide, the resize grips parked with it, and Enter / Esc /
  double click reopening rather than answering a hidden window.
- **`import_check.py` drawer rules**: every window layout has a header bar and a
  shrink button styled `BtnShrink`; every function that opens a window builds a
  Drawer for it; every shrink button is handed to a Drawer; and the drawer
  releases the animation on Top and Height, from both its finishing and
  relaxing steps.
- **`import_check.py --selftest`**: copies the tool to a temporary folder,
  breaks it one way at a time and confirms the matching rule fails. Eight
  breaks - six for the drawer rules, the 1.6.1 missing-import bug, and a
  StaticResource in a layout. All caught.
- **`bench_logic.py`**: fourteen drawer checks - the ease, parking and
  stacking, a second monitor above the primary, a dragged bar reopening upward,
  the parked state, the release, the vetoes, reopening exactly as it was,
  owners and dialogs going down and coming back together, the keys, the double
  click, a failing frame, and being held during a run. The Drawer class is
  driven against a stand-in window that vetoes and holds like WPF and only
  ticks when pumped. Eighteen new deliberate breaks; all 35 caught.

## 1.6.2

### Fixed

- **Detail items still did not land where the import symbol was.** The cause
  was upstream of the centring: the import's `GetTransform()` was asked first
  for its placement, and for an import symbol it can come back with no
  rotation and the wrong origin. With the angle read as 0 for a turned symbol,
  every placement rule built on it was off - the 1.6.1 centre measurement
  included. An identical-geometry detail item still looked right, because
  middle to middle with identical shapes does not need the angle.
- The insertion point and rotation now come from **the block's own placement
  transform**, read from the import's geometry - the transform its linework is
  drawn by. A wrapper instance round a single block is stepped through and the
  two placements combined; a block that holds anything besides one other block
  keeps its own insertion. The import's total transform, then its instance
  transform, are the fallbacks.

### Changed

- **Insertion point to insertion point is now the default** in drafting views,
  the same rule a family-for-family swap uses: the detail item's origin goes on
  the block's AutoCAD base point, turned to the block's rotation. Build the
  detail family with its origin where the block's base point is.
- After placing, the detail item's own placement is read back. More than 0.5 mm
  from the base point, or more than 0.01 degrees from the block's rotation, and
  it is moved or turned by exactly what is left. The report confirms it or names
  the ones that would not land.
- **Line up centres instead of insertion points** - a new option, off by
  default - keeps the middle-to-middle placement for families whose origin does
  not match the block's base point. It now takes its angle from the same block
  placement.
- The adjust window turns detail items about their insertion point, or about
  their centre when centres were lined up.
- The debug log now lists, for every symbol, each route to its placement with
  the origin and angle it gave, so a wrong route shows up at once.

### Added

- `bench_logic.py`: five new checks - the block placement found from geometry,
  through a wrapper and not into a mixed block; that route asked first; the
  angle unchanged by DWG unit scaling; a left-over turn taken the short way;
  and insertion point to insertion point exact for any shape, mirrored or not.
  Five new deliberate breaks, including putting the 1.6.1 order back; all 17
  breaks caught.

## 1.6.1

### Fixed

- **A detail item of a different size or shape to the import symbol did not
  land on the symbol's centre.** The centring step read the turned detail
  item's geometry once, moved it once, and never checked. When that read did
  not come back as expected the move did nothing - so a detail item whose
  origin happened to sit where the block's base point was looked right, and
  every other shape stayed off. Centring now runs in four steps:
  1. The detail item is placed **square to the view** and Revit's own bounding
     box read. Square, the box is the item's own extents, so this gives exactly
     where its middle sits from its insertion point, for any size and shape.
  2. It is turned, and mirrored if the block was, about its insertion point.
  3. Where its middle now sits is **worked out** from that offset, turned and
     mirrored in the same order, and the item moved onto the symbol's middle.
  4. It is **measured again**. More than 0.5 mm off and it is moved by what is
     left, once, then measured again. Anything still off is named in the
     report with how far.
- **Symbol centres are measured the same square way.** The symbol is turned
  square for a moment inside a rolled-back sub-transaction and its bounding box
  read, then the middle turned back through the symbol's angle. Reading the
  linework in its own axes stays as the fallback.
- **Bounding boxes now honour their own Transform.** Min and Max are in the
  box's frame; it was being ignored.
- **Preview would have thrown in a drafting view.** It used `Transaction` in
  `ffr_ui.py`, which never imports it - caught in the build, before shipping.

### Added

- **Debug log** at `%APPDATA%\RevoBIM\FamilyFindReplace_debug.txt`, one line
  per symbol: centre and route, angle, handedness, the detail item's offset,
  the move, the check, and the distance left. The run report gives the path.
- The run report confirms *All N checked after placing: each sits within 0.5mm
  of its symbol's centre*, or names the ones that do not.
- **`import_check.py` flags any name a module uses but never imports or
  defines.** The missing `Transaction` above parsed, passed the stub import,
  and would only have thrown in Revit on that line. Proved by putting the bug
  back and confirming the message.
- **`bench_logic.py` runs the whole centring sequence** for detail items of a
  different size and shape to the symbol - origins at a corner, centred, and
  well outside the drawing - at seven angles, mirrored and not, and checks
  every one lands on the symbol's centre, with the truth worked out from the
  family's own extents. Four new checks, five new deliberate breaks; all twelve
  breaks caught.

## 1.6.0

### Added

- **Drafting view mode.** When the active view is a drafting view, the tool
  swaps **import symbols** (AutoCAD blocks brought in as imports) for **detail
  items**. The window switches by itself as you change view - Find lists the
  import symbols found in views, Replace with lists detail item types, and the
  two pick buttons become *Select import symbol in the view* and *Select detail
  item in the view*. An orange chip in the scope bar says which mode is on.
  Changing view between a drafting view and anything else re-reads both lists,
  because a pick made in one mode means nothing in the other.
- **Centre to centre.** Each detail item lands on the middle of the symbol *as
  drawn*, not on its AutoCAD base point. The centre is measured from the
  symbol's own linework in the symbol's own axes, which is exact at any
  rotation; measuring in world axes instead puts a rotated, lop-sided block up
  to 52 mm off in the bench case. After placing, the detail item's own middle is
  measured the same way and the item moved onto the symbol's middle, so a
  detail item drawn off its origin still lands centred.
- **Rotation matched.** The symbol's rotation is read from its own X axis in
  the view's terms and the detail item is turned to the same angle about the
  view's normal, through the centre.
- **Mirrored blocks matched**, on by default: *Mirror to match blocks mirrored
  in AutoCAD*. The detail item is turned, then mirrored across the line its own
  X runs along, which reproduces the block's handedness exactly. Mirroring is
  judged in the view plane, so a block merely flipped through the sheet - which
  looks the same on paper - is not treated as mirrored.
- **The electrical section greys out** in a drafting view - the whole card,
  chip reading *Circuits retained? : n/a* - since nothing there carries a
  circuit or a wire. *Associate with the nearest level below* is hidden, as a
  drafting view has no levels. *Replace inside groups* is disabled.
- The adjust window, opened after a drafting run, **turns each detail item
  about its own centre** and the view's normal, so it stays on its symbol's
  centre, and hides the Z offset, which a drafting view has no depth for.
- Preview and the run report say how many symbols are rotated and mirrored,
  which views are involved, how each centre was measured, and warn where a
  symbol had no linework to measure and fell back to its base point.
- **`bench_logic.py`**, the logic bench this tool was missing. It lifts the
  drafting functions out of `ffr_core.py` and runs them under plain Python -
  centre, rotation, mirror detection, mirror reproduction, staying in the view
  plane, drafting-view detection, import labels - and `--selftest` breaks each
  one on purpose and confirms its check catches it. All seven do.

### Changed

- The two sides of the window now hold separate indexes. In a model view they
  are the same one; in a drafting view they are not.
- `import_check.py` skips `bench_logic.py`, which runs at a desk under CPython
  and is allowed to print.

## 1.5.2

### Changed

- **The progress bar is now a 26px band rather than a 3px hairline**, sitting
  under the header across the full width of the window.
- **It says how much is left, not how much is done**: the label reads
  `62%  -  45 of 120 left  -  75 of 120 elements`. On a long run the useful
  question is how much more of it there is. The plain percentage stays in the
  header as well.
- The label is white over the bar, which reads on both the filled blue and the
  empty track behind it, and it is centred so it stays legible whatever the
  fill has reached.
- The first paint is no longer swallowed by the whole-percent guard, so the bar
  appears empty at 0% when a run starts rather than appearing only once some
  work is already done.
- Minimum window height 730 to 750, for the taller band.

### Notes

- `BrdLine` was used for the band's edge while writing this and does not exist
  in `Theme.xaml`. The bench check named it — verified again on purpose by
  putting it back and confirming the message.

## 1.5.1

### Fixed

- **"Replace inside groups" found nothing and reported "nothing inside it would
  replace".** Group members were matched against the **replacement** type id
  rather than the source type id - so it was looking inside the group for
  elements that had already been swapped, found none, and correctly reported
  that none were there. The source types are now derived from the selection and
  passed through. `survey_groups` was being handed the same wrong id, though it
  had not been using it.
- Nothing was damaged by the bug: the group was ungrouped, matched nothing, and
  the whole thing rolled back, which is why the run reported 0 of 1 rather than
  leaving a mess.

### Changed

- **The group routine now takes the fast route by default.** One instance of
  each group type is taken apart, changed and put back as a new type, and the
  other instances are moved onto that type - so the swap runs **once per group
  type instead of once per instance**. On a type placed forty times that is
  forty times less work.
- **The fast route is checked, not trusted.** Regrouping computes a fresh group
  origin, and moving an instance to a type whose origin sits elsewhere can shift
  its contents. A witness point is taken from each instance before it is
  touched, and the first reassignment is compared against it. If anything moved,
  the whole group type is rolled back and rebuilt the careful way - every
  instance taken apart and put back in place, where identical inputs give
  identical origins and nothing can move. The report says when this happened
  and why.
- The confirmation now quotes how many of the family sit across **all**
  instances of each affected type, not only the ones the scope picked up, since
  that is the actual work.

## 1.5.0

### Added

- **A progress bar across the top of the window, with the percentage in the
  header** and the running count on the status line, matching Fire Damper Wall
  Type Push. It runs for both Preview and Replace and hides itself again after.
- The bar is drawn as **two star-sized grid columns** rather than a width in
  pixels, so the filled part is a ratio and is right at any window width with
  nothing measured.

### Changed

- **The run is now chunked into several transactions inside the transaction
  group**, 25 elements each, with one transaction per group type. This is what
  makes the progress bar safe: **the dispatcher must never be pumped between a
  transaction's Start and Commit** — doing it to repaint a progress line can
  leave the write with nothing committed, which cost Fire Damper a release.
  Progress is only ever reported between transactions, with nothing open.
  Undo still sees one step, because the transaction group is unchanged.
- Elements are now held as **ids and re-fetched at the point of use**, since the
  run spans several transactions and a handle captured before the first is not
  something to lean on after the third.
- The window is made **hit-test-invisible while a job runs**. Pumping the
  dispatcher also pumps input: it dispatches real mouse and key messages, so
  without this the window can be clicked, or closed, part way through a run.
- The bar **repaints only when the whole percent moves**. At 5000 elements that
  is 101 repaints across 200 transactions rather than one per element — pumping
  on every element costs more than the work being measured, and the bar cannot
  show a fraction of a percent anyway.
- The external event handler now **always releases the window** in a `finally`,
  so a job that throws part way through cannot leave the tool reading as frozen
  with no way back.

## 1.4.0

### Added

- **Replace inside groups**, on the Placement card, **off by default**.
  Elements inside a group are otherwise left alone, because they cannot be
  modified in place.
- **A confirmation before the run** when more than five group instances are
  involved: *"This element is within N groups. Are you sure? This could take
  some time."* — with the number of group types alongside, since that is what
  decides the work.
- **A completion prompt** after any run that took groups apart, saying how many
  group instances were updated, how many elements were replaced in total, and
  naming any groups that were left alone. An ordinary run still reports in the
  window without anything to dismiss.
- A themed prompt window, `FamilyFindReplacePrompt.xaml`, with a fallback to
  Revit's own dialog — a confirm step that answers itself is indistinguishable
  from a button that does nothing.

### How groups are handled

There is no edit-group-in-place in the API, so for each affected group type:
every instance is ungrouped, the ordinary swap runs on the members of each,
each set is regrouped, and they are all put back onto one shared type which is
renamed to the original name. The old, now empty, type is deleted.

Every instance is done rather than only the first, because regrouping computes
a group origin from the members it is given: doing identical work on identical
member sets gets identical origins, where regrouping one instance and
reassigning the others to that new type can shift their contents by the
difference between the two origins. It is more work, which is what the
confirmation is warning about.

Each group type sits in its own sub-transaction — taking a group apart and
putting it back is one move, and half of it done is worse than none of it. A
type that fails rolls back whole and is reported by name.

### Fixed

- **The bench check was only looking at a hardcoded list of layouts.** A layout
  added later was checked by nothing at all, silently — which is the exact
  class of gap `import_check.py` exists to close. It now reads the folder.
  Verified by injecting a `StaticResource` into the new prompt layout and
  confirming the check catches it.

### Changed

- Minimum window height 700 to 730 for the extra checkbox.

## 1.3.0

### Added

- **Retain tags pointing at the originals**, on the Placement card, on by
  default. Each tag is re-pointed at the replacement rather than recreated
  where the API allows it, which keeps the tag's head position, its leader and
  any elbow that was dragged by hand. Recreating an equivalent tag in the same
  view, at the same head position and with the same leader state, is the
  fallback, and it keeps the position but not the elbow.
- **Reconnect wires to the replacement**, on the Electrical card, on by
  default. Circuits and wires are separate things: putting the replacement on
  the circuit says nothing about the `Wire` elements drawn on the plan, which
  stayed pointing at the original and dangled once it was deleted. Each wire
  end is now disconnected from the original's connector, connected to the
  replacement's, and the wire's own end vertex dragged onto the new connector
  so the wire is drawn to where the device actually is.
- Both are counted in the run report, and Preview says how many tags and wire
  ends are involved before anything is written — including a warning naming
  what will be lost if either option is off.

### Changed

- Minimum window height 660 to 700, so the parameter list stays usable now the
  two new checkboxes take a little of the column.

### Notes

- Both transfers happen **before the original is deleted**, and that ordering
  is the whole thing: Revit removes a tag whose only referenced element has
  gone, and leaves a wire end dangling. Afterwards is too late for either.
- Wire connectors are matched by electrical system type where the replacement
  offers more than one, falling back to the first electrical connector.

## 1.2.1

### Fixed

- **"Can't use this type of host" when swapping a face based family for one
  that is not.** The placement cascade ended with a route that passed the
  *original's* host — the ceiling or wall — to the replacement, whatever the
  replacement was. A level based or work plane based family cannot take a host
  element, and that is the exact message Revit gives when you offer it one.
  Routes are now chosen from the replacement's own `FamilyPlacementType`, and a
  host element is only ever offered to a family whose placement type takes one.
  Applies to every category; nothing here is category-specific.
- **No work plane route existed.** Most families authored as "not face based"
  are in fact `WorkPlaneBased`, and they need a plane to sit on — neither the
  level overload nor the bare point overload gives them one, so they failed
  even once the host was out of the way. A horizontal `SketchPlane` is now
  created at the insertion point and used for those, cached by elevation so a
  run over three hundred fittings leaves three or four planes behind rather
  than three hundred.
- **A failing route could take the whole run with it.** A route can return an
  element and only then have Revit post an error at regeneration, which landed
  on the run instead of that attempt. Each route now sits in its own
  sub-transaction with a regenerate inside it, so the error surfaces where it
  can be rolled back and the cascade genuinely gets to try the next one.
- Added a **host face** route, so a face or work plane based replacement can
  land on the surface the original sat on rather than a flat plane.

### Added

- The run report says **which route placed the elements** and how many went by
  each. When nothing places, it lists *every* route tried rather than only the
  last — which routes were even attempted tells you what placement type the
  family reported, and that is usually the answer.

## 1.2.0

### Changed

- **The mode switch is gone.** There is no longer a "from lists" versus
  "manual selection" choice. Each side — Find and Replace with — carries both:
  a searchable category / family / type list, and a **Select family in the
  model** button that sets that side from one click on an element. Pick either
  side either way, in either order.
- **Each pick is independent and single.** One `PickObject` per button, so a
  click completes it. Picking sets the family and type, not that one element.
- **Scope moved to the top of the window** and now defaults to **Active view**.
  Entire project and Current selection are the other two. Replacing across a
  whole project is the wider blast radius, so it is the one you ask for.
- **Parameter values to retain now spans the full height of the window**,
  alongside both family columns and the report. The list is roughly 365px at
  the default window height against 226 before, and stays usable at the
  660px minimum.
- **Nothing is ticked by default.** Retention is a deliberate choice per run;
  a value carried across silently is the kind of thing noticed three drawings
  later. `DEFAULT_RETAIN_TOKENS` is now empty — put names back into it to have
  some pre-ticked again.
- **The electrical section is compact** — a chip and one line, no heading row
  and no acknowledgement tick.
- **The electrical chip is a toggle, not a verdict.** It reads
  **Circuits retained? : On** in solid green, or **: Off** in solid red. On is
  the default. Off on a circuited selection is the destructive setting, so it
  is the one that looks alarming.
- Whether the two families actually agree electrically now reads in the line
  beneath the chip rather than changing the chip itself. On but mismatched
  turns that line red and says circuited elements will be left alone rather
  than swapped — no circuit is destroyed either way.
- The run gate no longer depends on an acknowledgement tick; the per-element
  refusal added in 1.1.0 makes the circuit safe without one.
- Circuits dropped because the toggle was off are counted and reported as a
  failure line, since that is the one setting here that loses something an
  undo will not bring back.

## 1.1.0

### Fixed

- **Circuits were being lost on the swap.** Three faults, compounding:
  - `AddToCircuit` was only ever called with a `List[ElementId]` or a bare
    `ElementId`. Several releases expose only the **`ElementSet`** signature,
    so the call threw, the exception was swallowed, and the circuit was
    reported as refused when it had simply been asked the wrong way round.
    All four signatures are now tried in turn.
  - **Nothing was verified.** A call that does not throw has still not
    necessarily done anything. Every add is now checked by regenerating and
    reading the circuit's own member list back.
  - **Phasing was not carried across.** A replacement takes the phase of the
    view it is created in, not the original's, and circuits are phase-aware —
    so `AddToCircuit` refused for a reason that read as nothing to do with
    phasing. Phase Created and Phase Demolished now carry across always, like
    the workset, and are set *before* the circuit is touched.
- **A failed circuit transfer no longer deletes the original.** Previously the
  original was deleted regardless and the circuit went with it. Now, if any
  circuit will not take the replacement, that element's sub-transaction is
  rolled back and the original is left exactly as it was, with the panel and
  circuit number named in the report.
- Circuit discovery gained a fourth route: a document-wide scan that asks each
  circuit for its own members, cached per run. It does not depend on
  `MEPModel` handing anything back, and it catches what the other three miss.

### Changed

- **The window can be stretched.** Eight edge and corner grips, because a
  `WindowStyle=None` + `AllowsTransparency` window gets no usable resize border
  from WPF. Minimum 960 x 660; the lists and the parameter box grow with it.
- **Manual picking is two single clicks.** One element of the family to find,
  then — immediately, with no Finish and no Enter between them — one element of
  the family to replace it with. `PickObject`, not `PickObjects`.
- **Manual picking now identifies types, not instances.** Both modes resolve to
  a source type and a target type, and the scope decides how many get replaced,
  so one click stands for every instance of that type.
- **Scope** reads **Entire project** / **Active view** / **Current selection**,
  and applies in both modes.
- **Keep from the original** is now **Parameter values to retain**, and the box
  is taller — default window height 782 to 880, with a floor under the list.
- Clear resets both picks rather than a list of picked ids.

## 1.0.1

### Fixed

- **Level association picked the level above.** `nearest_level` chose by
  absolute distance, so a ceiling light at 2700mm with levels at 0 and 3600
  landed on the level above (gap 900) rather than the one it sits on (gap
  2700). Replacements are now associated with the nearest level *at or below*
  the insertion point.
- **A face-based original inherited its host's level.** The old fallback read
  the level off `instance.Host`, and a light hosted to Level 1's ceiling
  reports Level 2, because that is the level the ceiling was drawn on. The
  level-below rule is now tried first and gets both cases right.
- **The level is now forced onto every writable level parameter** after
  placement, not just the one the placement overload happened to take. A family
  carrying both Level and Schedule Level was leaving the second pointing
  somewhere else, which showed up in schedules rather than in the view. The
  insertion point is re-corrected afterwards, since setting a level moves the
  element.

### Added

- **Placement card** in the window with **Associate with the nearest level
  below the insertion point**, ticked by default. Untick to keep whatever level
  the original is associated with — for a family deliberately dimensioned down
  from the level above on a negative offset.
- Preview and the run report both list the levels the replacements land on and
  how many go to each, so a wrong association is visible before and after.

## 1.0.0

First release.

### Added

- Modeless window on the **RevoBIM PY** tab, **Management** panel. Revit stays
  fully navigable and selectable while the tool is open; every read of and
  write to the document goes through a single `ExternalEvent`.
- **Browse mode** — category, then family, then type, on both sides, each with
  its own keyword search box. Instance counts sit against every type.
- **Manual selection mode** — pick the elements to replace straight out of the
  model, and pick the replacement family by clicking any placed instance of it.
- **Scope** — entire model, active view, or current selection.
- **Parameters to retain** — the writable instance parameters of the original,
  each with its value and whether the replacement carries the same parameter.
  All / None / Shared only, plus a keyword search. Shared and project
  parameters are ticked by default; built-in geometry and host parameters are
  kept out of the list entirely.
- **Electrical state chip** — green **Retain circuits** where the two families
  agree on system type, poles and voltage; red **Review electrical data** where
  they do not, listing exactly which of the three disagrees. An acknowledgement
  tick is required before a red state will run.
- **Circuit transfer** — each replacement joins its circuits *before* the
  original is deleted, so a circuit is never emptied and never destroyed.
- Replacement lands on the original's insertion point, turned to read the same
  way round: facing direction for a wall-hosted original, hand direction for a
  ceiling-hosted one, instance transform as the last resort.
- **Adjust window** after the run — 0 / 90 / 180 / 270 or a custom angle, plus
  a Z offset in millimetres, applied to the whole set of replacements at once
  and re-applied live until it looks right.
- **Preview** reports what the run will do without touching the model.
- Workset and pinned state carry across from each original to its replacement.
- `import_check.py` bench check, `icon.png`, `bundle.yaml`, this changelog and
  a reference markdown doc ship with the tool.

### Notes on the build

- Runs unchanged on Revit 2024 through 2027. No `System.Uri`, no bare
  `.IntegerValue`, no f-strings, no `print` statements.
- `Theme.xaml` holds every brush and control template; the layouts reference it
  with `DynamicResource` only, because it is merged after `XamlReader` has
  parsed them.
- The whole run is one transaction with a per-element sub-transaction, so a
  single awkward element cannot take the run down and one undo puts everything
  back.
