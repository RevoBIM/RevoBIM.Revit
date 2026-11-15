# Clash Analysis - changelog

## 1.4.0 - 2026-11-13
- Clash Tests tab re-laid out: Saved clash tests is a strip across the
  top, Set A + Set B below it. Both collapse and expand from their header
  with the same drawer slide as the window (chevron turns with it); the
  open / shut state is remembered. When Set A + Set B is shut the options
  move up under the tests.
- Models lists show 7 models and have a drag bar under them to make them
  taller or shorter; dragging one sizes both and the height is remembered.
  Clicking anywhere on a model's row ticks it, and ticking a linked model
  lists that model's categories.
- The category tree lists Revit's own model categories only: no line
  styles such as <Room Separation>, no .dwg / .dxf (or other import)
  categories, no sub-categories, imports or model lines.
- Run on defaults to Current view (listed first). Saved tests keep their
  own choice.
- Clash Groups: Isolate Clash Sphere. On a floor plan of the group's level
  it turns on Temporary View Properties, shows the clash family's category
  (and Detail Items for the plan symbol), temporarily isolates the group's
  spheres (or the highlighted ones) and zooms to fit. From any other view
  a floor plan picker opens (search, "only plans on <level>" on by
  default, or use the current view). Reset view ends Temporary Hide /
  Isolate and Temporary View Properties.
- Clash Groups: View in 3D. Pick a 3D view (defaults to your own default
  3D view, then {3D}); it opens, its section box is set round the spheres
  (1 m clear all round) and it zooms to fit. With no 3D view in the model
  one is made.
- Clash Groups: review status. First column of "Clash families in the
  group" is a blob: red not reviewed, amber reviewed, green OK. Zoom to
  family turns red amber (never takes green away). Highlight any number
  and use the Not reviewed / Reviewed / OK buttons or right-click to set
  them all. Kept per project; included in Copy report.
- Zoom to family shrinks the window to the taskbar afterwards so the
  clash can be seen.

## 1.3.0 - 2026-11-13
- One group per floor: clash families are grouped by their level, and
  each group is named CLASH-YYYY_MM_DD_HH-MM_<level code>-<clash test>,
  e.g. CLASH-2026_11_13_12-49_L02-Tray vs Steel. Level codes come from
  the level name (L02 - First Floor -> L02, Level 2 -> L02, Level -1 ->
  B01, Ground Floor -> GF, Basement 2 -> B2, 3rd Floor -> L03, Roof -> RF,
  otherwise the initials) and are worked out from every level in the
  model so a floor always gets the same code. Groups placed before 1.3.0
  still read.
- Clash Groups list: new Level and "Last run started" columns. Last run
  started is when the group's clash test last began running.
- A test's last run time is now when the run started, not when it ended
  (test list, Results line, Clash Groups).
- Placing skips any clash that already has the chosen family within
  100 mm of it, and never puts two on one spot in the same run. The
  status line counts what was skipped.
- Bench: the version-bump breakage no longer depends on the version
  number (it had stopped applying at 1.2.0).

## 1.2.0 - 2026-11-13
- Run on: each clash test can run on the whole project or the current
  view (saved with the test, shown in the test list). A current-view run
  reads the host and linked models only as the view shows them (Revit
  2024+ link-in-view filtering; falls back to the view's crop / section
  box if Revit refuses).
- Clash family level: a test run on a floor plan puts its clash families
  on that plan's level; otherwise each goes on the closest level at or
  below the clash. The level is read back after placing.
- Create Clash schedule (Results tab, next to the clash family): creates
  or updates BIM_Clash Analysis Schedule - Generic Models filtered to the
  picked clash family (hidden Family field), columns Level and Comments,
  sorted by Level with a header per level (then by Comments), Comments
  column sized to the longest comment. Opens the schedule when done.
- Worksets: when the model has no Z_BIM_Clash_Sphere workset it is offered
  at the top of both workset lists, bold and green, "Create Workset?".
  "Custom workset..." below it asks for a name. Either is created when the
  command runs, then the clash families go on it. A name the model
  already has is used as is, and the suggestion is hidden once it exists.

## 1.1.0 - 2026-11-13
- Rename saved clash tests: a Rename button under the list, F2, or
  right-click a test. Right-click also offers Duplicate, Run this test and
  Delete (Del works on the list too), and selects the test under the pointer
  first.
- A rename is checked before anything is written: not blank, not another
  test's name (any case), and not a name that would save over another
  test's file. The new file is written before the old one is removed;
  results already run this session follow the new name. CLASH- groups
  already placed keep their name.
- Prompts can carry a text box (Enter accepts).

## 1.0.0 - 2026-11-13
- First release. Coordination panel, single pushbutton, modeless.
- Clash Tests tab: saved clash tests per project (new, duplicate, delete,
  run, run all). Set A and Set B each choose models (host and any loaded
  link instance) and categories > families from a searchable, collapsible
  tick tree with element counts.
- Detection by solid intersection (default) or bounding box; overlaps
  thinner than a set size (default 5 mm) count as touching; elements
  connected to each other or nested in each other can be skipped.
  Grid-hashed bounding box pre-filter, solids cached per run, Revit
  boolean failures fall back to the boxes and are reported as such.
- Results tab: clash count, clashing pairs table (filters the clash list),
  clash list with search, zoom to clash with optional 3D section box.
- Place clash families: dropdown of level / work plane based model
  families, placed on the clash point then moved so the family's centroid
  sits on the intersection centroid; Comments written as
  "<A>-vs-<B>" (Family : Type, Family, Category or Category - Family);
  grouped as CLASH-YYYY_MM_DD_HH-MM-<clash test name>; workset applied to
  the families and the group.
- Clash Groups tab: every CLASH- group in the model; click one for a
  quantity report by comment and a list of its clash families; copy the
  report for Excel; select / zoom in Revit; assign workset; delete group.
- House chrome: Revit dark / light palettes with Auto following the canvas
  theme, shrink-to-taskbar drawer on every window, full screen, resize grips.
