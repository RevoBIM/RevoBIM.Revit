# View Manager - changelog

## 1.11.0
- **The template list opens on Floor Plan templates** (`DEFAULT_TEMPLATE_FAMILY`
  at the top of `script.py`). Falls back to All where a project has none.
- **Add room tags**, ticked by default, in the footer on the Create Views tab.
  After the views commit - so their crops are real - every room each new
  plan's cut plane passes through, inside its crop, gets a tag. Rooms come
  from this model and every loaded link (`LinkElementId` with the point taken
  into host coordinates). Worked out geometrically rather than by asking which
  rooms the view shows, since MEP templates often hide Rooms while showing room
  tags. Cut heights from `ProjectElevation`. Unplaced, unbounded and redundant
  rooms are skipped. Ten views per transaction, inside the same undo group as
  the views, and a tagging failure never takes the views with it. Only views
  whose chunk committed are tagged. Dependent views are not tagged - they show
  their parent's tags.
- **Dark / Light / Auto chip** top right on all three windows, cycling
  Auto -> Dark -> Light, saved as `follow` / `dark` / `light`. Auto follows
  Revit: `UIThemeManager.CurrentCanvasTheme` (reached by `getattr`, tested
  `is not None` - `UITheme.Dark` is 0), then the canvas background's
  luminance, then `CurrentTheme`, and re-checks whenever a window comes to the
  front. The swap is live on every open window - ticks, scroll and selection
  survive it.
- **One shared resource block** loaded into all three windows, every colour a
  `DynamicResource` key. Dark is the 1.10.0 Revit palette; light is new, with
  darkened accents (`#1B72BE`, `#B96A12`, `#2E8546`) rather than the dark ones
  reused. Both carry exactly the same 37 keys.
- **New `OnBlue` key**: the bench found white on the dark-mode blue at 2.97:1,
  under the 3:1 floor - the ticked checkbox and the blue Copy button. Navy on
  the light blue in dark, white on the darker blue in light; 4.5:1 or better.
- **Settings has four tabs, with icons**: Level abbreviations, Template
  abbreviations, Scope box abbreviations, Tag settings. The three abbreviation
  tabs share one layout and one class.
  - **Levels** - set by hand beats the rule (F01 -> L01, Roof -> LRF).
  - **Scope boxes** - dependents are now named `DEP_<host>_<scope box abbr>`;
    anything not set uses the scope box's own name, so nothing changes until
    one is set. Set abbreviations show in orange on the Dependent Views list.
  - Level and scope box abbreviations are **kept per project**, in
    `%APPDATA%\RevoBIM\view_manager_projects\<central file name>\`, so
    every local copy of one central shares them. Template abbreviations stay
    global.
  - **Tag settings** - the room tag (`<Project default>` first, then every
    loaded room tag type as Family : Type), whether Add room tags starts
    ticked, and whether to tag rooms in linked models. A chosen tag not loaded
    in this project falls back to the project default, then the first loaded,
    and says so.
- **Fixed: fast create left linked models hidden.** 1.5.0 handed the worksets
  back after the template but not the categories it had hidden - RVT links,
  coordination models, point clouds, raster images. Where a template did not
  control model categories, those stayed hidden in the finished view. They
  are now unhidden after the template; a template that controls them refuses
  the write and its answer stands.
- The status line says when room tags are on, the finish message counts them,
  and the debug report gains a `tags` timing bucket and a per-view tally.
- **Bench**: both palettes' keys match, the baked defaults match the dark
  table, no literal colour and no brush read with `StaticResource` in any of
  the three layouts, 21 text / surface pairs in each palette, the room
  geometry (cut on the floor, above, below, on the crop edge, no crop), and
  7 deliberate breakages, all caught.

## 1.10.0
- **Dark theme matched to Revit's own dark UI**, sampled pixel by pixel from
  the Project Browser rather than judged by eye:

  | Role | Was | Now | Revit source |
  | --- | --- | --- | --- |
  | Tab strip, progress track | `#22262C` | `#1B1F24` | toolbar strip |
  | Title bar, footer | `#2B2B2B` | `#212932` | title bar |
  | Text boxes, scroll tracks, tick boxes | `#21252B` | `#2D3441` | search box |
  | Window body, list wells | `#262A31` / `#21252B` | `#3C4454` | tree |
  | Text | `#DCDCDC` | `#EBF5FF` | row text |
  | Muted text | `#8B929C` | `#9DA4B2` | icon grey |
  | Disabled text | `#7E848C` | `#7B8290` | search placeholder |
  | Tick box hover edge | `#9AA2AD` | `#A4ADBC` | tree connector |

  Derived where Revit has no equivalent: cards `#343C4A` (midway between
  the input and the surface), borders `#4E586A` (Revit's own input edge
  `#38404D` disappears on `#3C4454`), buttons `#465063` / hover `#535E73`,
  scroll thumb `#5A6476` / `#6C778A`, tick box edge `#8790A0`.
- **Text boxes now have their own `Input` brush.** They shared `Sunken` with
  the list wells; Revit draws its search box darker than its tree, so they
  are now two tones.
- **Accents unchanged** - blue, orange, green and red carry meaning here (the
  green Create button, red Apply, orange abbreviations, green expand arrow,
  blue shift-selection).
- Applied to all three windows. Every text / surface pair checked for WCAG
  contrast: body text 7.3:1 to 13.3:1, muted text 3.9:1 or better, the
  orange abbreviations 3.5:1 on the list.

## 1.9.0
- **Shrink to the bottom of the screen** on every window in the tool - the
  main window, Settings and the Debug report. The button sits top right,
  before close. Pressing it slides the window down like a drawer: `Top` and
  `Height` eased together on a 15 ms `DispatcherTimer` over 280 ms
  (1-(1-p)^3), landing as just the header bar floating 8 px above the bottom
  of the working area of whichever screen it is on. Then everything below the
  header is collapsed and resize is switched off.
- **The button turns into a green up arrow** while shrunk. That, or a
  double-click on the bar, slides it back to where it was - Left included, so
  a bar dragged across the screen still comes back home. The bar can be
  dragged while shrunk; a double-click that lands on a header button is left
  to the button.
- **Dialogs and their owner travel together.** Shrinking Settings or the
  Debug report shrinks the main window first, so it doesn't stay over Revit,
  and the dialog's bar stacks above the main one. Shrinking the main window
  takes any open dialogs with it. Expanding either brings both back; closing
  a shrunk dialog brings the main window back.
- Bars stack in slots with a 4 px gap and a freed slot is reused, so several
  bars never overlap.
- Pressing the ribbon button again while the window is shrunk expands it.
- The glyphs are `DataTemplate`s swapped by a `Tag` trigger, never a `Path`
  as `Content` - one element cannot sit in two windows. Same mechanics as the
  Pro Sheets `Chrome`, so the behaviour is identical across RevoBIM tools.
- A frame that throws mid-slide lands the window at its end state rather than
  leaving it half way.
- **Bench**: 42 drawer checks against a stand-in window (instant timer, a
  clock that moves 20 ms per read), and 8 deliberate breakages - no hiding,
  no green arrow, MinHeight not restored, owner not lifted, bars sharing a
  slot, Left not restored, double-click stealing button clicks, a throwing
  frame stranding the window. All 8 caught.

## 1.8.1
- **Fixed the load failure in 1.8.0** - `ImportError: Cannot import name
  TextTrimming`. `TextTrimming` lives in `System.Windows`, not
  `System.Windows.Controls`; it was imported from the wrong namespace and the
  tool would not open at all.
- **Fixed pre-selection, which had never worked.** `read_preselection` read
  `uidoc`, a name that went away in 1.3.0 when the tool went modeless. The call
  sat inside a try/except, so it did not crash - it returned nothing, and views
  picked in the Project Browser were silently ignored. `uidoc` is defined at
  module level again.
- **Two new bench checks** so neither class of bug can ship again: every
  imported .NET name is checked against the namespace it actually lives in,
  with the common traps listed explicitly, and the script is scanned with
  pyflakes for any name used but never imported or defined. The second is what
  found the `uidoc` bug - a try/except turns an undefined name into a feature
  that quietly does nothing.

## 1.8.0
- **New keyword abbreviations**: Fire Alarm -> FA, EXT Lighting -> LTG-EXT,
  Lighting -> LTG, HVAC Pipework -> HTG. Lighting is no longer swept into PWR.
- **The order of the keyword table is now the rule, and is commented as such.**
  First match wins, so anything specific has to sit above the general term it
  contains: `ext lighting` above `lighting`, and `hvac pipework` above the
  plain `hvac` that belongs to ventilation. Bench-checked against both
  collisions - `HVAC Pipework` gives HTG while `HVAC Ducting` still gives VENT.
- **Settings button in the header.** Pick any view template from the list and
  type its abbreviation. What is set by hand **beats the keyword table**, since
  the reason to set one is that the keywords got it wrong. **Use keyword** puts
  a single template back on the table; **Clear all** empties the lot.
- The settings list shows every template with its abbreviation as it stands and
  where it came from - orange and marked "set by hand" for an override, plain
  for a keyword match, muted and marked "no keyword" for a consonant fallback.
  Searchable by template name or by abbreviation.
- Abbreviations are saved to `%APPDATA%\RevoBIM\view_manager_abbreviations.txt`
  as `name<TAB>abbreviation`, **global rather than per project**, because an
  abbreviation is a house standard. The file is plain UTF-8 and hand-editable.
  Unicode round-trip is bench-checked.
- An abbreviation typed in Settings is run through the same `sanitise` as a
  view name, so a character Revit forbids cannot reach a view name through it.
- Saving reports failure to the status line rather than failing quietly, and
  the Create Views list relabels itself the moment an abbreviation changes.

## 1.7.0
- **Both first columns sort and group by view family and type.** Host Views on
  the Dependent Views tab and View Templates on the Create Views tab now break
  under a muted `FAMILY - TYPE` heading each time the pair changes, ordered
  family, then type, then name.
- **A filter dropdown beside each search box** - All families and types, then
  each family, then each type indented beneath its family. Picking a family
  narrows to every type in it; picking a type narrows to that one.
- `ComboBox` and `ComboBoxItem` both carry full control templates. Per the
  theme reference, a stock ComboBox ignores `Background` on its popup and its
  items and falls back to OS chrome - it would have shown as a white box in a
  dark window.
- The search box now matches on family and type as well as the name, so typing
  `section` or `201_GA` finds rows without touching the dropdown.
- Family and type are read **once** in `read_model`, not per keystroke -
  `GetTypeId` plus `GetElement` across 74 views on every character would be felt.
- Group headings are added to the panel but **not** to the row set, so
  shift-click selection indices stay contiguous across a group boundary and a
  run can span several groups. Bench-checked.
- Ticks survive filtering and grouping, because the tick state is keyed on the
  element id rather than on what is on screen.

## 1.6.0
- **Shift-click selects a run of rows**, highlighted blue, in all four tick
  lists on both tabs. Ticking any row in the run applies that tick to the
  whole run. Ctrl-click adds or removes a single row. A plain click inside
  the run keeps it; a plain click outside starts again from there.
  Shift-click itself only selects - it never ticks - so a run can be picked
  without changing anything.
- Each row is now a `CheckBox` inside a `Border`, because the tick box's own
  `Background` is the box, so a row needs a surface of its own to paint. The
  border is explicitly `Transparent` or it is not hit testable at all.
- **Views selected in the Project Browser before the tool opens** arrive on
  the Dependent Views tab with the host list **isolated to those views and
  every one of them ticked**. Where nothing picked was a view itself, the
  owning views are used instead - someone who picked a viewport meant its
  sheet.
- **Show all views** on the orange isolate chip drops the isolation and
  **leaves every tick exactly as it is**, so the selection can be added to
  rather than restarted.
- All / None now act on whatever the list is currently showing, so they
  compose with the search box and the isolation rather than ignoring them.
- The isolated set is pruned on Refresh, so a view deleted in Revit while the
  window is open cannot hold the list down to nothing.

## 1.5.0
- **Fast create.** The 1.4.0 timings showed 6m 28s of a 6m 29s run inside
  `apply_scope_box` - 97 seconds a view, with everything else in
  milliseconds. Assigning a scope box makes Revit work out the crop against
  everything the view can currently see, and a brand new view can see the whole
  model including every linked IFC. Fast create hides **RVT links,
  coordination models, point clouds, raster images and every user workset** in
  the new view *before* the scope box goes on, so the crop is worked out
  against nothing. The view template is applied straight afterwards and sets
  the visibility that actually belongs on the view, then the worksets are
  handed back to the global setting - a flag each, with the crop already
  established, so nothing is recomputed.
- **A prompt asks before each run** - Fast create / Create normally / Cancel -
  with "do not ask again this session". It is drawn **inside the window**
  rather than as a window of its own, because a modal child would disable
  Revit and undo the point of going modeless.
- **The scope box is no longer read back inside the loop.** `Parameter.AsElementId`
  straight after a `Set` forces a regeneration: fine once, ruinous per view.
  The crop flags are only written where they are not already set.
- The debug report gains **quieten** and **restore** timing buckets and states
  whether fast mode was on, so the next report says plainly whether this
  worked.
- Worksharing names are imported on their own inside a try/except, so a
  release that spells one differently cannot take the tool down.

## 1.4.0
- **Views are created in batches of 25 per transaction, not one each.** A
  `Transaction.Commit()` is a full document regeneration, so one transaction
  per view meant one regeneration per view - 268 views was 268 regenerations.
  It is now 11. A chunk Revit refuses is rolled back and **replayed one view
  at a time**, so the bad one is named and only that one is lost; the batch is
  not. `CHUNK_SIZE` is at the top of `script.py`.
- **The scope box is no longer written twice per view.** It was being set, then
  the template applied, then set again unconditionally - a parameter write and
  a crop recompute per view for nothing. It is now only re-asserted where
  `scope_box_holds` shows the template actually took it away.
- **Revit's dialogs are suppressed for the run** - `DialogBoxShowing` hooked
  once and switched with a flag, since unsubscribing an IronPython bound method
  is not reliable - and each transaction carries an `IFailuresPreprocessor`
  that deletes warnings, with `SetDelayedMiniWarnings` on. A run that stops to
  ask a question per view is a run that looks hung.
- **Progress strip across the footer** with a live count, painted between
  chunks only - never with a transaction open, which is what can leave a
  commit with nothing in it. The window is made hit-test-invisible while a run
  is on, because pumping the dispatcher to paint also pumps mouse and key
  input.
- **The debug report now carries per-stage timings** - create, name, scope box,
  template, commit - plus the average per view and the transaction count. If it
  is still slow, that report says which stage is eating it rather than leaving
  it to guesswork.
- The finish message reports how long the run took.

## 1.3.0
- **Fixed the Revit 2026 create failure.** `ViewPlan.Create` returns the
  `ViewPlan` itself, not an `ElementId`, so passing it to `doc.GetElement`
  threw `TypeError: expected ElementId, got ViewPlan` on every view. Both
  create calls now go through `as_element`, which takes an id or an element,
  so the tool works whichever a release hands back.
- **Fixed level abbreviation on project-coded level names.** The rule took the
  *first* number in the name, so `41AM_F01` through `41AM_F07B` all abbreviated
  to `L41` and collided. An explicit floor token now wins: `41AM_F01` -> L01,
  `41AM_F02A` -> L02A, `41AM_F08_ROF` -> L08. `Level -1` -> LB1 (a hyphen can
  now only read as a sign, never as a separator). Falls back to the last number
  rather than the first.
- **The window is modeless**, so Revit stays fully navigable and editable while
  it is open. `__persistentengine__` is on, the window is owned to Revit's main
  window handle, and the window, the `ExternalEvent` and its handler are parked
  in module-level variables. Every write goes out through that event and
  nothing ever waits on it. Pressing the button again brings the open window
  forward instead of opening a second one.
- **Refresh chip in the header, F5 too.** Modeless means the model can move on
  under the window; Refresh re-reads it and drops any pick that has gone. The
  lists also re-read themselves after a run.
- Elements are re-resolved by id at write time rather than held from when the
  window opened, so a deleted level is reported instead of throwing.
- **Create Views is now the first tab**, and both tabs carry an icon - a page
  with a plus in green, and a parent view feeding two dependents in orange.
- The debug window opens with `Show`, not `ShowDialog`: a modal child would
  have disabled Revit's own window and undone the point of going modeless.
- Template keywords widened - HVAC, ducting and ductwork now reach VENT, which
  is what `B_BS_01_ME_HVAC Ducting-DOC` should have matched. Also cable
  tray/trunking -> CONT, soil/waste -> DRN, lighting -> PWR, cctv -> SEC,
  dhw/mcws -> DOM.
- The no-keyword fallback takes the longest real word in the name rather than
  squeezing the consonants out of the whole string, so that template would read
  `DUCT` rather than `BBSM`.
- Where several ViewFamilyTypes suit a template, they are sorted by name and
  the first taken, so the same one is picked every run; the debug report lists
  the alternatives.

## 1.2.0
- **Dark scrollbars.** `ScrollBar`, its `Thumb` and `RepeatButton` parts, and
  `ScrollViewer` itself now carry full control templates, so no part of a
  scrollbar falls back to OS chrome. Arrow buttons are removed rather than
  themed - they were the part rendering as a light lozenge. Tick boxes and
  radio buttons are retemplated for the same reason, and `TextBox` now has a
  template so its inner scrollbar is themed too.
- **Debug tickbox** in the footer. With it ticked a run records the Revit
  build, the IronPython version, the document, every element picked with its
  id, and for each view the stage it reached and the exact exception - then
  opens a report window with Copy and Save to file. The report is pre-written
  as a prompt ready to paste into the chat. It also appears automatically,
  behind a "Debug report" button, whenever anything fails even with Debug off.
- **Create Views hardened for Revit 2024-2027.** The view is now named before
  the template is applied (a template can lock the crop and scope box
  parameters but never the name), the scope box is re-asserted after the
  template is applied, and each of the three steps reports separately instead
  of one bare failure. `apply_template` checks `IsValidViewTemplate` first and
  reads the id back; `apply_scope_box` reports read-only parameters by name.
- `set_name` now tries three routes - direct, `Element.Name.SetValue` and the
  `VIEW_NAME` parameter - and reports which ones refused.
- `ElementId` construction goes through `make_eid`, which prefers the Int64
  overload used from Revit 2026.
- Templates that are not plan templates are marked in the list before you pick
  them, rather than only being reported after the run.
- A failure before the window opens now writes
  `%APPDATA%\RevoBIM\logs\view_manager_last_error.txt` instead of vanishing.

## 1.1.1
- Renamed the tool to **View Manager**; button folder is now
  `ViewManager.pushbutton` and the header reads RevoBIM View Manager on both
  tabs. No functional change.

## 1.1.0
- Added a tabbed shell; the window now carries two view tools.
- New **Create Views** tab: view templates, levels and a single scope box.
  Creates one plan view per template x level, applies the template and the
  scope box, and names it `<Template abbreviation>_<Level abbreviation>`.
- Create Views button is green only when at least one template, at least one
  level and exactly one scope box are picked; greyed out otherwise.
- Template abbreviations table `TEMPLATE_ABBREVIATIONS` and level aliases
  `LEVEL_ALIASES` at the top of `script.py`.
- Replaced `ElementId.IntegerValue` with an `eid_value` helper (removed in
  Revit 2026), and renaming now goes through a confirm-by-read-back helper.

## 1.0.0
- First release. Dependent views from selected host views x selected scope
  boxes, named `DEP_<Host View>_<Scope Box>`.
- Keyword search on both lists, All/None per column, live counts.
- One TransactionGroup per run with a sub-transaction per view for fault
  isolation. Silent finish - status line only, no pyRevit output.
